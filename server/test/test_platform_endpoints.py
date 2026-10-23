"""Owned-domain advertisement through the real HTTP handler, without a phone."""
import contextlib
import copy
import http.client
import io
import json
import os
from pathlib import Path
import threading
import unittest
from unittest import mock

from server.platform import endpoints, local_stack


HOST = "rpc.halcyon.example.test"
ORIGIN = f"https://{HOST}"
ENV_KEYS = ("HALCYON_PLATFORM_ORIGIN", "HALCYON_NOTIFY_ORIGIN",
            "HALCYON_PLATFORM_CERT", "HALCYON_PLATFORM_KEY")


class EndpointTests(unittest.TestCase):
    def test_unconfigured_keeps_legacy_contract(self):
        self.assertIsNone(endpoints.from_environment({}))

    def test_default_ports_and_notify_transport(self):
        value = endpoints.from_environment({"HALCYON_PLATFORM_ORIGIN": ORIGIN + ":443/"})
        self.assertEqual(value.rpc_origin, ORIGIN)
        self.assertEqual(value.bootstrap_authority, HOST + ":443")
        self.assertEqual(value.notify_origin, "ws://" + HOST)

    def test_explicit_ports_are_independent(self):
        value = endpoints.from_environment({"HALCYON_PLATFORM_ORIGIN": ORIGIN + ":9443",
                                           "HALCYON_NOTIFY_ORIGIN": f"ws://{HOST}:9080"})
        self.assertEqual(value.bootstrap_authority, HOST + ":9443")
        self.assertEqual(value.notify_origin, f"ws://{HOST}:9080")

    def test_rejects_unsafe_or_non_origin_configuration(self):
        for value in ("", "http://example.test", "https://u:p@example.test", ORIGIN + "/rpc",
                      ORIGIN + "?x=1", ORIGIN + "#x", ORIGIN + "?", ORIGIN + "#",
                      ORIGIN + ":", ORIGIN + ":0", ORIGIN + ":65536", ORIGIN + ":bad",
                      "https://127.0.0.1", "https://[::1]", "https://bad_host.test",
                      "https://-bad.test", "https://bad..test", " " + ORIGIN,
                      ORIGIN + "\r\nInjected: value", "https://a%2eb.test"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                endpoints.from_environment({"HALCYON_PLATFORM_ORIGIN": value})
        with self.assertRaises(ValueError):
            endpoints.from_environment({"HALCYON_NOTIFY_ORIGIN": "ws://example.test"})
        with self.assertRaises(ValueError):
            endpoints.from_environment({"HALCYON_PLATFORM_ORIGIN": ORIGIN,
                                        "HALCYON_NOTIFY_ORIGIN": "https://example.test"})

    def test_rewrite_preserves_paths_shapes_tokens_and_input(self):
        value = endpoints.from_environment({"HALCYON_PLATFORM_ORIGIN": ORIGIN})
        source = [{"returnValue": {"startSessionUrl": "https://old.test/startsession?q=1",
                    "platformUrl": "https://old.test/platform", "notifyUrl": "ws://old.test/notify",
                    "notifyFallbackUrl": "", "sessionToken": "https://old.test/not-a-route",
                    "supportUrls": ["https://old.test/help"], "nested": {"state": "menus"}}}]
        before = copy.deepcopy(source)
        out = value.rewrite(source)[0]["returnValue"]
        self.assertEqual(out["startSessionUrl"], ORIGIN + "/startsession?q=1")
        self.assertEqual(out["platformUrl"], ORIGIN + "/platform")
        self.assertEqual(out["notifyUrl"], f"ws://{HOST}/notify")
        self.assertEqual(out["notifyFallbackUrl"], "")
        self.assertEqual(out["sessionToken"], source[0]["returnValue"]["sessionToken"])
        self.assertEqual(out["supportUrls"], source[0]["returnValue"]["supportUrls"])
        self.assertEqual(source, before)

    def test_bad_scripted_url_is_not_silently_served(self):
        value = endpoints.from_environment({"HALCYON_PLATFORM_ORIGIN": ORIGIN})
        for item in ("file:///private", "https://u@old.test", "https://old.test\n", 123):
            with self.subTest(item=item), self.assertRaises(ValueError):
                value.rewrite({"returnValue": {"startSessionUrl": item}})


class HandlerEndpointTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {}).start()
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["HALCYON_PLATFORM_ORIGIN"] = ORIGIN
        root = Path(__file__).resolve().parents[2]
        self.answers = json.loads((root / "Config/answers.example.json").read_text(encoding="utf-8"))
        self.answers["_fsm_auto"] = False
        mock.patch.object(local_stack, "_answers", return_value=self.answers).start()
        mock.patch.object(local_stack, "_log").start()
        mock.patch.object(local_stack, "_log_rpc").start()
        mock.patch.object(local_stack, "fsm_on_rpc").start()
        self.server = local_stack.ThreadingHTTPServer(("127.0.0.1", 0), local_stack.Handler)
        self.server.device_tag = "phone-endpoint-test"
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            conn.request(method, path, json.dumps(payload) if payload is not None else None,
                         {"Host": "untrusted-header.invalid", "Content-Type": "application/json"})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def rpc(self, method):
        return self.request("POST", f"/JSONRpc/{method}", {"method": method, "params": ["hwid"]})

    def test_bootstrap_uses_configured_authority_not_host_header(self):
        code, body = self.request("GET", "/kindred/live/147219-status-redirect")
        self.assertEqual((code, body), (200, f"{HOST}:443".encode()))

    def test_fresh_guest_uses_owned_origin_and_keeps_identity(self):
        code, body = self.rpc("createGuestPlayer")
        self.assertEqual(code, 200)
        value = json.loads(body)["returnValue"]
        self.assertEqual(value["startSessionUrl"], ORIGIN)
        self.assertEqual(local_stack._token_player_id(value["playerUUID"]),
                         local_stack._device_player_id("phone-endpoint-test"))

    def test_session_and_guest_routes_all_follow_own_domain(self):
        before = copy.deepcopy(self.answers)
        for method in ("startSessionForPlayer", "getPlayerForGuestAccount"):
            with self.subTest(method=method):
                code, body = self.rpc(method)
                self.assertEqual(code, 200)
                self.assertTrue(body.endswith(b"}"))
                value = json.loads(body)["returnValue"]
                for key in endpoints.RPC_FIELDS:
                    self.assertEqual(value[key], ORIGIN)
                for key in endpoints.NOTIFY_FIELDS:
                    self.assertEqual(value[key], f"ws://{HOST}/notify")
        self.assertEqual(self.answers, before)

    def test_json_value_stream_is_preserved(self):
        self.answers["stream"] = [{"returnValue": {"platformUrl": "https://old.test/a"}}, {"code": 0}]
        code, body = self.rpc("stream")
        self.assertEqual(code, 200)
        decoder = json.JSONDecoder()
        first, end = decoder.raw_decode(body.decode())
        second, final = decoder.raw_decode(body.decode(), end)
        self.assertEqual(first["returnValue"]["platformUrl"], ORIGIN + "/a")
        self.assertEqual(second, {"code": 0})
        self.assertEqual(final, len(body))

    def test_disabled_mode_preserves_existing_bootstrap_and_guest(self):
        del os.environ["HALCYON_PLATFORM_ORIGIN"]
        self.assertEqual(self.request("GET", "/kindred/live/147219-status-redirect"),
                         (200, b"rpc.kindred-live.net:8443"))
        code, body = self.rpc("createGuestPlayer")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["returnValue"]["startSessionUrl"], "https://rpc.kindred-live.net")

    def test_invalid_runtime_settings_and_scripted_urls_fail_closed(self):
        os.environ["HALCYON_PLATFORM_ORIGIN"] = "http://invalid.test"
        self.assertEqual(self.request("GET", "/kindred/live/147219-status-redirect")[0], 503)
        os.environ["HALCYON_PLATFORM_ORIGIN"] = ORIGIN
        self.answers["startSessionForPlayer"]["returnValue"]["startSessionUrl"] = "file:///private"
        self.assertEqual(self.rpc("startSessionForPlayer")[0], 503)


class EndpointTLSStartupTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {})
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.endpoints = endpoints.from_environment({"HALCYON_PLATFORM_ORIGIN": ORIGIN})

    def test_owned_domain_requires_tls_without_changing_legacy_fallback(self):
        with mock.patch.object(local_stack, "build_tls_context", return_value=None):
            self.assertIsNone(local_stack.configured_tls_context({}, None))
            with self.assertRaises(ValueError):
                local_stack.configured_tls_context({}, self.endpoints)
        with self.assertRaises(ValueError):
            local_stack.configured_tls_context({"_tls443": False}, self.endpoints)

    def test_explicit_pair_is_passed_to_existing_tls_builder(self):
        os.environ["HALCYON_PLATFORM_CERT"] = "owned-fullchain.pem"
        os.environ["HALCYON_PLATFORM_KEY"] = "owned-key.pem"
        with mock.patch.object(local_stack, "build_tls_context") as builder:
            result = local_stack.configured_tls_context({}, self.endpoints)
            self.assertIs(result, builder.return_value)
            builder.assert_called_once_with("owned-fullchain.pem", "owned-key.pem")

    def test_partial_or_empty_pair_is_rejected(self):
        for settings in ({"HALCYON_PLATFORM_CERT": "one.pem"},
                         {"HALCYON_PLATFORM_KEY": "key.pem"},
                         {"HALCYON_PLATFORM_CERT": "", "HALCYON_PLATFORM_KEY": ""}):
            with self.subTest(settings=settings), mock.patch.dict(os.environ, settings), self.assertRaises(ValueError):
                local_stack.configured_tls_context({}, self.endpoints)

    def test_invalid_origin_starts_no_listener(self):
        os.environ["HALCYON_PLATFORM_ORIGIN"] = "http://invalid.test"
        with mock.patch.object(local_stack.gateway, "Gateway") as gateway, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            local_stack.main([])
        gateway.assert_not_called()

    def test_missing_certificate_starts_no_listener(self):
        os.environ["HALCYON_PLATFORM_ORIGIN"] = ORIGIN
        with mock.patch.object(local_stack, "build_tls_context", return_value=None), \
                mock.patch.object(local_stack, "_answers", return_value={}), \
                mock.patch.object(local_stack.os, "makedirs"), \
                mock.patch.object(local_stack.os.path, "exists", return_value=True), \
                mock.patch.object(local_stack.gateway, "Gateway") as gateway, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            local_stack.main([])
        gateway.assert_not_called()


if __name__ == "__main__":
    unittest.main()

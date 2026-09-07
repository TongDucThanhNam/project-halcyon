"""Unit tests for the per-device guest identity layer (local_stack).

2026-09-07: two cloned LDPlayer installs presented the SAME fixed identity
at the match gateway because the stack served one static playerUUID. The
identity layer now mints a playerUUID per hardware id (createGuestPlayer)
and rewrites every identity-bearing answer to the player_id inside the
client's own session token.

2026-09-07 duo live follow-up: cloned images SHARE the hwid (8/8 identical
createGuestPlayer calls) and the match-join token each client presented was
byte-identical to the canned static sessionToken from answers.json — so the
hwid mint never reached the match and the client-pid rewrite skipped every
default-presenting client. Per-listener device tags (HALCYON_DEVICE_PORTS)
now key the identity; every answer on a tagged listener is rewritten to it.
"""
import base64
import json
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.platform import local_stack

DEFAULT = local_stack.DEFAULT_PLAYER_UUID


def _claims(token):
    body = token.split(".")[1]
    padded = body + "=" * (-len(body) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


class TestGuestIdentity(unittest.TestCase):

    def test_mint_token_carries_player_id(self):
        pid = "11111111-2222-4333-8444-555555555555"
        tok = local_stack._mint_token(pid)
        self.assertEqual(local_stack._token_player_id(tok), pid)

    def test_create_guest_player_deterministic_per_hwid(self):
        a1 = local_stack._create_guest_player(["kindred", "en", "HW_ID_ANDROID", "devA"])
        a2 = local_stack._create_guest_player(["kindred", "en", "HW_ID_ANDROID", "devA"])
        b = local_stack._create_guest_player(["kindred", "en", "HW_ID_ANDROID", "devB"])
        pid_a = local_stack._token_player_id(a1["returnValue"]["playerUUID"])
        pid_a2 = local_stack._token_player_id(a2["returnValue"]["playerUUID"])
        pid_b = local_stack._token_player_id(b["returnValue"]["playerUUID"])
        self.assertEqual(pid_a, pid_a2)          # same device → same identity
        self.assertNotEqual(pid_a, pid_b)        # different device → different
        self.assertNotEqual(pid_a, DEFAULT)      # never collides with the default
        self.assertEqual(a1["returnValue"]["startSessionUrl"],
                         "https://rpc.kindred-live.net")

    def test_client_player_id_extraction(self):
        tok = local_stack._mint_token("aaaaaaaa-1111-4222-8333-444455556666")
        self.assertEqual(local_stack._client_player_id(["", tok]),
                         "aaaaaaaa-1111-4222-8333-444455556666")
        self.assertIsNone(local_stack._client_player_id(["", "not-a-jwt"]))
        self.assertIsNone(local_stack._client_player_id(None))

    def test_rewrite_swaps_tokens_and_bare_uuids(self):
        pid = "bbbbbbbb-1111-4222-8333-444455556666"
        answer = {
            "code": 0,
            "returnValue": {
                "playerUUID": DEFAULT,
                "sessionToken": local_stack._mint_token(DEFAULT),
                "friends": [],
                "note": "owner " + DEFAULT,
            },
        }
        out = local_stack._rewrite_identity(answer, pid)
        self.assertEqual(out["returnValue"]["playerUUID"], pid)
        self.assertEqual(local_stack._token_player_id(out["returnValue"]["sessionToken"]), pid)
        self.assertEqual(out["returnValue"]["note"], "owner " + pid)
        self.assertEqual(out["returnValue"]["friends"], [])
        # the input answer is not mutated
        self.assertEqual(answer["returnValue"]["playerUUID"], DEFAULT)

    def test_rewrite_is_noop_for_default_identity(self):
        answer = {"code": 0, "returnValue": {"playerUUID": DEFAULT,
                                             "sessionToken": local_stack._mint_token(DEFAULT)}}
        out = local_stack._rewrite_identity(answer, DEFAULT)
        self.assertEqual(out, answer)

    def test_identity_path_keeps_nonidentity_answers_intact(self):
        """update/manifest answers contain no JWTs — rewrite leaves them so."""
        answer = {"code": 0, "returnValue": {"state": "menus"}}
        out = local_stack._rewrite_identity(answer, "cccccccc-1111-4222-8333-444455556666")
        self.assertEqual(out, answer)


class TestListenerDeviceTags(unittest.TestCase):
    """The tagged-listener layer that actually separates cloned devices."""

    def setUp(self):
        self._old_mint = os.environ.pop("HALCYON_MINT_IDENTITY", None)

    def tearDown(self):
        if self._old_mint is not None:
            os.environ["HALCYON_MINT_IDENTITY"] = self._old_mint

    def test_untagged_listener_keeps_legacy_flow(self):
        self.assertIsNone(local_stack._device_player_id(""))
        self.assertIsNone(local_stack._device_player_id(None))

    def test_device_tag_mints_stable_distinct_identity(self):
        a = local_stack._device_player_id("emulator-5554")
        b = local_stack._device_player_id("emulator-5556")
        self.assertEqual(a, local_stack._device_player_id("emulator-5554"))
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, DEFAULT)
        # the identity is exactly the documented derivation
        self.assertEqual(a, str(uuid.uuid5(
            local_stack._IDENTITY_NAMESPACE, "device:emulator-5554")))

    def test_create_guest_player_on_tagged_listener_ignores_shared_hwid(self):
        """The cloned-image case: same hwid on both devices, different tags —
        each minted token must carry ITS listener's identity."""
        shared_hwid = "0a-2837-400e-995c-f38b50164747"
        tok_a = local_stack._create_guest_player(["x", shared_hwid], "emulator-5554")
        tok_b = local_stack._create_guest_player(["x", shared_hwid], "emulator-5556")
        pid_a = _claims(tok_a["returnValue"]["playerUUID"])["player_id"]
        pid_b = _claims(tok_b["returnValue"]["playerUUID"])["player_id"]
        self.assertEqual(pid_a, local_stack._device_player_id("emulator-5554"))
        self.assertEqual(pid_b, local_stack._device_player_id("emulator-5556"))
        self.assertNotEqual(pid_a, pid_b)

    def test_tagged_listener_overrides_static_ab_probe(self):
        """HALCYON_MINT_IDENTITY=0 serves the shared static token on legacy
        listeners; on a tagged device listener that would re-collide the
        devices — the tag must win."""
        os.environ["HALCYON_MINT_IDENTITY"] = "0"
        tok = local_stack._create_guest_player(["x", "hwid"], "emulator-5556")
        pid = _claims(tok["returnValue"]["playerUUID"])["player_id"]
        self.assertEqual(pid, local_stack._device_player_id("emulator-5556"))

    def test_rewrite_gives_static_session_answer_a_device_identity(self):
        """The measured collision path: the client adopts the canned static
        sessionToken verbatim. On a tagged listener that answer is rewritten
        so the adopted token — and therefore the match-join PLAYER_UUID —
        carries the device identity."""
        answer = local_stack._answers()["startSessionForPlayer"]
        device_pid = local_stack._device_player_id("emulator-5556")
        served = local_stack._rewrite_identity(
            answer, device_pid, None)["returnValue"]["sessionToken"]
        self.assertEqual(_claims(served)["player_id"], device_pid)

    def test_match_server_decodes_rewritten_token_to_device_identity(self):
        """Platform→match contract: identity_from_token (the match-side
        canonicalizer) resolves the rewritten static token to the device
        player id — the second device gets its own roster slot."""
        from server.match_server import identity_from_token
        answer = local_stack._answers()["startSessionForPlayer"]
        device_pid = local_stack._device_player_id("emulator-5556")
        token = local_stack._rewrite_identity(
            answer, device_pid, None)["returnValue"]["sessionToken"]
        self.assertEqual(identity_from_token(token), device_pid)
        # the pre-fix static token decoded to the SHARED default — the bug
        self.assertEqual(identity_from_token(
            answer["returnValue"]["sessionToken"]), DEFAULT)


class TestTruncatedJoinFrame(unittest.TestCase):
    """The client's PLAYER_UUID frame truncates the token to its first
    63 bytes (measured live 09:29: `token[:63]` + nulls — the stored join
    uuid was 63 chars, 2 parts). The 'd' claim first in the payload puts a
    per-identity tag inside that window; identity_from_token must separate
    devices from the truncated form alone."""

    FRAME_WINDOW = 63

    def test_mint_leads_with_device_tag_claim(self):
        pid = "11111111-2222-4333-8444-555555555555"
        claims = _claims(local_stack._mint_token(pid))
        self.assertEqual(claims["d"], uuid.uuid5(
            local_stack._IDENTITY_NAMESPACE, f"device-tag:{pid}").hex[:12])

    def test_truncated_frames_separate_devices(self):
        from server.match_server import identity_from_token
        tok_a = local_stack._mint_token("aaaaaaaa-1111-4222-8333-444455556666")
        tok_b = local_stack._mint_token("bbbbbbbb-1111-4222-8333-444455556666")
        static = local_stack._answers()["startSessionForPlayer"][
            "returnValue"]["sessionToken"]
        id_a = identity_from_token(tok_a[:self.FRAME_WINDOW])
        id_b = identity_from_token(tok_b[:self.FRAME_WINDOW])
        self.assertTrue(id_a.startswith("devtag:"))
        self.assertNotEqual(id_a, id_b)
        # reconnect stability: same device, same truncated identity
        self.assertEqual(id_a, identity_from_token(tok_a[:self.FRAME_WINDOW]))
        # the static token carries no 'd' claim → raw-prefix fallback
        # (distinct from the device-tagged identities)
        self.assertNotEqual(id_a, identity_from_token(static[:self.FRAME_WINDOW]))

    def test_truncation_point_leaves_the_tag_intact(self):
        """63 bytes must be enough for `{"d":"<12 hex>"` after the header:
        36 (header) + 1 (dot) + 26 base64 chars = 19 payload bytes and the
        tag needs 6 + 12 + 1."""
        tok = local_stack._mint_token("cccccccc-1111-4222-8333-444455556666")
        fragment = tok.split(".")[1][:26]
        import base64
        decoded = base64.urlsafe_b64decode(
            fragment + "=" * (-len(fragment) % 4)).decode()
        self.assertGreaterEqual(len(decoded), 19)
        self.assertTrue(decoded.startswith('{"d":"'))


if __name__ == "__main__":
    unittest.main()

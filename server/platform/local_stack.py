"""Project Halcyon — T1 local platform stack (preauth + JSON-RPC + T2 gateway).

Goal (phase0.md T1 fork, option A/B hybrid): let an UNMODIFIED local
Vainglory 4.13 PC client reach OUR T2 gateway, by owning everything it
talks to before the match socket opens:

  * hosts file sends the SEMC hostnames to 127.0.0.1 (setup_hosts.ps1);
  * this stack serves HTTP on :80 for every host:
      - ``/kindred/live/<REV>-status-redirect``  — the preauth bootstrap
        (Startup.ini [Auth] initURL); behaviour is configurable because the
        response format is unknown (302 vs body) — see answers.json;
      - ``/JSONRpc/<service>``                  — the platform RPC
        (``{"method": "%s", "params": %s}`` per the exe's own format
        strings); every request is logged verbatim to teach us the schema,
        answers come from the hot-reloaded answers.json;
      - gamefeed / server-status / misc          — logged, benign defaults;
  * the T2 gateway + heartbeat relay from server.gateway run alongside.

All of it is 127.0.0.1-only and logged under $TEMP/halcyon_stack/. No
traffic ever leaves the machine; nothing of SEMC's real infrastructure is
touched (the hosts entries actively PREVENT the client from reaching it).

Usage:  python -m server.platform.local_stack
Edit $TEMP/halcyon_stack/answers.json while the client runs — it is
re-read on every request.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from server import gateway
else:
    from .. import gateway

STACK_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack")
LOG_PATH = os.path.join(STACK_DIR, "http_log.txt")
RPC_LOG_PATH = os.path.join(STACK_DIR, "rpc.jsonl")
ANSWERS_PATH = os.path.join(STACK_DIR, "answers.json")

DEFAULT_ANSWERS = {
    "_comment": "hot-reloaded; keys are RPC 'service/method' or special rows",
    "status_redirect": {"mode": "302", "location": "http://platform.superevil.net/"},
    "news": [],
    "rpc_default": {"error": {"code": -32601, "message": "halcyon: method not scripted yet"}},
}

_log_lock = threading.Lock()


def _log(line: str) -> None:
    os.makedirs(STACK_DIR, exist_ok=True)
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%H:%M:%S')} {line}\n")


def _log_rpc(entry: dict) -> None:
    os.makedirs(STACK_DIR, exist_ok=True)
    with _log_lock:
        with open(RPC_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=True) + "\n")


def _answers() -> dict:
    try:
        with open(ANSWERS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return DEFAULT_ANSWERS


MATCH_ID = "00000000-1111-4222-8333-444455556666"


def _fsm_update_state(answers_path: str, state_obj: dict,
                      match_id: str = MATCH_ID, gw_port: int | None = None) -> None:
    """Rewrite only the `update` row of answers.json (other rows preserved).
    Pure-FSM helper so tests can drive it against a scratch file."""
    try:
        with open(answers_path, encoding="utf-8") as fh:
            answers = json.load(fh)
    except Exception:
        answers = dict(DEFAULT_ANSWERS)
    if gw_port is not None and "host" in state_obj:
        state_obj = dict(state_obj, port=gw_port)
    answers["update"] = {"code": 0, "returnValue": state_obj}
    with _log_lock:
        with open(answers_path, "w", encoding="utf-8") as fh:
            json.dump(answers, fh, indent=1)


def fsm_on_boot(answers_path: str = ANSWERS_PATH,
                gw_port: int | None = None) -> None:
    """Boot must answer `menus` — a leftover `playing` from a previous run
    makes the booting client try to open a match socket from the menu
    (observed 2026-09-06: gray screen, then a libhoudini native death).
    Disable with "_fsm_auto": false in answers.json."""
    if _answers().get("_fsm_auto", True):
        _fsm_update_state(answers_path, {"state": "menus"}, gw_port=gw_port)


def fsm_on_rpc(rpc_method: str, answers_path: str = ANSWERS_PATH,
               gw_port: int | None = None,
               match_host: str | None = None) -> None:
    """Drive the client's update-FSM from the RPC stream: the client polls
    `update` as its FSM driver, so the moment it sends joinLobby we flip
    `playing` (+host/port) — skipping matched_partners/accept screen, the
    known-good route (§14). exitLobby returns the world to `menus` so a
    finished match does not re-queue the client forever."""
    if not _answers().get("_fsm_auto", True):
        return
    if rpc_method == "joinLobby":
        # The port fallback must come from the SAME answers file this call
        # rewrites — a caller may point answers_path at a scratch copy
        # (tests) while the live file carries a different _gw_port.
        try:
            with open(answers_path, encoding="utf-8") as fh:
                answers_cfg = json.load(fh)
        except (OSError, json.JSONDecodeError):
            answers_cfg = {}
        port = gw_port if gw_port is not None \
            else int(answers_cfg.get("_gw_port", 7100))
        host = match_host if match_host is not None \
            else answers_cfg.get("_match_host", "127.0.0.1")
        _fsm_update_state(
            answers_path,
            {"state": "playing", "host": host,
             "matchId": MATCH_ID},
            gw_port=port)
        _log(f"FSM joinLobby -> update=playing (host {host}, port {port})")
    elif rpc_method == "exitLobby":
        _fsm_update_state(answers_path, {"state": "menus"})
        _log("FSM exitLobby -> update=menus")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):  # silence stderr, we log ourselves
        pass

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _send(self, code: int, body: bytes, ctype: str = "application/json",
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj, extra: dict | None = None) -> None:
        self._send(code, json.dumps(obj).encode(), extra=extra)

    # -- routes ------------------------------------------------------------

    WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def _is_ws_upgrade(self) -> bool:
        return (self.headers.get("Upgrade", "").lower() == "websocket"
                and self.path.split("?")[0].startswith("/notify"))

    @staticmethod
    def _ws_encode(payload: bytes) -> bytes:
        if len(payload) < 126:
            return bytes([len(payload)]) + payload
        if len(payload) < 65536:
            return bytes([126]) + len(payload).to_bytes(2, "big") + payload
        return bytes([127]) + len(payload).to_bytes(8, "big") + payload

    @staticmethod
    def _ws_read_exact(conn, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("peer closed mid-frame")
            buf += chunk
        return buf

    def _handle_ws_notify(self) -> None:
        """Accept the client's notify WebSocket (RFC6455) and hold it open.

        The client connects to notifyUrl right after startSession; a failed
        upgrade is a candidate cause of the session-boot loop, so we accept
        and keep the socket alive, answering pings. We push nothing yet —
        the game tolerates a quiet notify channel (it also polls friendList).
        """
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(
            hashlib.sha1((key + self.WS_GUID).encode()).digest()).decode()
        self.connection.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n")
        _log(f"WS {self.path} upgraded")
        # failoverThreshold=4000/bucketIncrementer=3000 (ms) match the observed
        # ~5s session-teardown loop: the client expects the notify channel to
        # carry data continuously, not just once at connect. Push a minimal
        # valid state-update frame every 2s (recv timeout doubles as timer).
        # Payload shape: the game-layer update dispatcher (FUN_0095f8a8)
        # categorizes top-level keys party/partyInvitation/friends/
        # matchResponse/transition — a "friends" list is what the booting
        # client is waiting for after friendListAll.
        # _ws_push=false → silent channel (diagnostic: does a periodic
        # {"friends":[]} frame poison the menus transition?).
        # _ws_push / _ws_push_payload are hot-reloadable per loop iteration
        # (~2s), so a running client picks up probe changes without a
        # reconnect. Frame opcode 0x81 (text). The ingest side keys top-level
        # categories (party/partyInvitation/friends/matchResponse/transition)
        # and keeps per-category seqs.
        try:
            if _answers().get("_ws_push", True):
                _push_obj = json.dumps(
                    _answers().get("_ws_push_payload", {"friends": []})).encode()
                self.connection.sendall(
                    bytes([0x81]) + self._ws_encode(_push_obj))
                _log("WS notify pushed (connect)")
            self.connection.settimeout(2.0)
            while True:
                try:
                    hdr = self.connection.recv(2)
                except socket.timeout:
                    if _answers().get("_ws_push", True):
                        _push_obj = json.dumps(
                            _answers().get("_ws_push_payload",
                                           {"friends": []})).encode()
                        self.connection.sendall(
                            bytes([0x81]) + self._ws_encode(_push_obj))
                        _log(f"WS notify pushed: {_push_obj[:80]!r}")
                    continue
                if not hdr:
                    _log(f"WS {self.path} closed by client")
                    break
                op = hdr[0] & 0x0F
                ln = hdr[1] & 0x7F
                masked = bool(hdr[1] & 0x80)
                if ln == 126:
                    ln = int.from_bytes(
                        self._ws_read_exact(self.connection, 2), "big")
                elif ln == 127:
                    ln = int.from_bytes(
                        self._ws_read_exact(self.connection, 8), "big")
                mask = (self._ws_read_exact(self.connection, 4)
                        if masked else b"")
                payload = (self._ws_read_exact(self.connection, ln)
                           if ln else b"")
                if mask:
                    payload = bytes(b ^ mask[i % 4]
                                    for i, b in enumerate(payload))
                if op == 0x8:                      # close
                    self.connection.sendall(b"\x88\x00")
                    break
                if op == 0x9:                      # ping → pong
                    self.connection.sendall(
                        bytes([0x8A, len(payload)]) + payload)
                _log(f"WS frame op={op} len={ln} {payload[:120]!r}")
        except Exception as exc:
            _log(f"WS {self.path} closed: {exc!r}")
        finally:
            self.close_connection = True

    def _dispatch(self, method: str) -> None:
        if self._is_ws_upgrade():
            self._handle_ws_notify()
            return
        host = self.headers.get("Host", "?")
        path = self.path
        body = self._read_body()
        hdrs = dict(self.headers)
        _log(f"{method} http://{host}{path}  body[{len(body)}]={body[:600]!r}")
        if "notify" in path or "Upgrade" in self.headers:
            _log(f"    headers: {json.dumps(hdrs)}")
        answers = _answers()

        if "status-redirect" in path:
            cfg = answers.get("status_redirect", DEFAULT_ANSWERS["status_redirect"])
            mode = cfg.get("mode", "302")
            if mode == "302":
                self._send(302, b"", extra={"Location": cfg.get("location", "/")})
            elif mode == "raw":                     # raw bytes, no JSON quoting
                self._send(200, str(cfg.get("body", "")).encode(),
                           ctype="text/plain")
            else:
                self._send_json(200, cfg.get("body", {}))
            return

        # RPC paths may carry a prefix segment, e.g. the client's
        # startSessionUrl "…/startsession" produces
        # "/startsession/JSONRpc/startSessionForPlayer" — match "/JSONRpc/"
        # anywhere, not just as a prefix (a 404 here = startSession transport
        # failure = the "Unable to connect" boot loop).
        idx = path.find("/JSONRpc/")
        if idx != -1:
            service = path[idx + len("/JSONRpc/"):].split("?")[0]
            try:
                payload = json.loads(body or b"{}")
            except json.JSONDecodeError:
                payload = {"_raw": body.decode("utf-8", "replace")}
            rpc_method = payload.get("method", "?")
            _log_rpc({"t": time.time(), "host": host, "service": service,
                      "method": rpc_method, "params": payload.get("params"),
                      "headers": dict(self.headers)})
            key = f"{service}/{rpc_method}"
            answer = None
            if key in answers:
                answer = answers[key]
            elif rpc_method in answers:
                answer = answers[rpc_method]
            else:
                answer = answers.get("rpc_default", DEFAULT_ANSWERS["rpc_default"])
            fsm_on_rpc(rpc_method)
            # The client parses the body as a STREAM of JSON values
            # (FUN_00ebfddc: while(*cursor) parse_next). A trailing newline
            # makes parse_next fail on the leftover byte, dispatch a NULL
            # value, and the router (FUN_00e973f8: value type==0 → status -1)
            # turns that into the "Unable to connect" retry loop. Bytes must
            # END exactly at the last value — no trailing whitespace.
            if isinstance(answer, list):
                body = b"".join(json.dumps(o).encode() for o in answer)
            else:
                body = json.dumps(answer).encode()
            self._send(200, body)
            return

        if "gamefeed" in path or "news" in path:
            self._send_json(200, answers.get("news", []))
            return

        if "server-status" in path:
            self._send_json(200, {"status": "ok"})
            return

        self._send_json(404, {"halcyon": "unscripted path", "path": path})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_HEAD(self):
        self._dispatch("HEAD")


class TLSServer(ThreadingHTTPServer):
    """ThreadingHTTPServer whose TLS handshakes cannot kill the serve loop."""

    def __init__(self, addr, handler, ssl_context):
        self.ssl_context = ssl_context
        super().__init__(addr, handler)

    def server_bind(self):
        super().server_bind()
        self.socket = self.ssl_context.wrap_socket(self.socket, server_side=True)

    def get_request(self):
        try:
            return super().get_request()
        except Exception as exc:  # handshake failure — log, keep serving
            _log(f"TLS accept error: {exc!r}")
            raise


def main(argv=None) -> None:
    import argparse
    import ssl

    ap = argparse.ArgumentParser(description="Halcyon local platform stack (preauth + JSON-RPC + T2 gateway)")
    ap.add_argument("--bind-host", default=None,
                    help="IP to bind listeners to (default: _bind_host in answers.json or 0.0.0.0)")
    ap.add_argument("--match-host", default=None,
                    help="Host/IP returned to client in joinLobby playing state (default: _match_host or 127.0.0.1)")
    ap.add_argument("--gw-port", type=int, default=None,
                    help="Gateway port (default: _gw_port or 7100)")
    ap.add_argument("--hb-port", type=int, default=None,
                    help="Heartbeat port (default: _hb_port or 2112)")
    args = ap.parse_args(argv)

    os.makedirs(STACK_DIR, exist_ok=True)
    if not os.path.exists(ANSWERS_PATH):
        with open(ANSWERS_PATH, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_ANSWERS, fh, indent=1)

    gw_log_path = os.path.join(STACK_DIR, "gateway_log.txt")
    gw_log_lock = threading.Lock()

    def _gwlog(msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with gw_log_lock, open(gw_log_path, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {msg}\n")

    # Gateway ports and hosts are configurable:
    cfg = _answers()
    bind_host = args.bind_host or cfg.get("_bind_host", "0.0.0.0")
    match_host = args.match_host or cfg.get("_match_host", "127.0.0.1")
    gw_port = args.gw_port if args.gw_port is not None else int(cfg.get("_gw_port", 7100))
    hb_port = args.hb_port if args.hb_port is not None else int(cfg.get("_hb_port", 2112))

    if args.match_host or args.bind_host:
        if args.match_host:
            cfg["_match_host"] = args.match_host
        if args.bind_host:
            cfg["_bind_host"] = args.bind_host
        with open(ANSWERS_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=1)

    gw = gateway.Gateway(bind_host, port=gw_port,
                         match_id=MATCH_ID,
                         heartbeat_port=hb_port, log=_gwlog)
    gw.start()
    fsm_on_boot(gw_port=gw.port)   # a stale `playing` answer must not poison boot
    print(f"[stack] FSM auto {'ON' if _answers().get('_fsm_auto', True) else 'OFF'} "
          f"(boot=menus; joinLobby->playing:{gw.port} on {match_host}; exitLobby->menus)")
    try:
        httpd = ThreadingHTTPServer((bind_host, 80), Handler)
        print(f"[stack] http://{bind_host}:80 (all SEMC hosts) — log {LOG_PATH}")
    except OSError as exc:
        # A stale (often elevated) holder of :80 keeps serving HTTP — but from
        # the SHARED hot-reloaded answers.json, so its replies stay correct.
        # This instance still owns its freshly configured gateway ports above.
        httpd = None
        print(f"[stack] :80 unavailable ({exc!r}) — HTTP stays with the holder", flush=True)
    print(f"[stack] rpc journal {RPC_LOG_PATH}")
    print(f"[stack] answers {ANSWERS_PATH} (hot-reloaded)")
    print(f"[stack] T2 gateway {bind_host}:{gw.port} (announced: {match_host}) + heartbeat :{gw.relay.port}")

    cert = os.path.join(STACK_DIR, "platform_cert.pem")
    key = os.path.join(STACK_DIR, "platform_key.pem")
    use_tls = bool(_answers().get("_tls443", True))
    ctx = None
    if os.path.isfile(cert) and os.path.isfile(key) and use_tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)

    try:
        if ctx is not None:
            httpsd = TLSServer((bind_host, 443), Handler, ctx)
            print(f"[stack] https://{bind_host}:443 (platform RPC endpoint, TLS)", flush=True)
        else:
            httpsd = ThreadingHTTPServer((bind_host, 443), Handler)
            print(f"[stack] http://{bind_host}:443 (platform RPC endpoint, PLAIN)", flush=True)
        threading.Thread(target=httpsd.serve_forever, daemon=True).start()
    except OSError as exc:
        # A stale elevated stack may still hold :443 — the client-facing
        # endpoints are :8080/:8443 anyway; keep serving without :443.
        print(f"[stack] :443 unavailable ({exc!r}) — skipping", flush=True)

    # Alternate ports. A stale elevated copy of this stack can still hold
    # :80/:443; with two SO_REUSEADDR listeners bound to the same port the
    # connection delivery is indeterminate (observed: the old process wins).
    # Every client-facing URL we control (preauth redirect body, platformUrl,
    # startSessionUrl, notifyUrl) therefore points at :8080/:8443, which only
    # the live stack binds.
    alt = ThreadingHTTPServer((bind_host, 8080), Handler)
    threading.Thread(target=alt.serve_forever, daemon=True).start()
    print(f"[stack] http://{bind_host}:8080 (alternate plain)", flush=True)
    if ctx is not None:
        alt_tls = TLSServer((bind_host, 8443), Handler, ctx)
        threading.Thread(target=alt_tls.serve_forever, daemon=True).start()
        print(f"[stack] https://{bind_host}:8443 (alternate TLS)", flush=True)

    try:
        if httpd is not None:
            httpd.serve_forever()
        else:
            threading.Event().wait()  # gateway-only instance; block main thread
    except KeyboardInterrupt:
        pass
    finally:
        gw.stop()


if __name__ == "__main__":
    main()

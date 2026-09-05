"""Project Halcyon — T2 gateway (the front door, §15.1).

The real client connects to a generic endpoint and names the backend it
wants in a plaintext route request; the gateway is "the door", and the
match port is dynamic per match. Local faithful equivalent:

  1. accept a client connection, read the plaintext route-request frame
     (``[u16 134][00 05 "<backend>" + zero pad]``) and validate it;
  2. spawn a MatchServer bound to an OS-assigned dynamic port and start
     the §15.2 heartbeat relay (separate lane, shared across matches);
  3. proxy bytes both directions until either side closes — the client
     never learns the match port, exactly like production.

CLI: python -m server.gateway [--host 127.0.0.1] [--port 7100]
                              [--match-id <uuid>] [--heartbeat-port 2112]
"""
from __future__ import annotations

import os
import select
import socket
import sys
import threading

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import match_server
    import wire
else:
    from . import match_server
    from . import wire

PUMP_TIMEOUT = 1.0  # s, select cadence so stop() is responsive


class Gateway:
    def __init__(self, host="127.0.0.1", port=7100, match_id="00000000-1111-4222-8333-444455556666",
                 heartbeat_port=2112, heartbeat_interval=wire.HEARTBEAT_INTERVAL, log=print):
        self.host, self.port = host, port
        self.match_id = match_id
        self.log = log
        self.relay = match_server.HeartbeatRelay(host, heartbeat_port, heartbeat_interval)
        self.matches = []          # spawned MatchServer instances
        self.routes = []           # (backend_named, match_port) per client
        self._stop = threading.Event()
        self._listener = None

    def start(self):
        self.relay.start()
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind((self.host, self.port))
        self._listener.listen(8)
        self.port = self._listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        self.relay.stop()
        for ms in self.matches:
            ms.stop()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._listener.accept()
            except OSError:
                break
            threading.Thread(target=self._serve_client, args=(conn,), daemon=True).start()

    def _serve_client(self, conn):
        peer = conn.getpeername()
        try:
            conn.settimeout(10)
            body = wire.read_frame(conn)          # plaintext greeting (§15.1)
            if body is None:
                self.log(f"[gateway] {peer} left before route request")
                return
            backend = wire.parse_route_request(body)
        except (wire.WireError, OSError) as exc:
            self.log(f"[gateway] {peer} bad route request: {exc!r}")
            try:
                conn.close()
            except OSError:
                pass
            return
        conn.settimeout(None)

        match = match_server.MatchServer(self.host, self.match_id, port=0,
                                         log=lambda m: self.log(f"[match:{self.match_id[:8]}] {m}"))
        match.start()
        self.matches.append(match)
        self.routes.append((backend, match.port))
        self.log(f"[gateway] {peer} routed to backend {backend!r} -> match port {match.port} "
                 f"(heartbeat relay on {self.relay.port})")

        upstream = socket.create_connection((self.host, match.port), timeout=5)
        self._pump(conn, upstream)

    def _pump(self, client_sock, match_sock):
        """Forward bytes both ways until either side closes."""
        peers = {client_sock: match_sock, match_sock: client_sock}
        sockets = list(peers)
        try:
            while not self._stop.is_set():
                readable, _, exceptional = select.select(sockets, [], sockets, PUMP_TIMEOUT)
                if exceptional:
                    return
                for sock in readable:
                    try:
                        data = sock.recv(65536)
                    except OSError:
                        return
                    if not data:
                        return                    # EOF one way → tear down both
                    peers[sock].sendall(data)
        finally:
            for sock in sockets:
                try:
                    sock.close()
                except OSError:
                    pass


def _main(argv):
    import argparse
    import time

    ap = argparse.ArgumentParser(description="Project Halcyon T2 gateway")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7100)
    ap.add_argument("--match-id", default="00000000-1111-4222-8333-444455556666")
    ap.add_argument("--heartbeat-port", type=int, default=2112)
    ap.add_argument("--heartbeat-interval", type=float, default=wire.HEARTBEAT_INTERVAL)
    args = ap.parse_args(argv)

    gw = Gateway(args.host, args.port, args.match_id,
                 args.heartbeat_port, args.heartbeat_interval)
    gw.start()
    print(f"gateway: {gw.host}:{gw.port}  match_id={args.match_id}")
    print(f"heartbeat relay: {gw.relay.host}:{gw.relay.port} every {args.heartbeat_interval}s")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        gw.stop()


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))

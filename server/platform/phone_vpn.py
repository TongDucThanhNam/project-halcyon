"""Single-phone userspace WireGuard ingress, with no Internet forwarding or MITM.

Only a synthetic VPN address reaches four explicitly selected loopback services.
DNS is answered locally from a fixed allowlist. TLS bytes are relayed unchanged.
Install optional requirements-phone-vpn.txt, then use --help. No admin/root,
Windows route/firewall edit, app launch, or guest setup is performed here.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import time

from server.platform import endpoints
from server.platform.guest_setup import DNS_NAMES

ROOT = Path(__file__).resolve().parents[2]
VIRTUAL_IP = "10.77.0.1"
CLIENT_IP = "10.77.0.2"


def local_path(value: Path) -> Path:
    path = value.resolve()
    local = (ROOT / "Local").resolve()
    if path == local or not path.is_relative_to(local):
        raise ValueError("VPN keys, profiles and journals must stay beneath ignored Local/")
    return path


def port(value):
    number = int(value)
    if not 1 <= number <= 65535:
        raise ValueError("port must be in 1..65535")
    return number


@dataclass(frozen=True)
class Policy:
    hostname: str
    http_port: int = 9080
    https_port: int = 9443
    gateway_port: int = 7100
    heartbeat_port: int = 2112

    def __post_init__(self):
        parsed = endpoints.from_environment({"HALCYON_PLATFORM_ORIGIN": f"https://{self.hostname}"})
        if parsed.bootstrap_authority != f"{self.hostname}:443":
            raise ValueError("hostname must be a canonical DNS name without a port")
        for value in (self.http_port, self.https_port, self.gateway_port, self.heartbeat_port):
            port(value)
        if len({53, 80, 443, self.gateway_port, self.heartbeat_port}) != 5:
            raise ValueError("gateway/heartbeat ports must be distinct from DNS and platform ports")

    def target(self, destination):
        if destination is None or destination[0] != VIRTUAL_IP:
            return None
        mapped = {80: self.http_port, 443: self.https_port,
                  self.gateway_port: self.gateway_port, self.heartbeat_port: self.heartbeat_port}
        host_port = mapped.get(destination[1])
        return ("127.0.0.1", host_port) if host_port is not None else None

    def dns_reply(self, packet: bytes) -> bytes:
        from dnslib import A, DNSRecord, QTYPE, RCODE, RR

        if len(packet) > 4096:
            return b""
        try:
            request = DNSRecord.parse(packet)
        except Exception:
            return b""
        reply = request.reply(ra=0, aa=1)
        if request.header.qr or request.header.opcode or len(request.questions) != 1:
            reply.header.rcode = RCODE.FORMERR
        else:
            question = request.questions[0]
            name = str(question.qname).lower().rstrip(".")
            if question.qclass != 1 or name not in {*DNS_NAMES, self.hostname}:
                reply.header.rcode = RCODE.REFUSED
            elif question.qtype == QTYPE.A:
                reply.add_answer(RR(question.qname, QTYPE.A, ttl=30, rdata=A(VIRTUAL_IP)))
            elif question.qtype != QTYPE.AAAA:
                reply.header.rcode = RCODE.REFUSED
            # Known-name AAAA is NOERROR/NODATA: this pilot exposes IPv4 only.
        return reply.pack()


def initialize(state_path: Path, profile_path: Path, endpoint: str, listen_port: int):
    from mitmproxy_rs import wireguard

    state_path, profile_path = local_path(state_path), local_path(profile_path)
    address = ipaddress.ip_address(endpoint)
    if address.version != 4 or not address.is_private or address.is_unspecified or address.is_loopback:
        raise ValueError("initial phone experiment requires an explicit private LAN IPv4 endpoint")
    port(listen_port)
    if state_path == profile_path or state_path.exists() or profile_path.exists():
        raise ValueError("keys/profile already exist or share a path; never replace an existing peer implicitly")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    private = wireguard.genkey()
    peer_private = wireguard.genkey()
    state = {"schema_version": 1, "private_key": private,
             "peer_public_key": wireguard.pubkey(peer_private)}
    with state_path.open("x", encoding="utf-8") as output:
        json.dump(state, output, indent=2)
    profile = ("[Interface]\n" + f"PrivateKey = {peer_private}\nAddress = {CLIENT_IP}/32, fd77::2/128\n"
               + f"DNS = {VIRTUAL_IP}\nMTU = 1280\n\n[Peer]\nPublicKey = {wireguard.pubkey(private)}\n"
               + f"Endpoint = {endpoint}:{listen_port}\nAllowedIPs = 0.0.0.0/0, ::/0\nPersistentKeepalive = 25\n")
    with profile_path.open("x", encoding="utf-8") as output:
        output.write(profile)
    return {"state_path": str(state_path), "profile_path": str(profile_path),
            "boundary": "Single peer, full-tunnel profile; handset tunnel-loss containment is not yet qualified."}


async def read_exact(stream, length):
    result = bytearray()
    while len(result) < length:
        chunk = await asyncio.wait_for(stream.read(length - len(result)), timeout=120)
        if not chunk:
            raise EOFError
        result.extend(chunk)
    return bytes(result)


class Ingress:
    def __init__(self, policy: Policy, emit):
        self.policy = policy
        self.emit = emit

    async def tcp(self, stream):
        # WireGuard original_dst is the outer UDP listener, not the tunneled
        # application's destination. sockname identifies the inner flow.
        destination = stream.get_extra_info("sockname")
        self.emit("flow", transport="tcp", destination=destination,
                  tunnel_destination=stream.get_extra_info("original_dst"))
        target = self.policy.target(destination)
        writer = None
        tasks = []
        try:
            if destination == (VIRTUAL_IP, 53):
                while True:
                    length = int.from_bytes(await read_exact(stream, 2), "big")
                    if length > 4096:
                        return
                    response = self.policy.dns_reply(await read_exact(stream, length))
                    if not response:
                        return
                    stream.write(len(response).to_bytes(2, "big") + response)
                    await stream.drain()
                    self.emit("dns", transport="tcp", bytes=len(response))
            elif target is None:
                self.emit("denied", transport="tcp", destination=destination)
                return
            else:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(*target), timeout=5)
                self.emit("connected", transport="tcp", destination=destination, target=target)

                async def copy(source, sink):
                    while data := await asyncio.wait_for(source.read(65536), timeout=120):
                        sink.write(data)
                        await sink.drain()
                    with suppress(OSError, RuntimeError):
                        sink.write_eof()

                tasks = [asyncio.create_task(copy(stream, writer)), asyncio.create_task(copy(reader, stream))]
                await asyncio.gather(*tasks)
        except (EOFError, OSError, TimeoutError) as exc:
            self.emit("closed", transport="tcp", destination=destination, reason=type(exc).__name__)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if writer is not None:
                writer.close()
                with suppress(OSError, TimeoutError):
                    await asyncio.wait_for(writer.wait_closed(), timeout=2)
            stream.close()

    async def udp(self, stream):
        destination = stream.get_extra_info("sockname")
        self.emit("flow", transport="udp", destination=destination,
                  tunnel_destination=stream.get_extra_info("original_dst"))
        try:
            if destination != (VIRTUAL_IP, 53):
                self.emit("denied", transport="udp", destination=destination)
                return
            while packet := await asyncio.wait_for(stream.read(65535), timeout=30):
                response = self.policy.dns_reply(packet)
                if response:
                    stream.write(response)
                    await stream.drain()
                    self.emit("dns", transport="udp", bytes=len(response))
        except (OSError, TimeoutError) as exc:
            self.emit("closed", transport="udp", destination=destination, reason=type(exc).__name__)
        finally:
            stream.close()


async def serve(args):
    from mitmproxy_rs import wireguard

    policy = Policy(args.hostname, args.host_http, args.host_https, args.gateway_port, args.heartbeat_port)
    bind = ipaddress.ip_address(args.bind)
    if bind.version != 4 or not bind.is_private or bind.is_unspecified:
        raise ValueError("bind must be an explicit private LAN or loopback IPv4 address")
    state = json.loads(local_path(args.state).read_text(encoding="utf-8"))
    if state.get("schema_version") != 1:
        raise ValueError("unsupported peer state schema")
    wireguard.pubkey(state["private_key"])
    journal_path = local_path(args.journal)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("x", encoding="utf-8") as journal:
        def emit(event, **data):
            journal.write(json.dumps({"time": time.time(), "event": event, **data}) + "\n")
            journal.flush()

        ingress = Ingress(policy, emit)
        server = await wireguard.start_wireguard_server(str(bind), args.port, state["private_key"],
                                                        [state["peer_public_key"]], ingress.tcp, ingress.udp)
        emit("ready", address=server.getsockname(), hostname=policy.hostname, virtual_ip=VIRTUAL_IP,
             tls="unchanged TCP bytes; no interception", forwarding="allowlisted loopback only")
        print(json.dumps({"event": "ready", "address": server.getsockname(), "journal": str(journal_path)}), flush=True)
        try:
            await asyncio.Future()
        finally:
            server.close()
            await server.wait_closed()
            emit("stopped")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create one new peer/profile without starting a listener")
    init.add_argument("--state", type=Path, required=True)
    init.add_argument("--profile", type=Path, required=True)
    init.add_argument("--endpoint", required=True)
    init.add_argument("--port", type=port, default=51820)
    run = sub.add_parser("serve", help="Serve only the synthetic VPN address, with local DNS and TCP relays")
    run.add_argument("--state", type=Path, required=True)
    run.add_argument("--journal", type=Path, required=True)
    run.add_argument("--hostname", required=True)
    run.add_argument("--bind", required=True)
    run.add_argument("--port", type=port, default=51820)
    run.add_argument("--host-http", type=port, default=9080)
    run.add_argument("--host-https", type=port, default=9443)
    run.add_argument("--gateway-port", type=port, default=7100)
    run.add_argument("--heartbeat-port", type=port, default=2112)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(json.dumps(initialize(args.state, args.profile, args.endpoint, args.port)))
        else:
            asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

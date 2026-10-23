"""Optional userspace ingress checks; these do not claim handset containment."""
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from server.platform import phone_vpn as vpn

try:
    import dnslib
    import mitmproxy_rs
except ImportError:
    dnslib = mitmproxy_rs = None


@unittest.skipUnless(dnslib and mitmproxy_rs, "requires optional requirements-phone-vpn.txt")
class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = vpn.Policy("rpc.halcyon.example.test")

    def test_routes_only_four_ports_at_synthetic_address(self):
        for incoming, outgoing in ((80, 9080), (443, 9443), (7100, 7100), (2112, 2112)):
            self.assertEqual(self.policy.target((vpn.VIRTUAL_IP, incoming)), ("127.0.0.1", outgoing))
        for ip in ("127.0.0.1", "192.168.1.3", "8.8.8.8", "::1", "::ffff:10.77.0.1", "fd77::1"):
            self.assertIsNone(self.policy.target((ip, 443)))
        for port in (0, 22, 53, 8000, 8443, 65535):
            self.assertIsNone(self.policy.target((vpn.VIRTUAL_IP, port)))
        self.assertIsNone(self.policy.target(None))

    def test_known_dns_names_resolve_locally_unknowns_are_refused(self):
        with mock.patch("socket.getaddrinfo", side_effect=AssertionError("no upstream DNS")):
            for name in [*vpn.DNS_NAMES, self.policy.hostname]:
                question = dnslib.DNSRecord.question(name, "A")
                reply = dnslib.DNSRecord.parse(self.policy.dns_reply(question.pack()))
                self.assertEqual(reply.header.id, question.header.id)
                self.assertEqual(reply.header.ra, 0)
                self.assertEqual(str(reply.rr[0].rdata), vpn.VIRTUAL_IP)
            reply = dnslib.DNSRecord.parse(self.policy.dns_reply(dnslib.DNSRecord.question("outside.invalid").pack()))
            self.assertEqual(reply.header.rcode, dnslib.RCODE.REFUSED)
            self.assertEqual(reply.rr, [])

    def test_aaaa_is_nodata_and_other_types_refused(self):
        for qtype, expected in (("AAAA", dnslib.RCODE.NOERROR), ("TXT", dnslib.RCODE.REFUSED),
                                ("HTTPS", dnslib.RCODE.REFUSED)):
            response = dnslib.DNSRecord.parse(self.policy.dns_reply(dnslib.DNSRecord.question(self.policy.hostname, qtype).pack()))
            self.assertEqual(response.header.rcode, expected)
            self.assertEqual(response.rr, [])

    def test_malformed_or_multiple_questions_never_trigger_forwarding(self):
        self.assertEqual(self.policy.dns_reply(b"not dns"), b"")
        self.assertEqual(self.policy.dns_reply(b"x" * 4097), b"")
        question = dnslib.DNSRecord.question(self.policy.hostname)
        question.add_question(dnslib.DNSQuestion("outside.invalid"))
        response = dnslib.DNSRecord.parse(self.policy.dns_reply(question.pack()))
        self.assertEqual(response.header.rcode, dnslib.RCODE.FORMERR)

    def test_profile_routes_both_ip_families_and_preserves_existing_keys(self):
        with tempfile.TemporaryDirectory(dir=vpn.ROOT / "Local/evidence", prefix="phone-peer-test-") as folder:
            state, profile = Path(folder) / "keys.json", Path(folder) / "phone.conf"
            vpn.initialize(state, profile, "192.168.1.3", 51820)
            before = state.read_bytes(), profile.read_bytes()
            text = profile.read_text(encoding="utf-8")
            self.assertIn("AllowedIPs = 0.0.0.0/0, ::/0", text)
            self.assertIn("fd77::2/128", text)
            self.assertIn("DNS = " + vpn.VIRTUAL_IP, text)
            self.assertNotIn("ExcludedApplications", text)
            self.assertNotIn("IncludedApplications", text)
            keys = json.loads(state.read_text(encoding="utf-8"))
            self.assertIn(mitmproxy_rs.wireguard.pubkey(keys["private_key"]), text)
            with self.assertRaises(ValueError):
                vpn.initialize(state, profile, "192.168.1.3", 51820)
            self.assertEqual(before, (state.read_bytes(), profile.read_bytes()))

    def test_invalid_policy_and_storage_are_rejected(self):
        for hostname in ("host.test:443", "host.test/path", "192.168.1.3"):
            with self.subTest(hostname=hostname), self.assertRaises(ValueError):
                vpn.Policy(hostname)
        with self.assertRaises(ValueError):
            vpn.Policy("host.test", gateway_port=443)
        with self.assertRaises(ValueError):
            vpn.local_path(vpn.ROOT / "Config/leaked-key.json")


class FakeStream:
    def __init__(self, destination, chunks, outer_destination=("192.168.1.3", 51820)):
        self.destination = destination
        self.outer_destination = outer_destination
        self.chunks = list(chunks)
        self.output = bytearray()
        self.closed = False

    def get_extra_info(self, name):
        if name == "sockname":
            return self.destination
        if name == "original_dst":
            return self.outer_destination
        raise KeyError(name)

    async def read(self, size):
        await asyncio.sleep(0)
        if not self.chunks:
            return b""
        value = self.chunks.pop(0)
        if len(value) > size:
            self.chunks.insert(0, value[size:])
        return value[:size]

    def write(self, value):
        self.output.extend(value)

    async def drain(self):
        await asyncio.sleep(0)

    def write_eof(self):
        pass

    def close(self):
        self.closed = True


@unittest.skipUnless(dnslib and mitmproxy_rs, "requires optional requirements-phone-vpn.txt")
class IngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_allowlisted_outer_address_cannot_authorize_inner_flow(self):
        ingress = vpn.Ingress(vpn.Policy("host.test"), mock.Mock())
        with mock.patch.object(vpn.asyncio, "open_connection", side_effect=AssertionError("external dial")) as dial:
            for handler in (ingress.tcp, ingress.udp):
                stream = FakeStream(("203.0.113.1", 443), [b"payload"],
                                    outer_destination=(vpn.VIRTUAL_IP, 80))
                await handler(stream)
                self.assertTrue(stream.closed)
                self.assertEqual(stream.output, b"")
            dial.assert_not_called()

    async def test_unknown_ipv4_ipv6_and_datagrams_never_open_upstream(self):
        emit = mock.Mock()
        ingress = vpn.Ingress(vpn.Policy("host.test"), emit)
        with mock.patch.object(vpn.asyncio, "open_connection", side_effect=AssertionError("external dial")) as dial:
            for address in (("8.8.8.8", 53), ("2606:4700:4700::1111", 443), (vpn.VIRTUAL_IP, 8000)):
                for handler in (ingress.tcp, ingress.udp):
                    stream = FakeStream(address, [b"payload"])
                    await handler(stream)
                    self.assertTrue(stream.closed)
            dial.assert_not_called()
        self.assertEqual(sum(call.args[0] == "denied" for call in emit.call_args_list), 6)
        self.assertEqual(sum(call.args[0] == "flow" for call in emit.call_args_list), 6)

    async def test_udp_dns_and_tcp_dns_are_local(self):
        ingress = vpn.Ingress(vpn.Policy("host.test"), mock.Mock())
        question = dnslib.DNSRecord.question("host.test").pack()
        udp = FakeStream((vpn.VIRTUAL_IP, 53), [question])
        tcp = FakeStream((vpn.VIRTUAL_IP, 53), [len(question).to_bytes(2, "big")[:1],
                                               len(question).to_bytes(2, "big")[1:], question[:4], question[4:]])
        with mock.patch.object(vpn.asyncio, "open_connection", side_effect=AssertionError("no DNS forwarding")):
            await ingress.udp(udp)
            await ingress.tcp(tcp)
        self.assertEqual(tcp.output[2:], udp.output)
        self.assertEqual(int.from_bytes(tcp.output[:2], "big"), len(udp.output))
        self.assertEqual(str(dnslib.DNSRecord.parse(udp.output).rr[0].rdata), vpn.VIRTUAL_IP)

    async def test_allowed_tcp_is_byte_faithful_and_supports_half_close(self):
        received = []

        async def echo(reader, writer):
            data = await reader.read()
            received.append(data)
            writer.write(b"reply:" + data)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        try:
            ingress = vpn.Ingress(vpn.Policy("host.test", http_port=server.sockets[0].getsockname()[1]), mock.Mock())
            # Opaque binary bytes, not parsed or altered as HTTP/TLS by ingress.
            payload = b"\x16\x03\x03\x00\x08opaque\x00\xff"
            stream = FakeStream((vpn.VIRTUAL_IP, 80), [payload[:3], payload[3:]])
            await asyncio.wait_for(ingress.tcp(stream), timeout=5)
            self.assertEqual(received, [payload])
            self.assertEqual(stream.output, b"reply:" + payload)
            self.assertTrue(stream.closed)
        finally:
            server.close()
            await server.wait_closed()

    async def test_native_userspace_listener_starts_without_drivers(self):
        from mitmproxy_rs import wireguard
        server = await wireguard.start_wireguard_server("127.0.0.1", 0, wireguard.genkey(),
            [wireguard.pubkey(wireguard.genkey())], mock.AsyncMock(), mock.AsyncMock())
        try:
            self.assertEqual(server.getsockname()[0], "127.0.0.1")
            self.assertGreater(server.getsockname()[1], 0)
        finally:
            server.close()
            await server.wait_closed()


if __name__ == "__main__":
    unittest.main()

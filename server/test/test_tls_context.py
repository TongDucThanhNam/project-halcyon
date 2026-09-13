"""TLS context compatibility for the local stack's listeners.

Measured (main-review probe + local reproduction): Python's own default
context cipher list excludes ECDHE-RSA-AES128-SHA, which is the suite the
4.13 CE client completes TLS1.2 with; OpenSSL's DEFAULT list at the NORMAL
security level 2 includes it while modern peers keep TLS1.3 AEAD. These
tests pin that exact contract — the legacy suite negotiates, a modern peer
negotiates TLS1.3, the context stays at security level 2, and a missing
certificate yields no context at all (no silent fallback that could not
serve this client). Uses a locally generated throwaway certificate.
"""
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from server.platform import local_stack
    from server.platform import mkcert as stack_mkcert
except ImportError:                                   # pragma: no cover
    local_stack = None

try:
    from Crypto.PublicKey import RSA                  # noqa: F401
    HAVE_CRYPTO = True
except ImportError:                                   # pragma: no cover
    HAVE_CRYPTO = False


def _write_temp_cert(directory: Path):
    key = RSA.generate(2048)
    cert_der = stack_mkcert.build_cert(key, ["localhost"], "halcyon-test")
    cert_pem = directory / "cert.pem"
    key_pem = directory / "key.pem"
    cert_pem.write_bytes(stack_mkcert.pem("CERTIFICATE", cert_der))
    key_pem.write_bytes(key.export_key(format="PEM"))
    return cert_pem, key_pem


def _negotiate(ctx, port, *, client_ciphers, max_version=None, timeout=5.0):
    """One bounded client handshake against a loopback listener serving ctx."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    real_port = listener.getsockname()[1]
    accepted = {}

    def serve():
        try:
            conn, _ = listener.accept()
            conn.settimeout(timeout)
            tls_conn = ctx.wrap_socket(conn, server_side=True)
            accepted["cipher"] = tls_conn.cipher()[0]
            accepted["version"] = tls_conn.version()
            tls_conn.sendall(b"ok")
            tls_conn.close()
        except Exception as exc:                      # noqa: BLE001
            accepted["error"] = repr(exc)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    client = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client.check_hostname = False
    client.verify_mode = ssl.CERT_NONE
    if max_version is not None:
        client.maximum_version = max_version
    if client_ciphers:
        client.set_ciphers(client_ciphers)
    error = None
    try:
        with socket.create_connection(("127.0.0.1", real_port),
                                      timeout=timeout) as sock:
            with client.wrap_socket(sock, server_hostname="localhost") as ts:
                client_result = (ts.version(), ts.cipher()[0])
                ts.recv(2)
    except Exception as exc:                          # noqa: BLE001
        client_result = None
        error = repr(exc)
    thread.join(timeout=timeout)
    listener.close()
    return client_result, accepted, error


@unittest.skipUnless(local_stack is not None and HAVE_CRYPTO,
                     "platform stack or pycryptodome unavailable")
class TestTlsContext(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="halcyon-tls-test-"))

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_missing_certificate_returns_none(self):
        self.assertIsNone(local_stack.build_tls_context(
            self.base / "absent.pem", self.base / "absent-key.pem"))

    def test_context_keeps_normal_security_level(self):
        cert, key = _write_temp_cert(self.base)
        ctx = local_stack.build_tls_context(str(cert), str(key))
        self.assertIsNotNone(ctx)
        self.assertEqual(float(ctx.security_level), 2.0,
                         "the compatibility list must keep the normal "
                         "OpenSSL security level")

    def test_legacy_ce_suite_negotiates(self):
        cert, key = _write_temp_cert(self.base)
        ctx = local_stack.build_tls_context(str(cert), str(key))
        client_result, accepted, error = _negotiate(
            ctx, 0, client_ciphers="ECDHE-RSA-AES128-SHA",
            max_version=ssl.TLSVersion.TLSv1_2)
        self.assertIsNone(error, "the CE client's legacy suite must complete")
        self.assertEqual(client_result[0], "TLSv1.2")
        self.assertEqual(client_result[1], "ECDHE-RSA-AES128-SHA")

    def test_modern_peer_negotiates_tls13_aead(self):
        cert, key = _write_temp_cert(self.base)
        ctx = local_stack.build_tls_context(str(cert), str(key))
        client_result, accepted, error = _negotiate(ctx, 0, client_ciphers=None)
        self.assertIsNone(error, "a modern unrestricted peer must complete")
        self.assertEqual(client_result[0], "TLSv1.3")
        self.assertIn("AES_256_GCM", client_result[1])


import shutil  # noqa: E402  (kept late to avoid shadowing in helpers above)

if __name__ == "__main__":
    unittest.main()

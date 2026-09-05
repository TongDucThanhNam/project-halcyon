"""Project Halcyon — self-signed platform cert generator (T1, pure stdlib+pycryptodome).

Builds one self-signed RSA-2048 cert covering every hostname the local
platform stack serves (SAN), CA:TRUE so Windows accepts it in the Root
store, writes PEM key/cert for Python's ssl module into $TEMP/halcyon_stack
(private key never enters the repo), plus a .cer for Import-Certificate.

Usage:
  python -m server.platform.mkcert            # writes PEMs to $TEMP
  then (admin): Import-Certificate -FilePath <cer> -CertStoreLocation `
                Cert:\\LocalMachine\\Root
"""
from __future__ import annotations

import base64
import os
import sys

from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5

STACK_DIR = os.path.join(os.environ.get("TEMP", "."), "halcyon_stack")

DNS_NAMES = [
    "platform.superevil.net",
    "platform.superevilmegacorp.net",
    "rpc.kindred-live.net",
    "preauth.superevil.net",
    "preauth.superevilmegacorp.net",
    "gamefeeds.superevilmegacorp.net",
    "my.superevilmegacorp.net",
]

OID_SHA256_RSA = bytes.fromhex("2a864886f70d01010b")   # 1.2.840.113549.1.1.11
OID_RSA = bytes.fromhex("2a864886f70d010101")          # 1.2.840.113549.1.1.1
OID_CN = bytes.fromhex("550403")                       # 2.5.4.3
OID_BASIC_CONSTRAINTS = bytes.fromhex("551d13")        # 2.5.29.19
OID_SAN = bytes.fromhex("551d11")                      # 2.5.29.17


# ---- minimal DER encoder --------------------------------------------------

def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def tlv(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _len(len(body)) + body


def integer(n: int) -> bytes:
    body = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big")
    return tlv(0x02, body)


def oid(der: bytes) -> bytes:
    return tlv(0x06, der)


def sequence(*parts: bytes) -> bytes:
    return tlv(0x30, b"".join(parts))


def set_of(*parts: bytes) -> bytes:
    return tlv(0x31, b"".join(parts))


def utf8(text: str) -> bytes:
    return tlv(0x0C, text.encode())


def ia5(text: str) -> bytes:
    return tlv(0x16, text.encode("ascii"))


def utctime(text: str) -> bytes:
    return tlv(0x17, text.encode("ascii"))


def bit_string(data: bytes, unused: int = 0) -> bytes:
    return tlv(0x03, bytes([unused]) + data)


def octet_string(data: bytes) -> bytes:
    return tlv(0x04, data)


def boolean(value: bool) -> bytes:
    return tlv(0x01, b"\xff" if value else b"\x00")


def explicit(tag_no: int, content: bytes) -> bytes:
    return tlv(0xA0 | tag_no, content)


def ctx_prim(tag_no: int, content: bytes) -> bytes:
    return tlv(0x80 | tag_no, content)


# ---- certificate assembly --------------------------------------------------

def build_cert(key: RSA.RsaKey, names: list[str], cn: str) -> bytes:
    sigalg = sequence(oid(OID_SHA256_RSA), tlv(0x05, b""))
    name = sequence(set_of(sequence(oid(OID_CN), utf8(cn))))
    spki = key.publickey().export_key(format="DER")   # SubjectPublicKeyInfo

    san_general_names = b"".join(ctx_prim(2, n.encode("ascii")) for n in names)  # dNSName = raw IA5
    extensions = sequence(
        sequence(oid(OID_BASIC_CONSTRAINTS), boolean(True),
                 octet_string(sequence(boolean(True)))),            # CA:TRUE
        sequence(oid(OID_SAN), octet_string(sequence(san_general_names))),
    )

    tbs = sequence(
        explicit(0, integer(2)),          # v3
        integer(int.from_bytes(os.urandom(8), "big") | 1),
        sigalg,
        name,                             # issuer == subject (self-signed)
        sequence(utctime("260101000000Z"), utctime("420101000000Z")),
        name,
        spki,
        explicit(3, extensions),
    )
    signature = PKCS1_v1_5.new(key).sign(SHA256.new(tbs))
    return sequence(tbs, sigalg, bit_string(signature))


def pem(tag: str, der: bytes) -> bytes:
    body = base64.encodebytes(der).replace(b"\r\n", b"\n")
    return b"".join([f"-----BEGIN {tag}-----\n".encode(), body,
                     f"-----END {tag}-----\n".encode()])


def main() -> None:
    os.makedirs(STACK_DIR, exist_ok=True)
    key = RSA.generate(2048)
    cert_der = build_cert(key, DNS_NAMES, "Halcyon Local Platform CA")
    with open(os.path.join(STACK_DIR, "platform_key.pem"), "wb") as fh:
        fh.write(key.export_key(format="PEM"))
    with open(os.path.join(STACK_DIR, "platform_cert.pem"), "wb") as fh:
        fh.write(pem("CERTIFICATE", cert_der))
    with open(os.path.join(STACK_DIR, "platform.cer"), "wb") as fh:
        fh.write(cert_der)
    print(f"cert for {len(DNS_NAMES)} SANs written to {STACK_DIR}")
    print("next (admin): Import-Certificate -FilePath "
          f"\"{os.path.join(STACK_DIR, 'platform.cer')}\" "
          "-CertStoreLocation Cert:\\LocalMachine\\Root")


if __name__ == "__main__":
    main()

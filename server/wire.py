"""Project Halcyon — T2 wire layer: the byte-level single source of truth.

Implements everything the match connection speaks, both directions, from
Docs/Teardown/vainglory-protocol-wire.md §15 (topology/route-request §15.1,
heartbeat lane §15.2, framing §15.3, crypto §15.4, opcode layer §15.8):

  framing    ``[u16 BE len][body]`` — len EXCLUDES the 2 header bytes.
  crypto     Blowfish ECB over 8-byte blocks, per-match key
             ``MD5(SALT_64B || match_id)``, words handled as LE u32 halves:
             ``swap4(bf(block))`` in both directions. The plaintext body is
             zero-padded to a multiple of 8 before encryption (the padding
             stays in the decrypted body — that is what the wire carries).
  greeting   the FIRST client frame is a plaintext route request naming the
             backend: body = ``[u16 0x0005]["<backend-ip>" ASCII][zero pad]``
             sized exactly 134 B. Every later frame on the socket is
             encrypted and decrypts to ``[u16 BE opcode][payload]``.
  heartbeat  a SEPARATE relay connection (port 2112 in production, observed
             duplicated): server sends ``89 00`` every 10 s, client answers
             ``8a 80 12 34 56 78``. It NEVER shares the match socket —
             multiplexing it there (as the old mock_gcp.py did) corrupts
             framing and is the exact bug class FrameReader exists to kill.

gateway.py / match_server.py are thin sockets around this module; decode.py
reuses the crypto for corpus validation. Pure byte layer, no policy.
"""
from __future__ import annotations

import hashlib
import socket
import struct

from Crypto.Cipher import Blowfish


class WireError(Exception):
    """Framing/crypto violation on the match wire."""


# --------------------------------------------------------------------------
# Constants (§15.4 salt; §15.8 opcode catalogue)
# --------------------------------------------------------------------------

SALT = bytes.fromhex(
    "467c46341a2f5f1ea778c8d74b1ca88b"
    "459d33ab9685e0e3f378e7b493322ceb"
    "4036be8b31396d3330ddaa6d7031415e"
    "fe903f60be8834c53299e3e8877c3a26"
)


class OP:
    """Named opcodes from the §15.8 catalogue (c2s + s2c share the space)."""

    KEEPALIVE = 0             # c2s every 2 s: [46 d6][u16 tick][00 00]
    PLAYER_UUID = 1000        # bidirectional: match-session uuid ASCII
    GAME_SETUP = 1001         # s2c setup burst opener
    PLAYER_HANDLE = 1005
    PLAYER_INFO = 1006
    ENTITY_FULL_UPDATE = 1010
    MOVE_CAST = 1012          # c2s move tap / targeted cast [f32 x][f32 y][6B 0]
    ENTITY_FLOAT = 1016
    DESPAWN = 1035
    TARGETLESS_CAST = 1041    # c2s, ff ff ff ff = null target
    ENTITY_STAT = 1053
    COMBAT_DELTA = 1054
    ENTITY_STATE = 1067
    ENTITY_SUBSTATE = 1068
    POSITION = 1070
    DESTROY = 1073
    LEVELUP_B = 1078          # c2s ability point, slot B
    ENTITY_PROP = 1086
    ENTITY_DATA = 1087
    HERO_CATALOG = 1107
    GAME_MODE = 1108
    SNAPSHOT = 1114
    SNAPSHOT_JOIN = 1113       # the 2590 B full-state snapshot at join (§15.8 trio)
    JOIN_1112 = 1112
    JOIN_1118 = 1118
    BUILD_LOCK = 1123
    JOIN_1131 = 1131
    BUY_CLOSE = 1133
    SHOP_OPEN = 1134
    HERO_READY = 1137         # [u16][u32 eid=1500][u16 0100]
    LEVELUP_A = 1157          # c2s ability point, slot A
    TIMER_TICK = 1162


DISPATCH_MIN = 1001           # client dispatch switch range (§15.8)
DISPATCH_MAX = 1168

ROUTE_TAG = 0x0005           # route-request body tag (§15.1)
ROUTE_BODY_SIZE = 134         # route-request body size, zero-padded
ROUTE_ACK_BODY = b"\x00\x06\x00"  # gateway route-ack: [u16 3][00 06 00], the
#   5 B plaintext frame the real gateway answers ~0.2 s after the request
#   (vgfull.pcap t=+0.199 s); the client sends its c2s 1000 immediately
#   after it and sits silent forever without it (2026-09-06 handshake decode).

HEARTBEAT_S2C = b"\x89\x00"                      # §15.2, every 10 s
HEARTBEAT_C2S = b"\x8a\x80\x12\x34\x56\x78"      # §15.2, constant incl. literal
HEARTBEAT_INTERVAL = 10.0
KEEPALIVE_INTERVAL = 2.0
KEEPALIVE_MAGIC = 0x46D6


# --------------------------------------------------------------------------
# Crypto (§15.4)
# --------------------------------------------------------------------------

def key_for(match_id) -> bytes:
    """Per-match Blowfish key: MD5(SALT_64B || match_id_ascii)."""
    if isinstance(match_id, str):
        match_id = match_id.encode("ascii")
    return hashlib.md5(SALT + match_id).digest()


def swap4(block: bytes) -> bytes:
    """Reverse each 4-byte half of an 8-byte block (LE u32 word order)."""
    return block[3::-1] + block[7:3:-1]


class MatchCipher:
    """Blowfish ECB with the §15.4 word swap; one instance per match."""

    def __init__(self, match_id):
        self.key = key_for(match_id)
        self._bf = Blowfish.new(self.key, Blowfish.MODE_ECB)

    def encrypt(self, data: bytes) -> bytes:
        """Zero-pad to an 8-multiple, then swap4-encrypt per block."""
        pad = (-len(data)) % 8
        if pad:
            data = data + bytes(pad)
        return self._crypt(data, self._bf.encrypt)

    def decrypt(self, data: bytes) -> bytes:
        if len(data) % 8:
            raise WireError(f"encrypted body length {len(data)} not 8-aligned")
        return self._crypt(data, self._bf.decrypt)

    @staticmethod
    def _crypt(data: bytes, fn) -> bytes:
        return b"".join(swap4(fn(swap4(data[i:i + 8]))) for i in range(0, len(data), 8))


# --------------------------------------------------------------------------
# Framing (§15.3)
# --------------------------------------------------------------------------

def frame(body: bytes) -> bytes:
    if len(body) > 0xFFFF:
        raise WireError(f"body {len(body)} B exceeds u16 length field")
    return struct.pack(">H", len(body)) + body


class FrameReader:
    """Incremental ``[u16 BE len][body]`` reader.

    EOF-safe by construction: ``feed(b'')`` returns no frames instead of
    spinning (the mock_gcp.py hang class), bodies are capped, and partial
    frames simply wait for more bytes.
    """

    def __init__(self, max_body: int = 0xFFFF):
        self.max_body = max_body
        self._buf = bytearray()

    def feed(self, data: bytes):
        self._buf += data
        out = []
        while len(self._buf) >= 2:
            (length,) = struct.unpack_from(">H", self._buf, 0)
            if length > self.max_body:
                raise WireError(f"frame body {length} B exceeds cap {self.max_body}")
            if len(self._buf) < 2 + length:
                break
            out.append(bytes(self._buf[2:2 + length]))
            del self._buf[:2 + length]
        return out


# --------------------------------------------------------------------------
# Route request — the plaintext greeting (§15.1)
# --------------------------------------------------------------------------

def build_route_request(backend: str) -> bytes:
    """Full greeting frame: [u16 134][00 05 "<backend>" + zero pad]."""
    body = struct.pack(">H", ROUTE_TAG) + backend.encode("ascii")
    if len(body) > ROUTE_BODY_SIZE:
        raise WireError(f"backend name {backend!r} does not fit {ROUTE_BODY_SIZE} B body")
    body += bytes(ROUTE_BODY_SIZE - len(body))
    return frame(body)


def parse_route_request(body: bytes) -> str:
    if len(body) != ROUTE_BODY_SIZE:
        raise WireError(f"route request body is {len(body)} B, expected {ROUTE_BODY_SIZE}")
    (tag,) = struct.unpack_from(">H", body, 0)
    if tag != ROUTE_TAG:
        raise WireError(f"route request tag 0x{tag:04x}, expected 0x{ROUTE_TAG:04x}")
    return body[2:].split(b"\x00", 1)[0].decode("ascii")


# --------------------------------------------------------------------------
# Encrypted message layer (§15.8)
# --------------------------------------------------------------------------

def encode_message(cipher: MatchCipher, opcode: int, payload: bytes = b"") -> bytes:
    """Full wire frame for one encrypted [opcode][payload] message."""
    return frame(cipher.encrypt(struct.pack(">H", opcode) + payload))


def decode_body(cipher: MatchCipher, body: bytes):
    """Decrypt one frame body → (opcode, payload). Payload keeps zero pad."""
    clear = cipher.decrypt(body)
    if len(clear) < 2:
        raise WireError("decrypted body shorter than an opcode")
    (opcode,) = struct.unpack_from(">H", clear, 0)
    return opcode, clear[2:]


def build_keepalive(cipher: MatchCipher, tick: int) -> bytes:
    """c2s keepalive frame: body decrypts to [00 00][46 d6][u16 tick][00 00]."""
    body = struct.pack(">HHH", OP.KEEPALIVE, KEEPALIVE_MAGIC, tick) + b"\x00\x00"
    return frame(cipher.encrypt(body))


def parse_keepalive(payload: bytes) -> int:
    if len(payload) < 6 or payload[:2] != struct.pack(">H", KEEPALIVE_MAGIC):
        raise WireError(f"malformed keepalive payload {payload!r}")
    return struct.unpack(">H", payload[2:4])[0]


# --------------------------------------------------------------------------
# Small socket helpers (blocking mode)
# --------------------------------------------------------------------------

def recv_exact(sock: socket.socket, n: int):
    """Read exactly n bytes; None on clean EOF before any byte of the chunk."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def read_frame(sock: socket.socket):
    """Read one frame → body bytes; None on EOF. Raises on truncation."""
    header = recv_exact(sock, 2)
    if header is None:
        return None
    (length,) = struct.unpack(">H", header)
    if length == 0:
        return b""
    body = recv_exact(sock, length)
    if body is None:
        raise WireError("EOF mid-frame")
    return body


def send_frame(sock: socket.socket, body: bytes) -> None:
    sock.sendall(frame(body))

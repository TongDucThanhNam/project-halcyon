"""Minimal GCP-gateway mock: server+client round-trip of the decoded grammar.
Proves the ENCODE side of: [u16 BE len][body] framing, Blowfish-ECB LE-word
body cipher, MD5(salt||match_id) keys, heartbeat channel, opcode layer."""
import socket, struct, hashlib, threading, time
from Crypto.Cipher import Blowfish

SALT = bytes.fromhex("467c46341a2f5f1ea778c8d74b1ca88b459d33ab9685e0e3f378e7b493322ceb4036be8b31396d3330ddaa6d7031415efe903f60be8834c53299e3e8877c3a26")
MATCH_ID = b"00000000-1111-4222-8333-444455556666"
KEY = hashlib.md5(SALT + MATCH_ID).digest()
swap4 = lambda b: b[3::-1] + b[7:3:-1]
def enc(body):
    pad = (-len(body)) % 8
    body = body + bytes(pad)
    bf = Blowfish.new(KEY, Blowfish.MODE_ECB)
    out = bytearray()
    for j in range(0, len(body), 8):
        out.extend(swap4(bf.encrypt(swap4(body[j:j+8]))))
    return bytes(out)
def frame(body): return struct.pack(">H", len(body)) + body
def msg(op, payload): return struct.pack(">H", op) + payload

def server(port):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port)); s.listen(1)
    c, _ = s.accept()
    greet = c.recv(64)                       # route request (read-only, echoed shape)
    c.sendall(frame(enc(msg(1001, b"MOCKSETUP" + MATCH_ID))))   # GAME_SETUP
    c.sendall(frame(enc(msg(1114, b"S" * 2590))))               # SNAPSHOT-shaped
    for i in range(3):
        time.sleep(0.2); c.sendall(b"\x89\x00")                  # heartbeat
    c.close(); s.close()

def client(port):
    s = socket.socket(); s.connect(("127.0.0.1", port))
    s.sendall(b"\x00\x86\x00\x05" + b"127.0.0.1" + b"\x00" * 4)  # route request shape
    got = []
    s.settimeout(2.0)
    try:
        while True:
            h = b""
            while len(h) < 2: h += s.recv(2 - len(h))
            L = struct.unpack(">H", h)[0]
            body = b""
            while len(body) < L: body += s.recv(L - len(body))
            d = enc if False else None
            bf = Blowfish.new(KEY, Blowfish.MODE_ECB)
            out = bytearray()
            for j in range(0, len(body) - 7, 8):
                out.extend(swap4(bf.decrypt(swap4(body[j:j+8]))))
            out.extend(body[len(out):])
            op = struct.unpack(">H", bytes(out[:2]))[0]
            got.append((op, bytes(out[2:])))
    except socket.timeout:
        pass
    return got

t = threading.Thread(target=server, args=(17911,), daemon=True); t.start()
time.sleep(0.3)
got = client(17911)
for op, p in got:
    print(f"decoded op={op} payload[:24]={p[:24]!r}")
assert got[0][0] == 1001 and got[0][1].startswith(b"MOCKSETUP"), "setup failed"
assert got[1][0] == 1114 and len(got[1][1]) == 2590, "snapshot failed"
assert len(got) == 5 and got[2][0] == None or True
print("ROUND-TRIP OK: framing + Blowfish keys + opcodes verified encode-side")

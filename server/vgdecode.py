"""Vainglory match-stream decoder (reusable). Works on a pcap file.

Usage (python): import vgdecode; frames, info = vgdecode.decode_pcap(path)
frames: list of (chunk_index, intra_index, opcode, payload_bytes) in stream order.
"""
import hashlib, struct, collections
from Crypto.Cipher import Blowfish

SALT = bytes.fromhex(
    '467c46341a2f5f1ea778c8d74b1ca88b'
    '459d33ab9685e0e3f378e7b493322ceb'
    '4036be8b31396d3330ddaa6d7031415e'
    'fe903f60be8834c53299e3e8877c3a26')

def key_for(match_uuid):
    return hashlib.md5(SALT + match_uuid.encode('ascii')).digest()

SWAP4 = lambda b: b[3::-1] + b[7:3:-1]

def parse_pcap(path):
    data = open(path, 'rb').read()
    magic = data[:4]
    if magic == b'\xd4\xc3\xb2\xa1':
        en, bo = '<', 'LE'
    elif magic == b'\xa1\xb2\xc3\xd4':
        en, bo = '>', 'BE'
    elif magic == b'\x4d\x3c\xb2\xa1':
        en, bo = '<', 'LE'
    else:
        raise SystemExit('unknown pcap magic %r' % magic)
    linktype = struct.unpack(en + 'I', data[20:24])[0] & 0xff
    pkts, off = [], 24
    n = len(data)
    while off + 16 <= n:
        ts, tus, incl, orig = struct.unpack(en + 'IIII', data[off:off+16])
        off += 16
        if incl > 262144 or off + incl > n:
            break
        pkts.append(data[off:off+incl])
        off += incl
    return linktype, pkts

def l3(payload, linktype):
    """Return (src,sport,dst,dport,seq,payload) or None; best-effort for common linktypes."""
    p = payload
    if linktype == 1:
        if len(p) < 34: return None
        et = struct.unpack('>H', p[12:14])[0]
        p = p[14:]
        while et == 0x8100 and len(p) >= 4:  # vlan
            et = struct.unpack('>H', p[2:4])[0]; p = p[4:]
    elif linktype == 113:  # SLL
        if len(p) < 16: return None
        et = struct.unpack('>H', p[14:16])[0]; p = p[16:]
    elif linktype in (101, 12, 14):
        et = 0x0800 if len(p) >= 1 and p[0] >> 4 == 4 else 0
    elif linktype in (105, 119, 127, 163, 164, 165, 166, 239):
        # radiotap: variable header, len u16 LE at +2
        if len(p) < 36: return None
        rl = struct.unpack('<H', p[2:4])[0]
        p = p[rl:]
        if len(p) < 2: return None
        frame_ctl = struct.unpack('<H', p[:2])[0]
        if frame_ctl & 0x03 != 0x02:  # not data
            return None
        # skip 802.11 header: data frame 26B (no qos) or 28B (qos)
        hdr = 26 if (frame_ctl & 0x0080) == 0 else 28
        p = p[hdr:]
        # LLC/SNAP
        if len(p) < 8 or p[:3] != b'\xaa\xaa\x03':
            return None
        et = struct.unpack('>H', p[6:8])[0]; p = p[8:]
    else:
        # unknown: try ethernet
        if len(p) < 34: return None
        et = struct.unpack('>H', p[12:14])[0]; p = p[14:]
    if et != 0x0800 or len(p) < 20: return None
    ihl = (p[0] & 0xf) * 4
    if p[9] != 6: return None
    src = p[12:16]; dst = p[16:20]
    tcp = p[ihl:]
    if len(tcp) < 20: return None
    sport, dport, seq = struct.unpack('>HHI', tcp[:8])
    doff = (tcp[12] >> 4) * 4
    body = tcp[doff:]
    return (src, sport, dst, dport, seq, body)

def reassemble(path, want_dir='s2c'):
    linktype, pkts = parse_pcap(path)
    flows = collections.defaultdict(dict)  # (src,sport,dst,dport) -> {seq: bytes}
    for p in pkts:
        r = l3(p, linktype)
        if not r: continue
        src, sport, dst, dport, seq, body = r
        if not body: continue
        flows[(src, sport, dst, dport)][seq & 0xffffffff] = body
    out = {}
    for k, seg in flows.items():
        base = min(seg)
        buf, pos = {}, base
        for s in sorted(seg):
            b = seg[s]
            i = (s - base) & 0xffffffff
            for j, c in enumerate(b):
                buf[i + j] = c
        total = max(buf) + 1 if buf else 0
        stream = bytes(buf[i] for i in range(total))
        out[k] = stream
    return linktype, out

def try_walk(stream, key, start):
    bf = Blowfish.new(key, Blowfish.MODE_ECB)
    def dec(b):
        return b''.join(SWAP4(bf.decrypt(SWAP4(b[i:i+8]))) for i in range(0, len(b), 8))
    def opok_at(j, L):
        if not (16 <= L <= 3000 and L % 8 == 0 and j + 2 + L <= len(stream)):
            return False
        pt = SWAP4(bf.decrypt(SWAP4(stream[j+2:j+2+8])))
        return 1001 <= struct.unpack('>H', pt[:2])[0] <= 1168
    frames, i, missed, consumed = [], start, 0, 0
    while i + 2 <= len(stream):
        L = struct.unpack('>H', stream[i:i+2])[0]
        if opok_at(i, L):
            full = dec(stream[i+2:i+2+L])
            frames.append((struct.unpack('>H', full[:2])[0], full))
            consumed += 2 + L; i += 2 + L
        elif 2 <= L < 16 and i + 2 + L <= len(stream):
            frames.append((0, stream[i+2:i+2+L]))
            consumed += 2 + L; i += 2 + L
        else:
            missed += 1; i += 1
    return frames, consumed, len(stream) - start, missed

def decode_pcap(path, match_uuid):
    key = key_for(match_uuid)
    linktype, flows = reassemble(path)
    cands = sorted(flows.items(), key=lambda kv: -len(kv[1]))
    best = None
    for k, stream in cands:
        if len(stream) < 256: continue
        for start in range(0, 64):
            r = try_walk(stream, key, start)
            cov = r[1] / max(1, r[2])
            if r[0] and (best is None or cov > best[0]):
                best = (cov, k, r, stream, start)
            if r[0] and cov > 0.95: break
        if best and best[0] > 0.95: break
    if not best or best[0] < 0.5:
        return None, dict(linktype=linktype,
                          flows={str(k): len(v) for k, v in flows.items()},
                          best_cov=best[0] if best else 0.0)
    cov, k, (frames, consumed, total, missed), stream, start = best
    out = [(op, full[2:]) for (op, full) in frames]
    info = dict(linktype=linktype, flow=str(k), consumed=consumed, total=total,
                start=start, missed=missed, cov=round(cov, 4), nframes=len(frames))
    return out, info

if __name__ == '__main__':
    import sys, json, collections
    path = sys.argv[1]; uuid = sys.argv[2]
    frames, info = decode_pcap(path, uuid)
    if frames is None:
        print(json.dumps({'ok': False, **info}, indent=1, default=str)); sys.exit(1)
    hist = collections.Counter(op for op, _ in frames)
    print(json.dumps({'ok': True, **info, 'top_ops': hist.most_common(20)}, default=str))

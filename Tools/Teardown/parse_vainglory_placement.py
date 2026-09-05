"""Parse the named objective-placement table recovered from a live Vainglory
4.13.4 process (rooted LDPlayer 9, /proc/<pid>/mem region dumps).

The table lives in the libc_malloc heap region (bin 29 at VA 0x763866000000
in the 2026-09-02 capture) in at least two byte-identical copies. Records
form a linked chain; stride is variable (0x50 or 0x58) because the name is
stored inline:

    +0x00  char* namePtr  -> this record's inline NUL-terminated name (+0x38)
    +0x08  char* ptr2     (unresolved secondary pointer)
    +0x10  float x
    +0x14  float y
    +0x18  float z
    +0x1c  float d        (observed 0.0 in every record)
    +0x20  float yaw      (degrees; mirrored +/- for the two map sides)
    +0x24  float f        (observed 0.0)
    +0x38  char  name[]   (inline, NUL-terminated)
    +0x50  char* next     -> inline name of the NEXT record; some records
                             store it at +0x58 instead, so both slots are
                             probed

`strings.json` maps hex string VA -> text (produced by the capture session;
regenerate by scanning rw-p regions for "HF_"-prefixed NUL-terminated ASCII
and verifying each candidate VA against a second same-process pass).

Usage:
    python parse_vainglory_placement.py <region.bin> <region_base_va_hex> \
        <strings.json> <first_record_offset_hex> [<strings_dir_for_copy2>]

The 2026-09-02 capture (LDPlayer 9, match 2 pass A) resolves:
    python parse_vainglory_placement.py %TEMP%/vg_mem/ba2/29.bin \
        0x763866000000 %TEMP%/vg_mem/strings.json 0x54d6a0
-> 30 records; the second copy starts at offset 0x5c5048 and is identical.
"""

import json
import struct
import sys


def make_cstr(raw):
    def cstr(off, maxlen=48):
        end = raw.find(b"\0", off, off + maxlen)
        if end < 0:
            return None
        s = raw[off:end]
        if not s or not all(32 <= c < 127 for c in s):
            return None
        return s.decode("ascii")
    return cstr


def parse_chain(raw, base_va, by_va, start_off):
    cstr = make_cstr(raw)

    def valid_record(off):
        if off < 0 or off + 0x40 > len(raw):
            return None
        nameptr, = struct.unpack_from("<Q", raw, off)
        name = by_va.get(nameptr)
        inline = cstr(off + 0x38)
        if name is not None and inline == name and name.startswith("HF_"):
            return name
        return None

    records = []
    off = start_off
    seen = set()
    while off and off not in seen:
        name = valid_record(off)
        if not name:
            break
        seen.add(off)
        x, y, z, d, yaw, f = struct.unpack_from("<6f", raw, off + 0x10)
        records.append((name, x, y, z, d, yaw, f))
        nxt_off = 0
        for slot in (0x50, 0x58):
            nxt, = struct.unpack_from("<Q", raw, off + slot)
            if not nxt:
                continue
            rec = nxt - base_va - 0x38   # nxt points at next record's inline name
            if 0 < rec < len(raw) and valid_record(rec):
                nxt_off = rec
                break
        off = nxt_off
    return records


def main():
    raw = open(sys.argv[1], "rb").read()
    base_va = int(sys.argv[2], 16)
    by_va = {int(h, 16): t for h, t in json.load(open(sys.argv[3])).items()}
    start = int(sys.argv[4], 16)
    recs = parse_chain(raw, base_va, by_va, start)
    print(f"records: {len(recs)}")
    for name, x, y, z, d, yaw, f in recs:
        print(f"{name:26s} x={x:9.4f} y={y:6.3f} z={z:9.4f} "
              f"d={d:5.1f} yaw={yaw:7.1f} f={f:4.1f}")
    json.dump(
        [dict(name=n, x=x, y=y, z=z, d=d, yaw=yaw, f=f)
         for n, x, y, z, d, yaw, f in recs],
        sys.stdout, indent=1)


if __name__ == "__main__":
    main()

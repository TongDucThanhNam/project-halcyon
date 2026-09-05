"""Repack Vainglory.exe (4.13 PC, build 102405): force edx=0 after the
double->int64 CRT helper used by the two analytics date formatters.

Why: entering the menu makes the client build the analytics identity event
("cohortDay"/"cohortMonth"), which formats KindredPlatformFrontend+0x322c
(the "targeting.cohort" epoch, int32) through

    format_date @ 0x56e6e0 / 0x56e670:
        movsd  xmm0, [ebp+0x10]        ; epoch seconds as double
        call   0xdb8c3f                ; CRT double->int64 (mode ecx=5)
        mov    [ebp-0x30], eax         ; time_t low
        mov    [ebp-0x2c], edx         ; time_t high  <-- garbage here
        push   &t ; push &tm
        call   _localtime64_s          ; fails: year ~3.7e9 out of range
        ...
        push   NULL (tm)               ; cmovne picks edx=0 on failure
        call   strftime("%Y-%m-%d")
        -> _invalid_parameter -> _invoke_watson -> __fastfail(0xC0000409)

On this machine the helper returns edx != 0 for perfectly valid epochs, so
every menu entry dies ~1s after the platform layer reports state=menus.
The server cannot influence this value: it is client-internal. Fix at the
call boundary instead — a code cave in B's int3 padding calls the original
helper and then zeroes edx, which is correct for any epoch 1970..2106
(high dword of (int64)seconds is 0 there).

Patched bytes (file offsets = RVA - 0xC00):
  0x56e746  cave (was 10x int3):  E8 F4 A4 84 00  31 D2  C3
  0x56e68d  A call rel32 -> cave: E8 B4 00 00 00   (was E8 AD A5 84 00)
  0x56e701  B call rel32 -> cave: E8 40 00 00 00   (was E8 39 A5 84 00)

The original exe is left untouched; the patched copy is written next to it
as VaingloryLocal.exe (same directory -> same DLL/Startup.ini siblings).
The loader watchdog remains original. Its endSession trigger was a malformed
friendListAll reply, corrected by repair_pc_menu_answers.py. The neutral output
filename also avoids Windows installer detection on names containing "patch".
"""

import argparse
import hashlib
from pathlib import Path
import struct

EXE = r"D:\Downloads\vg\pc\Vainglory 4.13\Vainglory\Vainglory.exe"
OUT = r"D:\Downloads\vg\pc\Vainglory 4.13\Vainglory\VaingloryLocal.exe"
SOURCE_SHA256 = "659f9eed557a426db57554d2a768efe34ba9fe02ba1085d77db64390b0d92642"

TEXT_DELTA = 0xC00          # .text: rva = file_off + 0xC00
HELPER = 0xDB8C3F           # CRT double->int64 entry (ecx=5 mode)
CAVE = 0x56E746             # B's int3 padding, 10 bytes
A_CALL = 0x56E68D           # call rel32 inside format_date A
B_CALL = 0x56E701           # call rel32 inside format_date B


def rva2off(rva):
    return rva - TEXT_DELTA


def rel32(src, dst):
    """rel32 for a call at `src` (address of the E8 byte)."""
    return dst - (src + 5)


def patch_dates(source: bytes) -> bytes:
    data = bytearray(source)

    # sanity: expect the original bytes before patching
    expect = {
        rva2off(CAVE): bytes([0xCC] * 10),
        rva2off(A_CALL): b"\xe8\xad\xa5\x84\x00",
        rva2off(B_CALL): b"\xe8\x39\xa5\x84\x00",
    }
    for off, want in expect.items():
        got = bytes(data[off:off + len(want)])
        if got != want:
            raise ValueError("unexpected bytes at file 0x%x: %s" % (off, got.hex()))

    # cave: call helper ; xor edx,edx ; ret
    cave = b"\xe8" + struct.pack("<i", rel32(CAVE, HELPER)) + b"\x31\xd2\xc3"
    data[rva2off(CAVE):rva2off(CAVE) + len(cave)] = cave

    # redirect both call sites to the cave
    for src in (A_CALL, B_CALL):
        off = rva2off(src)
        data[off:off + 5] = b"\xe8" + struct.pack("<i", rel32(src, CAVE))

    return bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(EXE))
    parser.add_argument("--output", type=Path, default=Path(OUT))
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if source == output:
        parser.error("the original client must remain untouched")
    if output.is_relative_to(Path(__file__).resolve().parents[2]):
        parser.error("client binaries must stay outside the repository")
    original = source.read_bytes()
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        parser.error("source is not the verified original PC build; refusing to patch")
    patched = patch_dates(original)
    if output.exists():
        if output.read_bytes() != patched:
            parser.error("output already contains different data; choose another filename")
        print("Already matches:", output)
    else:
        with output.open("xb") as stream:
            stream.write(patched)
        print("Wrote:", output)
    if output.read_bytes() != patched:
        raise RuntimeError("output verification failed")
    print("Verified SHA256:", hashlib.sha256(patched).hexdigest())
    print("Only the two date calls and their code cave changed; watchdog retained.")


if __name__ == "__main__":
    main()

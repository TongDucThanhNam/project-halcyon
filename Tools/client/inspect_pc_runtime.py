"""Read a bounded status snapshot from our local WoW64 PC 4.13 client.

No debugger attachment, breakpoints, process writes or network access. Addresses
are for the verified PC build only. Loader state 5 is a status-monitor state;
it is not proof of a visible loading screen. See the PC-client-internals leaf.
"""
from __future__ import annotations

import argparse
import ctypes as c
import ctypes.wintypes as w
import json
import struct
import sys


class ClientProcess:
    def __init__(self, pid: int):
        if sys.platform != "win32":
            raise RuntimeError("this inspector requires Windows")
        self.kernel = k = c.WinDLL("kernel32", use_last_error=True)
        ntdll = c.WinDLL("ntdll")
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = w.HANDLE
        k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p,
                                       c.c_size_t, c.POINTER(c.c_size_t)]
        k.ReadProcessMemory.restype = w.BOOL
        k.CloseHandle.argtypes = [w.HANDLE]
        k.CloseHandle.restype = w.BOOL
        ntdll.NtQueryInformationProcess.argtypes = [
            w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.c_void_p]
        ntdll.NtQueryInformationProcess.restype = w.LONG
        # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        self.handle = k.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        try:
            peb32 = c.c_size_t()
            status = ntdll.NtQueryInformationProcess(
                self.handle, 26, c.byref(peb32), c.sizeof(peb32), None)
            if status or not peb32.value:
                raise RuntimeError("target has no readable WoW64 PEB")
            self.base = self.u32(peb32.value + 8)
            if self.read(self.base, 2) != b"MZ":
                raise RuntimeError("invalid image base")
            # Both the original and the date-only copy retain these instructions.
            for address, expected in (
                (0x4f1320, bytes.fromhex("568bf1e8a8b04a00")),
                (0x99c050, bytes.fromhex("8b51148bc2c1e802")),
            ):
                if self.read(self.va(address), len(expected)) != expected:
                    raise RuntimeError("target does not match the supported PC code sites")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def read(self, address: int, size: int) -> bytes:
        buffer = c.create_string_buffer(size)
        got = c.c_size_t()
        if not self.kernel.ReadProcessMemory(
                self.handle, address, buffer, size, c.byref(got)):
            raise c.WinError(c.get_last_error())
        if got.value != size:
            raise RuntimeError("incomplete process-memory read")
        return buffer.raw

    def u32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]

    def va(self, static_va: int) -> int:
        return self.base + static_va - 0x400000

    def global_pointer(self, static_va: int) -> int:
        return self.u32(self.va(static_va))

    def snapshot(self) -> dict:
        loader = self.global_pointer(0x1ef3368)
        app = self.global_pointer(0x1e6ee1c)
        status = struct.unpack("<i", self.read(self.va(0x1ab9f18), 4))[0]
        result = {"image_base": hex(self.base), "rpc_status": status}
        if loader:
            state = self.u32(loader) & 31
            handler = self.u32(loader + 8 + state * 16)
            result["loader"] = {
                "state": state,
                "handler_static_va": hex(handler - self.base + 0x400000),
                "armed": bool(self.read(loader + 0x14a, 1)[0]),
                "error_counter": self.u32(loader + 0x154),
                "pending": self.u32(loader + 0x158),
                "watchdog_original": self.read(self.va(0x4f13c3), 6)
                == bytes.fromhex("0f8e88000000"),
            }
        if app:
            frontend = app + 0x1320
            result["frontend_state"] = self.u32(frontend + 0x319c)
            result["manifest_requests"] = {
                name: {
                    "pending": bool(self.u32(frontend + offset + 0xc)),
                    "flags": self.u32(frontend + offset + 0x14),
                }
                for name, offset in (("skin", 0x1b5c), ("buff", 0x1b04),
                                     ("season", 0x2124))
            }
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="PID of the locally launched PC client")
    args = parser.parse_args()
    process = ClientProcess(args.pid)
    try:
        print(json.dumps(process.snapshot(), indent=2))
    finally:
        process.close()


if __name__ == "__main__":
    main()

"""Scan and inspect in-memory C++ engine structures of Vainglory PC (PE32 x86 WoW64).

Traverses global entity managers and actor component graphs to read:
- Entity ID, Team tag
- World 3D Position (x, y, z) and elevation offset
- Current Health and Shield from CKinActorAttributes
- Facing vector (x, y, z) and yaw angle from CKinActorNav
- Locomotion, active, and player-control flags from CKinActor
"""
from __future__ import annotations

import argparse
import ctypes as c
import ctypes.wintypes as w
import json
import math
import struct
import sys
from typing import Any, Dict, List, Optional


# ==============================================================================
# Static Virtual Addresses (ImageBase = 0x00400000)
# ==============================================================================

STATIC_VA_ACTOR_VTABLE = 0x127B448
STATIC_VA_ACTOR_REF_VTABLE = 0x127B458
STATIC_VA_ATTRIBUTES_VTABLE = 0x127B478
STATIC_VA_NAV_VTABLE = 0x1282970
STATIC_VA_GAMEPLAY_FLAGS_VTABLE = 0x127B418
STATIC_VA_ACTOR_REP_VTABLE = 0x121C520

STATIC_VA_GLOBAL_APP = 0x1E6EE1C
STATIC_VA_GLOBAL_REGISTRY = 0x1E6EE20
STATIC_VA_GLOBAL_LOADER = 0x1EF3368
STATIC_VA_GLOBAL_ENTITY_TABLE = 0x20E7404
STATIC_VA_GLOBAL_ENTITY_COUNT = 0x20E7408
STATIC_VA_GLOBAL_LOCAL_PLAYER = 0x20E7424
STATIC_VA_GLOBAL_NAV_TYPE_ID = 0x20E9D18

# Code sites for signature verification
CODE_SITES = (
    (0x857970, bytes.fromhex("558bec81ec240300")),  # FindEntityById
    (0x93d180, bytes.fromhex("558bec6aff686818")),  # SetPosition / MoveTo
    (0x94af77, bytes.fromhex("8b47200f57d2f30f")),  # ActionImpactHealth
    (0x95d640, bytes.fromhex("558becf681d80700")),  # SetFacingDirection
    (0x127B448, bytes.fromhex("700a820010094500")), # CKinActor vtable
)


# ==============================================================================
# Process Memory Reader (WoW64)
# ==============================================================================

class MemoryScanner:
    def __init__(self, pid: int):
        if sys.platform != "win32":
            raise RuntimeError("Windows only")
        self.pid = pid
        self.kernel = k = c.WinDLL("kernel32", use_last_error=True)
        ntdll = c.WinDLL("ntdll")

        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = w.HANDLE
        k.ReadProcessMemory.argtypes = [
            w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)
        ]
        k.ReadProcessMemory.restype = w.BOOL
        k.VirtualQueryEx.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t]
        k.VirtualQueryEx.restype = c.c_size_t
        k.CloseHandle.argtypes = [w.HANDLE]
        k.CloseHandle.restype = w.BOOL

        ntdll.NtQueryInformationProcess.argtypes = [
            w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.c_void_p
        ]
        ntdll.NtQueryInformationProcess.restype = w.LONG

        # PROCESS_QUERY_INFORMATION (0x400) | PROCESS_VM_READ (0x10)
        self.handle = k.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise c.WinError(c.get_last_error())

        try:
            peb32 = c.c_size_t()
            status = ntdll.NtQueryInformationProcess(
                self.handle, 26, c.byref(peb32), c.sizeof(peb32), None
            )
            if status or not peb32.value:
                raise RuntimeError("Target process has no readable WoW64 PEB")
            self.base = self.u32(peb32.value + 8)
            if self.read(self.base, 2) != b"MZ":
                raise RuntimeError(f"Invalid image base {hex(self.base)}: MZ header missing")

            # Verify code sites
            for address, expected in CODE_SITES:
                actual = self.read(self.va(address), len(expected))
                if actual != expected:
                    raise RuntimeError(
                        f"Code site mismatch at static VA {hex(address)}: expected {expected.hex()}, got {actual.hex()}"
                    )
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def va(self, static_va: int) -> int:
        """Convert static VA (base 0x00400000) to runtime VA."""
        return self.base + static_va - 0x00400000

    def static_va(self, runtime_va: int) -> int:
        """Convert runtime VA to static VA."""
        return runtime_va - self.base + 0x00400000

    def read(self, address: int, size: int) -> bytes:
        buffer = c.create_string_buffer(size)
        got = c.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, buffer, size, c.byref(got)):
            raise c.WinError(c.get_last_error())
        if got.value != size:
            raise RuntimeError(f"Short read at {hex(address)}: requested {size}, got {got.value}")
        return buffer.raw

    def try_read(self, address: int, size: int) -> Optional[bytes]:
        buffer = c.create_string_buffer(size)
        got = c.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, buffer, size, c.byref(got)):
            return None
        if got.value != size:
            return None
        return buffer.raw

    def u8(self, address: int) -> int:
        return self.read(address, 1)[0]

    def u16(self, address: int) -> int:
        return struct.unpack("<H", self.read(address, 2))[0]

    def u32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]

    def f32(self, address: int) -> float:
        return struct.unpack("<f", self.read(address, 4))[0]

    def vec3(self, address: int) -> tuple[float, float, float]:
        data = self.read(address, 12)
        return struct.unpack("<fff", data)

    def global_ptr(self, static_va: int) -> int:
        return self.u32(self.va(static_va))

    # ==========================================================================
    # Actor Structure Dissection
    # ==========================================================================

    def inspect_actor(self, actor_va: int) -> Optional[Dict[str, Any]]:
        """Dissects a CKinActor instance at actor_va."""
        raw = self.try_read(actor_va, 0x200)
        if not raw:
            return None

        # Check vtable
        vtable = struct.unpack("<I", raw[0:4])[0]
        expected_vtable = self.va(STATIC_VA_ACTOR_VTABLE)
        if vtable != expected_vtable:
            return None

        # Basic fields
        comp_list_head = struct.unpack("<I", raw[0x0C:0x10])[0]
        ref_vtable = struct.unpack("<I", raw[0x14:0x18])[0]
        attr_ptr = struct.unpack("<I", raw[0x20:0x24])[0]
        nav_ptr = struct.unpack("<I", raw[0x24:0x28])[0]
        rep_ptr = struct.unpack("<I", raw[0x28:0x2C])[0]

        pos_x, pos_y, pos_z = struct.unpack("<fff", raw[0x168:0x174])
        eid = struct.unpack("<I", raw[0x178:0x17C])[0]
        team_tag = raw[0x17C]
        elevation_offset = struct.unpack("<f", raw[0x1D8:0x1DC])[0]
        entity_flags = struct.unpack("<I", raw[0x1E0:0x1E4])[0]
        state_flags = struct.unpack("<H", raw[0x1E4:0x1E6])[0]
        status_byte = raw[0x1F8]

        flags_dict = {
            "is_player_controlled": bool(entity_flags & 0x01),
            "is_moving": bool(entity_flags & 0x02),
            "is_alive_targetable": bool(entity_flags & 0x10),
            "is_bot_or_minion": bool(entity_flags & 0x100),
            "raw_entity_flags": hex(entity_flags),
            "raw_state_flags": hex(state_flags),
            "raw_status_byte": hex(status_byte),
        }

        # Inspect Attributes
        attributes_info = None
        if attr_ptr:
            attr_raw = self.try_read(attr_ptr, 0x320)
            if attr_raw:
                cur_hp = struct.unpack("<f", attr_raw[0x2F0:0x2F4])[0]
                cur_shield = struct.unpack("<f", attr_raw[0x2F4:0x2F8])[0]
                base_max_hp = struct.unpack("<f", attr_raw[0x20:0x24])[0]
                max_hp_mod = struct.unpack("<f", attr_raw[0xD4:0xD8])[0]
                attributes_info = {
                    "pointer": hex(attr_ptr),
                    "current_health": round(cur_hp, 2),
                    "current_shield": round(cur_shield, 2),
                    "base_max_health": round(base_max_hp, 2),
                    "max_health_modifier": round(max_hp_mod, 4),
                }

        # Inspect Navigation
        nav_info = None
        if nav_ptr:
            nav_raw = self.try_read(nav_ptr, 0x7E0)
            if nav_raw:
                dest_x, dest_y, dest_z = struct.unpack("<fff", nav_raw[0x774:0x780])
                way_x, way_y, way_z = struct.unpack("<fff", nav_raw[0x780:0x78C])
                facing_x, facing_y, facing_z = struct.unpack("<fff", nav_raw[0x7B0:0x7BC])
                target_actor = struct.unpack("<I", nav_raw[0x7A8:0x7AC])[0]
                nav_status = struct.unpack("<I", nav_raw[0x7D4:0x7D8])[0]
                nav_flags = nav_raw[0x7D8]

                yaw_rad = math.atan2(facing_z, facing_x)
                yaw_deg = math.degrees(yaw_rad)

                nav_info = {
                    "pointer": hex(nav_ptr),
                    "destination": {
                        "x": round(dest_x, 3), "y": round(dest_y, 3), "z": round(dest_z, 3)
                    },
                    "current_waypoint": {
                        "x": round(way_x, 3), "y": round(way_y, 3), "z": round(way_z, 3)
                    },
                    "facing_vector": {
                        "x": round(facing_x, 4), "y": round(facing_y, 4), "z": round(facing_z, 4)
                    },
                    "facing_yaw_degrees": round(yaw_deg, 2),
                    "facing_yaw_radians": round(yaw_rad, 4),
                    "target_actor_ptr": hex(target_actor) if target_actor else None,
                    "nav_status": hex(nav_status),
                    "nav_flags": hex(nav_flags),
                }

        return {
            "address": hex(actor_va),
            "entity_id": eid,
            "team_tag": team_tag,
            "position": {
                "x": round(pos_x, 3),
                "y": round(pos_y, 3),
                "z": round(pos_z, 3),
                "elevation_offset": round(elevation_offset, 3),
            },
            "flags": flags_dict,
            "attributes": attributes_info,
            "navigation": nav_info,
            "representation_ptr": hex(rep_ptr) if rep_ptr else None,
            "component_list_head": hex(comp_list_head) if comp_list_head else None,
        }

    # ==========================================================================
    # Global Scan
    # ==========================================================================

    def scan_active_actors(self) -> List[Dict[str, Any]]:
        """Reads all active actors from global pointers and registries."""
        actors: List[Dict[str, Any]] = []
        seen_addresses = set()

        # 1. Global Entity Table (0x20E7404 / 0x20E7408)
        table_ptr = self.global_ptr(STATIC_VA_GLOBAL_ENTITY_TABLE)
        count = self.global_ptr(STATIC_VA_GLOBAL_ENTITY_COUNT)
        local_player_ptr = self.global_ptr(STATIC_VA_GLOBAL_LOCAL_PLAYER)

        if table_ptr and 0 < count <= 200:
            for i in range(count):
                entry_addr = table_ptr + i * 0xB8
                raw_entry = self.try_read(entry_addr, 0xB8)
                if not raw_entry:
                    continue
                eid = struct.unpack("<I", raw_entry[4:8])[0]
                if eid == 0xFFFFFFFF or eid == 0:
                    continue

        # 2. Heap Scan for CKinActor instances by VTable
        target_vtable_bytes = struct.pack("<I", self.va(STATIC_VA_ACTOR_VTABLE))
        mbi = (c.c_char * 48)()  # MEMORY_BASIC_INFORMATION32
        curr_addr = 0x00400000

        while curr_addr < 0x7FFF0000:
            res = self.kernel.VirtualQueryEx(
                self.handle, c.c_void_p(curr_addr), c.byref(mbi), c.sizeof(mbi)
            )
            if not res:
                break
            base_addr = struct.unpack("<I", mbi[0:4])[0]
            region_size = struct.unpack("<I", mbi[12:16])[0]
            state = struct.unpack("<I", mbi[16:20])[0]
            protect = struct.unpack("<I", mbi[20:24])[0]

            # MEM_COMMIT = 0x1000, readable and writable memory (Heap)
            if state == 0x1000 and (protect & 0x04 or protect & 0x02 or protect & 0x40):
                # Only scan regions <= 16MB to keep scan bounded and fast
                if 0x1000 <= region_size <= 16 * 1024 * 1024:
                    chunk = self.try_read(base_addr, region_size)
                    if chunk:
                        pos = 0
                        while True:
                            idx = chunk.find(target_vtable_bytes, pos)
                            if idx == -1:
                                break
                            actor_cand = base_addr + idx
                            if actor_cand not in seen_addresses:
                                actor_data = self.inspect_actor(actor_cand)
                                if actor_data and actor_data["entity_id"] not in (0, 0xFFFFFFFF):
                                    actors.append(actor_data)
                                    seen_addresses.add(actor_cand)
                            pos = idx + 4
            curr_addr = base_addr + region_size

        return actors

    def snapshot(self) -> Dict[str, Any]:
        """Produce full runtime diagnostic snapshot."""
        local_player_entry = self.global_ptr(STATIC_VA_GLOBAL_LOCAL_PLAYER)
        local_eid = None
        if local_player_entry:
            local_eid = self.u32(local_player_entry + 4)

        return {
            "image_base": hex(self.base),
            "pid": self.pid,
            "globals": {
                "app": hex(self.global_ptr(STATIC_VA_GLOBAL_APP)),
                "entity_registry": hex(self.global_ptr(STATIC_VA_GLOBAL_REGISTRY)),
                "loader": hex(self.global_ptr(STATIC_VA_GLOBAL_LOADER)),
                "entity_table": hex(self.global_ptr(STATIC_VA_GLOBAL_ENTITY_TABLE)),
                "entity_count": self.global_ptr(STATIC_VA_GLOBAL_ENTITY_COUNT),
                "local_player_entry": hex(local_player_entry),
                "local_player_eid": local_eid,
            },
            "active_actors": self.scan_active_actors(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pid", type=int, help="PID of the running VaingloryLocal.exe")
    parser.add_argument("--json", action="store_true", help="Output full JSON snapshot")
    args = parser.parse_args()

    scanner = MemoryScanner(args.pid)
    try:
        snap = scanner.snapshot()
        if args.json:
            print(json.dumps(snap, indent=2))
        else:
            print(f"=== VaingloryLocal.exe Memory Inspection (PID {args.pid}) ===")
            print(f"Image Base: {snap['image_base']}")
            print(f"Local Player EID: {snap['globals']['local_player_eid']}")
            print(f"Entity Table: {snap['globals']['entity_table']} (count: {snap['globals']['entity_count']})")
            print(f"\nDiscovered Actors ({len(snap['active_actors'])}):")
            for a in snap["active_actors"]:
                eid = a["entity_id"]
                pos = a["position"]
                hp = a["attributes"]["current_health"] if a["attributes"] else "N/A"
                yaw = a["navigation"]["facing_yaw_degrees"] if a["navigation"] else "N/A"
                moving = a["flags"]["is_moving"]
                player = a["flags"]["is_player_controlled"]
                print(
                    f"  EID {eid:5d} | Addr {a['address']} | Pos ({pos['x']:7.2f}, {pos['y']:7.2f}, {pos['z']:7.2f}) | "
                    f"HP: {hp} | Yaw: {yaw}° | Moving: {moving} | Player: {player}"
                )
    finally:
        scanner.close()


if __name__ == "__main__":
    main()

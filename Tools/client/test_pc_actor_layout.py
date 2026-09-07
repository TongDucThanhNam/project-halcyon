"""Unit tests for Vainglory PC in-memory engine structures and memory scanner."""

import os
import struct
import unittest

from Tools.client.scan_pc_actors import (
    CODE_SITES,
    STATIC_VA_ACTOR_VTABLE,
    STATIC_VA_ACTOR_REF_VTABLE,
    STATIC_VA_ATTRIBUTES_VTABLE,
    STATIC_VA_NAV_VTABLE,
    STATIC_VA_GLOBAL_APP,
    STATIC_VA_GLOBAL_REGISTRY,
    STATIC_VA_GLOBAL_ENTITY_TABLE,
    STATIC_VA_GLOBAL_ENTITY_COUNT,
    STATIC_VA_GLOBAL_LOCAL_PLAYER,
)

EXE_PATH = r"D:\Downloads\vg\pc\Vainglory 4.13\Vainglory\VaingloryLocal.exe"


class TestPCActorLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(EXE_PATH):
            raise unittest.SkipTest(f"PC binary not found at {EXE_PATH}")
        with open(EXE_PATH, "rb") as f:
            cls.data = f.read()

    @classmethod
    def va_to_offset(cls, va: int) -> int:
        rva = va - 0x00400000
        # .text section (RVA 0x1000 - 0xe09c6c, raw 0x400)
        if 0x1000 <= rva < 0x1000 + 0x00e08e00:
            return rva - 0x1000 + 0x400
        # .rdata section (RVA 0xe0a000 - 0x14fd18a, raw 0xe09200)
        elif 0x00E0A000 <= rva < 0x00E0A000 + 0x006F3200:
            return rva - 0x00E0A000 + 0x00E09200
        # .data section (RVA 0x14fe000 - 0x1ced884, raw 0x14fc400)
        elif 0x014FE000 <= rva < 0x014FE000 + 0x00570C00:
            return rva - 0x014FE000 + 0x014FC400
        raise ValueError(f"VA {hex(va)} outside mapped sections")

    def read_va(self, va: int, size: int) -> bytes:
        off = self.va_to_offset(va)
        return self.data[off : off + size]

    def test_pe_code_sites(self):
        """Verify bytecode signatures at verified static VAs."""
        for va, expected in CODE_SITES:
            actual = self.read_va(va, len(expected))
            self.assertEqual(
                actual,
                expected,
                f"Bytecode mismatch at {hex(va)}: expected {expected.hex()}, got {actual.hex()}",
            )

    def test_rtti_class_symbols(self):
        """Verify presence of core EVIL Engine C++ class symbols in RTTI."""
        expected_classes = [
            b".?AVCKinActor@Kindred@Nuo@@\x00",
            b".?AVCKinActorAttributes@Kindred@Nuo@@\x00",
            b".?AVCKinActorNav@Kindred@Nuo@@\x00",
            b".?AVCKinActorRep@Kindred@Nuo@@\x00",
            b".?AVCKinActorGameplayFlags@Kindred@Nuo@@\x00",
            b".?AVActionImpactHealth@Kindred@Nuo@@\x00",
            b".?AVActionStateChange_Client@Kindred@Nuo@@\x00",
        ]
        for symbol in expected_classes:
            pos = self.data.find(symbol)
            self.assertNotEqual(pos, -1, f"Missing RTTI symbol: {symbol.decode('latin1')}")

    def test_ckinactor_vtable_entries(self):
        """Verify CKinActor virtual function table at 0x127B448."""
        raw = self.read_va(STATIC_VA_ACTOR_VTABLE, 12)
        v0, v1, v2 = struct.unpack("<III", raw)
        self.assertEqual(v0, 0x00820A70)
        self.assertEqual(v1, 0x00450910)
        self.assertEqual(v2, 0x00450910)

    def test_health_offset_disassembly(self):
        """Verify that ActionImpactHealth reads and modifies health at Attributes + 0x2F0."""
        # 0x94af77: 8b 47 20 -> mov eax, [edi + 0x20] (CKinActor::attributes)
        # 0x94af82: f3 0f 10 88 f0 02 00 00 -> movss xmm1, [eax + 0x2F0] (attributes::current_health)
        raw = self.read_va(0x94AF77, 19)
        self.assertEqual(raw[:3], bytes.fromhex("8b4720"))
        self.assertIn(bytes.fromhex("f30f1088f0020000"), raw)

    def test_position_distance_calculation(self):
        """Verify 3D Euclidean distance calculation uses Actor offsets 0x168 (X), 0x16C (Y), 0x170 (Z)."""
        # 0x95dd85: f3 0f 10 8e 68 01 00 00 -> movss xmm1, [esi + 0x168] (Position X)
        # 0x95dd8d: f3 0f 10 96 70 01 00 00 -> movss xmm2, [esi + 0x170] (Position Z)
        # 0x95dd95: f3 0f 58 86 6c 01 00 00 -> addss xmm0, [esi + 0x16C] (Position Y)
        raw = self.read_va(0x95DD85, 24)
        self.assertIn(bytes.fromhex("68010000"), raw)  # +0x168
        self.assertIn(bytes.fromhex("70010000"), raw)  # +0x170
        self.assertIn(bytes.fromhex("6c010000"), raw)  # +0x16C

    def test_facing_vector_normalization(self):
        """Verify CKinActorNav::SetFacingDirection stores normalized vector at Nav + 0x7B0."""
        # 0x95d66b: 0f 28 81 b0 07 00 00 -> facing_direction.x at +0x7B0
        # 0x95d677: 8b 81 b8 07 00 00       -> facing_direction.z at +0x7B8
        raw = self.read_va(0x95D66B, 24)
        self.assertIn(bytes.fromhex("b0070000"), raw)  # +0x7B0
        self.assertIn(bytes.fromhex("b8070000"), raw)  # +0x7B8

    def test_find_entity_by_id_loop(self):
        """Verify FindEntityById loop reads entity ID from Actor + 0x178."""
        # 0x8579b7: 39 b0 78 01 00 00 -> cmp [eax + 0x178], esi
        raw = self.read_va(0x8579B7, 6)
        self.assertEqual(raw, bytes.fromhex("39b078010000"))


if __name__ == "__main__":
    unittest.main()

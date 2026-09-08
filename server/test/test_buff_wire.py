"""Half-float buff durations and instance cancellation against independent bytes."""
import math
from pathlib import Path
import struct
import unittest

from server import buff_wire
from server.test.test_item_input import CAPTURE, item_capture
from server.test.test_cooldown_wire import CORPUS_ROOT, CORPUS_FILES, recorded_frames
from Tools.Teardown.inspect_item_constants import read_last_instance


NATIVE_BUFFS = Path("D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/55/551BCB541D80053BACD0A897B7993A77")


class TestBuffWireValidation(unittest.TestCase):
    def test_duration_is_half_float_and_instance_starts_at_offset_ten(self):
        payload = buff_wire.build_buff_add(1500, 1515, 1.5, 0x12345678, 268)
        self.assertEqual(len(payload), 22)
        self.assertEqual(struct.unpack_from(">eIH", payload, 8), (1.5, 0x12345678, 268))
        self.assertEqual(payload[16:], bytes(6))
        self.assertEqual(buff_wire.parse_buff_add(payload).instance_id, 0x12345678)

    def test_rejects_nonfinite_or_invalid_negative_duration(self):
        for duration in (math.nan, math.inf, -math.inf, -0.5, -2, 65505):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                buff_wire.build_buff_add(1500, 1500, duration, 10000, 259)
        for duration in (-1.0, 0.0, 5.0):
            self.assertEqual(buff_wire.parse_buff_add(
                buff_wire.build_buff_add(1500, 1500, duration, 10000, 259)).duration, duration)

    def test_rejects_malformed_add_and_cancel_shapes(self):
        add = buff_wire.build_buff_add(1500, 1500, 3.0, 10000, 270)
        cancel = buff_wire.build_buff_cancel(1500, 10000)
        for parser, valid in ((buff_wire.parse_buff_add, add), (buff_wire.parse_buff_cancel, cancel)):
            for payload in (valid[:-1], valid + bytes(1), valid[:-1] + b"\x01"):
                with self.subTest(parser=parser.__name__, payload=payload), self.assertRaises(ValueError):
                    parser(payload)

    def test_state_preserves_typed_native_words_without_float_coercion(self):
        words = (0x3F800000, 0xBF000000, 456, 0)
        payload = buff_wire.build_buff_state(1500, 1515, 2.5, 400000, 174, 7, words)
        value = buff_wire.parse_buff_state(payload)
        self.assertEqual(len(payload), 38)
        self.assertEqual(value.words, words)
        self.assertEqual(value.state_count, 7)
        self.assertEqual(value.encode(padded=False), payload[:34])
        with self.assertRaises(ValueError):
            buff_wire.parse_buff_state(payload[:-1] + b"\x01")

    @unittest.skipUnless(NATIVE_BUFFS.is_file(), "external native buff registry unavailable")
    def test_item_buff_ids_are_exact_native_pointer_registry_indices(self):
        instance, refs = read_last_instance(NATIVE_BUFFS)
        self.assertEqual(refs[0], 8)
        symbols = {"healing_flask": "HealingFlask", "reflex_block": "ReflexBlock",
                   "fountain_of_renewal": "FountainOfRenewal", "sprint_boots_sprint": "SprintBootsSprint",
                   "travel_boots_sprint": "TravelBootsSprint", "halcyon_chargers_sprint": "HalcyonChargersSprint",
                   "vision_totem_aura": "VisionTotemAura", "atlas_pauldron_slow": "AtlasPauldronSlow"}
        self.assertEqual(set(symbols), set(buff_wire.ITEM_BUFF_KINDS))
        for key, suffix in symbols.items():
            slot = 8 + 8 * buff_wire.ITEM_BUFF_KINDS[key]
            name_offset = refs[refs[slot]]
            name_end = instance.index(b"\0", name_offset)
            self.assertEqual(instance[name_offset:name_end].decode("ascii"), "Buff_Item_" + suffix)


@unittest.skipUnless(CAPTURE.is_file(), "external passive buff capture unavailable")
class TestBuffWireCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = item_capture()["s2c"]

    def test_every_add_and_cancel_rebuilds_exactly(self):
        adds = [row for row in self.frames if row.opcode == 1086]
        cancels = [row for row in self.frames if row.opcode == 1093]
        self.assertEqual(len(adds), 12810)
        self.assertEqual(len(cancels), 157)
        for row in adds:
            self.assertEqual(buff_wire.parse_buff_add(row.payload).encode(), row.payload)
        for row in cancels:
            self.assertEqual(buff_wire.build_buff_cancel(*buff_wire.parse_buff_cancel(row.payload)), row.payload)

    def test_cancel_addresses_prior_target_and_buff_instance(self):
        instances = {}
        matched = missing = 0
        for row in self.frames:
            if row.opcode == 1086:
                buff = buff_wire.parse_buff_add(row.payload)
                instances[buff.instance_id] = buff.target_eid
            elif row.opcode == 1093:
                target, instance = buff_wire.parse_buff_cancel(row.payload)
                if instance in instances:
                    self.assertEqual(instances[instance], target)
                    matched += 1
                else:
                    missing += 1
        self.assertEqual((matched, missing), (124, 33))
        # The remaining 33 cancels lack an earlier 1086. The next test proves
        # all of them address an earlier parameterized 1087 instead.

    def test_all_parameterized_states_rebuild_and_close_every_cancel_identity(self):
        seen = {}
        state_count = cancel_count = 0
        for row in self.frames:
            if row.opcode == 1086:
                buff = buff_wire.parse_buff_add(row.payload)
                seen[buff.instance_id] = buff.target_eid
            elif row.opcode == 1087:
                state = buff_wire.parse_buff_state(row.payload)
                self.assertEqual(state.encode(), row.payload)
                self.assertLessEqual(state.state_count, 40)
                seen[state.buff.instance_id] = state.buff.target_eid
                state_count += 1
            elif row.opcode == 1093:
                target, instance = buff_wire.parse_buff_cancel(row.payload)
                self.assertEqual(seen[instance], target)
                cancel_count += 1
        self.assertEqual((state_count, cancel_count), (1646, 157))

    @unittest.skipUnless(all((CORPUS_ROOT / name).is_file() for name in CORPUS_FILES),
                         "external decoded replay caches unavailable")
    def test_ordinary_item_snapshots_have_remaining_duration_and_unparameterized_state(self):
        seen = set()
        for name, index, opcode, payload in recorded_frames():
            if opcode != 1087 or len(payload) < 16:
                continue
            kind = struct.unpack_from(">H", payload, 14)[0]
            if kind not in (29, 270, 279):
                continue
            state = buff_wire.parse_buff_state(payload)
            self.assertEqual(state.encode(padded=len(payload) == 38), payload)
            self.assertEqual((state.state_count, state.words), (1, (0, 0, 0, 0)))
            self.assertGreater(state.buff.duration, 0)
            self.assertLess(state.buff.duration, {29: 2.0, 270: 3.0, 279: 2.0}[kind])
            seen.add(kind)
        self.assertEqual(seen, {29, 270, 279})

    def test_measured_item_duration_categories(self):
        expected = {259: {5.0}, 268: {1.5}, 270: {3.0}, 279: {2.0}, 287: {-1.0}}
        observed = {kind: set() for kind in expected}
        for row in self.frames:
            if row.opcode == 1086:
                buff = buff_wire.parse_buff_add(row.payload)
                if buff.kind in observed:
                    observed[buff.kind].add(buff.duration)
        self.assertEqual(observed, expected)


if __name__ == "__main__":
    unittest.main()

"""Complete payload and ordering checks from external basic attacks."""
import os
from pathlib import Path
import struct
import unittest

from server import attack_wire
from server import decode
from server.test.test_corpus import VGFULL_PCAP, _cached_frames


class TestMeasuredVariantSelection(unittest.TestCase):
    def test_known_heroes_use_their_own_measured_variants_and_unknown_stays_unknown(self):
        self.assertEqual([attack_wire.basic_variant_for(925, i) for i in range(4)], [8, 9, 8, 9])
        self.assertEqual(attack_wire.basic_variant_for(245), 9)
        self.assertEqual(attack_wire.basic_variant_for(279), 7)
        self.assertEqual(attack_wire.basic_variant_for(399), 10)
        self.assertIsNone(attack_wire.basic_variant_for(99999))


class TestOtherRecordedHeroAttacks(unittest.TestCase):
    def test_amael_koshka_phinn_and_catherine_variants_match_external_attack_payloads(self):
        root = Path(os.environ.get('TEMP', ''))
        session = 'ea4c7fda-4b61-481d-abb7-1c757d24ae58-'
        samples = [
            ('vg_phaseB/vgr_live', '0e7de8af-96d9-4e3a-b3c2-609ed5e71120', 15, 1057, 1096, 925),
            ('vg_phaseB/vgr_live', '0e7de8af-96d9-4e3a-b3c2-609ed5e71120', 29, 252, 285, 925),
            ('vg_max/vgr2', '591146df-33f2-4f12-9a04-8d800d239821', 5, 815, 870, 245),
            ('vg_max/vgr5b', '045f86d4-7ef2-4125-a835-e70a96288c88', 4, 344, 361, 279),
            ('vg_max/vgr5b', '045f86d4-7ef2-4125-a835-e70a96288c88', 4, 1067, 1082, 279),
            ('vg_phaseB/vgr_live', '1574e27a-e851-492b-8d91-94fc4bd66985', 4, 715, 724, 242),
            ('vg_phaseB/vgr_live', '1574e27a-e851-492b-8d91-94fc4bd66985', 5, 234, 281, 242),
        ]
        paths = [root / folder / f'{session}{match}.{chunk}.vgr' for folder, match, chunk, *_ in samples]
        if not all(path.is_file() for path in paths):
            self.skipTest('external multi-match hero attack corpus unavailable')
        for path, (_, _, _, start, impact, hero_id) in zip(paths, samples):
            frames, stats = decode.walk_vgr(path)
            self.assertEqual(stats['failures'], 0)
            _, opcode, payload = frames[start]
            self.assertEqual(opcode, 1045)
            source, target = struct.unpack_from('>II', payload)
            self.assertIn(payload[8], attack_wire.MEASURED_BASIC_VARIANTS[hero_id])
            self.assertEqual(attack_wire.build_attack_start(source, target, payload[8]), payload)
            _, opcode, damage = frames[impact]
            self.assertEqual(opcode, 1054)
            self.assertEqual(struct.unpack_from('>II', damage), (target, source))
            self.assertLess(struct.unpack_from('>f', damage, 8)[0], 0)
            self.assertEqual(damage[13], 5)


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), 'external vgfull corpus unavailable')
class TestCorpusBasicAttacks(unittest.TestCase):
    def test_all_127_adagio_attacks_and_108_baptiste_attacks_start_with_current_position(self):
        frames, _ = _cached_frames()
        counts = {1516: 0, 1517: 0}
        variants = {1516: attack_wire.ADAGIO_BASIC_VARIANTS, 1517: attack_wire.BAPTISTE_BASIC_VARIANTS}
        for index, (opcode, payload) in enumerate(frames):
            if opcode != 1045 or len(payload) != 14:
                continue
            source, target = struct.unpack_from('>II', payload)
            if source not in variants or payload[8] not in variants[source]:
                continue
            position_opcode, position = frames[index + 1]
            self.assertEqual(position_opcode, 1070)
            eid, x, y = struct.unpack_from('>Iff', position)
            self.assertEqual(eid, source)
            rebuilt = attack_wire.build_attack_start_frames(source, target, payload[8], x, y)
            self.assertEqual(rebuilt, frames[index:index + 2])
            counts[source] += 1
        self.assertEqual(counts, {1516: 127, 1517: 108})

    def test_two_adagio_basic_cycles_require_two_attack_actions(self):
        frames, _ = _cached_frames()
        for start, impact in ((4675, 4756), (4807, 4913)):
            self.assertEqual(frames[start], (1045, attack_wire.build_attack_start(1516, 4478, 8)))
            self.assertEqual(frames[impact][0], 1054)
            self.assertEqual(struct.unpack_from('>IIf', frames[impact][1]), (4478, 1516, -82.5))
            # The 1038 action used by projectile/effect sequences is absent.
            # Other actors' ordinary 1010 spawns interleave in these windows.
            self.assertFalse(any(op == 1038 for op, _ in frames[start:impact]))

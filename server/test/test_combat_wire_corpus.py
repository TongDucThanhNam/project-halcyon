"""Real-corpus guards for the previously reversed victim and stat meanings."""
import os
import struct
import unittest

from server import hero_balance, roster, wire
from server.test.test_corpus import VGFULL_PCAP, _cached_frames


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), "external vgfull corpus unavailable")
class TestCombatWireCorpus(unittest.TestCase):
    def test_baptiste_basic_attack_targets_minion(self):
        frames, _ = _cached_frames()
        opcode, payload = frames[3438]
        self.assertEqual(opcode, wire.OP.COMBAT_DELTA)
        self.assertEqual(struct.unpack_from(">IIf", payload), (4315, 1517, -78.0))
        # 1517 is Baptiste, with 78 WP; 4315 is a lane minion.
        rebuilt = roster.build_combat_delta(1517, 4315, -78, tail=roster.COMBAT_DELTA_HERO_TAIL)
        self.assertEqual(rebuilt + bytes(len(payload) - len(rebuilt)), payload)

    def test_inventory_purchase_deducts_gold_not_health(self):
        frames, _ = _cached_frames()
        self.assertEqual(frames[2293][0], wire.OP.INVENTORY_SLOT)
        opcode, payload = frames[2294]
        self.assertEqual(opcode, wire.OP.ENTITY_STAT)
        self.assertEqual(payload, roster.build_hero_stat(1516, -300, roster.STAT_GOLD))
        self.assertEqual(frames[2295][0], 1085)

    def test_cast_spends_energy_and_fountain_regenerates_energy(self):
        frames, _ = _cached_frames()
        self.assertEqual(frames[2596], (wire.OP.ENTITY_STAT,
            roster.build_hero_stat(1500, -40, roster.STAT_ENERGY)))
        self.assertEqual(frames[481], (wire.OP.ENTITY_STAT,
            roster.build_hero_stat(1500, 10.3125, roster.STAT_ENERGY)))
        self.assertEqual(10.3125, hero_balance.STATS['Amael'].energy_base * .0375)

    def test_health_regeneration_uses_type_zero(self):
        frames, _ = _cached_frames()
        payload = next(p for op, p in frames if op == wire.OP.ENTITY_STAT and p[8] == 0)
        eid, delta = struct.unpack_from(">If", payload)
        self.assertGreater(delta, 0)
        self.assertEqual(payload, roster.build_hero_stat(eid, delta, roster.STAT_HEALTH))


class TestHeroIdentity(unittest.TestCase):
    def test_named_id_joins_match_six_independent_initial_stats(self):
        offsets = {42: 'health_base', 74: 'move_speed', 122: 'energy_base',
                   190: 'armor_base', 202: 'shield_base', 214: 'weapon_base'}
        for hero_id, name in hero_balance.HERO_NAMES.items():
            if hero_id not in roster.HERO_INIT_DATA:
                continue
            with self.subTest(hero_id=hero_id, name=name):
                data = bytearray(750)
                for offset, value in roster.HERO_INIT_DATA[hero_id]['runs'].items():
                    value = bytes.fromhex(value)
                    data[offset:offset + len(value)] = value
                for offset, field in offsets.items():
                    self.assertAlmostEqual(struct.unpack_from('>f', data, offset)[0],
                                           getattr(hero_balance.STATS[name], field), places=4)

    def test_unknown_id_is_not_assigned_an_unrelated_hero(self):
        self.assertNotIn(65535, hero_balance.HERO_NAMES)
        self.assertEqual(hero_balance.HERO_NAMES[924], 'Viola')
        self.assertEqual(hero_balance.HERO_NAMES[245], 'Koshka')

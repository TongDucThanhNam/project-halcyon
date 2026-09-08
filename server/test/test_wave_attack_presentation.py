"""Ground lane action ordinals and preserve the existing combat cadence."""
import os
from pathlib import Path
import struct
import unittest

from Tools.Teardown.inspect_jungle_actions import read_jungle_actions
from server import attack_wire, decode, wave
from server.hero_movement import HeroMovement
from server.status_effects import StatusEffect, StatusManager, StatusType


class TestLaneAttackEvidence(unittest.TestCase):
    def test_native_npc_vectors_match_melee_ranged_siege_and_captain_actions(self):
        root = Path('D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data')
        paths = {
            365: '74/74C3647809896C485179091260963244',
            366: '8D/8D300EEC712D921FE908FC39FD554FAB',
            367: 'AD/ADC34CE1748BA32E0A631949404BB60D',
            368: '1E/1E7A3B02E8305164AAA32F953749D112',
        }
        if not all((root / path).is_file() for path in paths.values()):
            self.skipTest('operator-owned lane CFFs unavailable')
        for archetype, path in paths.items():
            with self.subTest(archetype=archetype):
                rows = read_jungle_actions(root / path)
                expected = (attack_wire.MELEE_MINION_BASIC_VARIANTS if archetype == 366
                            else attack_wire.RANGED_MINION_BASIC_VARIANTS)
                self.assertEqual(tuple(row['index'] for row in rows), expected)
                self.assertTrue(all('Attack' in row['name'] for row in rows))
                self.assertTrue(all('Crit' not in row['name'] for row in rows))
                if archetype == 366:
                    self.assertTrue(all('DefaultMeleeAttack' in row['name'] for row in rows))
                elif archetype in (365, 368):
                    self.assertTrue(all('DefaultRangedAttack' in row['name'] for row in rows))
                else:
                    self.assertEqual([row['name'].split('__')[-1] for row in rows],
                                     ['DefaultAttack', 'AltAttack'])

    def test_nine_complete_native_actions_and_later_damage_pairs(self):
        root = Path(os.environ.get('TEMP', '')) / 'vg_max/vgr2'
        prefix = 'ea4c7fda-4b61-481d-abb7-1c757d24ae58-591146df-33f2-4f12-9a04-8d800d239821'
        paths = {chunk: root / f'{prefix}.{chunk}.vgr' for chunk in (3, 10, 11)}
        if not all(path.is_file() for path in paths.values()):
            self.skipTest('operator-owned lane action corpus unavailable')
        decoded = {}
        for chunk, path in paths.items():
            decoded[chunk], stats = decode.walk_vgr(path)
            self.assertEqual(stats['failures'], 0)
        samples = [
            (365, 3, 451, 3, 542), (365, 3, 560, 3, 886),
            (366, 3, 379, 3, 428), (366, 3, 326, 3, 358), (366, 3, 330, 3, 361),
            (367, 3, 377, 3, 485), (367, 3, 839, 3, 947),
            (368, 11, 464, 11, 614), (368, 10, 1270, 11, 264),
        ]
        seen = set()
        for archetype, chunk, start, end_chunk, impact in samples:
            frames = decoded[chunk]
            token, opcode, payload = frames[start]
            self.assertEqual(opcode, 1045)
            source, target = struct.unpack_from('>II', payload)
            self.assertEqual(attack_wire.build_attack_start(source, target, payload[8]), payload)
            self.assertEqual(frames[start + 1][1], 1086)
            impact_token, opcode, damage = decoded[end_chunk][impact]
            self.assertEqual(opcode, 1054)
            self.assertEqual(struct.unpack_from('>II', damage), (target, source))
            self.assertLess(struct.unpack_from('>f', damage, 8)[0], 0)
            self.assertEqual(damage[13], 5)
            seconds = lambda token: struct.unpack('>f', struct.pack('>I', token))[0]
            self.assertGreater(seconds(impact_token), seconds(token))
            if archetype == 365:
                self.assertTrue(1.38 < seconds(impact_token) - seconds(token) < 1.41)
                self.assertNotIn(1038, [op for _, op, _ in frames[start:impact + 1]])
            seen.add((archetype, payload[8]))
        self.assertEqual(seen, {(a, v) for a in (365, 367, 368) for v in (0, 1)}
                         | {(366, v) for v in (0, 1, 2)})


class TestLaneAttackCadence(unittest.TestCase):
    def pair(self, pair_index=0):
        director = wave.Director(0)
        minion = wave.Minion(4610, 1, 0, pair_index)
        minion.x, minion.y = 0, 0
        hero = HeroMovement(eid=1517, team=2, x=1, y=0)
        minion.target_hero = hero
        director.minions = [minion]
        return director, minion, hero

    def test_melee_ranged_siege_actions_keep_their_cadence_while_contacts_are_delayed(self):
        for pair_index, expected in ((0, [0, 1, 2]), (3, [0, 1, 0]), (5, [0, 1, 0])):
            with self.subTest(pair=pair_index):
                director, minion, hero = self.pair(pair_index)
                contacts = []
                def hit(a, b, amount, kind, now):
                    contacts.append((a.eid, b.eid, amount, kind, now))
                    return [(1054, b'contact')]
                now = 1
                for variant in expected:
                    frames = director._combat(now, damage_callback=hit)
                    actions = [body for op, body in frames if op == 1045]
                    self.assertEqual(len(actions), 1)
                    self.assertEqual(struct.unpack_from('>II', actions[0]), (minion.eid, hero.eid))
                    self.assertEqual(actions[0][8], variant)
                    self.assertNotIn(1045, [op for op, _ in director._combat(now + 0.05, damage_callback=hit)])
                    now = minion.next_attack_at
                director._resolve_contacts(now + 2, damage_callback=hit)
                self.assertEqual([c[2:4] for c in contacts], [(minion.attack_damage, 'weapon')] * 3)
                self.assertEqual(minion.attack_ordinal, 3)

    def test_no_action_while_stunned_out_of_range_dead_or_not_spawned(self):
        for state in ('stunned', 'out_of_range', 'dead', 'not_spawned'):
            with self.subTest(state=state):
                director, minion, hero = self.pair()
                status = StatusManager()
                if state == 'stunned':
                    status.apply_effect(StatusEffect('test_stun', StatusType.STUN,
                                                     hero.eid, minion.eid, 3, 0, 3))
                elif state == 'out_of_range':
                    hero.teleport(5, 0)
                elif state == 'dead':
                    minion.alive = False
                else:
                    minion.spawn_at = 2
                self.assertEqual(director._combat(1, status_manager=status), [])
                self.assertEqual(minion.attack_ordinal, 0)


if __name__ == '__main__':
    unittest.main()

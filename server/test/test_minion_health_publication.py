"""Spawn resource agreement against the recovered native setter/clamp contract."""
import struct
import unittest

from server import roster, wave


class MinionHealthPublication(unittest.TestCase):
    def test_initial_and_late_melee_ranged_siege_publish_full_authoritative_pool(self):
        # Deliberately varied native defaults: the publication must not need a
        # guessed base-health constant or depend on the client's minion age.
        for pair, baseline in ((0,575), (3,475), (5,1), (5,10000)):
            for minute in (0, 2, 15):
                with self.subTest(pair=pair, minute=minute, baseline=baseline):
                    director = wave.Director(0)
                    frames = director._spawn_pair(minute*60, pair)
                    for actor in director.minions:
                        current = maximum = float(baseline)
                        created = False
                        for op, p in frames:
                            if op == 1010 and struct.unpack_from('>I',p,8)[0] == actor.eid:
                                created = True
                            if op not in (1052,1053) or struct.unpack_from('>I',p)[0] != actor.eid:
                                continue
                            self.assertTrue(created)
                            if op == 1052:
                                self.assertEqual(p[12:], bytes((0,0,1))+bytes(7))
                                maximum = struct.unpack_from('>f',p,8)[0]
                                current = min(current, maximum)
                            else:
                                self.assertEqual(p[8:], bytes((0,0,1,0,0,0)))
                                current = min(maximum, current+struct.unpack_from('>f',p,4)[0])
                        self.assertAlmostEqual(maximum, actor.max_hp, places=3)
                        self.assertAlmostEqual(current, actor.hp, places=3)

    def test_reconnect_creation_does_not_refill_an_injured_actor(self):
        director = wave.Director(0)
        director._spawn_pair(0,0)
        director.minions[0].hp = 12
        frames = director.get_spawn_frames(1)
        self.assertFalse(any(op in (1052,1053) for op,_ in frames))
        self.assertEqual(director.minions[0].hp,12)

    def test_absolute_setter_is_distinct_from_equipment_delta(self):
        absolute = roster.build_entity_base_attribute(4610,735,0)
        additive = roster.build_entity_attribute(4610,735,0)
        self.assertEqual(struct.unpack_from('>IIf',absolute), (4610,0xffffffff,735))
        self.assertEqual(absolute[12:15],bytes((0,0,1)))
        self.assertEqual(additive[12:15],bytes((0,1,0)))


if __name__ == '__main__':
    unittest.main()

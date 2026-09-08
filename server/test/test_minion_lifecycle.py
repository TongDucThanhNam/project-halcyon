"""Native death precedes removal; corpses keep slots and cannot act."""
import os
import struct
import unittest

from server import roster, wave
from server.actor_slots import ActorSlots
from server.hero_movement import HeroMovement
from server.lifecycle_wire import build_hero_death
from server.test.test_corpus import VGFULL_PCAP, _cached_frames


class TestMinionCorpse(unittest.TestCase):
    def test_lethal_hit_marks_death_once_and_retains_slot_until_exact_removal_boundary(self):
        slots = ActorSlots(capacity=8)
        director = wave.Director(0, actor_slots=slots, combat=False)
        director._spawn_pair(0, 0)
        victim = director.minions[0]
        hero = HeroMovement()
        slot = slots.by_eid[victim.eid]
        death = director.apply_hero_damage_to_minion(victim.eid, victim.hp, hero, now=1)
        self.assertEqual(death, [(1072, build_hero_death(victim.eid, hero.eid))])
        self.assertFalse(victim.alive)
        self.assertEqual(victim.hp, 0)
        self.assertEqual(director.on_minion_death(victim, hero.eid, 2), [])
        self.assertEqual(slots.by_eid[victim.eid], slot)
        with self.assertRaises(RuntimeError):
            slots.allocate(90000)
        position = victim.position_fixed
        before_due = director.pump(4.799)
        self.assertFalse(any(op in (1073, 1035) for op, _ in before_due))
        self.assertFalse(any(op == 1070 and struct.unpack_from('>I', p)[0] == victim.eid for op, p in before_due))
        self.assertEqual(victim.position_fixed, position)
        removal = director.pump(4.8)
        self.assertEqual([(op, p) for op, p in removal if op in (1073, 1035)],
                         [(1073, roster.build_destroy(victim.eid)), (1035, roster.build_despawn(victim.eid))])
        self.assertEqual(slots.allocate(90000), slot)
        self.assertFalse(any(op in (1073, 1035) for op, _ in director.pump(5)))

    def test_minion_lethal_hit_uses_same_death_state_and_dead_actor_cannot_retaliate(self):
        director = wave.Director(0)
        director._spawn_pair(0, 0)
        right, left = director.minions
        right.x, right.y, left.x, left.y = 1, 5, -0.5, 5
        left.hp = 1
        frames = director.pump(0)
        self.assertTrue(left.alive)
        self.assertFalse(any(op in (1054, 1072) for op, _ in frames))
        frames = director.pump(0.5)
        self.assertFalse(left.alive)
        self.assertEqual(right.hp, right.max_hp)
        self.assertEqual([op for op, _ in frames if op in (1054, 1072, 1073, 1035)], [1054, 1072])
        self.assertIn(left.eid, director.actor_slots.by_eid)


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), 'external native lane corpus unavailable')
class TestNativeMinionDeath(unittest.TestCase):
    def test_all_83_recorded_minion_removals_follow_byte_exact_death_and_destroy(self):
        frames, _ = _cached_frames()
        archetypes = {struct.unpack_from('>I', p, 8)[0]: struct.unpack_from('>I', p)[0]
                      for op, p in frames if op == 1010 and len(p) == 126}
        deaths, destroys, removed = {}, {}, []
        for index, (opcode, payload) in enumerate(frames):
            if opcode not in (1072, 1073, 1035):
                continue
            eid = struct.unpack_from('>I', payload)[0]
            if archetypes.get(eid) not in (365, 366, 367, 368):
                continue
            if opcode == 1072:
                self.assertEqual(payload, build_hero_death(eid, struct.unpack_from('>I', payload, 4)[0]))
                deaths[eid] = index
            elif opcode == 1073:
                self.assertIn(eid, deaths)
                self.assertEqual(payload, roster.build_destroy(eid))
                self.assertGreater(index, deaths[eid])
                destroys[eid] = index
            else:
                self.assertIn(eid, destroys)
                self.assertEqual(payload, roster.build_despawn(eid))
                self.assertGreater(index, destroys[eid])
                removed.append(eid)
        self.assertEqual(len(removed), 83)

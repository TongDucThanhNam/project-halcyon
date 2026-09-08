"""Slot ownership regressions, including actual removal/reuse sequences."""
import os
import struct
import unittest

from server.actor_slots import ActorSlots
from server import jungle, wave
from server.hero_movement import HeroMovement
from server.test.test_corpus import VGFULL_PCAP, _cached_frames
from server.test.test_entity_spawn import original_test_catalog


class TestActorSlots(unittest.TestCase):
    def test_register_measured_sparse_map_does_not_confuse_count_with_slot(self):
        slots = ActorSlots()
        slots.register(1500, 0)
        slots.register(3000, 6)
        slots.register(3001, 17)
        self.assertEqual(slots.allocate(100000), 7)
        self.assertEqual(slots.allocate(100000), 7)
        with self.assertRaises(ValueError):
            slots.register(4000, 17)
        with self.assertRaises(ValueError):
            slots.register(3000, 18)

    def test_exhaustion_never_wraps_into_hero_or_live_actor(self):
        slots = ActorSlots(capacity=8)
        self.assertEqual((slots.allocate(100), slots.allocate(101)), (6, 7))
        with self.assertRaises(RuntimeError):
            slots.allocate(102)
        self.assertEqual(slots.release(100), 6)
        self.assertEqual(slots.allocate(102), 6)
        self.assertEqual(slots.by_eid[101], 7)

    def test_six_hundred_successive_wave_spawns_reuse_only_removed_actors(self):
        slots = ActorSlots(reserved_slots=range(33))
        director = wave.Director(0, actor_slots=slots)
        hero = HeroMovement()
        for index in range(300):
            frames = director._spawn_pair(index, 0)
            for spawn, move in ((frames[0][1], frames[1][1]), (frames[3][1], frames[4][1])):
                eid = struct.unpack_from('>I', spawn, 8)[0]
                self.assertEqual(spawn[116], slots.by_eid[eid])
                self.assertEqual(move[0], spawn[116])
                self.assertIn(spawn[116], (33, 34))
            for minion in director.minions[-2:]:
                death = director.apply_hero_damage_to_minion(minion.eid, minion.hp, hero, now=index * 4)
                self.assertEqual([op for op, _ in death], [1072])
                self.assertIn(minion.eid, slots.by_eid)
            removal = director._flush_removals(index * 4 + director.rules.corpse_duration)
            self.assertEqual([op for op, _ in removal], [1073, 1035, 1073, 1035])
            for minion in director.minions[-2:]:
                self.assertNotIn(minion.eid, slots.by_eid)
        self.assertEqual(len(director.minions), 600)
        self.assertEqual(set(slots.by_slot), set(range(33)))

    def test_jungle_and_waves_share_slots_and_reconnect_retains_owners(self):
        slots = ActorSlots(reserved_slots=range(33))
        manager = jungle.JungleManager(actor_slots=slots)
        first = manager.get_spawn_frames(catalog=original_test_catalog())
        director = wave.Director(0, actor_slots=slots)
        wave_frames = director._spawn_pair(0, 0)
        self.assertEqual([p[116] for op, p in wave_frames if op == 1010], [45, 46])
        second = manager.get_spawn_frames()
        self.assertEqual(first, second)
        self.assertEqual(len(slots.by_eid), 14)


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), 'external vgfull corpus unavailable')
class TestCorpusActorSlots(unittest.TestCase):
    def test_all_174_spawns_follow_live_ownership_and_116_reuses_follow_removal(self):
        slots = ActorSlots()
        frames, _ = _cached_frames()
        previous_owners, removed, spawns, reused = {}, set(), 0, 0
        for opcode, payload in frames:
            if opcode == 1035 and len(payload) >= 4:
                removed.add(struct.unpack_from('>I', payload)[0])
            if opcode == 1010 and len(payload) == 126:
                eid, slot = struct.unpack_from('>I', payload, 8)[0], payload[116]
                spawns += 1
                if slot in previous_owners:
                    reused += 1
                    self.assertIn(previous_owners[slot], removed)
                previous_owners[slot] = eid
            slots.observe(opcode, payload)
        self.assertEqual((spawns, reused), (174, 116))

"""History-free wave traversal and order-preserving spatial broad phase."""
import gc
import math
import unittest
import weakref
from unittest.mock import patch

from server import wave
from server.actor_slots import ActorSlots


class GuardedHistory(list):
    """After indexing, even reading the retired prefix is a test failure."""
    indexed = 0

    def __iter__(self):
        raise AssertionError('tick traversed retained minion history')

    def __getitem__(self, key):
        if not isinstance(key, slice) or (key.start or 0) < self.indexed:
            raise AssertionError('tick read an already-indexed history prefix')
        return super().__getitem__(key)


class AllCandidates:
    """Original full-fighter scan as a narrow-phase ordering oracle."""
    def __init__(self, fighters):
        self.fighters = fighters

    def near(self, minion, radius):
        return self.fighters

    def update(self, minion):
        pass


class TestWaveIndexes(unittest.TestCase):
    def test_spawn_death_corpse_removal_and_slot_reuse_preserve_history(self):
        director = wave.Director(0, actor_slots=ActorSlots(capacity=8))
        director._spawn_pair(0, 0)
        first = list(director.minions)
        slots = [director.actor_slots.by_eid[m.eid] for m in first]
        index = director._minion_index()
        self.assertEqual(list(index.present.values()), first)
        for minion in first:
            director.on_minion_death(minion, 1500, 1)
        self.assertEqual(list(index.present.values()), first)
        self.assertEqual(director._present_at(4.799), first)
        self.assertEqual(director._flush_removals(4.799), [])
        self.assertEqual([op for op, _ in director._flush_removals(4.8)],
                         [1073, 1035, 1073, 1035])
        self.assertEqual(list(index.present.values()), [])
        self.assertEqual(director._present_at(4.8), [])
        self.assertEqual(director.minions, first)
        self.assertTrue(all(index.actors[m.eid] is m for m in first))
        director._spawn_pair(5, 1)
        second = list(director.present_minions())
        self.assertEqual(second, director.minions[2:])
        self.assertEqual([director.actor_slots.by_eid[m.eid] for m in second], slots)
        self.assertTrue(set(m.eid for m in first).isdisjoint(m.eid for m in second))
        self.assertEqual(director._flush_removals(6), [])

    def test_steady_ticks_and_contacts_never_scan_indexed_history(self):
        director = wave.Director(0)
        director._spawn_pair(0, 0)
        right, left = director.minions
        right.x, right.y, left.x, left.y = 0, 0, 1, 0
        retired = [wave.Minion(10000 + i, 1, 0) for i in range(256)]
        for minion in retired:
            minion.alive, minion.hp = False, 0
        history = GuardedHistory(retired + [right, left])
        director.minions = history
        director._minion_index()
        history.indexed = len(history)
        director.pump(.05)
        self.assertTrue(director.pending_contacts)
        director.pump(.1)
        director.pump(1.4)
        self.assertLess(right.hp + left.hp, right.max_hp + left.max_hp)
        director._spawn_pair(2, 1)
        self.assertEqual(len(list(director.present_minions())), 4)
        history.indexed = len(history)
        director.pump(2)
        self.assertEqual(len(director._minion_index().actors), 260)

    def test_replacing_history_rebuilds_identity_index_for_contacts(self):
        director = wave.Director(0)
        director._spawn_pair(0, 3)
        previous = director.minions[0]
        director._minion_index()
        replacement = wave.Minion(previous.eid, previous.side, 0, 3)
        director.minions = [replacement]
        self.assertEqual(list(director.present_minions()), [replacement])
        self.assertIs(director._minion_index().actors[previous.eid], replacement)

    def test_discarding_cache_reconstructs_same_presence_and_retained_identities(self):
        director = wave.Director(0)
        director._spawn_pair(0, 0)
        first, second = director.minions
        director.on_minion_death(first, 1500, 1)
        director.on_minion_death(second, 1500, 2)
        director._flush_removals(4.8)
        before = director.get_spawn_frames(4.8), director.get_death_frames(4.8)
        wave._MINION_INDEXES.pop(director)
        self.assertEqual(list(director.present_minions()), [second])
        self.assertEqual((director.get_spawn_frames(4.8), director.get_death_frames(4.8)), before)
        self.assertEqual(director._minion_index().actors, {m.eid: m for m in director.minions})

    def test_weak_cache_does_not_retain_completed_director(self):
        director = wave.Director(0)
        director._spawn_pair(0, 0)
        index = director._minion_index()
        reference = weakref.ref(director)
        del director
        gc.collect()
        self.assertIsNone(reference())
        self.assertEqual(len(index.actors), 2)


class TestWaveNeighborhood(unittest.TestCase):
    def test_candidates_cover_exact_radius_and_preserve_order_across_cell_boundaries(self):
        coordinates = (-16.000001, -8, -.000001, 0, 7.999999, 8, 16.000001)
        fighters = []
        for x in coordinates:
            for y in coordinates:
                minion = wave.Minion(2000 - len(fighters), 1, 0)
                minion.x, minion.y = x, y
                fighters.append(minion)
        grid = wave._MinionNeighborhood(fighters)
        for minion in fighters:
            for radius in (0, .000001, .75, 6.5, 8, 8.000001):
                nearby = grid.near(minion, radius)
                self.assertEqual(nearby, [m for m in fighters if m in nearby])
                self.assertTrue(all(m in nearby for m in fighters
                                    if wave.Director._dist(minion, m) <= radius))
        moved = fighters[0]
        moved.x, moved.y = 24, -24
        grid.update(moved)
        self.assertIn(moved, grid.near(moved, 0))
        self.assertNotIn(moved, grid.near(fighters[1], 0))
        self.assertEqual(grid.near(moved, math.inf), fighters)
        self.assertEqual(grid.near(moved, math.nan), fighters)

    def test_sequential_movement_and_combat_match_full_scan_oracle(self):
        indexed, exhaustive = wave.Director(0), wave.Director(0)
        deaths = 0
        for tick in range(1, 1801):
            now = tick * .05
            actual = indexed.pump(now)
            with patch.object(wave, '_MinionNeighborhood', AllCandidates):
                expected = exhaustive.pump(now)
            self.assertEqual(actual, expected, f'wire mismatch at tick {tick}')
            deaths += sum(op == 1072 for op, _ in actual)
            for a, b in zip(indexed.minions, exhaustive.minions):
                self.assertEqual((a.position_fixed, a.hp, a.alive, a.seg,
                                  a.next_attack_at, a._move_destination),
                                 (b.position_fixed, b.hp, b.alive, b.seg,
                                  b.next_attack_at, b._move_destination))
        self.assertGreater(deaths, 0)
        self.assertEqual(len(indexed.minions), len(exhaustive.minions))


if __name__ == '__main__':
    unittest.main()

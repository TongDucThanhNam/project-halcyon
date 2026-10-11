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
    def test_removed_history_and_indexes_are_bounded_and_serials_forget_only_removed(self):
        from server.status_effects import StatusEffect, StatusManager, StatusType
        director = wave.Director(1_000_000, combat=False)
        statuses = StatusManager()
        statuses.apply_effect(StatusEffect('hero', StatusType.STUN, 1500, 1500, 1, 0, 1))
        hero_serial = statuses.get_attack_interrupt_serial(1500)
        previous_eid = 0
        for generation in range(50):
            now = generation * 10.0
            director._spawn_pair(now, 0)
            actors = list(director.minions)
            self.assertEqual(len(actors), 2)
            self.assertGreater(actors[0].eid, previous_eid)
            previous_eid = actors[-1].eid
            for actor in actors:
                statuses.apply_effect(StatusEffect('cc', StatusType.STUN, 1500, actor.eid, 1, now, now+1))
                director.on_minion_death(actor, 1500, now)
            director._flush_removals(now+3.799, statuses)
            self.assertEqual(len(director.minions), 2)
            director._flush_removals(now+3.8, statuses)
            self.assertEqual(director.minions, [])
            self.assertEqual(director._minion_index().actors, {})
            self.assertEqual(list(director.present_minions()), [])
            self.assertEqual(set(statuses._attack_interrupt_serial), {1500})
            self.assertEqual(statuses.get_attack_interrupt_serial(1500), hero_serial)
            statuses.clean_expired(now+4)
            # Scheduled spawn-state references expire through the real pump,
            # with automatic waves not due during this manual-spawn fixture.
            director.pump(now+4, status_manager=statuses)
            self.assertEqual(director.pending_states, [])

    def test_released_contact_survives_source_removal_but_dead_windup_does_not(self):
        for released in (True, False):
            with self.subTest(released=released):
                director = wave.Director(0)
                director._spawn_pair(0, 3)
                source, target = director.minions
                director.pending_contacts = [wave.PendingMinionContact(
                    100, 1, source, target, source.eid, target.eid, 17,
                    release_tick=10, released=released)]
                director.on_minion_death(source, 1500, 0)
                director._flush_removals(3.8)
                self.assertNotIn(source.eid, director._minion_index().actors)
                before = target.hp
                frames = director._resolve_contacts(5)
                self.assertEqual(target.hp, before - (17 if released else 0))
                self.assertEqual([op for op, _ in frames], [1054] if released else [])
                self.assertEqual(director.pending_contacts, [])

    def test_contact_to_removed_target_is_discarded(self):
        director = wave.Director(0)
        director._spawn_pair(0, 3)
        source, target = director.minions
        director.pending_contacts = [wave.PendingMinionContact(
            100, 1, source, target, source.eid, target.eid, 17, released=True)]
        director.on_minion_death(target, 1500, 0)
        director._flush_removals(3.8)
        self.assertEqual(director._resolve_contacts(5), [])
        self.assertEqual(director.pending_contacts, [])

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

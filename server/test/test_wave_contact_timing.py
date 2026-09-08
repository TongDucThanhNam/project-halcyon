"""Empirical NPC contact policy: exact tick boundaries and original identities."""
import unittest
import os
from pathlib import Path
import struct

from server import decode, wave
from server.hero_movement import HeroMovement
from server.status_effects import StatusEffect, StatusManager, StatusType


class TestWaveContactTiming(unittest.TestCase):
    def actors(self, pair=0, t0=0):
        director = wave.Director(t0)
        source = wave.Minion(4610, 1, t0, pair)
        source.x, source.y = 0, 0
        target = HeroMovement(eid=1517, team=2, x=1, y=0)
        source.target_hero = target
        director.minions = [source]
        return director, source, target

    def test_native_release_precedes_contact_with_recorded_timing_spread(self):
        path = Path(os.environ.get('TEMP', '')) / ('vg_phaseB/vgr_live/'
            'ea4c7fda-4b61-481d-abb7-1c757d24ae58-a683aa80-9811-47c3-bb64-0731a802e889.3.vgr')
        if not path.is_file():
            self.skipTest('operator-owned ranged release corpus unavailable')
        frames, stats = decode.walk_vgr(path)
        self.assertEqual(stats['failures'], 0)
        seconds = lambda token: struct.unpack('>f', struct.pack('>I', token))[0]
        samples = ((334, 380, 440), (421, 463, 527), (490, 528, None),
                   (921, 1003, None), (1001, 1051, None))
        delays = []
        for action, launch, contact in samples:
            self.assertEqual(frames[action][1], 1045)
            self.assertEqual(frames[launch][1], 1037)
            delay = seconds(frames[launch][0]) - seconds(frames[action][0])
            delays.append(delay)
            if contact is not None:
                self.assertEqual(frames[contact][1], 1054)
                source, target = struct.unpack_from('>II', frames[action][2])
                self.assertEqual(struct.unpack_from('>II', frames[contact][2]), (target, source))
                self.assertGreater(seconds(frames[contact][0]), seconds(frames[launch][0]))
        self.assertTrue(all(0.49 < delays[index] < 0.54 for index in (0, 1, 3, 4)))
        self.assertTrue(0.71 < delays[2] < 0.72)

    def test_exact_melee_ranged_and_siege_deadlines(self):
        for pair, ticks in ((0, 10), (3, 27), (5, 27)):
            for origin in (0, 1000):
                with self.subTest(pair=pair, origin=origin):
                    director, source, target = self.actors(pair, origin)
                    hits = []
                    hit = lambda a, b, amount, kind, now: hits.append((a, b, amount, now)) or [(1054, b'hit')]
                    frames = director._combat(origin, damage_callback=hit)
                    self.assertEqual([op for op, _ in frames], [1045])
                    self.assertEqual(hits, [])
                    deadline = origin + ticks / 20
                    for tick in range(ticks):
                        self.assertEqual(director._resolve_contacts(origin + tick / 20, damage_callback=hit), [])
                    self.assertEqual(director._resolve_contacts(deadline - 0.000001, damage_callback=hit), [])
                    self.assertEqual(hits, [])
                    self.assertEqual(director._resolve_contacts(deadline, damage_callback=hit), [(1054, b'hit')])
                    self.assertEqual(hits, [(source, target, source.attack_damage, deadline)])
                    self.assertEqual(director._resolve_contacts(deadline, damage_callback=hit), [])

    def test_overlapping_ranged_contacts_keep_each_original_deadline(self):
        director, source, target = self.actors(3)
        hits = []
        hit = lambda a, b, amount, kind, now: hits.append(now) or []
        starts = []
        for tick in range(52):
            frames = director._combat(tick / 20, damage_callback=hit)
            starts.extend(tick / 20 for op, _ in frames if op == 1045)
        self.assertEqual(starts[:3], [0, 0.6, 1.2])
        self.assertEqual(hits, [1.35, 1.95, 2.55])

    def test_source_death_before_release_cancels_melee_and_ranged_even_if_later_revived(self):
        for pair in (0, 3, 5):
            with self.subTest(pair=pair):
                director, source, target = self.actors(pair)
                director._combat(0)
                source.alive = False
                self.assertEqual(director._resolve_contacts(0.05), [])
                self.assertEqual(director.pending_contacts, [])
                source.alive = True
                self.assertEqual(director._resolve_contacts(2), [])

    def test_target_death_drops_contact_before_revival(self):
        director, source, target = self.actors(3)
        director._combat(0)
        target.is_alive = False
        self.assertEqual(director._resolve_contacts(0.05), [])
        target.is_alive = True
        self.assertEqual(director._resolve_contacts(1.35), [])

    def test_removed_source_and_reused_source_id_cannot_deliver_old_contact(self):
        for replace in (False, True):
            director, source, target = self.actors(3)
            director._combat(0)
            director.minions = [wave.Minion(source.eid, 1, 0, 3)] if replace else []
            before = target.hp
            self.assertEqual(director._resolve_contacts(1.35), [])
            self.assertEqual(target.hp, before)

    def test_reused_hero_id_never_receives_old_contact(self):
        director, source, target = self.actors(3)
        director._combat(0, all_heroes={target.eid: target})
        replacement = HeroMovement(eid=target.eid, team=2, x=1, y=0)
        self.assertEqual(director._resolve_contacts(1.35, all_heroes={replacement.eid: replacement}), [])
        self.assertEqual(replacement.hp, replacement.max_hp)
        self.assertEqual(target.hp, target.max_hp)

    def test_reused_minion_id_never_receives_old_contact(self):
        director, source, hero = self.actors(3)
        target = wave.Minion(4611, 2, 0)
        target.x, target.y = 1, 0
        source.target_hero, source.target = None, target
        target.next_attack_at = 100
        director.minions.append(target)
        director._combat(0)
        replacement = wave.Minion(target.eid, 2, 0)
        director.minions = [source, replacement]
        self.assertEqual(director._resolve_contacts(1.35), [])
        self.assertEqual(replacement.hp, replacement.max_hp)

    def test_non_tick_start_rounds_forward_and_damage_is_snapshotted(self):
        director, source, target = self.actors()
        damage = source.attack_damage
        director._combat(0.01)
        source.attack_damage = 999
        self.assertEqual(director._resolve_contacts(0.50), [])
        hits = []
        director._resolve_contacts(0.55, damage_callback=lambda a, b, amount, kind, now: hits.append(amount) or [])
        self.assertEqual(hits, [damage])

    def test_ranged_release_is_once_at_ten_ticks_before_contact_at_twenty_seven(self):
        for pair in (3, 5):
            with self.subTest(pair=pair):
                director, source, target = self.actors(pair)
                releases, hits = [], []
                def release(a, b, variant):
                    releases.append((a, b, variant))
                    return [(1037, b'projectile')]
                def hit(a, b, amount, kind, now):
                    hits.append(now)
                    return [(1054, b'hit')]
                director._combat(0)
                self.assertEqual(director._resolve_contacts(0.499999, on_projectile_release=release), [])
                self.assertEqual(director._resolve_contacts(0.5, on_projectile_release=release), [(1037, b'projectile')])
                self.assertEqual(releases, [(source, target, 0)])
                self.assertEqual(director._resolve_contacts(0.5, on_projectile_release=release), [])
                self.assertEqual(director._resolve_contacts(1.349999, damage_callback=hit), [])
                self.assertEqual(hits, [])
                self.assertEqual(director._resolve_contacts(1.35, damage_callback=hit), [(1054, b'hit')])
                self.assertEqual(hits, [1.35])

    def test_melee_contact_never_uses_projectile_release_callback(self):
        director, source, target = self.actors()
        director._combat(0)
        def unexpected(*args):
            self.fail('melee must not create a ranged projectile')
        frames = director._resolve_contacts(0.5, on_projectile_release=unexpected)
        self.assertIn(1054, [op for op, _ in frames])

    def test_committed_projectile_survives_source_death_removal_movement_and_retarget(self):
        for change in ('death', 'removal', 'movement_and_retarget'):
            with self.subTest(change=change):
                director, source, target = self.actors(3)
                director._combat(0)
                director._resolve_contacts(0.5)
                if change == 'death':
                    director.on_minion_death(source, target.eid, 0.6)
                elif change == 'removal':
                    director.minions = []
                else:
                    source.x, source.y = 100, 100
                    source.target_hero = HeroMovement(eid=1518, team=2, x=101, y=100)
                before = target.hp
                frames = director._resolve_contacts(1.35)
                self.assertIn(1054, [op for op, _ in frames])
                self.assertEqual(target.hp, before - source.attack_damage)
                self.assertEqual(director._resolve_contacts(1.35), [])

    def test_committed_projectile_drops_dead_or_replaced_original_target(self):
        for change in ('death', 'replacement', 'source_replacement'):
            with self.subTest(change=change):
                director, source, target = self.actors(3)
                director._combat(0)
                director._resolve_contacts(0.5)
                registry = {target.eid: target}
                if change == 'death':
                    target.is_alive = False
                elif change == 'replacement':
                    registry[target.eid] = HeroMovement(eid=target.eid, team=2, x=1, y=0)
                else:
                    director.minions = [wave.Minion(source.eid, 1, 0, 3)]
                self.assertEqual(director._resolve_contacts(1.35, all_heroes=registry), [])
                self.assertEqual(target.hp, target.max_hp)

    def test_release_and_lethal_contact_on_same_tick_keep_attack_start_order(self):
        for ranged_first in (False, True):
            with self.subTest(ranged_first=ranged_first):
                director = wave.Director(0)
                melee = wave.Minion(4610, 1, 0)
                ranged = wave.Minion(4611, 2, 0, 3)
                melee.x, melee.y, ranged.x, ranged.y = 0, 0, 1, 0
                melee.target, ranged.target = ranged, melee
                melee.attack_damage, ranged.hp = 999, 1
                director.minions = [ranged, melee] if ranged_first else [melee, ranged]
                director._combat(0)
                released = []
                def release(a, b, variant):
                    released.append((a.eid, b.eid))
                    return [(1037, b'projectile')]
                director._resolve_contacts(0.5, on_projectile_release=release)
                self.assertFalse(ranged.alive)
                self.assertEqual(released, [(ranged.eid, melee.eid)] if ranged_first else [])
                before = melee.hp
                director._resolve_contacts(1.35)
                self.assertEqual(melee.hp, before - (ranged.attack_damage if ranged_first else 0))

    def test_off_tick_release_rounds_forward_and_overlapping_variants_are_preserved(self):
        director, source, target = self.actors(3)
        releases = []
        release = lambda a, b, variant: releases.append(variant) or [(1037, b'projectile')]
        director._combat(0.01)
        self.assertEqual(director._resolve_contacts(0.5, on_projectile_release=release), [])
        self.assertEqual(director._resolve_contacts(0.55, on_projectile_release=release), [(1037, b'projectile')])
        self.assertEqual(releases, [0])
        director._combat(0.61)
        director._combat(1.21, on_projectile_release=release)
        director._resolve_contacts(1.8, on_projectile_release=release)
        self.assertEqual(releases, [0, 1, 0])

    def test_production_session_releases_with_slots_and_damages_after_source_death(self):
        from server.test.test_sandbox_simulation import session, ticks
        world, frames = session()
        world.enable_bots = False
        target = world.hero_sims[1517]
        target.armor = 100
        source = wave.Minion(4610, 1, 0, 3)
        source.x, source.y, source.target_hero = 0, 5, target
        director = wave.Director(0, navigation=world.navigation, actor_slots=world.actor_slots)
        director.minions = [source]
        world.wave_director = director
        world._emit_frames(director.get_spawn_frames(0))
        frames.clear()
        before = target.hp
        ticks(world, 11)
        launches = [body for op, body in frames if op == 1037]
        self.assertEqual(len(launches), 1)
        source_slot = world.actor_slots.by_eid[source.eid]
        self.assertEqual(launches[0][14:17], bytes((source_slot, source_slot,
                                                  world.actor_slots.by_eid[target.eid])))
        self.assertEqual(struct.unpack_from('>f', launches[0], 8)[0], 15)
        self.assertEqual(target.hp, before)
        world._emit_frames(director.on_minion_death(source, target.eid, world.sim_time))
        frames.clear()
        ticks(world, 17)
        hits = [body for op, body in frames if op == 1054
                and struct.unpack_from('>II', body) == (target.eid, source.eid)]
        self.assertEqual(len(hits), 1)
        self.assertEqual(struct.unpack_from('>f', hits[0], 8)[0], -source.attack_damage / 2)
        self.assertEqual(target.hp, before - source.attack_damage / 2)
        self.assertFalse(any(op == 1037 for op, _ in frames))

    def test_short_attack_interrupt_before_release_cancels_even_after_effect_expires(self):
        for pair in (0, 3, 5):
            with self.subTest(pair=pair):
                director, source, target = self.actors(pair)
                status = StatusManager()
                director._combat(0, status_manager=status)
                status.apply_effect(StatusEffect('short-stun', StatusType.STUN, target.eid,
                                                 source.eid, 0.05, 0.20, 0.25))
                self.assertTrue(status.can_attack(source.eid, 0.30))
                releases = []
                release = lambda *args: releases.append(args) or []
                director._resolve_contacts(0.30, status_manager=status, on_projectile_release=release)
                self.assertEqual(director.pending_contacts, [])
                director._resolve_contacts(1.35, status_manager=status, on_projectile_release=release)
                self.assertEqual(releases, [])
                self.assertEqual(target.hp, target.max_hp)

    def test_attack_interrupt_after_release_does_not_retract_committed_projectile(self):
        director, source, target = self.actors(3)
        status = StatusManager()
        director._combat(0, status_manager=status)
        director._resolve_contacts(0.5, status_manager=status)
        status.apply_effect(StatusEffect('after-release-stun', StatusType.STUN, target.eid,
                                         source.eid, 0.2, 0.6, 0.8))
        self.assertFalse(status.can_attack(source.eid, 0.7))
        self.assertEqual(director._resolve_contacts(0.7, status_manager=status), [])
        self.assertEqual(len(director.pending_contacts), 1)
        before = target.hp
        director._resolve_contacts(1.35, status_manager=status)
        self.assertEqual(target.hp, before - source.attack_damage)


if __name__ == '__main__':
    unittest.main()

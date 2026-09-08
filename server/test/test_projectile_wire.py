"""Independent native projectile records and production release boundaries."""
import os
from pathlib import Path
import struct
import unittest

from server import abilities, decode, projectile_wire, roster, wire
from server.test.test_corpus import VGFULL_PCAP, _cached_frames
from server.test.test_sandbox_simulation import session, ticks


class TestProjectileCorpus(unittest.TestCase):
    @unittest.skipUnless(os.path.isfile(VGFULL_PCAP), 'external vgfull unavailable')
    def test_adagio_ordinary_attacks_have_separate_targeted_projectiles(self):
        frames, _ = _cached_frames()
        for action, launch, hit in ((4675, 4717, 4756), (4807, 4846, 4913)):
            self.assertEqual(frames[action][0], 1045)
            source, target, variant = struct.unpack_from('>IIB', frames[action][1])
            self.assertEqual((source, target), (1516, 4478))
            op, payload = frames[launch]
            self.assertEqual(op, 1037)
            instance = struct.unpack_from('>I', payload)[0]
            rebuilt = projectile_wire.build_target_projectile(
                instance, projectile_wire.hero_projectile(244, variant), 2, 54)
            self.assertEqual(rebuilt, payload)
            self.assertEqual(frames[hit][0], 1054)
            self.assertEqual(struct.unpack_from('>II', frames[hit][1]), (target, source))

    def test_skye_and_ranged_minion_projectiles_join_real_compact_actor_slots(self):
        path = Path(os.environ.get('TEMP', '')) / ('vg_phaseB/vgr_live/'
            'ea4c7fda-4b61-481d-abb7-1c757d24ae58-a683aa80-9811-47c3-bb64-0731a802e889.3.vgr')
        if not path.is_file():
            self.skipTest('external Skye match unavailable')
        frames, stats = decode.walk_vgr(path)
        self.assertEqual(stats['failures'], 0)
        samples = ((252, 263, 272, 265, 3, 34, False),
                   (316, 321, 325, 265, 3, 34, False),
                   (334, 380, 440, None, 38, 3, True),
                   (421, 463, 527, None, 37, 36, False))
        for action, launch, hit, hero_id, source_slot, target_slot, target_hero in samples:
            with self.subTest(launch=launch):
                _, op, attack = frames[action]
                self.assertEqual(op, 1045)
                source, target, variant = struct.unpack_from('>IIB', attack)
                _, op, payload = frames[launch]
                self.assertEqual(op, 1037)
                profile = (projectile_wire.hero_projectile(hero_id, variant) if hero_id
                           else projectile_wire.minion_projectile(target_hero))
                self.assertEqual(projectile_wire.build_target_projectile(
                    struct.unpack_from('>I', payload)[0], profile, source_slot, target_slot), payload)
                self.assertEqual(frames[hit][1], 1054)
                self.assertEqual(struct.unpack_from('>II', frames[hit][2]), (target, source))


def skye_session():
    world, frames = session()
    hero = world.hero_sim
    hero.hero_id = world.players[0].hero_id = 265
    world.hero_kits[hero.eid] = world._new_hero_kit(hero, 265)
    return world, frames


class TestProjectileReleaseSession(unittest.TestCase):
    def test_release_emits_once_after_windup_and_before_damage_using_slots(self):
        world, frames = skye_session()
        hero, target = world.hero_sims.values()
        world._apply_event(wire.OP.TARGET_ENTITY, roster.build_target_entity(target.eid))
        ticks(world, 1)
        self.assertEqual(sum(op == 1045 for op, _ in frames), 1)
        self.assertFalse(any(op == 1037 for op, _ in frames))
        for _ in range(20):
            ticks(world, 1)
            if any(op == 1037 for op, _ in frames):
                break
        self.assertEqual(sum(op == 1037 for op, _ in frames), 1)
        self.assertFalse(any(op == 1054 for op, _ in frames))
        payload = next(p for op, p in frames if op == 1037)
        self.assertEqual(payload[14:17], bytes((0, 0, 3)))
        self.assertEqual(struct.unpack_from('>I', payload, 4)[0], 0x77B4B72A)
        # A committed launch remains visible and damaging after recovery movement.
        world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-10, 5))
        ticks(world, 8)
        self.assertEqual(sum(op == 1037 for op, _ in frames), 1)
        self.assertEqual(sum(op == 1054 for op, _ in frames), 1)

    def test_move_during_windup_never_spawns_a_projectile(self):
        world, frames = skye_session()
        target = world.hero_sims[1517]
        world._apply_event(wire.OP.TARGET_ENTITY, roster.build_target_entity(target.eid))
        ticks(world, 1)
        world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-10, 5))
        ticks(world, 15)
        self.assertTrue(any(op == 1045 for op, _ in frames))
        self.assertFalse(any(op in (1037, 1054) for op, _ in frames))

    def test_ability_attack_suppression_cancels_an_existing_windup(self):
        world, frames = skye_session()
        hero, target = world.hero_sims.values()
        world._apply_event(wire.OP.TARGET_ENTITY, roster.build_target_entity(target.eid))
        ticks(world, 1)
        hero.basic_attack_disabled = True
        ticks(world, 10)
        self.assertFalse(any(op in (1037, 1054) for op, _ in frames))

    def test_uncreated_target_never_uses_truncated_entity_id_as_a_slot(self):
        world, frames = skye_session()
        hero, target = world.hero_sims.values()
        world.actor_slots.release(target.eid)
        self.assertEqual(world._target_projectile_frames(hero, target,
                         projectile_wire.hero_projectile(265, 13)), [])


if __name__ == '__main__':
    unittest.main()

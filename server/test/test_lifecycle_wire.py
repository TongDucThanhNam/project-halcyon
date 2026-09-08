"""Real-corpus death/countdown/revival guards; no captured fixture in the repo."""
import os
from pathlib import Path
import struct
import unittest

from server import decode, lifecycle_wire
from server.actor_slots import ActorSlots
from server.hero_movement import HeroMovement
from server.test.test_corpus import VGFULL_PCAP, _cached_frames


class TestLifecycleEmission(unittest.TestCase):
    def test_death_uses_death_action_and_countdown_without_destroying_actor(self):
        hero = HeroMovement()
        frames = hero.apply_damage(hero.hp, 1517, 10)
        self.assertEqual([op for op, _ in frames], [1053, 1072, 1075])
        self.assertEqual(frames[1][1], lifecycle_wire.build_hero_death(1500, 1517))
        self.assertEqual(struct.unpack_from('>If', frames[2][1]), (1500, 8.5))

    def test_sparse_tick_hides_corpse_before_revive_and_restores_authoritative_pools(self):
        hero = HeroMovement(energy=0)
        hero.apply_damage(hero.hp, 1517, 10)
        frames = hero.check_respawn(18.5)
        self.assertEqual([op for op, _ in frames], [1073, 1033, 1070, 1074])
        self.assertEqual((hero.hp, hero.energy), (hero.max_hp, hero.max_energy))
        self.assertTrue(hero.is_alive)

    def test_corpse_hides_once_at_deadline_without_releasing_actor_slot(self):
        hero = HeroMovement()
        slots = ActorSlots(reserved_slots=())
        slots.register(hero.eid, 0)
        hero.apply_damage(hero.hp, 1517, 10)
        self.assertEqual(hero.tick_lifecycle(.05, 11.75), [])
        frames = hero.tick_lifecycle(.05, 11.8)
        self.assertEqual(frames, [(1073, lifecycle_wire.build_hero_corpse_hide(hero.eid))])
        for op, body in frames:
            slots.observe(op, body)
        self.assertEqual(slots.by_eid, {1500: 0})
        self.assertTrue(hero.corpse_hidden)
        self.assertFalse(hero.is_alive)
        self.assertEqual(hero.set_target(0, 0), [])
        self.assertEqual(hero.tick_lifecycle(.05, 11.85), [])
        self.assertEqual(hero.check_respawn(18.19), [])
        self.assertEqual([op for op, _ in hero.check_respawn(18.2)], [1033, 1070])
        self.assertTrue(hero.respawn_relocated)
        self.assertFalse(hero.is_alive)
        self.assertEqual(hero.hp, 0)
        self.assertEqual(hero.check_respawn(18.49), [])
        self.assertEqual(hero.set_target(0, 0), [])
        self.assertEqual([op for op, _ in hero.check_respawn(18.5)], [1074])
        self.assertFalse(hero.corpse_hidden)
        self.assertEqual(hero.check_respawn(18.55), [])
        self.assertTrue(hero.set_target(0, 0))

    def test_short_override_clamps_relocation_to_death_and_second_death_rearms_stages(self):
        for duration in (.2, .5):
            hero = HeroMovement(respawn_duration=duration, energy=0)
            for death_at in (10, 20):
                hero.apply_damage(hero.hp, 1517, death_at)
                relocation_at = max(death_at, death_at + duration - .3)
                self.assertEqual(hero.respawn_relocation_at, relocation_at)
                self.assertEqual(hero.check_respawn(relocation_at - .01), [])
                self.assertEqual([op for op, _ in hero.check_respawn(relocation_at)], [1073, 1033, 1070])
                self.assertEqual(hero.hp, 0)
                self.assertFalse(hero.is_alive)
                self.assertEqual(hero.check_respawn(death_at + duration - .01), [])
                self.assertEqual([op for op, _ in hero.check_respawn(death_at + duration)], [1074])
                self.assertTrue(hero.is_alive)
                self.assertEqual((hero.hp, hero.energy), (hero.max_hp, hero.max_energy))
                self.assertFalse(hero.respawn_relocated)
                self.assertIsNone(hero.respawn_relocation_at)


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), 'external vgfull corpus unavailable')
class TestCorpusLifecycle(unittest.TestCase):
    def test_all_six_hero_deaths_and_timers_match_complete_corpus_payloads(self):
        frames, _ = _cached_frames()
        deaths, timers = [], []
        hero_eids = {1500, 1515, 1516, 1517, 1518, 1519}
        for op, body in frames:
            if len(body) < 4 or struct.unpack_from('>I', body)[0] not in hero_eids:
                continue
            if op == 1072:
                deaths.append(body)
                self.assertEqual(lifecycle_wire.build_hero_death(*struct.unpack_from('>II', body)), body)
            if op == 1075:
                timers.append(body)
                self.assertEqual(lifecycle_wire.build_respawn_countdown(*struct.unpack_from('>If', body)), body)
        self.assertEqual((len(deaths), len(timers)), (6, 6))

    def test_all_five_hero_revives_match_complete_corpus_payloads(self):
        frames, _ = _cached_frames()
        relocations = [body for op, body in frames if op == 1033]
        revives = [body for op, body in frames if op == 1074]
        self.assertEqual((len(relocations), len(revives)), (5, 5))
        for body, complete in zip(relocations, revives):
            eid, x, height, y = struct.unpack_from('>Ifff', body)
            self.assertEqual(lifecycle_wire.build_hero_respawn(eid, x, y), body)
            self.assertEqual(lifecycle_wire.build_hero_respawn_complete(eid, x, y), complete)
            self.assertEqual(complete, body[:16] + bytes(6))
            self.assertEqual(height, 1.5)

    def test_five_full_native_lifecycle_sequences_include_corpse_hide_without_actor_removal(self):
        frames, _ = _cached_frames()
        # Independent exact full-capture indices, not locations generated by
        # searching for the builders' output. Previous two-frame tests missed
        # every 1073 because each happened several seconds before 1033.
        chains = ((16703, 16705, 16970, 17281, 17328), (23106, 23108, 23363, 24096, 24143),
                  (24046, 24050, 24296, 24843, 24895), (25676, 25679, 25851, 26295, 26329),
                  (31279, 31282, 31488, 32378, 32404))
        for death, timer, hide, relocate, revive in chains:
            with self.subTest(death=death):
                death_op, death_body = frames[death]
                eid, killer = struct.unpack_from('>II', death_body)
                self.assertEqual(death_op, 1072)
                self.assertEqual(lifecycle_wire.build_hero_death(eid, killer), death_body)
                self.assertEqual(frames[timer][0], 1075)
                self.assertEqual(lifecycle_wire.build_respawn_countdown(
                    eid, struct.unpack_from('>f', frames[timer][1], 4)[0]), frames[timer][1])
                self.assertEqual(frames[hide], (1073, lifecycle_wire.build_hero_corpse_hide(eid)))
                _, x, height, y = struct.unpack_from('>Ifff', frames[relocate][1])
                hero = HeroMovement(eid=eid, x=x, y=y,
                    respawn_duration=struct.unpack_from('>f', frames[timer][1], 4)[0])
                hero.apply_damage(hero.hp, killer, 0)
                self.assertEqual(hero.check_respawn(1.8), [frames[hide]])
                self.assertEqual(hero.check_respawn(hero.respawn_relocation_at), frames[relocate:relocate + 2])
                self.assertFalse(hero.is_alive)
                self.assertEqual(hero.hp, 0)
                self.assertEqual(hero.check_respawn(hero.respawn_at), [frames[revive]])
                self.assertTrue(hero.is_alive)
                own = [(op, body) for op, body in frames[death:revive + 1]
                       if body[:4] == death_body[:4]]
                self.assertEqual([op for op, _ in own if op in (1072, 1073, 1033, 1074, 1035)],
                                 [1072, 1073, 1033, 1074])


class TestNativeLocalLifecycle(unittest.TestCase):
    def test_native_snapshots_distinguish_dead_relocation_from_completed_full_pool_revival(self):
        cases = (
            ('vg_max/vgr5b', '045f86d4-7ef2-4125-a835-e70a96288c88',
             (26, 1448), (27, 8), (27, 241), False),
            ('vg_phaseB/vgr_live', '0e7de8af-96d9-4e3a-b3c2-609ed5e71120',
             (16, 2131), (17, 8), (16, 2173), True),
        )
        for relative, match, relocation, snapshot, completion, completed in cases:
            with self.subTest(match=match):
                root = Path(os.environ.get('TEMP', '')) / relative
                records = {}
                for chunk in range(relocation[0], max(snapshot[0], completion[0]) + 1):
                    path = root / f'ea4c7fda-4b61-481d-abb7-1c757d24ae58-{match}.{chunk}.vgr'
                    if not path.is_file():
                        self.skipTest(f'external local-player capture unavailable: {path}')
                    rows, info = decode.walk_vgr(str(path))
                    self.assertEqual((info['failures'], info.get('trailing', 0)), (0, 0))
                    records.update(((chunk, index), row) for index, row in enumerate(rows))
                _, rop, rb = records[relocation]
                _, vop, vb = records[completion]
                _, sop, sb = records[snapshot]
                self.assertEqual((rop, vop, sop), (1033, 1074, 1011))
                self.assertEqual((int.from_bytes(rb[:4], 'big'), int.from_bytes(vb[:4], 'big'),
                                  int.from_bytes(sb[8:12], 'big')), (1500, 1500, 1500))
                self.assertEqual((struct.unpack_from('>f', sb, 18)[0], struct.unpack_from('>f', sb, 26)[0]),
                                 (struct.unpack_from('>f', rb, 4)[0], struct.unpack_from('>f', rb, 12)[0]))
                hp, max_hp = struct.unpack_from('>ff', sb, 42)
                energy, max_energy = struct.unpack_from('>ff', sb, 122)
                self.assertGreater(max_hp, 0)
                if completed:
                    self.assertLess(completion, snapshot)
                    self.assertEqual((hp, max_hp, energy, max_energy), (982, 982, 300, 300))
                    # Full pools are present after 1074 without an intervening
                    # HP delta; adding a guessed full-health 1053 is unnecessary.
                    self.assertFalse(any(op == 1053 and body[:4] == rb[:4] and body[8] == 0
                        for origin, (_, op, body) in records.items() if completion < origin < snapshot))
                else:
                    self.assertLess(relocation, snapshot)
                    self.assertLess(snapshot, completion)
                    self.assertEqual(hp, 0)
                    self.assertLess(energy, max_energy)

    def test_seven_local_hero_chains_hide_before_flag_one_relocation_at_measured_height(self):
        # Every complete local-player resurrection in these four original
        # matches. A flag0 Recall relocation is deliberately excluded.
        cases = (
            ('vg_max/vgr5b', '045f86d4-7ef2-4125-a835-e70a96288c88', (26, 421), (26, 634), (26, 1448), (27, 241)),
            ('vg_max/vgr5b', '045f86d4-7ef2-4125-a835-e70a96288c88', (33, 684), (33, 846), (34, 618), (34, 644)),
            ('vg_phaseB/vgr_live', '0e7de8af-96d9-4e3a-b3c2-609ed5e71120', (16, 1001), (16, 1414), (16, 2131), (16, 2173)),
            ('vg_phaseB/vgr_live', '0e7de8af-96d9-4e3a-b3c2-609ed5e71120', (37, 512), (37, 634), (38, 742), (38, 787)),
            ('vg_phaseB/vgr_live', '5ac8f358-2683-4205-9b7b-969ea31b3c72', (33, 1525), (34, 379), (35, 316), (35, 355)),
            ('vg_phaseB/vgr_live', 'a683aa80-9811-47c3-bb64-0731a802e889', (10, 407), (10, 611), (10, 734), (10, 758)),
            ('vg_phaseB/vgr_live', 'a683aa80-9811-47c3-bb64-0731a802e889', (35, 364), (35, 529), (36, 587), (36, 648)),
        )
        decoded = {}
        for relative, match, death, hide, relocate, revive in cases:
            with self.subTest(match=match, death=death):
                root = Path(os.environ.get('TEMP', '')) / relative
                records = {}
                for chunk in range(death[0], revive[0] + 1):
                    path = root / f'ea4c7fda-4b61-481d-abb7-1c757d24ae58-{match}.{chunk}.vgr'
                    if not path.is_file():
                        self.skipTest(f'external local-player capture unavailable: {path}')
                    if path not in decoded:
                        rows, info = decode.walk_vgr(str(path))
                        self.assertEqual((info['failures'], info.get('trailing', 0)), (0, 0))
                        decoded[path] = rows
                    records.update(((chunk, index), row) for index, row in enumerate(decoded[path]))
                dtoken, dop, db = records[death]
                htoken, hop, hb = records[hide]
                rtoken, rop, rb = records[relocate]
                vtoken, vop, vb = records[revive]
                self.assertEqual((dop, hop, rop, vop), (1072, 1073, 1033, 1074))
                eid, killer = struct.unpack_from('>II', db)
                self.assertEqual(eid, 1500)
                self.assertEqual(lifecycle_wire.build_hero_death(eid, killer), db)
                self.assertEqual(lifecycle_wire.build_hero_corpse_hide(eid), hb)
                _, x, height, y = struct.unpack_from('>Ifff', rb)
                self.assertEqual(lifecycle_wire.build_hero_respawn(eid, x, y), rb)
                self.assertEqual(lifecycle_wire.build_hero_respawn_complete(eid, x, y), vb)
                self.assertEqual(vb, rb[:16] + bytes(6))
                self.assertAlmostEqual(height, 1.3, places=6)
                dead_at, hidden_at = (struct.unpack('>f', struct.pack('>I', token))[0]
                                      for token in (dtoken, htoken))
                self.assertAlmostEqual(hidden_at - dead_at, lifecycle_wire.HERO_CORPSE_SECONDS, delta=.11)
                relocation_at, revived_at = (struct.unpack('>f', struct.pack('>I', token))[0]
                                              for token in (rtoken, vtoken))
                self.assertAlmostEqual(revived_at - relocation_at,
                    lifecycle_wire.HERO_RESPAWN_TRANSITION_SECONDS, delta=.11)
                self.assertEqual([op for origin, (_, op, body) in sorted(records.items())
                    if death <= origin <= revive and body[:4] == db[:4]
                    and op in (1072, 1073, 1033, 1074, 1035)], [1072, 1073, 1033, 1074])

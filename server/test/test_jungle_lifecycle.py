"""Native jungle death/corpse retention and explicit captured-actor adaptation."""
import os
from pathlib import Path
import struct
import unittest

from server import decode, entity_spawn, jungle, roster
from server.actor_slots import ActorSlots
from server.hero_movement import HeroMovement
from server.lifecycle_wire import build_hero_death
from server.test.test_corpus import VGFULL_PCAP, _cached_frames
from server.test.test_entity_spawn import original_test_catalog, original_jungle_state_catalog


class TestJungleCorpse(unittest.TestCase):
    def manager(self):
        slots = ActorSlots()
        manager = jungle.JungleManager(actor_slots=slots, state_catalog=original_jungle_state_catalog())
        manager.get_spawn_frames(catalog=original_test_catalog())
        return manager, slots

    def test_treant_corpse_keeps_slot_and_hp0_reconnect_until_four_seconds(self):
        manager, slots = self.manager()
        hero = HeroMovement()
        monster = next(m for m in manager.monsters.values() if m.camp_id == 'LCampA')
        position, slot = (monster.x, monster.y), slots.by_eid[monster.eid]
        death = manager.apply_damage_to_monster(monster.eid, monster.hp, hero, 10)
        self.assertEqual(death[0], (1072, build_hero_death(monster.eid, hero.eid)))
        self.assertEqual(manager.camp_respawns['LCampA'], 70)
        self.assertEqual(manager.on_monster_death(monster, hero.eid, 11), [])
        creations = [p for op, p in manager.get_spawn_frames() if op == 1010 and struct.unpack_from('>I', p, 8)[0] == monster.eid]
        self.assertEqual(len(creations), 1)
        states = [p for _, p in manager.get_state_1010_frames() if struct.unpack_from('>I', p, 8)[0] == monster.eid]
        self.assertEqual(struct.unpack_from('>ff', states[0], 36), (0, 750))
        self.assertEqual(manager.get_death_frames(), [(1072, build_hero_death(monster.eid, hero.eid))])
        self.assertEqual(manager.step(0.05, 13.999, {}), [])
        self.assertEqual((monster.x, monster.y), position)
        self.assertEqual(slots.by_eid[monster.eid], slot)
        self.assertEqual(manager.step(0.05, 14, {}), [(1073, roster.build_destroy(monster.eid)), (1035, roster.build_despawn(monster.eid))])
        self.assertNotIn(monster.eid, manager.monsters)
        self.assertNotIn(monster.eid, slots.by_eid)
        self.assertEqual(manager.get_death_frames(), [])
        self.assertEqual(manager.on_monster_death(monster, hero.eid, 15), [])
        frames = manager.step(0.05, 95, {})
        fresh = next(m for m in manager.monsters.values() if m.camp_id == 'LCampA')
        self.assertNotEqual(fresh.eid, monster.eid)
        self.assertEqual(slots.by_eid[fresh.eid], slot)
        self.assertEqual([op for op, _ in frames], [1010, 1070])

    def test_bears_remove_at_3_8_seconds_and_respawn_timer_starts_only_on_full_clear(self):
        manager, slots = self.manager()
        hero = HeroMovement()
        first, second = [m for m in manager.monsters.values() if m.camp_id == 'LCampB']
        manager.apply_damage_to_monster(first.eid, first.hp, hero, 10)
        self.assertNotIn('LCampB', manager.camp_respawns)
        manager.apply_damage_to_monster(second.eid, second.hp, hero, 12)
        self.assertEqual(manager.camp_respawns['LCampB'], 62)
        manager.step(0.05, 13.8, {})
        self.assertNotIn(first.eid, slots.by_eid)
        self.assertIn(second.eid, slots.by_eid)
        manager.step(0.05, 15.8, {})
        self.assertNotIn(second.eid, slots.by_eid)
        self.assertEqual(manager.camp_respawns['LCampB'], 62)

    def test_nonhero_death_adapter_retains_corpse_without_assuming_a_hero_reward(self):
        manager, _ = self.manager()
        monster = next(iter(manager.monsters.values()))
        monster.take_damage(monster.hp, 90000)
        self.assertEqual(manager.on_monster_death(monster, 90000, 3), [(1072, build_hero_death(monster.eid, 90000))])


class TestCapturedObjectiveAdapter(unittest.TestCase):
    def test_both_captured_archetypes_and_teams_have_owned_creation_and_hp_snapshot(self):
        creation_catalog, state_catalog = original_test_catalog(), original_jungle_state_catalog()
        for archetype in (362, 364):
            for team in (1, 2):
                with self.subTest(archetype=archetype, team=team):
                    creation = creation_catalog.build(archetype, 100050, 0, 23.6, 40,
                        team=team, experimental_capture=True)
                    snapshot = state_catalog.build(archetype, 100050, 0, 23.6, 40, team=team,
                        snapshot=True, hp=(1234, 5000), experimental_capture=True)
                    self.assertEqual(struct.unpack_from('>III', creation), (archetype, entity_spawn.JUNGLE_CLASS, 100050))
                    self.assertEqual(struct.unpack_from('>III', snapshot), (archetype, entity_spawn.JUNGLE_CLASS, 100050))
                    self.assertEqual(creation[96:99], bytes(1 if side == team else 0 for side in range(3)))
                    self.assertEqual(snapshot[96:99], bytes(15 if side == team else 0 for side in range(3)))
                    self.assertEqual(creation[120:122], bytes((255, team)))
                    self.assertEqual(snapshot[120:122], bytes((255, team)))
                    self.assertEqual(snapshot[116], creation[116])
                    self.assertEqual(struct.unpack_from('>ff', snapshot, 36), (1234, 5000))
                    self.assertEqual(snapshot[88:96], b'original')
                    with self.assertRaises(ValueError):
                        state_catalog.build(archetype, 100050, 0, 23.6, 40, team=team, snapshot=True, hp=(1234, 5000))

    def test_opaque_index_override_requires_explicit_experiment_and_is_not_derived_from_team(self):
        catalog = original_test_catalog()
        with self.assertRaises(ValueError):
            catalog.build(362, 100050, 0, 23, 40, actor_index=3)
        creation = catalog.build(364, 100050, 0, 23, 40, team=2, actor_index=3, experimental_capture=True)
        self.assertEqual(creation[120:122], bytes((3, 2)))
        with self.assertRaises(ValueError):
            catalog.build(364, 100050, 0, 23, 40, team=2, actor_index=256, experimental_capture=True)

    def test_gold_recapture_keeps_defeated_faction_corpse_and_reconnects_current_owner(self):
        manager = jungle.JungleManager(state_catalog=original_jungle_state_catalog())
        manager.get_spawn_frames(catalog=original_test_catalog(), experimental_capture=True)
        manager.step(0.05, 300, {})
        miner = manager.gold_miner
        neutral_eid = miner.eid
        manager.apply_damage_to_monster(miner.eid, miner.hp, HeroMovement(), 301)
        first_owned_eid = miner.eid
        frames = manager.apply_damage_to_monster(miner.eid, miner.hp, HeroMovement(eid=1517, team=2), 302)
        self.assertEqual([op for op, _ in frames], [1072, 1010, 1010, 1070])
        self.assertEqual((manager.monsters[neutral_eid].team, manager.monsters[first_owned_eid].team, miner.team), (0, 1, 2))
        self.assertEqual(len({manager.actor_slots.by_eid[e] for e in (neutral_eid, first_owned_eid, miner.eid)}), 3)
        states = {struct.unpack_from('>I', p, 8)[0]: p for _, p in manager.get_state_1010_frames()}
        self.assertEqual(struct.unpack_from('>ff', states[first_owned_eid], 36), (0, 1800))
        self.assertEqual(struct.unpack_from('>ff', states[miner.eid], 36), (1800, 1800))
        self.assertEqual(states[first_owned_eid][121], 1)
        self.assertEqual(states[miner.eid][121], 2)
        manager.step(0.05, 306, {})
        self.assertNotIn(neutral_eid, manager.monsters)
        self.assertNotIn(first_owned_eid, manager.monsters)
        self.assertIn(miner.eid, manager.monsters)


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), 'external native jungle corpus unavailable')
class TestNativeJungleLifecycle(unittest.TestCase):
    def test_all_22_vgfull_jungle_removals_have_byte_exact_death_and_removal_chain(self):
        frames, _ = _cached_frames()
        actors = {struct.unpack_from('>I', p, 8)[0]: struct.unpack_from('>I', p)[0]
                  for op, p in frames if op == 1010 and len(p) == 126 and 357 <= struct.unpack_from('>I', p)[0] <= 364}
        deaths, destroys, removed = {}, {}, []
        for index, (op, p) in enumerate(frames):
            if op not in (1072, 1073, 1035):
                continue
            eid = struct.unpack_from('>I', p)[0]
            if eid not in actors:
                continue
            if op == 1072:
                self.assertEqual(p, build_hero_death(eid, struct.unpack_from('>I', p, 4)[0]))
                deaths[eid] = index
            elif op == 1073:
                self.assertIn(eid, deaths)
                self.assertEqual(p, roster.build_destroy(eid))
                self.assertGreater(index, deaths[eid])
                destroys[eid] = index
            else:
                self.assertIn(eid, destroys)
                self.assertEqual(p, roster.build_despawn(eid))
                self.assertGreater(index, destroys[eid])
                removed.append(eid)
        self.assertEqual(len(removed), 22)

    def test_owned_same_class_crystal_miners_falsify_old_team_minus_one_index(self):
        frames, _ = _cached_frames()
        miners = [p for op, p in frames if op == 1010 and len(p) == 126 and struct.unpack_from('>I', p)[0] == 361]
        self.assertEqual(sorted((p[120], p[121]) for p in miners), [(4, 1), (5, 2)])
        shops = [p for op, p in frames if op == 1010 and len(p) == 126 and struct.unpack_from('>II', p) == (315, entity_spawn.JUNGLE_CLASS)]
        self.assertEqual(sorted((p[120], p[121]) for p in shops), [(255, 0), (255, 1), (255, 2)])


class TestNativeGoldRetirement(unittest.TestCase):
    def test_scheduled_mine_self_hit_and_death_match_two_external_sequences(self):
        root = Path(os.environ.get('TEMP', '')) / 'vg_phaseB' / 'vgr_live' / 'cache'
        session = 'ea4c7fda-4b61-481d-abb7-1c757d24ae58-'
        samples = [('a683aa80-9811-47c3-bb64-0731a802e889', 940, 946),
                   ('f58e0359-8d83-4994-a33c-217cf863144b', 1090, 1096)]
        for match, damage_row, death_row in samples:
            path = root / f'{session}{match}.70.vgr'
            if not path.is_file():
                self.skipTest('external Gold retirement capture unavailable')
            frames, stats = decode.walk_vgr(str(path))
            self.assertEqual(stats['failures'], 0)
            _, op, native_damage = frames[damage_row]
            self.assertEqual(op, 1054)
            _, op, native_death = frames[death_row]
            self.assertEqual(op, 1072)
            eid = struct.unpack_from('>I', native_death)[0]
            manager = jungle.JungleManager()
            manager.step(0.05, 899, {})
            miner = manager.gold_miner
            del manager.monsters[miner.eid]
            miner.eid = eid
            manager.monsters[eid] = miner
            emitted = manager.step(0.05, 900, {})
            self.assertEqual(emitted[:2], [(1054, native_damage), (1072, native_death)])


class TestExternalCaptureEvidence(unittest.TestCase):
    def test_native_registry_identifies_neutral_and_captured_kraken_siblings(self):
        from Tools.Teardown.inspect_kindred_registry import registry_entries
        manifest = Path('D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/03/03A640B504C2B4D7C8CBF3A04E189223')
        instance = Path(os.environ.get('TEMP', '')) / 'vg_max' / 'inst_dump' / 'KindredManifest.inst.bin'
        if not manifest.is_file() or not instance.is_file():
            self.skipTest('external decoded Kindred registry unavailable')
        entries = registry_entries(manifest.read_bytes(), instance.read_bytes())
        self.assertEqual({name: entries[name] for name in ('HF_GoldMiner', 'HF_Kraken_Jungle', 'HF_Kraken_Captured')},
                         {'HF_GoldMiner': 362, 'HF_Kraken_Jungle': 363, 'HF_Kraken_Captured': 364})

    def test_capture_adaptation_preserves_every_unmapped_byte_of_external_neutral_forms(self):
        root = Path(os.environ.get('TEMP', '')) / 'vg_phaseB' / 'vgr_live'
        if not root.is_dir():
            self.skipTest('external neutral objective corpus unavailable')
        catalog = entity_spawn.load_native_actor_catalog(root)
        for archetype in (362, 364):
            for team in (1, 2):
                for snapshot in (False, True):
                    donor = catalog.template_for(363 if archetype == 364 else 362, 0, 0, 23.6, snapshot=snapshot)
                    original = donor.payload
                    maximum = 5000 if archetype == 364 else 1800
                    adapted = catalog.build(archetype, struct.unpack_from('>I', original, 8)[0], *donor.position,
                        original[116], team=team, snapshot=snapshot,
                        hp=(maximum, maximum) if snapshot else None, experimental_capture=True)
                    allowed_changes = set(range(0, 4)) | set(range(96, 99)) | {121}
                    if snapshot:
                        allowed_changes |= set(range(36, 44))
                    self.assertTrue(all(adapted[i] == original[i] for i in range(len(original)) if i not in allowed_changes))
                    self.assertEqual(adapted[120], 255)
                    self.assertEqual(adapted[121], team)

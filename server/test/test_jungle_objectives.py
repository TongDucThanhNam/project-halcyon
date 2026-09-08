"""Behavioral tests for solo sandbox objectives and jungle buffs."""
import unittest

from server import economy, jungle, structures, wire
from server.hero_movement import HeroMovement
from server.status_effects import StatusManager, StatusType


class TestGoldMiner(unittest.TestCase):
    def setUp(self):
        self.manager = jungle.JungleManager()
        self.heroes = {
            1500: HeroMovement(),
            1515: HeroMovement(eid=1515, team=1),
            1517: HeroMovement(eid=1517, team=2),
        }
        self.economy = economy.EconomyManager()

    def test_spawn_boundary_and_zero_starting_gold(self):
        self.manager.step(0.05, 239.95, {})
        self.assertIsNone(self.manager.gold_miner)
        self.manager.step(0.05, 240, {})
        self.assertEqual(self.manager.gold_miner.config.monster_type, jungle.MonsterType.GOLD_MINER)
        self.assertEqual((self.manager.gold_miner.x, self.manager.gold_miner.y), jungle.PIT_POSITION)
        self.assertEqual(self.manager.gold_accumulated, 0)

    def test_gold_accumulates_using_match_time_and_caps_at_300(self):
        self.manager.step(0.05, 300, {})
        self.assertEqual(self.manager.gold_accumulated, 60)
        self.manager.step(0.05, 600, {})
        self.assertEqual(self.manager.gold_accumulated, 300)

    def test_capture_pays_entire_team_only_and_preserves_guardian(self):
        self.manager.step(0.05, 600, {})
        miner = self.manager.gold_miner
        before = {eid: self.economy.get_or_create(eid).gold for eid in self.heroes}
        frames = self.manager.apply_damage_to_monster(miner.eid, miner.hp, self.heroes[1500], 600,
            self.economy, self.heroes)
        self.assertEqual(self.economy.get_or_create(1500).gold - before[1500], 300)
        self.assertEqual(self.economy.get_or_create(1515).gold - before[1515], 300)
        self.assertEqual(self.economy.get_or_create(1517).gold, before[1517])
        self.assertEqual((miner.team, miner.hp, miner.is_alive), (1, miner.max_hp, True))
        self.assertFalse(any(op in (wire.OP.DESTROY, wire.OP.DESPAWN) for op, _ in frames))
        self.assertEqual(self.manager.gold_accumulated, 0)

    def test_capture_awards_partial_reservoir_and_restarts_fill(self):
        self.manager.step(0.05, 300, {})
        miner = self.manager.gold_miner
        before = self.economy.get_or_create(1500).gold
        self.manager.apply_damage_to_monster(miner.eid, miner.hp, self.heroes[1500], 310, self.economy, self.heroes)
        self.assertEqual(self.economy.get_or_create(1500).gold - before, 70)
        self.manager.step(0.05, 320, {})
        self.assertEqual(self.manager.gold_accumulated, 10)

    def test_guardian_ignores_own_team_and_attacks_enemy(self):
        self.manager.step(0.05, 600, {})
        miner = self.manager.gold_miner
        self.manager.apply_damage_to_monster(miner.eid, miner.hp, self.heroes[1500], 600)
        self.heroes[1500].teleport(miner.x, miner.y)
        self.heroes[1517].teleport(miner.x + 1, miner.y)
        hits = []
        self.manager.step(0.05, 602, self.heroes,
            damage_callback=lambda a, b, amount, kind, now: hits.append((a.eid, b.eid, amount)) or [])
        self.assertIn((miner.eid, 1517, miner.config.attack_damage), hits)
        self.assertNotIn((miner.eid, 1500, miner.config.attack_damage), hits)

    def test_friendly_hero_cannot_recapture_owned_miner(self):
        self.manager.step(0.05, 600, {})
        miner = self.manager.gold_miner
        self.manager.apply_damage_to_monster(miner.eid, miner.hp, self.heroes[1500], 600)
        self.manager.apply_damage_to_monster(miner.eid, miner.hp, self.heroes[1500], 610)
        self.assertEqual(miner.hp, miner.max_hp)
        self.assertEqual(self.manager.gold_reset_at, 600)

    def test_enemy_can_recapture_guardian_and_receive_new_reservoir(self):
        self.manager.step(0.05, 600, {})
        miner = self.manager.gold_miner
        self.manager.apply_damage_to_monster(miner.eid, miner.hp, self.heroes[1500], 600)
        before = self.economy.get_or_create(1517).gold
        self.manager.apply_damage_to_monster(miner.eid, miner.hp, self.heroes[1517], 650,
            self.economy, self.heroes)
        self.assertEqual(miner.team, 2)
        self.assertEqual(self.economy.get_or_create(1517).gold - before, 50)


class TestKraken(unittest.TestCase):
    def setUp(self):
        self.manager = jungle.JungleManager()
        self.hero = HeroMovement()

    def test_kraken_replaces_miner_exactly_at_fifteen_minutes(self):
        self.manager.step(0.05, 899.95, {})
        miner = self.manager.gold_miner
        self.assertIsNone(self.manager.active_kraken)
        frames = self.manager.step(0.05, 900, {})
        kraken = self.manager.active_kraken
        self.assertIsNone(self.manager.gold_miner)
        self.assertFalse(miner.is_alive)
        self.assertEqual((kraken.hp, kraken.armor, kraken.shield), (5000, 400, 100))
        self.assertIn(wire.OP.ENTITY_DEATH, [op for op, _ in frames])
        self.assertNotIn(wire.OP.DESTROY, [op for op, _ in frames])
        self.manager.step(0.05, 901, {})
        self.assertIs(self.manager.active_kraken, kraken)

    def test_skipped_time_does_not_create_expired_gold_miner(self):
        self.manager.step(0.05, 1000, {})
        self.assertIsNone(self.manager.gold_miner)
        self.assertIsNotNone(self.manager.active_kraken)

    def test_capture_switches_team_and_restores_hp_without_death_frames(self):
        self.manager.step(0.05, 900, {})
        kraken = self.manager.active_kraken
        frames = self.manager.apply_damage_to_monster(kraken.eid, 5000, self.hero, 901)
        self.assertEqual((kraken.team, kraken.hp, kraken.is_alive), (1, 5000, True))
        self.assertTrue(self.manager.kraken_captured)
        self.assertEqual(self.manager.kraken_team, 1)
        self.assertFalse(any(op in (wire.OP.DESTROY, wire.OP.DESPAWN) for op, _ in frames))

    def test_captured_kraken_leaves_pit_and_damages_enemy_outer_turret(self):
        self.manager.step(0.05, 900, {})
        kraken = self.manager.active_kraken
        self.manager.apply_damage_to_monster(kraken.eid, 5000, self.hero, 901)
        buildings = structures.StructureManager()
        outer = buildings.structures[3539]
        initial = outer.hp
        for tick in range(400):
            self.manager.step(0.05, 901 + tick * 0.05, {}, structures=buildings)
            if outer.hp < initial:
                break
        self.assertLess(kraken.y, jungle.PIT_POSITION[1])
        self.assertLess(outer.hp, initial)
        self.assertEqual(buildings.structures[3545].hp, buildings.structures[3545].max_hp)

    def test_kraken_damage_routes_weapon_and_true_components_once(self):
        self.manager.step(0.05, 900, {})
        kraken = self.manager.active_kraken
        self.manager.apply_damage_to_monster(kraken.eid, 5000, self.hero, 901)
        buildings = structures.StructureManager()
        outer = buildings.structures[3539]
        kraken.siege_stage, kraken.x, kraken.y = 'siege', outer.x - 2, outer.y
        hits = []
        callback = lambda a, b, amount, kind, now: hits.append((a.eid, b.eid, amount, kind)) or []
        self.manager.step(0.05, 903, {}, structures=buildings, damage_callback=callback)
        self.assertEqual(hits, [(kraken.eid, outer.eid, 271, 'weapon'), (kraken.eid, outer.eid, 70, 'true')])
        self.manager.step(0.05, 903.05, {}, structures=buildings, damage_callback=callback)
        self.assertEqual(len(hits), 2)

    def test_captured_kraken_death_does_not_rearm_regular_camp_respawn(self):
        self.manager.step(0.05, 900, {})
        kraken = self.manager.active_kraken
        self.manager.apply_damage_to_monster(kraken.eid, 5000, self.hero, 901)
        enemy = HeroMovement(eid=1517, team=2)
        frames = self.manager.apply_damage_to_monster(kraken.eid, 5000, enemy, 902)
        self.assertFalse(kraken.is_alive)
        self.assertNotIn(kraken.camp_id, self.manager.camp_respawns)
        self.assertIn(wire.OP.ENTITY_DEATH, [op for op, _ in frames])
        self.assertNotIn(wire.OP.DESTROY, [op for op, _ in frames])


class TestJungleBuffs(unittest.TestCase):
    def setUp(self):
        self.status = StatusManager()
        self.manager = jungle.JungleManager(status_manager=self.status)
        self.hero = HeroMovement()
        self.enemy = HeroMovement(eid=1517, team=2)
        self.heroes = {1500: self.hero, 1517: self.enemy}

    def kill_camp(self, suffix, now=1):
        monster = next(m for m in self.manager.monsters.values() if m.camp_id == 'LCamp' + suffix and m.is_alive)
        self.manager.apply_damage_to_monster(monster.eid, monster.hp, self.hero, now)

    def test_weapon_buff_slow_and_burn_use_status_and_damage_hooks(self):
        self.kill_camp('A')
        self.manager.on_basic_attack(self.hero, self.enemy, 2)
        self.assertTrue(self.status.has_effect(1517, StatusType.SLOW, 2))
        hits = []
        callback = lambda a, b, amount, kind, now: hits.append((amount, kind, now)) or []
        self.manager.step(0.05, 2.99, self.heroes, damage_callback=callback)
        self.assertEqual(hits, [])
        self.manager.step(0.05, 3, self.heroes, damage_callback=callback)
        self.manager.step(0.05, 5, self.heroes, damage_callback=callback)
        self.assertEqual(hits, [(10, 'true', 3), (10, 'true', 4), (10, 'true', 5)])

    def test_repeated_attacks_refresh_without_postponing_every_burn_tick(self):
        self.kill_camp('A')
        self.manager.on_basic_attack(self.hero, self.enemy, 2)
        self.manager.on_basic_attack(self.hero, self.enemy, 2.6)
        hits = []
        self.manager.step(0.05, 3, self.heroes,
            damage_callback=lambda a, b, amount, kind, now: hits.append(now) or [])
        self.assertEqual(hits, [3])

    def test_expired_weapon_buff_cannot_apply_slow_or_burn(self):
        self.kill_camp('A')
        self.manager.step(0.05, 91, self.heroes)
        self.manager.on_basic_attack(self.hero, self.enemy, 92)
        self.assertNotIn(1500, self.manager.weapon_buffs)
        self.assertFalse(self.status.has_effect(1517, StatusType.SLOW, 92))
        self.assertEqual(self.manager._burns, {})

    def test_crystal_buff_increases_cp_and_energy_regen_then_restores(self):
        before = self.hero.crystal_power, self.hero.energy_regen
        self.kill_camp('C')
        self.assertEqual(self.hero.crystal_power, before[0] + 30)
        self.assertEqual(self.hero.energy_regen, before[1] + 5)
        self.hero.energy = 0
        self.hero.teleport(0, 10)
        self.hero.tick_lifecycle(1, 2)
        self.assertEqual(self.hero.energy, before[1] + 5)
        self.manager.step(0.05, 91, self.heroes)
        self.assertEqual((self.hero.crystal_power, self.hero.energy_regen), before)

    def test_crystal_refresh_does_not_stack_and_does_not_erase_new_item_cp(self):
        self.kill_camp('C')
        self.manager._spawn_camp('LCampC')
        self.kill_camp('C', now=2)
        self.assertEqual(self.hero.crystal_power, 30)
        self.hero.crystal_power += 150
        self.manager.step(0.05, 92, self.heroes)
        self.assertEqual(self.hero.crystal_power, 150)

    def test_crystal_buff_survives_economy_stat_recalculation(self):
        self.kill_camp('C')
        player = economy.PlayerEconomy(1500)
        player.apply_to_hero(self.hero)
        self.assertEqual(self.hero.crystal_power, 30)
        self.assertEqual(self.hero.energy_regen, self.hero.base_energy_regen + 5)
        self.manager.step(0.05, 91, self.heroes)
        self.assertEqual(self.hero.energy_regen, self.hero.base_energy_regen)

    def test_hero_death_removes_both_buffs(self):
        self.kill_camp('A')
        self.kill_camp('C')
        self.hero.apply_damage(self.hero.hp, 1517, 2)
        self.manager.step(0.05, 2.05, self.heroes)
        self.assertNotIn(1500, self.manager.weapon_buffs)
        self.assertNotIn(1500, self.manager.crystal_buffs)
        self.assertEqual(self.hero.crystal_power, 0)

    def test_monster_attacks_use_callback_without_double_applying_damage(self):
        monster = next(m for m in self.manager.monsters.values() if m.camp_id == 'LCampA')
        self.hero.teleport(monster.x, monster.y)
        before = self.hero.hp
        hits = []
        self.manager.step(0.05, 2, self.heroes,
            damage_callback=lambda a, b, amount, kind, now: hits.append((a.eid, b.eid)) or [])
        self.assertIn((monster.eid, 1500), hits)
        self.assertEqual(self.hero.hp, before)

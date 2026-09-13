"""Acceptance scenarios for item timing, proc damage, defenses, and shop access.

Named rule definitions use recovered native registry IDs. Some tests install
loadouts directly to isolate combat behavior; purchase scenarios exercise actual
component consumption. Item-button/HUD mapping remains separately validated.
"""
from dataclasses import replace
import struct
import unittest

from server.paths import pc_data_dir, research_dir
from server import cooldown_wire, economy, hero_movement, items, roster, wire
from server.status_effects import (DamageContext, DamageModifierQueue, DamageType,
                                   StatusEffect, StatusManager, StatusType)


class ItemScenario(unittest.TestCase):
    def setUp(self):
        self.economy = economy.EconomyManager()
        self.status = StatusManager()
        self.manager = items.ItemManager(self.economy, self.status)
        self.hero = hero_movement.HeroMovement(1500, 1, x=0.0, y=0.0, hp=1000.0, max_hp=1000.0)
        self.enemy = hero_movement.HeroMovement(1517, 2, x=3.0, y=0.0, hp=1000.0, max_hp=1000.0)
        self.ally = hero_movement.HeroMovement(1515, 1, x=4.0, y=0.0, hp=1000.0, max_hp=1000.0)
        self.heroes = {hero.eid: hero for hero in (self.hero, self.enemy, self.ally)}
        self.damage = []

    def equip(self, key, hero=None, slot=0):
        hero = hero or self.hero
        self.economy.get_or_create(hero.eid).inventory[slot] = economy.ITEMS_BY_KEY[key]

    def hit(self, source, target, amount, damage_type, now):
        self.damage.append((source.eid, target.eid, amount, damage_type, now))
        target.hp = max(0.0, target.hp - amount)
        target.is_alive = target.hp > 0.0
        return []

    def effect(self, kind, magnitude=1.0, target=None, at=0.0, until=5.0):
        return self.status.apply_effect(StatusEffect(kind.value, kind, self.enemy.eid,
                                       (target or self.hero).eid, until - at, at, until, magnitude))


class TestActiveItems(ItemScenario):
    def test_sprint_expires_at_three_seconds(self):
        self.equip("sprint_boots")
        result = self.manager.activate(1500, 0, 10.0, self.heroes)
        self.assertTrue(result.success)
        self.assertEqual(self.status.get_flat_speed_bonus(1500, 10.0), 2.0)
        self.assertEqual(self.status.get_flat_speed_bonus(1500, 12.99), 2.0)
        self.assertEqual(self.status.get_flat_speed_bonus(1500, 13.0), 0.0)

    def test_chargers_uses_same_sprint_mechanic(self):
        self.equip("halcyon_chargers")
        self.assertTrue(self.manager.activate(1500, 0, 0.0, self.heroes).success)
        self.assertEqual(self.status.get_flat_speed_bonus(1500, 1.0), 2.0)

    def test_sell_rebuy_cannot_reset_active_cooldown(self):
        self.equip("sprint_boots")
        self.assertTrue(self.manager.activate(1500, 0, 0.0, self.heroes).success)
        self.economy.players[1500].sell_item(0)
        self.equip("halcyon_chargers", slot=3)
        self.assertFalse(self.manager.activate(1500, 3, 3.0, self.heroes).success)
        self.assertFalse(self.manager.activate(1500, 3, 149.99, self.heroes).success)
        self.assertTrue(self.manager.activate(1500, 3, 150.0, self.heroes).success)

    def test_invalid_or_nonactive_slot_changes_nothing(self):
        self.equip("weapon_blade")
        for slot in (-1, 6, 10, 0, True):
            with self.subTest(slot=slot):
                self.assertFalse(self.manager.activate(1500, slot, 0.0, self.heroes).success)
        self.assertEqual(self.status.effects, {})
        self.assertEqual(self.economy.players[1500].item_cooldowns, {})

    def test_dead_or_stunned_hero_cannot_activate(self):
        self.equip("sprint_boots")
        self.hero.is_alive = False
        self.assertFalse(self.manager.activate(1500, 0, 0.0, self.heroes).success)
        self.hero.is_alive = True
        self.effect(StatusType.STUN)
        self.assertFalse(self.manager.activate(1500, 0, 1.0, self.heroes).success)
        self.assertTrue(self.manager.activate(1500, 0, 5.0, self.heroes).success)

    def test_aegis_timer_uses_native_upgraded_reflex_identity(self):
        self.equip("aegis")
        result = self.manager.activate(1500, 0, 0.0, self.heroes)
        self.assertTrue(result.success)
        self.assertEqual(result.cooldown_tag, 0x7DF46CAD)
        frames = result.frames(1500)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0], wire.OP.TIMER_TICK)
        timer = cooldown_wire.parse_timer_tick(frames[0][1])
        self.assertEqual((timer.eid, timer.tag), (1500, 0x7DF46CAD))
        self.assertEqual((timer.remaining, timer.duration), (45.0, 45.0))
        self.assertEqual(timer.state, bytes((0, 1, 2, 0, 0, 0)))

    def test_reflex_blocks_incoming_stun_without_cleansing_old_slow(self):
        self.effect(StatusType.SLOW, 0.25)
        self.equip("reflex_block")
        self.assertTrue(self.manager.activate(1500, 0, 0.0, self.heroes).success)
        self.assertFalse(self.effect(StatusType.STUN, at=0.5))
        self.assertTrue(self.status.can_move(1500, 0.5))
        self.assertEqual(self.status.get_speed_multiplier(1500, 0.5), 0.75)
        self.assertTrue(self.effect(StatusType.STUN, at=1.0))
        self.assertFalse(self.status.can_move(1500, 1.0))

    def test_reflex_barrier_absorbs_and_expires(self):
        self.equip("aegis")
        self.manager.activate(1500, 0, 0.0, self.heroes)
        self.assertEqual(self.status.absorb_damage_with_barrier(1500, 300.0, 0.2), (50.0, 250.0))
        self.assertTrue(self.status.has_effect(1500, StatusType.CC_IMMUNITY, 0.2))
        self.assertFalse(self.status.has_effect(1500, StatusType.CC_IMMUNITY, 1.0))

    def test_crucible_only_protects_nearby_allies(self):
        self.equip("crucible")
        distant = hero_movement.HeroMovement(1516, 1, x=20.0, y=0.0)
        self.heroes[distant.eid] = distant
        self.manager.activate(1500, 0, 0.0, self.heroes)
        for eid in (1500, 1515):
            self.assertTrue(self.status.has_effect(eid, StatusType.CC_IMMUNITY, 1.1))
            self.assertGreater(self.status.get_barrier(eid, 1.1), 0.0)
        for eid in (1516, 1517):
            self.assertFalse(self.status.has_effect(eid, StatusType.CC_IMMUNITY, 0.5))

    def test_fountain_ticks_missing_health_formula_for_allies_only(self):
        self.equip("fountain_of_renewal")
        self.hero.hp = self.ally.hp = self.enemy.hp = 500.0
        self.manager.activate(1500, 0, 0.0, self.heroes)
        self.manager.step(0.9, self.heroes)
        self.assertEqual(self.hero.hp, 500.0)
        self.manager.step(3.0, self.heroes)
        expected = 500.0
        for _ in range(3):
            expected += 2.0 + 0.01 * (1000.0 - expected)
        self.assertAlmostEqual(self.hero.hp, expected)
        self.assertAlmostEqual(self.ally.hp, expected)
        self.assertEqual(self.enemy.hp, 500.0)
        self.manager.step(10.0, self.heroes)
        self.assertAlmostEqual(self.hero.hp, expected)

    def test_fountain_wound_reduces_healing_and_never_resurrects(self):
        self.equip("fountain_of_renewal")
        self.hero.hp = 500.0
        self.effect(StatusType.WOUND, 0.33)
        self.manager.activate(1500, 0, 0.0, self.heroes)
        self.ally.hp = 0.0
        self.ally.is_alive = False
        self.manager.step(1.0, self.heroes)
        self.assertAlmostEqual(self.hero.hp, 500.0 + 7.0 * 0.67)
        self.assertEqual(self.ally.hp, 0.0)

    def test_fountain_heals_minion_entities(self):
        self.equip("fountain_of_renewal")
        from types import SimpleNamespace
        minion = SimpleNamespace(eid=6000, team=1, x=2.0, y=0.0, hp=50.0, max_hp=100.0, is_alive=True)
        self.manager.activate(1500, 0, 0.0, self.heroes, {6000: minion})
        self.manager.step(1.0, self.heroes, {6000: minion})
        self.assertEqual(minion.hp, 52.5)

    def test_atlas_detonates_after_delay_and_reduces_attack_speed(self):
        self.equip("atlas_pauldron")
        self.manager.activate(1500, 0, 0.0, self.heroes)
        self.manager.step(0.79, self.heroes)
        self.assertEqual(self.status.get_attack_speed_multiplier(1517, 0.79), 1.0)
        self.manager.step(0.8, self.heroes)
        self.assertAlmostEqual(self.status.get_attack_speed_multiplier(1517, 0.8), 0.35)
        self.assertEqual(self.status.get_attack_speed_multiplier(1515, 0.8), 1.0)
        self.assertEqual(self.status.get_attack_speed_multiplier(1517, 5.8), 1.0)

    def test_atlas_checks_explosion_position_and_immunity(self):
        self.equip("atlas_pauldron")
        self.manager.activate(1500, 0, 0.0, self.heroes)
        self.enemy.x = 4.1
        self.manager.step(0.8, self.heroes)
        self.assertEqual(self.status.get_attack_speed_multiplier(1517, 0.8), 1.0)
        self.enemy.x = 3.0
        self.effect(StatusType.CC_IMMUNITY, target=self.enemy, at=15.0, until=17.0)
        self.manager.activate(1500, 0, 15.0, self.heroes)
        self.manager.step(15.8, self.heroes)
        self.assertEqual(self.status.get_attack_speed_multiplier(1517, 15.8), 1.0)


class TestItemPassives(ItemScenario):
    def test_aftershock_only_next_attack_after_cast_procs(self):
        self.equip("aftershock")
        self.manager.on_basic_attack(self.hero, self.enemy, 0.0, self.hit)
        self.assertEqual(self.damage, [])
        self.manager.on_ability_cast(self.hero, 1.0)
        self.manager.on_basic_attack(self.hero, self.enemy, 1.2, self.hit)
        self.manager.on_basic_attack(self.hero, self.enemy, 2.0, self.hit)
        self.assertEqual(len(self.damage), 1)
        self.assertEqual(self.damage[0][2:4], (150.0, "crystal"))

    def test_aftershock_cooldown_and_ready_expiry(self):
        self.equip("aftershock")
        self.manager.on_ability_cast(self.hero, 1.0)
        self.manager.on_basic_attack(self.hero, self.enemy, 2.0, self.hit)
        self.manager.on_ability_cast(self.hero, 2.1)
        self.manager.on_basic_attack(self.hero, self.enemy, 2.2, self.hit)
        self.manager.on_ability_cast(self.hero, 3.0)
        self.manager.on_basic_attack(self.hero, self.enemy, 3.0, self.hit)
        self.manager.on_ability_cast(self.hero, 4.0)
        self.manager.on_basic_attack(self.hero, self.enemy, 10.0, self.hit)
        self.assertEqual(len(self.damage), 2)

    def test_aftershock_requires_item_still_equipped(self):
        self.equip("aftershock")
        self.manager.on_ability_cast(self.hero, 1.0)
        self.economy.players[1500].sell_item(0)
        self.manager.on_basic_attack(self.hero, self.enemy, 2.0, self.hit)
        self.assertEqual(self.damage, [])

    def test_alternating_current_every_second_landed_attack(self):
        self.equip("alternating_current")
        self.hero.crystal_power = 200.0
        for now in range(4):
            self.manager.on_basic_attack(self.hero, self.enemy, float(now), self.hit)
        self.assertEqual([event[2] for event in self.damage], [140.0, 140.0])

    def test_passive_copies_do_not_multiply_procs(self):
        self.equip("aftershock", slot=0)
        self.equip("aftershock", slot=1)
        self.manager.on_ability_cast(self.hero, 1.0)
        self.manager.on_basic_attack(self.hero, self.enemy, 2.0, self.hit)
        self.assertEqual(len(self.damage), 1)

    def test_spellfire_wounds_and_native_two_ticks_per_second(self):
        self.equip("spellfire")
        self.hero.crystal_power = 100.0
        self.manager.on_crystal_damage(self.hero, self.enemy, 0.0)
        self.assertAlmostEqual(self.status.get_healing_multiplier(1517, 0.0), 0.67)
        self.manager.step(3.0, self.heroes, damage_callback=self.hit)
        self.assertEqual([event[4] for event in self.damage], [0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
        self.assertEqual([event[2] for event in self.damage], [12.5] * 6)
        self.assertEqual(self.status.get_healing_multiplier(1517, 3.0), 1.0)

    def test_spellfire_refresh_preserves_tick_cadence_without_stacking(self):
        self.equip("spellfire")
        self.manager.on_crystal_damage(self.hero, self.enemy, 0.0)
        self.manager.on_crystal_damage(self.hero, self.enemy, 0.5)
        self.manager.on_crystal_damage(self.hero, self.enemy, 1.5)
        self.manager.step(5.0, self.heroes, damage_callback=self.hit)
        self.assertEqual([event[4] for event in self.damage], [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5])

    def test_dot_callback_is_required_to_preserve_authoritative_death_path(self):
        self.equip("spellfire")
        self.manager.on_crystal_damage(self.hero, self.enemy, 0.0)
        with self.assertRaises(ValueError):
            self.manager.step(1.0, self.heroes)

    def test_husk_triggers_above_twenty_percent_burst_then_halves_damage(self):
        self.equip("slumbering_husk")
        self.assertFalse(self.manager.before_damage(self.hero, 200.0, 0.0))
        self.assertTrue(self.manager.before_damage(self.hero, 10.0, 0.2))
        self.assertEqual(self.status.get_fortified_health(1500, 0.2), 1000.0)
        self.assertEqual(self.status.absorb_damage_with_barrier(1500, 300.0, 0.2), (150.0, 150.0))
        self.assertFalse(self.manager.before_damage(self.hero, 1000.0, 1.0))
        self.assertGreater(self.status.get_fortified_health(1500, 3.19), 0.0)
        self.assertEqual(self.status.get_fortified_health(1500, 3.2), 0.0)

    def test_husk_does_not_accumulate_unrelated_damage_indefinitely(self):
        self.equip("slumbering_husk")
        self.assertFalse(self.manager.before_damage(self.hero, 150.0, 0.0))
        self.assertFalse(self.manager.before_damage(self.hero, 150.0, 2.0))

    def test_husk_coexists_with_barrier_without_double_halving(self):
        self.effect(StatusType.BARRIER, 100.0)
        self.effect(StatusType.FORTIFIED_HEALTH, 100.0)
        self.assertEqual(self.status.absorb_damage_with_barrier(1500, 300.0, 1.0), (100.0, 200.0))
        self.assertEqual(self.status.get_fortified_health(1500, 1.0), 0.0)


class TestShopLocations(ItemScenario):
    def test_lane_purchase_is_rejected_without_spending_gold(self):
        self.hero.x, self.hero.y = 0.0, 0.0
        ok, frames = self.economy.purchase_item(1500, 467, self.hero)
        self.assertFalse(ok)
        self.assertEqual(frames, [])
        self.assertNotIn(1500, self.economy.players)

    def test_returning_to_own_base_allows_purchase(self):
        self.hero.x, self.hero.y = roster.HERO_SPAWNS[1500]
        self.assertTrue(self.economy.purchase_item(1500, 467, self.hero)[0])
        self.assertEqual(self.economy.players[1500].gold, 300.0)

    def test_jungle_shop_range_has_boundary(self):
        self.hero.x, self.hero.y = economy.JUNGLE_SHOP_POSITION
        self.hero.x += economy.JUNGLE_SHOP_RADIUS
        self.assertTrue(economy.can_shop(self.hero))
        self.hero.x += 0.01
        self.assertFalse(economy.can_shop(self.hero))

    def test_enemy_base_dead_hero_and_mismatched_eid_are_rejected(self):
        self.hero.x, self.hero.y = roster.HERO_SPAWNS[1517]
        self.assertFalse(economy.can_shop(self.hero))
        self.hero.x, self.hero.y = roster.HERO_SPAWNS[1500]
        self.assertFalse(self.economy.purchase_item(1517, 467, self.hero)[0])
        self.hero.is_alive = False
        self.assertFalse(economy.can_shop(self.hero))

    def test_team_two_can_shop_own_base(self):
        self.enemy.x, self.enemy.y = roster.HERO_SPAWNS[1517]
        self.assertTrue(self.economy.purchase_item(1517, 467, self.enemy)[0])

    def test_nonfinite_positions_cannot_bypass_gate(self):
        from types import SimpleNamespace
        for value in (float("nan"), float("inf"), -float("inf")):
            # Actor coordinates already reject nonfinite input; the public
            # shop predicate also rejects malformed external entity records.
            actor = SimpleNamespace(is_alive=True, team=1, x=value, y=0.0)
            self.assertFalse(economy.can_shop(actor))

    def test_stat_application_is_idempotent_and_updates_attack_speed(self):
        self.equip("halcyon_chargers")
        player = self.economy.players[1500]
        player.inventory[1] = economy.ITEMS_BY_KEY["alternating_current"]
        player.apply_to_hero(self.hero)
        expected = (self.hero.max_hp, self.hero.item_move_speed, self.hero.bonus_attack_speed)
        player.apply_to_hero(self.hero)
        self.assertEqual((self.hero.max_hp, self.hero.item_move_speed, self.hero.bonus_attack_speed), expected)
        self.assertEqual(self.hero.bonus_attack_speed, 40.0)

    def test_selling_hp_item_clamps_health_and_does_not_heal_dead_hero(self):
        self.equip("oakheart")
        player = self.economy.players[1500]
        player.apply_to_hero(self.hero)
        self.assertEqual(self.hero.hp, 1150.0)
        player.sell_item(0)
        player.apply_to_hero(self.hero)
        self.assertEqual(self.hero.hp, 1000.0)
        self.hero.hp = 0.0
        self.hero.is_alive = False
        self.equip("oakheart")
        player.apply_to_hero(self.hero)
        self.assertEqual(self.hero.hp, 0.0)

    def test_captured_lifespring_fountain_upgrade_prices_and_instances(self):
        self.hero.x, self.hero.y = roster.HERO_SPAWNS[1500]
        player = self.economy.get_or_create(1500)
        self.assertTrue(self.economy.purchase_item(1500, 467, self.hero)[0])
        self.assertTrue(self.economy.purchase_item(1500, 467, self.hero)[0])
        player.add_gold(500.0)
        ok, frames = self.economy.purchase_item(1500, 504, self.hero)
        self.assertTrue(ok)
        self.assertEqual(player.gold, 0.0)
        removed = [struct.unpack_from(">II", payload) for op, payload in frames if op == 1099]
        self.assertEqual(removed, [(1500, 2002)])
        self.assertEqual([struct.unpack_from(">III", payload) for op, payload in frames if op == 1085],
                         [(1500, 504, 2004)])
        player.add_gold(1300.0)
        ok, frames = self.economy.purchase_item(1500, 487, self.hero)
        self.assertTrue(ok)
        self.assertEqual(player.gold, 0.0)
        self.assertEqual([item.id for item in player.inventory if item is not None], [487, 467])
        attributes = [struct.unpack_from(">IIfBB", payload)[2:4] for op, payload in frames if op == 1052]
        self.assertEqual(attributes, [(-200.0, 0), (400.0, 0), (40.0, 7), (40.0, 8)])

    def test_nested_component_discount_never_spends_one_component_twice(self):
        player = economy.PlayerEconomy(1500, start_gold=300.0)
        self.assertEqual(player.buy_item(458), 0)
        # Both Sorrowblade branches need Weapon Blade. This one blade may
        # discount only one branch, even though the two paths name it twice.
        self.assertEqual(player.purchase_plan(464)[0], 2800)
        player.add_gold(2799.0)
        before = (player.gold, list(player.inventory), list(player.inventory_instances))
        self.assertIsNone(player.buy_item(464))
        self.assertEqual((player.gold, player.inventory, player.inventory_instances), before)

    def test_full_inventory_can_upgrade_using_a_component_slot(self):
        player = economy.PlayerEconomy(1500, start_gold=2650.0)
        for _ in range(6):
            self.assertIsNotNone(player.buy_item(458))
        self.assertFalse(player.can_buy_item(467))  # no component and no free slot
        self.assertEqual(player.buy_item(505), 0)   # 850g combine fee, one blade consumed
        self.assertEqual(player.gold, 0.0)
        self.assertEqual(sum(item is not None for item in player.inventory), 6)
        self.assertEqual(player.inventory[0].id, 505)
        self.assertEqual(player.inventory_instances[0], 2008)

    def test_passive_resources_survive_coarse_broadcast_steps(self):
        frames = self.economy.step(2.5, 2.5, {1500: self.hero})
        values = [struct.unpack_from(">IfB", payload) for op, payload in frames if op == 1053]
        self.assertEqual(values, [(1500, 15.0, 6), (1500, 2.5, 8)])
        self.assertEqual(self.economy.players[1500].gold, 615.0)
        frames = self.economy.step(0.5, 3.0, {1500: self.hero})
        self.assertEqual(frames, [])
        frames = self.economy.step(0.5, 3.5, {1500: self.hero})
        self.assertEqual([struct.unpack_from(">IfB", payload) for op, payload in frames],
                         [(1500, 6.0, 6), (1500, 1.0, 8)])

    def test_required_item_ids_are_all_buyable_through_native_shop_path(self):
        required = ("sprint_boots", "halcyon_chargers", "fountain_of_renewal", "reflex_block",
                    "crucible", "aegis", "atlas_pauldron", "aftershock", "spellfire",
                    "alternating_current", "slumbering_husk")
        for key in required:
            with self.subTest(item=key):
                manager = economy.EconomyManager()
                manager.get_or_create(1500).gold = 10000.0
                hero = hero_movement.HeroMovement(1500)
                item = economy.ITEMS_BY_KEY[key]
                ok, frames = manager.purchase_item(1500, item.id, hero)
                self.assertTrue(ok)
                self.assertEqual([struct.unpack_from(">III", payload) for op, payload in frames if op == 1085],
                                 [(1500, item.id, 2002)])


class TestItemStatusContracts(ItemScenario):
    def test_immunity_blocks_all_control_and_wound_types(self):
        self.effect(StatusType.CC_IMMUNITY)
        for kind in (StatusType.STUN, StatusType.SLOW, StatusType.SILENCE, StatusType.ROOT,
                     StatusType.KNOCKBACK, StatusType.DISARM, StatusType.ATTACK_SPEED_SLOW, StatusType.WOUND):
            with self.subTest(kind=kind):
                self.assertFalse(self.effect(kind, at=1.0))
        self.assertEqual(self.status.get_interrupt_serial(1500), 0)

    def test_knockback_stops_attacking_and_casting(self):
        self.effect(StatusType.KNOCKBACK)
        self.assertFalse(self.status.can_move(1500, 1.0))
        self.assertFalse(self.status.can_attack(1500, 1.0))
        self.assertFalse(self.status.can_cast(1500, 1.0))

    def test_interruption_serial_survives_effect_expiry(self):
        self.effect(StatusType.STUN, at=0.0, until=0.1)
        self.status.clean_expired(1.0)
        self.assertTrue(self.status.can_cast(1500, 1.0))
        self.assertEqual(self.status.get_interrupt_serial(1500), 1)

    def test_future_effect_cannot_control_hero_early(self):
        self.effect(StatusType.STUN, at=10.0, until=11.0)
        self.assertTrue(self.status.can_move(1500, 9.0))
        self.assertFalse(self.status.has_effect(1500, StatusType.STUN, 9.0))

    def test_healing_ignores_barrier_armor_crit_and_respects_wound(self):
        self.effect(StatusType.BARRIER, 100.0)
        self.effect(StatusType.WOUND, 0.33)
        result = DamageModifierQueue().resolve(DamageContext(1515, 1500, DamageType.HEAL,
            100.0, 1.0, armor=500.0, crit_multiplier=2.0), self.status)
        self.assertAlmostEqual(result.final_damage, 67.0)
        self.assertFalse(result.is_critical)
        self.assertEqual(self.status.get_barrier(1500, 1.0), 100.0)

    def test_negative_resistance_increases_damage_as_recovered_for_minions(self):
        queue = DamageModifierQueue()
        for damage_type in (DamageType.WEAPON, DamageType.CRYSTAL):
            with self.subTest(damage_type=damage_type):
                result = queue.resolve(DamageContext(1500, 6000, damage_type, 100.0, 0.0,
                                                    armor=-10.0, shield=-10.0))
                self.assertAlmostEqual(result.final_damage, 111.111111111)

    def test_invalid_resistance_is_rejected_instead_of_dividing_by_zero(self):
        queue = DamageModifierQueue()
        for armor in (-100.0, -101.0, float("nan"), float("inf")):
            with self.subTest(armor=armor), self.assertRaises(ValueError):
                queue.resolve(DamageContext(1500, 6000, DamageType.WEAPON, 100.0, 0.0, armor=armor))

    def test_item_identifiers_match_the_recovered_manifest(self):
        self.assertEqual(economy.ITEMS_BY_KEY["sprint_boots"].id, 477)
        self.assertEqual(economy.ITEMS_BY_KEY["fountain_of_renewal"].id, 487)
        self.assertEqual(economy.ITEMS_BY_KEY["aftershock"].id, 492)
        self.assertNotIn(None, economy.ITEMS)
        with self.assertRaises(ValueError):
            economy.bind_item_identity("sprint_boots", 458, evidence="conflicts with measured Weapon Blade")
        with self.assertRaises(ValueError):
            economy.bind_item_identity("sprint_boots", 12345, evidence="")


_MANIFEST = pc_data_dir() / '03/03A640B504C2B4D7C8CBF3A04E189223'
_INSTANCE = research_dir('vg_max') / 'inst_dump/KindredManifest.inst.bin'


@unittest.skipUnless(_MANIFEST.is_file() and _INSTANCE.is_file(), "native manifest corpus unavailable")
class TestNativeItemRegistry(unittest.TestCase):
    def test_runtime_catalog_ids_match_recovered_registry_pointer_graph(self):
        from Tools.Teardown.inspect_kindred_registry import registry_entries
        entries = registry_entries(_MANIFEST.read_bytes(), _INSTANCE.read_bytes())
        # The two default instances independently anchor the array origin on wire.
        self.assertEqual(entries["Item_HealingFlask"], 457)
        self.assertEqual(entries["Item_VisionTotem"], 526)
        names = {"sprint_boots": "Item_SprintBoots", "halcyon_chargers": "Item_HalcyonChargers",
                 "fountain_of_renewal": "Item_FountainOfRenewal", "reflex_block": "Item_ReflexBlock",
                 "crucible": "Item_Crucible", "aegis": "Item_Aegis", "atlas_pauldron": "Item_AtlasPauldron",
                 "aftershock": "Item_Aftershock", "spellfire": "Item_Spellfire",
                 "alternating_current": "Item_AlternatingCurrent", "slumbering_husk": "Item_SlumberingHusk"}
        for key, native_name in names.items():
            with self.subTest(item=key):
                self.assertEqual(economy.ITEMS_BY_KEY[key].id, entries[native_name])


if __name__ == "__main__":
    unittest.main()

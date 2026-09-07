"""Unit tests for Project Halcyon economy, shop, item catalog, and level progression."""
import unittest

from server import abilities, economy, hero_movement, roster, wire


class TestItemCatalogue(unittest.TestCase):
    def test_canonical_items_exist(self):
        self.assertIn(467, economy.ITEMS)  # Weapon Blade
        self.assertIn(504, economy.ITEMS)  # Heavy Steel
        self.assertIn(487, economy.ITEMS)  # Sorrowblade
        self.assertIn(502, economy.ITEMS)  # Light Armor
        self.assertIn(539, economy.ITEMS)  # Metal Jacket
        self.assertIn(470, economy.ITEMS)  # Oakheart
        self.assertIn(464, economy.ITEMS)  # Shatterglass

    def test_item_stats(self):
        wb = economy.ITEMS[467]
        self.assertEqual(wb.cost, 300)
        self.assertEqual(wb.weapon_power, 10.0)

        sb = economy.ITEMS[487]
        self.assertEqual(sb.cost, 3100)
        self.assertEqual(sb.weapon_power, 150.0)

        mj = economy.ITEMS[539]
        self.assertEqual(mj.cost, 2100)
        self.assertEqual(mj.armor, 85.0)

        sg = economy.ITEMS[464]
        self.assertEqual(sg.cost, 3000)
        self.assertEqual(sg.crystal_power, 150.0)


class TestPlayerEconomy(unittest.TestCase):
    def setUp(self):
        self.hero = hero_movement.HeroMovement(eid=1500)
        self.econ = economy.PlayerEconomy(eid=1500, start_gold=600.0)

    def test_initial_state(self):
        self.assertEqual(self.econ.gold, 600.0)
        self.assertEqual(self.econ.level, 1)
        self.assertEqual(self.econ.ability_points, 1)
        self.assertEqual(len(self.econ.inventory), 6)
        self.assertTrue(all(slot is None for slot in self.econ.inventory))

    def test_purchase_item_flow(self):
        # 1. Buy Weapon Blade (cost 300) -> 300g left, slot 0
        slot0 = self.econ.buy_item(467)
        self.assertEqual(slot0, 0)
        self.assertEqual(self.econ.gold, 300.0)
        self.assertIsNotNone(self.econ.inventory[0])
        self.assertEqual(self.econ.inventory[0].name, "Weapon Blade")

        # 2. Buy second Weapon Blade (cost 300) -> 0g left, slot 1
        slot1 = self.econ.buy_item(467)
        self.assertEqual(slot1, 1)
        self.assertEqual(self.econ.gold, 0.0)

        # 3. Third Weapon Blade fails due to insufficient gold
        slot2 = self.econ.buy_item(467)
        self.assertIsNone(slot2)

        # 4. Sell item in slot 0 -> refunds 50% (150g)
        sold = self.econ.sell_item(0)
        self.assertIsNotNone(sold)
        self.assertEqual(sold.id, 467)
        self.assertIsNone(self.econ.inventory[0])
        self.assertEqual(self.econ.gold, 150.0)

    def test_apply_stats_to_hero(self):
        base_dmg = self.hero.attack_damage
        base_armor = self.hero.armor
        base_shield = self.hero.shield
        base_hp = self.hero.max_hp

        # Buy Weapon Blade (+10 WP) and Light Armor (+25 Armor, +20 Shield)
        self.econ.add_gold(1000.0)
        self.econ.buy_item(467)
        self.econ.buy_item(502)
        self.econ.apply_to_hero(self.hero)

        self.assertEqual(self.hero.attack_damage, base_dmg + 10.0)
        self.assertEqual(self.hero.armor, base_armor + 25.0)
        self.assertEqual(self.hero.shield, base_shield + 20.0)

        # Buy Oakheart (+200 HP)
        self.econ.buy_item(470)
        self.econ.apply_to_hero(self.hero)
        self.assertEqual(self.hero.max_hp, base_hp + 200.0)
        self.assertEqual(self.hero.hp, base_hp + 200.0)

    def test_level_progression(self):
        # Initial: level 1, 0 XP, 1 ability point
        self.assertEqual(self.econ.level, 1)
        self.assertEqual(self.econ.ability_points, 1)

        # Add 120 XP -> crosses level 2 threshold (100)
        new_levels = self.econ.add_xp(120.0)
        self.assertEqual(new_levels, [2])
        self.assertEqual(self.econ.level, 2)
        self.assertEqual(self.econ.ability_points, 2)

        # Add 600 XP -> crosses level 3 (250), level 4 (450), level 5 (700)
        new_levels = self.econ.add_xp(600.0)
        self.assertEqual(new_levels, [3, 4, 5])
        self.assertEqual(self.econ.level, 5)
        self.assertEqual(self.econ.ability_points, 5)


class TestEconomyManager(unittest.TestCase):
    def setUp(self):
        self.mgr = economy.EconomyManager()
        self.hero = hero_movement.HeroMovement(eid=1500)
        self.heroes = {1500: self.hero}

    def test_purchase_item(self):
        ok, frames = self.mgr.purchase_item(1500, 467, self.hero)
        self.assertTrue(ok)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0], wire.OP.INVENTORY_SLOT)

        eid, slot = roster.parse_inventory_slot(frames[0][1])
        self.assertEqual(eid, 1500)
        self.assertEqual(slot, 0)
        self.assertEqual(self.hero.attack_damage, self.hero.base_attack_damage + 10.0)

    def test_passive_step_and_trickle(self):
        # Step 1.0 second: accumulates 4.0 gold and 3.594 XP, emits 1086 trickle
        frames = self.mgr.step(dt=1.0, now=1.0, all_heroes=self.heroes)
        player_econ = self.mgr.get_or_create(1500)
        self.assertAlmostEqual(player_econ.gold, 604.0, places=2)
        self.assertAlmostEqual(player_econ.xp, 3.594, places=2)

        # Expect 1086 ENTITY_PROP frame
        self.assertTrue(any(op == wire.OP.ENTITY_PROP for op, _ in frames))

    def test_minion_bounty(self):
        frames = self.mgr.reward_minion_bounty(1500, self.heroes, gold=45.0, xp=50.0)
        player_econ = self.mgr.get_or_create(1500)
        self.assertEqual(player_econ.gold, 645.0)
        self.assertEqual(player_econ.xp, 50.0)

        # Emits 1086 award delta
        self.assertTrue(any(op == wire.OP.ENTITY_PROP for op, _ in frames))

    def test_hero_bounty(self):
        frames = self.mgr.reward_hero_bounty(1500, 1515, self.heroes, gold=200.0, xp=150.0)
        player_econ = self.mgr.get_or_create(1500)
        self.assertEqual(player_econ.gold, 800.0)
        self.assertEqual(player_econ.xp, 150.0)
        # Crosses level 2 threshold (100) -> emits HP stat delta (1053) + 1086 gold award
        self.assertEqual(player_econ.level, 2)
        self.assertTrue(any(op == wire.OP.ENTITY_STAT for op, _ in frames))

    def test_ability_upgrade(self):
        kit = abilities.create_ringo_kit(self.hero)
        achilles = kit.abilities[abilities.AbilitySlot.A]
        orig_dmg = achilles.base_damage
        orig_cd = achilles.cooldown

        # Level 1 has 1 ability point
        success = self.mgr.upgrade_ability(1500, abilities.AbilitySlot.A, kit)
        self.assertTrue(success)
        self.assertEqual(achilles.base_damage, orig_dmg + 30.0)
        self.assertEqual(achilles.cooldown, orig_cd - 0.5)

        # Second upgrade fails without points
        success2 = self.mgr.upgrade_ability(1500, abilities.AbilitySlot.A, kit)
        self.assertFalse(success2)


class TestEconomyWireHelpers(unittest.TestCase):
    def test_shop_buy_roundtrip(self):
        payload = roster.build_shop_buy(1500, 487)
        self.assertEqual(len(payload), 14)
        eid, item_id = roster.parse_shop_buy(payload)
        self.assertEqual(eid, 1500)
        self.assertEqual(item_id, 487)

    def test_inventory_slot_roundtrip(self):
        payload = roster.build_inventory_slot(1500, 3)
        self.assertEqual(len(payload), 14)
        eid, slot = roster.parse_inventory_slot(payload)
        self.assertEqual(eid, 1500)
        self.assertEqual(slot, 3)

    def test_xp_trickle_shape(self):
        payload = roster.build_xp_trickle(1500, 3.594, seq=42)
        self.assertEqual(len(payload), 22)

    def test_ability_upgrade_roundtrip(self):
        payload = roster.build_ability_upgrade(abilities.AbilitySlot.A)
        self.assertEqual(len(payload), 6)
        slot = roster.parse_ability_upgrade(payload)
        self.assertEqual(slot, abilities.AbilitySlot.A)


class TestAbilityDamageScalingWithItems(unittest.TestCase):
    def test_crystal_power_scales_abilities(self):
        caster = hero_movement.HeroMovement(eid=1500, x=0.0, y=0.0)
        target = hero_movement.HeroMovement(eid=1515, x=4.0, y=0.0)
        heroes = {1500: caster, 1515: target}

        kit = abilities.create_ringo_kit(caster)

        # 1. Base Ult damage (no items, crystal_power = 0.0)
        kit.cast_ability(
            slot=abilities.AbilitySlot.ULT,
            now=1.0,
            target_eid=1515,
            all_heroes=heroes,
        )
        dmg_unbuffed = target.max_hp - target.hp

        # Reset target HP and reset cooldown
        target.hp = target.max_hp
        kit.cooldowns[abilities.AbilitySlot.ULT] = 0.0

        # 2. Buy Shatterglass (+150 CP)
        econ_mgr = economy.EconomyManager()
        econ_mgr.get_or_create(1500).add_gold(3000.0)
        econ_mgr.purchase_item(1500, 464, caster)
        self.assertEqual(caster.crystal_power, 150.0)

        # 3. Cast Ult with +150 CP -> extra 150 * 1.2 = +180 raw damage
        kit.cast_ability(
            slot=abilities.AbilitySlot.ULT,
            now=2.0,
            target_eid=1515,
            all_heroes=heroes,
        )
        dmg_buffed = target.max_hp - target.hp

        self.assertGreater(dmg_buffed, dmg_unbuffed)


if __name__ == "__main__":
    unittest.main()

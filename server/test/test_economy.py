"""Unit tests for Project Halcyon economy, shop, item catalog, and level progression."""
import unittest
import struct

from server import abilities, economy, hero_movement, level_wire, roster, wire


class TestItemCatalogue(unittest.TestCase):
    def test_canonical_items_exist(self):
        self.assertIn(458, economy.ITEMS)  # Weapon Blade
        self.assertIn(505, economy.ITEMS)  # Heavy Steel
        self.assertIn(464, economy.ITEMS)  # Sorrowblade
        self.assertIn(469, economy.ITEMS)  # Light Armor
        self.assertIn(471, economy.ITEMS)  # Metal Jacket
        self.assertIn(467, economy.ITEMS)  # Oakheart
        self.assertIn(465, economy.ITEMS)  # Shatterglass

    def test_item_stats(self):
        wb = economy.ITEMS[458]
        self.assertEqual(wb.cost, 300)
        self.assertEqual(wb.weapon_power, 10.0)

        sb = economy.ITEMS[464]
        self.assertEqual(sb.cost, 3100)
        self.assertEqual(sb.weapon_power, 120.0)

        mj = economy.ITEMS[471]
        self.assertEqual(mj.cost, 1900)
        self.assertEqual(mj.armor, 95.0)

        sg = economy.ITEMS[465]
        self.assertEqual(sg.cost, 3000)
        self.assertEqual(sg.crystal_power, 130.0)


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
        slot0 = self.econ.buy_item(458)
        self.assertEqual(slot0, 0)
        self.assertEqual(self.econ.gold, 300.0)
        self.assertIsNotNone(self.econ.inventory[0])
        self.assertEqual(self.econ.inventory[0].name, "Weapon Blade")

        # 2. Buy second Weapon Blade (cost 300) -> 0g left, slot 1
        slot1 = self.econ.buy_item(458)
        self.assertEqual(slot1, 1)
        self.assertEqual(self.econ.gold, 0.0)

        # 3. Third Weapon Blade fails due to insufficient gold
        slot2 = self.econ.buy_item(458)
        self.assertIsNone(slot2)

        # 4. Sell item in slot 0 -> refunds 50% (150g)
        sold = self.econ.sell_item(0)
        self.assertIsNotNone(sold)
        self.assertEqual(sold.id, 458)
        self.assertIsNone(self.econ.inventory[0])
        self.assertEqual(self.econ.gold, 150.0)

    def test_apply_stats_to_hero(self):
        base_dmg = self.hero.attack_damage
        base_armor = self.hero.armor
        base_shield = self.hero.shield
        base_hp = self.hero.max_hp

        # Captured item attributes: Weapon Blade +10 WP, Light Armor +25 armor.
        self.econ.add_gold(1000.0)
        self.econ.buy_item(458)
        self.econ.buy_item(469)
        self.econ.apply_to_hero(self.hero)

        self.assertEqual(self.hero.attack_damage, base_dmg + 10.0)
        self.assertEqual(self.hero.armor, base_armor + 25.0)
        self.assertEqual(self.hero.shield, base_shield)

        # Recovered 1052 after Oakheart creation adds 150 max HP.
        self.econ.buy_item(467)
        self.econ.apply_to_hero(self.hero)
        self.assertEqual(self.hero.max_hp, base_hp + 150.0)
        self.assertEqual(self.hero.hp, base_hp + 150.0)

    def test_level_progression(self):
        # Initial: level 1, 0 XP, 1 ability point
        self.assertEqual(self.econ.level, 1)
        self.assertEqual(self.econ.ability_points, 1)

        # Native requirements start 68, 84, 100, ...; cumulative L2 is 68.
        new_levels = self.econ.add_xp(120.0)
        self.assertEqual(new_levels, [2])
        self.assertEqual(self.econ.level, 2)
        self.assertEqual(self.econ.ability_points, 2)

        # Total 720 crosses cumulative thresholds through level 7 (648).
        new_levels = self.econ.add_xp(600.0)
        self.assertEqual(new_levels, [3, 4, 5, 6, 7])
        self.assertEqual(self.econ.level, 7)
        self.assertEqual(self.econ.ability_points, 7)


class TestEconomyManager(unittest.TestCase):
    def setUp(self):
        self.mgr = economy.EconomyManager()
        self.hero = hero_movement.HeroMovement(eid=1500)
        self.heroes = {1500: self.hero}

    def test_purchase_item(self):
        ok, frames = self.mgr.purchase_item(1500, 458, self.hero)
        self.assertTrue(ok)
        self.assertEqual([op for op, _ in frames], [1081, 1053, 1085, 1052])
        self.assertEqual(struct.unpack_from(">IfB", frames[1][1]), (1500, -300.0, 6))
        self.assertEqual(struct.unpack(">IIIH", frames[2][1]), (1500, 458, 2002, 0))
        self.assertEqual(struct.unpack_from(">IIfBB", frames[3][1]), (1500, 0xFFFFFFFF, 10.0, 4, 1))
        self.assertEqual(self.hero.attack_damage, self.hero.base_attack_damage + 10.0)

    def test_passive_step_and_trickle(self):
        # Captured passive resources are paired 1053 +6 gold / +1 XP.
        frames = self.mgr.step(dt=1.0, now=1.0, all_heroes=self.heroes)
        player_econ = self.mgr.get_or_create(1500)
        self.assertAlmostEqual(player_econ.gold, 606.0, places=2)
        self.assertAlmostEqual(player_econ.xp, 1.0, places=2)
        self.assertEqual([struct.unpack_from(">IfB", payload) for op, payload in frames],
                         [(1500, 6.0, 6), (1500, 1.0, 8)])

    def test_minion_bounty(self):
        frames = self.mgr.reward_minion_bounty(1500, self.heroes, gold=45.0, xp=50.0)
        player_econ = self.mgr.get_or_create(1500)
        self.assertEqual(player_econ.gold, 645.0)
        self.assertEqual(player_econ.xp, 50.0)

        self.assertEqual([struct.unpack_from(">IfB", payload) for op, payload in frames],
                         [(1500, 45.0, 6), (1500, 50.0, 8)])

    def test_hero_bounty(self):
        previous_hp, previous_max_hp = self.hero.hp, self.hero.max_hp
        frames = self.mgr.reward_hero_bounty(1500, 1515, self.heroes, gold=200.0, xp=150.0)
        player_econ = self.mgr.get_or_create(1500)
        self.assertEqual(player_econ.gold, 800.0)
        self.assertEqual(player_econ.xp, 150.0)
        # Native 1076 applies level growth; no second 1053 HP growth is valid.
        self.assertEqual(player_econ.level, 2)
        self.assertEqual([op for op, _ in frames], [1053, 1053, 1076, 1052])
        self.assertEqual([struct.unpack_from(">IfB", payload) for op, payload in frames[:2]],
                         [(1500, 200.0, 6), (1500, 150.0, 8)])
        self.assertEqual(level_wire.parse_level_increment(frames[2][1]), (1500, 1))
        self.assertEqual(level_wire.parse_xp_requirement(frames[3][1]), (1500, 84.0))
        self.assertAlmostEqual(self.hero.hp - previous_hp, self.hero.max_hp - previous_max_hp)
        self.assertGreater(self.hero.max_hp, previous_max_hp)

    def test_ability_upgrade(self):
        kit = abilities.create_ringo_kit(self.hero)
        kit.reset_ranks()
        # Runtime heroes begin with unlearned abilities and one point.
        success = self.mgr.upgrade_ability(1500, abilities.AbilitySlot.A, kit)
        self.assertTrue(success)
        self.assertEqual(kit.ranks[abilities.AbilitySlot.A], 1)

        # Second upgrade fails without points
        success2 = self.mgr.upgrade_ability(1500, abilities.AbilitySlot.A, kit)
        self.assertFalse(success2)

    def test_rejected_ability_upgrade_preserves_point(self):
        kit = abilities.create_ringo_kit(self.hero)
        kit.reset_ranks()
        self.assertFalse(self.mgr.upgrade_ability(1500, abilities.AbilitySlot.ULT, kit))
        self.assertEqual(self.mgr.get_or_create(1500).ability_points, 1)
        self.assertEqual(kit.ranks[abilities.AbilitySlot.ULT], 0)


class TestEconomyWireHelpers(unittest.TestCase):
    def test_shop_buy_roundtrip(self):
        payload = roster.build_shop_buy(1500, 464)
        self.assertEqual(len(payload), 14)
        eid, item_id = roster.parse_shop_buy(payload)
        self.assertEqual(eid, 1500)
        self.assertEqual(item_id, 464)

    def test_inventory_slot_roundtrip(self):
        payload = roster.build_inventory_slot(1500, 3)
        self.assertEqual(len(payload), 14)
        eid, slot = roster.parse_inventory_slot(payload)
        self.assertEqual(eid, 1500)
        self.assertEqual(slot, 3)

    def test_xp_delta_uses_measured_1053_resource_kind(self):
        payload = roster.build_hero_stat(1500, 1.0, stat_type=8)
        self.assertEqual(len(payload), 14)
        self.assertEqual(struct.unpack_from(">IfB", payload), (1500, 1.0, 8))
        self.assertEqual(payload[9:], bytes.fromhex("0001000000"))

    def test_ability_upgrade_roundtrip(self):
        # The measured 1078 upgrade carries a one-byte slot. 1096 carries an
        # inventory instance ID and must never allocate ability points.
        payload = roster.build_ability_cast(abilities.AbilitySlot.A)
        self.assertEqual(len(payload), 6)
        slot = roster.parse_ability_cast(payload)
        self.assertEqual(slot, abilities.AbilitySlot.A)


class TestAbilityDamageScalingWithItems(unittest.TestCase):
    def test_crystal_power_scales_abilities(self):
        caster = hero_movement.HeroMovement(eid=1500, x=0.0, y=0.0)
        target = hero_movement.HeroMovement(eid=1515, team=2, x=4.0, y=0.0,
                                            hp=2000.0, max_hp=2000.0)
        caster.energy = caster.max_energy = 500.0
        heroes = {1500: caster, 1515: target}

        kit = abilities.create_ringo_kit(caster)

        # 1. Base Ult damage (no items, crystal_power = 0.0)
        kit.cast_ability(
            slot=abilities.AbilitySlot.ULT,
            now=1.0,
            target_eid=1515,
            all_heroes=heroes,
        )
        self.assertEqual(target.hp, target.max_hp)  # damage waits for the channel
        kit.step(now=3.0, all_heroes=heroes)
        dmg_unbuffed = target.max_hp - target.hp

        # Reset target HP and reset cooldown
        target.hp = target.max_hp
        target.is_alive = True
        kit.cooldowns[abilities.AbilitySlot.ULT] = 0.0
        caster.energy = caster.max_energy

        # 2. Buy Shatterglass (+130 CP in the native item attribute array)
        econ_mgr = economy.EconomyManager()
        econ_mgr.get_or_create(1500).add_gold(3000.0)
        # Purchasing from the lane was an invalid premise once shop location
        # gating is enforced. Buy at our actual base, then restore cast geometry.
        caster.x, caster.y = roster.HERO_SPAWNS[1500]
        self.assertTrue(econ_mgr.purchase_item(1500, 465, caster)[0])
        caster.x, caster.y = 0.0, 0.0
        self.assertEqual(caster.crystal_power, 130.0)

        # 3. Cast Ult again with the native crystal-power bonus.
        kit.cast_ability(
            slot=abilities.AbilitySlot.ULT,
            now=4.0,
            target_eid=1515,
            all_heroes=heroes,
        )
        self.assertEqual(target.hp, target.max_hp)
        kit.step(now=6.0, all_heroes=heroes)
        dmg_buffed = target.max_hp - target.hp

        self.assertGreater(dmg_buffed, dmg_unbuffed)


if __name__ == "__main__":
    unittest.main()

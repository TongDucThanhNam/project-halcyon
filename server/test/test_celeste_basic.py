"""Julia's Light replaces the basic hit using the current native tooltip."""
import unittest

from server import abilities, hero_balance, hero_movement


class CelesteBasicDamageTests(unittest.TestCase):
    def setUp(self):
        stats = hero_balance.STATS["Celeste"]
        self.hero = hero_movement.HeroMovement(attack_damage=stats.weapon_base)
        self.kit = abilities.create_celeste_kit(self.hero)

    def test_native_zero_weapon_base_still_has_level_one_crystal_basic(self):
        self.assertEqual(self.hero.attack_damage, 0.0)
        self.assertEqual(self.kit.basic_attack_damage_profile(), (75.0, "crystal"))
        self.assertEqual(self.hero.attack_damage, 0.0)

    def test_native_level_twelve_damage_endpoint(self):
        self.hero.level = 12
        self.assertEqual(self.kit.basic_attack_damage_profile(), (125.0, "crystal"))

    def test_release_reads_current_cp_and_wp_into_one_crystal_hit(self):
        self.hero.level = 12
        self.hero.crystal_power = 100.0
        self.hero.attack_damage = 50.0
        self.assertEqual(self.kit.basic_attack_damage_profile(), (250.0, "crystal"))
        self.hero.crystal_power = 200.0
        self.hero.attack_damage = 0.0
        self.assertEqual(self.kit.basic_attack_damage_profile(), (275.0, "crystal"))

    def test_other_kits_use_the_normal_weapon_profile(self):
        for factory in (abilities.create_catherine_kit, abilities.create_ringo_kit,
                        abilities.create_gwen_kit, abilities.HeroKit):
            with self.subTest(factory=factory.__name__):
                self.assertIsNone(factory(self.hero).basic_attack_damage_profile())


if __name__ == "__main__":
    unittest.main()

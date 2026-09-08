"""Hellfire keeps crystal-hit item behavior while its explosion ignores shield."""
import unittest

from server import abilities, economy
from server.status_effects import DamageContext, DamageModifierQueue, DamageType, StatusType
from server.test.test_sandbox_simulation import session


class HellfireSessionTests(unittest.TestCase):
    def test_shield_piercing_explosion_still_triggers_spellfire(self):
        world, _ = session()
        attacker, target = world.hero_sims[1500], world.hero_sims[1517]
        world.economy.get_or_create(attacker.eid).inventory = [economy.ITEMS_BY_KEY['spellfire']]
        target.hp = target.max_hp = 1000
        target.shield = 1000
        kit = world.hero_kits[attacker.eid]
        self.assertTrue(kit.upgrade_ability(abilities.AbilitySlot.ULT, 6))
        arguments = dict(status_manager=world.status_manager, damage_queue=world.damage_queue,
                         all_heroes=world.hero_sims, damage_callback=world._deal_damage)
        kit.cast_ability(abilities.AbilitySlot.ULT, 0, target_eid=target.eid, **arguments)
        kit.step(1.5, **arguments)
        self.assertEqual(target.hp, 1000)
        kit.step(2, **arguments)
        self.assertEqual(target.hp, 750)
        self.assertTrue(world.status_manager.has_effect(target.eid, StatusType.WOUND, 2))

    def test_full_shield_pierce_preserves_reduction_and_barrier(self):
        result = DamageModifierQueue().resolve(DamageContext(1500, 1517,
            DamageType.SHIELD_PIERCING_CRYSTAL, 250, 0, shield=1000,
            damage_reduction=0.2, barrier=25))
        self.assertEqual(result.breakdown['defense_mitigated'], 0)
        self.assertEqual(result.absorbed_by_barrier, 25)
        self.assertEqual(result.final_damage, 175)


if __name__ == '__main__':
    unittest.main()

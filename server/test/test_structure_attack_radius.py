"""Baked structure obstacles must not make melee targets unreachable."""
import math
import unittest

from server import combat, structures
from server.hero_movement import HeroMovement
from server.navigation import DEFAULT_CLASSIC_NAVMESH, load_halcyon_navmesh


class StructureAttackRadius(unittest.TestCase):
    def test_turret_edge_accepts_melee_attack_but_outside_edge_does_not(self):
        target = structures.StructureManager().structures[3539]
        hero = HeroMovement(x=target.x - 4.15, y=target.y, attack_range=2)
        hero.set_target_eid(target.eid)
        engine = combat.BasicAttackEngine()
        engine.step_attacker(hero, target, 0)
        self.assertEqual(engine.states[hero.eid].phase, 'windup')
        self.assertEqual(len(engine.step_attacker(hero, target, .5)), 1)
        hero.x -= .00001
        engine.step_attacker(hero, target, 1)
        self.assertEqual(engine.states[hero.eid].phase, 'idle')

    def test_crystal_radius_is_not_turret_radius(self):
        target = structures.StructureManager().structures[3544]
        hero = HeroMovement(attack_range=2)
        self.assertEqual(combat.basic_attack_reach(hero, target), 4.5)
        self.assertEqual(combat.basic_attack_reach(hero, HeroMovement()), 2)

    @unittest.skipUnless(DEFAULT_CLASSIC_NAVMESH.is_file(), 'owned baked navmesh unavailable')
    def test_melee_pursuit_reaches_and_damages_baked_turret_without_entering_wall(self):
        mesh = load_halcyon_navmesh()
        manager = structures.StructureManager()
        target = manager.structures[3539]
        hero = HeroMovement(x=10, y=target.y, attack_range=2, navigation=mesh)
        hero.set_target_eid(target.eid)
        engine = combat.BasicAttackEngine()
        for tick in range(1, 100):
            now = tick * .05
            hero.step(.05, now, (target.x, target.y),
                      target_radius=target.basic_attack_radius)
            self.assertTrue(mesh.contains((hero.x, hero.y)))
            for impact in engine.step_attacker(hero, target, now):
                manager.apply_damage(target.eid, impact.damage, hero.eid)
            if target.hp < target.max_hp:
                break
        self.assertLess(target.hp, target.max_hp)
        self.assertFalse(hero.is_moving)
        distance = math.dist((hero.x, hero.y), (target.x, target.y))
        self.assertGreater(distance, hero.attack_range)
        self.assertLessEqual(distance, combat.basic_attack_reach(hero, target))


if __name__ == '__main__':
    unittest.main()

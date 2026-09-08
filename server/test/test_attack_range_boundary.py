"""Movement and attack admission must agree at oblique range boundaries."""
import math
from types import SimpleNamespace
import unittest

from server.combat import BasicAttackEngine
from server.hero_balance import configure_hero
from server.hero_movement import HeroMovement


class TestAttackRangeBoundary(unittest.TestCase):
    def test_live_celeste_approach_reaches_repeated_attacks(self):
        # Actual 1060 / 1070 coordinates from the owned Celeste device run.
        # Previously stopped 0.000000724 units outside range forever; the
        # attack engine also rounded this oblique vector to a longer mm vector.
        hero = HeroMovement(x=44.5, y=2.92)
        configure_hero(hero, 285)
        target = SimpleNamespace(eid=1517, team=2, is_alive=True,
                                 x=52.094387, y=2.952555)
        hero.target_eid = target.eid
        attacks, starts, impacts = BasicAttackEngine(), [], []
        for tick in range(1, 121):
            now = tick * .05
            impacts.extend(attacks.step_projectiles(.05, {target.eid: target}))
            hero.step(.05, now=now, target_pos=(target.x, target.y))
            attacks.step_attacker(hero, target, now,
                                  on_windup=lambda *_: starts.append(tick))
        self.assertGreaterEqual(len(starts), 3)
        self.assertGreaterEqual(len(impacts), 3)
        self.assertFalse(hero.is_moving)
        self.assertLessEqual(math.hypot(target.x - hero.x, target.y - hero.y),
                             hero.attack_range)
        self.assertLess(starts[0] * .05, 1.0)

    def test_inside_oblique_boundary_can_begin_attack(self):
        hero = HeroMovement(x=0, y=0, attack_range=5.3)
        target = SimpleNamespace(eid=20, team=2, is_alive=True,
                                 x=5.29996, y=.02)
        self.assertLess(math.hypot(target.x, target.y), hero.attack_range)
        hero.target_eid = target.eid
        attacks = BasicAttackEngine()
        attacks.step_attacker(hero, target, 0)
        self.assertEqual(attacks.states[hero.eid].phase, 'windup')

    def test_submillimetre_outside_boundary_cannot_attack(self):
        hero = HeroMovement(x=0, y=0, attack_range=5.3)
        target = SimpleNamespace(eid=20, team=2, is_alive=True,
                                 x=5.3004, y=0)
        hero.target_eid = target.eid
        attacks = BasicAttackEngine()
        attacks.step_attacker(hero, target, 0)
        self.assertEqual(attacks.states[hero.eid].phase, 'idle')
        self.assertEqual(attacks.projectiles, [])

    def test_exact_integer_triangle_boundary_is_inclusive(self):
        hero = HeroMovement(x=0, y=0, attack_range=5.3)
        target = SimpleNamespace(eid=20, team=2, is_alive=True,
                                 x=3.18, y=4.24)
        hero.target_eid = target.eid
        attacks = BasicAttackEngine()
        attacks.step_attacker(hero, target, 0)
        self.assertEqual(attacks.states[hero.eid].phase, 'windup')


if __name__ == '__main__':
    unittest.main()

"""Attack timing contracts: cancel before release, commit afterwards."""
from types import SimpleNamespace
import unittest

from server.combat import BasicAttackEngine
from server.hero_movement import HeroMovement
from server.status_effects import StatusEffect, StatusManager, StatusType


class TestAttackFSM(unittest.TestCase):
    def setUp(self):
        self.engine = BasicAttackEngine()
        self.hero = HeroMovement(x=0, y=0, attack_range=6, attack_cooldown=.8)
        self.target = SimpleNamespace(eid=20, team=2, x=4., y=0., is_alive=True)
        self.hero.target_eid = 20
        self.status = StatusManager()

    def step(self, now):
        return self.engine.step_attacker(self.hero, self.target, now, self.status)

    def test_windup_does_not_damage(self):
        self.assertEqual(self.step(0), [])
        self.assertEqual(self.engine.states[1500].phase, "windup")
        self.assertEqual(self.step(.239), [])
        self.assertEqual(self.engine.projectiles, [])

    def test_move_cancels_windup(self):
        self.step(0)
        self.hero.target_eid = None
        self.step(.24)
        self.assertEqual(self.engine.projectiles, [])
        self.assertEqual(self.engine.states[1500].phase, "idle")

    def test_move_then_retarget_in_same_tick_cancels_old_windup(self):
        self.step(0)
        self.hero.order_version += 1
        self.step(.24)
        self.assertEqual(self.engine.projectiles, [])

    def test_transient_cc_restarts_windup_after_expiry_between_ticks(self):
        for kind in (StatusType.STUN, StatusType.KNOCKBACK, StatusType.DISARM):
            for clean_expired in (False, True):
                with self.subTest(kind=kind, clean_expired=clean_expired):
                    self.setUp()
                    self.step(0)
                    self.step(.2)
                    self.status.apply_effect(StatusEffect('cc', kind, 20, 1500, .01, .2, .21))
                    if clean_expired:
                        self.status.clean_expired(.25)
                    self.step(.25)
                    self.assertEqual(self.engine.projectiles, [])
                    self.step(.489)
                    self.assertEqual(self.engine.projectiles, [])
                    self.step(.49)
                    self.assertEqual(len(self.engine.projectiles), 1)

    def test_cleansing_cc_does_not_restore_cancelled_windup(self):
        for kind in (StatusType.STUN, StatusType.KNOCKBACK, StatusType.DISARM):
            with self.subTest(kind=kind):
                self.setUp()
                self.step(0)
                self.status.apply_effect(StatusEffect('cc', kind, 20, 1500, 1., .2, 1.2))
                self.status.remove_effect(1500, 'cc', now=.21)
                self.step(.25)
                self.assertEqual(self.engine.projectiles, [])
                self.step(.49)
                self.assertEqual(len(self.engine.projectiles), 1)

    def test_cc_after_release_preserves_projectile_and_cooldown(self):
        for kind in (StatusType.STUN, StatusType.KNOCKBACK, StatusType.DISARM):
            for expired in (False, True):
                with self.subTest(kind=kind, expired=expired):
                    self.setUp()
                    self.step(0)
                    self.step(.24)
                    until = .26 if expired else .5
                    self.status.apply_effect(StatusEffect('cc', kind, 20, 1500, until - .25, .25, until))
                    self.status.clean_expired(.3)
                    self.step(.3)
                    hits = self.engine.step_projectiles(.2, {20: self.target})
                    self.assertEqual(len(hits), 1)
                    self.assertEqual(hits[0].damage, self.hero.attack_damage)
                    self.assertEqual(self.engine.states[1500].ready_ms, 800)
                    self.step(.79)
                    self.assertEqual(self.engine.projectiles, [])
                    self.step(.8)
                    self.assertEqual(self.engine.states[1500].phase, 'windup')

    def test_silence_and_root_allow_original_windup_to_release(self):
        for kind in (StatusType.SILENCE, StatusType.ROOT):
            with self.subTest(kind=kind):
                self.setUp()
                self.step(0)
                self.status.apply_effect(StatusEffect('cc', kind, 20, 1500, 1., .2, 1.2))
                self.step(.24)
                self.assertEqual(len(self.engine.projectiles), 1)

    def test_cc_immunity_preserves_original_windup(self):
        for kind in (StatusType.STUN, StatusType.KNOCKBACK, StatusType.DISARM):
            with self.subTest(kind=kind):
                self.setUp()
                self.status.apply_effect(StatusEffect('immune', StatusType.CC_IMMUNITY, 1500, 1500, 1., 0., 1.))
                self.step(0)
                self.assertFalse(self.status.apply_effect(StatusEffect('cc', kind, 20, 1500, .01, .2, .21)))
                self.step(.24)
                self.assertEqual(len(self.engine.projectiles), 1)

    def test_completed_cc_before_new_windup_does_not_cancel_it(self):
        for kind in (StatusType.STUN, StatusType.KNOCKBACK, StatusType.DISARM):
            with self.subTest(kind=kind):
                self.setUp()
                self.status.apply_effect(StatusEffect('cc', kind, 20, 1500, .1, 0., .1))
                self.status.clean_expired(.1)
                self.step(.15)
                self.step(.39)
                self.assertEqual(len(self.engine.projectiles), 1)

    def test_melee_damage_at_release(self):
        self.hero.is_ranged = False
        self.step(0)
        hit = self.step(.24)
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0].damage, self.hero.attack_damage)
        self.assertEqual(hit[0].target_eid, 20)

    def test_ranged_damage_only_at_contact(self):
        self.step(0)
        self.assertEqual(self.step(.24), [])
        self.assertEqual(len(self.engine.projectiles), 1)
        self.assertEqual(self.engine.step_projectiles(.1, {20: self.target}), [])
        hit = self.engine.step_projectiles(.1, {20: self.target})
        self.assertEqual(len(hit), 1)
        self.assertEqual(self.engine.projectiles, [])

    def test_release_commits_damage_profile_until_projectile_impact(self):
        self.hero.is_ranged = True
        profile = [90.0, 'crystal']
        calls = []

        def resolve(source, target):
            calls.append((source.eid, target.eid))
            return tuple(profile)

        self.engine.step_attacker(self.hero, self.target, 0, damage_profile=resolve)
        self.assertEqual(calls, [])
        self.engine.step_attacker(self.hero, self.target, .24, damage_profile=resolve)
        self.assertEqual(calls, [(1500, 20)])
        profile[:] = [10.0, 'weapon']
        self.hero.target_eid = None
        self.engine.step_attacker(self.hero, self.target, .25, damage_profile=resolve)
        hit = self.engine.step_projectiles(.2, {20: self.target})
        self.assertEqual(len(hit), 1)
        self.assertEqual((hit[0].damage, hit[0].damage_type), (90.0, 'crystal'))
        self.assertEqual(len(calls), 1)

    def test_stutter_step_preserves_projectile_and_cooldown(self):
        self.step(0)
        self.step(.24)
        self.hero.target_eid = None
        self.step(.25)
        self.assertEqual(len(self.engine.step_projectiles(.2, {20: self.target})), 1)
        self.hero.target_eid = 20
        self.step(.79)
        self.assertEqual(self.engine.states[1500].phase, "idle")
        self.step(.8)
        self.assertEqual(self.engine.states[1500].phase, "windup")

    def test_attack_speed_scales_windup_and_cycle(self):
        self.hero.bonus_attack_speed = 100
        self.assertEqual(self.engine.durations(self.hero), (400, 120))
        self.step(0)
        self.step(.12)
        self.assertEqual(len(self.engine.projectiles), 1)
        self.assertEqual(self.hero.next_attack_at, .4)

    def test_attacker_death_does_not_retract_projectile(self):
        self.step(0)
        self.step(.24)
        self.hero.is_alive = False
        self.step(.25)
        self.assertEqual(len(self.engine.step_projectiles(.2, {20: self.target})), 1)

    def test_dead_target_drops_projectile_without_damage(self):
        self.step(0)
        self.step(.24)
        self.target.is_alive = False
        self.assertEqual(self.engine.step_projectiles(.2, {20: self.target}), [])
        self.assertEqual(self.engine.projectiles, [])

    def test_projectile_tracks_moving_target(self):
        self.step(0)
        self.step(.24)
        self.target.y = 4
        self.assertEqual(self.engine.step_projectiles(.1, {20: self.target}), [])
        projectile = self.engine.projectiles[0]
        self.assertGreater(projectile.y_mm, 0)
        self.assertEqual(len(self.engine.step_projectiles(.2, {20: self.target})), 1)

    def test_out_of_range_and_friendly_targets_never_release(self):
        self.target.x = 7
        self.step(0)
        self.step(1)
        self.target.x = 4
        self.target.team = 1
        self.step(2)
        self.assertEqual(self.engine.projectiles, [])


if __name__ == "__main__":
    unittest.main()

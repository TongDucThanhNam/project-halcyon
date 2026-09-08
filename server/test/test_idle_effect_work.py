"""Skip empty effect work without losing death cleanup or queued damage."""
import unittest
from unittest.mock import patch

from server import abilities, buff_wire, cooldown_wire, economy, hero_movement, items
from server.status_effects import DamageModifierQueue, StatusEffect, StatusManager, StatusType


class UnscannableHistory:
    def __iter__(self):
        raise AssertionError("idle ability scanned retained entity history")


class UnscannableCorpse:
    @property
    def is_alive(self):
        raise AssertionError("item cleanup inspected an already-clean corpse")


class TestIdleAbilityWork(unittest.TestCase):
    def setUp(self):
        self.hero = hero_movement.HeroMovement(1500, 1, 0, 0, hp=808, max_hp=808,
                                               energy=500, max_energy=500)
        self.enemy = hero_movement.HeroMovement(1517, 2, 5, 0, hp=2000, max_hp=2000)
        self.heroes = {hero.eid: hero for hero in (self.hero, self.enemy)}
        self.status = StatusManager()
        self.damage = DamageModifierQueue()

    def step(self, kit, now, history=()):
        return kit.step(now, status_manager=self.status, damage_queue=self.damage,
                        all_heroes=self.heroes, all_minions=history)

    def cast(self, kit, slot, **aim):
        return kit.cast_ability(slot, 10, status_manager=self.status,
                                damage_queue=self.damage, all_heroes=self.heroes, **aim)

    def test_all_six_idle_fixture_kits_leave_retained_history_unvisited(self):
        for hero_id in (244, 243, 285, 925, 395, 242):
            with self.subTest(hero_id=hero_id):
                kit = abilities.create_hero_kit(self.hero, hero_id)
                self.assertEqual(self.step(kit, 10, UnscannableHistory()), [])

    def test_bubble_between_pulses_does_not_scan_but_next_pulse_still_hits(self):
        kit = abilities.create_catherine_kit(self.hero)
        self.enemy.x = 3
        self.cast(kit, abilities.AbilitySlot.B)
        after_first_pulse = self.enemy.hp
        self.assertLess(after_first_pulse, 2000)
        self.assertEqual(self.step(kit, 10.49, UnscannableHistory()), [])
        self.assertEqual(self.enemy.hp, after_first_pulse)
        self.step(kit, 10.5)
        self.assertAlmostEqual(after_first_pulse - self.enemy.hp, 22.5 / 1.2)

    def test_dead_bubble_cleans_presentation_without_building_targets(self):
        kit = abilities.create_catherine_kit(self.hero)
        self.cast(kit, abilities.AbilitySlot.B)
        instance = self.status.presentation.active[(1500, "stormguard")].instance_id
        self.status.drain_frames()
        self.hero.hp, self.hero.is_alive = 0, False
        self.step(kit, 10.2, UnscannableHistory())
        self.assertEqual(kit._stormguard_until, 0)
        self.assertNotIn((1500, "stormguard"), self.status.presentation.active)
        cancel, = self.status.drain_frames()
        self.assertEqual(cancel[0], 1093)
        self.assertEqual(buff_wire.parse_buff_cancel(cancel[1]), (1500, instance))
        self.step(kit, 10.3, UnscannableHistory())
        self.assertEqual(self.status.drain_frames(), [])

    def test_queued_reflection_resolves_after_death_before_bubble_cleanup(self):
        kit = abilities.create_catherine_kit(self.hero)
        self.cast(kit, abilities.AbilitySlot.B)
        cap, _ = kit.modify_incoming_damage(100, 10.1, status_manager=self.status)
        self.assertAlmostEqual(cap, 60.6)
        self.hero.hp, self.hero.is_alive = 0, False
        self.step(kit, 10.1)
        self.assertAlmostEqual(self.enemy.hp, 2000 - (100 - cap) / 1.2)
        self.assertEqual(kit._reflections, [])
        self.assertEqual(kit._stormguard_until, 0)
        self.assertNotIn((1500, "stormguard"), self.status.presentation.active)
        after_reflection = self.enemy.hp
        self.step(kit, 10.2, UnscannableHistory())
        self.assertEqual(self.enemy.hp, after_reflection)

    def test_launched_projectile_and_burn_survive_caster_death_then_clean_dead_anchor(self):
        kit = abilities.create_ringo_kit(self.hero, projectile_speed=10)
        self.cast(kit, abilities.AbilitySlot.ULT, target_eid=self.enemy.eid)
        self.step(kit, 11.5)
        self.assertEqual(len(kit._projectiles), 1)
        self.hero.hp, self.hero.is_alive = 0, False
        self.step(kit, 12)
        self.assertEqual(self.enemy.hp, 1750)
        self.assertEqual(kit._projectiles, [])
        self.assertEqual(len(kit._hellfire_burns), 1)
        self.step(kit, 13)
        self.assertAlmostEqual(self.enemy.hp, 1750 - 55 / 1.2)
        self.enemy.hp, self.enemy.is_alive = 0, False
        self.step(kit, 13.1)
        self.assertEqual(kit._hellfire_burns, [])
        self.assertFalse(any(buff.kind == 382 for buff in self.status.presentation.active.values()))
        self.assertEqual(self.step(kit, 13.2, UnscannableHistory()), [])


class TestItemDeadCleanupWork(unittest.TestCase):
    def setUp(self):
        self.status = StatusManager()
        self.economy = economy.EconomyManager()
        self.manager = items.ItemManager(self.economy, self.status)
        self.hero = hero_movement.HeroMovement(1500, 1, 0, 0)

    def test_clean_history_is_unvisited_while_item_ready_timer_still_finishes_once(self):
        player = self.economy.get_or_create(self.hero.eid)
        player.inventory[0] = economy.ITEMS_BY_KEY["sprint_boots"]
        activated = self.manager.activate(1500, 0, 10, {1500: self.hero})
        self.assertTrue(activated.success)
        history = {eid: UnscannableCorpse() for eid in range(2000, 2200)}
        at = 10 + activated.cooldown
        ready, = self.manager.step(at, {1500: self.hero}, history)
        self.assertEqual(ready[0], 1162)
        timer = cooldown_wire.parse_timer_tick(ready[1])
        self.assertEqual((timer.eid, timer.remaining), (1500, 0))
        self.assertEqual(self.manager.step(at + .05, {1500: self.hero}, history), [])

    def test_mechanical_and_presentation_deaths_clear_once_in_eid_order(self):
        dead = {eid: hero_movement.HeroMovement(eid, 2, 0, 0) for eid in (10, 11, 12, 15)}
        for hero in dead.values():
            hero.hp, hero.is_alive = 0, False
        self.status.apply_effect(StatusEffect("mechanical", StatusType.SLOW, 1500, 10,
                                               10, 0, 10, .2))
        linked = StatusEffect("linked", StatusType.SLOW, 1500, 12, 10, 0, 10, .2,
                              native_buff_kind=295)
        self.status.apply_effect(linked)
        linked_instance = self.status.presentation.active[(12, "linked")].instance_id
        visual_instance = self.status.apply_presentation("visual", 1500, 11, 373, 0, 10)
        # Empty mechanics keys must retain the old clear_target behavior too.
        self.status.effects[15] = []
        self.status.apply_effect(StatusEffect("living", StatusType.SLOW, 1500, 1500,
                                               10, 0, 10, .2))
        self.status.apply_effect(StatusEffect("absent", StatusType.SLOW, 1500, 99,
                                               10, 0, 10, .2))
        self.status.drain_frames()
        entities = {2000: UnscannableCorpse(), **dict(reversed(list(dead.items())))}
        with patch.object(self.status, "clear_target", wraps=self.status.clear_target) as clear:
            self.manager.step(1, {1500: self.hero}, entities)
            self.assertEqual([call.args[0] for call in clear.call_args_list], [10, 11, 12, 15])
            self.assertEqual(set(self.status.effects), {99, 1500})
            self.assertEqual(self.status.presentation.active, {})
            cancellations = self.status.drain_frames()
            self.assertEqual([op for op, _ in cancellations], [1093, 1093])
            self.assertEqual([buff_wire.parse_buff_cancel(payload) for _, payload in cancellations],
                             [(11, visual_instance), (12, linked_instance)])
            clear.reset_mock()
            self.manager.step(1.05, {1500: self.hero}, entities)
            clear.assert_not_called()
            self.assertEqual(self.status.drain_frames(), [])


if __name__ == "__main__":
    unittest.main()

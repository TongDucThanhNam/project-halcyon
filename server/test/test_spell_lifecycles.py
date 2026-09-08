"""Authoritative travel/area/deflection regressions for the completed kit paths.

These test the documented simulation policies. Travel speed and Stormguard's
per-pulse scale still require a controlled native-client measurement.
"""
import struct
import unittest

from server import abilities, ability_wire, hero_movement, wire
from server.status_effects import DamageModifierQueue, DamageType, StatusManager


class SpellFixture(unittest.TestCase):
    def setUp(self):
        self.hero = hero_movement.HeroMovement(1500, 1, 0, 0, hp=808, max_hp=808,
                                                energy=500, max_energy=500)
        self.enemy = hero_movement.HeroMovement(1517, 2, 5, 0, hp=2000, max_hp=2000)
        self.other = hero_movement.HeroMovement(1518, 2, 8, 0, hp=2000, max_hp=2000)
        self.ally = hero_movement.HeroMovement(1515, 1, 5, 1, hp=2000, max_hp=2000)
        self.heroes = {h.eid: h for h in (self.hero, self.enemy, self.other, self.ally)}
        self.sm = StatusManager()
        self.queue = DamageModifierQueue()
        self.kit = abilities.create_ringo_kit(self.hero, projectile_speed=10)

    def cast(self, slot=abilities.AbilitySlot.ULT, **kwargs):
        return self.kit.cast_ability(slot, 10, status_manager=self.sm, damage_queue=self.queue,
                                     all_heroes=self.heroes, **kwargs)

    def step(self, now):
        return self.kit.step(now, status_manager=self.sm, damage_queue=self.queue, all_heroes=self.heroes)


class HellfireLifecycleTests(SpellFixture):
    def test_homing_follows_current_position_then_splashes_without_friendly_fire(self):
        self.cast(target_eid=self.enemy.eid)
        self.step(11.5)
        self.step(11.75)
        self.enemy.x = 10
        self.step(12.0)
        self.assertEqual(self.enemy.hp, 2000)
        self.step(12.5)
        self.assertEqual((self.enemy.hp, self.other.hp, self.ally.hp), (1750, 1750, 2000))
        self.assertEqual(self.kit._projectiles, [])
        burn = next(value for value in self.sm.presentation.active.values() if value.kind == 382)
        self.assertEqual((burn.source_eid, burn.target_eid, burn.expires_at), (1500, 1517, 16.5))

    def test_four_burn_ticks_follow_anchor_and_recheck_nearby_enemies(self):
        self.enemy.shield = 300
        self.cast(target_eid=self.enemy.eid)
        self.step(11.5)
        self.step(12.0)
        self.assertEqual(self.enemy.hp, 1750)  # Initial explosion ignores all shield.
        self.other.x = 30
        for tick in range(13, 17):
            self.step(float(tick))
        self.assertAlmostEqual(self.enemy.hp, 1750 - 4 * 55 / 4)
        self.assertEqual(self.other.hp, 1750)
        self.step(17)
        self.assertAlmostEqual(self.enemy.hp, 1750 - 4 * 55 / 4)
        self.assertEqual(self.kit._hellfire_burns, [])

    def test_launched_projectile_survives_caster_death_but_drops_dead_target(self):
        self.cast(target_eid=self.enemy.eid)
        self.step(11.5)
        self.hero.is_alive = False
        self.step(12)
        self.assertEqual(self.enemy.hp, 1750)
        self.enemy.is_alive = False
        self.step(13)
        self.assertEqual(self.kit._hellfire_burns, [])
        self.assertFalse(any(value.kind == 382 for value in self.sm.presentation.active.values()))


class StormguardLifecycleTests(SpellFixture):
    def setUp(self):
        super().setUp()
        self.kit = abilities.create_catherine_kit(self.hero)

    def test_damage_cap_excludes_items_and_reflects_excess_only(self):
        self.hero.max_hp += 1000
        self.cast(abilities.AbilitySlot.B)
        capped, frames = self.kit.modify_incoming_damage(100, 10.1, status_manager=self.sm)
        self.assertAlmostEqual(capped, 60.6)
        self.assertAlmostEqual(self.kit._stormguard_until, 13.8)
        self.assertEqual(frames, [(1045, ability_wire.build_target_cast(1500, 1500, 4))])
        self.step(10.1)
        self.assertAlmostEqual(self.enemy.hp, 2000 - 39.4 / 1.2)
        self.assertEqual(self.ally.hp, 2000)
        self.assertEqual(self.kit.modify_incoming_damage(10, 10.2, status_manager=self.sm), (10, []))
        self.assertAlmostEqual(self.kit._stormguard_until, 13.8)

    def test_shortened_buff_keeps_identity_and_cancels_at_early_expiry(self):
        self.cast(abilities.AbilitySlot.B)
        active = self.sm.presentation.active[(1500, 'stormguard')]
        instance = active.instance_id
        self.sm.drain_frames()
        self.kit.modify_incoming_damage(100, 10.1, status_manager=self.sm)
        self.assertEqual(self.sm.drain_frames(), [])
        self.assertEqual(self.sm.presentation.active[(1500, 'stormguard')].instance_id, instance)
        self.assertAlmostEqual(self.sm.presentation.active[(1500, 'stormguard')].expires_at, 13.8)
        self.sm.clean_expired(13.8)
        cancelled = self.sm.drain_frames()
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0][0], 1093)
        self.assertEqual(struct.unpack_from('>II', cancelled[0][1]), (1500, instance))
        self.assertEqual(self.kit.modify_incoming_damage(100, 13.8), (100, []))

    def test_burn_starts_immediately_then_rechecks_moving_range_each_half_second(self):
        self.enemy.x = 3
        self.cast(abilities.AbilitySlot.B)
        self.assertAlmostEqual(self.enemy.hp, 2000 - 22.5 / 1.2)
        self.step(10.49)
        self.assertAlmostEqual(self.enemy.hp, 2000 - 22.5 / 1.2)
        self.enemy.x = 4
        self.step(10.5)
        self.assertAlmostEqual(self.enemy.hp, 2000 - 22.5 / 1.2)
        self.hero.x = 3
        self.step(11.0)
        self.assertAlmostEqual(self.enemy.hp, 2000 - 45 / 1.2)
        self.hero.is_alive = False
        self.step(11.5)
        self.assertAlmostEqual(self.enemy.hp, 2000 - 45 / 1.2)

    def test_level_growth_counts_and_rank_five_amplifies_reflection(self):
        self.hero.level = 2
        self.hero.hp_per_level = 169.55
        for _ in range(4):
            self.assertTrue(self.kit.upgrade_ability(abilities.AbilitySlot.B, 12))
        self.cast(abilities.AbilitySlot.B)
        capped, _ = self.kit.modify_incoming_damage(100, 10.1, status_manager=self.sm)
        self.assertAlmostEqual(capped, (808 + 169.55) * 0.075)
        self.assertAlmostEqual(self.kit._reflections[0].amount, (100 - capped) * 1.25)


class CastPresentationTests(SpellFixture):
    def test_four_geometry_classes_emit_one_native_start_and_no_impact_marker(self):
        cases = [(abilities.create_gwen_kit, abilities.AbilitySlot.A, 1046, 1, {'target_pos': (9, 0)}),
                 (abilities.create_gwen_kit, abilities.AbilitySlot.ULT, 1046, 3, {'target_pos': (9, 0)}),
                 (abilities.create_celeste_kit, abilities.AbilitySlot.B, 1046, 1, {'target_pos': (5, 0)}),
                 (abilities.create_amael_kit, abilities.AbilitySlot.ULT, 1045, 2, {'target_eid': 1517})]
        for factory, slot, opcode, index, aim in cases:
            with self.subTest(factory=factory.__name__, slot=slot):
                self.setUp()
                self.kit = factory(self.hero)
                frames = self.cast(slot, **aim)
                starts = [(op, p) for op, p in frames if op in (1045, 1046)]
                self.assertEqual(len(starts), 1)
                self.assertEqual(starts[0][0], opcode)
                self.assertEqual(starts[0][1][8 if opcode == 1045 else 16], index)
                self.assertFalse(any(op in (1045, 1046) for op, _ in self.step(12)))


if __name__ == '__main__':
    unittest.main()

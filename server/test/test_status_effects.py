"""Unit tests for StatusManager and DamageModifierQueue (T3 Milestone 2).

Verifies:
- Stun: halts movement and suppresses basic attacks.
- Slow: scales move speed correctly and tests multiple slow stacking.
- Root: stops movement while preserving basic attacks.
- Silence: suppresses ability casting while allowing movement and attacks.
- Knockback: displaces entity coordinates and interrupts motion.
- Disarm: suppresses basic attacks while allowing movement.
- Barrier: absorbs incoming damage before HP depletion.
- DamageModifierQueue:
  * Weapon vs Armor: D = W / (1 + A / 100)
  * Armor Pierce: p * D + (1 - p) * D / (1 + A_eff / 100)
  * Crystal vs Shield: D = C / (1 + S / 100)
  * True Damage: bypasses armor/shield completely
  * Crit Multiplier: 1.5x
  * Damage Reduction: percentage mitigation
  * Full pipeline integration with HeroMovement
"""
import math
import struct
import unittest

from server import hero_movement, roster, status_effects, wire
from server.status_effects import (
    DamageContext,
    DamageModifierQueue,
    DamageType,
    StatusEffect,
    StatusManager,
    StatusType,
)


class TestStatusManager(unittest.TestCase):

    def setUp(self):
        self.sm = StatusManager()

    def test_stun_blocks_move_attack_cast(self):
        self.sm.apply_effect(StatusEffect(
            effect_id="stun_1",
            effect_type=StatusType.STUN,
            source_eid=1515,
            target_eid=1500,
            duration=1.5,
            applied_at=10.0,
            expires_at=11.5,
        ))

        # During stun
        self.assertFalse(self.sm.can_move(1500, now=10.5))
        self.assertFalse(self.sm.can_attack(1500, now=10.5))
        self.assertFalse(self.sm.can_cast(1500, now=10.5))

        # After stun expires
        self.assertTrue(self.sm.can_move(1500, now=11.6))
        self.assertTrue(self.sm.can_attack(1500, now=11.6))
        self.assertTrue(self.sm.can_cast(1500, now=11.6))

    def test_slow_scales_speed_and_highest_dominates(self):
        # 30% slow
        self.sm.apply_effect(StatusEffect(
            effect_id="slow_30",
            effect_type=StatusType.SLOW,
            source_eid=1515,
            target_eid=1500,
            duration=2.0,
            applied_at=10.0,
            expires_at=12.0,
            magnitude=0.30,
        ))
        self.assertAlmostEqual(self.sm.get_speed_multiplier(1500, now=10.5), 0.70)

        # Apply stronger 50% slow
        self.sm.apply_effect(StatusEffect(
            effect_id="slow_50",
            effect_type=StatusType.SLOW,
            source_eid=1516,
            target_eid=1500,
            duration=1.0,
            applied_at=10.5,
            expires_at=11.5,
            magnitude=0.50,
        ))
        # 50% slow dominates while active
        self.assertAlmostEqual(self.sm.get_speed_multiplier(1500, now=11.0), 0.50)

        # After 50% slow expires, 30% slow still in effect
        self.assertAlmostEqual(self.sm.get_speed_multiplier(1500, now=11.8), 0.70)

        # After both expire
        self.assertAlmostEqual(self.sm.get_speed_multiplier(1500, now=12.1), 1.00)

    def test_root_blocks_move_allows_attack(self):
        self.sm.apply_effect(StatusEffect(
            effect_id="root_1",
            effect_type=StatusType.ROOT,
            source_eid=1515,
            target_eid=1500,
            duration=1.2,
            applied_at=5.0,
            expires_at=6.2,
        ))
        self.assertFalse(self.sm.can_move(1500, now=5.5))
        self.assertTrue(self.sm.can_attack(1500, now=5.5))
        self.assertTrue(self.sm.can_cast(1500, now=5.5))

    def test_silence_blocks_cast_allows_move_attack(self):
        self.sm.apply_effect(StatusEffect(
            effect_id="silence_1",
            effect_type=StatusType.SILENCE,
            source_eid=1515,
            target_eid=1500,
            duration=2.0,
            applied_at=5.0,
            expires_at=7.0,
        ))
        self.assertTrue(self.sm.can_move(1500, now=6.0))
        self.assertTrue(self.sm.can_attack(1500, now=6.0))
        self.assertFalse(self.sm.can_cast(1500, now=6.0))

    def test_disarm_blocks_attack_allows_move(self):
        self.sm.apply_effect(StatusEffect(
            effect_id="disarm_1",
            effect_type=StatusType.DISARM,
            source_eid=1515,
            target_eid=1500,
            duration=1.5,
            applied_at=5.0,
            expires_at=6.5,
        ))
        self.assertTrue(self.sm.can_move(1500, now=6.0))
        self.assertFalse(self.sm.can_attack(1500, now=6.0))
        self.assertTrue(self.sm.can_cast(1500, now=6.0))

    def test_knockback_displacement_calculation(self):
        # Knockback toward positive x direction at 10 u/s for 0.5s (5.0 units total)
        self.sm.apply_effect(StatusEffect(
            effect_id="kb_1",
            effect_type=StatusType.KNOCKBACK,
            source_eid=1515,
            target_eid=1500,
            duration=0.5,
            applied_at=10.0,
            expires_at=10.5,
            direction=(1.0, 0.0),
            speed=10.0,
        ))
        self.assertFalse(self.sm.can_move(1500, now=10.1))
        dx, dy = self.sm.get_knockback_displacement(1500, dt=0.1, now=10.1)
        self.assertAlmostEqual(dx, 1.0)
        self.assertAlmostEqual(dy, 0.0)

    def test_barrier_absorption(self):
        self.sm.apply_effect(StatusEffect(
            effect_id="shield_1",
            effect_type=StatusType.BARRIER,
            source_eid=1500,
            target_eid=1500,
            duration=3.0,
            applied_at=10.0,
            expires_at=13.0,
            magnitude=200.0,
        ))
        self.assertAlmostEqual(self.sm.get_barrier(1500, now=11.0), 200.0)

        # Incoming 120 damage: fully absorbed, 80 barrier left
        rem, absorbed = self.sm.absorb_damage_with_barrier(1500, 120.0, now=11.0)
        self.assertAlmostEqual(rem, 0.0)
        self.assertAlmostEqual(absorbed, 120.0)
        self.assertAlmostEqual(self.sm.get_barrier(1500, now=11.0), 80.0)

        # Incoming 100 damage: absorbs 80, 20 breaks through to HP
        rem2, absorbed2 = self.sm.absorb_damage_with_barrier(1500, 100.0, now=11.0)
        self.assertAlmostEqual(rem2, 20.0)
        self.assertAlmostEqual(absorbed2, 80.0)
        self.assertAlmostEqual(self.sm.get_barrier(1500, now=11.0), 0.0)


class TestDamageModifierQueue(unittest.TestCase):

    def setUp(self):
        self.queue = DamageModifierQueue()

    def test_weapon_vs_armor_base_formula(self):
        # D = W / (1 + A / 100) -> 100 / (1 + 25/100) = 80.0
        ctx = DamageContext(
            source_eid=1515,
            target_eid=1500,
            damage_type=DamageType.WEAPON,
            raw_amount=100.0,
            now=1.0,
            armor=25.0,
        )
        res = self.queue.resolve(ctx)
        self.assertAlmostEqual(res.final_damage, 80.0, places=2)
        self.assertAlmostEqual(res.mitigated_by_defense, 20.0, places=2)

    def test_crystal_vs_shield_base_formula(self):
        # D = C / (1 + S / 100) -> 120 / (1 + 50/100) = 80.0
        ctx = DamageContext(
            source_eid=1515,
            target_eid=1500,
            damage_type=DamageType.CRYSTAL,
            raw_amount=120.0,
            now=1.0,
            shield=50.0,
        )
        res = self.queue.resolve(ctx)
        self.assertAlmostEqual(res.final_damage, 80.0, places=2)
        self.assertAlmostEqual(res.mitigated_by_defense, 40.0, places=2)

    def test_armor_pierce_formula(self):
        # W = 100, A = 100, pierce = 0.25 (25%)
        # D_pierce = 25.0
        # A_eff = 100 * (1 - 0.25) = 75.0
        # D_resisted = (100 * 0.75) / (1 + 0.75) = 75 / 1.75 = 42.857
        # Total = 67.857
        ctx = DamageContext(
            source_eid=1515,
            target_eid=1500,
            damage_type=DamageType.WEAPON,
            raw_amount=100.0,
            now=1.0,
            armor=100.0,
            armor_pierce=0.25,
        )
        res = self.queue.resolve(ctx)
        self.assertAlmostEqual(res.final_damage, 67.857, places=2)

    def test_true_damage_ignores_resistances(self):
        ctx = DamageContext(
            source_eid=1515,
            target_eid=1500,
            damage_type=DamageType.TRUE,
            raw_amount=150.0,
            now=1.0,
            armor=200.0,
            shield=200.0,
        )
        res = self.queue.resolve(ctx)
        self.assertAlmostEqual(res.final_damage, 150.0, places=2)
        self.assertAlmostEqual(res.mitigated_by_defense, 0.0)

    def test_critical_strike_and_reduction(self):
        # 100 damage with 1.5x crit = 150.0
        # Armor 50 -> 150 / 1.5 = 100.0
        # 20% damage reduction -> 100 * 0.8 = 80.0
        ctx = DamageContext(
            source_eid=1515,
            target_eid=1500,
            damage_type=DamageType.WEAPON,
            raw_amount=100.0,
            now=1.0,
            crit_multiplier=1.5,
            armor=50.0,
            damage_reduction=0.20,
        )
        res = self.queue.resolve(ctx)
        self.assertTrue(res.is_critical)
        self.assertAlmostEqual(res.final_damage, 80.0, places=2)


class TestHeroStatusEffectsIntegration(unittest.TestCase):

    def setUp(self):
        self.sm = StatusManager()
        self.queue = DamageModifierQueue()
        self.hero = hero_movement.HeroMovement(eid=1500, team=1, x=0.0, y=0.0, speed=5.0)

    def test_stun_stops_active_hero_movement(self):
        self.hero.set_target(20.0, 0.0)
        self.assertTrue(self.hero.is_moving)

        # Apply 1.0s stun
        self.sm.apply_effect(StatusEffect(
            effect_id="stun_test",
            effect_type=StatusType.STUN,
            source_eid=1515,
            target_eid=1500,
            duration=1.0,
            applied_at=10.0,
            expires_at=11.0,
        ))

        # Step during stun: hero halts and does not progress
        frames = self.hero.step(dt=0.2, now=10.2, status_manager=self.sm)
        self.assertFalse(self.hero.is_moving)
        self.assertAlmostEqual(self.hero.x, 0.0)

    def test_slow_scales_hero_distance_traveled(self):
        self.hero.set_target(20.0, 0.0)

        # Apply 40% slow (effective speed = 5.0 * 0.6 = 3.0 u/s)
        self.sm.apply_effect(StatusEffect(
            effect_id="slow_test",
            effect_type=StatusType.SLOW,
            source_eid=1515,
            target_eid=1500,
            duration=2.0,
            applied_at=10.0,
            expires_at=12.0,
            magnitude=0.40,
        ))

        # Advance 1.0 second
        self.hero.step(dt=1.0, now=11.0, status_manager=self.sm)
        # Expected distance = 3.0 units (not 5.0 units)
        self.assertAlmostEqual(self.hero.x, 3.0, places=2)

    def test_knockback_displaces_hero_position(self):
        self.hero.set_target(10.0, 0.0)

        # Knock back in -x direction at 8.0 u/s for 0.5s
        self.sm.apply_effect(StatusEffect(
            effect_id="kb_test",
            effect_type=StatusType.KNOCKBACK,
            source_eid=1515,
            target_eid=1500,
            duration=0.5,
            applied_at=10.0,
            expires_at=10.5,
            direction=(-1.0, 0.0),
            speed=8.0,
        ))

        # Step 0.25s: displaced by -2.0 units
        frames = self.hero.step(dt=0.25, now=10.25, status_manager=self.sm)
        self.assertAlmostEqual(self.hero.x, -2.0, places=2)
        pos_frames = [f for f in frames if f[0] == wire.OP.POSITION]
        self.assertTrue(pos_frames)
        eid, x, y, _ = struct.unpack(">IffH", pos_frames[0][1][:14])
        self.assertEqual(eid, 1500)
        self.assertAlmostEqual(x, -2.0, places=2)

    def test_hero_damage_with_barrier_absorption(self):
        # Attach 100 barrier
        self.sm.apply_effect(StatusEffect(
            effect_id="barrier_test",
            effect_type=StatusType.BARRIER,
            source_eid=1500,
            target_eid=1500,
            duration=3.0,
            applied_at=10.0,
            expires_at=13.0,
            magnitude=100.0,
        ))

        init_hp = self.hero.hp
        # Apply 150 damage through modifier queue:
        # Hero has base armor 25.0 -> 150 / 1.25 = 120.0 post-mitigation
        # Barrier absorbs 100.0 -> 20.0 damages HP!
        frames = self.hero.apply_damage(
            amount=150.0,
            attacker_eid=1515,
            now=10.5,
            damage_type="weapon",
            status_manager=self.sm,
            modifier_queue=self.queue,
        )
        self.assertAlmostEqual(self.hero.hp, init_hp - 20.0, places=2)
        stat_frame = next(f for f in frames if f[0] == wire.OP.ENTITY_STAT)
        eid, val, typ = struct.unpack_from(">IfB", stat_frame[1], 0)
        self.assertEqual(eid, 1500)
        self.assertAlmostEqual(val, -20.0, places=2)


if __name__ == "__main__":
    unittest.main()

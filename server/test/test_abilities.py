"""Unit tests for hero ability scaffold and Ringo-class kit (T3 Milestone 2).

Verifies:
- Ability definitions and kit creation.
- Ability A (Achilles Shot): 140 damage, 6.5u range, 1046 impact event, 50% slow debuff.
- Ability B (Twirling Silver): self-buff steroid (+40% move speed, reduced attack cooldown).
- Ability C / Ult (Hellfire Brew): 350 crystal damage, 15.0u range, 1046 fireball impact (kind 3).
- Cooldown tracking: blocks casting while on cooldown, emits 1162 timer tick.
- Status effect suppression: stun and silence block ability casting.
- Wire builders & parsers: 1046, 1078, 1102 round-trip validation.
"""
import math
import struct
import unittest

from server import abilities, hero_movement, roster, status_effects, wire
from server.abilities import AbilitySlot, AbilityType, HeroKit, create_ringo_kit
from server.status_effects import DamageModifierQueue, StatusEffect, StatusManager, StatusType


class TestAbilityWireEncoding(unittest.TestCase):

    def test_position_event_1046_encoding(self):
        body = roster.build_position_event(1500, -38.5, 22.7, z=0, kind=3)
        self.assertEqual(len(body), roster.POSITION_EVENT_PAYLOAD_SIZE)
        eid, x, z, y, kind = struct.unpack_from(">IfIfB", body, 0)
        self.assertEqual(eid, 1500)
        self.assertAlmostEqual(x, -38.5, places=2)
        self.assertEqual(z, 0)
        self.assertAlmostEqual(y, 22.7, places=2)
        self.assertEqual(kind, 3)
        self.assertEqual(body[17:], bytes(5))

    def test_ability_cast_1078_roundtrip(self):
        body = roster.build_ability_cast(AbilitySlot.B)
        self.assertEqual(len(body), roster.ABILITY_CAST_PAYLOAD_SIZE)
        slot = roster.parse_ability_cast(body)
        self.assertEqual(slot, 1)

    def test_skillshot_cast_1102_roundtrip(self):
        payload = struct.pack(">IIfffBB", 1500, 1517, 12.5, 0.0, 34.2, 2, 1)
        self.assertEqual(len(payload), roster.SKILLSHOT_CAST_PAYLOAD_SIZE)
        caster, target, x, y, slot, flag = roster.parse_skillshot_cast(payload)
        self.assertEqual(caster, 1500)
        self.assertEqual(target, 1517)
        self.assertAlmostEqual(x, 12.5, places=2)
        self.assertAlmostEqual(y, 34.2, places=2)
        self.assertEqual(slot, 2)
        self.assertEqual(flag, 1)


class TestRingoKit(unittest.TestCase):

    def setUp(self):
        self.sm = StatusManager()
        self.queue = DamageModifierQueue()
        self.hero = hero_movement.HeroMovement(eid=1500, team=1, x=0.0, y=0.0)
        self.enemy = hero_movement.HeroMovement(eid=1517, team=2, x=5.0, y=0.0)
        self.kit = create_ringo_kit(self.hero)
        self.heroes = {1500: self.hero, 1517: self.enemy}

    def test_achilles_shot_in_range(self):
        """Ability A applies 140 damage, 1046 impact, 1078 echo, 1162 timer, and 50% slow."""
        now = 10.0
        self.assertTrue(self.kit.can_cast(AbilitySlot.A, now, self.sm))

        init_enemy_hp = self.enemy.hp
        frames = self.kit.cast_ability(
            slot=AbilitySlot.A,
            now=now,
            target_eid=1517,
            status_manager=self.sm,
            damage_queue=self.queue,
            all_heroes=self.heroes,
        )

        ops = [f[0] for f in frames]
        self.assertIn(wire.OP.ABILITY_CAST, ops)
        self.assertIn(wire.OP.TIMER_TICK, ops)
        self.assertIn(wire.OP.POSITION_EVENT, ops)
        self.assertIn(wire.OP.COMBAT_DELTA, ops)

        # Target took damage
        self.assertLess(self.enemy.hp, init_enemy_hp)

        # 50% slow applied on enemy
        self.assertTrue(self.sm.has_effect(1517, StatusType.SLOW, now=10.5))
        self.assertAlmostEqual(self.sm.get_speed_multiplier(1517, now=10.5), 0.50)

        # Achilles shot is now on cooldown (5.0s)
        self.assertFalse(self.kit.can_cast(AbilitySlot.A, now=12.0, status_manager=self.sm))
        self.assertTrue(self.kit.can_cast(AbilitySlot.A, now=15.1, status_manager=self.sm))

    def test_achilles_shot_out_of_range(self):
        """Cannot hit target outside 6.5u range."""
        self.enemy.x = 20.0  # distance 20.0 > 6.5
        frames = self.kit.cast_ability(
            slot=AbilitySlot.A,
            now=10.0,
            target_eid=1517,
            status_manager=self.sm,
            damage_queue=self.queue,
            all_heroes=self.heroes,
        )
        combat_deltas = [f for f in frames if f[0] == wire.OP.COMBAT_DELTA]
        self.assertEqual(len(combat_deltas), 0)

    def test_twirling_silver_self_buff(self):
        """Ability B grants temporary movement speed and faster basic attacks."""
        base_speed = self.hero.speed
        base_cd = self.hero.attack_cooldown

        frames = self.kit.cast_ability(
            slot=AbilitySlot.B,
            now=10.0,
            status_manager=self.sm,
        )

        ops = [f[0] for f in frames]
        self.assertIn(wire.OP.ABILITY_CAST, ops)
        self.assertIn(wire.OP.TIMER_TICK, ops)
        self.assertIn(wire.OP.POSITION_EVENT, ops)

        # Speed buffed +40%
        self.assertAlmostEqual(self.hero.speed, base_speed * 1.40)
        # Attack cooldown reduced
        self.assertLess(self.hero.attack_cooldown, base_cd)

    def test_hellfire_brew_massive_damage(self):
        """Ability C deals 350 crystal damage with kind=3 fireball impact."""
        self.enemy.x = 10.0  # within 15.0u ult range
        init_enemy_hp = self.enemy.hp

        frames = self.kit.cast_ability(
            slot=AbilitySlot.ULT,
            now=20.0,
            target_eid=1517,
            status_manager=self.sm,
            damage_queue=self.queue,
            all_heroes=self.heroes,
        )

        ops = [f[0] for f in frames]
        self.assertIn(wire.OP.ABILITY_CAST, ops)
        self.assertIn(wire.OP.TIMER_TICK, ops)
        self.assertIn(wire.OP.POSITION_EVENT, ops)

        # Verify kind 3 fireball event
        p_event = next(f[1] for f in frames if f[0] == wire.OP.POSITION_EVENT)
        _, x, z, y, kind = struct.unpack_from(">IfIfB", p_event, 0)
        self.assertEqual(kind, 3)

        # Target took massive crystal damage
        self.assertLess(self.enemy.hp, init_enemy_hp - 200.0)

    def test_silence_and_stun_block_ability_casting(self):
        """Silenced or stunned heroes cannot cast any abilities."""
        self.sm.apply_effect(StatusEffect(
            effect_id="silence_hero",
            effect_type=StatusType.SILENCE,
            source_eid=1517,
            target_eid=1500,
            duration=3.0,
            applied_at=10.0,
            expires_at=13.0,
        ))

        self.assertFalse(self.kit.can_cast(AbilitySlot.A, now=11.0, status_manager=self.sm))
        self.assertFalse(self.kit.can_cast(AbilitySlot.B, now=11.0, status_manager=self.sm))
        self.assertFalse(self.kit.can_cast(AbilitySlot.ULT, now=11.0, status_manager=self.sm))

        # After silence expires, can cast again
        self.assertTrue(self.kit.can_cast(AbilitySlot.A, now=13.5, status_manager=self.sm))


class TestCatherineKit(unittest.TestCase):

    def setUp(self):
        self.sm = StatusManager()
        self.queue = DamageModifierQueue()
        self.hero = hero_movement.HeroMovement(eid=1500, team=1, x=0.0, y=0.0)
        self.enemy = hero_movement.HeroMovement(eid=1517, team=2, x=5.0, y=0.0)
        self.kit = abilities.create_catherine_kit(self.hero)
        self.heroes = {1500: self.hero, 1517: self.enemy}

    def test_merciless_pursuit_stun(self):
        """Ability A applies damage and 1.2s STUN."""
        now = 10.0
        init_hp = self.enemy.hp
        frames = self.kit.cast_ability(
            slot=AbilitySlot.A,
            now=now,
            target_eid=1517,
            status_manager=self.sm,
            damage_queue=self.queue,
            all_heroes=self.heroes,
        )
        ops = [f[0] for f in frames]
        self.assertIn(wire.OP.ABILITY_CAST, ops)
        self.assertIn(wire.OP.POSITION, ops)  # dash position
        self.assertIn(wire.OP.COMBAT_DELTA, ops)
        self.assertLess(self.enemy.hp, init_hp)
        self.assertTrue(self.sm.has_effect(1517, StatusType.STUN, now=10.5))

    def test_stormguard_barrier(self):
        """Ability B applies 300 HP barrier."""
        now = 10.0
        frames = self.kit.cast_ability(
            slot=AbilitySlot.B,
            now=now,
            status_manager=self.sm,
            damage_queue=self.queue,
            all_heroes=self.heroes,
        )
        self.assertTrue(self.sm.has_effect(1500, StatusType.BARRIER, now=11.0))
        self.assertEqual(self.sm.get_barrier(1500, now=11.0), 300.0)

    def test_blast_tremor_aoe_silence(self):
        """Ult damages and silences all enemies in 9.0u radius."""
        now = 10.0
        init_hp = self.enemy.hp
        frames = self.kit.cast_ability(
            slot=AbilitySlot.ULT,
            now=now,
            status_manager=self.sm,
            damage_queue=self.queue,
            all_heroes=self.heroes,
        )
        self.assertLess(self.enemy.hp, init_hp)
        self.assertTrue(self.sm.has_effect(1517, StatusType.SILENCE, now=11.0))

    def test_create_hero_kit_factory(self):
        c_kit = abilities.create_hero_kit(self.hero, hero_id=245)
        self.assertEqual(c_kit.abilities[AbilitySlot.A].name, "Merciless Pursuit")
        r_kit = abilities.create_hero_kit(self.hero, hero_id=924)
        self.assertEqual(r_kit.abilities[AbilitySlot.A].name, "Achilles Shot")


if __name__ == "__main__":
    unittest.main()

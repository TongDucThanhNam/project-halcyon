"""Ability contracts and behavior tests against source-backed rank-one anchors.

The previous assertions treated Catherine A as a dash and Ringo's channel as
instant damage. Those premises contradicted the real kits; tests below check
timing, resources and effects, including the former false-positive cases.
"""
import math
import struct
from types import SimpleNamespace
import unittest

from server import abilities, cooldown_wire, hero_movement, roster, wire
from server.abilities import AbilityDefinition, AbilitySlot, AbilityType, HeroKit, create_ringo_kit
from server.status_effects import DamageModifierQueue, DamageType, StatusEffect, StatusManager, StatusType


class TestAbilityWireEncoding(unittest.TestCase):
    def test_position_event_1046_encoding(self):
        body = roster.build_position_event(1500, -38.5, 22.7, z=0, kind=3)
        self.assertEqual(len(body), roster.POSITION_EVENT_PAYLOAD_SIZE)
        eid, x, z, y, kind = struct.unpack_from(">IfIfB", body, 0)
        self.assertEqual((eid, z, kind), (1500, 0, 3))
        self.assertAlmostEqual(x, -38.5, places=2)
        self.assertAlmostEqual(y, 22.7, places=2)
        self.assertEqual(body[17:], bytes(5))

    def test_ability_cast_1078_roundtrip(self):
        body = roster.build_ability_cast(AbilitySlot.B)
        self.assertEqual(len(body), roster.ABILITY_CAST_PAYLOAD_SIZE)
        self.assertEqual(roster.parse_ability_cast(body), 1)

    def test_internal_skillshot_adapter_roundtrip(self):
        # The adapter's contract is checked here; client 1102 semantics remain open.
        payload = struct.pack(">IIfffBB", 1500, 1517, 12.5, 0.0, 34.2, 2, 1)
        caster, target, x, y, slot, flag = roster.parse_skillshot_cast(payload)
        self.assertEqual((caster, target, slot, flag), (1500, 1517, 2, 1))
        self.assertAlmostEqual(x, 12.5, places=2)
        self.assertAlmostEqual(y, 34.2, places=2)


class AbilityFixture(unittest.TestCase):
    def setUp(self):
        self.hero = hero_movement.HeroMovement(eid=1500, team=1, x=0.0, y=0.0)
        self.hero.energy = self.hero.max_energy = 500.0
        self.enemy = hero_movement.HeroMovement(eid=1517, team=2, x=5.0, y=0.0)
        self.enemy.hp = self.enemy.max_hp = 2000.0
        self.ally = hero_movement.HeroMovement(eid=1515, team=1, x=4.0, y=0.0)
        self.heroes = {h.eid: h for h in (self.hero, self.enemy, self.ally)}
        self.sm = StatusManager()
        self.queue = DamageModifierQueue()
        self.kit = create_ringo_kit(self.hero)

    def cast(self, slot=AbilitySlot.A, now=10.0, **kwargs):
        return self.kit.cast_ability(slot, now, status_manager=self.sm, damage_queue=self.queue,
                                     all_heroes=self.heroes, **kwargs)

    def step(self, now):
        return self.kit.step(now, status_manager=self.sm, damage_queue=self.queue, all_heroes=self.heroes)

    def cc(self, kind, start=10.5, duration=0.5):
        self.sm.apply_effect(StatusEffect("interrupt", kind, self.enemy.eid, self.hero.eid,
                                          duration, start, start + duration))


class TestRingoKit(AbilityFixture):
    def test_achilles_damage_slow_energy_and_cooldown(self):
        before_hp, before_energy = self.enemy.hp, self.hero.energy
        frames = self.cast(target_eid=self.enemy.eid)
        ops = [op for op, _ in frames]
        self.assertIn(wire.OP.TARGET_ACQUIRE, ops)
        self.assertNotIn(wire.OP.ABILITY_CAST, ops)
        timer = cooldown_wire.parse_timer_tick(next(body for op, body in frames if op == wire.OP.TIMER_TICK))
        self.assertEqual((timer.eid, timer.tag, timer.remaining, timer.duration),
                         (1500, 0xC8D51D33, 9.0, 9.0))
        self.assertEqual(timer.state, bytes((0, 1, 1, 0, 1, 0)))
        ack = next(body for op, body in frames if op == wire.OP.TARGET_ACQUIRE)
        self.assertEqual(struct.unpack_from(">IIB", ack), (1500, 1517, 0))
        self.assertIn(wire.OP.COMBAT_DELTA, ops)
        self.assertAlmostEqual(before_hp - self.enemy.hp, 80.0 / 1.2)
        self.assertEqual(before_energy - self.hero.energy, 40.0)
        self.assertAlmostEqual(self.sm.get_speed_multiplier(self.enemy.eid, 10.5), 0.7)
        self.assertFalse(self.sm.has_effect(self.enemy.eid, StatusType.SLOW, 11.5))
        self.assertFalse(self.kit.can_cast(AbilitySlot.A, 18.9, self.sm))
        self.assertTrue(self.kit.can_cast(AbilitySlot.A, 19.0, self.sm))

    def test_out_of_range_cast_does_not_consume_energy_or_cooldown(self):
        self.enemy.x = 8.01
        energy = self.hero.energy
        self.assertEqual(self.cast(target_eid=self.enemy.eid), [])
        self.assertEqual(self.hero.energy, energy)
        self.assertEqual(self.kit.cooldowns[AbilitySlot.A], 0.0)

    def test_invalid_dead_or_friendly_target_is_rejected(self):
        for eid in (987654, self.ally.eid, self.hero.eid):
            with self.subTest(target=eid):
                self.assertEqual(self.cast(target_eid=eid), [])
        self.enemy.is_alive = False
        self.assertEqual(self.cast(target_eid=self.enemy.eid), [])
        self.assertEqual(self.hero.energy, 500.0)

    def test_not_enough_energy_prevents_cast(self):
        self.hero.energy = 39.99
        self.assertFalse(self.kit.can_cast(AbilitySlot.A, 10.0))
        self.assertEqual(self.cast(target_eid=self.enemy.eid), [])
        self.assertEqual(self.hero.energy, 39.99)

    def test_exact_energy_cost_can_be_spent(self):
        self.hero.energy = 40.0
        self.assertTrue(self.cast(target_eid=self.enemy.eid))
        self.assertEqual(self.hero.energy, 0.0)

    def test_cooldown_acceleration_applies_without_mutating_rank_table(self):
        self.hero.cooldown_reduction = 0.5
        self.cast(target_eid=self.enemy.eid)
        self.assertEqual(self.kit.cooldowns[AbilitySlot.A], 16.0)
        self.assertEqual(self.kit.abilities[AbilitySlot.A].cooldown, 9.0)

    def test_twirling_silver_timed_modifiers_do_not_mutate_item_stats(self):
        base_speed, base_cd = self.hero.speed, self.hero.attack_cooldown
        self.cast(AbilitySlot.B)
        self.assertEqual(self.hero.speed, base_speed)
        self.assertEqual(self.hero.attack_cooldown, base_cd)
        self.assertAlmostEqual(self.hero.effective_speed(10.1), base_speed + 0.5)
        self.assertEqual(self.sm.get_attack_speed_bonus(self.hero.eid, 10.1), 30.0)
        self.assertAlmostEqual(self.hero.effective_speed(14.0), base_speed)
        self.assertEqual(self.sm.get_attack_speed_bonus(self.hero.eid, 14.0), 0.0)
        self.assertFalse(self.sm.has_effect(self.hero.eid, StatusType.BARRIER, 10.1))

    def test_hellfire_channels_then_travels_before_shield_piercing_impact(self):
        before = self.enemy.hp
        self.cast(AbilitySlot.ULT, target_eid=self.enemy.eid)
        self.assertTrue(self.kit.is_channeling)
        self.assertEqual(self.enemy.hp, before)
        self.assertFalse(self.kit.can_cast(AbilitySlot.A, 10.1))
        self.assertEqual(self.step(11.49), [])
        frames = self.step(11.5)
        self.assertFalse(self.kit.is_channeling)
        self.assertEqual(self.enemy.hp, before)
        self.assertEqual(frames, [])
        self.assertEqual(len(self.kit._projectiles), 1)
        self.step(11.9)
        self.assertEqual(self.enemy.hp, before)
        frames = self.step(11.95)
        self.assertAlmostEqual(before - self.enemy.hp, 250.0)
        self.assertNotIn(wire.OP.POSITION_EVENT, [op for op, _ in frames])

    def test_each_hard_cc_interrupts_channel_even_after_effect_expires(self):
        for kind in (StatusType.STUN, StatusType.SILENCE, StatusType.KNOCKBACK):
            with self.subTest(kind=kind):
                self.setUp()
                before = self.enemy.hp
                self.cast(AbilitySlot.ULT, target_eid=self.enemy.eid)
                self.cc(kind, duration=0.1)
                self.sm.clean_expired(11.5)
                self.step(11.5)
                self.assertFalse(self.kit.is_channeling)
                self.assertEqual(self.enemy.hp, before)
                self.assertEqual(self.kit.last_interruption_at, 11.5)
                self.assertEqual(self.hero.energy, 400.0)
                self.assertEqual(self.kit.cooldowns[AbilitySlot.ULT], 100.0)

    def test_cc_immunity_keeps_channel_alive(self):
        self.sm.apply_effect(StatusEffect("immunity", StatusType.CC_IMMUNITY, 1500, 1500, 3.0, 10.0, 13.0))
        before = self.enemy.hp
        self.cast(AbilitySlot.ULT, target_eid=self.enemy.eid)
        self.cc(StatusType.STUN)
        self.step(11.5)
        self.step(12.0)
        self.assertLess(self.enemy.hp, before)

    def test_root_allows_channel_but_blocks_dash(self):
        self.cc(StatusType.ROOT, start=9.0, duration=4.0)
        self.assertTrue(self.cast(AbilitySlot.ULT, target_eid=self.enemy.eid))
        self.step(11.5)
        self.assertIsNone(self.kit.last_interruption_at)
        self.kit = abilities.create_taka_kit(self.hero)
        self.assertFalse(self.kit.can_cast(AbilitySlot.A, 12.0, self.sm))

    def test_death_interrupts_channel(self):
        self.cast(AbilitySlot.ULT, target_eid=self.enemy.eid)
        before = self.enemy.hp
        self.hero.is_alive = False
        self.step(12.0)
        self.assertEqual(self.enemy.hp, before)
        self.assertFalse(self.hero.channeling)

    def test_success_callback_fires_once_and_only_on_accepted_cast(self):
        calls = []
        self.kit.on_cast = lambda hero, now: calls.append((hero.eid, now))
        self.cast(target_eid=self.enemy.eid)
        self.cast(target_eid=self.enemy.eid)
        self.assertEqual(calls, [(self.hero.eid, 10.0)])

    def test_shared_damage_callback_owns_damage_exactly_once(self):
        calls = []
        def damage(caster, target, raw, kind, now):
            calls.append((caster.eid, target.eid, raw, kind, now))
            target.hp -= 12.0
            return []
        before = self.enemy.hp
        self.cast(target_eid=self.enemy.eid, damage_callback=damage)
        self.assertEqual(before - self.enemy.hp, 12.0)
        self.assertEqual(calls, [(1500, 1517, 80.0, DamageType.CRYSTAL, 10.0)])


class TestGeometryAbilities(AbilityFixture):
    def test_delayed_ground_hit_checks_position_at_impact(self):
        self.kit = abilities.create_celeste_kit(self.hero)
        before = self.enemy.hp
        self.cast(target_pos=(5.0, 0.0))
        self.enemy.x = 9.0
        self.assertEqual(self.step(10.59), [])
        self.step(10.6)
        self.assertEqual(self.enemy.hp, before)

    def test_delayed_ground_hit_catches_enemy_entering_after_cast(self):
        self.kit = abilities.create_celeste_kit(self.hero)
        self.enemy.x = 9.0
        before = self.enemy.hp
        self.cast(target_pos=(5.0, 0.0))
        self.enemy.x = 5.0
        self.step(10.6)
        self.assertAlmostEqual(before - self.enemy.hp, 60.0 / 1.2)

    def test_released_ground_effect_survives_caster_death(self):
        self.kit = abilities.create_celeste_kit(self.hero)
        self.cast(target_pos=(5.0, 0.0))
        self.hero.is_alive = False
        before = self.enemy.hp
        self.step(10.6)
        self.assertLess(self.enemy.hp, before)

    def test_heliogenesis_second_star_supernova(self):
        self.kit = abilities.create_celeste_kit(self.hero)
        self.cast(target_pos=(5.0, 0.0))
        self.step(10.6)
        self.enemy.y = 3.0
        before = self.enemy.hp
        self.cast(now=13.0, target_pos=(5.0, 0.0))
        self.step(13.39)
        self.assertEqual(self.enemy.hp, before)
        self.step(13.4)
        self.assertAlmostEqual(before - self.enemy.hp, 80.0 / 1.2)

    def test_ground_cast_rejects_nonfinite_or_out_of_range_point(self):
        self.kit = abilities.create_celeste_kit(self.hero)
        for point in ((math.nan, 0.0), (math.inf, 0.0), (7.001, 0.0)):
            with self.subTest(point=point):
                self.assertEqual(self.cast(target_pos=point), [])
        self.assertEqual(self.hero.energy, 500.0)

    def test_cone_excludes_behind_and_friendly_targets(self):
        self.kit = abilities.create_gwen_kit(self.hero)
        behind = hero_movement.HeroMovement(eid=1520, team=2, x=-4.0, y=0.0)
        self.heroes[behind.eid] = behind
        hp_behind, hp_ally, hp_enemy = behind.hp, self.ally.hp, self.enemy.hp
        self.cast(target_pos=(10.0, 0.0))
        self.step(10.3)
        self.assertEqual(behind.hp, hp_behind)
        self.assertEqual(self.ally.hp, hp_ally)
        self.assertLess(self.enemy.hp, hp_enemy)

    def test_gwen_line_passes_minion_and_stops_at_first_hero(self):
        self.kit = abilities.create_gwen_kit(self.hero)
        minion = SimpleNamespace(eid=6000, side=2, alive=True, x=2.0, y=0.0, hp=600.0)
        behind = hero_movement.HeroMovement(eid=1520, team=2, x=8.0, y=0.0)
        self.heroes[behind.eid] = behind
        before = behind.hp
        self.cast(AbilitySlot.ULT, target_pos=(14.0, 0.0), all_minions=[minion])
        self.kit.step(10.6, self.sm, self.queue, self.heroes, [minion])
        self.assertLess(minion.hp, 600.0)
        self.assertLess(self.enemy.hp, 2000.0)
        self.assertEqual(behind.hp, before)
        self.assertTrue(self.sm.has_effect(self.enemy.eid, StatusType.STUN, 10.7))
        self.assertFalse(self.sm.has_effect(minion.eid, StatusType.STUN, 10.7))

    def test_lance_line_pierces_multiple_enemies(self):
        self.kit = abilities.create_lance_kit(self.hero)
        second = hero_movement.HeroMovement(eid=1520, team=2, x=3.0, y=0.0)
        self.heroes[second.eid] = second
        before = second.hp
        self.cast(target_pos=(6.0, 0.0))
        self.step(10.7)
        self.assertLess(second.hp, before)
        self.assertLess(self.enemy.hp, 2000.0)
        self.assertTrue(self.sm.has_effect(second.eid, StatusType.ROOT, 10.8))

    def test_vector_dash_lands_behind_enemy_and_hits(self):
        self.kit = abilities.create_taka_kit(self.hero)
        self.enemy.x = 3.0
        before = self.enemy.hp
        self.cast(target_eid=self.enemy.eid)
        self.assertAlmostEqual(self.hero.x, 4.0)
        self.assertAlmostEqual(self.hero.y, 0.0)
        self.assertLess(self.enemy.hp, before)

    def test_terrain_stopped_dash_does_not_hit_through_wall(self):
        self.kit = abilities.create_taka_kit(self.hero)
        self.enemy.x = 3.0
        def blocked_dash(x, y, now=None):
            self.hero.x = 1.0
            return []
        self.hero.dash_to = blocked_dash
        before = self.enemy.hp
        self.cast(target_eid=self.enemy.eid)
        self.assertEqual(self.enemy.hp, before)
        self.assertEqual(self.hero.x, 1.0)

    def test_skedaddle_can_cleanse_stun_and_grants_brief_immunity(self):
        self.kit = abilities.create_gwen_kit(self.hero)
        self.cc(StatusType.STUN, start=9.0, duration=4.0)
        self.assertTrue(self.cast(AbilitySlot.B))
        self.assertFalse(self.sm.has_effect(self.hero.eid, StatusType.STUN, 10.0))
        self.assertTrue(self.sm.has_effect(self.hero.eid, StatusType.CC_IMMUNITY, 10.4))
        self.assertFalse(self.sm.has_effect(self.hero.eid, StatusType.CC_IMMUNITY, 10.5))


class TestCatherineKit(AbilityFixture):
    def setUp(self):
        super().setUp()
        self.kit = abilities.create_catherine_kit(self.hero)

    def test_merciless_pursuit_runs_and_stuns_next_attack_once(self):
        before = self.enemy.hp
        frames = self.cast()
        self.assertEqual(self.kit.basic_attack_variant(10.1), 0)
        self.assertEqual((self.hero.x, self.hero.y), (0.0, 0.0))
        self.assertNotIn(wire.OP.COMBAT_DELTA, [op for op, _ in frames])
        self.assertAlmostEqual(self.hero.effective_speed(10.1), self.hero.speed + 2.75)
        self.kit.on_basic_attack(self.enemy, 10.5, self.sm, self.queue)
        self.assertIsNone(self.kit.basic_attack_variant(10.6))
        self.assertAlmostEqual(before - self.enemy.hp, 35.0 / 1.2)
        self.assertTrue(self.sm.has_effect(self.enemy.eid, StatusType.STUN, 10.6))
        self.assertAlmostEqual(self.hero.effective_speed(10.6), self.hero.speed)
        self.assertEqual(self.kit.on_basic_attack(self.enemy, 10.7, self.sm, self.queue), [])

    def test_expired_pursuit_does_not_stun(self):
        self.cast()
        self.assertEqual(self.kit.on_basic_attack(self.enemy, 11.5, self.sm, self.queue), [])

    def test_stormguard_does_not_substitute_an_incorrect_barrier(self):
        self.assertTrue(self.cast(AbilitySlot.B))
        self.assertFalse(self.sm.has_effect(self.hero.eid, StatusType.BARRIER, 10.1))
        self.assertEqual(self.kit._stormguard_until, 14.0)

    def test_blast_tremor_directional_delayed_silence(self):
        before = self.enemy.hp
        self.cast(AbilitySlot.ULT, target_pos=(11.0, 0.0))
        self.assertEqual(self.enemy.hp, before)
        self.step(10.966)
        self.assertAlmostEqual(before - self.enemy.hp, 400.0 / 1.2)
        self.assertTrue(self.sm.has_effect(self.enemy.eid, StatusType.SILENCE, 11.0))

    def test_factory_uses_correct_selected_identity(self):
        self.assertEqual(abilities.create_hero_kit(self.hero, 245).name, "Koshka")
        self.assertEqual(abilities.create_hero_kit(self.hero, 924).name, "Viola")
        self.assertEqual(abilities.create_hero_kit(self.hero, 244).name, "Adagio")
        self.assertEqual(abilities.create_hero_kit(self.hero, hero_name="Ringo").name, "Ringo")
        self.assertEqual(abilities.create_hero_kit(self.hero, 98765).abilities, {})


class TestAdagioKit(AbilityFixture):
    def setUp(self):
        super().setUp()
        self.kit = abilities.create_adagio_kit(self.hero)

    def test_gift_of_fire_heals_self_then_ticks_and_burns(self):
        self.hero.hp = 100.0
        before = self.hero.hp
        enemy_hp = self.enemy.hp
        self.cast()
        self.assertGreater(self.hero.hp, before)
        burst_hp = self.hero.hp
        self.assertEqual(self.enemy.hp, enemy_hp)
        self.step(10.5)
        self.assertGreater(self.hero.hp, burst_hp)
        self.assertLess(self.enemy.hp, enemy_hp)
        self.assertAlmostEqual(self.sm.get_speed_multiplier(self.enemy.eid, 10.1), 0.3)

    def test_gift_can_target_ally_but_not_enemy(self):
        self.assertEqual(self.cast(target_eid=self.enemy.eid), [])
        self.ally.hp = 100.0
        self.assertTrue(self.cast(target_eid=self.ally.eid))
        self.assertGreater(self.ally.hp, 100.0)

    def test_agent_of_wrath_empowers_exactly_five_attacks(self):
        self.cast(AbilitySlot.B)
        for index in range(5):
            self.assertTrue(self.kit.on_basic_attack(self.enemy, 10.1 + index, self.sm, self.queue))
        self.assertEqual(self.kit.on_basic_attack(self.enemy, 15.2, self.sm, self.queue), [])

    def test_ally_receives_wrath_even_with_different_kit(self):
        self.cast(AbilitySlot.B, target_eid=self.ally.eid)
        ally_kit = create_ringo_kit(self.ally)
        before = self.enemy.hp
        ally_kit.on_basic_attack(self.enemy, 11.0, self.sm, self.queue)
        self.assertAlmostEqual(before - self.enemy.hp, 30.0 / 1.2)

    def test_verse_requires_two_seconds_and_stuns_only_burning_targets(self):
        self.kit._arcane_fire[self.enemy.eid] = 20.0
        other = hero_movement.HeroMovement(eid=1520, team=2, x=6.0, y=0.0, hp=2000.0, max_hp=2000.0)
        self.heroes[other.eid] = other
        before = self.enemy.hp
        self.cast(AbilitySlot.ULT)
        self.assertEqual(self.enemy.hp, before)
        self.step(11.99)
        self.assertEqual(self.enemy.hp, before)
        self.step(12.0)
        self.assertAlmostEqual(before - self.enemy.hp, 800.0 / 1.2)
        self.assertTrue(self.sm.has_effect(self.enemy.eid, StatusType.STUN, 12.1))
        self.assertFalse(self.sm.has_effect(other.eid, StatusType.STUN, 12.1))

    def test_ally_wrath_reads_caster_fire_metadata_on_real_slotted_minion(self):
        from server.wave import Minion
        target = Minion(4610, 2, 0)
        target.x, target.y = 5.0, 0.0
        self.cast(AbilitySlot.A, all_minions=[target])
        self.cast(AbilitySlot.B, target_eid=self.ally.eid)
        ally_kit = create_ringo_kit(self.ally)
        before = target.hp
        ally_kit.on_basic_attack(target, 11.0, self.sm, self.queue)
        self.assertAlmostEqual(before - target.hp, 35.0)
        self.assertFalse(hasattr(target, "arcane_fire"))
        self.kit.step(15.1, self.sm, self.queue, self.heroes, [target])
        self.assertNotIn(target.eid, self.kit._arcane_fire)
        before = target.hp
        ally_kit.on_basic_attack(target, 15.5, self.sm, self.queue)
        self.assertAlmostEqual(before - target.hp, 30.0)

    def test_verse_hard_cc_cancels_damage(self):
        self.cast(AbilitySlot.ULT)
        before = self.enemy.hp
        self.cc(StatusType.STUN)
        self.step(12.0)
        self.assertEqual(self.enemy.hp, before)

    def test_interruption_removes_channel_fortified_health(self):
        self.cast(AbilitySlot.ULT)
        self.assertTrue(self.sm.has_effect(self.hero.eid, StatusType.FORTIFIED_HEALTH, 10.0))
        self.cc(StatusType.STUN, start=10.1)
        self.step(10.1)
        self.assertFalse(self.sm.has_effect(self.hero.eid, StatusType.FORTIFIED_HEALTH, 10.1))


class TestAbilityRanks(AbilityFixture):
    def test_runtime_selection_starts_unlearned(self):
        self.kit = abilities.create_hero_kit(self.hero, 243)
        self.assertEqual(self.kit.name, "Ringo")
        self.assertFalse(self.kit.can_cast(AbilitySlot.A, 10.0))
        self.assertTrue(self.kit.upgrade_ability(AbilitySlot.A, 1))
        self.assertTrue(self.kit.can_cast(AbilitySlot.A, 10.0))

    def test_actual_selection_ids_route_all_implemented_kits(self):
        expected = {242: "Catherine", 243: "Ringo", 244: "Adagio", 245: "Koshka", 256: "Taka",
                    275: "Lance", 285: "Celeste", 395: "Gwen", 925: "Amael"}
        for hero_id, name in expected.items():
            with self.subTest(hero_id=hero_id):
                self.assertEqual(abilities.create_hero_kit(self.hero, hero_id).name, name)

    def test_rank_changes_real_cost_damage_and_cooldown_curves(self):
        self.assertTrue(self.kit.upgrade_ability(AbilitySlot.A, 2))
        self.assertEqual(self.kit.ranks[AbilitySlot.A], 2)
        definition = self.kit.abilities[AbilitySlot.A]
        self.assertEqual((definition.energy_cost, definition.base_damage, definition.cooldown), (45.0, 125.0, 8.5))
        before = self.hero.energy
        self.cast(target_eid=self.enemy.eid)
        self.assertEqual(before - self.hero.energy, 45.0)

    def test_ultimate_unlocks_at_six_nine_twelve(self):
        self.kit.reset_ranks()
        self.assertFalse(self.kit.upgrade_ability(AbilitySlot.ULT, 5))
        self.assertTrue(self.kit.upgrade_ability(AbilitySlot.ULT, 6))
        self.assertFalse(self.kit.upgrade_ability(AbilitySlot.ULT, 8))
        self.assertTrue(self.kit.upgrade_ability(AbilitySlot.ULT, 9))
        self.assertFalse(self.kit.upgrade_ability(AbilitySlot.ULT, 11))
        self.assertTrue(self.kit.upgrade_ability(AbilitySlot.ULT, 12))
        self.assertFalse(self.kit.upgrade_ability(AbilitySlot.ULT, 12))
        self.assertEqual(self.kit.abilities[AbilitySlot.ULT].energy_cost, 130.0)

    def test_max_rank_cannot_consume_further_upgrades(self):
        for _ in range(4):
            self.assertTrue(self.kit.upgrade_ability(AbilitySlot.A, 12))
        before = self.kit.abilities[AbilitySlot.A]
        self.assertFalse(self.kit.upgrade_ability(AbilitySlot.A, 12))
        self.assertIs(self.kit.abilities[AbilitySlot.A], before)

    def test_taka_overdrive_cost_is_zero(self):
        self.kit = abilities.create_taka_kit(self.hero)
        for _ in range(4):
            self.kit.upgrade_ability(AbilitySlot.A, 12)
        self.hero.energy = 0.0
        self.assertTrue(self.kit.can_cast(AbilitySlot.A, 10.0))
        self.assertEqual(self.kit.abilities[AbilitySlot.A].cooldown, 7.5)

    def test_celeste_overdrive_applies_non_linear_changes(self):
        self.kit = abilities.create_celeste_kit(self.hero)
        for _ in range(4):
            self.kit.upgrade_ability(AbilitySlot.B, 12)
        definition = self.kit.abilities[AbilitySlot.B]
        self.assertEqual((definition.energy_cost, definition.base_damage, definition.cooldown), (0.0, 475.0, 9.0))


class TestAmaelKit(AbilityFixture):
    def setUp(self):
        super().setUp()
        self.kit = abilities.create_amael_kit(self.hero)

    def test_super_punch_first_press_charges_second_press_dashes(self):
        hp, energy = self.enemy.hp, self.hero.energy
        self.cast()
        self.assertEqual(self.enemy.hp, hp)
        self.assertEqual(self.hero.x, 0.0)
        self.assertEqual(self.hero.energy, energy - 40.0)
        self.assertTrue(self.kit.can_cast(AbilitySlot.A, 11.5, self.sm))
        self.cast(now=11.5, target_pos=(10.0, 0.0))
        self.assertGreater(self.hero.x, self.enemy.x)
        self.assertLess(self.enemy.hp, hp)
        self.assertEqual(self.hero.energy, energy - 40.0)
        self.assertTrue(self.sm.has_effect(self.enemy.eid, StatusType.KNOCKBACK, 11.6))

    def test_charge_can_release_with_empty_energy_pool(self):
        self.hero.energy = 40.0
        self.cast()
        self.assertTrue(self.cast(now=11.5, target_pos=(10.0, 0.0)))
        self.assertEqual(self.hero.energy, 0.0)

    def test_hard_cc_discards_charged_recast(self):
        self.cast()
        self.cc(StatusType.SILENCE)
        self.step(11.5)
        self.assertIsNone(self.kit._charge)
        self.assertFalse(self.kit.can_cast(AbilitySlot.A, 11.5, self.sm))

    def test_charge_expires_after_five_seconds(self):
        self.cast()
        self.step(15.0)
        self.assertIsNone(self.kit._charge)
        self.assertFalse(self.kit.can_cast(AbilitySlot.A, 15.0, self.sm))

    def test_lawn_mower_backstep_then_piercing_forward_sweep(self):
        other = hero_movement.HeroMovement(eid=1520, team=2, x=2.0, y=0.0)
        self.heroes[other.eid] = other
        enemy_hp, other_hp = self.enemy.hp, other.hp
        self.cast(AbilitySlot.B, target_pos=(9.0, 0.0))
        self.assertAlmostEqual(self.hero.x, -3.0)
        self.assertEqual(self.enemy.hp, enemy_hp)
        self.step(10.5)
        self.assertAlmostEqual(self.hero.x, 6.0)
        self.assertLess(self.enemy.hp, enemy_hp)
        self.assertLess(other.hp, other_hp)

    def test_lawn_mower_hard_cc_interrupts_forward_dash(self):
        self.cast(AbilitySlot.B, target_pos=(9.0, 0.0))
        self.cc(StatusType.STUN, start=10.1)
        before = self.enemy.hp
        self.step(10.5)
        self.assertAlmostEqual(self.hero.x, -3.0)
        self.assertEqual(self.enemy.hp, before)

    def test_bull_dozer_has_area_followup_only_on_controlled_target(self):
        other = hero_movement.HeroMovement(eid=1520, team=2, x=5.0, y=2.0)
        self.heroes[other.eid] = other
        hp = other.hp
        self.sm.apply_effect(StatusEffect("root_target", StatusType.ROOT, 1500, 1517, 2.0, 9.0, 11.0))
        self.cast(AbilitySlot.ULT, target_eid=self.enemy.eid)
        self.assertLess(other.hp, hp)
        self.assertTrue(self.sm.has_effect(other.eid, StatusType.KNOCKBACK, 10.1))


if __name__ == "__main__":
    unittest.main()

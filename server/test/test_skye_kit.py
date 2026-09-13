"""Skye's owned action/constants evidence and authoritative spell lifecycles.

Geometry and directional speed assertions cover the explicit simulation
policies; they do not claim a native visual or timing measurement.
"""
import unittest

from server.paths import pc_data_dir
from server import abilities, ability_wire, buff_wire, cooldown_wire, hero_movement
from server.status_effects import DamageModifierQueue, StatusEffect, StatusManager, StatusType
from server.structures import Structure
from server.vision import Vision
from server.wave import Minion
from Tools.Teardown.inspect_ability_actions import read_actions
from Tools.Teardown.inspect_ability_constants import read_records


A, B, C = abilities.AbilitySlot
NATIVE = pc_data_dir() / '0C/0CB20BA22E7D1BBCC89CBCF4895B8E6F'


class SkyeFixture(unittest.TestCase):
    def setUp(self):
        self.hero = hero_movement.HeroMovement(1500, 1, 0, 0, attack_damage=100,
                                              energy=1000, max_energy=1000)
        self.hero.crystal_power = 100
        self.enemy = hero_movement.HeroMovement(1517, 2, 5, 0, hp=10000, max_hp=10000)
        self.other = hero_movement.HeroMovement(1518, 2, 8, 0, hp=10000, max_hp=10000)
        self.ally = hero_movement.HeroMovement(1515, 1, 4, 0, hp=10000, max_hp=10000)
        for target in (self.enemy, self.other, self.ally):
            target.armor = target.shield = 0
        self.heroes = {h.eid: h for h in (self.hero, self.enemy, self.other, self.ally)}
        self.minions = []
        self.sm, self.queue = StatusManager(), DamageModifierQueue()
        self.kit = abilities.create_skye_kit(self.hero)

    def lock(self, now=10, target=None):
        return self.kit.on_basic_attack(target or self.enemy, now, self.sm, self.queue)

    def cast(self, slot, now=10, point=(10, 0)):
        return self.kit.cast_ability(slot, now, target_pos=point, status_manager=self.sm,
            damage_queue=self.queue, all_heroes=self.heroes, all_minions=self.minions)

    def step(self, now):
        return self.kit.step(now, self.sm, self.queue, self.heroes, self.minions)

    def cc(self, kind, now=10.15, duration=.01):
        self.sm.apply_effect(StatusEffect('incoming', kind, 1517, 1500, duration,
                                         now, now + duration))


class TestSkyeNativeConstants(SkyeFixture):
    @unittest.skipUnless(NATIVE.is_file(), 'operator-owned Skye CFF unavailable')
    def test_native_actions_costs_and_dps_are_joined_by_names_and_offsets(self):
        actions = read_actions(NATIVE)
        for slot, ordinal in ((A, 0), (B, 2), (C, 4)):
            expected = next(row for row in actions if row['name'] == f'Ability__Skye__{"ABC"[slot]}')
            definition = self.kit.abilities[slot]
            self.assertEqual((expected['index'], definition.native_action), (ordinal, ordinal))
            self.assertEqual(definition.tag_inst, cooldown_wire.native_ability_tag(expected['name']))
        self.assertEqual(next(row for row in actions if row['name'] == 'Ability__Skye__A_Cancel')['index'], 1)
        records = {row['pointer_offset']: row['coefficients'] for row in read_records(
            NATIVE, {'cooldown', 'energy cost', 'damagepersecond', 'lockonbonus', 'abilityareset',
                     'dashspeed', 'shottraveltime', 'duration', 'stun_duration', 'slowmagnitude'})}
        # Independent current A record; the old A_Cancel tooltip is stale.
        self.assertEqual(records[1532][:5], [140, 40, 40, 1.8, 1.2])
        for offset, expected in ((1404, [6, 0, -1]), (1468, [40, 10, 0]),
                                 (3400, [16, -2, -2]), (3464, [70, 0, 0]),
                                 (4988, [30, -6, 0]), (5052, [70, 20, 0])):
            self.assertEqual(records[offset][:3], expected)

    def test_factory_starts_unlearned_and_rank_curves_include_overdrives(self):
        kit = abilities.create_hero_kit(self.hero, 265)
        self.assertIsInstance(kit, abilities.SkyeKit)
        self.assertEqual(kit.ranks, {A: 0, B: 0, C: 0})
        for slot in (A, B):
            for _ in range(5):
                self.assertTrue(kit.upgrade_ability(slot, 12))
        for _ in range(3):
            self.assertTrue(kit.upgrade_ability(C, 12))
        self.assertEqual((kit.abilities[A].cooldown, kit.abilities[A].energy_cost,
                          kit.abilities[A].base_damage), (5, 80, 340))
        self.assertEqual((kit.abilities[B].cooldown, kit.abilities[B].base_damage), (6, 330))
        self.assertEqual((kit.abilities[C].cooldown, kit.abilities[C].energy_cost,
                          kit.abilities[C].base_damage), (18, 110, 350))
        self.assertEqual((kit.lock_duration, kit.lock_range), (7, 12.5))


class TestSkyeLock(SkyeFixture):
    def test_basic_hit_has_native_finite_and_indefinite_lock_buffs(self):
        self.lock()
        buffs = [buff_wire.parse_buff_add(p) for op, p in self.sm.drain_frames() if op == 1086]
        self.assertEqual([(b.kind, b.source_eid, b.target_eid, b.duration) for b in buffs],
            [(602, 1500, 1517, 4), (603, 1500, 1517, -1),
             (601, 1500, 1500, -1), (604, 1500, 1500, 1.7998046875)])
        self.assertEqual(self.hero.revealed_targets, {1517: 14})
        self.lock(11, self.other)
        self.assertEqual(self.hero.revealed_targets, {1518: 15})
        self.assertFalse(any(value.target_eid == 1517 for value in self.sm.presentation.active.values()))

    def test_missing_expired_dead_or_distant_lock_rejects_b_and_c_before_spending(self):
        for state in ('missing', 'expired', 'dead', 'distant'):
            with self.subTest(state=state):
                self.setUp()
                if state != 'missing':
                    self.lock(1)
                if state == 'dead':
                    self.enemy.is_alive = False
                if state == 'distant':
                    self.enemy.x = 30
                now = 5 if state == 'expired' else 2
                for slot in (B, C):
                    self.assertFalse(self.cast(slot, now, (5, 0)))
                self.assertEqual(self.hero.energy, 1000)
                self.assertEqual(self.kit.cooldowns, {A: 0, B: 0, C: 0})

    def test_production_vision_keeps_rank_three_lock_beyond_radius_then_hides(self):
        for _ in range(2):
            self.kit.upgrade_ability(C, 12)
        self.enemy.x = 12.25
        self.other.x = self.ally.x = 50
        vision = Vision()
        vision.update(9, self.heroes)
        self.assertEqual(vision.values[1517, 1], (1, 0, 0))
        self.lock(10)
        vision.update(10, self.heroes)
        self.assertEqual(vision.values[1517, 1], (1, 1, 0))
        self.step(14)
        vision.update(14, self.heroes)
        self.assertEqual(vision.values[1517, 1], (1, 0, 0))
        self.lock(15)
        self.hero.is_alive = False
        vision.update(15, self.heroes)
        self.assertEqual(vision.values[1517, 1], (1, 0, 0))
        self.step(15)
        self.assertEqual(self.hero.revealed_targets, {})

    def test_directional_speed_changes_with_new_order_and_expires(self):
        self.lock()
        self.hero.waypoints = [(0, 5)]
        self.kit.prepare_movement(10)
        self.assertAlmostEqual(self.hero.effective_speed(10, status_manager=self.sm), self.hero.speed + 2)
        self.hero.waypoints = [(-5, 0)]
        self.kit.prepare_movement(10.1)
        self.assertAlmostEqual(self.hero.effective_speed(10.1, status_manager=self.sm), self.hero.speed + .2)
        self.kit.prepare_movement(11.8)
        self.assertAlmostEqual(self.hero.effective_speed(11.8, status_manager=self.sm), self.hero.speed)


class TestSkyeBarrage(SkyeFixture):
    def test_structure_provider_participates_in_first_contact_and_native_objective_scaling(self):
        turret = Structure(3545, 'enemy-turret', 2, 3, 0, 10000, 10000, 1)
        turret.shield = 0
        self.kit.additional_targets = lambda: (turret,)
        self.cast(A)
        self.step(10.1)
        self.assertEqual(turret.hp, 10000 - 22)  # Half of the 44 raw A pulse.
        self.assertEqual(self.enemy.hp, 10000)

    def test_fixed_facing_follows_moving_origin_and_only_first_enemy_gets_pulses(self):
        self.lock()
        frames = self.cast(A)
        self.assertEqual([p[16] for op, p in frames if op == 1046], [0])
        self.assertEqual(self.hero.energy, 960)
        self.assertFalse(self.hero.channeling)
        self.assertTrue(self.hero.basic_attack_disabled)
        self.step(10.099)
        self.assertEqual(self.enemy.hp, 10000)
        self.step(10.1)
        self.assertAlmostEqual(self.enemy.hp, 10000 - 57.2)
        self.assertEqual((self.other.hp, self.ally.hp), (10000, 10000))
        self.hero.y = self.other.y = 2
        self.hero.facing = (0, 1)
        self.assertFalse(self.kit.interrupt_channel(10.15))  # MOVE does not end mobile A.
        self.step(10.2)
        self.assertEqual(self.hero.facing, (1, 0))
        self.assertAlmostEqual(self.other.hp, 10000 - 44)
        self.assertAlmostEqual(self.enemy.hp, 10000 - 57.2)
        self.assertTrue(self.sm.has_effect(self.other.eid, StatusType.SLOW, 10.2))

    def test_recast_native_cancel_costs_nothing_and_preserves_existing_cooldown(self):
        self.cast(A)
        self.hero.energy = 0
        self.assertTrue(self.kit.can_cast(A, 10.05, self.sm))
        self.assertEqual(self.kit.cancel_native_action(1, 10.05, self.sm),
            [(1045, ability_wire.build_target_cast(1500, None, 1))])
        self.assertEqual((self.hero.energy, self.kit.cooldowns[A]), (0, 16))
        self.assertFalse(self.hero.basic_attack_disabled)
        self.step(13)
        self.assertEqual(self.enemy.hp, 10000)
        self.assertEqual(self.kit.cancel_native_action(1, 13), [])
        self.assertIsNone(self.kit.cancel_native_action(3, 13))

    def test_duration_is_exactly_thirty_pulses_and_clears_basic_attack_gate(self):
        self.cast(A)
        self.step(13)
        self.assertAlmostEqual(self.enemy.hp, 10000 - 30 * 44)
        self.assertFalse(self.hero.basic_attack_disabled)
        self.step(14)
        self.assertAlmostEqual(self.enemy.hp, 10000 - 30 * 44)

    def test_short_hard_cc_recall_and_death_end_barrage_before_next_pulse(self):
        for cause in (StatusType.STUN, StatusType.SILENCE, StatusType.KNOCKBACK, 'recall', 'death'):
            with self.subTest(cause=cause):
                self.setUp()
                self.lock()
                self.cast(A)
                self.step(10.1)
                if cause == 'death':
                    self.hero.is_alive = False
                elif cause == 'recall':
                    self.hero.start_recall(10.15)
                else:
                    self.cc(cause)
                    self.sm.clean_expired(10.2)
                self.step(10.2)
                self.assertFalse(self.hero.basic_attack_disabled)
                self.assertAlmostEqual(self.enemy.hp, 10000 - 57.2)


class TestSkyeSuri(SkyeFixture):
    def test_dash_speed_four_delayed_missiles_and_per_victim_multi_hit_decay(self):
        self.lock()
        self.cast(B, point=(5, 0))
        self.assertEqual(self.hero.x, 0)
        self.step(10.1)
        self.assertAlmostEqual(self.hero.x, 1.8)
        self.assertEqual(self.enemy.hp, 10000)
        self.step(10.3)
        self.assertEqual((self.hero.x, self.hero.y), (5, 0))
        self.assertFalse(self.hero.channeling)
        self.assertFalse(self.hero.basic_attack_disabled)
        self.step(10.699)
        self.assertEqual(self.enemy.hp, 10000)
        self.step(10.7)
        self.assertEqual(self.enemy.hp, 9810)
        self.step(11)
        self.assertEqual(self.enemy.hp, 10000 - 190 * 1.6)
        self.assertEqual((self.other.hp, self.ally.hp), (10000, 10000))

    def test_missiles_sample_impact_positions_and_minions_use_wave_damage(self):
        minion = Minion(4611, 2, 0)
        minion.x, minion.y, minion.hp = 5, 0, 1000
        self.minions.append(minion)
        self.lock()
        self.cast(B, point=(5, 0))
        self.step(10.3)
        self.enemy.y = 4
        self.step(11)
        self.assertEqual(self.enemy.hp, 10000)
        self.assertEqual(minion.hp, 1000 - (90 + .3 * 100) * 1.6)

    def test_interrupt_stops_dash_and_future_shots_but_retains_one_launched(self):
        self.lock()
        self.cast(B, point=(14, 0))
        self.step(10.1)
        self.cc(StatusType.STUN)
        self.sm.clean_expired(10.2)
        self.step(10.2)
        self.assertAlmostEqual(self.hero.x, 1.8)
        self.assertFalse(self.hero.basic_attack_disabled)
        self.step(11.5)
        self.assertEqual(self.enemy.hp, 9810)

    def test_remaining_a_cooldown_reset_at_each_rank(self):
        for rank, remaining in enumerate((6, 4.5, 3, 1.5, 0), 1):
            with self.subTest(rank=rank):
                self.setUp()
                for _ in range(rank - 1):
                    self.kit.upgrade_ability(B, 12)
                self.kit.cooldowns[A] = 20
                self.lock()
                frames = self.cast(B, point=(5, 0))
                self.assertAlmostEqual(self.kit.cooldowns[A], 10 + remaining)
                timers = [cooldown_wire.parse_timer_tick(p) for op, p in frames if op == 1162]
                timer = next(t for t in timers if t.tag == self.kit.abilities[A].tag_inst)
                self.assertAlmostEqual(timer.remaining, remaining)

    def test_root_and_bad_point_reject_before_energy_and_barrage_mutation(self):
        self.lock()
        self.cast(A)
        self.cc(StatusType.ROOT, 10)
        self.assertFalse(self.cast(B, point=(5, 0)))
        self.sm.clean_expired(10.1)
        self.assertFalse(self.cast(B, 10.1, (30, 0)))
        self.assertEqual(self.hero.energy, 960)
        self.assertTrue(self.hero.basic_attack_disabled)
        self.assertIsNotNone(self.kit._barrage)


class TestSkyeMissileField(SkyeFixture):
    def test_native_publisher_receives_cast_snapshot_only_after_successful_lock_validation(self):
        calls = []
        self.kit.volley_presentation = lambda *args, **kwargs: calls.append((args, kwargs)) or [(1010, b'fixture')]
        self.assertEqual(self.cast(C, point=(5, 0)), [])
        self.assertEqual(calls, [])
        self.lock()
        frames = self.cast(C, point=(5, 0))
        self.assertIn((1010, b'fixture'), frames)
        self.assertEqual(calls, [((self.hero, (5, 0), None, 10), {'activation_at': 11.3, 'duration': 2})])

    def test_structure_lock_and_field_apply_objective_reduction(self):
        turret = Structure(3545, 'enemy-turret', 2, 5, 0, 10000, 10000, 1)
        turret.shield = 0
        self.kit.additional_targets = lambda: (turret,)
        self.lock(target=turret)
        self.assertTrue(self.cast(C, point=(5, 0)))
        self.step(11.3)
        self.assertEqual(turret.hp, 10000 - 12)  # 40% of a 30 raw C pulse.

    def test_line_publisher_uses_owned_clockwise_facing_from_target_to_selected_point(self):
        calls = []
        self.kit.volley_presentation = lambda *args, **kwargs: calls.append((args, kwargs)) or []
        self.lock()
        self.cast(C, point=(10, 0))
        self.assertEqual(calls[0][0], (self.hero, (10, 0), (0, -1), 10))

    def test_cluster_selection_excludes_the_exact_two_unit_boundary(self):
        # Native ELF 0xce33bc/0xce33c0 uses FCMP/CSET MI: strictly less.
        for distance, is_line in ((1.999, False), (2.0, True), (2.001, True)):
            with self.subTest(distance=distance):
                self.setUp()
                calls = []
                self.kit.volley_presentation = lambda *args, **kwargs: calls.append(args) or []
                self.lock()
                target_pos = (self.enemy.x, self.enemy.y)
                aim = (self.enemy.x + distance, self.enemy.y)
                self.assertTrue(self.cast(C, point=aim))
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][1], aim if is_line else target_pos)
                self.assertEqual(calls[0][2], (0, -1) if is_line else None)

    def test_cluster_waits_then_stuns_slows_and_stops_after_rank_lifetime(self):
        self.lock()
        frames = self.cast(C, point=(5, 0))
        self.assertEqual([p[16] for op, p in frames if op == 1046], [4])
        self.assertEqual((self.hero.energy, self.kit.cooldowns[C]), (930, 40))
        self.step(11.299)
        self.assertEqual(self.enemy.hp, 10000)
        self.step(11.3)
        self.assertEqual(self.enemy.hp, 9970)
        self.assertTrue(self.sm.has_effect(1517, StatusType.STUN, 11.3))
        self.assertTrue(self.sm.has_effect(1517, StatusType.SLOW, 11.3))
        self.assertEqual(self.other.hp, 10000)
        self.step(13.3)
        self.assertAlmostEqual(self.enemy.hp, 9400)
        self.assertEqual(self.kit._missile_fields, [])
        self.step(14)
        self.assertAlmostEqual(self.enemy.hp, 9400)

    def test_nearby_c_aim_snaps_cluster_to_marked_target_at_cast(self):
        calls = []
        self.kit.volley_presentation = lambda *args, **kwargs: calls.append((args, kwargs)) or []
        self.lock()
        self.cast(C, point=(self.enemy.x + 1.2, self.enemy.y - .9))
        center = (self.enemy.x, self.enemy.y)
        self.assertEqual(calls[0][0][1:3], (center, None))
        self.enemy.x += 5
        self.step(11.3)
        self.assertEqual(self.kit._missile_fields[0].center, center)

    def test_line_is_perpendicular_to_target_to_aim_and_rechecks_each_tick(self):
        self.lock()
        self.cast(C, point=(10, 0))
        self.enemy.x, self.enemy.y = 10, 4
        self.other.x, self.other.y = 14, 0
        self.step(11.3)
        self.assertEqual((self.enemy.hp, self.other.hp), (9970, 10000))
        self.enemy.x = 14
        self.other.x, self.other.y = 10, -4
        self.step(11.4)
        self.assertEqual((self.enemy.hp, self.other.hp), (9970, 9970))

    def test_launched_field_keeps_cast_rank_cp_and_aim_after_lock_loss_and_death(self):
        self.lock()
        self.cast(C, point=(5, 0))
        self.kit.upgrade_ability(C, 12)
        self.hero.crystal_power = 1000
        self.hero.is_alive = False
        self.step(13.3)
        self.assertAlmostEqual(self.enemy.hp, 9400)
        self.assertEqual(self.kit._missile_fields, [])


if __name__ == '__main__':
    unittest.main()

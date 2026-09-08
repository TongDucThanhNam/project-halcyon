"""Celeste's real crystal basic profile through purchases, release and item procs."""
import math
import struct
import unittest

from server import economy, roster, wave, wire
from server.status_effects import StatusEffect, StatusType
from server.test.test_ability_cc_presentation import session


class CelesteItemSessionTests(unittest.TestCase):
    def world_with_items(self):
        world, frames, _, owner, _ = session(hero_id=285, target_id=399, slot=0)
        source, target = world.hero_sims[1500], world.hero_sims[1517]
        self.assertEqual((source.level, source.attack_damage, source.crystal_power), (1, 0, 0))
        player = world.economy.get_or_create(source.eid)
        player.gold = 10000
        source.teleport(source.spawn_x, source.spawn_y)
        for key in ('aftershock', 'alternating_current', 'spellfire', 'weapon_blade'):
            item = economy.ITEMS_BY_KEY[key]
            world._apply_event(wire.OP.SHOP_BUY, roster.build_shop_buy(source.eid, item.id), owner)
            self.assertIn(item, player.inventory)
        self.assertEqual((source.crystal_power, source.attack_damage), (155, 10))
        self.assertEqual(world._basic_attack_damage_profile(source, target), (201.25, 'crystal'))

        source.teleport(0, 5)
        target.teleport(4, 5)
        target.hp = target.max_hp = 10000
        # Distinct defenses make accidentally retaining weapon mitigation visible.
        target.armor, target.shield = 300, 100
        frames.clear()
        return world, frames, owner, source, target

    def arm_and_attack(self, world, owner, source, target):
        energy = source.energy
        # A is aimed away from the victim: it arms Aftershock without supplying
        # another source of direct damage or refreshing Spellfire on the victim.
        world._apply_event(wire.OP.GROUND_CAST, struct.pack('>fffBB', -5, 0, 5, 0, 0), owner)
        self.assertEqual(energy - source.energy, 30)
        world._apply_event(wire.OP.TARGET_ENTITY, roster.build_target_entity(target.eid), owner)

    def test_crystal_basics_apply_each_item_proc_once_and_spellfire_does_not_recurse(self):
        world, frames, owner, source, target = self.world_with_items()
        self.arm_and_attack(world, owner, source, target)

        events = []
        primary_times = []

        def tick():
            begin = len(frames)
            world.advance_simulation()
            for opcode, payload in frames[begin:]:
                if opcode != wire.OP.COMBAT_DELTA:
                    continue
                victim, attacker, delta = struct.unpack_from('>IIf', payload)
                if (victim, attacker) != (target.eid, source.eid):
                    continue
                basic = payload[12:] == roster.COMBAT_DELTA_HERO_TAIL
                events.append((world.sim_time, delta, basic))
                if basic:
                    primary_times.append(world.sim_time)

        while len(primary_times) < 2 and world.sim_time < 5:
            tick()
        self.assertEqual(len(primary_times), 2, events)
        # Stop the real attack order after the second impact, then observe the
        # complete remaining DoT lifetime without another cast or basic attack.
        world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-2, 5), owner)
        while world.sim_time < primary_times[-1] + 4:
            tick()

        first, second = primary_times
        self.assertEqual([delta for _, delta, basic in events if basic], [-100.625, -100.625])
        self.assertEqual([(at, delta) for at, delta, basic in events if not basic and delta == -750],
                         [(first, -750)])
        self.assertEqual([(at, delta) for at, delta, basic in events if not basic and delta == -54.25],
                         [(second, -54.25)])
        # Spellfire retains its initial half-second cadence when the second
        # crystal basic refreshes its three-second lifetime. Its own ticks may
        # neither create more basic procs nor extend their own expiry.
        dots = [(at, delta) for at, delta, basic in events
                if not basic and delta not in (-750, -54.25)]
        count = math.floor((second + 3 - first) / .5 + 1e-9)
        self.assertEqual(len(dots), count, events)
        self.assertTrue(all(delta == -6.9375 for _, delta in dots), dots)
        for index, (at, _) in enumerate(dots, 1):
            self.assertAlmostEqual(at, first + index * .5)
        self.assertEqual(len(primary_times), 2)
        self.assertAlmostEqual(10000 - target.hp, 100.625 * 2 + 750 + 54.25 + 6.9375 * count)
        self.assertNotIn(source.eid, world.items._aftershock_ready)
        self.assertEqual(world.items._alternating_hits[source.eid], 2)
        self.assertFalse(world.items._periodic)

    def test_fully_absorbed_landed_basic_consumes_aftershock_and_counts_once_without_hp_damage(self):
        world, frames, owner, source, target = self.world_with_items()
        barrier = StatusEffect('test-barrier', StatusType.BARRIER, target.eid,
                               target.eid, 10, 0, 10, magnitude=1000)
        world.status_manager.apply_effect(barrier)
        self.arm_and_attack(world, owner, source, target)
        self.assertIn(source.eid, world.items._aftershock_ready)
        while source.eid in world.items._aftershock_ready and world.sim_time < 3:
            world.advance_simulation()
        self.assertNotIn(source.eid, world.items._aftershock_ready)
        world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-2, 5), owner)
        # The ordinary crystal hit and its one Aftershock proc debit the same
        # barrier after shield mitigation. Neither reaches the actual HP pool.
        self.assertEqual(barrier.magnitude, 1000 - 100.625 - 750)
        self.assertEqual(target.hp, 10000)
        self.assertEqual(world.items._alternating_hits[source.eid], 1)
        self.assertAlmostEqual(world.items._aftershock_cooldown[source.eid], world.sim_time + 1)
        self.assertFalse(any(op == wire.OP.COMBAT_DELTA
                             and struct.unpack_from('>II', payload) == (target.eid, source.eid)
                             for op, payload in frames))
        self.assertFalse(any(op == wire.OP.ENTITY_STAT
                             and struct.unpack_from('>I', payload)[0] == target.eid
                             and payload[8] == roster.STAT_HEALTH
                             for op, payload in frames))

    def test_lethal_basic_spends_aftershock_and_next_target_receives_second_hit_ac(self):
        world, frames, owner, source, target = self.world_with_items()
        target.hp = 1
        self.arm_and_attack(world, owner, source, target)
        while target.is_alive and world.sim_time < 3:
            world.advance_simulation()
        self.assertFalse(target.is_alive)
        self.assertNotIn(source.eid, world.items._aftershock_ready)
        self.assertEqual(world.items._alternating_hits[source.eid], 1)
        self.assertAlmostEqual(world.items._aftershock_cooldown[source.eid], world.sim_time + 1)
        lethal = [payload for op, payload in frames if op == wire.OP.COMBAT_DELTA
                  and struct.unpack_from('>II', payload) == (target.eid, source.eid)]
        self.assertEqual(len(lethal), 1)
        self.assertEqual(struct.unpack_from('>f', lethal[0], 8)[0], -1)
        self.assertEqual(lethal[0][12:], roster.COMBAT_DELTA_HERO_TAIL)

        next_target = wave.Minion(6000, 2, world.sim_time)
        next_target.x, next_target.y = 4, 5
        next_target.path, next_target.seg = [(4, 5)], 1
        next_target.hp = next_target.max_hp = 10000
        world.wave_director.minions.append(next_target)
        world.wave_director.combat = False
        world._emit_frames(world.wave_director.get_spawn_frames(world.sim_time, actor_slots=world.actor_slots))
        frames.clear()
        world._apply_event(wire.OP.TARGET_ENTITY, roster.build_target_entity(next_target.eid), owner)
        while world.items._alternating_hits[source.eid] < 2 and world.sim_time < 5:
            world.advance_simulation()
        self.assertEqual(world.items._alternating_hits[source.eid], 2)
        world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-2, 5), owner)
        hits = [payload for op, payload in frames if op == wire.OP.COMBAT_DELTA
                and struct.unpack_from('>II', payload) == (next_target.eid, source.eid)]
        # The first kill's real bounty levels Celeste to two before this shot.
        self.assertEqual(source.level, 2)
        primary = 75 + 50 / 11 + .75 * 155 + 10
        primary_wire = struct.unpack('>f', struct.pack('>f', -primary))[0]
        self.assertEqual([struct.unpack_from('>f', payload, 8)[0] for payload in hits], [primary_wire, -108.5])
        self.assertEqual(hits[0][12:], roster.COMBAT_DELTA_HERO_TAIL)
        self.assertEqual(hits[1][12:], roster.COMBAT_DELTA_TAIL)
        self.assertAlmostEqual(next_target.hp, 10000 - primary - 108.5)


if __name__ == '__main__':
    unittest.main()

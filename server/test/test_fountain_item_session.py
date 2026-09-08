"""Fountain's native input publishes capped healing for actual lane actors."""
import struct
import unittest

from server import economy, item_input, roster, wave, wire
from server.status_effects import StatusEffect, StatusType
from server.test.test_ability_cc_presentation import session


class FountainItemSessionTests(unittest.TestCase):
    def test_three_pulses_publish_only_actual_living_nearby_ally_healing(self):
        world, frames, _, owner, _ = session()
        source = world.hero_sims[1500]
        player = world.economy.get_or_create(source.eid)
        player.gold = 10000
        source.teleport(source.spawn_x, source.spawn_y)
        item = economy.ITEMS_BY_KEY['fountain_of_renewal']
        world._apply_event(wire.OP.SHOP_BUY, roster.build_shop_buy(source.eid, item.id), owner)
        slot = player.inventory.index(item)
        instance = player.inventory_instances[slot]
        source.teleport(0, 5)
        world.hero_sims[1517].teleport(50, 50)
        world.wave_director.combat = False

        # Ordinary, wounded, almost-full, dead, enemy and distant lane actors.
        minions = {}
        for eid, side, x, hp, alive in ((6000, 1, 2, 50, True), (6001, 1, 3, 50, True),
                (6002, 1, 4, 99, True), (6003, 1, 5, 0, False),
                (6004, 2, 6, 50, True), (6005, 1, 30, 50, True)):
            minion = wave.Minion(eid, side, 0)
            minion.x, minion.y = x, 5
            minion.path, minion.seg = [(x, 5)], 1
            minion.hp, minion.max_hp, minion.alive = hp, 100, alive
            world.wave_director.minions.append(minion)
            minions[eid] = minion
        world._emit_frames(world.wave_director.get_spawn_frames(0, actor_slots=world.actor_slots))
        world.status_manager.apply_effect(StatusEffect('wound', StatusType.WOUND,
            1517, 6001, 2.5, 0, 2.5, magnitude=.33))
        frames.clear()
        world._apply_event(wire.OP.ITEM_USE, item_input.build_item_use(instance), owner)
        self.assertEqual(player.item_cooldowns['fountain'], item.cooldown)

        heals = {eid: [] for eid in minions}
        while world.sim_time < 4:
            begin = len(frames)
            world.advance_simulation()
            for op, payload in frames[begin:]:
                if op != wire.OP.ENTITY_STAT:
                    continue
                eid, delta = struct.unpack_from('>If', payload)
                if eid in heals and payload[8] == roster.STAT_HEALTH:
                    self.assertEqual(len(payload), 14)
                    self.assertEqual(payload[9:], bytes.fromhex('0001000000'))
                    heals[eid].append((world.sim_time, delta))

        for eid in (6000, 6001):
            self.assertEqual([at for at, _ in heals[eid]], [1, 2, 3])
            expected_hp = 50
            for at, delta in heals[eid]:
                multiplier = .67 if eid == 6001 and at < 2.5 else 1
                expected_delta = (2 + .01 * (100 - expected_hp)) * multiplier
                self.assertAlmostEqual(delta, expected_delta, places=6)
                expected_hp += expected_delta
            self.assertAlmostEqual(minions[eid].hp, expected_hp)
            self.assertAlmostEqual(sum(delta for _, delta in heals[eid]), expected_hp - 50, places=6)
        self.assertEqual(heals[6002], [(1, 1)])
        self.assertEqual(minions[6002].hp, 100)
        for eid, hp in ((6003, 0), (6004, 50), (6005, 50)):
            self.assertEqual(heals[eid], [])
            self.assertEqual(minions[eid].hp, hp)
        self.assertFalse(minions[6003].alive)
        self.assertFalse(any(op == wire.OP.COMBAT_DELTA for op, _ in frames))
        self.assertFalse(world.items._periodic)


if __name__ == '__main__':
    unittest.main()

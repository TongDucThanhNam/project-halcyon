"""Stormguard enters the production damage pipeline before resistance/barriers."""
import struct
import unittest

from server import abilities, ability_wire, jungle, match_server, roster, wave, wire
from server.navigation import NavMesh
from server.status_effects import StatusEffect, StatusType


def session():
    mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                   [(0, 1, 2), (0, 2, 3)])
    players = roster.default_solo_bots('stormguard-test', 'stormguard-test')
    players = [players[0], players[3]]
    players[0].hero_id, players[1].hero_id = 242, 243
    for player in players:
        player.is_bot = False
    frames = []
    world = match_server.SnapshotStream(None, players, 'stormguard-test',
        lambda op, payload: frames.append((op, payload)), log=lambda _: None,
        navigation_mesh=mesh)
    world._finalize()
    world.hero_sims[1500].teleport(0, 0)
    world.hero_sims[1517].teleport(5, 0)
    world.jungle = jungle.JungleManager(open_time=1000000)
    world.wave_director = wave.Director(1000000)
    world.structures.structures.clear()
    world.phase = world.WORLD
    kit = world.hero_kits[1500]
    if not world.economy.upgrade_ability(1500, int(abilities.AbilitySlot.B), kit):
        raise AssertionError('test fixture could not learn Stormguard')
    action = ability_wire.hero_action_variant(242, 'B')
    if action != 2:
        raise AssertionError('native Catherine B action must be 2')
    world._apply_event(wire.OP.TARGETLESS_CAST, struct.pack('>IBB', 0xffffffff, action, 0))
    if kit._stormguard_until <= world.sim_time:
        raise AssertionError('native B input did not start Stormguard')
    frames.clear()
    return world, frames


class StormguardSessionTests(unittest.TestCase):
    def test_damage_is_capped_before_armor_and_hp_changes_once(self):
        world, _ = session()
        defender, attacker = world.hero_sims[1500], world.hero_sims[1517]
        defender.armor = 100
        before = defender.hp
        frames = world._deal_damage(attacker, defender, 100, 'weapon', 0.01)
        self.assertAlmostEqual(before - defender.hp, 808 * 0.075 / 2)
        hits = [p for op, p in frames if op == 1054]
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(struct.unpack_from('>f', hits[0], 8)[0], -30.3, places=4)
        self.assertFalse(any(op == 1053 and p[8] == 0 for op, p in frames))
        self.assertEqual(len([op for op, _ in frames if op == 1045]), 1)
        self.assertLess(next(i for i, (op, _) in enumerate(frames) if op == 1045),
                        next(i for i, (op, _) in enumerate(frames) if op == 1054))

    def test_queued_reflection_uses_world_kill_credit_once_on_next_tick(self):
        world, frames = session()
        defender, attacker = world.hero_sims[1500], world.hero_sims[1517]
        attacker.hp = 1
        gold = world.economy.get_or_create(defender.eid).gold
        world._deal_damage(attacker, defender, 100, 'weapon', 0.01)
        self.assertTrue(attacker.is_alive)
        world.advance_simulation()
        self.assertFalse(attacker.is_alive)
        self.assertGreater(world.economy.get_or_create(defender.eid).gold, gold)
        hits = [p for op, p in frames if op == 1054
                and struct.unpack_from('>II', p) == (attacker.eid, defender.eid)]
        self.assertEqual(len(hits), 1)
        bounty_gold = world.economy.get_or_create(defender.eid).gold
        for _ in range(3):
            world.advance_simulation()
        hits = [p for op, p in frames if op == 1054
                and struct.unpack_from('>II', p) == (attacker.eid, defender.eid)]
        self.assertEqual(len(hits), 1)
        self.assertLess(world.economy.get_or_create(defender.eid).gold - bounty_gold, 1)

    def test_fully_absorbed_hit_retains_reflection_action_and_queued_effect(self):
        world, _ = session()
        defender, attacker = world.hero_sims[1500], world.hero_sims[1517]
        world.status_manager.apply_effect(StatusEffect('absorb', StatusType.BARRIER,
            defender.eid, defender.eid, 10, 0, 10, magnitude=1000))
        before = defender.hp
        frames = world._deal_damage(attacker, defender, 100, 'weapon', 0.01)
        self.assertEqual(defender.hp, before)
        self.assertEqual([op for op, _ in frames], [wire.OP.TARGET_ACQUIRE])
        self.assertEqual(struct.unpack_from('>IIB', frames[0][1]), (1500, 1500, 4))
        before_attacker = attacker.hp
        world.advance_simulation()
        self.assertLess(attacker.hp, before_attacker)


if __name__ == '__main__':
    unittest.main()

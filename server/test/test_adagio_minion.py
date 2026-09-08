"""Regression for the real client Gift of Fire crash on wave.Minion slots."""
import struct
import unittest

from server import jungle, match_server, roster, wave, wire
from server.navigation import NavMesh


class TestAdagioProductionMinion(unittest.TestCase):
    def test_self_cast_with_lane_minion_in_radius_keeps_world_ticking(self):
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                       [(0, 1, 2), (0, 2, 3)])
        players = roster.default_solo_bots("adagio-regression", "adagio-regression")[:1]
        players[0].hero_id = 244
        frames = []
        world = match_server.SnapshotStream(None, players, "adagio-regression",
            lambda opcode, payload: frames.append((opcode, payload)),
            log=lambda _: None, navigation_mesh=mesh)
        world._finalize()
        hero = world.hero_sim
        hero.teleport(0, 0)
        world.structures.structures.clear()
        world.jungle = jungle.JungleManager(open_time=1000000)
        world.wave_director = wave.Director(1000000)
        target = wave.Minion(4610, 2, 0)
        target.x, target.y, target.path = 2.0, 0.0, []
        world.wave_director.minions.append(target)
        kit = world.hero_kits[hero.eid]
        self.assertTrue(world.economy.upgrade_ability(hero.eid, 0, kit))
        before_hp, before_energy = target.hp, hero.energy
        # This is the 1041 self-targeted A intent sent by the real client.
        world._apply_event(wire.OP.TARGETLESS_CAST, struct.pack(">IBB", 0xFFFFFFFF, 0, 0))
        self.assertEqual(before_energy - hero.energy, 120.0)
        self.assertIn(target.eid, kit._arcane_fire)
        self.assertFalse(hasattr(target, "arcane_fire"))
        for _ in range(10):
            world.advance_simulation()
        self.assertEqual(world.sim_tick, 10)
        self.assertLess(target.hp, before_hp)
        self.assertTrue(any(opcode == wire.OP.COMBAT_DELTA
            and struct.unpack_from(">II", payload) == (target.eid, hero.eid)
            for opcode, payload in frames))


if __name__ == "__main__":
    unittest.main()

"""Opt-in roster modifier through production lock/finalize, not a second sim."""
import os
import struct
import unittest
from unittest.mock import patch

from server import abilities, match_server, roster, wire
from server.navigation import NavMesh


class SameHeroTests(unittest.TestCase):
    def make_match(self, enabled):
        players = roster.default_solo_bots('same-hero-owner', 'same-hero-match')
        players[0].hero_id, players[0].selection_hash = 265, 0x12345678
        players[3].is_bot = False
        players[3].hero_id, players[3].selection_hash = 242, 0x87654321
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                       [(0, 1, 2), (0, 2, 3)])
        owner, guest = object(), object()
        frames, guest_frames = [], []
        with patch.dict(os.environ, {'HALCYON_SAME_HERO': '1' if enabled else '0'}):
            world = match_server.SnapshotStream(owner, players, 'same-hero-match',
                lambda op, body: frames.append((op, body)), log=lambda _: None,
                navigation_mesh=mesh)
        world.clients[guest] = (players[3], lambda op, body: guest_frames.append((op, body)))
        return world, frames, guest_frames

    def test_six_mirrors_keep_identity_and_independent_production_kits(self):
        world, frames, guest_frames = self.make_match(True)
        identities = [(p.eid, p.team, p.slot, p.uuid, p.is_bot) for p in world.players]
        world._begin_lock()
        self.assertEqual({(p.hero_id, p.selection_hash) for p in world.players},
                         {(265, 0x12345678)})
        self.assertEqual(identities, [(p.eid, p.team, p.slot, p.uuid, p.is_bot) for p in world.players])
        self.assertTrue(any(op == wire.OP.JOIN_1118 and struct.unpack_from('>II', body) ==
                            (265, 0x12345678) for op, body in guest_frames))
        snapshots = [body for op, body in frames if op == wire.OP.SNAPSHOT_JOIN]
        for player in world.players:
            offset = roster.SNAPSHOT_RECORD_BASE + player.slot * roster.SNAPSHOT_RECORD_STRIDE
            self.assertEqual(struct.unpack_from('>H', snapshots[-1], offset + 9)[0], 265)
        world._finalize()
        self.assertTrue(all(isinstance(kit, abilities.SkyeKit) for kit in world.hero_kits.values()))
        self.assertEqual(len({id(kit) for kit in world.hero_kits.values()}), 6)
        first, second = world.hero_sims[1500], world.hero_sims[1515]
        self.assertEqual(first.max_hp, second.max_hp)
        first.hp -= 100
        self.assertNotEqual(first.hp, second.hp)
        self.assertIsNot(world.economy.get_or_create(1500), world.economy.get_or_create(1515))

    def test_classic_does_not_override_other_humans_or_default_bots(self):
        world, _, guest_frames = self.make_match(False)
        world._begin_lock()
        self.assertEqual(world.players[3].hero_id, 242)
        self.assertEqual(world.players[1].hero_id, roster.BOT_HERO_CHOICES[0][0])
        self.assertFalse(any(op == wire.OP.JOIN_1118 for op, _ in guest_frames))

    def test_finalize_includes_host_cosmetic_change_without_shared_state(self):
        world, _, _ = self.make_match(True)
        world._begin_lock()
        world.players[0].selection_hash = 0xABCDEF12
        world._finalize()
        self.assertEqual({p.selection_hash for p in world.players}, {0xABCDEF12})
        self.assertEqual({sim.hero_id for sim in world.hero_sims.values()}, {265})


if __name__ == '__main__':
    unittest.main()

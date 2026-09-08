"""Reconnect progression through real SnapshotStream client attachments.

The small receiver below applies the independently measured 1011/1053/1076/
1082 progression contracts, so assertions cover the final client state rather
than only the values initially seeded into the hero block.
"""
from dataclasses import dataclass, field
import struct
import unittest

from server import economy, level_wire, match_server, roster, wave
from server.navigation import NavMesh
from server.test.test_reconnect_state import catalog


@dataclass
class NativeProgression:
    eid: int
    level: int = 1
    points: int = 1
    xp: float = 0.0
    requirement: float = 68.0
    ranks: dict = field(default_factory=dict)
    xp_history: list = field(default_factory=list)
    point_history: list = field(default_factory=list)

    def receive(self, frames):
        for opcode, payload in frames:
            if opcode == 1011 and struct.unpack_from(">I", payload, 8)[0] == self.eid:
                self.level = int(struct.unpack_from(">f", payload, 294)[0])
                self.points = int(struct.unpack_from(">f", payload, 314)[0])
                self.xp, self.requirement = struct.unpack_from(">ff", payload, 318)
                self.ranks.clear()
            elif len(payload) < 4 or struct.unpack_from(">I", payload)[0] != self.eid:
                continue
            elif opcode == 1053 and payload[8] == 8:
                self.xp += struct.unpack_from(">f", payload, 4)[0]
            elif opcode == 1076:
                level_wire.parse_level_increment(payload)
                self.xp -= self.requirement
                self.level += 1
                self.points += 1
            elif opcode == 1052 and payload[12] == 39:
                _, self.requirement = level_wire.parse_xp_requirement(payload)
            elif opcode == 1082:
                slot = struct.unpack_from(">I", payload, 4)[0]
                self.ranks[slot] = self.ranks.get(slot, 0) + 1
                self.points -= 1
            self.xp_history.append(self.xp)
            self.point_history.append(self.points)


class TestLevelReconnect(unittest.TestCase):
    def make_world(self):
        players = roster.default_solo_bots("returning-level-player", "level-reconnect-match")
        players[0].hero_id = 244  # native Adagio stats and a supported ability kit
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                       [(0, 1, 2), (0, 2, 3)])
        world = match_server.SnapshotStream(None, players, "level-reconnect-match", None,
                                           log=lambda _: None, navigation_mesh=mesh)
        native, jungle = catalog()
        world.structures.spawn_catalog, world.jungle.spawn_catalog = native, jungle
        world.tape_frames, world.tape_done = [], True
        world.enable_bots = False
        world.emit_waves = True
        world._finalize()
        world._dump_world()
        world._enter_world()
        world.wave_director.t0 = 1000000.0
        world.wave_director._state_catalog = native
        returning_conn, returning_frames = self.join(world, players[0].uuid)
        observer_conn, observer_frames = self.join(world, "continuous-level-observer")
        self.assertEqual(len(world.clients), 2)
        self.assertNotEqual(world.clients[returning_conn][0].eid, world.clients[observer_conn][0].eid)
        return world, returning_conn, returning_frames, observer_conn, observer_frames

    @staticmethod
    def join(world, uuid):
        conn, frames = object(), []
        world.add_client(conn, uuid, lambda opcode, payload: frames.append((opcode, payload)))
        return conn, frames

    @staticmethod
    def hero_block(frames, eid):
        blocks = [payload for opcode, payload in frames
                  if opcode == 1011 and struct.unpack_from(">I", payload, 8)[0] == eid]
        if len(blocks) != 1:
            raise AssertionError(f"expected one hero creation, got {len(blocks)}")
        return blocks[0]

    @staticmethod
    def xp_deltas(frames, eid):
        return [struct.unpack_from(">f", payload, 4)[0] for opcode, payload in frames
                if opcode == 1053 and payload[8] == 8
                and struct.unpack_from(">I", payload)[0] == eid]

    def assert_matches(self, received, player):
        self.assertEqual((received.level, received.points), (player.level, player.ability_points))
        self.assertAlmostEqual(received.xp, level_wire.within_level_xp(player.xp, player.level), places=4)
        self.assertEqual(received.requirement, level_wire.next_level_requirement(player.level))
        self.assertGreaterEqual(min(received.xp_history), -0.0001)
        self.assertGreaterEqual(min(received.point_history), 0)

    def test_fresh_bootstrap_resets_each_donor_progression_field(self):
        world, _, returning, _, observer = self.make_world()
        for frames in (returning, observer):
            for player in world.players:
                block = self.hero_block(frames, player.eid)
                self.assertEqual(tuple(struct.unpack_from(">f", block, offset)[0]
                                       for offset in (294, 314, 318, 322)), (1, 1, 0, 68))
            self.assertFalse(any(opcode == 1076 for opcode, _ in frames))
            self.assertFalse(any(opcode == 1053 and payload[8] == 8 for opcode, payload in frames))

    def test_two_clients_bounty_rollover_credits_only_pending_xp_then_later_flush(self):
        world, old_conn, _, observer_conn, observer_frames = self.make_world()
        hero = world.hero_sim
        player = world.economy.get_or_create(hero.eid)
        observer = NativeProgression(hero.eid)
        observer.receive(observer_frames)
        observer_frames.clear()
        # Advance the economy to an exact native boundary setup, then use real
        # fixed ticks to leave half a second of passive XP pending on the wire.
        world._emit_frames(world.economy.step(67.0, 67.0, world.hero_sims))
        world.sim_time, world.sim_tick = 67.0, 1340
        observer.receive(observer_frames)
        observer_frames.clear()
        world.remove_client(old_conn)
        for _ in range(10):
            world.advance_simulation()
        self.assertAlmostEqual(world.economy._pending_xp[hero.eid], 0.5)
        observer.receive(observer_frames)
        observer_frames.clear()
        new_conn, returning_frames = self.join(world, world.players[0].uuid)
        self.assertIn(observer_conn, world.clients)
        self.assertNotIn(old_conn, world.clients)
        self.assertEqual(len(world.clients), 2)
        returning = NativeProgression(hero.eid)
        returning.receive(returning_frames)
        self.assert_matches(returning, player)
        self.assertEqual(self.xp_deltas(returning_frames, hero.eid), [])
        self.assertFalse(any(opcode == 1076 for opcode, _ in returning_frames))
        self.assertAlmostEqual(world._resource_catchup[new_conn][hero.eid, 8], 0.5)
        returning_frames.clear()

        minion = wave.Minion(4610, 2, 0)
        minion.hp = 1.0
        world.wave_director.minions.append(minion)
        world.actor_slots.allocate(minion.eid)
        # Damage/death frames precede the pending-XP frame in the merged list.
        # Credit must follow its tuple metadata, not its position or opcode.
        merged = world._deal_damage(hero, minion, 1000.0, "true", world.sim_time)
        pending = [frame for frame in merged if getattr(frame, "resource_credit", False)]
        self.assertEqual(len(pending), 1)
        self.assertGreater(merged.index(pending[0]), 0)
        world._emit_frames(merged)
        self.assertAlmostEqual(self.xp_deltas(observer_frames, hero.eid)[0], 0.5)
        self.assertEqual(self.xp_deltas(observer_frames, hero.eid)[1:], [50.0])
        self.assertAlmostEqual(self.xp_deltas(returning_frames, hero.eid)[0], 0.0)
        self.assertEqual(self.xp_deltas(returning_frames, hero.eid)[1:], [50.0])
        for received, frames in ((observer, observer_frames), (returning, returning_frames)):
            received.receive(frames)
            self.assert_matches(received, player)
            self.assertEqual(sum(opcode == 1076 and struct.unpack_from(">I", payload)[0] == hero.eid
                                 for opcode, payload in frames), 1)
            frames.clear()
        self.assertNotIn((hero.eid, 8), world._resource_catchup[new_conn])
        for _ in range(10):
            world.advance_simulation()
        for received, frames in ((observer, observer_frames), (returning, returning_frames)):
            self.assertEqual(len(self.xp_deltas(frames, hero.eid)), 1)
            self.assertAlmostEqual(self.xp_deltas(frames, hero.eid)[0], 0.5)
            received.receive(frames)
            self.assert_matches(received, player)

    def test_reconnect_item_modifiers_reconstruct_maximum_resources_once(self):
        world, old_conn, _, _, observer_frames = self.make_world()
        hero = world.hero_sim
        player = world.economy.get_or_create(hero.eid)
        player.add_xp(500.0)
        player.gold = 10000.0
        for key in ("halcyon_chargers", "crucible"):
            self.assertIsNotNone(player.buy_item(economy.ITEMS_BY_KEY[key].id))
        player.apply_to_hero(hero)
        hero.hp = hero.max_hp - 50.0
        hero.energy = hero.max_energy - 25.0
        authoritative_before = (hero.hp, hero.max_hp, hero.energy, hero.max_energy,
                                player.level, player.ability_points, player.xp)
        equipment = player.get_total_item_stats()
        self.assertEqual((equipment["max_hp"], equipment["max_energy"]), (700.0, 250.0))
        world.remove_client(old_conn)
        observer_frames.clear()
        _, frames = self.join(world, world.players[0].uuid)
        block = self.hero_block(frames, hero.eid)
        self.assertAlmostEqual(struct.unpack_from(">f", block, 46)[0], hero.max_hp - 700, places=3)
        self.assertAlmostEqual(struct.unpack_from(">f", block, 126)[0], hero.max_energy - 250, places=3)
        self.assertAlmostEqual(struct.unpack_from(">f", block, 42)[0], hero.hp, places=3)
        self.assertAlmostEqual(struct.unpack_from(">f", block, 122)[0], hero.energy, places=3)
        modifiers = [(payload[12], struct.unpack_from(">f", payload, 8)[0])
                     for opcode, payload in frames if opcode == 1052
                     and struct.unpack_from(">I", payload)[0] == hero.eid and payload[12] in (0, 2)]
        self.assertCountEqual(modifiers, [(0, 700.0), (2, 250.0)])
        self.assertAlmostEqual(struct.unpack_from(">f", block, 46)[0] + sum(v for a, v in modifiers if a == 0),
                               hero.max_hp, places=3)
        self.assertAlmostEqual(struct.unpack_from(">f", block, 126)[0] + sum(v for a, v in modifiers if a == 2),
                               hero.max_energy, places=3)
        self.assertFalse(any(opcode == 1076 or (opcode == 1053 and payload[8] in (0, 2, 8))
                             for opcode, payload in frames))
        self.assertEqual(observer_frames, [])
        self.assertEqual((hero.hp, hero.max_hp, hero.energy, hero.max_energy,
                          player.level, player.ability_points, player.xp), authoritative_before)
        received = NativeProgression(hero.eid)
        received.receive(frames)
        self.assert_matches(received, player)

    def test_reconnect_rank_replay_preserves_unspent_points_after_every_action(self):
        world, old_conn, _, _, _ = self.make_world()
        hero = world.hero_sim
        player = world.economy.get_or_create(hero.eid)
        player.add_xp(500.0)
        player.apply_to_hero(hero)
        kit = world.hero_kits[hero.eid]
        for slot in (0, 0, 0, 1, 1, 2):
            self.assertTrue(world.economy.upgrade_ability(hero.eid, slot, kit))
        self.assertEqual(player.ability_points, 0)
        world.remove_client(old_conn)
        _, frames = self.join(world, world.players[0].uuid)
        received = NativeProgression(hero.eid)
        received.receive(frames)
        self.assertEqual(received.ranks, {int(slot): rank for slot, rank in kit.ranks.items() if rank})
        self.assert_matches(received, player)
        self.assertFalse(any(opcode == 1076 for opcode, _ in frames))
        self.assertEqual(self.xp_deltas(frames, hero.eid), [])


if __name__ == "__main__":
    unittest.main()

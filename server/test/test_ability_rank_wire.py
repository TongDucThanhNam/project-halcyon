"""UI upgrade slots and native rank-action ordinals are different domains."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from server.paths import pc_data_dir, research_dir, stack_dir
from server import abilities, ability_wire, cooldown_wire, decode, hero_balance, hero_movement
from server import match_server, roster, sandbox_qa
from server.navigation import NavMesh
from Tools.Teardown.inspect_ability_actions import read_actions


CATHERINE_REPLAY = research_dir("vg_phaseB") / "vgr_live"
CATHERINE_PREFIX = "ea4c7fda-4b61-481d-abb7-1c757d24ae58-1574e27a-e851-492b-8d91-94fc4bd66985"
DATA = pc_data_dir()
NAMES = research_dir("vg_max") / "inst_names.tsv"


class TestNativeAbilityRanks(unittest.TestCase):
    def test_owned_catherine_client_cast_and_recall_requests_use_native_actions(self):
        path = stack_dir() / "wire-1788799203725554700.jsonl"
        if not path.is_file():
            self.skipTest("operator-owned Catherine input trace unavailable")
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        heroes = [bytes.fromhex(row["payload"]) for row in rows
                  if row["opcode"] == 1011 and row["direction"] == "s2c"]
        self.assertTrue(any(struct.unpack_from(">I", payload)[0] == 242
                            and struct.unpack_from(">I", payload, 8)[0] == 1500 for payload in heroes))
        # The operator clicked the first ability, then Recall. These are the
        # requests emitted by the unchanged client, independent of our reply.
        for timestamp, action in ((1788800004.0111146, 1), (1788800117.7488608, 5)):
            request = next(row for row in rows if row["time"] == timestamp and row["direction"] == "c2s")
            self.assertEqual(request["opcode"], 1041)
            self.assertEqual(bytes.fromhex(request["payload"]), struct.pack(">IBB", 0xFFFFFFFF, action, 0))

    def test_native_action_inverse_does_not_fall_back_to_an_unrelated_ui_slot(self):
        self.assertEqual([ability_wire.hero_slot_for_action(242, action) for action in (1, 2, 3)], [0, 1, 2])
        for action in (0, 4, 5, 200):
            self.assertIsNone(ability_wire.hero_slot_for_action(242, action))
        self.assertEqual([ability_wire.hero_slot_for_action(243, action) for action in (0, 1, 2)], [0, 1, 2])
        self.assertIsNone(ability_wire.hero_slot_for_action(243, 4))  # Ringo Recall
        self.assertIsNone(ability_wire.hero_slot_for_action(279, 3))  # Phinn Recall
        self.assertIsNone(ability_wire.hero_slot_for_action(123456, 0))

    def test_catherine_native_rank_one_and_two_unlock_ui_a_and_b(self):
        for before_chunk, rank_row, after_chunk, ui_slot, native_action, cooldown in (
                (1, 419, 2, 0, 1, 16.0), (11, 1261, 12, 1, 2, 13.0)):
            before_path = CATHERINE_REPLAY / f"{CATHERINE_PREFIX}.{before_chunk}.vgr"
            after_path = CATHERINE_REPLAY / f"{CATHERINE_PREFIX}.{after_chunk}.vgr"
            if not before_path.is_file() or not after_path.is_file():
                self.skipTest("operator-owned Catherine replay unavailable")
            before, before_stats = decode.walk_vgr(str(before_path))
            after, after_stats = decode.walk_vgr(str(after_path))
            self.assertEqual((before_stats["failures"], after_stats["failures"]), (0, 0))
            rank_payload = before[rank_row][2]
            self.assertEqual(before[rank_row][1], 1082)
            self.assertEqual(rank_payload, struct.pack(">II6x", 1516, native_action))
            rank_actions = [struct.unpack_from(">I", payload, 4)[0] for _, opcode, payload in before
                            if opcode == 1082 and struct.unpack_from(">I", payload)[0] == 1516]
            self.assertEqual(rank_actions, [native_action])
            symbol = f"Ability__Catherine__{'ABC'[ui_slot]}"
            tag = cooldown_wire.native_ability_tag(symbol)

            def timer(rows, wanted):
                return next(tick for _, opcode, payload in rows if opcode == 1162
                            for tick in (cooldown_wire.parse_timer_tick(payload),)
                            if tick.eid == 1516 and tick.tag == wanted)

            previous, learned = timer(before, tag), timer(after, tag)
            self.assertEqual((previous.duration, previous.state), (0.0, bytes((0, 0, 1, 0, 1, 0))))
            self.assertEqual((learned.duration, learned.state), (cooldown, bytes((1, 1, 1, 0, 1, 0))))
            ultimate = timer(after, cooldown_wire.native_ability_tag("Ability__Catherine__C"))
            self.assertEqual((ultimate.duration, ultimate.state), (0.0, bytes((0, 0, 1, 1, 1, 0))))
            kit = abilities.create_hero_kit(hero_movement.HeroMovement(1500), 242)
            self.assertEqual(kit.abilities[ui_slot].native_action, native_action)
            self.assertNotEqual(ui_slot, native_action)

    @unittest.skipUnless(DATA.is_dir() and NAMES.is_file(), "operator-owned native hero CFF files unavailable")
    def test_all_implemented_named_kit_actions_and_timer_tags_match_native_symbols(self):
        paths = dict(line.split("\t")[:2] for line in NAMES.read_text().splitlines())
        checked = 0
        for hero_id in (242, 243, 244, 245, 256, 275, 285, 395, 925):
            kit = abilities.create_hero_kit(hero_movement.HeroMovement(1500), hero_id)
            native = read_actions(DATA / paths[hero_balance.HERO_NAMES[hero_id]])
            for slot, ability in kit.abilities.items():
                with self.subTest(hero=kit.name, slot=slot):
                    matched = next(row for row in native if row["name"].endswith("__" + "ABC"[int(slot)]))
                    self.assertEqual(ability.native_action, matched["index"])
                    self.assertEqual(ability.tag_inst, cooldown_wire.native_ability_tag(matched["name"]))
                    checked += 1
        self.assertEqual(checked, 21)


class TestCatherineRankSession(unittest.TestCase):
    def setUp(self):
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                       [(0, 1, 2), (0, 2, 3)])
        players = roster.default_solo_bots("rank-owner", "rank-match")
        players = [players[0], players[3]]
        players[0].hero_id, players[1].hero_id = 242, 243
        for player in players:
            player.is_bot = False
        self.owner, self.observer = object(), object()
        self.owner_frames, self.observer_frames = [], []
        self.world = match_server.SnapshotStream(self.owner, players, "rank-match",
            lambda opcode, payload: self.owner_frames.append((opcode, payload)),
            log=lambda _: None, navigation_mesh=mesh)
        self.world.clients[self.observer] = (players[1],
            lambda opcode, payload: self.observer_frames.append((opcode, payload)))
        self.world._finalize()
        self.world.phase = self.world.WORLD
        self.owner_frames.clear()
        self.observer_frames.clear()

    def assert_c_learned_frames(self):
        self.assertEqual([payload for opcode, payload in self.owner_frames if opcode == 1078],
                         [bytes((2,)) + bytes(5)])
        self.assertFalse(any(opcode == 1078 for opcode, _ in self.observer_frames))
        for frames in (self.owner_frames, self.observer_frames):
            self.assertEqual([payload for opcode, payload in frames if opcode == 1082],
                             [struct.pack(">II6x", 1500, 3)])
            timers = [cooldown_wire.parse_timer_tick(payload) for opcode, payload in frames if opcode == 1162]
            self.assertEqual(len(timers), 1)
            self.assertEqual((timers[0].eid, timers[0].tag, timers[0].remaining, timers[0].duration, timers[0].state),
                             (1500, 0x74C2BF8D, 0.0, 90.0, bytes((1, 1, 1, 1, 1, 0))))

    def test_native_ui_c_request_echoes_slot_two_but_acknowledges_action_three(self):
        player = self.world.economy.get_or_create(1500)
        player.add_xp(500.0)
        player.apply_to_hero(self.world.hero_sim)
        # Observed on the owned Catherine client: C's plus button sends 02,
        # while native Catherine action ordinal 3 identifies Blast Tremor.
        self.world._apply_event(1078, bytes((2,)) + bytes(5), self.owner)
        self.assertEqual(self.world.hero_kits[1500].ranks[2], 1)
        self.assertEqual((player.level, player.ability_points), (6, 5))
        self.assert_c_learned_frames()

    def test_qa_learn_uses_same_native_c_action_and_correct_timer(self):
        with tempfile.TemporaryDirectory(prefix="halcyon-rank-qa-") as temporary:
            directory = Path(temporary)
            qa = sandbox_qa.SandboxQA(directory)
            sandbox_qa.atomic_json(directory / "command-learn-c.json",
                                   {"command": "learn", "eid": 1500, "slot": 2})
            result, = qa.pump(self.world)
            self.assertTrue(result["ok"], result)
        self.assertEqual((self.world.hero_kits[1500].ranks[2], self.world.economy.players[1500].level), (1, 6))
        self.assertEqual(sum(opcode == 1076 for opcode, _ in self.owner_frames), 5)
        self.assert_c_learned_frames()

    def test_reconnect_rank_notifications_map_all_catherine_slots(self):
        player = self.world.economy.get_or_create(1500)
        player.add_xp(500.0)
        player.apply_to_hero(self.world.hero_sim)
        kit = self.world.hero_kits[1500]
        for slot in (0, 1, 2):
            self.assertTrue(self.world.economy.upgrade_ability(1500, slot, kit))
        frames = []
        self.world._reconnect_hero_state(self.world.players[0],
                                       lambda opcode, payload: frames.append((opcode, payload)))
        self.assertEqual([payload for opcode, payload in frames if opcode == 1078],
                         [bytes((slot,)) + bytes(5) for slot in (0, 1, 2)])
        self.assertEqual([struct.unpack_from(">I", payload, 4)[0] for opcode, payload in frames
                          if opcode == 1082 and struct.unpack_from(">I", payload)[0] == 1500], [1, 2, 3])
        self.assertEqual(player.ability_points, 3)

    def test_recorded_catherine_action_one_casts_a_without_spending_b(self):
        kit, hero = self.world.hero_kits[1500], self.world.hero_sim
        self.assertTrue(self.world.economy.upgrade_ability(1500, 0, kit))
        energy = hero.energy
        self.world._apply_event(1041, struct.pack(">IBB", 0xFFFFFFFF, 1, 0), self.owner)
        self.assertEqual(energy - hero.energy, 30.0)
        self.assertEqual(kit.cooldowns.get(0), 16.0)
        self.assertEqual(kit.cooldowns.get(1, 0.0), 0.0)
        self.assertEqual([payload for opcode, payload in self.owner_frames if opcode == 1045],
                         [struct.pack(">IIB5x", 1500, 0xFFFFFFFF, 1)])

    def _assert_catherine_ground_action_three(self, opcode):
        player, hero, kit = self.world.economy.get_or_create(1500), self.world.hero_sim, self.world.hero_kits[1500]
        player.add_xp(500.0)
        player.apply_to_hero(hero)
        self.assertTrue(self.world.economy.upgrade_ability(1500, 2, kit))
        x, y = hero.x + 4.0, hero.y
        if opcode == 1042:
            payload = struct.pack(">fffBB", x, 0.0, y, 3, 0)
        else:
            payload = struct.pack(">IIfffBB", 1500, 0xFFFFFFFF, x, 0.0, y, 3, 0)
        energy = hero.energy
        self.world._apply_event(opcode, payload, self.owner)
        self.assertEqual(energy - hero.energy, 120.0)
        self.assertEqual(kit.cooldowns.get(2), 90.0)
        self.assertIsNone(hero.recall_completes_at)
        actions = [p for op, p in self.owner_frames if op == 1046]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0][16], 3)

    def test_ground_input_converts_catherine_action_three_to_c(self):
        self._assert_catherine_ground_action_three(1042)

    def test_legacy_skillshot_input_uses_same_native_action_conversion(self):
        # Compatibility-path coverage; this does not claim a Catherine 1102
        # request was observed in the bounded native input capture.
        self._assert_catherine_ground_action_three(1102)

    def test_catherine_unmapped_action_zero_is_not_a_and_recall_is_action_five(self):
        kit, hero = self.world.hero_kits[1500], self.world.hero_sim
        self.assertTrue(self.world.economy.upgrade_ability(1500, 0, kit))
        energy = hero.energy
        for action in (0, 3, 4):
            self.world._apply_event(1041, struct.pack(">IBB", 0xFFFFFFFF, action, 0), self.owner)
        self.assertEqual(hero.energy, energy)
        self.assertFalse(self.owner_frames)
        self.assertIsNone(hero.recall_completes_at)
        self.world._apply_event(1041, struct.pack(">IBB", 0xFFFFFFFF, 5, 0), self.owner)
        self.assertEqual(hero.recall_completes_at, 4.0)
        self.assertEqual(hero.energy, energy)
        self.assertEqual([payload for opcode, payload in self.owner_frames if opcode == 1045],
                         [struct.pack(">IIB5x", 1500, 0xFFFFFFFF, 5)])

    def test_ringo_a_keeps_action_zero_and_its_native_timer(self):
        self.world.players[0].hero_id = 243
        self.world._finalize()
        kit = self.world.hero_kits[1500]
        self.assertTrue(self.world.economy.upgrade_ability(1500, 0, kit))
        frames = self.world._learned_ability_frames(1500, 0)
        self.assertEqual(frames[0], (1082, struct.pack(">II6x", 1500, 0)))
        timer = cooldown_wire.parse_timer_tick(frames[1][1])
        self.assertEqual((timer.eid, timer.tag, timer.duration, timer.state),
                         (1500, 0xC8D51D33, 9.0, bytes((1, 1, 1, 0, 1, 0))))


if __name__ == "__main__":
    unittest.main()

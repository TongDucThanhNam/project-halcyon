"""Local QA fixtures use the production world and preserve native ownership."""
import copy
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from server import buff_wire, economy, sandbox_qa
from server import wave as wave_module
from server.status_effects import StatusEffect, StatusType
from server.test.test_sandbox_simulation import session
from server.test.test_level_reconnect import NativeProgression
from Tools import sandbox_qa as qa_cli


class TestSandboxQA(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='halcyon-qa-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.qa = sandbox_qa.SandboxQA(self.directory)
        self.world, self.frames = session()
        self.world.sim_tick, self.world.sim_time = 200, 10.0
        for eid in self.world.hero_sims:
            self.world.economy.get_or_create(eid)

    def queue(self, command, identity='one'):
        path = self.directory / f'command-{identity}.json'
        sandbox_qa.atomic_json(path, command)
        return path

    def run_command(self, command, identity='one'):
        self.queue(command, identity)
        result, = self.qa.pump(self.world)
        self.assertEqual(result['tick'], 200)
        self.assertEqual(result['time'], 10)
        return result

    def test_lane_minions_census_is_read_only_and_team_filtered(self):
        from server import wave as wave_module
        self.world._enter_world()
        self.world.wave_director = wave_module.Director(0.0, seq_1010=[0])
        self.world.wave_director.minions = [
            wave_module.Minion(4610, 1, 0.0), wave_module.Minion(4620, 2, 0.0)]
        self.world.wave_director.minions[1].x = 12.5
        result = self.run_command({'command': 'lane_minions'})
        rows = result['result']['minions']
        self.assertEqual(result['result']['count'], 2)
        self.assertEqual([row['eid'] for row in rows], [4610, 4620])
        self.assertEqual([row['team'] for row in rows], [1, 2])
        self.assertTrue(all(row['alive'] if 'alive' in row else row['hp'] > 0
                            for row in rows))
        filtered = self.run_command({'command': 'lane_minions', 'team': 2}, 'two')
        self.assertEqual([row['eid'] for row in filtered['result']['minions']],
                         [4620])
        self.assertEqual(filtered['result']['count'], 1)

    def test_diagnostics_reports_loaded_state_identity(self):
        """The diagnostics receipt ties to the actual process and reports the
        loaded bootstrap identity (world.tape_frames), source digests for
        startup vs current, tape file identity, and env config."""
        import struct as _struct
        self.world._enter_world()
        self.world.wave_director = wave_module.Director(0.0, seq_1010=[0])
        self.world.tape_frames = [(0, _struct.pack(">H", 1087) + b"\x00" * 8),
                                  (500, _struct.pack(">H", 1053) + b"\x00" * 8)]
        result = self.run_command({'command': 'diagnostics'})
        receipt = result['result']
        self.assertEqual(receipt['pid'], os.getpid())
        self.assertTrue(receipt['source_startup_digest'])
        self.assertIn(receipt['source_unchanged_since_startup'], (True, False))
        self.assertEqual(receipt['tape_loaded']['records'], 2)
        self.assertTrue(receipt['tape_loaded']['sha256'])
        self.assertIn('match_id', receipt)
        self.assertIn('phase', receipt)
        self.assertIn('tape_file_identity', receipt)

    def test_diagnostics_reports_unknown_loaded_tape_without_frames(self):
        self.world._enter_world()
        self.world.tape_frames = None
        result = self.run_command({'command': 'diagnostics'})
        receipt = result['result']
        self.assertEqual(receipt['tape_loaded']['identity'], 'UNKNOWN',
                         'unobservable loaded frames must be UNKNOWN, not '
                         'silently accepted')

    def test_lane_minions_requires_world_phase(self):
        self.world.phase = self.world.LOCKED
        self.queue({'command': 'lane_minions'})
        result, = self.qa.pump(self.world)
        self.assertFalse(result['ok'])
        self.assertIn('WORLD', result['error'])

    def test_default_is_disabled_and_external_absolute_directory_is_required(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(sandbox_qa.SandboxQA.from_environment())
        with self.assertRaises(ValueError):
            sandbox_qa.SandboxQA('relative-qa')
        with self.assertRaises(ValueError):
            sandbox_qa.SandboxQA(Path(__file__).resolve().parents[2])

    def test_sorted_requests_execute_once_and_restart_cannot_replay_a_consumed_identity(self):
        self.queue({'command': 'resources', 'eid': 1500, 'gold': 3000}, 'z')
        self.queue({'command': 'resources', 'eid': 1500, 'gold': 1000}, 'a')
        results = self.qa.pump(self.world)
        self.assertEqual([result['id'] for result in results], ['a', 'z'])
        self.assertTrue(all(result['ok'] for result in results))
        self.assertEqual(self.world.economy.players[1500].gold, 3000)
        journal = [json.loads(line) for line in (self.directory / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual([(row['id'], row['tick']) for row in journal if row['event'] == 'accepted'], [('a', 200), ('z', 200)])
        old_ack = (self.directory / 'ack-a.json').read_bytes()
        self.frames.clear()
        self.queue({'command': 'resources', 'eid': 1500, 'gold': 9999}, 'a')
        restarted = sandbox_qa.SandboxQA(self.directory)
        self.assertFalse(restarted.pump(self.world))
        self.assertEqual(self.world.economy.players[1500].gold, 3000)
        self.assertEqual((self.directory / 'ack-a.json').read_bytes(), old_ack)
        self.assertFalse(self.frames)

    def test_per_tick_batch_limit_and_partial_temp_files_are_not_commands(self):
        for number in range(10):
            self.queue({'command': 'snapshot'}, str(number).zfill(2))
        (self.directory / '.qa-incomplete.tmp').write_text('{')
        self.assertEqual(len(self.qa.pump(self.world)), 8)
        self.assertEqual(len(self.qa.pump(self.world)), 2)
        self.assertTrue((self.directory / '.qa-incomplete.tmp').exists())

    def test_snapshot_is_read_only_and_state_file_contains_current_cooldowns_inventory_and_phase(self):
        econ = self.world.economy.players[1500]
        econ.inventory[0] = economy.ITEMS_BY_KEY['sprint_boots']
        econ.inventory_instances[0] = 2020
        econ.item_cooldowns['boots'] = 15
        self.world.hero_kits[1500].cooldowns[0] = 12
        before = copy.deepcopy((self.world.sim_tick, self.world.sim_time, vars(econ),
                                self.world.hero_kits[1500].ranks, self.world.hero_kits[1500].cooldowns,
                                self.world._next_buff_instance, self.world.economy._pending_gold))
        result = self.run_command({'command': 'snapshot'})
        self.assertTrue(result['ok'])
        state = result['result']
        hero = next(hero for hero in state['heroes'] if hero['eid'] == 1500)
        self.assertEqual((state['phase'], state['tick'], state['time']), (self.world.WORLD, 200, 10))
        self.assertEqual(hero['inventory'], [{'slot': 0, 'item': econ.inventory[0].id, 'instance': 2020}])
        self.assertEqual(hero['item_cooldowns']['boots'], 5)
        self.assertEqual(hero['ability_cooldowns']['0'], 2)
        self.assertEqual(len(state['structures']), 12)
        self.assertEqual(before, (self.world.sim_tick, self.world.sim_time, vars(econ),
                                  self.world.hero_kits[1500].ranks, self.world.hero_kits[1500].cooldowns,
                                  self.world._next_buff_instance, self.world.economy._pending_gold))
        self.assertFalse(self.frames)
        self.assertEqual(json.loads((self.directory / 'state.json').read_text()), state)

    def test_snapshot_before_first_economy_tick_does_not_create_accounts(self):
        self.world.economy.players.clear()
        result = self.run_command({'command': 'snapshot'})
        self.assertTrue(result['ok'])
        self.assertFalse(self.world.economy.players)
        self.assertFalse(self.frames)

    def test_resources_clamp_to_actor_caps_and_publish_only_actual_native_deltas(self):
        hero = self.world.hero_sims[1500]
        old = hero.hp, hero.energy, self.world.economy.players[1500].gold
        result = self.run_command({'command': 'resources', 'eid': 1500, 'hp': 123, 'energy': 0, 'gold': 10000})
        self.assertTrue(result['ok'])
        self.assertEqual((hero.hp, hero.energy, self.world.economy.players[1500].gold), (123, 0, 10000))
        deltas = [struct.unpack_from('>IfB', payload) for opcode, payload in self.frames if opcode == 1053]
        self.assertEqual(deltas, [(1500, 123 - old[0], 0), (1500, -old[1], 2), (1500, 10000 - old[2], 6)])
        result = self.run_command({'command': 'resources', 'eid': 1500, 'hp': 1000000, 'energy': 1000000}, 'caps')
        self.assertTrue(result['ok'])
        self.assertEqual((hero.hp, hero.energy), (hero.max_hp, hero.max_energy))
        self.assertTrue(hero.is_alive)

    def test_teleport_clamps_to_mesh_and_cancels_movement_recall_and_windup(self):
        hero = self.world.hero_sims[1500]
        hero.start_recall(10)
        hero.target_eid = 1517
        self.world.attacks.step_attacker(hero, self.world.hero_sims[1517], 10)
        result = self.run_command({'command': 'teleport', 'eid': 1500, 'x': 500, 'y': 0})
        self.assertTrue(result['ok'])
        self.assertEqual((hero.x, hero.y), (100, 0))
        self.assertIsNone(hero.target_eid)
        self.assertIsNone(hero.recall_completes_at)
        self.assertFalse(hero.is_moving)
        self.assertEqual(self.frames[-1][0], 1070)
        self.assertEqual(struct.unpack_from('>Iff', self.frames[-1][1]), (1500, 100, 0))

    def test_damage_uses_production_mitigation_and_one_native_hp_delta(self):
        victim = self.world.hero_sims[1517]
        victim.armor = 100
        before = victim.hp
        result = self.run_command({'command': 'damage', 'source': 1500, 'target': 1517, 'amount': 100, 'kind': 'weapon'})
        self.assertTrue(result['ok'])
        self.assertEqual((before - victim.hp, result['result']['actual_damage']), (50, 50))
        self.assertEqual([opcode for opcode, _ in self.frames], [1054])
        self.assertEqual(struct.unpack_from('>IIf', self.frames[0][1]), (1517, 1500, -50))

    def test_status_uses_actual_interrupt_serial_and_fixed_tick_displacement(self):
        hero = self.world.hero_sims[1500]
        self.assertTrue(self.run_command({'command': 'status', 'eid': 1500, 'type': 'STUN', 'duration': .5})['ok'])
        self.assertFalse(self.world.status_manager.can_cast(1500, 10))
        self.assertEqual(self.world.status_manager.get_interrupt_serial(1500), 1)
        self.assertTrue(self.world.status_manager.can_cast(1500, 10.5))
        result = self.run_command({'command': 'status', 'eid': 1500, 'type': 'KNOCKBACK',
                                   'duration': .5, 'dx': 3, 'dy': 4, 'speed': 10}, 'knockback')
        self.assertTrue(result['ok'])
        dx, dy = self.world.status_manager.get_knockback_displacement(1500, .05, 10.05)
        self.assertAlmostEqual(dx, .3)
        self.assertAlmostEqual(dy, .4)
        self.assertEqual(self.world.status_manager.get_interrupt_serial(1500), 2)

    def test_known_statuses_publish_native_buffs_through_the_normal_tick_drain(self):
        self.world.qa = self.qa
        for kind, duration in (('STUN', .5), ('SILENCE', 1)):
            self.queue({'command': 'status', 'eid': 1500, 'type': kind, 'duration': duration}, kind)
        self.assertFalse(self.frames)
        self.world.advance_simulation()
        adds = [buff_wire.parse_buff_add(payload) for op, payload in self.frames if op == 1086]
        self.assertEqual(sorted((buff.kind, buff.target_eid, buff.source_eid, buff.duration) for buff in adds),
                         [(22, 1500, 1500, .5), (32, 1500, 1500, 1)])
        self.assertEqual(len({buff.instance_id for buff in adds}), 2)
        for kind in ('STUN', 'SILENCE'):
            receipt = json.loads((self.directory / f'ack-{kind}.json').read_text())
            self.assertTrue(receipt['ok'])
            self.assertTrue(receipt['result']['applied'])
            self.assertEqual((receipt['tick'], receipt['time']), (200, 10))
            self.assertTrue(self.world.status_manager.has_effect(1500, StatusType[kind], self.world.sim_time))
        while self.world.sim_tick < 220:
            self.world.advance_simulation()
        self.assertTrue(self.world.status_manager.can_cast(1500, 11))
        self.assertNotIn(1500, self.world.status_manager.effects)
        self.assertFalse(any(op == 1093 for op, _ in self.frames))

    def test_immune_status_rejections_emit_no_false_buff_or_allocate_an_instance(self):
        self.world.qa = self.qa
        manager = self.world.status_manager
        manager.apply_effect(StatusEffect('block', StatusType.CC_IMMUNITY, 1500, 1500, 1, 10, 11))
        next_instance = self.world._next_buff_instance
        for kind in ('STUN', 'SILENCE'):
            self.queue({'command': 'status', 'eid': 1500, 'type': kind, 'duration': .5}, kind)
        self.world.advance_simulation()
        for kind in ('STUN', 'SILENCE'):
            receipt = json.loads((self.directory / f'ack-{kind}.json').read_text())
            self.assertTrue(receipt['ok'])
            self.assertFalse(receipt['result']['applied'])
            self.assertFalse(manager.has_effect(1500, StatusType[kind], self.world.sim_time))
        self.assertFalse(any(op == 1086 for op, _ in self.frames))
        self.assertEqual(self.world._next_buff_instance, next_instance)
        self.assertEqual(manager.get_interrupt_serial(1500), 0)

    def test_unmapped_fixture_statuses_keep_mechanics_without_an_invented_native_buff(self):
        self.world.qa = self.qa
        for kind in ('SLOW', 'KNOCKBACK'):
            self.queue({'command': 'status', 'eid': 1500, 'type': kind, 'duration': .5}, kind)
        self.world.advance_simulation()
        effects = self.world.status_manager.effects[1500]
        self.assertEqual({effect.effect_type for effect in effects}, {StatusType.SLOW, StatusType.KNOCKBACK})
        self.assertTrue(all(effect.native_buff_kind is None for effect in effects))
        self.assertFalse(any(op == 1086 for op, _ in self.frames))

    def test_learn_grants_real_level_and_point_then_owner_only_ack(self):
        left, right = object(), object()
        left_frames, right_frames = [], []
        self.world.clients = {
            left: (self.world.players[0], lambda op, payload: left_frames.append((op, payload))),
            right: (self.world.players[1], lambda op, payload: right_frames.append((op, payload))),
        }
        result = self.run_command({'command': 'learn', 'eid': 1500, 'slot': 2})
        self.assertTrue(result['ok'])
        kit, econ = self.world.hero_kits[1500], self.world.economy.players[1500]
        self.assertEqual((kit.ranks[2], econ.level, self.world.hero_sims[1500].level), (1, 6, 6))
        self.assertEqual(econ.xp, economy.XP_LEVEL_THRESHOLDS[5])
        self.assertEqual(econ.ability_points, 5)
        self.assertEqual([payload for op, payload in left_frames if op == 1078], [bytes((2,)) + bytes(5)])
        self.assertFalse(any(op == 1078 for op, _ in right_frames))
        self.assertEqual([payload for op, payload in right_frames if op == 1082], [struct.pack('>II6x', 1500, 2)])
        self.assertTrue(any(op == 1053 and payload[8] == 8 for op, payload in left_frames))

    def test_catherine_a_b_c_each_has_a_native_point_before_rank_ack(self):
        self.world.players[0].hero_id = 242
        self.world._finalize()
        self.world.phase = self.world.WORLD
        owner, observer = object(), object()
        owner_frames, observer_frames = [], []
        self.world.clients = {
            owner: (self.world.players[0], lambda op, p: owner_frames.append((op, p))),
            observer: (self.world.players[1], lambda op, p: observer_frames.append((op, p))),
        }
        receivers = [NativeProgression(1500), NativeProgression(1500)]
        for slot, level, xp_granted, points, increments in (
                (0, 1, 0, 0, 0), (1, 2, 68, 0, 1), (2, 6, 432, 3, 4)):
            result = self.run_command({'command': 'learn', 'eid': 1500, 'slot': slot}, f'chain-{slot}')
            self.assertTrue(result['ok'], result)
            self.assertEqual((result['result']['level'], result['result']['xp_granted'],
                              result['result']['extra_points_granted']), (level, xp_granted, 0))
            econ = self.world.economy.players[1500]
            self.assertEqual(econ.ability_points, points)
            self.assertEqual([p for op, p in owner_frames if op == 1078], [bytes((slot,)) + bytes(5)])
            self.assertFalse(any(op == 1078 for op, _ in observer_frames))
            for receiver, frames in zip(receivers, (owner_frames, observer_frames)):
                self.assertEqual(sum(op == 1076 for op, _ in frames), increments)
                self.assertEqual([p for op, p in frames if op == 1082], [struct.pack('>II6x', 1500, slot + 1)])
                # The measured receiver counts each 1076 grant and each 1082
                # spend; the server's private point counter cannot hide a gap.
                receiver.receive(frames)
                self.assertEqual((receiver.level, receiver.points), (level, points))
                self.assertGreaterEqual(min(receiver.point_history), 0)
                frames.clear()
        self.assertEqual(self.world.economy.players[1500].xp, 500)
        self.assertEqual(receivers[0].ranks, {1: 1, 2: 1, 3: 1})

    def test_level_cap_with_no_points_rejects_an_otherwise_legal_rank_without_mutation(self):
        hero = self.world.hero_sims[1500]
        econ = self.world.economy.players[1500]
        kit = self.world.hero_kits[1500]
        econ.add_xp(economy.XP_LEVEL_THRESHOLDS[11])
        econ.apply_to_hero(hero)
        for slot in [0] * 5 + [1] * 5 + [2] * 2:
            self.assertTrue(self.world.economy.upgrade_ability(1500, slot, kit))
        self.assertEqual((econ.level, econ.ability_points, sum(kit.ranks.values())), (12, 0, 12))
        before = sandbox_qa.SandboxQA.snapshot(self.world)
        self.frames.clear()
        result = self.run_command({'command': 'learn', 'eid': 1500, 'slot': 2}, 'cap-no-point')
        self.assertFalse(result['ok'])
        self.assertIn('available ability point', result['error'])
        self.assertEqual(sandbox_qa.SandboxQA.snapshot(self.world), before)
        self.assertFalse(self.frames)

    def test_level_cap_can_spend_its_last_existing_point_without_granting_xp(self):
        hero = self.world.hero_sims[1500]
        econ = self.world.economy.players[1500]
        kit = self.world.hero_kits[1500]
        econ.add_xp(economy.XP_LEVEL_THRESHOLDS[11])
        econ.apply_to_hero(hero)
        for slot in [0] * 5 + [1] * 4 + [2] * 2:
            self.assertTrue(self.world.economy.upgrade_ability(1500, slot, kit))
        self.assertEqual(econ.ability_points, 1)
        self.frames.clear()
        result = self.run_command({'command': 'learn', 'eid': 1500, 'slot': 2}, 'cap-last-point')
        self.assertTrue(result['ok'], result)
        self.assertEqual((result['result']['xp_granted'], result['result']['extra_points_granted']), (0, 0))
        self.assertEqual((econ.level, econ.ability_points, kit.ranks[2]), (12, 0, 3))
        self.assertEqual(sum(kit.ranks.values()), 12)
        self.assertFalse(any(op == 1076 or (op == 1053 and payload[8] == 8) for op, payload in self.frames))
        self.assertEqual([payload for op, payload in self.frames if op == 1082], [struct.pack('>II6x', 1500, 2)])

    def test_invalid_inputs_are_rejected_before_any_world_mutation(self):
        requests = [
            {'command': 'resources', 'eid': 1500, 'hp': 10, 'execute': 'anything'},
            {'command': 'resources', 'eid': 1500, 'hp': 0},
            {'command': 'resources', 'eid': 1500, 'gold': 100001},
            {'command': 'teleport', 'eid': True, 'x': 0, 'y': 0},
            {'command': 'status', 'eid': 1500, 'type': 'STUN', 'duration': 11},
            {'command': 'status', 'eid': 1500, 'type': 'KNOCKBACK', 'duration': 1, 'dx': 0, 'dy': 0},
            {'command': 'learn', 'eid': 1500, 'slot': 1.0},
            {'command': 'damage', 'source': 1500, 'target': 1517, 'amount': 1, 'kind': 'eval'},
            {'command': 'execute', 'code': 'anything'},
        ]
        before = sandbox_qa.SandboxQA.snapshot(self.world)
        for number, request in enumerate(requests):
            with self.subTest(request=request):
                self.assertFalse(self.run_command(request, str(number))['ok'])
        self.assertEqual(sandbox_qa.SandboxQA.snapshot(self.world), before)
        self.assertFalse(self.frames)

    def test_oversize_nonfinite_duplicate_json_and_symlink_files_are_rejected(self):
        rows = ['{"command":"snapshot","extra":"' + 'x' * 4096 + '"}',
                '{"command":"teleport","eid":1500,"x":NaN,"y":0}',
                '{"command":"snapshot","command":"resources"}']
        for number, raw in enumerate(rows):
            path = self.directory / f'command-bad{number}.json'
            path.write_text(raw)
        results = self.qa.pump(self.world)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(not result['ok'] for result in results))
        target = self.directory / 'target.json'
        target.write_text('{"command":"resources","eid":1500,"gold":9999}')
        linked = self.directory / 'command-link.json'
        try:
            linked.symlink_to(target)
        except OSError as error:
            self.skipTest(f'local OS cannot create a test symlink: {error}')
        result, = self.qa.pump(self.world)
        self.assertFalse(result['ok'])
        self.assertIn('non-symlink', result['error'])
        self.assertTrue(target.exists())
        self.assertEqual(self.world.economy.players[1500].gold, economy.START_GOLD)
        self.assertFalse(self.frames)

    def test_dead_or_finished_world_changes_are_rejected(self):
        self.world.hero_sims[1500].is_alive = False
        self.assertFalse(self.run_command({'command': 'resources', 'eid': 1500, 'hp': 500})['ok'])
        self.world.structures.match_finished = True
        self.assertFalse(self.run_command({'command': 'learn', 'eid': 1517, 'slot': 0}, 'finished')['ok'])
        self.assertTrue(self.run_command({'command': 'snapshot'}, 'read-only')['ok'])

    def test_snapshot_sharing_failure_keeps_last_good_state_and_retries_next_tick(self):
        self.qa.pump(self.world)
        state_path = self.directory / 'state.json'
        previous = state_path.read_bytes()
        original_publish = sandbox_qa.atomic_json
        logs = []
        self.world.log = logs.append
        self.world.qa = self.qa
        self.world.sim_tick, self.world.sim_time = 210, 10.5

        def locked_state(path, value):
            if path == state_path:
                raise PermissionError(13, 'simulated Windows sharing violation')
            return original_publish(path, value)

        with patch('server.sandbox_qa.atomic_json', side_effect=locked_state):
            self.world.advance_simulation()
            self.world.advance_simulation()
        self.assertEqual(self.world.sim_tick, 212)
        self.assertEqual(state_path.read_bytes(), previous)
        self.assertTrue(self.qa._snapshot_pending)
        self.assertEqual(sum('publish state.json failed' in line for line in logs), 1)
        self.world.advance_simulation()
        self.assertEqual(self.world.sim_tick, 213)
        self.assertEqual(json.loads(state_path.read_text())['tick'], 212)
        self.assertFalse(self.qa._snapshot_pending)

    @unittest.skipUnless(os.name == 'nt', 'real Windows read-share lock reproduction')
    def test_real_windows_reader_blocks_replace_without_ending_world_ticks(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        self.qa.pump(self.world)
        state_path = self.directory / 'state.json'
        previous = state_path.read_bytes()
        # Allow concurrent reads/writes but omit FILE_SHARE_DELETE, as a
        # reader can do. Atomic replacement of this destination must fail.
        handle = create(str(state_path), 0x80000000, 0x1 | 0x2, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            self.fail(f'could not acquire isolated test read handle: {ctypes.get_last_error()}')
        self.world.qa = self.qa
        self.world.sim_tick, self.world.sim_time = 210, 10.5
        try:
            with self.assertRaises(PermissionError):
                sandbox_qa.atomic_json(state_path, {'would_replace': True})
            self.world.advance_simulation()
            self.assertEqual(self.world.sim_tick, 211)
            self.assertEqual(state_path.read_bytes(), previous)
            self.assertTrue(self.qa._snapshot_pending)
        finally:
            kernel.CloseHandle(handle)
        self.world.advance_simulation()
        self.assertEqual(self.world.sim_tick, 212)
        self.assertEqual(json.loads(state_path.read_text())['tick'], 211)
        self.assertFalse(self.qa._snapshot_pending)

    def test_failed_ack_is_retried_without_reapplying_claimed_command_or_duplicate(self):
        self.queue({'command': 'learn', 'eid': 1500, 'slot': 0}, 'locked-ack')
        ack = self.directory / 'ack-locked-ack.json'
        original_publish = sandbox_qa.atomic_json

        def locked_ack(path, value):
            if path == ack:
                raise PermissionError(13, 'ack destination locked')
            return original_publish(path, value)

        with patch('server.sandbox_qa.atomic_json', side_effect=locked_ack):
            result, = self.qa.pump(self.world)
            self.assertTrue(result['ok'])
            self.assertFalse(ack.exists())
            self.assertEqual(len(self.qa._pending_acks), 1)
            self.queue({'command': 'learn', 'eid': 1500, 'slot': 0}, 'locked-ack')
            self.assertEqual(self.qa.pump(self.world), [])
            self.assertEqual(self.world.hero_kits[1500].ranks[0], 1)
        self.assertEqual(self.qa.pump(self.world), [])
        published = ack.read_bytes()
        self.assertTrue(json.loads(published)['ok'])
        self.assertEqual(self.qa._pending_acks, {})
        self.queue({'command': 'learn', 'eid': 1500, 'slot': 0}, 'locked-ack')
        restarted = sandbox_qa.SandboxQA(self.directory)
        self.assertEqual(restarted.pump(self.world), [])
        self.assertEqual(ack.read_bytes(), published)
        self.assertEqual(self.world.hero_kits[1500].ranks[0], 1)

    def test_ack_backlog_is_bounded_and_pauses_only_new_qa_work(self):
        for number in range(10):
            self.queue({'command': 'snapshot'}, f'blocked-{number}')
        original_publish = sandbox_qa.atomic_json

        def locked_acks(path, value):
            if path.name.startswith('ack-'):
                raise PermissionError(13, 'ack publication blocked')
            return original_publish(path, value)

        with patch('server.sandbox_qa.atomic_json', side_effect=locked_acks):
            self.assertEqual(len(self.qa.pump(self.world)), 8)
            self.assertEqual(len(self.qa._pending_acks), 8)
            self.assertEqual(self.qa.pump(self.world), [])
            self.assertEqual(len(self.qa._pending_acks), 8)
            self.assertEqual(len(list(self.directory.glob('command-*.json'))), 2)
        self.assertEqual(len(self.qa.pump(self.world)), 2)
        self.assertEqual(self.qa._pending_acks, {})
        self.assertEqual(len(list(self.directory.glob('ack-*.json'))), 10)

    def test_failed_acceptance_journal_rejects_before_effect_and_cannot_replay(self):
        self.queue({'command': 'learn', 'eid': 1500, 'slot': 0}, 'journal-before')
        original_journal = self.qa._journal

        def blocked_acceptance(value):
            if value['event'] == 'accepted':
                raise PermissionError(13, 'journal locked before execution')
            return original_journal(value)

        with patch.object(self.qa, '_journal', side_effect=blocked_acceptance):
            result, = self.qa.pump(self.world)
        self.assertFalse(result['ok'])
        self.assertIn('before execution', result['error'])
        self.assertEqual(self.world.hero_kits[1500].ranks[0], 0)
        self.assertFalse(self.frames)
        self.queue({'command': 'learn', 'eid': 1500, 'slot': 0}, 'journal-before')
        self.assertEqual(sandbox_qa.SandboxQA(self.directory).pump(self.world), [])
        self.assertEqual(self.world.hero_kits[1500].ranks[0], 0)

    def test_failed_completion_journal_preserves_applied_result_and_never_replays(self):
        self.queue({'command': 'learn', 'eid': 1500, 'slot': 0}, 'journal-after')
        original_journal = self.qa._journal
        logs = []
        self.world.log = logs.append

        def blocked_completion(value):
            if value['event'] == 'completed':
                raise PermissionError(13, 'journal locked after execution')
            return original_journal(value)

        with patch.object(self.qa, '_journal', side_effect=blocked_completion):
            result, = self.qa.pump(self.world)
        self.assertTrue(result['ok'])
        self.assertTrue(json.loads((self.directory / 'ack-journal-after.json').read_text())['ok'])
        self.assertEqual(self.world.hero_kits[1500].ranks[0], 1)
        self.assertTrue(any('append completion journal failed' in line for line in logs))
        self.queue({'command': 'learn', 'eid': 1500, 'slot': 0}, 'journal-after')
        self.assertEqual(sandbox_qa.SandboxQA(self.directory).pump(self.world), [])
        self.assertEqual(self.world.hero_kits[1500].ranks[0], 1)

    def test_cli_atomically_queues_once_and_reports_pending_without_automatic_retry(self):
        with patch.dict(os.environ, {'HALCYON_QA_DIR': str(self.directory)}):
            pending = qa_cli.submit({'command': 'snapshot'}, timeout=0, request_id='cli')
            self.assertTrue(pending['pending'])
            self.assertEqual(len(list(self.directory.glob('command*.json'))), 1)
            self.assertFalse(list(self.directory.glob('.qa-*.tmp')))
            self.qa.pump(self.world)
            result = json.loads(Path(pending['result_path']).read_text())
            self.assertTrue(result['ok'])
            with self.assertRaises(ValueError):
                qa_cli.submit({'command': 'snapshot'}, timeout=0, request_id='cli')
            with patch('Tools.sandbox_qa.time.sleep', side_effect=lambda _: self.qa.pump(self.world)):
                completed = qa_cli.submit({'command': 'snapshot'}, timeout=.5, request_id='cli2')
            self.assertTrue(completed['ok'])
            self.assertEqual(completed['tick'], 200)


if __name__ == '__main__':
    unittest.main()

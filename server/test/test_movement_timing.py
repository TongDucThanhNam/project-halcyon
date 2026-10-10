"""Movement timing must keep actor attribution and evidence limits intact."""
import struct
import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from Tools.Teardown.inspect_movement_trace import correlate_ticks, timing_report


def row(line, time, direction, op, payload):
    return dict(line=line, time=time, direction=direction, opcode=op, decoded=payload)


class MovementTimingTests(unittest.TestCase):
    def test_sustained_overload_services_input_between_bounded_fixed_tick_batches(self):
        from server.test.test_ability_cc_presentation import session
        from server import wire
        world, _, _, owner, _ = session()
        world._load_tape = lambda: None
        world.tape_frames = []
        world.wave_t0 = 0
        world.ready_clients.add(owner)
        world._jungle_published = True
        world.emit_hero_1010 = False
        world.trace_movement_ticks = False
        clock, queued_tick, applied_tick = [0.0], [], []
        original = world.advance_simulation
        def advance():
            original()
            clock[0] += .120  # each fixed step costs more than its50ms budget
            if world.sim_tick == 10:
                queued_tick.append(world.sim_tick)
                world.events.put((wire.OP.MOVE_CAST, struct.pack('>ff6x', 40, 0), owner))
            if world.sim_tick == 30:
                world._stop_event.set()
        original_pump = world._pump
        def pump(timeout):
            clock[0] += timeout
            original_pump(0)
            if queued_tick and world.hero_sims[1500].move_target is not None and not applied_tick:
                applied_tick.append(world.sim_tick)
        world.advance_simulation, world._pump = advance, pump
        with patch('server.match_server.time.monotonic', side_effect=lambda: clock[0]):
            world._run_world()
        self.assertTrue(applied_tick, 'received input was starved during catch-up')
        self.assertLessEqual(applied_tick[0]-queued_tick[0], 4)
        self.assertEqual((world.sim_tick, world.sim_time), (30, 1.5))

    def test_phase_timing_separates_diagnostic_io_without_changing_state(self):
        from server.test.test_ability_cc_presentation import session
        from unittest.mock import Mock
        world, _, _, _, _ = session()
        reference, _, _, _, _ = session()
        world.trace_movement_ticks = True
        clock, cpu = [0.0], [0]
        def qa_work(_):
            clock[0] += .011
        original_step = world._step_heroes
        def hero_work(*args):
            original_step(*args)
            clock[0] += .017
            cpu[0] += 17_000_000
        world.qa = Mock(pump=qa_work)
        world._step_heroes = hero_work
        lines = []
        world.log = lines.append
        phases = {'stale': {}}
        with (patch('server.match_server.time.monotonic', side_effect=lambda: clock[0]),
              patch('server.match_server.time.thread_time_ns', side_effect=lambda: cpu[0])):
            world.advance_simulation(phase_timings=phases)
            world._trace_movement_tick(0, 0)
        reference.advance_simulation()
        record = json.loads(lines[-1].split(' ', 1)[1])
        self.assertAlmostEqual(record['phases_ms']['qa'], 11)
        self.assertAlmostEqual(record['phases_ms']['heroes_effects'], 17)
        self.assertAlmostEqual(sum(record['phases_ms'].values()), 28)
        self.assertNotIn('stale', phases)
        self.assertAlmostEqual(phases['qa']['wall_ms'], 11)
        self.assertEqual(phases['qa']['thread_cpu_ms'], 0)
        self.assertAlmostEqual(phases['heroes_effects']['wall_ms'], 17)
        self.assertEqual(phases['heroes_effects']['thread_cpu_ms'], 17)
        self.assertEqual((world.sim_tick, world.sim_time, world.hero_sim.position_fixed),
                         (reference.sim_tick, reference.sim_time, reference.hero_sim.position_fixed))
        world.trace_movement_ticks = False
        world.advance_simulation()
        self.assertEqual(world._movement_phase_ms, {})  # no stale attribution

    def test_world_pump_waits_for_tick_deadline_not_full_interval_after_work(self):
        from server.test.test_ability_cc_presentation import session
        world, _, _, owner, _ = session()
        world._load_tape = lambda: None
        world.tape_frames = []
        world.wave_t0 = 0
        world.ready_clients.add(owner)
        world._jungle_published = True
        world.emit_hero_1010 = False
        world.trace_movement_ticks = False
        clock = [0.0]
        starts = []
        original = world.advance_simulation
        def advance():
            starts.append(clock[0])
            original()
            clock[0] += .012  # reproducible 12 ms tick work, no real sleeping
            if len(starts) == 20:
                world._stop_event.set()
        def pump(timeout):
            clock[0] += timeout
        world.advance_simulation = advance
        world._pump = pump
        with patch('server.match_server.time.monotonic', side_effect=lambda: clock[0]):
            world._run_world()
        self.assertEqual(len(starts), 20)
        for index, started in enumerate(starts, 1):
            self.assertAlmostEqual(started, index * .05, places=8)

    def test_tick_telemetry_does_not_change_authoritative_movement(self):
        from server.test.test_ability_cc_presentation import session
        from server import wire
        world, _, _, owner, _ = session()
        world._apply_event(wire.OP.MOVE_CAST, struct.pack('>ff6x', 40, 0), owner)
        world.advance_simulation()
        before = (world.sim_tick, world.sim_time, world.hero_sims[1500].position_fixed,
                  world.hero_sims[1500].order_version, dict(world.position_burst))
        lines = []
        world.log = lines.append
        with patch('server.match_server.time.monotonic', return_value=1.025):
            world._trace_movement_tick(1.0, 1.02)
        after = (world.sim_tick, world.sim_time, world.hero_sims[1500].position_fixed,
                 world.hero_sims[1500].order_version, dict(world.position_burst))
        self.assertEqual(before, after)
        record = json.loads(lines[0].split(' ', 1)[1])
        self.assertAlmostEqual(record['late_ms'], 20)
        self.assertAlmostEqual(record['work_ms'], 5)
        self.assertEqual(record['tick'], world.sim_tick)

    def test_logging_cost_and_transient_overrun_preserve_deadlines_and_fixed_steps(self):
        from server.test.test_ability_cc_presentation import session
        from server import wire
        for first_work in (.012, .120):
            with self.subTest(first_work=first_work):
                world, _, _, owner, _ = session()
                reference, _, _, reference_owner, _ = session()
                for stream, conn in ((world, owner), (reference, reference_owner)):
                    stream._apply_event(wire.OP.MOVE_CAST, struct.pack('>ff6x', 40, 0), conn)
                world._load_tape = lambda: None
                world.tape_frames = []
                world.wave_t0 = 0
                world.ready_clients.add(owner)
                world._jungle_published = True
                world.emit_hero_1010 = False
                world.trace_movement_ticks = True
                clock, starts, waits, records = [0.0], [], [], []
                original = world.advance_simulation

                def advance():
                    starts.append(clock[0])
                    original()
                    clock[0] += first_work if len(starts) == 1 else .012
                    if len(starts) == 20:
                        world._stop_event.set()

                def log(line):
                    if line.startswith('[movement-tick] '):
                        records.append(json.loads(line.split(' ', 1)[1]))
                        clock[0] += .008  # costs time but is outside work_ms

                def pump(timeout):
                    waits.append(timeout)
                    clock[0] += timeout

                world.advance_simulation, world._pump, world.log = advance, pump, log
                with patch('server.match_server.time.monotonic', side_effect=lambda: clock[0]):
                    world._run_world()
                for _ in range(20):
                    reference.advance_simulation()
                self.assertEqual(len(starts), 20)
                self.assertEqual((world.sim_tick, world.sim_time), (20, 1.0))
                self.assertEqual(world.hero_sims[1500].position_fixed,
                                 reference.hero_sims[1500].position_fixed)
                self.assertTrue(all(0 <= wait <= .05 for wait in waits))
                # The overrun is caught up with individual 50 ms simulation
                # steps; the scheduler recovers without dropping ticks.
                for index in range(4, 20):
                    self.assertAlmostEqual(starts[index], (index + 1) * .05)
                if first_work > .05:
                    self.assertAlmostEqual(starts[1], .178)
                    self.assertGreater(records[1]['late_ms'], 70)
                else:
                    self.assertAlmostEqual(starts[1], .100)
                self.assertAlmostEqual(records[-1]['work_ms'], 12)

    def test_other_actor_echo_does_not_ack_owner_and_projection_is_measured(self):
        rows = [row(1, 10, 'c2s', 1012, struct.pack('>ff6x', 40, 0)),
                row(2, 10.001, 's2c', 1016, struct.pack('>Bff5x', 1, 40, 0)),
                row(3, 10.003, 's2c', 1016, struct.pack('>Bff5x', 0, 30, 0)),
                row(4, 11, 's2c', 1070, struct.pack('>Iff2x', 1517, 30, 0)),
                row(5, 12, 's2c', 1070, struct.pack('>Iff2x', 1500, 30, 0))]
        result = timing_report(rows, 1500, 0)['requests'][0]
        self.assertAlmostEqual(result['ack']['delay_s'], .003)
        self.assertEqual(result['requested_to_accepted_distance'], 10)
        self.assertEqual(result['arrival_after_input_s'], 2)
        self.assertEqual(result['sample_count'], 1)

    def test_retarget_prevents_later_arrival_being_attributed_to_prior_order(self):
        rows = [row(1, 0, 'c2s', 1012, struct.pack('>ff6x', 10, 0)),
                row(2, .01, 's2c', 1016, struct.pack('>Bff5x', 0, 10, 0)),
                row(3, .2, 'c2s', 1012, struct.pack('>ff6x', 20, 0)),
                row(4, .3, 's2c', 1070, struct.pack('>Iff2x', 1500, 10, 0))]
        first, second = timing_report(rows, 1500, 0)['requests']
        self.assertEqual(first['end_reason'], 'next_client_intent')
        self.assertIsNone(first['arrival_after_input_s'])
        self.assertIsNone(second['ack'])
        self.assertIsNone(second['arrival_after_input_s'])

    def test_client_interface_timing_is_not_mislabeled_as_server_receipt(self):
        rows = [row(1, 10, 'c2s', 1012, struct.pack('>ff6x', 10, 0)),
                row(2, 10.12, 's2c', 1016, struct.pack('>Bff5x', 0, 10, 0))]
        for record in rows:
            record['time_source'] = 'client-interface capture + measured host offset'
        report = timing_report(rows, 1500, 0)
        self.assertIn('client-interface', report['limits'][1])
        self.assertAlmostEqual(report['requests'][0]['ack']['delay_s'], .12)
        with self.assertRaisesRegex(ValueError, 'requires server-side'):
            correlate_ticks(report, Path('must-not-read-a-local-server-log'))
        rows[0].pop('time_source')
        with self.assertRaisesRegex(ValueError, 'mixed wire timestamp'):
            timing_report(rows, 1500, 0)
        for record in rows:
            record['time_source'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'unknown wire timestamp'):
            timing_report(rows, 1500, 0)


class TickCorrelationTests(unittest.TestCase):
    def tick(self, number, wall, x, *, match='match', order=1):
        return {'match_id': match, 'tick': number, 'sim_time': number * .05,
                'wall_time': wall, 'started_monotonic': wall - 100 - .002,
                'late_ms': 0, 'work_ms': 2,
                'heroes': [{'eid': 1500, 'position_fixed': [round(x * 1_000_000), 0],
                            'moving': True, 'target': [10, 0], 'order_version': order}]}

    def report(self):
        return timing_report([
            row(1, 101, 'c2s', 1012, struct.pack('>ff6x', 10, 0)),
            row(2, 101.001, 's2c', 1016, struct.pack('>Bff5x', 0, 10, 0)),
            row(3, 101.002, 's2c', 1070, struct.pack('>Iff2x', 1500, 0, 0)),
            row(4, 101.049, 's2c', 1070, struct.pack('>Iff2x', 1500, .185, 0)),
            row(5, 101.11, 'c2s', 1041, bytes(6)),
        ], 1500, 0)

    def correlate(self, ticks, *, match=None, partial=False):
        with tempfile.TemporaryDirectory(prefix='halcyon-tick-correlation-') as folder:
            path = Path(folder) / 'server.log'
            path.write_text('unrelated server message\n' + ''.join(
                '[12:00:00] [movement-tick] ' + json.dumps(t) + '\n' for t in ticks)
                + ('[movement-tick] {"tick":' if partial else ''), encoding='utf-8')
            return correlate_ticks(self.report(), path, match)

    def test_positions_match_previous_or_following_tick_in_float32(self):
        ticks = [self.tick(1, 100.999, 0), self.tick(2, 101.05, .185), self.tick(3, 101.1, .37)]
        result = self.correlate(ticks, partial=True)
        self.assertEqual(result['publication']['matched'], [{'line': 3, 'ticks': [1]}, {'line': 4, 'ticks': [2]}])
        self.assertEqual(result['publication']['unmatched_lines'], [])
        self.assertEqual(result['missing_tick_count'], 0)
        self.assertTrue(result['incomplete_trailing_tick'])
        self.assertAlmostEqual(result['requests'][0]['moving_step_units']['max'], .185)

    def test_absent_ticks_are_not_interpolated_and_wrong_position_is_unmatched(self):
        result = self.correlate([self.tick(1, 100.999, 0), self.tick(3, 101.1, .37)])
        self.assertEqual(result['missing_tick_count'], 1)
        self.assertEqual(result['publication']['unbracketed_lines'], [3, 4])
        self.assertEqual(result['requests'][0]['moving_step_units']['count'], 0)
        result = self.correlate([self.tick(1, 100.999, 0), self.tick(2, 101.05, .3)])
        self.assertEqual(result['publication']['unmatched_lines'], [4])

    def test_locale_encoded_prose_is_ignored_but_invalid_tick_bytes_are_rejected(self):
        ticks = [self.tick(1, 100.999, 0), self.tick(2, 101.05, .185)]
        with tempfile.TemporaryDirectory(prefix='halcyon-tick-encoding-') as folder:
            path = Path(folder) / 'server.log'
            body = b'Windows prose \x97 not telemetry\n' + b''.join(
                b'prefix \x97 [movement-tick] ' + json.dumps(t).encode() + b'\n' for t in ticks)
            path.write_bytes(body)
            self.assertEqual(len(correlate_ticks(self.report(), path)['publication']['matched']), 2)
            path.write_bytes(body + b'[movement-tick] {"match_id":"\x97"}\n')
            with self.assertRaisesRegex(ValueError, 'invalid movement tick'):
                correlate_ticks(self.report(), path)

    def test_unrelated_matches_and_reused_identity_resets_cannot_be_merged(self):
        ticks = [self.tick(1, 100.999, 0), self.tick(1, 101.02, 0, match='other'),
                 self.tick(2, 101.05, .185)]
        with self.assertRaisesRegex(ValueError, 'expected one match'):
            self.correlate(ticks)
        self.assertEqual(len(self.correlate(ticks, match='match')['publication']['matched']), 2)
        with self.assertRaisesRegex(ValueError, 'reset/overlap'):
            self.correlate([self.tick(2, 100.999, 0), self.tick(1, 101.05, .185)])

    def test_retarget_step_and_clock_reversal_do_not_become_movement_evidence(self):
        result = self.correlate([self.tick(1, 100.999, 0), self.tick(2, 101.05, .185),
                                 self.tick(3, 101.1, 20, order=2)])
        self.assertEqual(result['requests'][0]['moving_step_units']['count'], 0)
        with self.assertRaisesRegex(ValueError, 'clock reversal'):
            self.correlate([self.tick(1, 101.01, 0), self.tick(2, 101.0, .185)])


if __name__ == '__main__':
    unittest.main()

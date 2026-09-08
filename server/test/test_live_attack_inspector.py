"""Trace audit must preserve observation boundaries and avoid false hit joins."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from Tools.Teardown.inspect_live_attack import inspect, read_rows


def row(time, direction, opcode, payload, connection=1):
    return {'time': time, 'direction': direction, 'opcode': opcode,
            'payload': payload.hex(), 'decoded': payload, 'connection': connection}


def target(time, eid=1517):
    return row(time, 'c2s', 1060, struct.pack('>IH', eid, 0))


def attack(time, action=8):
    return row(time, 's2c', 1045, struct.pack('>IIB5x', 1500, 1517, action))


def move(time):
    return row(time, 'c2s', 1012, struct.pack('>ff6x', -2, 3))


def hit(time, dtype=0, source=1500, victim=1517, delta=-60):
    return row(time, 's2c', 1054, struct.pack('>IIfBBB5x', victim, source, delta, 0, 5, dtype))


def position(time, eid, x, y):
    return row(time, 's2c', 1070, struct.pack('>Iff2x', eid, x, y))


def report(rows, **kwargs):
    rows = [{**value, 'line': index} for index, value in enumerate(rows, 1)]
    return inspect(rows, 1500, hero_id=395, **kwargs)


class LiveAttackInspectorTests(unittest.TestCase):
    def test_move_before_hit_keeps_exact_actor_order_damage_type_and_position_age(self):
        result = report([position(0, 1500, 0, 0), position(0.1, 1517, 4, 0),
            target(1), attack(1.1), position(1.101, 1500, 0.5, 0), move(1.2),
            hit(1.3, source=1517, victim=1500), hit(1.31, victim=2000),
            hit(1.32, delta=10), hit(1.4), hit(1.401, dtype=4), target(2)])
        candidate, = result['candidates']
        self.assertTrue(candidate['candidate_move_before_hit'])
        self.assertFalse(candidate['candidate_windup_cancel'])
        self.assertEqual(candidate['target_intent']['line'], 3)
        self.assertEqual(candidate['attack_start']['action_id'], 8)
        self.assertEqual(candidate['attack_start']['source_position']['xy'], [0, 0])
        self.assertEqual(candidate['attack_start']['source_position']['age_seconds'], 1.1)
        self.assertEqual(candidate['attack_start']['immediate_source_position_echo']['xy'], [0.5, 0])
        self.assertEqual([hit['line'] for hit in candidate['following_damage']], [10, 11])
        self.assertEqual([hit['damage_fields'] for hit in candidate['following_damage']], [[0, 5, 0], [0, 5, 4]])
        self.assertEqual([hit['ordinary_damage_candidate'] for hit in candidate['following_damage']], [True, False])
        self.assertEqual(candidate['observation_end']['line'], 12)

    def test_new_intent_bounds_no_hit_window_and_prevents_later_hit_attribution(self):
        result = report([target(1), attack(1.1, 9), move(1.2), target(1.3), hit(1.4)])
        candidate, = result['candidates']
        self.assertTrue(candidate['candidate_windup_cancel'])
        self.assertFalse(candidate['candidate_move_before_hit'])
        self.assertEqual(candidate['following_damage'], [])
        self.assertEqual(candidate['observation_end']['reason'], 'next_player_intent')
        self.assertAlmostEqual(candidate['seconds_observed_after_move'], 0.1)

    def test_proc_only_does_not_count_as_ordinary_hit_and_new_action_bounds_window(self):
        result = report([target(1), attack(1.1), move(1.2), hit(1.25, dtype=4),
                         attack(1.4, 9), hit(1.5)])
        first, second = result['action_examples']
        self.assertTrue(first['candidate_windup_cancel'])
        self.assertFalse(first['candidate_move_before_hit'])
        self.assertEqual(first['observation_end']['reason'], 'next_source_action')
        self.assertEqual([hit['damage_type'] for hit in first['following_damage']], [4])
        self.assertEqual([hit['time'] for hit in second['following_damage']], [1.5])

    def test_move_before_attack_start_is_distinct_and_zero_observation_is_inconclusive(self):
        result = report([target(1), move(1.01), target(1.3), attack(1.4), move(1.5)])
        early, = result['moves_before_attack_start']
        self.assertTrue(early['candidate_cancel_before_attack_start'])
        self.assertAlmostEqual(early['seconds_observed_after_move'], 0.29)
        self.assertEqual(result['counts']['windup_cancel_candidates'], 0)
        self.assertFalse(result['action_examples'][0]['candidate_windup_cancel'])

    def test_movement_after_damage_and_nonordinary_action_cannot_prove_stutter(self):
        recovery = report([target(1), attack(1.1), hit(1.2), move(1.3), target(2)])
        self.assertEqual(recovery['candidates'], [])
        special = report([target(1), attack(1.1, 3), move(1.2), hit(1.3), target(2)])
        self.assertEqual(special['candidates'], [])
        self.assertFalse(special['action_examples'][0]['attack_start']['known_ordinary_action'])

    def test_time_limit_and_selected_start_lines_do_not_discard_position_history(self):
        result = report([position(0, 1500, 2, 3), target(1), attack(1.1), move(1.2),
                         hit(2), target(3)], seconds=0.5, from_line=3, to_line=3)
        candidate, = result['candidates']
        self.assertEqual(candidate['following_damage'], [])
        self.assertEqual(candidate['observation_end']['reason'], 'time_limit')
        self.assertEqual(candidate['observation_end']['time'], 1.6)
        self.assertEqual(candidate['attack_start']['source_position']['xy'], [2, 3])

    def test_reader_requires_connection_and_reports_incomplete_tail_without_rewriting(self):
        rows = [target(1), {**target(2), 'connection': 2}]
        raw = b''.join((json.dumps({key: value for key, value in entry.items() if key != 'decoded'}) + '\n').encode()
                       for entry in rows) + b'{"time":3'
        with tempfile.TemporaryDirectory(prefix='halcyon-attack-inspector-') as temporary:
            path = Path(temporary) / 'synthetic.jsonl'
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'select --connection'):
                read_rows(path)
            selected, connection, incomplete = read_rows(path, 2)
            self.assertEqual(connection, 2)
            self.assertTrue(incomplete)
            self.assertEqual([value['line'] for value in selected], [2])
            self.assertEqual(path.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()

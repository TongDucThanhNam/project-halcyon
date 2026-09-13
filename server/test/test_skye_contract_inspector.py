"""Synthetic evidence checks: do not infer causality across owners or lifetimes."""
import io
import pickle
import struct
import unittest

from server.buff_wire import build_buff_add
from Tools.Teardown.inspect_skye_c_contract import (
    PlainDataUnpickler, VOLLEY_CLASS, audit_frames,
)


def spawn(eid=100, owner=1):
    body = bytearray(126)
    struct.pack_into('>III', body, 0, 384, VOLLEY_CLASS, eid)
    struct.pack_into('>I', body, 112, owner)
    return 1010, bytes(body)


def buff(kind, target=100, source=1):
    return 1086, build_buff_add(target, source, .1, 999, kind)


def damage(target=2, source=1, tag=394):
    return 1054, struct.pack('>IIfHBB', target, source, -25, tag, 1, 0)


def end(opcode, eid=100):
    return opcode, struct.pack('>I', eid)


def audit(frames):
    return audit_frames(frames, [('synthetic', i) for i in range(len(frames))])


class TestSkyeContractInspector(unittest.TestCase):
    def test_pairing_filters_owner_victim_and_damage_tag(self):
        result = audit([spawn(), buff(613), buff(618, target=2),
                        damage(source=3), damage(target=4), damage(tag=5), damage(),
                        end(1072), end(1073), end(1035)])
        self.assertEqual(result['hit_marker_associations'][0]['candidate_damage_frames'], [6])
        self.assertEqual(result['summary']['uniquely_bracketed_damage'], 1)
        self.assertEqual(result['summary']['complete_lifecycles'], 1)
        self.assertEqual(result['tag394_records'][-1]['byte14'], 1)

    def test_damage_after_field_death_cannot_pair_with_earlier_marker(self):
        result = audit([spawn(), buff(618, target=2), damage(),  # before activation
                        buff(613), buff(618, target=2), end(1072), damage(),
                        buff(618, target=2), damage()])  # after death
        self.assertEqual(result['summary']['uniquely_bracketed_damage'], 0)
        markers = result['hit_marker_associations']
        self.assertEqual([m['candidate_fields'] for m in markers], [[], [100], []])
        self.assertEqual(markers[1]['candidate_damage_frames'], [])

    def test_overlapping_fields_remain_ambiguous_until_one_dies(self):
        result = audit([spawn(100), buff(613, 100), spawn(101), buff(613, 101),
                        buff(618, target=2), damage(), end(1072, 100),
                        buff(618, target=2), damage()])
        markers = result['hit_marker_associations']
        self.assertEqual(markers[0]['candidate_fields'], [100, 101])
        self.assertEqual(markers[1]['candidate_fields'], [101])
        self.assertEqual(result['summary']['uniquely_bracketed_damage'], 1)

    def test_released_identity_does_not_join_damage_from_later_incarnation(self):
        result = audit([spawn(), buff(613), buff(618, target=2),
                        end(1072), end(1073), end(1035),
                        spawn(), buff(613), damage()])
        self.assertEqual(result['summary']['volley_count'], 2)
        self.assertEqual(result['summary']['uniquely_bracketed_damage'], 0)
        self.assertEqual(result['hit_marker_associations'][0]['candidate_damage_frames'], [])

    def test_multiple_damage_records_are_not_collapsed_into_one_proven_hit(self):
        result = audit([spawn(), buff(613), buff(618, target=2), damage(), damage()])
        self.assertEqual(result['hit_marker_associations'][0]['candidate_damage_frames'], [3, 4])
        self.assertEqual(result['summary']['uniquely_bracketed_damage'], 0)

    def test_cache_refuses_globals_and_missing_origins(self):
        with self.assertRaises(ValueError):
            PlainDataUnpickler(io.BytesIO(pickle.dumps(eval))).load()
        with self.assertRaises(ValueError):
            audit_frames([spawn()], [])


if __name__ == '__main__':
    unittest.main()

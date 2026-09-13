"""Recall's paired buffs, cancellation, completion and own-corpus goldens."""
import struct
import unittest

from server.paths import research_dir
from server import buff_wire, decode, recall_wire
from server.status_effects import StatusManager


class RecallPresentationTests(unittest.TestCase):
    def setUp(self):
        self.status = StatusManager()
        self.recall = recall_wire.RecallPresentation(self.status)

    def test_start_and_reconnect_keep_two_native_instances(self):
        state = self.recall.start(1500, 10)
        adds = self.status.drain_frames()
        self.assertEqual([op for op, _ in adds], [1086, 1086])
        values = [struct.unpack_from('>IIeIH', payload) for _, payload in adds]
        self.assertEqual(values, [(1500, 1500, 4.0, state.withdraw_instance, 25),
                                  (1500, 1500, 4.0, state.ping_instance, 26)])
        self.assertEqual(self.recall.start(1500, 10), state)
        self.assertEqual(self.status.drain_frames(), [])
        snapshot = [struct.unpack_from('>IIeIH', payload) for _, payload in self.status.snapshot_frames(11)]
        self.assertEqual([row[2:] for row in snapshot], [(3.0, state.withdraw_instance, 25),
                                                        (3.0, state.ping_instance, 26)])

    def test_early_cancel_removes_both_without_trigger_or_return(self):
        state = self.recall.start(1500, 10)
        self.status.drain_frames()
        self.assertTrue(self.recall.cancel(1500, 10.2))
        frames = self.status.drain_frames()
        self.assertEqual(frames, [(1093, buff_wire.build_buff_cancel(1500, state.withdraw_instance)),
                                   (1093, buff_wire.build_buff_cancel(1500, state.ping_instance))])
        self.assertEqual(self.recall.complete(1500, 14), [])

    def test_success_keeps_trigger_after_natural_buff_expiry_and_runs_once(self):
        state = self.recall.start(1500, 10)
        self.status.drain_frames()
        self.status.clean_expired(14)
        frames = self.recall.complete(1500, 14, x=-78.18, y=0.88,
                                      effect_height=1.3, relocation_height=1.267)
        self.assertEqual([op for op, _ in frames], [1094, 1049, 1033])
        self.assertEqual(frames[0][1], recall_wire.build_recall_trigger(1500, state.withdraw_instance))
        self.assertEqual(frames[-1][1][16:], bytes(6))
        self.assertEqual(self.status.drain_frames(), [])
        self.assertEqual(self.recall.complete(1500, 14), [])

    def test_early_or_partial_completion_cannot_consume_state(self):
        state = self.recall.start(1500, 10)
        with self.assertRaises(ValueError):
            self.recall.complete(1500, 13)
        with self.assertRaises(ValueError):
            self.recall.complete(1500, 14, x=1, y=1)
        self.assertEqual(self.recall.active[1500], state)

    def test_catherine_complete_and_other_hero_move_cancel_match_raw_vgr(self):
        base = research_dir('vg_phaseB') / 'vgr_live'
        prefix = 'ea4c7fda-4b61-481d-abb7-1c757d24ae58-'
        complete = base / f'{prefix}1574e27a-e851-492b-8d91-94fc4bd66985.18.vgr'
        cancel = base / f'{prefix}f58e0359-8d83-4994-a33c-217cf863144b.27.vgr'
        if not complete.exists() or not cancel.exists():
            self.skipTest('operator-owned Recall captures are not installed')
        frames, stats = decode.walk_vgr(str(complete))
        self.assertEqual(stats['failures'], 0)
        token, op, payload = frames[755]
        eid, source, duration, instance, kind = struct.unpack_from('>IIeIH', payload)
        self.assertEqual((op, eid, source, duration, kind), (1086, 1516, 1516, 4, 25))
        self.assertEqual(frames[1181][1:], (1094, recall_wire.build_recall_trigger(eid, instance)))
        effect = frames[1182][2]
        _, source, x, height, y = struct.unpack_from('>IIfff', effect)
        self.assertEqual((frames[1182][1], effect), (1049, recall_wire.build_return_effect(source, x, y, height)))
        relocation = frames[1183][2]
        source, x, height, y = struct.unpack_from('>Ifff', relocation)
        self.assertEqual((frames[1183][1], relocation), (1033, recall_wire.build_return_relocation(source, x, y, height)))
        frames, stats = decode.walk_vgr(str(cancel))
        self.assertEqual(stats['failures'], 0)
        for start, stop, kind in [(300, 312, 25), (301, 314, 26)]:
            token, op, payload = frames[start]
            eid, source, duration, instance, actual_kind = struct.unpack_from('>IIeIH', payload)
            self.assertEqual((op, duration, actual_kind), (1086, 4, kind))
            self.assertEqual(frames[stop][1:], (1093, buff_wire.build_buff_cancel(eid, instance)))
        self.assertEqual(frames[313][1], 1016)

    def test_phinn_return_uses_same_trigger_effect_and_flag_zero_relocation(self):
        base = research_dir('vg_max') / 'vgr5b'
        matches = [p for p in base.glob('*-045f86d4-7ef2-4125-a835-e70a96288c88.47.vgr')]
        if not matches:
            self.skipTest('operator-owned Phinn VGR is not installed')
        frames, stats = decode.walk_vgr(str(matches[0]))
        self.assertEqual(stats['failures'], 0)
        eid, _, duration, instance, kind = struct.unpack_from('>IIeIH', frames[378][2])
        self.assertEqual((eid, duration, kind), (1500, 4, 25))
        self.assertEqual(frames[618][1:], (1094, recall_wire.build_recall_trigger(eid, instance)))
        effect, relocation = frames[619][2], frames[620][2]
        _, eid, x, height, y = struct.unpack_from('>IIfff', effect)
        self.assertEqual(effect, recall_wire.build_return_effect(eid, x, y, height))
        eid, x, height, y = struct.unpack_from('>Ifff', relocation)
        self.assertEqual(relocation, recall_wire.build_return_relocation(eid, x, y, height))

    def test_successful_native_returns_restore_a_quarter_of_max_resources(self):
        base = research_dir('vg_phaseB') / 'vgr_live'
        cases = [('0e7de8af-96d9-4e3a-b3c2-609ed5e71120', 17, 1025),
                 ('f58e0359-8d83-4994-a33c-217cf863144b', 22, 1159)]
        for match, chunk, row in cases:
            files = list(base.glob(f'*-{match}.{chunk}.vgr'))
            if not files:
                self.skipTest('operator-owned resource-return VGR is not installed')
            frames, stats = decode.walk_vgr(str(files[0]))
            self.assertEqual(stats['failures'], 0)
            eid = struct.unpack_from('>I', frames[row][2])[0]
            block = next(p for _, op, p in frames[:row]
                         if op == 1011 and struct.unpack_from('>I', p, 8)[0] == eid)
            max_hp, max_energy = (struct.unpack_from('>f', block, offset)[0] for offset in (46, 126))
            heal = next(struct.unpack_from('>f', p, 8)[0] for _, op, p in frames[row:row + 7]
                        if op == 1054 and struct.unpack_from('>II', p) == (eid, eid))
            energy = next(struct.unpack_from('>f', p, 4)[0] for _, op, p in frames[row:row + 7]
                          if op == 1053 and struct.unpack_from('>I', p)[0] == eid and p[8] == 2)
            self.assertEqual(heal, max_hp * recall_wire.RECALL_RESOURCE_FRACTION)
            self.assertEqual(energy, max_energy * recall_wire.RECALL_RESOURCE_FRACTION)

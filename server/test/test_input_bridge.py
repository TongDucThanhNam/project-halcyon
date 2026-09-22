"""A fast transport must not silently repeat or misattribute ordinary input."""
import io
import queue
import unittest
from unittest.mock import Mock

from Tools.input_bridge import InputBridge


class InputBridgeTests(unittest.TestCase):
    def bridge(self):
        bridge = InputBridge(Mock(), 'not-used.dex', 'not-used.jsonl')
        bridge.process = Mock(stdin=io.StringIO())
        bridge.journal = io.StringIO()
        return bridge

    def test_exact_sequence_and_no_fallback_after_wrong_receipt(self):
        bridge = self.bridge()
        bridge.lines.put('DONE 2 100 101')
        with self.assertRaises(RuntimeError):
            bridge.tap(480, 270)
        self.assertEqual(bridge.process.stdin.getvalue(), '1 T 480 270\n')
        bridge.adb.tap.assert_not_called()
        self.assertIn('"event":"attempt"', bridge.journal.getvalue())
        self.assertNotIn('"event":"done"', bridge.journal.getvalue())

    def test_bounds_and_duration_fail_before_any_input(self):
        for args in ((-1,20), (960,20), (20,540), (20,float('nan'))):
            bridge = self.bridge()
            with self.subTest(args=args), self.assertRaises(ValueError):
                bridge.tap(*args)
            self.assertEqual(bridge.process.stdin.getvalue(), '')
        bridge = self.bridge()
        with self.assertRaises(ValueError):
            bridge.swipe(1,2,3,4,duration_ms=10000)
        self.assertEqual(bridge.process.stdin.getvalue(), '')

    def test_receipts_are_transport_evidence_not_game_ack(self):
        bridge = self.bridge()
        bridge.lines.put('DONE 1 100 105')
        bridge.tap(480,270)
        self.assertIn('"guest_started_ns":100', bridge.journal.getvalue())
        self.assertIn('"guest_ended_ns":105', bridge.journal.getvalue())
        self.assertNotIn('PASS', bridge.journal.getvalue())
        bridge.lines.put(None)
        with self.assertRaises(RuntimeError):
            bridge.ping()


if __name__ == '__main__':
    unittest.main()

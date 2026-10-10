"""Dual-guest startup cannot mask either guest's routing failure."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from server.platform import live_up


class LiveUpTests(unittest.TestCase):
    def run_guests(self, results):
        with tempfile.TemporaryDirectory() as directory:
            with (patch.object(live_up, "_running_pids", return_value=[]),
                  patch.object(live_up, "_ports_listening", return_value=True),
                  patch.object(live_up.local_stack, "_answers", return_value={}),
                  patch.object(live_up.local_stack, "STACK_DIR", str(Path(directory))),
                  patch.object(live_up.subprocess, "Popen", return_value=Mock(pid=123)),
                  patch.object(live_up.subprocess, "CREATE_NEW_PROCESS_GROUP", 0, create=True),
                  patch.object(live_up.subprocess, "DETACHED_PROCESS", 0, create=True),
                  patch.object(live_up.guest_setup, "main", side_effect=results) as setup):
                rc = live_up.main(["--serial", "emulator-5554", "--device-serial", "emulator-5556"])
                self.assertEqual(setup.call_count, 2, "try both guests even if the first fails")
                self.assertEqual(setup.call_args_list[0].args[0][:2], ["--serial", "emulator-5554"])
                self.assertEqual(setup.call_args_list[1].args[0][:2], ["--serial", "emulator-5556"])
                return rc

    def test_first_fails_second_succeeds(self):
        self.assertEqual(self.run_guests([2, 0]), 2)

    def test_first_succeeds_second_fails(self):
        self.assertEqual(self.run_guests([0, 3]), 3)

    def test_both_succeed(self):
        self.assertEqual(self.run_guests([0, 0]), 0)

"""Platform-stack FSM automation — unit tests against a scratch answers.json.

The client's `update` poll is its FSM driver (mobile leaf §match-entry):
boot must answer `menus`, joinLobby flips `playing` (+host/port), exitLobby
returns `menus`. These tests pin the answers.json rewrites only — no
sockets, no adb.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.platform import local_stack


class TestFsm(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(prefix="halcyon-fsm-", suffix=".json")
        os.close(fd)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"update": {"code": 0,
                                  "returnValue": {"state": "playing",
                                                  "host": "127.0.0.1",
                                                  "port": 9999}},
                       "joinLobby": {"code": 0, "returnValue": {}},
                       "_gw_port": 7102}, fh)
        self.addCleanup(os.unlink, self.path)

    def _update(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)["update"]["returnValue"]

    def _with_auto(self, enabled):
        patcher = mock.patch.object(local_stack, "_answers",
                                    return_value={"_fsm_auto": enabled})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_boot_resets_stale_playing_to_menus(self):
        local_stack.fsm_on_boot(answers_path=self.path, gw_port=7102)
        self.assertEqual(self._update(), {"state": "menus"})

    def test_join_lobby_flips_playing_with_gateway_port(self):
        local_stack.fsm_on_boot(answers_path=self.path)
        local_stack.fsm_on_rpc("joinLobby", answers_path=self.path,
                               gw_port=7102)
        upd = self._update()
        self.assertEqual(upd["state"], "playing")
        self.assertEqual(upd["host"], "127.0.0.1")
        self.assertEqual(upd["port"], 7102)          # the real gateway port
        self.assertEqual(upd["matchId"], local_stack.MATCH_ID)

    def test_exit_lobby_returns_to_menus(self):
        local_stack.fsm_on_rpc("joinLobby", answers_path=self.path,
                               gw_port=7102)
        local_stack.fsm_on_rpc("exitLobby", answers_path=self.path)
        self.assertEqual(self._update(), {"state": "menus"})

    def test_other_rpc_methods_do_not_touch_the_state(self):
        before = self._update()
        for method in ("update", "getPlayerInfo", "queryPendingMatch",
                       "acceptMatch", "startSessionForPlayer"):
            local_stack.fsm_on_rpc(method, answers_path=self.path,
                                   gw_port=7102)
        self.assertEqual(self._update(), before)

    def test_fsm_auto_false_disables_every_transition(self):
        self._with_auto(False)
        before = self._update()
        local_stack.fsm_on_boot(answers_path=self.path)
        local_stack.fsm_on_rpc("joinLobby", answers_path=self.path,
                               gw_port=7102)
        self.assertEqual(self._update(), before)

    def test_join_lobby_port_falls_back_to_answers_gw_port(self):
        local_stack.fsm_on_rpc("joinLobby", answers_path=self.path,
                               gw_port=None)         # no explicit port → _gw_port
        self.assertEqual(self._update()["port"], 7102)

    def test_other_answer_rows_survive_the_rewrite(self):
        local_stack.fsm_on_rpc("joinLobby", answers_path=self.path,
                               gw_port=7102)
        with open(self.path, encoding="utf-8") as fh:
            answers = json.load(fh)
        self.assertEqual(answers["joinLobby"], {"code": 0, "returnValue": {}})
        self.assertEqual(answers["_gw_port"], 7102)


if __name__ == "__main__":
    unittest.main()

"""Tests use synthetic JSON and code-site bytes, never shipped game payloads."""
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest

from repair_pc_menu_answers import repair_answers, write_answers
from repack_ftol_edx import A_CALL, B_CALL, CAVE, HELPER, patch_dates, rva2off


class ReplyRepairTests(unittest.TestCase):
    def baseline(self):
        return {
            "getSkinManifest": {"code": 0, "returnValue": {"skins": {}}},
            "getBuffManifest": {"code": 0, "returnValue": {"buffs": {}}},
            "getSeasonRewardsManifest": {
                "code": 0, "returnValue": {"season": 1, "rewards": []}},
            "friendListAll": {"code": 0, "returnValue": {"friends": []}},
            "startSessionForPlayer": {
                "code": 0, "returnValue": {"sessionToken": "test-token"}},
            "update": {"code": 0, "returnValue": {}},
            "_ws_push": False,
        }

    def test_wire_types_cache_preconditions_and_unrelated_replies(self):
        before = self.baseline()
        saved = copy.deepcopy(before)
        fixed = repair_answers(before, diagnostic_skins=True)
        self.assertEqual(before, saved)
        # The wire contains a string, whose contents form a second JSON document.
        wire = json.loads(json.dumps(fixed["getSkinManifest"]))
        self.assertIsInstance(wire["returnValue"], str)
        skin = json.loads(wire["returnValue"])
        self.assertTrue(skin["themes"])
        self.assertTrue(skin["skins"])
        self.assertFalse(skin["skins"][0]["visible"])
        self.assertFalse(skin["skins"][0]["obtainable"])
        for method in ("getBuffManifest", "getSeasonRewardsManifest"):
            self.assertEqual(json.loads(fixed[method]["returnValue"]),
                             before[method]["returnValue"])
        self.assertEqual(fixed["friendListAll"]["returnValue"]["pending"], [])
        self.assertEqual(fixed["friendListAll"]["returnValue"]["confirmed"], [])
        for key in ("startSessionForPlayer", "update", "_ws_push"):
            self.assertEqual(fixed[key], before[key])

    def test_preserves_existing_catalogue_and_friend_entries(self):
        data = repair_answers(self.baseline(), diagnostic_skins=True)
        skin = json.loads(data["getSkinManifest"]["returnValue"])
        skin["metadata"] = "operator-supplied"
        data["getSkinManifest"]["returnValue"] = json.dumps(skin)
        data["friendListAll"]["returnValue"]["pending"] = [{"uuid": "test-friend"}]
        fixed = repair_answers(data)
        self.assertEqual(json.loads(fixed["getSkinManifest"]["returnValue"]), skin)
        self.assertEqual(fixed["friendListAll"], data["friendListAll"])
        self.assertEqual(repair_answers(fixed), fixed)

    def test_requires_explicit_diagnostic_catalogue(self):
        with self.assertRaisesRegex(ValueError, "nonempty themes and skins"):
            repair_answers(self.baseline())

    def test_rejects_bad_reply_without_changing_input(self):
        data = self.baseline()
        data["friendListAll"]["returnValue"]["pending"] = {}
        before = copy.deepcopy(data)
        with self.assertRaisesRegex(ValueError, "pending must be an array"):
            repair_answers(data, diagnostic_skins=True)
        self.assertEqual(data, before)

    def test_backup_keeps_exact_previous_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            original = json.dumps(self.baseline(), indent=2).encode() + b"\r\n"
            path.write_bytes(original)
            repaired = repair_answers(self.baseline(), diagnostic_skins=True)
            backup = write_answers(path, original, repaired)
            self.assertEqual(backup.read_bytes(), original)
            self.assertEqual(json.loads(path.read_bytes()), repaired)

    def test_refuses_stale_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            path.write_bytes(b'{"newer":true}')
            with self.assertRaisesRegex(ValueError, "changed during repair"):
                write_answers(path, b"{}", {})
            self.assertEqual(path.read_bytes(), b'{"newer":true}')
            self.assertEqual(list(Path(directory).iterdir()), [path])


class DatePatchTests(unittest.TestCase):
    def synthetic_code_sites(self):
        data = bytearray(rva2off(CAVE) + 10)
        for site in (A_CALL, B_CALL):
            off = rva2off(site)
            data[off:off + 5] = b"\xe8" + struct.pack("<i", HELPER - site - 5)
        data[rva2off(CAVE):] = b"\xcc" * 10
        data[0xf07c3:0xf07c9] = bytes.fromhex("0f8e88000000")
        return bytes(data)

    def test_call_targets_and_watchdog_are_preserved(self):
        original = self.synthetic_code_sites()
        patched = patch_dates(original)
        self.assertEqual(len(patched), len(original))
        for site, target in ((A_CALL, CAVE), (B_CALL, CAVE), (CAVE, HELPER)):
            off = rva2off(site)
            self.assertEqual(patched[off], 0xe8)
            self.assertEqual(site + 5 + struct.unpack_from("<i", patched, off + 1)[0], target)
        self.assertEqual(patched[rva2off(CAVE) + 5:rva2off(CAVE) + 8], b"\x31\xd2\xc3")
        self.assertEqual(patched[0xf07c3:0xf07c9], original[0xf07c3:0xf07c9])
        # Every byte outside the three intended sites must be unchanged.
        restored = bytearray(patched)
        for site, size in ((A_CALL, 5), (B_CALL, 5), (CAVE, 8)):
            off = rva2off(site)
            restored[off:off + size] = original[off:off + size]
        self.assertEqual(restored, original)

    def test_refuses_used_cave_or_changed_call_site(self):
        for site in (A_CALL, B_CALL, CAVE):
            with self.subTest(site=site):
                changed = bytearray(self.synthetic_code_sites())
                changed[rva2off(site)] = 0x90
                with self.assertRaisesRegex(ValueError, "unexpected bytes"):
                    patch_dates(changed)


if __name__ == "__main__":
    unittest.main()

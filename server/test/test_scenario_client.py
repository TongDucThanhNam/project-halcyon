"""Scenario client driver tests: mock-validated stages and honest classification.

The driver's live phase (real ADB input against a rendered client) is a later
bounded validation. These tests exercise every classification decision with
fake adb/QA seams and a causally scripted wire trace: session staleness,
missing-input versus missing-acknowledgment, wrong-actor and basic-attack
exclusion, partial trace records, lock-to-cast sequencing, volley attribution,
capture failure, and argument refusals.
"""
import copy
import functools
import hashlib
import itertools
import json
import os
from pathlib import Path
from PIL import Image as PILImage
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import unittest.mock as mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Tools import scenario_client as sc
from server import jungle, match_server, roster, wire
from server import sandbox_qa as server_qa
from server.navigation import NavMesh

SKYE_EID = 1500
ENEMY_EID = 1517


def hex32(*values):
    return b"".join(struct.pack(">I", value) for value in values).hex()


def build_ground_cast_payload(action: int) -> str:
    return struct.pack(">fffBB", 4.0, 0.0, 35.0, action, 0).hex()


def build_position_event(eid: int, action: int) -> str:
    return (struct.pack(">IfIfB", eid, 4.0, 0, 35.0, action) + bytes(5)).hex()


COMBAT_DELTA_TAIL = bytes.fromhex("0005040000000000")
COMBAT_DELTA_HERO_TAIL = bytes.fromhex("0005000000000000")


def build_damage(victim: int, attacker: int, delta: float, *,
                 basic: bool = False) -> str:
    tail = COMBAT_DELTA_HERO_TAIL if basic else COMBAT_DELTA_TAIL
    return (struct.pack(">IIf", victim, attacker, delta) + tail).hex()


def build_lock(target: int, source: int, kind: int = 602) -> str:
    return (struct.pack(">IIeIH", target, source, 4.0, 77, kind) + bytes(6)).hex()


def build_entity_death(victim: int, killer: int) -> str:
    """s2c 1072 [u32 victim][u32 killer][6 pad] — the explicit death
    evidence a minion survivor claim is allowed to rest on."""
    return (struct.pack(">II", victim, killer) + bytes(6)).hex()


def build_timer(eid: int, tag: int) -> str:
    return (struct.pack(">IIfH", eid, tag, 12.0, 12) + bytes(8)).hex()


def build_volley_1010(owner: int, *, volley_class: int = sc.VOLLEY_CLASS) -> str:
    body = bytearray(126)
    struct.pack_into(">I", body, 0, 385)             # line archetype
    struct.pack_into(">I", body, 4, volley_class)
    struct.pack_into(">I", body, 8, 9000)            # volley eid
    struct.pack_into(">f", body, 12, 4.0)
    struct.pack_into(">f", body, 20, 35.0)
    struct.pack_into(">I", body, 112, owner)
    body[116] = 7
    return bytes(body).hex()


def build_basic_1037() -> str:
    return (struct.pack(">IIfHBBB", 9001, 0x77B4B72A, 0.0, 108, 3, 3, 9)
            + bytes(5)).hex()


class FakeAdb:
    """Records gestures; causally appends wire records to the fake trace."""

    def __init__(self, harness) -> None:
        self.harness = harness
        self.calls: list[tuple] = []
        self.fail_screencap = False

    def _emit(self, direction, opcode, payload: str) -> None:
        self.harness.emit({"time": time.time(), "direction": direction,
                           "connection": 424242, "opcode": opcode,
                           "payload": payload})

    def wm_size(self):
        self.calls.append(("wm_size",))
        return (960, 540)

    def tap(self, x, y):
        self.calls.append(("tap", x, y, time.time()))
        if self.harness.mode in ("skye-b", "skye-c"):
            self._emit("s2c", 1086, build_lock(ENEMY_EID, SKYE_EID))
            # a faithful basic = release (1037) then hit (1054)
            self._emit("s2c", 1037, build_basic_1037())
            self._emit("s2c", 1054,
                       build_damage(ENEMY_EID, SKYE_EID, -120.0, basic=True))

    def swipe(self, x1, y1, x2, y2, *, duration_ms=250):
        self.calls.append(("swipe", x1, y1, x2, y2, time.time()))
        self.harness.on_swipe()

    def client_version(self, package: str = sc.ANDROID_PACKAGE) -> dict:
        return {"version_name": "4.13.4", "version_code": 147219}

    def screencap(self, destination: Path):
        self.calls.append(("screencap", destination))
        if self.fail_screencap:
            raise RuntimeError("device detached")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Draw the enemy health bar the aim locator looks for, mirroring the
        # live HUD; a test can switch it off via harness.show_enemy_bar.
        from PIL import ImageDraw
        image = PILImage.new("RGB", (960, 540), (30, 40, 30))
        if getattr(self.harness, "show_enemy_bar", True):
            draw = ImageDraw.Draw(image)
            draw.rectangle([525, 100, 595, 107], fill=(190, 40, 40))
        image.save(destination)

    def start_screenrecord(self, device_path, *, time_limit):
        self.calls.append(("screenrecord", device_path, time_limit))
        return types.SimpleNamespace(poll=lambda: 0, terminate=lambda: None,
                                     kill=lambda: None, wait=lambda timeout=None: 0)

    def pull(self, device_path, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"mp4-fake")
        self.calls.append(("pull", device_path, destination))
        return {"path": str(destination), "bytes": destination.stat().st_size}


class FakeQa:
    """Snapshot schema faithful to server/sandbox_qa.SandboxQA.snapshot."""

    # production World derives sim_time from a fixed 20 Hz tick
    # (server/match_server.py: SIM_TICK = 0.05, sim_time = sim_tick * SIM_TICK)
    SIM_TICK = 0.05
    _NEXT_PID = itertools.count(4242)

    def __init__(self, harness) -> None:
        self.harness = harness
        # ONE live server process per trial: pid/startup_at are fresh-session
        # identity — distinct across trials, constant within a trial's two
        # endpoint receipts.
        self.pid = next(self._NEXT_PID)
        self.startup_at = 1.0 + self.pid
        self.state = {
            "diagnostic_fixture": True, "match_id": "qa-session", "phase": "world",
            "tick": 100, "time": 5.0, "match_finished": False,
            "heroes": [
                {"eid": SKYE_EID, "team": 1, "hero_id": 265, "x": 0.0, "y": 35.0,
                 "hp": 1200.0, "max_hp": 1200.0, "energy": 1000.0,
                 "max_energy": 1000.0, "alive": True, "target": None,
                 "ranks": {"0": 1, "1": 1, "2": 1}, "ability_cooldowns": {},
                 "gold": None, "xp": None, "level": 6, "ability_points": None,
                 "inventory": [], "item_cooldowns": {}, "default_items": [],
                 "statuses": []},
                {"eid": ENEMY_EID, "team": 2, "hero_id": 243, "x": 4.0, "y": 35.0,
                 "hp": 10000.0, "max_hp": 10000.0, "energy": 500.0,
                 "max_energy": 500.0, "alive": True, "target": None,
                 "ranks": {"0": 0, "1": 0, "2": 0}, "ability_cooldowns": {},
                 "gold": None, "xp": None, "level": 1, "ability_points": None,
                 "inventory": [], "item_cooldowns": {}, "default_items": [],
                 "statuses": []},
            ],
            "nearby_creatures": [], "structures": [],
        }
        self.snapshots = 0

    def submit(self, command, *, timeout=5.0, request_id=None):
        self.snapshots += 1
        name = command.get("command")
        if name == "snapshot":
            self.state["tick"] += 2
            self.state["time"] = self.state["tick"] * self.SIM_TICK
            return {"id": request_id, "tick": self.state["tick"],
                    "time": self.state["time"], "ok": True,
                    "result": json.loads(json.dumps(self.state))}
        if name == "teleport":
            for row in self.state["heroes"]:
                if row["eid"] == command["eid"]:
                    row["x"], row["y"] = command["x"], command["y"]
            return {"id": request_id, "ok": True, "result": {"eid": command["eid"]}}
        if name == "diagnostics":
            # A live-stack receipt reflects the world AT READ TIME: the
            # linkage fields come from this fake's own state (the same state
            # the snapshot command serves), so an endpoint receipt is later
            # because the fake world actually advanced, never because a
            # "successful" value was inserted after the fact.
            return {"id": request_id, "ok": True,
                    "result": {"pid": self.pid, "startup_at": self.startup_at,
                               "source_startup_digest": "f" * 64,
                               "source_current_digest": "f" * 64,
                               "source_unchanged_since_startup": True,
                               "tape_loaded": {"records": 1458,
                                               "sha256": "d" * 64},
                               "tape_file_identity": {"path": "tape.bin",
                                                      "file_sha256": "e" * 64},
                               "env": {"HALCYON_NO_BOTS": "1"},
                               "match_id": self.state["match_id"],
                               "phase": self.state["phase"],
                               "match_finished": self.state["match_finished"],
                               "tick": self.state["tick"],
                               "time": self.state["time"]}}
        if name == "resources":
            # Resources is the production QA preparation step the writer
            # runs BEFORE measuring the manifest. Production
            # SandboxQA.pump(resources) creates an economy for the actor
            # and exposes ability_points=1, gold=600.0, xp=0.0; the
            # writer validates AFTER this preparation. Mirror that shape
            # here so the measured state matches the production
            # prepared state — unknown/missing pre-preparation stays
            # honest because that snapshot is captured before the
            # resources call.
            for row in self.state["heroes"]:
                if row["eid"] == command["eid"]:
                    if "hp" in command:
                        row["hp"] = min(command["hp"], row["max_hp"])
                    if "energy" in command:
                        row["energy"] = min(command["energy"], row["max_energy"])
                    # production resources creates the economy on the
                    # targeted hero
                    if row.get("ability_points") is None:
                        row["ability_points"] = 1
                    if row.get("gold") is None:
                        row["gold"] = 600.0
                    if row.get("xp") is None:
                        row["xp"] = 0.0
            return {"id": request_id, "ok": True, "result": {"eid": command["eid"]}}
        if name == "learn":
            return {"id": request_id, "ok": True,
                    "result": {"eid": command["eid"], "slot": command["slot"],
                               "rank": 1, "level": 6, "xp_granted": 0,
                               "extra_points_granted": 0}}
        return {"id": request_id, "ok": False, "error": "unsupported in fake"}


class Harness:
    """One fake session: trace file, adb, qa, driver."""

    def __init__(self, mode="skye-b", *, castle=False):
        self.mode = mode
        self.base = Path(tempfile.mkdtemp(prefix="halcyon-client-test-"))
        self.trace_path = self.base / "wire-fake.jsonl"
        self.trace_path.write_text("", encoding="ascii")
        self.records = 0
        self.show_enemy_bar = True
        self.on_swipe = self._default_swipe
        self.adb = FakeAdb(self)
        self.qa = FakeQa(self)
        self.cast_emitted = False
        # A live session's trace already carries traffic before the driver
        # starts; model that with one fresh bootstrap record.
        self.emit({"time": time.time(), "direction": "s2c", "connection": 424242,
                   "opcode": 1010, "payload": build_volley_1010(SKYE_EID,
                                                                volley_class=7)})

    def emit(self, record: dict) -> None:
        with self.trace_path.open("a", encoding="ascii") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")

    def emit_partial(self, text: str) -> None:
        with self.trace_path.open("a", encoding="ascii") as stream:
            stream.write(text)

    def _default_swipe(self):
        action = {"skye-a": 0, "skye-b": 2, "skye-c": 4}[self.mode]
        self.emit({"time": time.time(), "direction": "c2s", "connection": 424242,
                   "opcode": 1042, "payload": build_ground_cast_payload(action)})
        if self.mode == "skye-b" and not self.cast_emitted:
            # an unrelated basic during the window + wrong-actor damage
            self.emit({"time": time.time(), "direction": "s2c",
                       "connection": 424242, "opcode": 1037,
                       "payload": build_basic_1037()})
            self.emit({"time": time.time(), "direction": "s2c",
                       "connection": 424242, "opcode": 1054,
                       "payload": build_damage(ENEMY_EID, SKYE_EID, -88.0,
                                                basic=True)})
            self.emit({"time": time.time(), "direction": "s2c",
                       "connection": 424242, "opcode": 1054,
                       "payload": build_damage(ENEMY_EID, 3545, -60.0)})   # turret hit
            self.emit({"time": time.time(), "direction": "s2c",
                       "connection": 424242, "opcode": 1054,
                       "payload": build_damage(4610, SKYE_EID, -40.0)})    # hero PvE
        self.emit({"time": time.time(), "direction": "s2c", "connection": 424242,
                   "opcode": 1046,
                   "payload": build_position_event(SKYE_EID, action)})
        tag = sc.SKYE_COOLDOWN_TAGS[{"skye-a": "A", "skye-b": "B", "skye-c": "C"}[self.mode]]
        self.emit({"time": time.time(), "direction": "s2c", "connection": 424242,
                   "opcode": 1162, "payload": build_timer(SKYE_EID, tag)})
        # ability projectiles need travel time; without a real gap the
        # missiles would be inseparable from the basic hit they follow
        time.sleep(0.65)
        if self.mode == "skye-c":
            self.emit({"time": time.time(), "direction": "s2c",
                       "connection": 424242, "opcode": 1010,
                       "payload": build_volley_1010(SKYE_EID)})
            for index in range(8):
                self.emit({"time": time.time(), "direction": "s2c",
                           "connection": 424242, "opcode": 1054,
                           "payload": build_damage(ENEMY_EID, SKYE_EID, -21.15)})
        elif self.mode == "skye-b":
            for index in range(4):
                self.emit({"time": time.time(), "direction": "s2c",
                           "connection": 424242, "opcode": 1054,
                           "payload": build_damage(ENEMY_EID, SKYE_EID, -30.0)})
        else:
            self.emit({"time": time.time(), "direction": "s2c",
                       "connection": 424242, "opcode": 1054,
                       "payload": build_damage(ENEMY_EID, SKYE_EID, -25.8)})
        # cast payment visible in the next snapshot
        self.qa.state["heroes"][0]["energy"] = 930.0
        self.qa.state["heroes"][0]["ability_cooldowns"][
            {"skye-a": "0", "skye-b": "1", "skye-c": "2"}[self.mode]] = 12.0
        self.cast_emitted = True

    def driver(self, *, timeout=2.0):
        qa_dir = self.base / "qa"
        qa_dir.mkdir(exist_ok=True)
        (qa_dir / "state.json").write_text(json.dumps({"tick": 100}), encoding="utf-8")
        tail = sc.TraceTail(self.trace_path)
        qa = sc.QaSession(str(qa_dir), submit=self.qa.submit)
        driver = sc.ClientDriver(self.mode, adb=self.adb, qa=qa, tail=tail,
                                 connection=424242,
                                 profile=json.loads(json.dumps(
                                     {**sc.DEFAULT_PROFILE,
                                      "minion_push_window_s": 1.5,
                                      "camera_settle_s": 0,
                                      "declared_fixture": {
                                          **sc.DEFAULT_PROFILE[
                                              "declared_fixture"],
                                          "skye_level": 6,
                                          "skye_ranks": {"0": 1, "1": 1,
                                                         "2": 1},
                                          # skye_points matches the prepared
                                          # measured ability_points that
                                          # FakeQa.resources (production
                                          # SandboxQA.pump(resources) shape)
                                          # creates on the first resources
                                          # call: ability_points=1, gold=600,
                                          # xp=0 for both heroes.
                                          "skye_points": 1,
                                          "enemy_points": 1,
                                          "enemy_level": 1}})),
                                 out_dir=self.base / "out", timeout=timeout)
        return driver

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)


class TestWireParsers(unittest.TestCase):
    def test_ground_cast_action_at_offset_12(self):
        self.assertEqual(sc.ground_cast_action(
            {"opcode": 1042, "payload": build_ground_cast_payload(2)}), 2)
        self.assertIsNone(sc.ground_cast_action({"opcode": 1046, "payload": ""}))

    def test_position_event_action_at_offset_16(self):
        self.assertEqual(sc.position_event_action(
            {"opcode": 1046, "payload": build_position_event(1500, 4)}), 4)

    def test_damage_identity_offsets(self):
        victim, attacker, delta = sc.damage_identity(
            {"opcode": 1054, "payload": build_damage(1517, 1500, -232.68)})
        self.assertEqual((victim, attacker), (1517, 1500))
        self.assertAlmostEqual(delta, -232.68, places=3)

    def test_lock_identity_kind_602(self):
        self.assertEqual(sc.lock_identity(
            {"opcode": 1086, "payload": build_lock(1517, 1500)}), (1517, 1500, 602))

    def test_volley_owner_requires_class_and_owner(self):
        self.assertEqual(sc.volley_owner(
            {"opcode": 1010, "payload": build_volley_1010(1500)}), 1500)
        self.assertIsNone(sc.volley_owner(
            {"opcode": 1010,
             "payload": build_volley_1010(1500, volley_class=0xDEADBEEF)}),
            "an arbitrary 1010 publication must not count as a Skye volley")

    def test_timer_tag_extraction(self):
        payload = struct.pack(">IIfH", 1500, 0x46A89591, 12.0, 12) + bytes(14)
        self.assertEqual(sc.timer_tag_eid({"opcode": 1162, "payload": payload.hex()}),
                         (1500, 0x46A89591))


class TestTraceTail(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="halcyon-tail-test-"))
        self.path = self.base / "trace.jsonl"
        self.path.write_text("", encoding="ascii")

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def _line(self, opcode):
        return json.dumps({"time": time.time(), "direction": "c2s",
                           "connection": 1, "opcode": opcode, "payload": ""})

    def test_partial_final_line_is_not_consumed(self):
        tail = sc.TraceTail(self.path)
        with self.path.open("a", encoding="ascii") as stream:
            stream.write(self._line(1042) + "\n")
            stream.write(self._line(1046)[:20])       # torn write
        tail.poll()
        self.assertEqual(len(tail.records), 1)
        with self.path.open("a", encoding="ascii") as stream:
            stream.write(self._line(1046)[20:] + "\n")
        tail.poll()
        self.assertEqual(len(tail.records), 2)
        self.assertEqual(sorted(record["opcode"] for record in tail.records),
                         [1042, 1046])

    def test_missing_file_is_not_an_error_until_read(self):
        tail = sc.TraceTail(self.base / "absent.jsonl")
        self.assertEqual(tail.poll(), [])


class TestSessionPreconditions(unittest.TestCase):
    def setUp(self):
        self.harness = Harness()
        self.base = self.harness.base

    def tearDown(self):
        self.harness.cleanup()

    def test_missing_qa_dir_is_setup_failure(self):
        qa = sc.QaSession(str(self.base / "absent-qa"))
        with self.assertRaises(sc.ClientStageFailure) as caught:
            sc.verify_session(qa, timeout=1.0)
        self.assertEqual((caught.exception.stage, caught.exception.status),
                         ("SETUP", "FAIL"))

    def test_qa_dir_inside_repository_is_refused(self):
        inside = ROOT / "Docs" / ".halcyon-qa-test"
        qa = sc.QaSession(str(inside))
        with self.assertRaises(sc.ClientStageFailure) as caught:
            sc.verify_session(qa, timeout=1.0)
        self.assertIn("outside the repository", caught.exception.detail)

    def test_stale_session_is_refused_and_blocks_ui_mutation(self):
        self.harness.qa.state["phase"] = "world"
        # Freeze the world: snapshots never advance the tick.
        original = self.harness.qa.submit

        def frozen(command, *, timeout=5.0, request_id=None):
            if command.get("command") == "snapshot":
                self.harness.qa.snapshots += 1
                return {"id": request_id, "ok": True,
                        "result": json.loads(json.dumps(self.harness.qa.state))}
            return original(command, timeout=timeout, request_id=request_id)

        driver = self.harness.driver()
        driver.qa._submit = frozen
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.setup()
        self.assertIn("not progressing", caught.exception.detail)
        self.assertEqual([call for call in self.harness.adb.calls
                          if call[0] in ("tap", "swipe")], [],
                         "a stale session must never receive UI input")

    def test_missing_skye_is_setup_failure(self):
        self.harness.qa.state["heroes"][0]["hero_id"] = 244
        driver = self.harness.driver()
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.setup()
        self.assertIn("no hero_id 265", caught.exception.detail)

    def test_resolution_mismatch_refuses_profile_coordinates(self):
        self.harness.adb.wm_size = lambda: (1080, 2400)
        driver = self.harness.driver()
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.setup()
        self.assertIn("does not match the profile", caught.exception.detail)

    def test_stale_explicit_connection_is_refused_before_input(self):
        stale = time.time() - 180
        with self.harness.trace_path.open("a", encoding="ascii") as stream:
            stream.write(json.dumps({"time": stale, "direction": "c2s",
                                     "connection": 999, "opcode": 1000,
                                     "payload": ""}) + "\n")
        driver = self.harness.driver(timeout=1.0)
        driver.connection = 999
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.setup()
        self.assertIn("no records within", caught.exception.detail)
        self.assertEqual([call for call in self.harness.adb.calls
                          if call[0] in ("tap", "swipe")], [],
                         "a stale connection must never receive UI input")

    def test_auto_selected_connection_is_the_freshest(self):
        old = time.time() - 90
        with self.harness.trace_path.open("a", encoding="ascii") as stream:
            for _ in range(3):
                stream.write(json.dumps({"time": old, "direction": "s2c",
                                         "connection": 111, "opcode": 1010,
                                         "payload": ""}) + "\n")
            stream.write(json.dumps({"time": time.time(), "direction": "s2c",
                                     "connection": 424242, "opcode": 1010,
                                     "payload": ""}) + "\n")
        driver = self.harness.driver(timeout=1.0)
        driver.connection = None
        driver.setup()
        self.assertEqual(driver.connection, 424242,
                         "the most recently active connection must be selected")

    def test_unverified_teleport_position_refuses_tap_coordinates(self):
        driver = self.harness.driver(timeout=1.0)
        driver.setup()
        # Start away from the profile position so a real teleport is required;
        # then let the QA teleport ack WITHOUT moving the hero: the profile
        # taps are only valid for the framed placement, so this must refuse.
        self.harness.qa.state["heroes"][0]["x"] = -85.0
        self.harness.qa.state["heroes"][0]["y"] = 2.0
        original = driver.qa.submit

        def broken_teleport(command, **kwargs):
            if command.get("command") == "teleport":
                return {"id": "broken", "ok": True, "result": {}}
            return original(command, **kwargs)

        driver.qa.submit = broken_teleport
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.prepare_positions()
        self.assertIn("unverified framing", caught.exception.detail)


_REMOVE = object()


def mutate_diagnostics(harness, **fields):
    """Wrap the fake QA so its diagnostics receipt carries mutated fields.

    A value of ``_REMOVE`` deletes the field entirely (the missing-required-
    linkage case); any other value replaces it. Every other command passes
    through untouched.
    """
    original = harness.qa.submit

    def submit(command, *, timeout=5.0, request_id=None):
        result = original(command, timeout=timeout, request_id=request_id)
        if command.get("command") == "diagnostics" and result.get("ok"):
            receipt = dict(result.get("result") or {})
            for key, value in fields.items():
                if value is _REMOVE:
                    receipt.pop(key, None)
                else:
                    receipt[key] = value
            result = {**result, "result": receipt}
        return result

    harness.qa.submit = submit
    return submit


def mutate_endpoint_diagnostics(harness, **fields):
    """Wrap the fake QA so ONLY the END-of-trial diagnostics reply (the
    second and later diagnostics read) carries mutated fields.

    The trial's FIRST diagnostics read is the setup-boundary provenance
    receipt and keeps the fake world's own coherent linkage, so an endpoint
    defect is isolated from any setup failure. ``_REMOVE`` deletes a field.
    """
    original = harness.qa.submit
    seen = {"diagnostics": 0}

    def submit(command, *, timeout=5.0, request_id=None):
        reply = original(command, timeout=timeout, request_id=request_id)
        if command.get("command") == "diagnostics":
            seen["diagnostics"] += 1
            if seen["diagnostics"] >= 2 and reply.get("ok"):
                receipt = dict(reply.get("result") or {})
                for key, value in fields.items():
                    if value is _REMOVE:
                        receipt.pop(key, None)
                    else:
                        receipt[key] = value
                reply = {**reply, "result": receipt}
        return reply

    harness.qa.submit = submit
    return submit


def endpoint_reply_override(harness, transform):
    """Wrap the fake QA so the END-of-trial diagnostics REPLY ITSELF is
    replaced by ``transform(reply)``: the unacknowledged (pending) and
    malformed-receipt evidence failures need a reply shape, not a mutated
    receipt."""
    original = harness.qa.submit
    seen = {"diagnostics": 0}

    def submit(command, *, timeout=5.0, request_id=None):
        reply = original(command, timeout=timeout, request_id=request_id)
        if command.get("command") == "diagnostics":
            seen["diagnostics"] += 1
            if seen["diagnostics"] >= 2:
                return transform(reply)
        return reply

    harness.qa.submit = submit
    return submit


def unacknowledged_endpoint(harness):
    """The endpoint diagnostics read is never acknowledged inside the
    mailbox bound (the production QaSession timeout shape)."""
    return endpoint_reply_override(
        harness, lambda reply: {"id": reply.get("id"), "pending": True,
                                "result_path": "C:/tmp/never-written.json"})


def non_object_endpoint(harness):
    """The endpoint read acknowledges with a non-object result."""
    return endpoint_reply_override(
        harness, lambda reply: {**reply, "result": [1, 2, 3]})


class TestSetupDiagnosticsLinkage(unittest.TestCase):
    """Early checkpoint: an incoherent diagnostics receipt disagrees with the
    trial's own session snapshot and must fail SETUP at the setup boundary.
    The broad best-effort handler exists for a MISSING receipt (transport
    error), not for a received-but-invalid one."""

    def setUp(self):
        self.harness = Harness("skye-b")

    def tearDown(self):
        self.harness.cleanup()

    def test_matching_diagnostics_permit_setup_and_retain_typed_linkage(self):
        driver = self.harness.driver(timeout=1.0)
        session = driver.setup()
        linkage = driver.observations["diagnostics_linkage"]
        self.assertEqual(driver._diag_linkage, linkage,
                         "the validated linkage must survive into the "
                         "driver's serialized provenance")
        self.assertEqual(linkage["match_id"], session["snapshot"]["match_id"])
        self.assertEqual(linkage["pid"], self.harness.qa.pid)
        self.assertEqual(linkage["startup_at"], self.harness.qa.startup_at)
        self.assertEqual(linkage["phase"], "world")
        self.assertIs(linkage["match_finished"], False)
        # the receipt mirrors the fake world's own live progress
        self.assertEqual(linkage["tick"], self.harness.qa.state["tick"])
        self.assertEqual(linkage["time"], self.harness.qa.state["time"])
        self.assertNotIn("provenance_error", driver.observations)

    def test_different_match_diagnostics_fail_setup_before_any_gesture(self):
        mutate_diagnostics(self.harness, match_id="different-match")
        driver = self.harness.driver(timeout=1.0)
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.setup()
        self.assertEqual((caught.exception.stage, caught.exception.status),
                         ("SETUP", "FAIL"))
        self.assertIn("match_id", caught.exception.detail)
        self.assertIn("different-match", caught.exception.detail)
        kinds = [call[0] for call in self.harness.adb.calls]
        self.assertNotIn("tap", kinds,
                         "no gameplay gesture may run against a session whose "
                         "provenance disagrees with its snapshot")
        self.assertNotIn("swipe", kinds)
        self.assertEqual(driver.gestures, [])
        self.assertIsNone(driver._diag_linkage)

    def test_malformed_required_linkage_is_rejected(self):
        cases = {
            "pid_missing": {"pid": _REMOVE},
            "pid_string": {"pid": "4242"},
            "pid_bool": {"pid": True},
            "startup_at_missing": {"startup_at": _REMOVE},
            "startup_at_none": {"startup_at": None},
            "startup_at_string": {"startup_at": "1.0"},
            "match_id_missing": {"match_id": _REMOVE},
            "match_id_empty": {"match_id": ""},
            "match_id_null": {"match_id": None},
            "phase_missing": {"phase": _REMOVE},
            "phase_draft": {"phase": "draft"},
            "match_finished_missing": {"match_finished": _REMOVE},
            "match_finished_true": {"match_finished": True},
            "tick_missing": {"tick": _REMOVE},
            "tick_string": {"tick": "1"},
            "time_missing": {"time": _REMOVE},
            "time_nan": {"time": float("nan")},
        }
        for name, fields in cases.items():
            with self.subTest(case=name):
                harness = Harness("skye-b")
                try:
                    mutate_diagnostics(harness, **fields)
                    driver = harness.driver(timeout=1.0)
                    with self.assertRaises(sc.ClientStageFailure) as caught:
                        driver.setup()
                    self.assertEqual(
                        (caught.exception.stage, caught.exception.status),
                        ("SETUP", "FAIL"))
                    self.assertEqual(driver.gestures, [])
                    self.assertEqual(
                        [call[0] for call in harness.adb.calls
                         if call[0] in ("tap", "swipe")], [])
                finally:
                    harness.cleanup()

    def test_runner_retains_failure_result_and_evidence_for_bad_linkage(self):
        """Through the existing client runner: an incoherent receipt is a
        structured FAIL with the receipts and partial evidence persisted."""
        import unittest.mock as mock
        real_qa_class = sc.QaSession
        cases = {
            "different_match": ({"match_id": "different-match"}, "match_id"),
            "malformed_pid": ({"pid": "4242"}, "pid"),
        }
        for name, (fields, expected_in_detail) in cases.items():
            with self.subTest(case=name):
                harness = Harness("skye-b")
                try:
                    mutate_diagnostics(harness, **fields)
                    (harness.base / "qa").mkdir(exist_ok=True)
                    (harness.base / "qa" / "state.json").write_text(
                        json.dumps({"tick": 100}), encoding="utf-8")
                    declared_profile = json.loads(json.dumps({
                        **sc.DEFAULT_PROFILE,
                        "declared_fixture": {
                            **sc.DEFAULT_PROFILE["declared_fixture"],
                            "skye_level": 6,
                            "skye_ranks": {"0": 1, "1": 1, "2": 1},
                            "skye_points": 1,
                            "enemy_points": 1,
                            "enemy_level": 1}}))
                    profile_path = harness.base / "profile-declared.json"
                    profile_path.write_text(json.dumps(declared_profile),
                                            encoding="utf-8")
                    out_dir = harness.base / "runner-out"

                    def fake_qa(qa_dir, *, submit=None):
                        return real_qa_class(qa_dir, submit=harness.qa.submit)

                    with mock.patch.object(sc, "QaSession", fake_qa), \
                            mock.patch.object(sc, "Adb",
                                              lambda serial: harness.adb):
                        result = sc.run_client("skye-b", types.SimpleNamespace(
                            adb_serial="emulator-5554",
                            qa_dir=str(harness.base / "qa"),
                            wire_trace=str(harness.trace_path), timeout=1.0,
                            output=str(out_dir), connection=424242,
                            client_profile=str(profile_path), reference=None))
                    self.assertEqual(result["status"], "FAIL")
                    self.assertEqual(result["first_failed_stage"], "SETUP")
                    self.assertEqual(result["stages"]["SETUP"]["status"], "FAIL")
                    self.assertIn(expected_in_detail, result["failure_detail"])
                    self.assertEqual(result["gestures"], [])
                    self.assertNotIn("tap", [call[0] for call in harness.adb.calls])
                    diag_receipt = next(
                        receipt for receipt in result["qa_receipts"]
                        if receipt["label"] == "provenance-diagnostics")
                    self.assertTrue(diag_receipt["result"]["ok"],
                                    "the incoherent receipt itself is retained")
                    self.assertTrue(result["result_path"],
                                    "failure result persisted")
                    persisted_path = Path(result["result_path"])
                    self.assertEqual(persisted_path.parent, out_dir)
                    persisted = json.loads(
                        persisted_path.read_text(encoding="utf-8"))
                    self.assertEqual(persisted["failure_detail"],
                                     result["failure_detail"])
                    self.assertEqual(persisted["status"], "FAIL")
                finally:
                    harness.cleanup()


class TestSkyeBFlow(unittest.TestCase):
    """Full skye-b integration over the fakes: sequencing and classification."""

    def setUp(self):
        self.harness = Harness("skye-b")

    def tearDown(self):
        self.harness.cleanup()

    def test_lock_precedes_cast_and_classifies_damage(self):
        driver = self.harness.driver(timeout=3.0)
        result = driver.run_cast_scenario("B", requires_lock=True)
        self.assertEqual(result["status"], "PASS", result)
        gestures = [call for call in self.harness.adb.calls
                    if call[0] in ("tap", "swipe")]
        self.assertEqual(gestures[0][0], "tap",
                         "the basic-attack tap must precede the cast swipe")
        self.assertEqual(gestures[1][0], "swipe")
        # Lock-to-cast: the lock 1086 record time must sit between the tap and
        # the swipe, and no QA submission may occur in that interval.
        tap_time = gestures[0][-1]
        swipe_time = gestures[1][-1]
        self.assertLessEqual(tap_time, swipe_time)
        self.assertGreater(len(driver.observations.get("lock", {})), 0)
        # Damage classification: 4 ability missiles attributed; the
        # 1037-correlated basic, the turret hit and the PvE hit excluded.
        classification = driver.observations["damage_classification"]
        self.assertEqual(len(classification["attributed"]), 4)
        self.assertEqual(len(classification["basic_hits"]), 2,
                         "the swipe-window basic and the post-cast disengage "
                         "basic carry the basic tail; the pre-cast lock basic "
                         "is outside the attribution window")
        for row in classification["attributed"]:
            self.assertEqual(row["reason"],
                             "COMBAT_DELTA_TAIL (non-basic source)")
        for row in classification["basic_hits"]:
            self.assertIn("COMBAT_DELTA_HERO_TAIL", row["reason"])
        self.assertEqual(len(classification["excluded"]["other_attacker"]), 1)
        self.assertEqual(len(classification["excluded"]["other_victim"]), 1)
        self.assertTrue(driver.observations["resources"]["energy_paid"])
        self.assertEqual(driver.stages["PRESENTATION"]["status"], "UNVERIFIED")
        self.assertIn("disengage-move",
                      [g.get("label") for g in driver.gestures],
                      "the driver must stop ordinary auto-attacks through real "
                      "UI after the acknowledged cast")

    def test_missing_client_input_is_not_observed(self):
        self.harness.on_swipe = lambda: None       # gesture goes nowhere
        driver = self.harness.driver(timeout=1.0)
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.run_cast_scenario("B", requires_lock=False)
        self.assertEqual((caught.exception.stage, caught.exception.status),
                         ("CLIENT_INPUT_OBSERVED", "NOT_OBSERVED"))

    def test_input_without_acknowledgment_is_unacknowledged(self):
        original = self.harness.on_swipe

        def cast_without_ack():
            self.harness.emit({"time": time.time(), "direction": "c2s",
                               "connection": 424242, "opcode": 1042,
                               "payload": build_ground_cast_payload(2)})
            self.harness.qa.state["heroes"][0]["energy"] = 930.0

        self.harness.on_swipe = cast_without_ack
        driver = self.harness.driver(timeout=1.0)
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.run_cast_scenario("B", requires_lock=False)
        self.assertEqual((caught.exception.stage, caught.exception.status),
                         ("SERVER_ACKNOWLEDGED", "UNACKNOWLEDGED"))

    def test_wrong_cooldown_tag_is_not_accepted_as_b_evidence(self):
        original = self.harness.on_swipe

        def swipe_with_a_tag_only():
            self.harness.emit({"time": time.time(), "direction": "c2s",
                               "connection": 424242, "opcode": 1042,
                               "payload": build_ground_cast_payload(2)})
            self.harness.emit({"time": time.time(), "direction": "s2c",
                               "connection": 424242, "opcode": 1046,
                               "payload": build_position_event(SKYE_EID, 2)})
            # Only the A timer moved — B may reset A, so this is not B proof.
            self.harness.emit({"time": time.time(), "direction": "s2c",
                               "connection": 424242, "opcode": 1162,
                               "payload": build_timer(
                                   SKYE_EID, sc.SKYE_COOLDOWN_TAGS["A"])})
            for _ in range(4):
                self.harness.emit({"time": time.time(), "direction": "s2c",
                                   "connection": 424242, "opcode": 1054,
                                   "payload": build_damage(ENEMY_EID, SKYE_EID, -30.0)})
            self.harness.qa.state["heroes"][0]["energy"] = 930.0
            self.harness.qa.state["heroes"][0]["ability_cooldowns"]["1"] = 12.0

        self.harness.on_swipe = swipe_with_a_tag_only
        driver = self.harness.driver(timeout=1.0)
        result = driver.run_cast_scenario("B", requires_lock=True)
        self.assertEqual(result["status"], "PASS")
        self.assertNotIn("cooldown_tag", driver.observations,
                         "an A-tag movement must never be recorded as B cooldown evidence")


class TestSkyeCVolleyAttribution(unittest.TestCase):
    def setUp(self):
        self.harness = Harness("skye-c")

    def tearDown(self):
        self.harness.cleanup()

    def test_volley_actor_publication_is_required(self):
        driver = self.harness.driver(timeout=3.0)
        result = driver.run_cast_scenario("C", requires_lock=True)
        self.assertEqual(result["status"], "PASS")
        self.assertGreaterEqual(driver.observations.get("volley_actors", 0), 1)

    def test_missing_volley_publication_fails_the_effect_stage(self):
        original = self.harness.on_swipe

        def cast_without_volley():
            self.harness.emit({"time": time.time(), "direction": "c2s",
                               "connection": 424242, "opcode": 1042,
                               "payload": build_ground_cast_payload(4)})
            self.harness.emit({"time": time.time(), "direction": "s2c",
                               "connection": 424242, "opcode": 1046,
                               "payload": build_position_event(SKYE_EID, 4)})
            for _ in range(8):
                self.harness.emit({"time": time.time(), "direction": "s2c",
                                   "connection": 424242, "opcode": 1054,
                                   "payload": build_damage(ENEMY_EID, SKYE_EID, -21.15)})
            self.harness.qa.state["heroes"][0]["energy"] = 930.0
            self.harness.qa.state["heroes"][0]["ability_cooldowns"]["2"] = 25.0

        self.harness.on_swipe = cast_without_volley
        driver = self.harness.driver(timeout=1.0)
        with self.assertRaises(sc.ClientStageFailure) as caught:
            driver.run_cast_scenario("C", requires_lock=True)
        self.assertEqual(caught.exception.stage, "AUTHORITATIVE_EFFECT")
        self.assertIn("volley actor", caught.exception.detail)


class TestCaptureFailure(unittest.TestCase):
    def test_stop_failure_still_pulls_partial_video_and_retains_error(self):
        harness = Harness("skye-a")
        try:
            driver = harness.driver(timeout=2.0)
            recorder = mock.Mock()
            recorder.poll.return_value = None
            recorder.terminate.side_effect = lambda: setattr(recorder.poll, "return_value", 0)
            harness.adb.start_screenrecord = mock.Mock(return_value=recorder)
            harness.adb.stop_screenrecord = mock.Mock(
                side_effect=RuntimeError("screenrecord identity mismatch"))
            with mock.patch.object(sc.time, "sleep"):
                driver.start_capture(window_hint=10)
                driver.finalize_capture()
            harness.adb.stop_screenrecord.assert_called_once_with(recorder)
            recorder.terminate.assert_called_once()
            presentation = driver.observations["presentation"]
            self.assertTrue(presentation["video"])
            self.assertEqual(presentation["video_bytes"], len(b"mp4-fake"))
            self.assertTrue(presentation["finalized"])
            self.assertEqual(presentation["capture_errors"][0]["stage"], "stop")
            self.assertIn("identity mismatch", presentation["capture_errors"][0]["error"])
            self.assertEqual(driver.stages["PRESENTATION"]["status"], "UNVERIFIED")
        finally:
            harness.cleanup()

    def test_aim_screencap_failure_refuses_the_blind_cast(self):
        """A missing pre-gesture screenshot means the driver cannot see the
        enemy; the trial must fail SETUP rather than cast blind."""
        harness = Harness("skye-a")
        try:
            harness.adb.fail_screencap = True
            driver = harness.driver(timeout=2.0)
            with self.assertRaises(sc.ClientStageFailure) as caught:
                driver.run_cast_scenario("A", requires_lock=False)
            self.assertEqual(caught.exception.stage, "SETUP")
            self.assertIn("pre-gesture screenshot", caught.exception.detail)
        finally:
            harness.cleanup()

    def test_video_pull_failure_keeps_result_passing_but_visible(self):
        harness = Harness("skye-a")
        try:
            original_pull = harness.adb.pull

            def broken_pull(device_path, destination):
                raise RuntimeError("pull failed: device offline")

            harness.adb.pull = broken_pull
            driver = harness.driver(timeout=2.0)
            result = driver.run_cast_scenario("A", requires_lock=False)
            self.assertEqual(result["status"], "PASS")
            presentation = driver.observations["presentation"]
            self.assertIsNone(presentation["video"],
                              "a failed pull must not fake a video path")
            self.assertTrue(presentation["finalized"])
            self.assertTrue(presentation["capture_errors"])
            self.assertEqual(driver.stages["PRESENTATION"]["status"],
                             "UNVERIFIED")
        finally:
            harness.cleanup()


class TestAdaptiveAim(unittest.TestCase):
    def _frame_with_bar(self, path, bar_xy, bar_w=70):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (960, 540), (30, 40, 30))
        draw = ImageDraw.Draw(img)
        x, y = bar_xy
        draw.rectangle([x - bar_w // 2, y, x + bar_w // 2, y + 7],
                       fill=(190, 40, 40))
        img.save(path)
        return path

    def test_locates_enemy_bar_and_aims_below_it(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-aim-test-"))
        try:
            frame = self._frame_with_bar(base / "f.png", (560, 100))
            aim, mode = sc.locate_enemy_aim(frame, fallback=(603, 267))
            self.assertEqual(mode, "located:enemy-health-bar")
            self.assertAlmostEqual(aim[0], 560, delta=6)
            self.assertGreaterEqual(aim[1], 100)
            self.assertLessEqual(aim[1], 540 - 60)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_falls_back_when_no_bar(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-aim-test-"))
        try:
            img = Image.new if False else None
            from PIL import Image
            Image.new("RGB", (960, 540), (30, 40, 30)).save(base / "f.png")
            aim, mode = sc.locate_enemy_aim(base / "f.png", fallback=(603, 267))
            self.assertEqual((aim, mode), ((603, 267), "fallback:enemy-bar-not-found"))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_body_aim_uses_selected_bar_width_after_scanning_blank_rows(self):
        frame = PILImage.new("RGB", (960, 540), (30, 40, 30))
        for x in range(400, 500):
            frame.putpixel((x, 100), (220, 80, 0))
        with mock.patch("PIL.Image.open", return_value=frame):
            aim, mode = sc.locate_enemy_aim(
                "in-memory.png", fallback=(0, 0), ground=False)
        self.assertEqual(mode, "located:enemy-health-bar")
        self.assertEqual(aim, (420, 168))


class TestOwnedAdbRecording(unittest.TestCase):
    """Mocked transport checks: these tests never execute ADB."""

    def test_start_retries_empty_receipt_until_remote_pid_is_written(self):
        adb = sc.Adb("owned-device")
        recorder = mock.Mock()
        recorder.poll.return_value = None
        with mock.patch.object(sc.subprocess, "Popen", return_value=recorder), \
                mock.patch.object(adb, "shell", side_effect=["", "3621"]) as shell, \
                mock.patch.object(sc.time, "sleep"):
            self.assertIs(adb.start_screenrecord(
                "/sdcard/halcyon-owned.mp4", time_limit=10), recorder)
        self.assertEqual(recorder.halcyon_recording["remote_pid"], 3621)
        self.assertEqual(shell.call_count, 2)
        recorder.terminate.assert_not_called()

    def test_empty_pid_receipt_retry_stops_at_startup_deadline(self):
        adb = sc.Adb("owned-device")
        recorder = mock.Mock()
        recorder.poll.return_value = None
        with mock.patch.object(sc.subprocess, "Popen", return_value=recorder), \
                mock.patch.object(adb, "shell", return_value="") as shell, \
                mock.patch.object(sc.time, "monotonic", side_effect=[100.0, 100.0, 105.0]), \
                mock.patch.object(sc.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "did not produce a live PID"):
                adb.start_screenrecord("/sdcard/halcyon-owned.mp4", time_limit=10)
        shell.assert_called_once()
        recorder.terminate.assert_called_once()

    def test_start_retains_remote_pid_and_stop_scopes_signal_to_owned_output(self):
        adb = sc.Adb("owned-device")
        recorder = mock.Mock()
        recorder.poll.return_value = None
        path = "/sdcard/halcyon-owned.mp4"
        with mock.patch.object(sc.subprocess, "Popen", return_value=recorder) as spawn, \
                mock.patch.object(adb, "shell", side_effect=["4321", ""]) as shell:
            self.assertIs(adb.start_screenrecord(path, time_limit=12.2), recorder)
            adb.stop_screenrecord(recorder)
        self.assertEqual(recorder.halcyon_recording, {
            "remote_pid": 4321, "serial": "owned-device", "device_path": path,
            "pid_path": path + ".pid", "time_limit": 13})
        argv = spawn.call_args.args[0]
        self.assertEqual(argv[:4], ["adb", "-s", "owned-device", "shell"])
        self.assertIn("set -C", argv[4])
        self.assertIn('"$$"', argv[4])
        self.assertIn("exec screenrecord --time-limit 13 " + path, argv[4])
        stop = shell.call_args_list[-1].args[0]
        self.assertIn("/proc/4321/cmdline", stop)
        self.assertIn("screenrecord\n--time-limit\n13\n" + path, stop)
        self.assertIn("kill -2 4321", stop)
        self.assertNotIn("pidof", stop)
        self.assertNotIn("killall", stop)
        self.assertIn("identity mismatch; refused to signal", stop)

    def test_stop_refuses_missing_identity_other_device_and_nonpositive_pid(self):
        adb = sc.Adb("owned-device")
        for identity in (None, {"serial": "other-device", "remote_pid": 4321},
                         {"serial": "owned-device", "remote_pid": 0},
                         {"serial": "owned-device", "remote_pid": True}):
            with self.subTest(identity=identity), mock.patch.object(adb, "shell") as shell:
                recorder = types.SimpleNamespace(halcyon_recording=identity)
                with self.assertRaisesRegex(RuntimeError, "trusted remote identity"):
                    adb.stop_screenrecord(recorder)
                shell.assert_not_called()

    def test_invalid_pid_receipt_only_terminates_its_local_transport(self):
        adb = sc.Adb("owned-device")
        recorder = mock.Mock()
        recorder.poll.return_value = None
        with mock.patch.object(sc.subprocess, "Popen", return_value=recorder), \
                mock.patch.object(adb, "shell", return_value="0") as shell:
            with self.assertRaisesRegex(RuntimeError, "invalid screenrecord PID"):
                adb.start_screenrecord("/sdcard/halcyon-owned.mp4", time_limit=10)
        recorder.terminate.assert_called_once()
        recorder.wait.assert_called_once_with(timeout=3.0)
        self.assertEqual(shell.call_count, 1)
        self.assertTrue(shell.call_args.args[0].startswith("cat "))

    def test_identity_mismatch_does_not_retry_with_a_broader_signal(self):
        adb = sc.Adb("owned-device")
        recorder = types.SimpleNamespace(halcyon_recording={
            "serial": "owned-device", "remote_pid": 4321, "time_limit": 10,
            "device_path": "/sdcard/halcyon-owned.mp4"})
        with mock.patch.object(adb, "shell", side_effect=RuntimeError("identity mismatch")) as shell:
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                adb.stop_screenrecord(recorder)
        shell.assert_called_once()


class TestMinionEpisodes(unittest.TestCase):
    """Pure episode builder: causal combat -> carried end -> resume semantics.

    An engagement END is a CARRIED EVENT WITH AN INSTANT: an explicit 1072
    death publication for every opponent the actor engaged, or a census sample
    recording hp <= 0. An opponent observed alive, holding position, or simply
    absent carries no end, so the claim stays unknown; movement before the
    carried instant is never credited; and the resumption is measured over a
    CONTIGUOUS run of samples that observe the actor explicitly alive strictly
    after that instant.
    """

    def test_full_causal_episode(self):
        """The whole chain in one record: contact, the opponent's death
        publication, then an alive march strictly after that instant."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),   # march
                (2.0, 12.0, 2.0, 300.0, True),   # contact
                (3.0, 14.0, 2.0, 260.0, True),   # after the kill: resumes
                (4.0, 17.0, 2.0, 260.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (2.0, 15.0, 2.0, 300.0, True)]},   # killed in the exchange
        }
        combat = [{"time": 2.5, "victim": 4611, "attacker": 4610,
                   "delta": -40.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 2.7, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        a = episodes[4610]
        self.assertGreaterEqual(a["approach"], 1.0)
        self.assertTrue(a["combat_participant"])
        self.assertEqual(a["opponents"], [4611])
        self.assertEqual(a["engagement_end"], 2.7,
                         "the end IS the carried death instant")
        self.assertEqual(a["end_evidence"], "opponent-death-publication")
        self.assertEqual(a["opponent_closure"],
                         {"4611": "death-publication@2.70"})
        self.assertEqual(a["unaccounted_opponents"], [])
        self.assertEqual(a["alive_samples_after_end"], 2)
        self.assertEqual(a["resumed_after_combat"], 3.0)
        self.assertIsNone(a["resumption_unverified"])
        b = episodes[4611]
        self.assertEqual(b["death_time"], 2.7)
        self.assertEqual(b["death_evidence"], "death-publication")
        self.assertIsNone(b["resumed_after_combat"],
                          "the dead participant resumes nothing")

    def test_unrelated_wave_after_global_combat_cannot_resume(self):
        """A new wave marching after SOMEONE ELSE's engagement gets no
        resumption credit (no combat participation at all)."""
        tracked = {
            4700: {"team": 1, "timeline": [   # unrelated fresh wave
                (1.0, 5.0, 2.0, 300.0, True),
                (2.0, 11.0, 2.0, 300.0, True)]},
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 14.0, 2.0, 260.0, True),
                (3.0, 16.0, 2.0, 260.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (2.0, 15.0, 2.0, 120.0, True)]},
        }
        combat = [{"time": 1.5, "victim": 4611, "attacker": 4610,
                   "delta": -40.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 1.6, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        self.assertFalse(episodes[4700]["combat_participant"])
        self.assertIsNone(episodes[4700]["resumed_after_combat"],
                          "a bystander wave must not satisfy resumption")
        self.assertIsNone(episodes[4700]["resumption_unverified"],
                          "and it makes no claim of its own")
        # the fighter's closure is carried, so its post-closure march counts
        self.assertEqual(episodes[4610]["engagement_end"], 1.6)
        self.assertEqual(episodes[4610]["resumed_after_combat"], 2.0)

    def test_participant_death_prevents_resumption(self):
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 12.0, 2.0, 300.0, True),
                (3.0, 13.0, 2.0, 300.0, True),
                (4.0, 16.0, 2.0, 300.0, True)]},   # marches on AFTER the kill
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (2.0, 13.0, 2.0, 60.0, True),
                (3.0, 13.0, 2.0, 0.0, False)]},    # died at 2.x
        }
        combat = [{"time": 2.0, "victim": 4611, "attacker": 4610,
                   "delta": -260.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 2.2, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        # 4611 (the dead participant) has no proven resumption of its own
        self.assertIsNone(episodes[4611]["resumed_after_combat"])
        self.assertEqual(episodes[4611]["death_time"], 2.2,
                         "the earliest carried death evidence is the death")
        # 4610 (the winner) resumes after the closure at 2.2
        self.assertEqual(episodes[4610]["resumed_after_combat"], 3.0)

    def test_movement_while_engaged_is_not_resumption(self):
        """The opponent opens a second fight with a teammate while this actor
        advances: the engagement stays open until the opponent's death is
        carried, so that advance is pursuit — and after the closure the actor
        holds position, which is the only movement that gets measured."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 14.0, 2.0, 300.0, True),
                (3.0, 18.0, 2.0, 300.0, True),   # advancing while the
                (4.0, 20.0, 2.0, 300.0, True),   # opponent is still fighting
                (7.0, 20.0, 2.0, 300.0, True),   # halted after the closure
                (8.0, 20.0, 2.0, 300.0, True)]},
            4612: {"team": 1, "timeline": [
                (1.0, 12.0, 2.0, 300.0, True),
                (6.0, 12.0, 2.0, 240.0, True),
                (8.0, 12.0, 2.0, 240.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (2.0, 16.0, 2.0, 260.0, True),
                (6.0, 14.0, 2.0, 140.0, True),
                (8.0, 14.0, 2.0, 140.0, True)]},
        }
        combat = [{"time": 2.0, "victim": 4611, "attacker": 4610,
                   "delta": -40.0, "victim_team": 2, "attacker_team": 1},
                  {"time": 6.0, "victim": 4612, "attacker": 4611,
                   "delta": -60.0, "victim_team": 1, "attacker_team": 2}]
        deaths = [{"time": 6.5, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        a = episodes[4610]
        self.assertEqual(a["opponents"], [4611])
        self.assertEqual(a["engagement_end"], 6.5,
                         "the closure waits for the carried death, not for "
                         "this actor's own last hit")
        self.assertGreater(a["engagement_end"], a["last_combat_time"])
        self.assertEqual(a["resumed_after_combat"], 0.0,
                         "the pre-closure advance is pursuit; after the "
                         "closure the actor held position and only that is "
                         "credited")
        self.assertFalse(a["resumed_after_combat"] >= 1.0)
        self.assertGreaterEqual(a["approach"], 1.0,
                               "the advance itself is still reported")

    def test_opponent_alive_with_no_end_event_is_unknown(self):
        """An opponent observed alive, holding position and out of contact is
        NOT disengagement evidence. The record carries no death for it, so
        there is no closure instant and the movement earns no resumption
        credit — the claim is reported as unknown, never inferred."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 0.0, 0.0, 100.0, True),
                (2.0, 2.0, 0.0, 100.0, True),
                (3.0, 4.0, 0.0, 100.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 5.0, 0.0, 100.0, True),
                (2.0, 5.0, 0.0, 100.0, True),
                (3.0, 5.0, 0.0, 100.0, True)]},
        }
        combat = [{"time": 1.5, "victim": 4611, "attacker": 4610,
                   "delta": -10.0, "victim_team": 2, "attacker_team": 1}]
        episodes = sc.minion_episodes(tracked, combat, [])
        a = episodes[4610]
        self.assertIsNone(a["engagement_end"],
                          "no carried end event: an alive opponent is not one")
        self.assertEqual(a["end_evidence"], "unknown")
        self.assertEqual(a["opponent_closure"], {"4611": "no-death-evidence"})
        self.assertEqual(a["unaccounted_opponents"], [4611])
        self.assertIsNone(a["resumed_after_combat"])
        claim = a["resumption_unverified"]
        self.assertIsNotNone(claim,
                             "the unknown is reported, the claim is not dropped")
        self.assertIn("4611", claim["reasons"][0])
        self.assertIn("no disengagement evidence", claim["reasons"][0])
        self.assertIsNone(claim["march_after"],
                          "no closure instant exists, so no post-end march is "
                          "measured at all")
        self.assertEqual(a["approach"], 4.0,
                         "the movement itself is still reported")

    def test_opponent_death_after_all_movement_cannot_validate_it(self):
        """The death instant is the closure, and movement is measured strictly
        after it: an opponent death published at t=10 can never certify the
        t=2..3 advance as post-engagement movement."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 0.0, 0.0, 100.0, True),
                (2.0, 2.0, 0.0, 100.0, True),
                (3.0, 4.0, 0.0, 100.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 5.0, 0.0, 100.0, True),
                (2.0, 5.0, 0.0, 100.0, True),
                (3.0, 5.0, 0.0, 100.0, True)]},
        }
        combat = [{"time": 1.5, "victim": 4611, "attacker": 4610,
                   "delta": -10.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 10.0, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        a = episodes[4610]
        self.assertEqual(a["engagement_end"], 10.0)
        self.assertEqual(a["end_evidence"], "opponent-death-publication")
        self.assertIsNone(a["resumed_after_combat"],
                          "the 1.5..3 advance precedes the event used to "
                          "prove the end, so it is not resumption")
        self.assertEqual(a["alive_samples_after_end"], 0)
        claim = a["resumption_unverified"]
        self.assertIsNotNone(claim)
        self.assertIsNone(claim["march_after"])
        self.assertEqual(a["approach"], 4.0,
                         "the movement is still reported, just not credited")

    def test_opponent_death_publication_proves_the_end_without_later_rows(self):
        """The production shape of a kill: the opponent disappears from the
        census, and the 1072 ENTITY_DEATH publication is what evidences its
        death and therefore the end of the engagement."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 12.0, 2.0, 300.0, True),
                (3.0, 14.0, 2.0, 300.0, True),
                (4.0, 17.0, 2.0, 300.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (2.0, 16.0, 2.0, 40.0, True),
                (3.0, 16.0, 2.0, 40.0, False)]},  # absent: cause unknown here
        }
        combat = [{"time": 2.5, "victim": 4611, "attacker": 4610,
                   "delta": -260.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 2.7, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        a = episodes[4610]
        self.assertEqual(a["engagement_end"], 2.7)
        self.assertEqual(a["end_evidence"], "opponent-death-publication")
        self.assertEqual(a["opponent_closure"],
                         {"4611": "death-publication@2.70"})
        self.assertEqual(a["unaccounted_opponents"], [])
        self.assertIsNone(a["resumption_unverified"])
        self.assertEqual(a["resumed_after_combat"], 3.0)
        b = episodes[4611]
        self.assertEqual(b["death_time"], 2.7)
        self.assertEqual(b["death_evidence"], "death-publication")
        self.assertEqual(b["absent_since"], 3.0)
        # the dead participant makes no resumption claim of its own
        self.assertIsNone(b["resumed_after_combat"])

    def test_opponent_lethal_census_sample_is_death_evidence(self):
        """A recorded hp <= 0 sample is a measurement, not an inference: it
        is the weaker death-evidence kind and it closes the engagement even
        when no 1072 was observed for that actor."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (4.0, 16.0, 2.0, 300.0, True),
                (5.0, 19.0, 2.0, 300.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (3.0, 14.0, 2.0, 0.0, True)]},
        }
        combat = [{"time": 2.0, "victim": 4611, "attacker": 4610,
                   "delta": -300.0, "victim_team": 2, "attacker_team": 1}]
        episodes = sc.minion_episodes(tracked, combat, [])
        a = episodes[4610]
        self.assertEqual(a["opponent_closure"], {"4611": "death-sample@3.00"})
        self.assertEqual(a["end_evidence"], "opponent-death-sample")
        self.assertEqual(a["engagement_end"], 3.0)
        self.assertEqual(a["resumed_after_combat"], 3.0)

    def test_missing_opponent_census_without_death_evidence_is_unverified(self):
        """The opponent's rows simply stop. The absence keeps its instant, but
        it is NOT a death and NOT an end: with no carried end event there is
        no closure instant to measure against, so the claim stays UNVERIFIED
        instead of borrowing a death the record does not carry."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 12.0, 2.0, 300.0, True),
                (3.0, 14.0, 2.0, 280.0, True),
                (4.0, 17.0, 2.0, 280.0, True),
                (5.0, 20.0, 2.0, 280.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (2.0, 16.0, 2.0, 260.0, True),
                (3.0, 16.0, 2.0, 260.0, False),  # absent from here on
                (4.0, 16.0, 2.0, 260.0, False)]},
        }
        combat = [{"time": 2.5, "victim": 4611, "attacker": 4610,
                   "delta": -40.0, "victim_team": 2, "attacker_team": 1}]
        episodes = sc.minion_episodes(tracked, combat, [])
        a = episodes[4610]
        self.assertIsNone(a["engagement_end"])
        self.assertEqual(a["end_evidence"], "unknown")
        self.assertEqual(a["unaccounted_opponents"], [4611])
        self.assertIsNone(a["resumed_after_combat"],
                          "an unexplained absence cannot prove a resumption")
        claim = a["resumption_unverified"]
        self.assertIsNotNone(claim)
        self.assertIn("4611", claim["reasons"][0])
        self.assertIn("absence is not a death", claim["reasons"][0])
        self.assertIsNone(claim["march_after"],
                          "with no closure instant there is no post-end march")
        self.assertGreaterEqual(a["approach"], 1.0,
                               "the movement itself is still reported")
        # the absent opponent carries no death evidence anywhere
        self.assertIsNone(episodes[4611]["death_time"])
        self.assertEqual(episodes[4611]["absent_since"], 3.0)

    def test_unknown_hp_sample_is_not_alive_evidence(self):
        """An unknown HP is not evidence of life: a sample that serves the
        actor with no HP value can neither open nor continue a proven-alive
        interval, so no resumption is fabricated out of it."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 12.0, 2.0, 300.0, True),
                (3.0, 14.0, 2.0, None, True),   # served, HP unknown
                (4.0, 17.0, 2.0, None, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True)]},
        }
        combat = [{"time": 1.5, "victim": 4611, "attacker": 4610,
                   "delta": -40.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 2.2, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        a = episodes[4610]
        self.assertEqual(a["engagement_end"], 2.2)
        self.assertEqual(a["alive_samples_after_end"], 0,
                         "a present sample with an unknown HP is not alive "
                         "evidence")
        self.assertIsNone(a["resumed_after_combat"])
        claim = a["resumption_unverified"]
        self.assertIsNotNone(claim)
        self.assertIn("explicitly alive", claim["reasons"][0])
        self.assertIsNone(claim["march_after"])
        self.assertEqual(a["approach"], 2.0,
                         "only the two known-HP samples feed the approach")

    def test_absence_gap_is_not_bridged_into_one_alive_interval(self):
        """An absence inside the post-closure window ends the run: the alive
        samples after the gap are a SEPARATE interval and are never stitched
        to the ones before it."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 12.0, 2.0, 300.0, True),
                (3.0, 14.0, 2.0, 300.0, True),   # alive, after the closure
                (4.0, 14.0, 2.0, 300.0, False),  # ABSENT: the run ends here
                (5.0, 20.0, 2.0, 300.0, True),   # alive again, far ahead
                (6.0, 22.0, 2.0, 300.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True)]},
        }
        combat = [{"time": 1.5, "victim": 4611, "attacker": 4610,
                   "delta": -40.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 2.2, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        a = episodes[4610]
        self.assertEqual(a["engagement_end"], 2.2)
        self.assertEqual(a["alive_samples_after_end"], 1,
                         "the unbroken run after the closure is one sample")
        self.assertIsNone(a["resumed_after_combat"],
                          "the 8 u seen after the gap is never bridged to the "
                          "samples before it")
        claim = a["resumption_unverified"]
        self.assertIsNotNone(claim)
        self.assertIn("contiguous", claim["reasons"][0])
        self.assertIsNone(claim["march_after"])

    def test_moving_bystander_is_never_a_resumption_claim(self):
        """Checkpoint 10 negative: a minion that marched after SOMEONE
        ELSE's combat is not a survivor — it never fought, has no engagement
        to end, and is not even an unverified claimant."""
        tracked = {
            4700: {"team": 1, "timeline": [   # marches the whole window
                (1.0, 5.0, 2.0, 300.0, True),
                (3.0, 13.0, 2.0, 300.0, True),
                (5.0, 21.0, 2.0, 300.0, True)]},
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (3.0, 12.0, 2.0, 280.0, True),
                (5.0, 14.0, 2.0, 280.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (3.0, 18.0, 2.0, 260.0, True),
                (5.0, 18.0, 2.0, 260.0, True)]},
        }
        combat = [{"time": 2.0, "victim": 4611, "attacker": 4610,
                   "delta": -40.0, "victim_team": 2, "attacker_team": 1}]
        episodes = sc.minion_episodes(tracked, combat, [])
        bystander = episodes[4700]
        self.assertGreater(bystander["approach"], 1.0,
                           "the bystander really did march")
        self.assertFalse(bystander["combat_participant"])
        self.assertIsNone(bystander["resumed_after_combat"])
        self.assertIsNone(bystander["resumption_unverified"],
                          "a bystander makes no claim at all")

    def test_movement_before_the_engagement_end_is_not_resumption(self):
        """Checkpoint-10 negative: the opponent keeps fighting a teammate
        after this actor's own last hit, so the engagement is still open
        while it advances. Only movement strictly after the carried end
        counts — and there the actor is stopped."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 12.0, 2.0, 300.0, True),
                (3.0, 18.0, 2.0, 300.0, True),   # advancing while the
                (4.0, 20.0, 2.0, 300.0, True),   # opponent is still fighting
                (6.0, 20.0, 2.0, 300.0, True),   # halted after it died
                (7.0, 20.0, 2.0, 300.0, True)]},
            4612: {"team": 1, "timeline": [
                (1.0, 12.0, 2.0, 300.0, True),
                (5.0, 12.0, 2.0, 240.0, True),
                (7.0, 12.0, 2.0, 240.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (2.0, 16.0, 2.0, 260.0, True),
                (5.0, 14.0, 2.0, 140.0, True)]},
        }
        combat = [{"time": 2.0, "victim": 4611, "attacker": 4610,
                   "delta": -40.0, "victim_team": 2, "attacker_team": 1},
                  {"time": 5.0, "victim": 4612, "attacker": 4611,
                   "delta": -60.0, "victim_team": 1, "attacker_team": 2}]
        deaths = [{"time": 5.2, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        a = episodes[4610]
        self.assertEqual(a["opponents"], [4611])
        self.assertEqual(a["engagement_end"], 5.2,
                         "the closure waits for the opponent's death, not "
                         "for this actor's last hit")
        self.assertGreater(a["engagement_end"], a["last_combat_time"])
        self.assertEqual(a["resumed_after_combat"], 0.0,
                         "the pre-closure advance is not credited: only the "
                         "post-closure movement counts, and it is zero")
        self.assertFalse(a["resumed_after_combat"] >= 1.0)

    def test_valid_resume_then_later_death_keeps_the_historical_resume(self):
        """The actor proved a carried end, was observed alive while resuming,
        and died LATER. The death is reported separately and does not erase
        the interval that was validly observed alive before it."""
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 12.0, 2.0, 300.0, True),
                (3.0, 13.0, 2.0, 260.0, True),
                (4.0, 16.0, 2.0, 260.0, True),
                (5.0, 19.0, 2.0, 260.0, True),
                (6.0, 19.0, 2.0, 260.0, False)]},  # gone after the death
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True),
                (2.0, 16.0, 2.0, 220.0, True)]},
        }
        combat = [{"time": 2.5, "victim": 4611, "attacker": 4610,
                   "delta": -80.0, "victim_team": 2, "attacker_team": 1}]
        # 4612 is not otherwise carried here: it is simply the actor that
        # killed the survivor later, which is reported, not explained.
        deaths = [{"time": 2.7, "victim": 4611, "killer": 4610},
                  {"time": 5.5, "victim": 4610, "killer": 4612}]
        episodes = sc.minion_episodes(tracked, combat, [], deaths)
        a = episodes[4610]
        self.assertEqual(a["engagement_end"], 2.7)
        self.assertEqual(a["resumed_after_combat"], 6.0,
                         "the earlier alive interval stands")
        self.assertEqual(a["alive_samples_after_end"], 3,
                         "only the samples observed alive before the death")
        self.assertEqual(a["death_time"], 5.5)
        self.assertEqual(a["death_evidence"], "death-publication")
        self.assertEqual(a["absent_since"], 6.0)
        self.assertIsNone(a["resumption_unverified"])

    def test_structure_hit_by_unrelated_actor_does_not_count(self):
        tracked = {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (3.0, 16.0, 2.0, 300.0, True)]},
        }
        structure_hits = [{"time": 3.5, "structure": 3539,
                           "attacker": 4999, "delta": -40.0}]
        episodes = sc.minion_episodes(tracked, [], structure_hits)
        self.assertFalse(episodes[4610]["structure_hit"])
        self.assertTrue(episodes[4610]["structure_hit"] is False)
        self.assertEqual(episodes[4610]["structure_hits"], [],
                         "another actor's hit is not this actor's observation")
        self.assertIsNone(episodes[4610]["structure_sequence"])
        self.assertIsNone(episodes[4610]["structure_unverified"])

    def _sequence_lane(self):
        """One accepted sequence's lane: contact at t=2, the opponent's death
        published at t=2.4, and a survivor that is observed alive at t=3, 4, 5
        (push-direction x 12 -> 14 -> 16 -> 16)."""
        return {
            4610: {"team": 1, "timeline": [
                (1.0, 10.0, 2.0, 300.0, True),
                (2.0, 12.0, 2.0, 300.0, True),
                (3.0, 14.0, 2.0, 280.0, True),
                (4.0, 16.0, 2.0, 280.0, True),
                (5.0, 16.0, 2.0, 280.0, True)]},
            4611: {"team": 2, "timeline": [
                (1.0, 20.0, 2.0, 300.0, True)]},
        }

    def _sequence_inputs(self, *, hits, deaths=None, teams=None, tracked=None):
        combat = [{"time": 2.0, "victim": 4611, "attacker": 4610,
                   "delta": -80.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 2.4, "victim": 4611, "killer": 4610}] \
            if deaths is None else deaths
        teams = {3539: 2} if teams is None else teams
        return sc.minion_episodes(tracked if tracked is not None
                                  else self._sequence_lane(),
                                  combat, hits, deaths, teams)

    def test_same_participant_sequence_carries_the_opposing_structure_hit(self):
        """Checkpoint 11 positive: the participant's own hit on the opposing
        structure, later than the resumption that was already measured."""
        hits = [{"time": 4.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits)[4610]
        self.assertEqual(a["engagement_end"], 2.4)
        self.assertEqual(a["resumed_after_combat"], 2.0)
        self.assertTrue(a["structure_hit"], "the raw observation is kept")
        self.assertEqual(a["structure_hits"],
                         [{"time": 4.5, "structure": 3539, "delta": -40.0,
                           "structure_team": 2}])
        sequence = a["structure_sequence"]
        self.assertIsNotNone(sequence)
        self.assertEqual(sequence["structure"], 3539)
        self.assertEqual(sequence["structure_team"], 2)
        self.assertEqual(sequence["time"], 4.5)
        self.assertEqual(sequence["samples_before_hit"], 2,
                         "t=3 and t=4 are the resumption measured before it")
        self.assertEqual(sequence["march_before_hit"], 2.0)
        self.assertIsNone(a["structure_unverified"])

    def test_bystander_structure_hit_never_satisfies_the_sequence(self):
        """The hit is preserved raw, but a minion that never fought cannot
        bind it to a resumption of its own — and the fighter's own hit is the
        one that carries the sequence."""
        tracked = self._sequence_lane()
        tracked[4700] = {"team": 1, "timeline": [
            (1.0, 4.0, 2.0, 300.0, True),
            (3.0, 12.0, 2.0, 300.0, True),
            (4.0, 14.0, 2.0, 300.0, True)]}
        hits = [{"time": 4.5, "structure": 3539, "attacker": 4700,
                 "delta": -40.0},
                {"time": 4.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        combat = [{"time": 2.0, "victim": 4611, "attacker": 4610,
                   "delta": -80.0, "victim_team": 2, "attacker_team": 1}]
        deaths = [{"time": 2.4, "victim": 4611, "killer": 4610}]
        episodes = sc.minion_episodes(tracked, combat, hits, deaths, {3539: 2})
        bystander = episodes[4700]
        self.assertTrue(bystander["structure_hit"],
                        "the bystander's hit really happened")
        self.assertIsNone(bystander["structure_sequence"],
                          "a bystander hit must not satisfy the sequence")
        self.assertGreater(bystander["approach"], 1.0,
                           "it really did advance too")
        claim = bystander["structure_unverified"]
        self.assertIsNotNone(claim)
        self.assertIn("not an opposing-combat participant",
                      claim["reasons"][0])
        self.assertIsNotNone(episodes[4610]["structure_sequence"],
                             "the participant's own hit still qualifies")

    def test_structure_hit_before_the_closure_is_unverified(self):
        hits = [{"time": 2.2, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits)[4610]
        self.assertIsNone(a["structure_sequence"])
        claim = a["structure_unverified"]
        self.assertIsNotNone(claim)
        self.assertIn("is not later than the engagement-end instant",
                      claim["reasons"][0])
        self.assertEqual(claim["hits"], 1)

    def test_structure_hit_before_the_resumption_is_measured_is_unverified(self):
        """The hit follows the closure but only one alive sample lies between
        them: the resumption had not been measured yet when it landed."""
        hits = [{"time": 3.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits)[4610]
        self.assertIsNone(a["structure_sequence"])
        claim = a["structure_unverified"]
        self.assertIn("only 1 contiguous observed-alive census sample(s) lie "
                      "between the engagement end and the hit",
                      claim["reasons"][0])

    def test_friendly_structure_target_is_unverified(self):
        hits = [{"time": 4.5, "structure": 3540, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits, teams={3539: 2, 3540: 1})[4610]
        self.assertIsNone(a["structure_sequence"])
        claim = a["structure_unverified"]
        self.assertIn("structure 3540 is on the actor's own team 1",
                      claim["reasons"][0])
        self.assertEqual(a["structure_hits"][0]["structure_team"], 1)

    def test_structure_hit_after_the_actor_own_death_cannot_qualify(self):
        hits = [{"time": 6.0, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        deaths = [{"time": 2.4, "victim": 4611, "killer": 4610},
                  {"time": 5.0, "victim": 4610, "killer": 4611}]
        a = self._sequence_inputs(hits=hits, deaths=deaths)[4610]
        self.assertIsNone(a["structure_sequence"])
        claim = a["structure_unverified"]
        self.assertIn("post-death hit cannot qualify", claim["reasons"][0])
        self.assertEqual(a["resumed_after_combat"], 2.0,
                         "the resumption measured before the death stands")

    def test_later_death_does_not_erase_a_valid_structure_hit(self):
        hits = [{"time": 4.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        deaths = [{"time": 2.4, "victim": 4611, "killer": 4610},
                  {"time": 8.0, "victim": 4610, "killer": 4612}]
        a = self._sequence_inputs(hits=hits, deaths=deaths)[4610]
        self.assertEqual(a["death_time"], 8.0)
        self.assertEqual(a["death_evidence"], "death-publication")
        self.assertIsNotNone(a["structure_sequence"],
                             "an already valid hit is not erased by a later "
                             "death")
        self.assertEqual(a["structure_sequence"]["time"], 4.5)
        self.assertEqual(a["resumed_after_combat"], 2.0)
        self.assertIsNone(a["structure_unverified"])

    def test_structure_team_not_carried_is_unverified_not_fabricated(self):
        hits = [{"time": 4.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits, teams={})[4610]
        self.assertIsNone(a["structure_sequence"],
                          "an unknown target team is never assumed opposing")
        claim = a["structure_unverified"]
        self.assertIn("does not carry a team for structure 3539",
                      claim["reasons"][0])
        self.assertIsNone(a["structure_hits"][0]["structure_team"])
        self.assertEqual(a["resumed_after_combat"], 2.0,
                         "the accepted resumption itself is unaffected")

    def test_invalid_structure_team_is_unverified_not_credited(self):
        """Correction: only the integers 1 and 2 name a side. A carried team
        that is neither the actor's nor one of the two real teams — team 3 in
        the parent's witness — is not evidence of an opposing structure."""
        hits = [{"time": 4.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits, teams={3539: 3})[4610]
        self.assertIsNone(a["structure_sequence"],
                          "team 3 is not the opposing team")
        claim = a["structure_unverified"]
        self.assertIn("is not one of the two teams of the match",
                      claim["reasons"][0])
        self.assertEqual(claim["hits"], 1)
        self.assertEqual(a["structure_hits"][0]["structure_team"], 3,
                         "the raw team the record carried is preserved")
        self.assertEqual(a["resumed_after_combat"], 2.0,
                         "the accepted resumption is unaffected")

    def test_boolean_structure_team_is_unverified_not_credited(self):
        """A boolean is not a team identity even though ``False == 0`` and
        ``True == 1`` in Python. ``False`` is the value that a bare
        "different from the actor's team" check reads as an opposing side."""
        hits = [{"time": 4.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits, teams={3539: False})[4610]
        self.assertIsNone(a["structure_sequence"],
                          "a boolean team is not an opposing side")
        self.assertIn("which is not a team identity",
                      a["structure_unverified"]["reasons"][0])
        self.assertIs(a["structure_hits"][0]["structure_team"], False,
                      "the raw value the record carried is preserved")
        self.assertEqual(a["resumed_after_combat"], 2.0)

    def test_non_integer_structure_team_is_unverified_not_credited(self):
        """A string that spells a team number is a formatting accident, not a
        team identity."""
        hits = [{"time": 4.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits, teams={3539: "2"})[4610]
        self.assertIsNone(a["structure_sequence"])
        self.assertIn("which is not a team identity",
                      a["structure_unverified"]["reasons"][0])
        self.assertEqual(a["resumed_after_combat"], 2.0)

    def test_absence_before_the_hit_breaks_the_sequence(self):
        """The parent's witness: the actor is observed alive at t=3 and t=4,
        the census carries an ABSENCE at t=5, and the hit lands at t=6. The
        resumption stays accepted, but the interval does not reach the hit, so
        the sequence is unverified with that reason."""
        tracked = self._sequence_lane()
        tracked[4610]["timeline"] = [
            (1.0, 10.0, 2.0, 300.0, True),
            (2.0, 12.0, 2.0, 300.0, True),
            (3.0, 14.0, 2.0, 280.0, True),
            (4.0, 16.0, 2.0, 280.0, True),
            (5.0, 16.0, 2.0, 280.0, False)]
        hits = [{"time": 6.0, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits, tracked=tracked)[4610]
        self.assertEqual(a["resumed_after_combat"], 2.0,
                         "the historical resumption interval still stands")
        self.assertEqual(a["alive_samples_after_end"], 2)
        self.assertEqual(a["absent_since"], 5.0)
        self.assertTrue(a["structure_hit"], "the raw hit is preserved")
        self.assertIsNone(a["structure_sequence"],
                          "an absence between the resumption and the hit "
                          "cannot be bridged")
        self.assertIn("does not reach the hit",
                      a["structure_unverified"]["reasons"][0])

    def test_unknown_hp_before_the_hit_breaks_the_sequence(self):
        """An unknown hp is not alive evidence, so it breaks the run even
        though the actor's position kept advancing."""
        tracked = self._sequence_lane()
        tracked[4610]["timeline"] = [
            (1.0, 10.0, 2.0, 300.0, True),
            (2.0, 12.0, 2.0, 300.0, True),
            (3.0, 14.0, 2.0, 280.0, True),
            (4.0, 16.0, 2.0, 280.0, True),
            (5.0, 18.0, 2.0, None, True)]
        hits = [{"time": 6.0, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        a = self._sequence_inputs(hits=hits, tracked=tracked)[4610]
        self.assertEqual(a["resumed_after_combat"], 2.0,
                         "the resumption measured before the unknown sample "
                         "stands")
        self.assertIsNone(a["structure_sequence"])
        self.assertIn("does not reach the hit",
                      a["structure_unverified"]["reasons"][0])

    def test_later_death_after_a_valid_uninterrupted_hit_still_stands(self):
        """Correction check: the gap rule must not cost the preserved
        later-death positive — the run reaches the hit, and the death is after
        it."""
        hits = [{"time": 4.5, "structure": 3539, "attacker": 4610,
                 "delta": -40.0}]
        deaths = [{"time": 2.4, "victim": 4611, "killer": 4610},
                  {"time": 8.0, "victim": 4610, "killer": 4612}]
        a = self._sequence_inputs(hits=hits, deaths=deaths)[4610]
        sequence = a["structure_sequence"]
        self.assertIsNotNone(sequence)
        self.assertEqual(sequence["samples_before_hit"], 2)
        self.assertEqual(sequence["march_before_hit"], 2.0)
        self.assertEqual(a["death_time"], 8.0)
        self.assertIsNone(a["structure_unverified"])
        self.assertEqual(a["alive_samples_after_end"] >= 2, True)


class TestSlotAttribution(unittest.TestCase):
    """The compact-slot ownership rule the 1016 attribution rests on.

    Contract (server/actor_slots.py and every despawn path that feeds it):
    1010 binds an actor to its slot, **1035 releases it**, and 1073 retires
    the presentation without releasing — a hero keeps its actor and compact
    slot across a lone 1073 so resurrection reuses them. All payloads here
    are synthetic structures built with struct.pack; no capture is read.
    """

    @staticmethod
    def _spawn(t, slot, eid, connection=1):
        """126-byte 1010 full update: eid at +8, compact slot at +116."""
        body = bytearray(126)
        struct.pack_into(">I", body, 0, 385)
        struct.pack_into(">I", body, 4, sc.VOLLEY_CLASS)
        struct.pack_into(">I", body, 8, eid)
        struct.pack_into(">I", body, 112, eid)
        body[116] = slot
        return {"time": t, "direction": "s2c", "connection": connection,
                "opcode": sc.OP_ENTITY_FULL_UPDATE,
                "payload": bytes(body).hex()}

    @staticmethod
    def _retire(t, eid, connection=1):
        """1073 retirement / hero corpse hide: [u32 eid][u16 0]."""
        return {"time": t, "direction": "s2c", "connection": connection,
                "opcode": sc.OP_ACTOR_RETIRE,
                "payload": struct.pack(">IH", eid, 0).hex()}

    @staticmethod
    def _despawn(t, eid, connection=1):
        """1035 actor removal — the release publication."""
        return {"time": t, "direction": "s2c", "connection": connection,
                "opcode": sc.OP_ACTOR_DESPAWN,
                "payload": struct.pack(">IH", eid, 0).hex()}

    def test_slot_reuse_attributes_to_owner_at_the_time(self):
        records = [self._spawn(1.0, 5, 4610), self._despawn(2.0, 4610),
                   self._spawn(3.0, 5, 4620)]
        events = sc.build_slot_timeline(records, connection=1)
        self.assertEqual(sc.slot_owner_at(events, 5, 1.5), 4610)
        self.assertEqual(sc.slot_owner_at(events, 5, 2.5), None)
        self.assertEqual(sc.slot_owner_at(events, 5, 3.5), 4620,
                         "slot reuse must attribute to the CURRENT owner")

    def test_hero_retirement_keeps_the_slot_until_the_despawn(self):
        """A hero's 1073 hides the corpse; only its 1035 frees the slot, and
        the freed slot is then reusable."""
        records = [self._spawn(1.0, 5, 1500),      # hero binds slot 5
                   self._retire(2.0, 1500),        # corpse hide: NO release
                   self._despawn(3.0, 1500),       # the real release
                   self._spawn(4.0, 5, 4620)]      # reuse
        events = sc.build_slot_timeline(records, connection=1)
        self.assertEqual([(t, kind) for t, kind, _s, _e in events],
                         [(1.0, "assign"), (3.0, "release"), (4.0, "assign")],
                         "a lone 1073 publishes no release event")
        self.assertEqual(sc.slot_owner_at(events, 5, 1.5), 1500)
        self.assertEqual(sc.slot_owner_at(events, 5, 2.5), 1500,
                         "the retired hero still owns its slot at 2.5 s")
        self.assertEqual(sc.slot_owner_at(events, 5, 3.0), None,
                         "the 1035 instant frees the slot (inclusive bound)")
        self.assertEqual(sc.slot_owner_at(events, 5, 4.5), 4620,
                         "the released slot is reused by the later actor")

    def test_hero_retirement_alone_never_frees_the_slot(self):
        """The same hero chain without a 1035: ownership must persist, which
        is what lets resurrection keep addressing the same slot."""
        records = [self._spawn(1.0, 5, 1500), self._retire(2.0, 1500)]
        events = sc.build_slot_timeline(records, connection=1)
        self.assertEqual([(t, kind) for t, kind, _s, _e in events],
                         [(1.0, "assign")])
        self.assertEqual(sc.slot_owner_at(events, 5, 30.0), 1500,
                         "a retired-but-not-despawned actor still owns it")

    def test_minion_retire_then_despawn_pair_releases_at_the_despawn(self):
        """The measured minion chain is (1073, 1035) back to back: the release
        timestamp is the 1035 instant, not the retirement before it."""
        records = [self._spawn(1.0, 59, 4626),
                   self._retire(2.0, 4626),
                   self._despawn(2.0004, 4626),
                   self._spawn(3.0, 59, 4645)]
        events = sc.build_slot_timeline(records, connection=1)
        self.assertEqual([(round(t, 6), kind) for t, kind, _s, _e in events],
                         [(1.0, "assign"), (2.0004, "release"),
                          (3.0, "assign")])
        self.assertEqual(sc.slot_owner_at(events, 59, 2.0), 4626,
                         "the retiring minion still owns its slot")
        self.assertEqual(sc.slot_owner_at(events, 59, 2.0004), None)
        self.assertEqual(sc.slot_owner_at(events, 59, 2.5), None)
        self.assertEqual(sc.slot_owner_at(events, 59, 3.5), 4645)

    def test_another_connections_events_cannot_clear_or_bind_ownership(self):
        records = [self._spawn(1.0, 5, 1500),
                   self._despawn(2.0, 1500, connection=2),
                   self._retire(2.5, 1500, connection=2),
                   self._spawn(3.0, 7, 4999, connection=2)]
        events = sc.build_slot_timeline(records, connection=1)
        self.assertEqual(events, [(1.0, "assign", 5, 1500)],
                         "only this connection's publications are evidence")
        self.assertEqual(sc.slot_owner_at(events, 5, 3.0), 1500,
                         "another connection's 1035 cannot clear the owner")
        self.assertEqual(sc.slot_owner_at(events, 7, 3.5), None,
                         "another connection's 1010 cannot bind a slot")

    def test_without_a_connection_filter_every_connection_counts(self):
        records = [self._spawn(1.0, 5, 1500),
                   self._spawn(3.0, 7, 4999, connection=2),
                   self._despawn(4.0, 1500, connection=2)]
        events = sc.build_slot_timeline(records)
        self.assertEqual(sc.slot_owner_at(events, 7, 3.5), 4999)
        self.assertEqual(sc.slot_owner_at(events, 5, 4.5), None)


def run_trial(base: Path, trial: int, *, prepare=None, scenario="skye-b"):
    """ONE full writer trial (the unit ``produce_pair`` runs twice) through
    the real ``run_client`` entry point; returns ``(result, harness)`` where
    ``result`` is whatever the writer produced — PASS or structured FAIL.

    ``prepare(harness)`` runs after the fake session is built and before the
    trial starts, which is how a test injects an endpoint-receipt defect.
    ``scenario`` selects the cast slot the harness and the writer run (the
    fake session emits that slot's native action and timer tag, and only B/C
    require a Target Lock).
    """
    import unittest.mock as mock
    qa_dir = base / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / "state.json").write_text(json.dumps({"tick": 100}),
                                       encoding="utf-8")
    declared_profile = json.loads(json.dumps(
        {**sc.DEFAULT_PROFILE,
         "declared_fixture": {
             **sc.DEFAULT_PROFILE["declared_fixture"],
             "skye_level": 6,
             "skye_ranks": {"0": 1, "1": 1, "2": 1},
             "skye_points": 1,
             "enemy_points": 1,
             "enemy_level": 1}}))
    profile_path = base / "profile-declared.json"
    profile_path.write_text(json.dumps(declared_profile), encoding="utf-8")
    harness = Harness(scenario)
    if prepare is not None:
        prepare(harness)
    real_qa_class = sc.QaSession

    def fake_qa(qa_dir, *, submit=None):
        return real_qa_class(qa_dir, submit=harness.qa.submit)

    out_dir = base / f"trial-{trial}"
    with mock.patch.object(sc, "QaSession", fake_qa), \
            mock.patch.object(sc, "Adb", lambda serial: harness.adb):
        result = sc.run_client(scenario, types.SimpleNamespace(
            adb_serial="emulator-5554", qa_dir=str(qa_dir),
            wire_trace=str(harness.trace_path), timeout=2.0,
            output=str(out_dir), connection=424242,
            client_profile=str(profile_path), reference=None))
    return result, harness


def produce_pair(base: Path, scenario="skye-b"):
    """Two full driver trials (separate fake harnesses, one shared QA dir)
    returning their SERIALIZED results read back from disk — the same bytes
    the public compare-pair CLI consumes."""
    results = []
    for trial in (1, 2):
        result, _harness = run_trial(base, trial, scenario=scenario)
        assert result["status"] == "PASS", result.get("failure_detail")
        serialized = json.loads(
            Path(result["result_path"]).read_text(encoding="utf-8"))
        results.append(serialized)
    return results[0], results[1]


class TestFixtureContract(unittest.TestCase):
    """Review item 1: the declared fixture gates input; pair comparability."""

    def _contract(self, **overrides):
        profile = {**sc.DEFAULT_PROFILE, "declared_fixture": {
            "skye_level": 6,
            "skye_ranks": {"0": 1, "1": 1, "2": 1},
            # matches the post-preparation measured state — production
            # SandboxQA.pump(resources) creates ability_points=1 on
            # both heroes; FakeQa.resources mirrors that.
            "skye_points": 1,
            "enemy_points": 1,
            "skye_energy_policy": "full",
            "skye_hp_policy": "full",
            "enemy_level": 6,
            "enemy_hp_policy": "full",
        }}
        profile["declared_fixture"].update(overrides)
        return sc.build_fixture_contract(profile, "A")

    def _manifest(self, **overrides):
        manifest = {
            "match_id": "synthetic-match",
            "skye": {"level": 6, "ranks": {"0": 1, "1": 1, "2": 1},
                     "ability_points": 1, "hp": 1200.0, "max_hp": 1200.0,
                     "energy": 560.0, "max_energy": 560.0, "statuses": [],
                     "alive": True,
                     "team": 1, "hero_id": sc.SKYE_HERO_ID, "eid": 1500,
                     "x": 0.0, "y": 38.0, "inventory": [],
                     "default_items": []},
            "enemy": {"eid": 1517, "hero_id": 243, "level": 6,
                      "hp": 4000.0, "max_hp": 4000.0, "x": 4.0, "y": 38.0,
                      "alive": True, "team": 2,
                      "energy": 200.0, "max_energy": 200.0,
                      "ability_points": 1,
                      "inventory": [], "default_items": [], "statuses": [],
                      "ranks": {"0": 0, "1": 0, "2": 0}},
            "cooldowns": {},
            "slot": "A",
            "scenario": "skye-a",
            "declared_fixture": {"skye_energy_policy": "full",
                                 "skye_hp_policy": "full",
                                 "enemy_hp_policy": "full",
                                 "skye_level": 6, "enemy_level": 6,
                                 "skye_ranks": {"0": 1, "1": 1, "2": 1},
                                 "skye_points": 1, "enemy_points": 1},
        }
        manifest["skye"].update(overrides.get("skye", {}))
        manifest["enemy"].update(overrides.get("enemy", {}))
        return manifest

    def test_declared_state_passes_validation(self):
        failures = sc.validate_fixture(self._manifest(), self._contract())
        self.assertEqual(failures, [])

    def test_level_mismatch_fails_before_input(self):
        manifest = self._manifest(skye={"level": 7})
        failures = sc.validate_fixture(manifest, self._contract())
        self.assertTrue(any("level 7" in f for f in failures))
        enemy_manifest = self._manifest(enemy={"level": 7})
        failures = sc.validate_fixture(enemy_manifest, self._contract())
        self.assertTrue(any("enemy level" in f for f in failures))

    def test_resource_clamp_mismatch_is_not_silent(self):
        """QA resources clamp to maxima: an out-of-range EXACT declaration
        must fail validation, never silently accept another value."""
        manifest = self._manifest(skye={"energy": 560.0, "max_energy": 560.0})
        contract = self._contract(
            skye_energy_policy="exact", skye_energy_exact=1000.0)
        failures = sc.validate_fixture(manifest, contract)
        self.assertTrue(any("energy" in f for f in failures),
                        "the clamp must surface as a declared-vs-measured "
                        "failure")

    def test_full_policy_requires_maximum(self):
        manifest = self._manifest(skye={"energy": 500.0, "max_energy": 560.0})
        failures = sc.validate_fixture(manifest, self._contract())
        self.assertTrue(any("not at its full" in f for f in failures))

    def test_position_tolerance_boundary(self):
        manifest = self._manifest(skye={"x": 1.5, "y": 38.0})
        failures = sc.validate_fixture(manifest, self._contract())
        self.assertEqual(failures, [], "exactly at tolerance must pass")
        manifest = self._manifest(skye={"x": 1.6, "y": 38.0})
        failures = sc.validate_fixture(manifest, self._contract())
        self.assertTrue(failures, "beyond tolerance must fail")

    def test_active_status_fails_validation(self):
        manifest = self._manifest(
            skye={"statuses": [{"type": "STUN", "remaining": 1.0}]})
        failures = sc.validate_fixture(manifest, self._contract())
        self.assertTrue(any("statuses" in f for f in failures))

    def _pair_manifests(self):
        return self._manifest(), self._manifest()

    def _pair_results(self, a, b, contract=None):
        """Two schema-2 results over the given manifests with full provenance.

        The carried fixture_contract is the contract that ``validate_fixture``
        will use; the validator MUST consume the carried contract, not a
        reconstruction from defaults. If the caller does not supply a
        contract, we synthesize one from a default profile + the manifest's
        declared_fixture.
        """
        prov = {"source_startup_digest": "s" * 64,
                "source_current_digest": "s" * 64,
                "tape_loaded": {"records": 0, "sha256": "t" * 64},
                "env_config": {},
                "client_version": {"version_name": "4.13.4",
                                   "version_code": 147219},
                "qa_dir": "q",
                "tape_file_identity": {"file_sha256": "u" * 64},
                # required schema-3 process/startup/session linkage, coherent
                # with the synthetic manifests' own match_id
                "diagnostics": {"pid": 4242, "startup_at": 1.0,
                                "match_id": "synthetic-match",
                                "phase": "world", "match_finished": False,
                                "tick": 100, "time": 5.0},
                # required schema-4 end-of-trial receipt: same process,
                # startup and match, strictly later tick/time
                "diagnostics_end": {"pid": 4242, "startup_at": 1.0,
                                    "match_id": "synthetic-match",
                                    "phase": "world", "match_finished": False,
                                    "tick": 140, "time": 7.0}}
        # synthesize the contract from a profile carrying the manifest's
        # declared_fixture (the validator must consume THIS contract, not
        # one rebuilt from defaults)
        profile = {**sc.DEFAULT_PROFILE,
                   "declared_fixture": a.get("declared_fixture", {})}
        if contract is None:
            contract = sc.build_fixture_contract(profile, "A")
        base = {"schema_version": sc.PAIR_SCHEMA_VERSION, "status": "PASS",
                "stages": {k: {"status": "PASS"} for k in (
                    "SETUP", "UI_COMMAND_SUBMITTED", "CLIENT_INPUT_OBSERVED",
                    "SERVER_ACKNOWLEDGED", "AUTHORITATIVE_EFFECT")},
                "provenance": prov,
                "fixture_contract": contract}
        va = dict(base); va["scenario"] = "skye-a"; va["fixture_manifest"] = a
        vb = dict(base); vb["scenario"] = "skye-a"; vb["fixture_manifest"] = b
        vb["fixture_contract"] = contract
        return va, vb

    def _real_pair(self, base: Path):
        """Two driver-produced serialized results sharing one QA directory,
        from separate full trials (the TestPairCliRoundTrip producer)."""
        return produce_pair(base)

    def test_real_driver_pair_is_controlled(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-fixture-pair-"))
        try:
            va, vb = self._real_pair(base)
            verdict = sc.compare_pair(va, vb)
            self.assertTrue(verdict["controlled_pair"], verdict["failures"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_real_pair_declared_level99_vs_measured6_fails(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-fixture-pair-"))
        try:
            va, vb = self._real_pair(base)
            va["fixture_manifest"]["declared_fixture"]["skye_level"] = 99
            verdict = sc.compare_pair(va, vb)
            self.assertFalse(verdict["controlled_pair"])
            self.assertTrue(any("declared" in f or "level" in f
                                for f in verdict["failures"]),
                            verdict["failures"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_real_pair_missing_provenance_fails(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-fixture-pair-"))
        try:
            va, vb = self._real_pair(base)
            va["provenance"]["tape"] = {"path": "tape.bin", "present": False}
            vb["provenance"]["source_current_digest"] = "0" * 64
            verdict = sc.compare_pair(va, vb)
            self.assertFalse(verdict["controlled_pair"])
            self.assertTrue(any("tape" in f or "source" in f
                                for f in verdict["failures"]),
                            verdict["failures"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_real_pair_outcome_mutation_fails(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-fixture-pair-"))
        try:
            va, vb = self._real_pair(base)
            attrib = (va["observations"]["damage_classification"]
                      ["attributed"])
            attrib[0]["delta"] = round(attrib[0]["delta"] * 1.10, 4)
            verdict = sc.compare_pair(va, vb)
            self.assertFalse(verdict["controlled_pair"],
                             "a 10% mutated outcome must fail exact totals")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_nan_manifest_fails_the_pair(self):
        a, b = self._pair_manifests()
        a["skye"]["hp"] = float("nan")
        va, vb = self._pair_results(a, b)
        verdict = sc.compare_pair(va, vb)
        self.assertFalse(verdict["controlled_pair"],
                         "NaN gameplay values must fail the pair")

    def test_nan_manifest_fails_the_pair(self):
        a, b = self._pair_manifests()
        a["skye"]["hp"] = float("nan")
        va, vb = self._pair_results(a, b)
        verdict = sc.compare_pair(va, vb)
        self.assertFalse(verdict["controlled_pair"],
                         "NaN gameplay values must fail the pair")

    def test_basic_only_trace_never_satisfies_ability_effect(self):
        harness = Harness("skye-a")
        try:
            def basics_only():
                harness.emit({"time": time.time(), "direction": "c2s",
                              "connection": 424242, "opcode": 1042,
                              "payload": build_ground_cast_payload(0)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1046,
                              "payload": build_position_event(SKYE_EID, 0)})
                for _ in range(6):
                    harness.emit({"time": time.time(), "direction": "s2c",
                                  "connection": 424242, "opcode": 1037,
                                  "payload": build_basic_1037()})
                    harness.emit({"time": time.time(), "direction": "s2c",
                                  "connection": 424242, "opcode": 1054,
                                  "payload": build_damage(
                                      ENEMY_EID, SKYE_EID, -61.88, basic=True)})
                harness.qa.state["heroes"][0]["energy"] = 930.0
                harness.qa.state["heroes"][0]["ability_cooldowns"]["0"] = 5.0

            harness.on_swipe = basics_only
            driver = harness.driver(timeout=1.5)
            with self.assertRaises(sc.ClientStageFailure) as caught:
                driver.run_cast_scenario("A", requires_lock=False)
            self.assertEqual(caught.exception.stage, "AUTHORITATIVE_EFFECT")
            self.assertIn("basic-only", caught.exception.detail)
            classification = driver.observations["damage_classification"]
            self.assertEqual(classification["attributed"], [])
            self.assertEqual(len(classification["basic_hits"]), 6)
        finally:
            harness.cleanup()

    def test_interleaved_basics_are_separated_by_tail(self):
        """Ability pulses interleaved with basics: only COMBAT_DELTA_TAIL
        pulses count, whatever the emission order (review failures:
        skye-b-repeat2 / skye-c-live6 mislabeled both directions)."""
        harness = Harness("skye-a")
        try:
            def interleaved():
                harness.emit({"time": time.time(), "direction": "c2s",
                              "connection": 424242, "opcode": 1042,
                              "payload": build_ground_cast_payload(0)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1046,
                              "payload": build_position_event(SKYE_EID, 0)})
                # basic, ability, basic, ability x2, ambiguous, heal
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  ENEMY_EID, SKYE_EID, -61.88, basic=True)})
                harness.emit({"time": time.time(), "direction": "s2c",
                                  "connection": 424242, "opcode": 1054,
                                  "payload": build_damage(
                                      ENEMY_EID, SKYE_EID, -42.2)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1037,
                              "payload": build_basic_1037()})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  ENEMY_EID, SKYE_EID, -61.88, basic=True)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  ENEMY_EID, SKYE_EID, -42.2)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  ENEMY_EID, SKYE_EID, -42.2)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  ENEMY_EID, SKYE_EID, -16.36, basic=True)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  ENEMY_EID, SKYE_EID, 5.0)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  ENEMY_EID, SKYE_EID, -9.0)[:24] + "00" + "0000000000"})
                harness.qa.state["heroes"][0]["energy"] = 930.0
                harness.qa.state["heroes"][0]["ability_cooldowns"]["0"] = 5.0

            harness.on_swipe = interleaved
            driver = harness.driver(timeout=1.5)
            driver.run_cast_scenario("A", requires_lock=False)
            classification = driver.observations["damage_classification"]
            self.assertEqual(len(classification["attributed"]), 3)
            self.assertEqual(len(classification["basic_hits"]), 3)
            self.assertEqual(len(classification["non_damage"]), 1)
            self.assertEqual(len(classification["ambiguous"]), 1)
        finally:
            harness.cleanup()


class TestCaptureLifecycle(unittest.TestCase):
    def test_recorder_starts_before_first_gesture_and_finalizes(self):
        """Review fix 1: recording covers the authored sequence; ordering is
        observable through the fake seams (not just a video filename)."""
        harness = Harness("skye-b")
        try:
            driver = harness.driver(timeout=3.0)
            result = driver.run_cast_scenario("B", requires_lock=True)
            self.assertEqual(result["status"], "PASS")
            presentation = driver.observations["presentation"]
            self.assertTrue(presentation["finalized"])
            self.assertIsNotNone(presentation["video"])
            first_gesture = min(g["at"] for g in driver.gestures)
            self.assertLessEqual(presentation["started_at"], first_gesture,
                                 "the recorder must start before the first "
                                 "authored UI gesture")
            self.assertGreaterEqual(presentation["ended_at"],
                                    max(g["at"] for g in driver.gestures))
        finally:
            harness.cleanup()

    def test_failure_keeps_completed_stages_and_receipts(self):
        """Review fix 2: a stage failure retains completed stages, gestures,
        observations and QA receipts instead of discarding them."""
        harness = Harness("skye-b")
        try:
            harness.on_swipe = lambda: None        # gesture goes nowhere
            (harness.base / "qa").mkdir(exist_ok=True)
            (harness.base / "qa" / "state.json").write_text(
                json.dumps({"tick": 100}), encoding="utf-8")
            declared_profile = json.loads(json.dumps(
                {**sc.DEFAULT_PROFILE,
                 "declared_fixture": {
                     **sc.DEFAULT_PROFILE["declared_fixture"],
                     "skye_level": 6,
                     "skye_ranks": {"0": 1, "1": 1, "2": 1},
                     "skye_points": 1,
                     "enemy_level": 1}}))
            profile_path = harness.base / "profile-declared.json"
            profile_path.write_text(json.dumps(declared_profile),
                                    encoding="utf-8")
            import unittest.mock as mock

            real_qa_class = sc.QaSession

            def fake_qa(qa_dir, *, submit=None):
                return real_qa_class(qa_dir, submit=harness.qa.submit)

            with mock.patch.object(sc, "QaSession", fake_qa), \
                mock.patch.object(sc, "Adb", lambda serial: harness.adb):
                result = sc.run_client("skye-b", types.SimpleNamespace(
                    adb_serial="emulator-5554", qa_dir=str(harness.base / "qa"),
                    wire_trace=str(harness.trace_path), timeout=1.0,
                    output=None, connection=424242, client_profile=str(profile_path),
                    reference=None))
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(
                result["first_failed_stage"], "CLIENT_INPUT_OBSERVED",
                result.get("failure_detail"))
            self.assertTrue(result["gestures"], "submitted gestures retained")
            self.assertTrue(result["stages"]["SETUP"]["status"] in
                            ("PASS", "PENDING"),
                            "completed setup stage must survive the failure")
            self.assertNotIn("never left the client",
                             result["failure_detail"],
                             "missing trace evidence must not assert client-side "
                             "causality")
        finally:
            harness.cleanup()

    def test_wrong_connection_records_are_ignored(self):
        """Review fix 3: ack/damage on another stream cannot satisfy this
        trial's intended action."""
        harness = Harness("skye-b")
        try:
            original = harness.on_swipe

            def foreign_stream_cast():
                before = len(harness.adb.calls)
                original()
                # rewrite every record just emitted onto a foreign connection
                records = harness.trace_path.read_text(
                    encoding="ascii").splitlines()
                rewritten = []
                for line in records:
                    record = json.loads(line)
                    if record["opcode"] in (1042, 1046, 1162, 1054):
                        record["connection"] = 999999
                    rewritten.append(json.dumps(record, separators=(",", ":")))
                harness.trace_path.write_text(
                    "\n".join(rewritten) + "\n", encoding="ascii")

            harness.on_swipe = foreign_stream_cast
            driver = harness.driver(timeout=1.0)
            driver.connection = 424242
            with self.assertRaises(sc.ClientStageFailure) as caught:
                driver.run_cast_scenario("B", requires_lock=False)
            self.assertEqual(caught.exception.stage, "CLIENT_INPUT_OBSERVED")
        finally:
            harness.cleanup()


class TestMinionPushClient(unittest.TestCase):
    """Named-stage minion observation (review item 3)."""

    def _wire_fake(self, harness):
        """Route QA submit through the fake and support lane_minions."""
        original = harness.qa.submit
        state = {"lane": []}

        def submit(command, *, timeout=5.0, request_id=None):
            name = command.get("command")
            if name == "lane_minions":
                team = command.get("team")
                rows = [dict(row) for row in state["lane"]
                        if not team or row["team"] == team]
                return {"id": request_id, "ok": True,
                        "result": {"count": len(rows), "minions": rows}}
            result = original(command, timeout=timeout, request_id=request_id)
            if name == "snapshot":
                # the census mutates between samples: mirror snapshot rows
                state["snapshot_rows"] = harness.qa.state["nearby_creatures"]
            return result

        return submit, state

    def test_observed_halt_and_no_combat_is_named_partial(self):
        harness = Harness("skye-b")
        try:
            submit, state = self._wire_fake(harness)
            state["lane"] = [
                {"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]
            driver = harness.driver(timeout=1.0)
            driver.qa._submit = submit
            with self.assertRaises(sc.ClientStageFailure) as caught:
                driver.run_minion_push()
            # no movement AND no combat: LANE_APPROACH NOT_OBSERVED; the
            # incoherence check: AUTHORITATIVE_EFFECT + first_failed_stage
            # finalized, never PENDING with no failed stage
            self.assertEqual(caught.exception.stage, "AUTHORITATIVE_EFFECT")
            self.assertEqual(driver.stages["LANE_APPROACH"]["status"],
                             "NOT_OBSERVED")
            self.assertEqual(driver.stages["AUTHORITATIVE_EFFECT"]["status"],
                             "NOT_OBSERVED")
            self.assertIn("incomplete",
                          driver.stages["AUTHORITATIVE_EFFECT"]["detail"])
        finally:
            harness.cleanup()

    def test_movement_plus_combat_without_resumption_is_not_pass(self):
        """Review regression: movement + combat but NO survivor resumption
        must not pass (regression scenario from the review text)."""
        harness = Harness("skye-b")
        try:
            submit, state = self._wire_fake(harness)
            row_a = {"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0}
            row_b = {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0}
            state["lane"] = [row_a, row_b]
            original_submit = harness.qa.submit
            ticks = {"n": 0}

            def census_rows():
                return [dict(r) for r in state["lane"]]

            def submit_with_combat(command, *, timeout=5.0, request_id=None):
                if command.get("command") == "lane_minions":
                    ticks["n"] += 1
                    if ticks["n"] == 3:
                        # first contact: the two minions damage each other,
                        # then stop moving entirely (no resumption)
                        harness.emit({"time": time.time(),
                                      "direction": "s2c",
                                      "connection": 424242, "opcode": 1054,
                                      "payload": build_damage(4610, 4611,
                                                              -30.0)})
                    rows = census_rows()
                    return {"id": request_id, "ok": True,
                            "result": {"count": len(rows), "minions": rows}}
                return original_submit(command, timeout=timeout,
                                       request_id=request_id)

            driver = harness.driver(timeout=1.0)
            driver.profile["minion_push_window_s"] = 6.0
            driver.qa._submit = submit_with_combat
            with self.assertRaises(sc.ClientStageFailure) as caught:
                driver.run_minion_push()
            # combat observed but participants kept fighting (no engagement
            # end -> no proven resumption): coherent incomplete finalization
            self.assertEqual(caught.exception.stage, "AUTHORITATIVE_EFFECT")
            self.assertEqual(driver.stages["OPPOSING_COMBAT"]["status"], "PASS")
            self.assertEqual(
                driver.stages["SURVIVOR_RESUMPTION"]["status"], "NOT_OBSERVED")
            self.assertEqual(driver.stages["AUTHORITATIVE_EFFECT"]["status"],
                             "NOT_OBSERVED")
            window = driver.observations["minion_window"]
            self.assertGreaterEqual(window["minion_vs_minion_events"], 1)
        finally:
            harness.cleanup()

    def test_full_sequence_passes_with_opposing_combat_and_resumption(self):
        harness = Harness("skye-b")
        try:
            submit, state = self._wire_fake(harness)
            row_a = {"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0}
            row_b = {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0}
            state["lane"] = [row_a, row_b]
            harness.qa.state["structures"] = [
                {"eid": 3539, "team": 2, "x": 17.06, "y": 1.93, "hp": 2500.0,
                 "max_hp": 2500.0, "alive": True}]
            original_submit = harness.qa.submit
            ticks = {"n": 0}

            def submit_seq(command, *, timeout=5.0, request_id=None):
                if command.get("command") == "lane_minions":
                    ticks["n"] += 1
                    n = ticks["n"]
                    if n == 2:
                        # contact: the two minions exchange damage, and the
                        # exchange's outcome is then PUBLISHED (1072) rather
                        # than implied by the opponent holding position.
                        harness.emit({"time": time.time(),
                                      "direction": "s2c",
                                      "connection": 424242, "opcode": 1054,
                                      "payload": build_damage(4610, 4611,
                                                              -30.0)})
                        harness.emit({"time": time.time(),
                                      "direction": "s2c",
                                      "connection": 424242,
                                      "opcode": sc.OP_ENTITY_DEATH,
                                      "payload": build_entity_death(4611,
                                                                    4610)})
                        state["lane"] = [row_a]   # killed: leaves the census
                    elif n >= 3:
                        row_a["x"] += 2.0         # the survivor pushes on,
                        if n == 5:                # strictly after that death
                            harness.emit({"time": time.time(),
                                          "direction": "s2c",
                                          "connection": 424242,
                                          "opcode": 1054,
                                          "payload": build_damage(
                                              3539, 4610, -40.0)})
                    rows = [dict(r) for r in state["lane"]]
                    return {"id": request_id, "ok": True,
                            "result": {"count": len(rows), "minions": rows}}
                return original_submit(command, timeout=timeout,
                                       request_id=request_id)

            driver = harness.driver(timeout=1.0)
            driver.profile["minion_push_window_s"] = 6.0
            driver.qa._submit = submit_seq
            result = driver.run_minion_push()
            self.assertEqual(result["status"], "PASS", result["stages"])
            self.assertGreaterEqual(
                result["stages"]["LANE_APPROACH"]["status"], "PASS")
            for stage in ("LANE_APPROACH", "OPPOSING_COMBAT",
                          "SURVIVOR_RESUMPTION"):
                self.assertEqual(result["stages"][stage]["status"], "PASS")
            self.assertGreaterEqual(
                result["observed"]["minion_vs_minion_events"], 1)
        finally:
            harness.cleanup()

    def test_no_minions_visible_is_specific_absence(self):
        harness = Harness("skye-b")
        try:
            submit, state = self._wire_fake(harness)
            state["lane"] = []
            driver = harness.driver(timeout=1.0)
            driver.qa._submit = submit
            with self.assertRaises(sc.ClientStageFailure) as caught:
                driver.run_minion_push()
            self.assertIn("no living lane minions", caught.exception.detail)
        finally:
            harness.cleanup()


# The census sampler's own cadence: the writer sleeps one real second between
# censuses, so the fake world it reads advances one SIMULATED second per
# served census — the relation the live stack has, where a world is never
# frozen between reads. 20 ticks at the production SIM_TICK of 0.05s.
CENSUS_TICKS_PER_SAMPLE = int(round(1.0 / FakeQa.SIM_TICK))


def minion_lane_fake(harness, rows, *, script=None):
    """Fake ``lane_minions`` census over ``rows`` (mutated in place by the
    trial) while every other command keeps the harness's own fake QA.

    ``script(harness, sample, rows)`` runs BEFORE each census is served
    (``sample`` is 1-based), which is how a test scripts approach movement,
    combat damage, the survivors' resumption and a structure hit between
    samples.

    Each served census reports the world clock it was served AT (the same
    ``tick``/``time`` pair ``snapshot`` serves, mirroring
    ``SandboxQA.lane_minions``), so the record carries the simulation time of
    every census frame rather than only the client's wall clock.
    """
    original = harness.qa.submit
    counter = {"samples": 0}

    def submit(command, *, timeout=5.0, request_id=None):
        if command.get("command") == "lane_minions":
            counter["samples"] += 1
            if script is not None:
                script(harness, counter["samples"], rows)
            state = harness.qa.state
            state["tick"] += CENSUS_TICKS_PER_SAMPLE
            state["time"] = state["tick"] * FakeQa.SIM_TICK
            team = command.get("team")
            served = [dict(row) for row in rows
                      if not team or row.get("team") == team]
            return {"id": request_id, "ok": True,
                    "result": {"count": len(served), "minions": served,
                               "tick": state["tick"], "time": state["time"]}}
        return original(command, timeout=timeout, request_id=request_id)

    harness.qa.submit = submit
    return counter


def endpoint_receipt_fake(harness, mutate):
    """Replace ONLY the trial's ENDPOINT diagnostics reply (the second
    ``diagnostics`` submit; the first belongs to the setup boundary) with
    ``mutate(genuine_reply)``. Everything else reaches the fake QA
    untouched, so the defect is injected at the live reply boundary instead
    of by editing the serialized record after the fact."""
    original = harness.qa.submit
    counter = {"diagnostics": 0}

    def submit(command, *, timeout=5.0, request_id=None):
        if command.get("command") == "diagnostics":
            counter["diagnostics"] += 1
            if counter["diagnostics"] == 2:
                genuine = original(command, timeout=timeout,
                                   request_id=request_id)
                return mutate(genuine)
        return original(command, timeout=timeout, request_id=request_id)

    harness.qa.submit = submit
    return counter


def script_lane(harness, sample, rows, *, kill_at=2, march=(3, 4), combat_at=2,
                structure_at=5, structure_eid=3539):
    """One sample of the scripted lane the observation window watches.

    ``combat_at`` is the sample on which the two minions damage each other (a
    1054 between two tracked, opposing-team actors); ``kill_at`` is the
    sample on which the team-2 minion's death is PUBLISHED (1072
    ENTITY_DEATH) and it leaves the census; ``march`` lists the samples on
    which the team-1 survivor takes one step toward the opposing base (they
    must come AFTER ``kill_at``, because only movement strictly after the
    carried end instant counts); ``structure_at`` adds a hit by the survivor
    on ``structure_eid`` — which must also come after at least two marching
    samples, since the structure sequence is only accepted once the
    resumption has already been measured.

    The carried end event is what the survivor-resumption criterion requires.
    A lane where the opponent merely holds position, stops being served, or
    keeps fighting has no disengagement evidence in it, so the scripted
    "positive" lanes publish the exchange's outcome instead of implying an
    ending from the opponent's posture.
    """
    row_a = rows[0]
    row_b = rows[1] if len(rows) > 1 else None
    if sample in march:
        row_a["x"] += 2.0
    if combat_at is not None and sample == combat_at and row_b is not None:
        harness.emit({"time": time.time(), "direction": "s2c",
                      "connection": 424242, "opcode": 1054,
                      "payload": build_damage(row_a["eid"], row_b["eid"],
                                              -30.0)})
    if kill_at is not None and sample == kill_at and row_b is not None:
        harness.emit({"time": time.time(), "direction": "s2c",
                      "connection": 424242, "opcode": sc.OP_ENTITY_DEATH,
                      "payload": build_entity_death(row_b["eid"],
                                                    row_a["eid"])})
        del rows[1]
    if structure_at is not None and sample == structure_at:
        harness.emit({"time": time.time(), "direction": "s2c",
                      "connection": 424242, "opcode": 1054,
                      "payload": build_damage(structure_eid, row_a["eid"],
                                              -40.0)})


def run_minion_trial(base: Path, trial: int, *, rows, structures=(),
                     script=None, prepare=None, window=4.0, clock_offset=0):
    """ONE full writer trial of the ``minion-push`` scenario through the
    real ``run_client`` entry point; returns ``(result, harness)``.

    The scripted lane census, the structures the window can damage and any
    endpoint-receipt defect are installed BEFORE the trial starts, so the
    serialized record is the one the fake session really produced.

    ``clock_offset`` starts the fake WORLD this many ticks further along (a
    world that has been running longer), so a trial can be produced on a
    different absolute clock origin with the same per-frame cadence.
    """
    import unittest.mock as mock
    qa_dir = base / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / "state.json").write_text(json.dumps({"tick": 100}),
                                       encoding="utf-8")
    profile = json.loads(json.dumps(
        {**sc.DEFAULT_PROFILE, "minion_push_window_s": window,
         "camera_settle_s": 0, "declared_fixture": {}}))
    profile_path = base / f"profile-minion-{trial}.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")
    harness = Harness("minion-push")
    if clock_offset:
        harness.qa.state["tick"] += clock_offset
        harness.qa.state["time"] = harness.qa.state["tick"] * FakeQa.SIM_TICK
    harness.qa.state["structures"] = [dict(row) for row in structures]
    minion_lane_fake(harness, rows, script=script)
    if prepare is not None:
        prepare(harness)
    real_qa_class = sc.QaSession

    def fake_qa(qa_dir, *, submit=None):
        return real_qa_class(qa_dir, submit=harness.qa.submit)

    out_dir = base / f"minion-trial-{trial}"
    with mock.patch.object(sc, "QaSession", fake_qa), \
            mock.patch.object(sc, "Adb", lambda serial: harness.adb):
        result = sc.run_client("minion-push", types.SimpleNamespace(
            adb_serial="emulator-5554", qa_dir=str(qa_dir),
            wire_trace=str(harness.trace_path), timeout=2.0,
            output=str(out_dir), connection=424242,
            client_profile=str(profile_path), reference=None))
    return result, harness


MINION_LANE_STRUCTURE = {"eid": 3539, "team": 2, "x": 17.06, "y": 1.93,
                         "hp": 2500.0, "max_hp": 2500.0, "alive": True}
MINION_FRIENDLY_STRUCTURE = {"eid": 3540, "team": 1, "x": 40.0, "y": 1.93,
                             "hp": 2500.0, "max_hp": 2500.0, "alive": True}
MINION_OBSERVED_STAGES = ("LANE_APPROACH", "OPPOSING_COMBAT",
                          "SURVIVOR_RESUMPTION", "STRUCTURE_INTERACTION")


class TestMinionEndpointContinuity(unittest.TestCase):
    """Checkpoint 6: the bounded minion observation window now ends with the
    SAME endpoint diagnostics receipt the cast trial reads — one typed
    receipt, one continuity comparison, one serialized provenance slot.

    A missing, unacknowledged, malformed, restarted or stalled endpoint is an
    EVIDENCE failure on TRIAL_CONTINUITY: the independently observed
    LANE_APPROACH / OPPOSING_COMBAT / SURVIVOR_RESUMPTION /
    STRUCTURE_INTERACTION statuses keep the values they were measured with,
    and a continuity PASS never upgrades an incomplete sequence into a PASS.

    Scope boundary (stated, not glossed): these are minion-push records. The
    public compare-pair CLI still judges records against the cast-trial
    contract (skill slot A/B/C, cast stages PASS, fixture manifest), so a
    minion record is NOT claimed as one half of a controlled pair here.
    """

    def _lane(self):
        return [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]

    def _run(self, base, trial=1, **script_overrides):
        prepare = script_overrides.pop("prepare", None)
        rows = self._lane()
        script = functools.partial(script_lane, **script_overrides)
        return run_minion_trial(
            base, trial, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, prepare=prepare)

    @staticmethod
    def _serialized(result):
        return json.loads(
            Path(result["result_path"]).read_text(encoding="utf-8"))

    def test_full_sequence_serializes_a_coherent_advancing_endpoint(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-endpoint-"))
        result, harness = self._run(base)
        try:
            self.assertEqual(result["status"], "PASS",
                             result.get("failure_detail"))
            record = self._serialized(result)
            for stage in MINION_OBSERVED_STAGES:
                self.assertEqual(record["stages"][stage]["status"], "PASS",
                                 f"{stage}: {record['stages'][stage]}")
            self.assertEqual(record["stages"]["TRIAL_CONTINUITY"]["status"],
                             "PASS", record["stages"]["TRIAL_CONTINUITY"])
            # carried VERBATIM from the two live replies, never reconstructed
            initial = record["provenance"]["diagnostics"]
            endpoint = record["provenance"]["diagnostics_end"]
            self.assertEqual(
                initial, record["observations"]["diagnostics_linkage"])
            self.assertEqual(
                endpoint, record["observations"]["diagnostics_linkage_end"])
            # ONE trial: same process, startup and match at both ends, and
            # the fake world genuinely advanced between the two reads
            self.assertEqual(endpoint["pid"], initial["pid"])
            self.assertEqual(endpoint["startup_at"], initial["startup_at"])
            self.assertEqual(endpoint["match_id"], initial["match_id"])
            self.assertEqual(endpoint["phase"], "world")
            self.assertIs(endpoint["match_finished"], False)
            self.assertGreater(endpoint["tick"], initial["tick"])
            self.assertGreater(endpoint["time"], initial["time"])
            self.assertEqual(endpoint["time"],
                             endpoint["tick"] * FakeQa.SIM_TICK)
            # the endpoint is a SECOND live receipt, not a re-serialized
            # copy of the setup one
            labels = [r["label"] for r in record["qa_receipts"]]
            self.assertEqual(labels.count("endpoint-diagnostics"), 1)
            self.assertEqual(labels.count("provenance-diagnostics"), 1)
            # the observed window really happened before the endpoint read
            self.assertGreater(record["observations"]["minion_window"]
                               ["minion_vs_minion_events"], 0)
            # BOUNDARY: the minion observation scenario is NOT a cast trial —
            # this stage adds endpoint evidence, it does not make the
            # observational scenario satisfy the cast-trial contract (cast
            # stages PASS, skill slot, fixture manifest). Checkpoint 13 made
            # the public CLI DISPATCH a pair of minion records to the minion
            # contract, so the cast contract is asserted directly here and the
            # CLI is asserted to dispatch rather than refuse.
            path = base / "minion-record.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            code, report, stderr = run_compare_cli(path, path)
            self.assertEqual(code, 0, report)
            self.assertEqual(report["dispatched_contract"],
                             "minion observation pair")
            self.assertTrue(report["controlled_pair"])
            cast = sc.compare_cast_pair(record, record)
            self.assertFalse(cast["controlled_pair"])
            joined = json.dumps(cast.get("failures"))
            self.assertIn("required stage UI_COMMAND_SUBMITTED is N/A", joined)
            self.assertIn("fixture_manifest missing/malformed", joined)
            self.assertNotIn("Traceback", stderr)
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_same_match_startup_change_blocks_continuity(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-restart-"))

        def mutate(genuine):
            reply = json.loads(json.dumps(genuine))
            reply["result"]["startup_at"] = \
                genuine["result"]["startup_at"] + 100.0
            return reply

        result, harness = self._run(
            base, prepare=lambda h: endpoint_receipt_fake(h, mutate))
        try:
            self.assertEqual(result["status"], "FAIL",
                             result.get("failure_detail"))
            self.assertEqual(result["first_failed_stage"],
                             "TRIAL_CONTINUITY")
            self.assertEqual(result["stages"]["TRIAL_CONTINUITY"]["status"],
                             "FAIL")
            self.assertIn("startup_at changed within the trial",
                          result["failure_detail"])
            self.assertIn("the process or match restarted mid-trial",
                          result["failure_detail"])
            # same pid and same match: the only difference is the startup
            # identity, and the gameplay stages keep their own statuses
            for stage in MINION_OBSERVED_STAGES:
                self.assertEqual(result["stages"][stage]["status"], "PASS",
                                 f"{stage}: {result['stages'][stage]}")
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_missing_or_pending_endpoint_blocks_continuity(self):
        cases = {
            "pending": ({"pending": True, "result_path": "unused"},
                        "UNVERIFIED", "not acknowledged within the mailbox"),
            "rejected": ({"ok": False, "error": "mailbox refused it"},
                         "UNVERIFIED", "was rejected"),
            "malformed": ({"ok": True, "result": {"pid": 4242}},
                          "FAIL", "not a coherent world session"),
            "non_object": ({"ok": True, "result": [1, 2, 3]},
                           "FAIL", "not an object"),
        }
        for name, (reply_body, status, needle) in cases.items():
            with self.subTest(case=name):
                base = Path(tempfile.mkdtemp(
                    prefix=f"halcyon-minion-{name}-"))

                def mutate(genuine, body=reply_body):
                    reply = {"id": genuine.get("id")}
                    reply.update(json.loads(json.dumps(body)))
                    return reply

                result, harness = self._run(
                    base, prepare=lambda h: endpoint_receipt_fake(h, mutate))
                try:
                    self.assertEqual(result["status"], "FAIL",
                                     result.get("failure_detail"))
                    self.assertEqual(result["first_failed_stage"],
                                     "TRIAL_CONTINUITY")
                    self.assertEqual(
                        result["stages"]["TRIAL_CONTINUITY"]["status"],
                        status, result["stages"]["TRIAL_CONTINUITY"])
                    self.assertIn(needle, result["failure_detail"])
                    # the observed gameplay stages are NOT rewritten by an
                    # endpoint-evidence failure
                    for stage in MINION_OBSERVED_STAGES:
                        self.assertEqual(
                            result["stages"][stage]["status"], "PASS",
                            f"{name}/{stage}: {result['stages'][stage]}")
                    # no endpoint linkage was accepted for this trial
                    self.assertNotIn("diagnostics_linkage_end",
                                     result["observations"])
                finally:
                    harness.cleanup()
                    shutil.rmtree(base, ignore_errors=True)

    def test_incomplete_sequence_stays_incomplete_with_continuity_pass(self):
        """Movement and combat but no survivor resumption and no structure
        interaction: the endpoint continuity PASSES, and the record is still
        an incomplete sequence, never a PASS."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-incomplete-"))
        result, harness = self._run(base, march=(1, 2), combat_at=2,
                                    structure_at=None)
        try:
            self.assertEqual(result["status"], "FAIL",
                             result.get("failure_detail"))
            self.assertEqual(result["stages"]["LANE_APPROACH"]["status"],
                             "PASS")
            self.assertEqual(result["stages"]["OPPOSING_COMBAT"]["status"],
                             "PASS")
            self.assertEqual(
                result["stages"]["SURVIVOR_RESUMPTION"]["status"],
                "NOT_OBSERVED")
            self.assertEqual(
                result["stages"]["STRUCTURE_INTERACTION"]["status"],
                "NOT_OBSERVED")
            # continuity itself was established and is reported as such
            self.assertEqual(result["stages"]["TRIAL_CONTINUITY"]["status"],
                             "PASS",
                             result["stages"]["TRIAL_CONTINUITY"])
            self.assertEqual(result["first_failed_stage"],
                             "AUTHORITATIVE_EFFECT")
            self.assertEqual(
                result["stages"]["AUTHORITATIVE_EFFECT"]["status"],
                "NOT_OBSERVED")
            self.assertIn("incomplete", result["failure_detail"])
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)


class TestMinionSurvivorResumptionEvidence(unittest.TestCase):
    """Checkpoint 10: SURVIVOR_RESUMPTION is measured causally in the
    production observation path. A survivor must itself have fought a tracked
    opposing minion, the engagement must have an evidenced end (an explicit
    1072 death publication, a census sample recording hp <= 0, or the
    opponent observed alive after the last contact), and the resumed march
    must be observed while the actor is explicitly alive. An opponent that
    merely stops appearing in the census makes an UNVERIFIED claim, reported
    as such — never an inferred death or disengagement.

    Offline scripted lane through the existing Harness/writer and the
    production analysis: the census rows and the wire records a test emits
    are the ones the trial really observed, so the record under test is the
    one the fake session produced.
    """

    def _lane(self):
        return [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]

    @staticmethod
    def _serialized(result):
        return json.loads(
            Path(result["result_path"]).read_text(encoding="utf-8"))

    @staticmethod
    def _episode(window, eid):
        return window["per_actor_timelines"][str(eid)]["episode"]

    def test_death_publication_keeps_the_survivor_proven(self):
        """The production shape of a kill: the exchange ends, the killed
        minion disappears from the census and its 1072 publication is the
        death evidence — the survivor's resumption is proven and the four
        measured stages pass."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-kill-"))
        rows = self._lane()

        def script(harness, sample, rows):
            if sample <= 2:
                # both minions close in and exchange at sample 2
                script_lane(harness, sample, rows, kill_at=None, march=(1, 2),
                            combat_at=2, structure_at=None)
                return
            rows[0]["x"] += 2.0              # the survivor pushes on
            if len(rows) > 1:
                rows[1]["x"] += 2.0          # the loser gives ground
            if sample == 3:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242,
                              "opcode": sc.OP_ENTITY_DEATH,
                              "payload": build_entity_death(4611, 4610)})
                del rows[1]                  # killed: gone from the census
            if sample == 6:
                # The hit lands only after the resumption has been measured:
                # samples 3, 4 and 5 observed the survivor alive and marching.
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(3539, 4610, -40.0)})

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, window=8.0)
        try:
            self.assertEqual(result["status"], "PASS",
                             result.get("failure_detail"))
            record = self._serialized(result)
            for stage in MINION_OBSERVED_STAGES:
                self.assertEqual(record["stages"][stage]["status"], "PASS",
                                 f"{stage}: {record['stages'][stage]}")
            window = record["observations"]["minion_window"]
            self.assertEqual(window["survivors_resumed"], 1)
            # the killed participant makes no proven claim of its own: its
            # claim is reported as unverified rather than counted or dropped
            self.assertEqual(window["survivor_claims_unverified"], 1)
            self.assertIn("UNVERIFIED",
                          record["stages"]["SURVIVOR_RESUMPTION"]["detail"])
            survivors = [eid for eid in window["per_actor_timelines"]
                         .keys()
                         if self._episode(window, eid)["resumed_after_combat"]
                         is not None]
            self.assertEqual(survivors, ["4610"])
            survivor = self._episode(window, 4610)
            self.assertTrue(survivor["combat_participant"])
            self.assertEqual(survivor["opponents"], [4611])
            self.assertEqual(survivor["end_evidence"],
                             "opponent-death-publication")
            self.assertEqual(survivor["opponent_closure"]["4611"]
                             .split("@")[0], "death-publication")
            self.assertEqual(survivor["unaccounted_opponents"], [])
            self.assertIsNone(survivor["resumption_unverified"])
            self.assertGreaterEqual(survivor["resumed_after_combat"], 1.0)
            self.assertEqual(survivor["alive_samples_after_end"] >= 2, True)
            # the death evidence is the publication the trial observed
            self.assertEqual(len(window["death_log"]), 1)
            self.assertEqual(window["death_log"][0]["victim"], 4611)
            self.assertEqual(window["death_log"][0]["killer"], 4610)
            loser = self._episode(window, 4611)
            self.assertEqual(loser["death_evidence"], "death-publication")
            self.assertIsNotNone(loser["death_time"])
            self.assertIsNotNone(loser["absent_since"],
                                 "the absence after the death is recorded")
            self.assertIsNone(loser["resumed_after_combat"])
            # the absence really is in the serialized timeline, after the
            # last census sample that still served the actor
            points = window["per_actor_timelines"]["4611"]["points"]
            self.assertTrue(any(point[4] is False for point in points))
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_vanished_opponent_without_death_evidence_is_unverified(self):
        """The boundary case: the opponent's rows stop and the record carries
        no death for it. The survivor claim stays UNVERIFIED and the sequence
        stays incomplete — the absence alone is never read as a death."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-vanish-"))
        rows = self._lane()

        def script(harness, sample, rows):
            if sample <= 2:
                script_lane(harness, sample, rows, kill_at=None, march=(1, 2),
                            combat_at=2, structure_at=None)
                if sample == 2:
                    # The opponent is absent from THIS very census onward, so
                    # the exchange is the last the record carries of it and
                    # nothing observes it alive after the contact.
                    del rows[1]
                return
            rows[0]["x"] += 2.0
            if sample == 4:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(3539, 4610, -40.0)})

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, window=8.0)
        try:
            self.assertEqual(result["status"], "FAIL",
                             result.get("failure_detail"))
            self.assertEqual(
                result["stages"]["SURVIVOR_RESUMPTION"]["status"],
                "NOT_OBSERVED")
            self.assertIn("UNVERIFIED",
                          result["stages"]["SURVIVOR_RESUMPTION"]["detail"])
            self.assertIn("an absence is not a death",
                          result["stages"]["SURVIVOR_RESUMPTION"]["detail"])
            self.assertEqual(
                result["stages"]["STRUCTURE_INTERACTION"]["status"],
                "NOT_OBSERVED",
                "an unproven resumption cannot carry the structure cohort")
            self.assertEqual(result["stages"]["AUTHORITATIVE_EFFECT"]["status"],
                             "NOT_OBSERVED")
            self.assertIn("incomplete", result["failure_detail"])
            record = self._serialized(result)
            window = record["observations"]["minion_window"]
            self.assertEqual(window["survivors_resumed"], 0)
            # two claims the record cannot verify: the survivor's (no end
            # evidence for its opponent) and the vanished opponent's own (it
            # was never observed alive after the exchange either)
            self.assertEqual(window["survivor_claims_unverified"], 2)
            self.assertEqual(window["death_log"], [],
                             "no death publication was observed")
            survivor = self._episode(window, 4610)
            self.assertEqual(survivor["end_evidence"], "unknown")
            self.assertEqual(survivor["unaccounted_opponents"], [4611])
            self.assertIsNone(survivor["resumed_after_combat"])
            claim = survivor["resumption_unverified"]
            self.assertTrue(any("4611" in reason for reason in claim["reasons"]))
            self.assertTrue(any("absence is not a death" in reason
                                for reason in claim["reasons"]))
            # with no carried end there is no closure instant, so no post-end
            # march is measured at all; the movement is still reported as the
            # episode's approach instead of being silently discarded
            self.assertIsNone(claim["march_after"])
            self.assertGreaterEqual(survivor["approach"], 1.0)
            missing = self._episode(window, 4611)
            self.assertIsNone(missing["death_time"],
                              "a missing census row is not a death")
            self.assertIsNotNone(missing["absent_since"])
            points = window["per_actor_timelines"]["4611"]["points"]
            self.assertTrue(any(point[4] is False for point in points),
                            "the absence keeps its instant in the record")
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_movement_before_the_engagement_end_is_not_resumption(self):
        """The opponent opens a second fight with a teammate after this
        actor's own last hit, so the engagement stays open until the
        opponent's DEATH is published. The actor advances during that window:
        the closure instant is the death, and only the samples after it can
        evidence a resumed push — and there the actor is halted."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-open-"))
        rows = [
            {"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
             "max_hp": 300.0, "alive": True},
            {"eid": 4612, "team": 1, "x": 12.0, "y": 2.0, "hp": 300.0,
             "max_hp": 300.0, "alive": True},
            {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
             "max_hp": 300.0, "alive": True}]

        def script(harness, sample, rows):
            actor = rows[0]
            mate = rows[1] if len(rows) > 1 else None
            opponent = rows[2] if len(rows) > 2 else None
            if sample == 1:
                actor["x"] += 2.0
            if sample == 2 and opponent is not None:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(opponent["eid"],
                                                      actor["eid"], -40.0)})
            if sample in (3, 4):
                actor["x"] += 2.0            # advancing while the fight is
            if sample == 5 and opponent is not None:   # still open elsewhere
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(mate["eid"],
                                                      opponent["eid"],
                                                      -60.0)})
                # the fight ends with the opponent's death, PUBLISHED as an
                # event with its own instant
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242,
                              "opcode": sc.OP_ENTITY_DEATH,
                              "payload": build_entity_death(opponent["eid"],
                                                            actor["eid"])})
                del rows[2]

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[], script=script, window=8.0)
        try:
            record = self._serialized(result)
            window = record["observations"]["minion_window"]
            actor = self._episode(window, 4610)
            events = window["combat_log"]
            self.assertTrue(any(event["attacker"] == 4611
                                and event["victim"] == 4612 for event in events),
                            "the opponent's second fight is tracked combat")
            opponent_last = max(event["time"] for event in events
                                if event["attacker"] == 4611)
            self.assertGreaterEqual(
                actor["engagement_end"], opponent_last,
                "the closure is not earlier than the opponent's last "
                "recorded involvement")
            # the closure IS the carried death instant, not the last hit
            self.assertEqual(len(window["death_log"]), 1)
            self.assertAlmostEqual(actor["engagement_end"],
                                   window["death_log"][0]["time"], places=3)
            self.assertGreater(
                actor["engagement_end"], actor["last_combat_time"],
                "the opponent's later death extended the engagement past "
                "this actor's own last hit")
            self.assertGreaterEqual(actor["approach"], 1.0,
                                    "the actor really did advance")
            self.assertEqual(actor["resumed_after_combat"], 0.0,
                             "only the post-closure movement is credited, and "
                             "after the closure the actor held position")
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "NOT_OBSERVED")
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)


class TestMinionStructureSequence(unittest.TestCase):
    """Checkpoint 11: STRUCTURE_INTERACTION is bound to the SAME participant
    whose resumption was accepted. The qualifying hit must be that actor's
    own, later than the resumption already measured from its own contiguous
    observed-alive samples, before its own death, and against a structure
    whose recorded team is the opposing one. A bystander's hit, a friendly
    structure, a hit that precedes the sequence and a post-death hit are all
    carried raw and reported as UNVERIFIED instead of satisfying the stage.

    Offline scripted lane through the existing Harness/writer and the
    production analysis, so the record under test is the one the fake session
    really produced.
    """

    def _lane(self):
        return [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]

    @staticmethod
    def _serialized(result):
        return json.loads(
            Path(result["result_path"]).read_text(encoding="utf-8"))

    @staticmethod
    def _episode(window, eid):
        return window["per_actor_timelines"][str(eid)]["episode"]

    @staticmethod
    def _exchange(harness, rows, actor, opponent, *, kill):
        """The exchange and (when ``kill``) the opponent's death publication,
        which removes that row from the census by IDENTITY."""
        harness.emit({"time": time.time(), "direction": "s2c",
                      "connection": 424242, "opcode": 1054,
                      "payload": build_damage(actor["eid"], opponent["eid"],
                                              -30.0)})
        if kill:
            harness.emit({"time": time.time(), "direction": "s2c",
                          "connection": 424242,
                          "opcode": sc.OP_ENTITY_DEATH,
                          "payload": build_entity_death(opponent["eid"],
                                                        actor["eid"])})
            for index, row in enumerate(rows):
                if row is opponent:
                    del rows[index]
                    break

    def test_same_participant_sequence_passes_and_is_serialized(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-sequence-"))
        rows = self._lane()

        def script(harness, sample, rows):
            script_lane(harness, sample, rows)

        result, harness = run_minion_trial(
            base, 1, rows=rows,
            structures=[MINION_LANE_STRUCTURE, MINION_FRIENDLY_STRUCTURE],
            script=script, window=8.0)
        try:
            self.assertEqual(result["status"], "PASS",
                             result.get("failure_detail"))
            record = self._serialized(result)
            for stage in MINION_OBSERVED_STAGES:
                self.assertEqual(record["stages"][stage]["status"], "PASS",
                                 f"{stage}: {record['stages'][stage]}")
            self.assertEqual(record["stages"]["TRIAL_CONTINUITY"]["status"],
                             "PASS", record["stages"]["TRIAL_CONTINUITY"])
            window = record["observations"]["minion_window"]
            self.assertEqual(window["resumed_cohort_structure_hits"], 1)
            self.assertEqual(window["structure_claims_unverified"], 0)
            # the identity the sequence was bound to is in the record
            self.assertEqual(window["structure_teams"], {"3539": 2, "3540": 1})
            self.assertEqual(window["structure_log"][0]["attacker"], 4610)
            self.assertEqual(window["structure_log"][0]["structure_team"], 2)
            self.assertEqual(window["structure_log"][0]["attacker_team"], 1)
            actor = self._episode(window, 4610)
            sequence = actor["structure_sequence"]
            self.assertIsNotNone(sequence)
            self.assertEqual(sequence["structure"], 3539)
            self.assertEqual(sequence["structure_team"], 2)
            self.assertGreaterEqual(sequence["samples_before_hit"], 2,
                                    "the resumption was measured before it")
            self.assertGreaterEqual(sequence["march_before_hit"], 1.0)
            self.assertGreaterEqual(actor["resumed_after_combat"], 1.0)
            self.assertIsNone(actor["structure_unverified"])
            # the hit really is later than the samples that measured the
            # resumption, in the serialized evidence itself
            hit_time = window["structure_log"][0]["time"]
            measured = [point[0] for point in
                        window["per_actor_timelines"]["4610"]["points"]
                        if point[4] and point[0] < hit_time]
            self.assertGreaterEqual(len(measured), 2)
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_bystander_structure_hit_does_not_satisfy_the_stage(self):
        """The survivor resumes but the turret damage comes from a different
        team-1 minion: the sequence belongs to the participant, so the stage
        stays NOT_OBSERVED while the resumption is untouched."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-bystander-"))
        rows = [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4612, "team": 1, "x": 6.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]
        actor, opponent, bystander = rows

        def script(harness, sample, rows):
            if sample == 1:
                self._exchange(harness, rows, actor, opponent, kill=False)
            if sample == 2:
                self._exchange(harness, rows, actor, opponent, kill=True)
            if sample in (3, 4):
                actor["x"] += 2.0
            if sample == 5:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(3539, bystander["eid"],
                                                      -40.0)})

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, window=8.0)
        try:
            record = self._serialized(result)
            self.assertEqual(record["status"], "FAIL",
                             record.get("failure_detail"))
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "PASS")
            self.assertEqual(record["stages"]["STRUCTURE_INTERACTION"]["status"],
                             "NOT_OBSERVED")
            self.assertIn("UNVERIFIED",
                          record["stages"]["STRUCTURE_INTERACTION"]["detail"])
            self.assertIn("not an opposing-combat participant",
                          record["stages"]["STRUCTURE_INTERACTION"]["detail"])
            self.assertEqual(record["stages"]["TRIAL_CONTINUITY"]["status"],
                             "PASS", record["stages"]["TRIAL_CONTINUITY"])
            window = record["observations"]["minion_window"]
            self.assertEqual(window["resumed_cohort_structure_hits"], 0)
            self.assertEqual(window["structure_claims_unverified"], 1)
            survivor = self._episode(window, 4610)
            self.assertGreaterEqual(survivor["resumed_after_combat"], 1.0)
            self.assertEqual(survivor["structure_hits"], [])
            bystander = self._episode(window, 4612)
            self.assertEqual(bystander["structure_hit"], True,
                             "the bystander's hit is preserved raw")
            self.assertIsNone(bystander["structure_sequence"])
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_friendly_structure_target_does_not_satisfy_the_stage(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-friendly-"))
        rows = self._lane()

        def script(harness, sample, rows):
            actor, opponent = rows[0], rows[1] if len(rows) > 1 else None
            if sample == 1 and opponent is not None:
                self._exchange(harness, rows, actor, opponent, kill=False)
            if sample == 2 and opponent is not None:
                self._exchange(harness, rows, actor, opponent, kill=True)
            if sample in (3, 4):
                actor["x"] += 2.0
            if sample == 5:
                # the SAME participant, the same moment — but on its own
                # team's structure
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(3540, actor["eid"],
                                                      -40.0)})

        result, harness = run_minion_trial(
            base, 1, rows=rows,
            structures=[MINION_LANE_STRUCTURE, MINION_FRIENDLY_STRUCTURE],
            script=script, window=8.0)
        try:
            record = self._serialized(result)
            self.assertEqual(record["status"], "FAIL",
                             record.get("failure_detail"))
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "PASS")
            self.assertEqual(record["stages"]["STRUCTURE_INTERACTION"]["status"],
                             "NOT_OBSERVED")
            self.assertIn("own team", record["stages"]
                          ["STRUCTURE_INTERACTION"]["detail"])
            window = record["observations"]["minion_window"]
            actor = self._episode(window, 4610)
            self.assertIsNone(actor["structure_sequence"])
            self.assertEqual(actor["structure_hits"][0]["structure"], 3540)
            self.assertEqual(actor["structure_hits"][0]["structure_team"], 1)
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_structure_hit_before_the_sequence_does_not_satisfy_the_stage(self):
        """The hit lands while the exchange is still open: the participant
        resumes later, but the hit precedes the closure and cannot be its
        consequence."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-before-"))
        rows = self._lane()

        def script(harness, sample, rows):
            actor = rows[0]
            opponent = rows[1] if len(rows) > 1 else None
            if sample == 1 and opponent is not None:
                self._exchange(harness, rows, actor, opponent, kill=False)
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(3539, actor["eid"],
                                                      -40.0)})
            if sample == 2 and opponent is not None:
                self._exchange(harness, rows, actor, rows[1], kill=True)
            if sample in (3, 4):
                actor["x"] += 2.0

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, window=8.0)
        try:
            record = self._serialized(result)
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "PASS")
            self.assertEqual(record["stages"]["STRUCTURE_INTERACTION"]["status"],
                             "NOT_OBSERVED")
            self.assertIn("not later than the engagement-end instant",
                          record["stages"]["STRUCTURE_INTERACTION"]["detail"])
            window = record["observations"]["minion_window"]
            actor = self._episode(window, 4610)
            self.assertIsNone(actor["structure_sequence"])
            self.assertGreaterEqual(actor["resumed_after_combat"], 1.0)
            self.assertEqual(actor["structure_unverified"]["hits"], 1)
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_post_death_structure_hit_does_not_satisfy_the_stage(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-postdeath-"))
        rows = self._lane()
        actor, opponent = rows

        def script(harness, sample, rows):
            if sample == 1:
                self._exchange(harness, rows, actor, opponent, kill=False)
            if sample == 2:
                self._exchange(harness, rows, actor, opponent, kill=True)
            if sample in (3, 4):
                actor["x"] += 2.0
            if sample == 5:
                # the participant dies here: its own 1072 publication
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242,
                              "opcode": sc.OP_ENTITY_DEATH,
                              "payload": build_entity_death(4610, 4611)})
                for index, row in enumerate(rows):
                    if row is actor:
                        del rows[index]
                        break
            if sample == 7:
                # and a hit is carried after that death
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(3539, 4610, -40.0)})

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, window=8.0)
        try:
            record = self._serialized(result)
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "PASS")
            self.assertEqual(record["stages"]["STRUCTURE_INTERACTION"]["status"],
                             "NOT_OBSERVED")
            self.assertIn("post-death hit cannot qualify",
                          record["stages"]["STRUCTURE_INTERACTION"]["detail"])
            window = record["observations"]["minion_window"]
            actor = self._episode(window, 4610)
            self.assertEqual(actor["death_evidence"], "death-publication")
            self.assertIsNone(actor["structure_sequence"])
            self.assertGreaterEqual(actor["resumed_after_combat"], 1.0,
                                    "the measured resumption stands")
            self.assertEqual(actor["structure_hits"][0]["structure"], 3539)
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_gap_before_the_hit_does_not_satisfy_the_stage(self):
        """Correction negative through the writer: the participant resumes and
        then disappears from the census (a carried ABSENCE, not a death)
        before its hit. The resumption stands, but the alive interval does not
        reach the hit, so the stage is NOT_OBSERVED with that reason."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-gap-"))
        rows = self._lane()
        actor, opponent = rows

        def script(harness, sample, rows):
            if sample == 1:
                self._exchange(harness, rows, actor, opponent, kill=False)
            if sample == 2:
                self._exchange(harness, rows, actor, opponent, kill=True)
            if sample in (3, 4):
                actor["x"] += 2.0
            if sample == 5:
                # the census stops serving the actor: an absence is recorded,
                # never a death
                for index, row in enumerate(rows):
                    if row is actor:
                        del rows[index]
                        break
            if sample == 7:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(3539, actor["eid"],
                                                      -40.0)})

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, window=10.0)
        try:
            record = self._serialized(result)
            self.assertEqual(record["status"], "FAIL",
                             record.get("failure_detail"))
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "PASS")
            self.assertEqual(record["stages"]["STRUCTURE_INTERACTION"]["status"],
                             "NOT_OBSERVED")
            self.assertIn("does not reach the hit",
                          record["stages"]["STRUCTURE_INTERACTION"]["detail"])
            self.assertEqual(record["stages"]["TRIAL_CONTINUITY"]["status"],
                             "PASS", record["stages"]["TRIAL_CONTINUITY"])
            window = record["observations"]["minion_window"]
            self.assertEqual(window["resumed_cohort_structure_hits"], 0)
            self.assertEqual(window["structure_claims_unverified"], 1)
            actor_episode = self._episode(window, 4610)
            self.assertGreaterEqual(actor_episode["resumed_after_combat"], 1.0,
                                    "the measured resumption stands")
            self.assertIsNotNone(actor_episode["absent_since"],
                                 "the gap is a recorded absence")
            self.assertIsNone(actor_episode["death_time"],
                              "an absence is not a death")
            self.assertTrue(actor_episode["structure_hit"],
                            "the raw hit is preserved")
            self.assertIsNone(actor_episode["structure_sequence"])
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_invalid_structure_team_does_not_satisfy_the_stage(self):
        """Correction negative through the writer: the snapshot serves a team
        that is neither side of the match (3), so the hit cannot be shown to
        be an opposing-structure hit even though it is the participant's own
        and follows its measured resumption."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-team3-"))
        rows = self._lane()

        def script(harness, sample, rows):
            script_lane(harness, sample, rows)

        result, harness = run_minion_trial(
            base, 1, rows=rows,
            structures=[{"eid": 3539, "team": 3, "x": 17.06, "y": 1.93,
                         "hp": 2500.0, "max_hp": 2500.0, "alive": True}],
            script=script, window=8.0)
        try:
            record = self._serialized(result)
            self.assertEqual(record["status"], "FAIL",
                             record.get("failure_detail"))
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "PASS")
            self.assertEqual(record["stages"]["STRUCTURE_INTERACTION"]["status"],
                             "NOT_OBSERVED")
            self.assertIn("is not one of the two teams of the match",
                          record["stages"]["STRUCTURE_INTERACTION"]["detail"])
            window = record["observations"]["minion_window"]
            self.assertEqual(window["structure_teams"], {"3539": 3},
                             "the raw team the snapshot carried is kept")
            self.assertEqual(window["resumed_cohort_structure_hits"], 0)
            actor = self._episode(window, 4610)
            self.assertIsNone(actor["structure_sequence"])
            self.assertEqual(actor["structure_hits"][0]["structure_team"], 3)
            self.assertGreaterEqual(actor["resumed_after_combat"], 1.0)
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)


class TestDeclaredFixtureStrictness(unittest.TestCase):
    """Review item: exact/full policies through preparation and validation,
    with out-of-range exact requests rejected before sending."""

    def _run_with_declared(self, declared, scenario="skye-a", **profile_extra):
        harness = Harness(scenario)
        (harness.base / "qa").mkdir(parents=True, exist_ok=True)
        (harness.base / "qa" / "state.json").write_text(
            json.dumps({"tick": 100}), encoding="utf-8")
        declared_profile = json.loads(json.dumps(
            {**sc.DEFAULT_PROFILE, "declared_fixture": declared,
             **profile_extra}))
        profile_path = harness.base / "profile-declared.json"
        profile_path.write_text(json.dumps(declared_profile), encoding="utf-8")
        real_qa_class = sc.QaSession

        def fake_qa(qa_dir, *, submit=None):
            return real_qa_class(qa_dir, submit=harness.qa.submit)

        import unittest.mock as mock
        with mock.patch.object(sc, "QaSession", fake_qa),                 mock.patch.object(sc, "Adb", lambda serial: harness.adb):
            result = sc.run_client(scenario, types.SimpleNamespace(
                adb_serial="emulator-5554", qa_dir=str(harness.base / "qa"),
                wire_trace=str(harness.trace_path), timeout=2.0,
                output=str(harness.base / "out"), connection=424242,
                client_profile=str(profile_path), reference=None))
        return result, harness

    def test_exact_energy_within_maximum_prepares_and_passes(self):
        declared = {**sc.DEFAULT_PROFILE["declared_fixture"],
                    "skye_energy_policy": "exact",
                    "skye_energy_exact": 900.0,
                    "skye_level": 6, "skye_ranks": {"0": 1, "1": 1, "2": 1},
                    "skye_points": 1, "enemy_level": 1}
        result, harness = self._run_with_declared(declared)
        self.assertEqual(result["stages"]["SETUP"]["status"], "PASS",
                         result.get("failure_detail"))
        energy_receipts = [r for r in result["qa_receipts"]
                           if r["command"].get("energy") is not None]
        self.assertTrue(energy_receipts,
                        "the exact energy request must reach the QA mailbox")
        self.assertEqual(energy_receipts[-1]["command"]["energy"], 900.0,
                         "exact request must be sent unchanged (no clamp)")

    def test_exact_resource_outside_maximum_fails_before_sending(self):
        declared = {**sc.DEFAULT_PROFILE["declared_fixture"],
                    "skye_energy_policy": "exact",
                    "skye_energy_exact": 5000.0,
                    "skye_level": 6, "skye_ranks": {"0": 1, "1": 1, "2": 1},
                    "skye_points": 1, "enemy_level": 1}
        result, harness = self._run_with_declared(declared)
        self.assertEqual(result["first_failed_stage"], "SETUP")
        self.assertIn("outside the actor's legal maximum",
                      result.get("failure_detail"))
        sent = [r for r in result["qa_receipts"]
                if r["command"].get("command") == "resources"]
        self.assertEqual(sent, [], "no out-of-range request may reach the QA "
                                   "mailbox")

    def test_full_resource_declaration_exercises_preparation(self):
        declared = {**sc.DEFAULT_PROFILE["declared_fixture"],
                    "skye_hp_policy": "full",
                    "skye_level": 6, "skye_ranks": {"0": 1, "1": 1, "2": 1},
                    "skye_points": 1, "enemy_level": 1}
        result, harness = self._run_with_declared(declared)
        self.assertEqual(result["stages"]["SETUP"]["status"], "PASS")
        hp_receipts = [r for r in result["qa_receipts"]
                       if r["command"].get("hp") is not None]
        self.assertTrue(hp_receipts,
                        "skye HP full restore must be exercised")


class TestCausalOutcomeEvidence(unittest.TestCase):
    """Outcome evidence: exact totals, positive/non-finite deltas, and
    timer-identity binding."""

    def _result_with_outcome(self, deltas, cooldown_slot="B"):
        prov = {"source_startup_digest": "s" * 64,
                "source_current_digest": "s" * 64,
                "tape": {"sha256": "t" * 64}, "env_config": {},
                "client_version": {"version_name": "4.13.4",
                                   "version_code": 147219},
                "qa_dir": "q",
                "diagnostics": {"pid": 4242, "startup_at": 1.0,
                                "match_id": "synthetic-match",
                                "phase": "world", "match_finished": False,
                                "tick": 100, "time": 5.0},
                "diagnostics_end": {"pid": 4242, "startup_at": 1.0,
                                    "match_id": "synthetic-match",
                                    "phase": "world", "match_finished": False,
                                    "tick": 140, "time": 7.0}}
        declared = {"skye_level": 6, "enemy_level": 1,
                    "skye_ranks": {"0": 1, "1": 1, "2": 1},
                    "skye_points": 1,
                    "skye_energy_policy": "full",
                    "skye_hp_policy": "full",
                    "enemy_hp_policy": "full"}
        manifest = {
            "match_id": "synthetic-match",
            "skye": {"level": 6, "ranks": {"0": 1, "1": 1, "2": 1},
                     "ability_points": 0, "hp": 1200.0, "max_hp": 1200.0,
                     "energy": 560.0, "max_energy": 560.0, "statuses": [],
                     "alive": True, "hero_id": 265, "eid": 1500,
                     "x": 0.0, "y": 38.0, "inventory": [],
                     "default_items": []},
            "enemy": {"eid": 1517, "hero_id": 243, "level": 1,
                      "hp": 4000.0, "max_hp": 4000.0, "x": 4.0, "y": 38.0,
                      "alive": True, "statuses": []},
            "cooldowns": {}, "slot": cooldown_slot,
            "declared_fixture": declared,
        }
        attributed = [{"time": 1.0 + i, "delta": d, "payload": "x" * 40,
                       "reason": "COMBAT_DELTA_TAIL (non-basic source)"}
                      for i, d in enumerate(deltas)]
        contract = sc.build_fixture_contract(
            {**sc.DEFAULT_PROFILE, "declared_fixture": declared,
             "placement_tolerance": 1.5, "local_player_eid": 1500}, "B")
        return {"schema_version": sc.PAIR_SCHEMA_VERSION,
                "scenario": "skye-b", "status": "PASS",
                "fixture_contract": contract,
                "stages": {k: {"status": "PASS"} for k in (
                    "SETUP", "UI_COMMAND_SUBMITTED", "CLIENT_INPUT_OBSERVED",
                    "SERVER_ACKNOWLEDGED", "AUTHORITATIVE_EFFECT")},
                "fixture_manifest": manifest, "provenance": prov,
                "observations": {
                    "damage_classification": {"attributed": attributed},
                    "cooldown_tag": {"slot": cooldown_slot,
                                     "tag": "46a89591"},
                    "fixture_manifest": manifest},
                "provenance": prov}

    def test_cooldown_tag_for_wrong_slot_fails_record(self):
        result = self._result_with_outcome([-30.0])
        (result.get("observations") or {})["cooldown_tag"] = {
            "slot": "A", "tag": "43a890d8"}
        failures, _m, _d = sc.validate_trial_record(result)
        self.assertTrue(any("wrong slot" in f for f in failures),
                        "an A-tag timer must never satisfy a B cast")


class TestSkyeBCausalEvidence(unittest.TestCase):
    """Checkpoint 7: serialized CAUSAL coherence for skye-b.

    The positives are the UNPATCHED output of the real writer path
    (``run_client`` over the fake session, exactly as the other offline
    suites produce records) — never hand-built or post-edited records. The
    negatives change ONE relevant linkage at a time in the serialized JSON
    and go through the PUBLIC compare-pair CLI, so the refusal is the
    public gate's own verdict.

    Bounded slice: the shared checker now covers slots A, B and C (see the
    caller in ``validate_trial_record``); checkpoint 8 covers skye-a with the
    same checker (``TestSkyeACausalEvidence``) and checkpoint 9 covers
    skye-c's receipts plus its volley publications
    (``TestSkyeCVolleyCausalEvidence``).
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-causal-"))
        cls.va, cls.vb = produce_pair(cls.base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _cli(self, name, va, vb):
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        return run_compare_cli(pa, pb)

    def _assert_refused(self, name, va, vb, *needles):
        code, report, stderr = self._cli(name, va, vb)
        self.assertNotEqual(code, 0, f"{name} must not be a controlled pair")
        self.assertFalse(report.get("controlled_pair"))
        joined = json.dumps(report.get("failures"))
        for needle in needles:
            self.assertIn(needle, joined, f"expected {needle!r} in {joined}")
        self.assertNotIn("Traceback", stderr)
        return report

    def _mutated_b(self):
        return json.loads(json.dumps(self.vb))

    def test_writer_pair_carries_coherent_causal_evidence(self):
        """The writer-produced pair IS a controlled pair, and every carried
        linkage is coherent for the trial's own actor, connection and window."""
        for label, record in (("A", self.va), ("B", self.vb)):
            self.assertEqual(record["scenario"], "skye-b")
            self.assertEqual(
                sc.collect_skye_cast_causal_failures(
                    record, record["fixture_manifest"], "B"), [],
                f"record {label} must carry coherent causal evidence")
            observed = record["observations"]
            connection = record["connection"]
            self.assertEqual(record["fixture_manifest"]["connection"],
                             connection)
            # the observed input: the B's native action, on this session, and
            # the c2s bytes it was matched on
            client_input = observed["client_input"]
            self.assertEqual(client_input["action"],
                             sc.SKYE_NATIVE_ACTIONS["B"])
            self.assertEqual(client_input["connection"], connection)
            self.assertEqual(
                sc.ground_cast_action({"opcode": sc.OP_GROUND_CAST,
                                       "payload": client_input["payload"]}),
                client_input["action"])
            # the acknowledgment: the same action, on this session, not
            # before its own input and not past the observed window; its own
            # 1046 bytes carry the action and the acknowledged actor
            acknowledgment = observed["acknowledgment"]
            self.assertEqual(acknowledgment["action"], client_input["action"])
            self.assertGreaterEqual(acknowledgment["time"],
                                    client_input["time"])
            self.assertEqual(acknowledgment["connection"], connection)
            self.assertEqual(
                sc.position_event_action(
                    {"opcode": sc.OP_POSITION_EVENT,
                     "payload": acknowledgment["payload"]}),
                acknowledgment["action"])
            hero_eid = record["fixture_manifest"]["skye"]["eid"]
            self.assertEqual(
                sc._payload_u32(acknowledgment["payload"], 0), hero_eid)
            # the timer receipt: this actor's native B tag, on this session,
            # and its own 1162 bytes carry that very (eid, tag)
            tag = observed["cooldown_tag"]
            self.assertEqual(tag["slot"], "B")
            self.assertEqual(tag["tag"],
                             f"{sc.SKYE_COOLDOWN_TAGS['B']:08x}")
            self.assertEqual(tag["eid"], hero_eid)
            self.assertGreaterEqual(tag["time"], acknowledgment["time"])
            self.assertEqual(tag["connection"], connection)
            self.assertEqual(
                sc.timer_tag_eid({"opcode": sc.OP_TIMER_TICK,
                                  "payload": tag["payload"]}),
                (hero_eid, sc.SKYE_COOLDOWN_TAGS["B"]))
            # the action window opens with the observed input and CONTAINS
            # every receipt that establishes this cast
            classification = observed["damage_classification"]
            start, end = classification["window"]
            self.assertGreaterEqual(start, client_input["time"])
            self.assertGreater(end, start)
            for label_receipt, when in (("ack", acknowledgment["time"]),
                                        ("timer", tag["time"])):
                self.assertGreaterEqual(when, start, label_receipt)
                self.assertLessEqual(when, end, label_receipt)
            # every attributed event is this session's, inside that window,
            # and backed by its own payload
            enemy_eid = record["fixture_manifest"]["enemy"]["eid"]
            for hit in classification["attributed"]:
                self.assertEqual(hit["connection"], connection)
                self.assertGreaterEqual(hit["time"], start)
                self.assertLessEqual(hit["time"], end)
                self.assertIsNone(sc.payload_backs_hit(hit, hero_eid,
                                                       enemy_eid))
            # exact counts and the four-decimal total, both against the
            # carried attribution
            outcome = observed["outcome"]
            self.assertEqual(outcome["attributed_events"],
                             len(classification["attributed"]))
            self.assertEqual(
                outcome["outcome_total"],
                round(sum(h["delta"] for h in classification["attributed"]),
                      sc.OUTCOME_TOTAL_DECIMALS))
        code, report, stderr = self._cli("causal-pass", self.va, self.vb)
        self.assertEqual(code, 0, report.get("failures") or stderr)
        self.assertTrue(report["controlled_pair"])

    def test_slot_only_timer_witness_is_refused(self):
        """A timer receipt that names only a SLOT is not this hero's cast."""
        cases = {
            "slot_only": {"slot": "B", "tag": "46a89591", "time": 1.0},
            "other_actor": {"slot": "B", "tag": "46a89591", "eid": 1517,
                            "time": 1.0},
            "other_slot_tag": {"slot": "B", "tag": "43a890d8", "eid": 1500,
                               "time": 1.0},
        }
        for name, receipt in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                original = vb["observations"]["cooldown_tag"]
                # the writer's own receipt carries the actor binding; each
                # witness changes only that binding (or omits it, which is
                # exactly the slot-only shape older records had)
                self.assertTrue({"slot", "tag", "time"} <= set(receipt))
                if name == "slot_only":
                    self.assertIn("eid", original)
                    self.assertNotIn("eid", receipt)
                else:
                    self.assertIn("eid", original)
                    self.assertIn("eid", receipt)
                vb["observations"]["cooldown_tag"] = receipt
                if name == "slot_only":
                    needle = "slot-only"
                elif name == "other_actor":
                    needle = "!= the trial hero"
                else:
                    needle = "!= the native B timer tag"
                self._assert_refused(f"causal-tag-{name}", self.va, vb, needle)

    def test_input_linkage_changes_are_refused(self):
        def window_start(record):
            return record["observations"]["damage_classification"]["window"][0]

        cases = {
            "action": (lambda r: r["observations"]["client_input"].update(
                {"action": 0}), "!= the B native action"),
            "connection": (lambda r: r["observations"]["client_input"].update(
                {"connection": 424243}), "input and outcome evidence come "
                "from different sessions"),
            # The window the driver recorded opens exactly at the c2s input it
            # observed, so an input moved either way re-dates the cast. The
            # earlier case is the parent's exact preserved witness shape
            # (client_input.time - 100 s, everything else untouched).
            "time_earlier_minus_100": (
                lambda r: r["observations"]["client_input"].update(
                    {"time": r["observations"]["client_input"]["time"] - 100.0}),
                "not at the recorded input"),
            "time_later_inside_window": (
                lambda r: r["observations"]["client_input"].update(
                    {"time": window_start(r) + 1.0}),
                "not at the recorded input"),
            "time_after_window": (
                lambda r: r["observations"]["client_input"].update(
                    {"time": r["observations"]["damage_classification"]
                     ["window"][1] + 5.0}),
                "not at the recorded input"),
            "missing": (lambda r: r["observations"].pop("client_input"),
                        "no observed B input"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"causal-input-{name}", self.va, vb,
                                     needle)

    def test_acknowledgment_linkage_changes_are_refused(self):
        cases = {
            "action": (lambda r: r["observations"]["acknowledgment"].update(
                {"action": 0}), "acknowledgment and input are different "
                "actions"),
            "before_input": (lambda r: r["observations"]["acknowledgment"]
                             .update({"time": r["observations"]["client_input"]
                                      ["time"] - 1.0}),
                             "precedes the observed input"),
            "missing": (lambda r: r["observations"].pop("acknowledgment"),
                        "the B cast was never acknowledged"),
            "timer_before_ack": (lambda r: r["observations"]["cooldown_tag"]
                                 .update({"time": r["observations"]
                                          ["acknowledgment"]["time"] - 1.0}),
                                 "cannot precede its own cast"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"causal-ack-{name}", self.va, vb, needle)

    def test_attributed_damage_linkage_changes_are_refused(self):
        def other_connection(record):
            record["observations"]["damage_classification"]["attributed"][0][
                "connection"] = 424243

        def outside_window(record):
            record["observations"]["damage_classification"]["attributed"][0][
                "time"] = record["observations"]["damage_classification"][
                    "window"][1] + 5.0

        def other_actor(record):
            record["observations"]["damage_classification"]["attributed"][0][
                "payload"] = build_damage(1517, 4610, -30.0)

        def edited_delta(record):
            record["observations"]["damage_classification"]["attributed"][0][
                "delta"] = -30.5

        def window_before_input(record):
            record["observations"]["damage_classification"]["window"] = [
                record["observations"]["client_input"]["time"] - 10.0,
                record["observations"]["damage_classification"]["window"][1]]

        def stalled_window(record):
            start = record["observations"]["damage_classification"]["window"][0]
            record["observations"]["damage_classification"]["window"] = [
                start, start]

        cases = {
            "connection": (other_connection,
                           "damage from another session was carried as this "
                           "trial's outcome"),
            "time_outside_window": (outside_window,
                                    "unrelated damage cannot establish this "
                                    "cast's outcome"),
            "other_actor_payload": (other_actor, "actor binding"),
            "edited_delta": (edited_delta, "!= payload delta"),
            "window_before_input": (window_before_input,
                                    "not at the recorded input"),
            "window_stalled": (stalled_window, "does not advance"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"causal-damage-{name}", self.va, vb,
                                     needle)

    def test_receipts_beyond_the_observed_window_are_refused(self):
        """The proven false PASS: a receipt moved past the window's end.

        The window is the driver's own observation window for this cast, so a
        receipt timestamped after it cannot establish the cast — regardless of
        still being ordered after the input and the acknowledgment."""
        def window_end(record):
            return record["observations"]["damage_classification"]["window"][1]

        def ack_past(record):
            record["observations"]["acknowledgment"]["time"] = \
                window_end(record) + 100.0

        def timer_past(record):
            record["observations"]["cooldown_tag"]["time"] = \
                window_end(record) + 101.0

        def parent_witness(record):
            # the exact shape of the preserved CLI witness: ack = end + 100 s,
            # timer = end + 101 s, everything else untouched
            ack_past(record)
            timer_past(record)

        cases = {
            "ack_end_plus_100": (ack_past, "acknowledgment.time"),
            "timer_end_plus_101": (timer_past, "cooldown_tag.time"),
            "parent_witness": (parent_witness,
                               "outside the observed action window"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                report = self._assert_refused(f"causal-window-{name}",
                                              self.va, vb, needle)
                joined = json.dumps(report.get("failures"))
                self.assertIn("outside the observed action window", joined,
                              "a receipt outside the recorded window must say "
                              "so explicitly")

    def test_receipt_connection_changes_are_refused(self):
        """A receipt copied from another session is not this trial's cast."""
        cases = {
            "ack_other_connection": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"connection": 424243}), "acknowledgment.connection"),
            "timer_other_connection": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"connection": 424243}), "cooldown_tag.connection"),
            "ack_connection_missing": (
                lambda r: r["observations"]["acknowledgment"].pop(
                    "connection"), "acknowledgment.connection"),
            "timer_connection_missing": (
                lambda r: r["observations"]["cooldown_tag"].pop("connection"),
                "cooldown_tag.connection"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"causal-conn-{name}", self.va, vb, needle)

    def test_receipt_payload_disagreement_is_refused(self):
        """Copied action/eid metadata is not the wire receipt: the bytes each
        receipt carries must parse to the very action/actor/tag claimed."""
        cases = {
            "ack_payload_action": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"payload": build_position_event(1500, 0)}),
                "acknowledgment.payload action"),
            "ack_payload_eid": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"payload": build_position_event(1517, 2)}),
                "acknowledgment.payload eid"),
            "ack_payload_too_short": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"payload": "0000"}),
                "too short to carry the acknowledged eid"),
            "ack_payload_not_hex": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"payload": "zz"}), "acknowledgment.payload is not hex"),
            "ack_payload_missing": (
                lambda r: r["observations"]["acknowledgment"].pop("payload"),
                "acknowledgment.payload"),
            "timer_payload_tag": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"payload": build_timer(1500, 0x43A890D8)}),
                "cooldown_tag.payload tag"),
            "timer_payload_eid": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"payload": build_timer(1517, 0x46A89591)}),
                "cooldown_tag.payload eid"),
            "timer_payload_too_short": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"payload": "0000"}),
                "does not parse as a 1162 timer receipt"),
            "timer_payload_missing": (
                lambda r: r["observations"]["cooldown_tag"].pop("payload"),
                "cooldown_tag.payload"),
            "input_payload_action": (
                lambda r: r["observations"]["client_input"].update(
                    {"payload": build_ground_cast_payload(0)}),
                "client_input.payload action"),
            "input_payload_missing": (
                lambda r: r["observations"]["client_input"].pop("payload"),
                "client_input.payload"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"causal-payload-{name}", self.va, vb,
                                     needle)

    def test_outcome_summary_tamper_is_refused_exactly(self):
        """Counts and the four-decimal total are exact: an edited summary is
        not a measured outcome, and no tolerance is applied."""
        cases = {
            "count_plus_one": (lambda r: r["observations"]["outcome"].update(
                {"attributed_events":
                 r["observations"]["outcome"]["attributed_events"] + 1}),
                "!= the carried attribution's"),
            "total_epsilon": (lambda r: r["observations"]["outcome"].update(
                {"outcome_total":
                 r["observations"]["outcome"]["outcome_total"] + 0.0001}),
                "at 4 decimals"),
            "missing": (lambda r: r["observations"].pop("outcome"),
                        "carries no summary of its own attribution"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"causal-outcome-{name}", self.va, vb,
                                     needle)


class TestSkyeACausalEvidence(unittest.TestCase):
    """Checkpoint 8: serialized CAUSAL coherence for skye-a.

    Same shared checker as B (``collect_skye_cast_causal_failures``), because
    the writer captures A's input, acknowledgment, timer receipt and effect
    window through the same ``run_cast_scenario`` path with only the native
    action and timer tag differing. What is A-specific here, and asserted
    explicitly rather than assumed: A's native action/tag binding, and the
    fact that A carries NO Target Lock observation (the lock is required only
    for B/C) while still being a controlled pair — no B-only lock requirement
    is imported into A.

    The positive is the UNPATCHED writer output (``run_client`` over the fake
    session) driven through the PUBLIC compare-pair CLI; every negative
    changes ONE linkage in the serialized JSON and is refused by that same
    public gate.
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-causal-a-"))
        cls.va, cls.vb = produce_pair(cls.base, "skye-a")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _cli(self, name, va, vb):
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        return run_compare_cli(pa, pb)

    def _assert_refused(self, name, va, vb, *needles):
        code, report, stderr = self._cli(name, va, vb)
        self.assertNotEqual(code, 0, f"{name} must not be a controlled pair")
        self.assertFalse(report.get("controlled_pair"))
        joined = json.dumps(report.get("failures"))
        for needle in needles:
            self.assertIn(needle, joined, f"expected {needle!r} in {joined}")
        self.assertNotIn("Traceback", stderr)
        return report

    def _mutated_b(self):
        return json.loads(json.dumps(self.vb))

    def test_writer_pair_is_a_controlled_pair_and_coherent(self):
        code, report, stderr = self._cli("a-positive", self.va, self.vb)
        self.assertEqual(code, 0, report.get("failures"))
        self.assertTrue(report.get("controlled_pair"), report.get("failures"))
        self.assertNotIn("Traceback", stderr)
        for label, record in (("A", self.va), ("B", self.vb)):
            self.assertEqual(record["scenario"], "skye-a")
            self.assertEqual(record["fixture_manifest"]["slot"], "A")
            self.assertEqual(
                sc.collect_skye_cast_causal_failures(
                    record, record["fixture_manifest"], "A"), [],
                f"record {label} must carry coherent causal evidence")

    def test_a_binds_its_own_action_tag_and_window_relationship(self):
        """A's native action and timer tag, its acknowledgment actor, and the
        MEASURED window relationship of A's own writer output: the driver's
        window opens exactly at the c2s input it observed, for A as for B."""
        for label, record in (("A", self.va), ("B", self.vb)):
            observed = record["observations"]
            connection = record["connection"]
            self.assertEqual(record["fixture_manifest"]["connection"],
                             connection)
            client_input = observed["client_input"]
            self.assertEqual(client_input["action"],
                             sc.SKYE_NATIVE_ACTIONS["A"])
            self.assertEqual(client_input["connection"], connection)
            self.assertEqual(
                sc.ground_cast_action({"opcode": sc.OP_GROUND_CAST,
                                       "payload": client_input["payload"]}),
                client_input["action"])
            window = observed["damage_classification"]["window"]
            self.assertEqual(
                window[0], client_input["time"],
                "the A writer's window must open at the observed c2s input")
            self.assertGreater(window[1], window[0])
            ack = observed["acknowledgment"]
            self.assertEqual(ack["action"], client_input["action"])
            self.assertEqual(ack["connection"], connection)
            self.assertEqual(
                sc.position_event_action(
                    {"opcode": sc.OP_POSITION_EVENT,
                     "payload": ack["payload"]}), ack["action"])
            hero_eid = record["fixture_manifest"]["skye"]["eid"]
            self.assertEqual(sc._payload_u32(ack["payload"], 0), hero_eid)
            self.assertLessEqual(ack["time"], window[1])
            tag = observed["cooldown_tag"]
            self.assertEqual(tag["slot"], "A")
            self.assertEqual(tag["tag"], f"{sc.SKYE_COOLDOWN_TAGS['A']:08x}")
            self.assertEqual(tag["eid"], hero_eid)
            self.assertEqual(tag["connection"], connection)
            self.assertEqual(
                sc.timer_tag_eid({"opcode": sc.OP_TIMER_TICK,
                                  "payload": tag["payload"]}),
                (hero_eid, sc.SKYE_COOLDOWN_TAGS["A"]))
            self.assertLessEqual(tag["time"], window[1])
            for index, hit in enumerate(
                    observed["damage_classification"]["attributed"]):
                self.assertEqual(hit["connection"], connection,
                                 f"{label} attributed[{index}]")
                self.assertLessEqual(window[0], hit["time"])
                self.assertLessEqual(hit["time"], window[1])
            # A carries no Target Lock: the lock is a B/C capture step, and
            # the shared checker must not require it of A.
            self.assertNotIn("lock", observed,
                             "A does not observe a Target Lock in the writer")
            failures = sc.collect_skye_cast_causal_failures(
                record, record["fixture_manifest"], "A")
            self.assertEqual(failures, [])
            self.assertFalse(any("lock" in f for f in failures),
                             "no lock requirement may appear in A's verdict")

    def test_input_linkage_changes_are_refused(self):
        def window_start(record):
            return record["observations"]["damage_classification"]["window"][0]

        cases = {
            "action_wrong_skill": (
                lambda r: r["observations"]["client_input"].update(
                    {"action": sc.SKYE_NATIVE_ACTIONS["B"]}),
                "!= the A native action"),
            "action_from_b_payload": (
                lambda r: r["observations"]["client_input"].update(
                    {"payload": build_ground_cast_payload(
                        sc.SKYE_NATIVE_ACTIONS["B"])}),
                "the receipt's own bytes do not carry this action"),
            "connection": (
                lambda r: r["observations"]["client_input"].update(
                    {"connection": 424243}),
                "input and outcome evidence come from different sessions"),
            "time_earlier_minus_100": (
                lambda r: r["observations"]["client_input"].update(
                    {"time": r["observations"]["client_input"]["time"] - 100.0}),
                "not at the recorded input"),
            "time_later_inside_window": (
                lambda r: r["observations"]["client_input"].update(
                    {"time": window_start(r) + 1.0}),
                "not at the recorded input"),
            "time_after_window": (
                lambda r: r["observations"]["client_input"].update(
                    {"time": r["observations"]["damage_classification"]
                     ["window"][1] + 5.0}),
                "not at the recorded input"),
            "payload_missing": (
                lambda r: r["observations"]["client_input"].pop("payload"),
                "client_input.payload"),
            "missing": (lambda r: r["observations"].pop("client_input"),
                        "no observed A input"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"a-causal-input-{name}", self.va, vb,
                                     needle)

    def test_acknowledgment_linkage_changes_are_refused(self):
        def window_end(record):
            return record["observations"]["damage_classification"]["window"][1]

        cases = {
            "action_wrong_skill": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"action": sc.SKYE_NATIVE_ACTIONS["C"]}),
                "acknowledgment and input are different actions"),
            "action_from_b_payload": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"payload": build_position_event(
                        SKYE_EID, sc.SKYE_NATIVE_ACTIONS["B"])}),
                "the receipt's own bytes do not carry this action"),
            "actor_eid": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"payload": build_position_event(
                        ENEMY_EID, sc.SKYE_NATIVE_ACTIONS["A"])}),
                "the receipt's own bytes do not name this actor"),
            "connection": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"connection": 424243}), "acknowledgment.connection"),
            "before_input": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"time": r["observations"]["client_input"]["time"] - 1.0}),
                "precedes the observed input"),
            "beyond_window": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"time": window_end(r) + 100.0}),
                "outside the observed action window"),
            "payload_missing": (
                lambda r: r["observations"]["acknowledgment"].pop("payload"),
                "acknowledgment.payload"),
            "missing": (lambda r: r["observations"].pop("acknowledgment"),
                        "the A cast was never acknowledged"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"a-causal-ack-{name}", self.va, vb,
                                     needle)

    def test_timer_receipt_linkage_changes_are_refused(self):
        def window_end(record):
            return record["observations"]["damage_classification"]["window"][1]

        cases = {
            "slot_wrong": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"slot": "B"}), "!= 'A'"),
            "tag_wrong_ability": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"tag": f"{sc.SKYE_COOLDOWN_TAGS['B']:08x}"}),
                "!= the native A timer tag"),
            "tag_from_b_payload": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"payload": build_timer(SKYE_EID,
                                            sc.SKYE_COOLDOWN_TAGS["B"])}),
                "the receipt's own bytes carry a different timer"),
            "eid_other_actor": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"payload": build_timer(ENEMY_EID,
                                            sc.SKYE_COOLDOWN_TAGS["A"])}),
                "the receipt's own bytes do not name this actor"),
            "eid_missing": (
                lambda r: r["observations"]["cooldown_tag"].pop("eid"),
                "slot-only"),
            "connection": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"connection": 424243}), "cooldown_tag.connection"),
            "before_ack": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"time": r["observations"]["acknowledgment"]["time"] - 1.0}),
                "cannot precede its own cast"),
            "beyond_window": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"time": window_end(r) + 101.0}),
                "outside the observed action window"),
            "payload_missing": (
                lambda r: r["observations"]["cooldown_tag"].pop("payload"),
                "cooldown_tag.payload"),
            "missing": (lambda r: r["observations"].pop("cooldown_tag"),
                        "no timer receipt has no acknowledgment evidence"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"a-causal-timer-{name}", self.va, vb,
                                     needle)

    def test_attributed_damage_linkage_changes_are_refused(self):
        def other_connection(record):
            record["observations"]["damage_classification"]["attributed"][0][
                "connection"] = 424243

        def outside_window(record):
            record["observations"]["damage_classification"]["attributed"][0][
                "time"] = record["observations"]["damage_classification"][
                    "window"][1] + 5.0

        def other_actor(record):
            record["observations"]["damage_classification"]["attributed"][0][
                "payload"] = build_damage(ENEMY_EID, 4610, -30.0)

        def edited_delta(record):
            record["observations"]["damage_classification"]["attributed"][0][
                "delta"] = -25.9

        cases = {
            "connection": (other_connection,
                           "damage from another session was carried as this "
                           "trial's outcome"),
            "time_outside_window": (outside_window,
                                    "unrelated damage cannot establish this "
                                    "cast's outcome"),
            "other_actor_payload": (other_actor, "actor binding"),
            "edited_delta": (edited_delta, "!= payload delta"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"a-causal-damage-{name}", self.va, vb,
                                     needle)

    def test_outcome_summary_and_attribution_tamper_are_refused(self):
        """Exact counts and the four-decimal total for A, and an emptied
        attribution: no tolerance, no percentage, no silent re-derivation."""
        cases = {
            "count_plus_one": (
                lambda r: r["observations"]["outcome"].update(
                    {"attributed_events":
                     r["observations"]["outcome"]["attributed_events"] + 1}),
                "!= the carried attribution's"),
            "total_epsilon": (
                lambda r: r["observations"]["outcome"].update(
                    {"outcome_total":
                     r["observations"]["outcome"]["outcome_total"] + 0.0001}),
                "at 4 decimals"),
            "summary_missing": (
                lambda r: r["observations"].pop("outcome"),
                "carries no summary of its own attribution"),
            "attribution_emptied": (
                lambda r: r["observations"]["damage_classification"].update(
                    {"attributed": []}),
                "cannot satisfy the effect"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"a-causal-outcome-{name}", self.va, vb,
                                     needle)


class TestSkyeCVolleyCausalEvidence(unittest.TestCase):
    """Checkpoint 9: serialized CAUSAL coherence for skye-c.

    C shares the A/B receipt/window/connection/exact-outcome checker (the
    writer captures those identically for every cast slot) and adds its own
    volley-publication evidence: the matched 1010 publications travel with
    their payload, connection and observation instant, and are re-derived with
    the same parser the driver matched with (``volley_owner``) — a bare
    ``volley_actors`` count establishes no publisher, session or instant.

    What a publication does NOT do here, and is not claimed: prove that the
    volley caused the attributed damage. No per-publication <-> per-pulse
    identity is carried, so the damage evidence stays the payload-backed 1054
    attribution with its exact count and four-decimal total.

    The positive is UNPATCHED writer output through the public compare-pair
    CLI; every negative changes ONE linkage in the serialized JSON and is
    refused by that same public gate.
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-causal-c-"))
        cls.va, cls.vb = produce_pair(cls.base, "skye-c")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _cli(self, name, va, vb):
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        return run_compare_cli(pa, pb)

    def _assert_refused(self, name, va, vb, *needles):
        code, report, stderr = self._cli(name, va, vb)
        self.assertNotEqual(code, 0, f"{name} must not be a controlled pair")
        self.assertFalse(report.get("controlled_pair"))
        joined = json.dumps(report.get("failures"))
        for needle in needles:
            self.assertIn(needle, joined, f"expected {needle!r} in {joined}")
        self.assertNotIn("Traceback", stderr)
        return report

    def _mutated_b(self):
        return json.loads(json.dumps(self.vb))

    def test_writer_pair_is_a_controlled_pair_and_coherent(self):
        code, report, stderr = self._cli("c-positive", self.va, self.vb)
        self.assertEqual(code, 0, report.get("failures"))
        self.assertTrue(report.get("controlled_pair"), report.get("failures"))
        self.assertNotIn("Traceback", stderr)
        for label, record in (("A", self.va), ("B", self.vb)):
            self.assertEqual(record["scenario"], "skye-c")
            self.assertEqual(record["fixture_manifest"]["slot"], "C")
            manifest = record["fixture_manifest"]
            self.assertEqual(
                sc.collect_skye_cast_causal_failures(record, manifest, "C"), [],
                f"record {label} must carry coherent causal evidence")
            self.assertEqual(
                sc.collect_skye_c_volley_failures(record, manifest), [],
                f"record {label} must carry coherent volley evidence")

    def test_c_binds_its_own_action_receipts_and_publications(self):
        """C's native action/tag, its receipts' own bytes, the measured window
        relationship, and the publications re-derived from their own bytes."""
        for label, record in (("A", self.va), ("B", self.vb)):
            observed = record["observations"]
            connection = record["connection"]
            hero_eid = record["fixture_manifest"]["skye"]["eid"]
            client_input = observed["client_input"]
            self.assertEqual(client_input["action"],
                             sc.SKYE_NATIVE_ACTIONS["C"])
            self.assertEqual(client_input["connection"], connection)
            window = observed["damage_classification"]["window"]
            self.assertEqual(
                window[0], client_input["time"],
                "the C writer's window must open at the observed c2s input")
            ack = observed["acknowledgment"]
            self.assertEqual(ack["action"], client_input["action"])
            self.assertEqual(
                sc.position_event_action({"opcode": sc.OP_POSITION_EVENT,
                                          "payload": ack["payload"]}),
                ack["action"])
            self.assertEqual(sc._payload_u32(ack["payload"], 0), hero_eid)
            tag = observed["cooldown_tag"]
            self.assertEqual(tag["slot"], "C")
            self.assertEqual(tag["tag"], f"{sc.SKYE_COOLDOWN_TAGS['C']:08x}")
            self.assertEqual(
                sc.timer_tag_eid({"opcode": sc.OP_TIMER_TICK,
                                  "payload": tag["payload"]}),
                (hero_eid, sc.SKYE_COOLDOWN_TAGS["C"]))
            self.assertLessEqual(ack["time"], window[1])
            self.assertLessEqual(tag["time"], window[1])
            # the publications: one count, one carried set, each re-derived
            publications = observed["volley_publications"]
            self.assertGreaterEqual(observed["volley_actors"], 1)
            self.assertEqual(observed["volley_actors"], len(publications))
            for index, publication in enumerate(publications):
                payload = publication["payload"]
                self.assertEqual(len(bytes.fromhex(payload)), 126,
                                 f"{label} publication[{index}] bytes")
                self.assertEqual(sc._payload_u32(payload, 4), sc.VOLLEY_CLASS)
                self.assertEqual(
                    sc.volley_owner({"opcode": sc.OP_ENTITY_FULL_UPDATE,
                                     "payload": payload}), hero_eid)
                self.assertEqual(publication["connection"], connection)
                self.assertLessEqual(window[0], publication["time"])
                self.assertLessEqual(publication["time"], window[1])
            # C requires an observed Target Lock in the CAPTURE step (unlike A),
            # but the lock is capture state, never a validator requirement
            self.assertIn("lock", observed)
            self.assertEqual(
                sc.collect_skye_c_volley_failures(
                    record, record["fixture_manifest"]), [])

    def test_missing_or_count_only_publications_are_refused(self):
        cases = {
            "publications_missing": (
                lambda r: r["observations"].pop("volley_publications"),
                "a bare count cannot establish who published the volley"),
            "publications_empty": (
                lambda r: r["observations"].update(
                    {"volley_publications": []}),
                "a bare count cannot establish who published the volley"),
            "publications_not_a_list": (
                lambda r: r["observations"].update(
                    {"volley_publications": {"time": 1.0}}),
                "a bare count cannot establish who published the volley"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"c-volley-{name}", self.va, vb, needle)

    def test_publication_count_agreement_is_enforced(self):
        cases = {
            "count_plus_one": (
                lambda r: r["observations"].update(
                    {"volley_actors":
                     r["observations"]["volley_actors"] + 1}),
                "the count and the carried publications disagree"),
            "count_zero": (
                lambda r: r["observations"].update({"volley_actors": 0}),
                "is not a positive integer"),
            "count_below_carried": (
                lambda r: r["observations"].update(
                    {"volley_publications":
                     r["observations"]["volley_publications"] * 2}),
                "the count and the carried publications disagree"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"c-volley-{name}", self.va, vb, needle)

    def test_publication_owner_class_connection_and_time_are_bound(self):
        def other_owner(record):
            record["observations"]["volley_publications"][0]["payload"] = \
                build_volley_1010(ENEMY_EID)

        def other_class(record):
            record["observations"]["volley_publications"][0]["payload"] = \
                build_volley_1010(SKYE_EID, volley_class=7)

        def other_connection(record):
            record["observations"]["volley_publications"][0][
                "connection"] = 424243

        def past_window(record):
            window_end = record["observations"]["damage_classification"][
                "window"][1]
            record["observations"]["volley_publications"][0]["time"] = \
                window_end + 5.0

        def before_cast(record):
            record["observations"]["volley_publications"][0]["time"] = \
                record["observations"]["client_input"]["time"] - 5.0

        cases = {
            "owner": (other_owner,
                      "the receipt's own bytes name another actor as the "
                      "publisher"),
            "class": (other_class, "!= the C volley class"),
            "connection": (other_connection, "volley_publications[0]."
                           "connection"),
            "time_past_window": (past_window,
                                 "cannot establish this cast's volley"),
            "time_before_cast": (before_cast,
                                 "cannot establish this cast's volley"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"c-volley-{name}", self.va, vb, needle)

    def test_publication_payload_disagreement_is_refused(self):
        """Every malformed payload is a STRUCTURED failure — never a parser
        exception out of the public CLI. The length guard counts DECODED bytes
        because ``bytes.fromhex`` ignores whitespace: a padded payload can pass
        a character count while decoding to fewer bytes than the class (@4) and
        owner (@112) reads need."""
        valid = build_volley_1010(SKYE_EID)

        def truncated_owner(record):
            # a real publication cut short: the class at @4 is still readable,
            # the owner at @112 is not — the case the character-count guard
            # missed once whitespace pads the string back over the threshold
            cut = bytes.fromhex(valid)[:60].hex()
            record["observations"]["volley_publications"][0]["payload"] = \
                cut + " " * (252 - len(cut))

        cases = {
            "payload_missing": (
                lambda r: r["observations"]["volley_publications"][0].pop(
                    "payload"),
                "the publication's own wire bytes are not carried"),
            "payload_not_hex": (
                lambda r: r["observations"]["volley_publications"][0].update(
                    {"payload": "not-hex"}),
                "is not hexadecimal"),
            "payload_too_short": (
                lambda r: r["observations"]["volley_publications"][0].update(
                    {"payload": "0000"}),
                "fewer than the 126-byte C volley publication shape"),
            "payload_whitespace_padded_one_byte": (
                lambda r: r["observations"]["volley_publications"][0].update(
                    {"payload": "00" + " " * 252}),
                "whitespace-padded, so its character count is not its byte "
                "count"),
            "payload_whitespace_only": (
                lambda r: r["observations"]["volley_publications"][0].update(
                    {"payload": " " * 252}),
                "decodes to 0 byte(s)"),
            "payload_truncated_owner_bytes": (
                truncated_owner,
                "fewer than the 126-byte C volley publication shape"),
            "time_missing": (
                lambda r: r["observations"]["volley_publications"][0].pop(
                    "time"),
                "is not a finite number"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"c-volley-{name}", self.va, vb, needle)

    def test_c_input_ack_timer_linkage_changes_are_refused(self):
        """The shared receipt checks, exercised on C's own native action and
        tag: window, payload and connection binding."""
        def window_end(record):
            return record["observations"]["damage_classification"]["window"][1]

        cases = {
            "input_action_wrong_skill": (
                lambda r: r["observations"]["client_input"].update(
                    {"action": sc.SKYE_NATIVE_ACTIONS["A"]}),
                "!= the C native action"),
            "input_time_earlier_100": (
                lambda r: r["observations"]["client_input"].update(
                    {"time": r["observations"]["client_input"]["time"] - 100.0}),
                "not at the recorded input"),
            "input_time_after_window": (
                lambda r: r["observations"]["client_input"].update(
                    {"time": window_end(r) + 5.0}),
                "not at the recorded input"),
            "input_payload_other_action": (
                lambda r: r["observations"]["client_input"].update(
                    {"payload": build_ground_cast_payload(
                        sc.SKYE_NATIVE_ACTIONS["B"])}),
                "the receipt's own bytes do not carry this action"),
            "input_connection": (
                lambda r: r["observations"]["client_input"].update(
                    {"connection": 424243}),
                "input and outcome evidence come from different sessions"),
            "ack_past_window": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"time": window_end(r) + 100.0}),
                "outside the observed action window"),
            "ack_payload_other_action": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"payload": build_position_event(
                        SKYE_EID, sc.SKYE_NATIVE_ACTIONS["A"])}),
                "the receipt's own bytes do not carry this action"),
            "ack_other_connection": (
                lambda r: r["observations"]["acknowledgment"].update(
                    {"connection": 424243}), "acknowledgment.connection"),
            "timer_payload_other_tag": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"payload": build_timer(
                        SKYE_EID, sc.SKYE_COOLDOWN_TAGS["A"])}),
                "the receipt's own bytes carry a different timer"),
            "timer_past_window": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"time": window_end(r) + 101.0}),
                "outside the observed action window"),
            "timer_wrong_slot": (
                lambda r: r["observations"]["cooldown_tag"].update(
                    {"slot": "B"}), "!= 'C'"),
            "outcome_total_epsilon": (
                lambda r: r["observations"]["outcome"].update(
                    {"outcome_total":
                     r["observations"]["outcome"]["outcome_total"] + 0.0001}),
                "at 4 decimals"),
            "damage_other_connection": (
                lambda r: r["observations"]["damage_classification"][
                    "attributed"][0].update({"connection": 424243}),
                "damage from another session was carried as this trial's "
                "outcome"),
        }
        for name, (mutate, needle) in cases.items():
            with self.subTest(case=name):
                vb = self._mutated_b()
                mutate(vb)
                self._assert_refused(f"c-causal-{name}", self.va, vb, needle)


class TestPairCliRoundTrip(unittest.TestCase):
    """Driver result -> serialized JSON -> public compare-pair CLI, using
    the real subprocess (review: exercise the actual integration, not a
    handcrafted test-only schema)."""

    def _run_two_valid_results(self, base: Path, qa_dir: Path):
        results = []
        qa_dir = Path(qa_dir)
        qa_dir.mkdir(parents=True, exist_ok=True)
        (qa_dir / "state.json").write_text(json.dumps({"tick": 100}),
                                           encoding="utf-8")
        for trial in (1, 2):
            harness = Harness("skye-b")
            declared_profile = json.loads(json.dumps(
                {**sc.DEFAULT_PROFILE,
                 "declared_fixture": {
                     **sc.DEFAULT_PROFILE["declared_fixture"],
                     "skye_level": 6,
                     "skye_ranks": {"0": 1, "1": 1, "2": 1},
                     "skye_points": 1,
                     "enemy_level": 1}}))
            profile_path = harness.base / "profile-declared.json"
            profile_path.write_text(json.dumps(declared_profile),
                                    encoding="utf-8")
            real_qa_class = sc.QaSession

            def fake_qa(qa_dir, *, submit=None):
                return real_qa_class(qa_dir, submit=harness.qa.submit)

            import unittest.mock as mock
            out_dir = base / f"trial-{trial}"
            with mock.patch.object(sc, "QaSession", fake_qa), \
                    mock.patch.object(sc, "Adb", lambda serial: harness.adb):
                result = sc.run_client("skye-b", types.SimpleNamespace(
                    adb_serial="emulator-5554", qa_dir=str(qa_dir),
                    wire_trace=str(harness.trace_path), timeout=2.0,
                    output=str(out_dir), connection=424242,
                    client_profile=str(profile_path), reference=None))
            self.assertEqual(result["status"], "PASS",
                             f"trial {trial}: {result.get('failure_detail')}")
            results.append(result)
            shutil.move(str(harness.base), str(base / f"src-{trial}"))
        return results

    def test_serialized_results_round_trip_through_public_cli(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-pair-cli-"))
        try:
            results = self._run_two_valid_results(base, base / "shared-qa")
            path_a = base / "result-a.json"
            path_b = base / "result-b.json"
            path_a.write_text(json.dumps(results[0]), encoding="utf-8")
            path_b.write_text(json.dumps(results[1]), encoding="utf-8")
            import subprocess
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
                 "--mode", "compare-pair",
                 "--result-a", str(path_a),
                 "--result-b", str(path_b)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0,
                             completed.stdout[-2000:] + completed.stderr[-2000:])
            report = json.loads(completed.stdout)
            self.assertTrue(report["controlled_pair"], report["failures"])
            self.assertIn("inputs", report)
            self.assertEqual(report["inputs"]["result_a"]["path"],
                             str(path_a.resolve()))
            report_path = base / "pair-report.json"
            report_path.write_text(json.dumps(report, indent=1),
                                   encoding="utf-8")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_cli_rejects_level_mismatch_with_nonzero_exit(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-pair-cli-"))
        try:
            results = self._run_two_valid_results(base, base / "shared-qa")
            results[1]["fixture_manifest"]["skye"]["level"] = 7
            path_a = base / "result-a.json"
            path_b = base / "result-b.json"
            path_a.write_text(json.dumps(results[0]), encoding="utf-8")
            path_b.write_text(json.dumps(results[1]), encoding="utf-8")
            import subprocess
            completed = subprocess.run(
                [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
                 "--mode", "compare-pair",
                 "--result-a", str(path_a),
                 "--result-b", str(path_b)],
                capture_output=True, text=True, timeout=120)
            self.assertNotEqual(completed.returncode, 0,
                                "a level mismatch must fail the pair gate")
            self.assertIn("level", completed.stdout)
        finally:
            shutil.rmtree(base, ignore_errors=True)


class TestDiagnosticsLinkagePair(unittest.TestCase):
    """Checkpoint 2: the setup-validated diagnostics linkage is carried into
    each writer-produced record and re-validated by the public compare-pair
    CLI. Fresh-session identity (pid/startup_at/match_id/tick/time) is
    judged per record, never across the pair."""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-linkage-pair-"))
        # UNPATCHED writer output: two full driver trials read back from the
        # serialized client-result files the CLI consumes.
        cls.va, cls.vb = produce_pair(cls.base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _cli(self, name, va, vb):
        import subprocess
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
             "--mode", "compare-pair",
             "--result-a", str(pa), "--result-b", str(pb)],
            capture_output=True, text=True, timeout=120)
        try:
            report = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError):
            report = {}
        return completed.returncode, report, completed.stderr

    def test_writer_pair_carries_verbatim_linkage_and_passes(self):
        for label, record in (("A", self.va), ("B", self.vb)):
            self.assertEqual(record["schema_version"], sc.PAIR_SCHEMA_VERSION)
            linkage = record["provenance"]["diagnostics"]
            self.assertEqual(
                linkage, record["observations"]["diagnostics_linkage"],
                f"record {label} must carry the validated linkage VERBATIM, "
                "not a reconstructed copy")
            self.assertIsInstance(linkage["pid"], int)
            self.assertIsInstance(linkage["tick"], int)
            self.assertIsInstance(linkage["startup_at"], float)
            self.assertIsInstance(linkage["time"], float)
            self.assertEqual(linkage["phase"], "world")
            self.assertIs(linkage["match_finished"], False)
            self.assertEqual(linkage["match_id"],
                             record["fixture_manifest"]["match_id"])
        code, report, stderr = self._cli("linkage-pass", self.va, self.vb)
        self.assertEqual(code, 0, stderr)
        self.assertTrue(report["controlled_pair"], report.get("failures"))

    def test_missing_linkage_cannot_be_a_controlled_pair(self):
        vb = json.loads(json.dumps(self.vb))
        del vb["provenance"]["diagnostics"]
        code, report, stderr = self._cli("linkage-missing", self.va, vb)
        self.assertNotEqual(code, 0)
        self.assertFalse(report.get("controlled_pair"))
        self.assertTrue(any("provenance.diagnostics" in f
                            for f in report.get("failures", [])),
                        report.get("failures"))
        self.assertNotIn("Traceback", stderr)

    def test_malformed_linkage_is_a_structured_fail(self):
        cases = {
            "pid_string": {"pid": "4242"},
            "phase_draft": {"phase": "draft"},
            "match_finished_true": {"match_finished": True},
            "tick_string": {"tick": "100"},
            "time_string": {"time": "5.0"},
            "startup_at_none": {"startup_at": None},
            "match_id_empty": {"match_id": ""},
            "linkage_list": [1, 2],
        }
        for name, value in cases.items():
            with self.subTest(case=name):
                vb = json.loads(json.dumps(self.vb))
                if isinstance(value, list):
                    vb["provenance"]["diagnostics"] = value
                else:
                    vb["provenance"]["diagnostics"].update(value)
                code, report, stderr = self._cli(f"linkage-{name}", self.va, vb)
                self.assertNotEqual(code, 0,
                                    f"{name} must not be a controlled pair")
                self.assertFalse(report.get("controlled_pair"))
                self.assertTrue(any("provenance.diagnostics" in f
                                    for f in report.get("failures", [])),
                                report.get("failures"))
                self.assertNotIn("Traceback", stderr)

    def test_linkage_from_another_match_fails_its_own_record(self):
        """A receipt that disagrees with the fixture THIS record measured is
        incoherent even though both records individually look well-formed."""
        vb = json.loads(json.dumps(self.vb))
        vb["provenance"]["diagnostics"]["match_id"] = "some-other-match"
        code, report, stderr = self._cli("linkage-wrong-match", self.va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("not the same match" in f
                            for f in report.get("failures", [])),
                        report.get("failures"))
        self.assertIn("some-other-match", json.dumps(report.get("failures")))

    def test_different_fresh_session_identities_still_pass(self):
        va = json.loads(json.dumps(self.va))
        vb = json.loads(json.dumps(self.vb))
        vb["fixture_manifest"]["match_id"] = "second-fresh-match"
        vb["fixture_manifest"]["tick"] = 7788
        # A whole separate trial: BOTH endpoint receipts carry that trial's
        # own fresh-session identity and the end receipt is still strictly
        # later than its own initial receipt.
        vb["provenance"]["diagnostics"].update(
            {"match_id": "second-fresh-match", "tick": 7788, "time": 999.5,
             "pid": 515151, "startup_at": 77.0})
        vb["provenance"]["diagnostics_end"].update(
            {"match_id": "second-fresh-match", "tick": 7788 + 40,
             "time": 999.5 + 2.0, "pid": 515151, "startup_at": 77.0})
        code, report, stderr = self._cli("linkage-fresh-sessions", va, vb)
        self.assertEqual(code, 0, report.get("failures") or stderr)
        self.assertTrue(report["controlled_pair"])

    def test_previous_schema_record_is_a_negative_input(self):
        """Old schema-2 evidence (no linkage) stays usable as a NEGATIVE
        input: it is never silently upgraded into a controlled pair."""
        vb = json.loads(json.dumps(self.vb))
        vb["schema_version"] = 2
        del vb["provenance"]["diagnostics"]
        code, report, _stderr = self._cli("linkage-old-schema", self.va, vb)
        self.assertNotEqual(code, 0)
        self.assertFalse(report.get("controlled_pair"))
        joined = json.dumps(report.get("failures"))
        self.assertIn("schema_version", joined)
        self.assertIn("provenance.diagnostics", joined)


def run_compare_cli(a_path: Path, b_path: Path):
    """The PUBLIC compare-pair CLI over two serialized records."""
    import subprocess
    completed = subprocess.run(
        [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
         "--mode", "compare-pair",
         "--result-a", str(a_path), "--result-b", str(b_path)],
        capture_output=True, text=True, timeout=120)
    try:
        report = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        report = {}
    return completed.returncode, report, completed.stderr


class TestTrialEndpointContinuity(unittest.TestCase):
    """Checkpoint 4: an end-of-trial diagnostics receipt, read AFTER the
    time-sensitive action sequence, must prove the SAME process, startup and
    match with strictly advancing tick and simulation time. Missing,
    unacknowledged or malformed endpoint evidence is an EVIDENCE failure on
    TRIAL_CONTINUITY — never a controlled pair, and never a rewrite of the
    input/ack/effect stages already observed."""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-endpoint-"))
        # UNPATCHED writer output: two full driver trials read back from the
        # serialized client-result files the CLI consumes.
        cls.va, cls.vb = produce_pair(cls.base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _cli(self, name, va, vb):
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        return run_compare_cli(pa, pb)

    def _endpoint(self, record):
        return record["provenance"]["diagnostics_end"]

    def _assert_endpoint_fail(self, name, va, vb, *needles):
        code, report, stderr = self._cli(name, va, vb)
        self.assertNotEqual(code, 0, f"{name} must not be a controlled pair")
        self.assertFalse(report.get("controlled_pair"))
        joined = json.dumps(report.get("failures"))
        for needle in needles:
            self.assertIn(needle, joined, f"expected {needle!r} in {joined}")
        self.assertNotIn("Traceback", stderr)
        return report

    def test_writer_pair_carries_both_receipts_and_passes(self):
        for label, record in (("A", self.va), ("B", self.vb)):
            self.assertEqual(record["schema_version"], sc.PAIR_SCHEMA_VERSION)
            initial = record["provenance"]["diagnostics"]
            end = self._endpoint(record)
            self.assertEqual(
                initial, record["observations"]["diagnostics_linkage"],
                f"record {label}: the initial receipt must be carried verbatim")
            self.assertEqual(
                end, record["observations"]["diagnostics_linkage_end"],
                f"record {label}: the endpoint receipt must be carried "
                "verbatim, not reconstructed")
            # ONE trial: same process, startup and match at both ends
            self.assertEqual(initial["pid"], end["pid"])
            self.assertEqual(initial["startup_at"], end["startup_at"])
            self.assertEqual(initial["match_id"], end["match_id"])
            self.assertEqual(end["match_id"],
                             record["fixture_manifest"]["match_id"])
            self.assertEqual(end["phase"], "world")
            self.assertIs(end["match_finished"], False)
            # the fake world really advanced between the two reads
            self.assertGreater(end["tick"], initial["tick"])
            self.assertGreater(end["time"], initial["time"])
            self.assertEqual(record["stages"]["TRIAL_CONTINUITY"]["status"],
                             "PASS")
        code, report, stderr = self._cli("endpoint-pass", self.va, self.vb)
        self.assertEqual(code, 0, stderr)
        self.assertTrue(report["controlled_pair"], report.get("failures"))

    def test_endpoint_identity_changes_fail_continuity(self):
        cases = {
            "pid_changed": {"pid": 999999},
            "startup_changed": {"startup_at": 4242.0},
            "match_changed": {"match_id": "some-other-match"},
        }
        for name, mutation in cases.items():
            with self.subTest(case=name):
                vb = json.loads(json.dumps(self.vb))
                self._endpoint(vb).update(mutation)
                self._assert_endpoint_fail(
                    f"endpoint-{name}", self.va, vb, "trial continuity")

    def test_endpoint_world_state_must_stay_active(self):
        cases = {
            "phase_draft": {"phase": "draft"},
            "finished": {"match_finished": True},
        }
        for name, mutation in cases.items():
            with self.subTest(case=name):
                vb = json.loads(json.dumps(self.vb))
                self._endpoint(vb).update(mutation)
                self._assert_endpoint_fail(
                    f"endpoint-{name}", self.va, vb, "provenance.diagnostics_end")

    def test_missing_or_malformed_endpoint_receipt_fails(self):
        cases = {
            "missing": None,
            "non_object": [1, 2, 3],
            "pid_string": {"pid": "4242"},
            "startup_none": {"startup_at": None},
            "tick_string": {"tick": "140"},
            "time_string": {"time": "7.0"},
            "match_id_empty": {"match_id": ""},
            "phase_missing": {"phase": _REMOVE},
        }
        for name, mutation in cases.items():
            with self.subTest(case=name):
                vb = json.loads(json.dumps(self.vb))
                if mutation is None:
                    del vb["provenance"]["diagnostics_end"]
                elif isinstance(mutation, list):
                    vb["provenance"]["diagnostics_end"] = mutation
                else:
                    for key, value in mutation.items():
                        if value is _REMOVE:
                            del vb["provenance"]["diagnostics_end"][key]
                        else:
                            self._endpoint(vb)[key] = value
                self._assert_endpoint_fail(
                    f"endpoint-{name}", self.va, vb,
                    "provenance.diagnostics_end")

    def test_stalled_or_regressed_progress_fails(self):
        cases = (
            ("tick_stalled", "tick", "stalled"),
            ("tick_regressed", "tick", "regressed"),
            ("time_stalled", "time", "stalled"),
            ("time_regressed", "time", "regressed"),
        )
        for name, field, mode in cases:
            with self.subTest(case=name):
                vb = json.loads(json.dumps(self.vb))
                initial = vb["provenance"]["diagnostics"]
                if mode == "stalled":
                    vb["provenance"]["diagnostics_end"][field] = initial[field]
                elif field == "tick":
                    vb["provenance"]["diagnostics_end"][field] = (
                        initial["tick"] - 40)
                else:
                    vb["provenance"]["diagnostics_end"][field] = (
                        initial["time"] - 2.0)
                self._assert_endpoint_fail(
                    f"endpoint-{name}", self.va, vb, "trial continuity",
                    "did not strictly advance")

    def test_identical_malformed_endpoint_in_both_records_fails(self):
        """Two records that agree on a MALFORMED endpoint receipt are not a
        controlled pair: agreement is never evidence."""
        va = json.loads(json.dumps(self.va))
        vb = json.loads(json.dumps(self.vb))
        for record in (va, vb):
            self._endpoint(record)["tick"] = "identical-garbage"
        self._assert_endpoint_fail("endpoint-identical-malformed", va, vb,
                                   "provenance.diagnostics_end")

    def test_previous_schema_three_record_is_a_negative_input(self):
        """Old schema-3 evidence (initial linkage only, no endpoint receipt)
        stays usable as a NEGATIVE input — never silently upgraded."""
        vb = json.loads(json.dumps(self.vb))
        vb["schema_version"] = 3
        del vb["provenance"]["diagnostics_end"]
        code, report, _stderr = self._cli("endpoint-old-schema", self.va, vb)
        self.assertNotEqual(code, 0)
        self.assertFalse(report.get("controlled_pair"))
        joined = json.dumps(report.get("failures"))
        self.assertIn("schema_version", joined)
        self.assertIn("provenance.diagnostics_end", joined)

    def _driver_endpoint_failure(self, name, prepare):
        base = Path(tempfile.mkdtemp(prefix=f"halcyon-endpoint-{name}-"))
        try:
            result, _harness = run_trial(base, 1, prepare=prepare)
            self.assertEqual(result["status"], "FAIL",
                             result.get("failure_detail"))
            self.assertEqual(result["first_failed_stage"], "TRIAL_CONTINUITY")
            stages = result["stages"]
            # the time-sensitive sequence was already OBSERVED: an endpoint
            # collection problem never rewrites those stages
            for stage in ("UI_COMMAND_SUBMITTED", "CLIENT_INPUT_OBSERVED",
                          "SERVER_ACKNOWLEDGED", "AUTHORITATIVE_EFFECT"):
                self.assertEqual(stages[stage]["status"], "PASS",
                                 f"{stage} was observed before the endpoint "
                                 "read and must keep its own status")
            for stage in stages:
                if stage != "TRIAL_CONTINUITY":
                    self.assertNotEqual(stages[stage]["status"], "FAIL",
                                        f"{stage} must not be blamed for an "
                                        "endpoint evidence failure")
            observations = result["observations"]
            self.assertIn("diagnostics_linkage", observations,
                          "the initial validated receipt must be retained")
            self.assertNotIn(
                "diagnostics_linkage_end", observations,
                "an endpoint read that failed evidence validation never "
                "fabricates a linkage")
            self.assertIn("damage_classification", observations)
            self.assertIn("cooldown_tag", observations)
            self.assertIn("outcome", observations)
            self.assertTrue(Path(result["result_path"]).exists(),
                            "the failure result keeps its evidence on disk")
            return result
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_unacknowledged_endpoint_receipt_is_an_evidence_failure(self):
        result = self._driver_endpoint_failure(
            "pending", unacknowledged_endpoint)
        self.assertEqual(result["stages"]["TRIAL_CONTINUITY"]["status"],
                         "UNVERIFIED")
        detail = result["failure_detail"]
        self.assertIn("endpoint diagnostics", detail)
        self.assertNotIn("UI action", detail)

    def test_malformed_endpoint_receipt_is_an_evidence_failure(self):
        result = self._driver_endpoint_failure(
            "malformed", non_object_endpoint)
        self.assertEqual(result["stages"]["TRIAL_CONTINUITY"]["status"],
                         "FAIL")
        self.assertIn("not an object", result["failure_detail"])

    def test_changed_pid_endpoint_through_the_driver_fails_continuity(self):
        result = self._driver_endpoint_failure(
            "pid", lambda harness: mutate_endpoint_diagnostics(
                harness, pid=999999))
        self.assertIn("trial endpoint continuity violated",
                      result["failure_detail"])
        self.assertIn("pid changed within the trial",
                      result["failure_detail"])


class TestEnvTraceNormalization(unittest.TestCase):
    """Checkpoint 3: HALCYON_TRACE_WIRE is an ENABLE SWITCH. Production
    match_server reads only its truthiness and generates its own
    wire-<ns>.jsonl path, so the recorded string is the switch setting, not
    necessarily the file written: two ENABLED trials are equivalent whatever
    they recorded. Enabled vs disabled, a present key vs an absent one, and
    every other environment flag still fail; a present non-string value is
    malformed receipt evidence and is rejected per record."""

    @classmethod
    def _produce_trial(cls, base: Path, trial: int, trace_value):
        """One full writer trial whose diagnostics receipt reports the given
        trace configuration; returns the SERIALIZED record."""
        import unittest.mock as mock
        qa_dir = base / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        (qa_dir / "state.json").write_text(json.dumps({"tick": 100}),
                                           encoding="utf-8")
        harness = Harness("skye-b")
        mutate_diagnostics(harness, env={"HALCYON_NO_BOTS": "1",
                                         "HALCYON_TRACE_WIRE": trace_value})
        declared_profile = json.loads(json.dumps({
            **sc.DEFAULT_PROFILE,
            "declared_fixture": {
                **sc.DEFAULT_PROFILE["declared_fixture"],
                "skye_level": 6,
                "skye_ranks": {"0": 1, "1": 1, "2": 1},
                "skye_points": 1,
                "enemy_points": 1,
                "enemy_level": 1}}))
        profile_path = base / f"profile-{trial}.json"
        profile_path.write_text(json.dumps(declared_profile), encoding="utf-8")
        real_qa_class = sc.QaSession

        def fake_qa(qa_dir, *, submit=None):
            return real_qa_class(qa_dir, submit=harness.qa.submit)

        out_dir = base / f"trial-{trial}"
        with mock.patch.object(sc, "QaSession", fake_qa), \
                mock.patch.object(sc, "Adb", lambda serial: harness.adb):
            result = sc.run_client("skye-b", types.SimpleNamespace(
                adb_serial="emulator-5554", qa_dir=str(qa_dir),
                wire_trace=str(harness.trace_path), timeout=2.0,
                output=str(out_dir), connection=424242,
                client_profile=str(profile_path), reference=None))
        assert result["status"] == "PASS", result.get("failure_detail")
        return json.loads(Path(result["result_path"]).read_text(encoding="utf-8"))

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-trace-env-"))
        cls.trace_a = "C:/traces/wire-111.jsonl"
        cls.trace_b = "C:/traces/wire-222.jsonl"
        cls.va = cls._produce_trial(cls.base, 1, cls.trace_a)
        cls.vb = cls._produce_trial(cls.base, 2, cls.trace_b)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _cli(self, name, va, vb):
        """Public CLI over the exact bytes; also proves the CLI never rewrites
        its inputs (raw recorded paths stay raw)."""
        import subprocess
        case = self.base / f"cli-{name}"
        case.mkdir(exist_ok=True)
        pa = case / "a.json"
        pb = case / "b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        before = (pa.read_bytes(), pb.read_bytes())
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
             "--mode", "compare-pair", "--result-a", str(pa),
             "--result-b", str(pb)],
            capture_output=True, text=True, timeout=120)
        (case / "stdout.txt").write_text(completed.stdout, encoding="utf-8")
        (case / "stderr.txt").write_text(completed.stderr, encoding="utf-8")
        (case / "exit.txt").write_text(str(completed.returncode),
                                       encoding="utf-8")
        self.assertEqual((pa.read_bytes(), pb.read_bytes()), before,
                         "the pair CLI must never rewrite its inputs")
        try:
            report = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError):
            report = {}
        return completed.returncode, report, completed.stderr

    def test_writer_records_carry_the_raw_trace_values(self):
        for label, record, expected in (("A", self.va, self.trace_a),
                                        ("B", self.vb, self.trace_b)):
            raw = record["provenance"]["env_config"]["HALCYON_TRACE_WIRE"]
            self.assertEqual(raw, expected,
                             f"record {label} must keep the RAW recorded "
                             "switch value")

    def test_trace_destination_only_difference_passes(self):
        code, report, stderr = self._cli("trace-only", self.va, self.vb)
        self.assertEqual(code, 0, report.get("failures") or stderr)
        self.assertTrue(report["controlled_pair"], report.get("failures"))
        evidence = report["env_trace_normalization"]
        self.assertEqual(evidence["raw_a"], self.trace_a)
        self.assertEqual(evidence["raw_b"], self.trace_b)
        self.assertTrue(evidence["enabled_a"] and evidence["enabled_b"])
        self.assertTrue(evidence["normalized_equal"])
        self.assertIn("normalized", report["gates"]["provenance"]["detail"])

    def test_trace_enabled_versus_disabled_fails(self):
        cases = {
            "disabled_none": None,
            "disabled_empty": "",
            "key_absent": _REMOVE,
        }
        for name, value in cases.items():
            with self.subTest(case=name):
                vb = json.loads(json.dumps(self.vb))
                if value is _REMOVE:
                    del vb["provenance"]["env_config"]["HALCYON_TRACE_WIRE"]
                else:
                    vb["provenance"]["env_config"]["HALCYON_TRACE_WIRE"] = value
                code, report, stderr = self._cli(f"trace-{name}", self.va, vb)
                self.assertNotEqual(code, 0, f"{name} must not be a pair")
                self.assertFalse(report.get("controlled_pair"))
                self.assertTrue(any("env_config" in f
                                    for f in report.get("failures", [])),
                                report.get("failures"))
                self.assertNotIn("Traceback", stderr)

    def test_non_trace_semantic_flag_difference_fails(self):
        cases = {
            "no_bots_value": ("HALCYON_NO_BOTS", "0"),
            "no_bots_absent": ("HALCYON_NO_BOTS", _REMOVE),
            "no_wave_added": ("HALCYON_NO_WAVE", "1"),
        }
        for name, (flag, value) in cases.items():
            with self.subTest(case=name):
                vb = json.loads(json.dumps(self.vb))
                if value is _REMOVE:
                    del vb["provenance"]["env_config"][flag]
                else:
                    vb["provenance"]["env_config"][flag] = value
                code, report, stderr = self._cli(f"flag-{name}", self.va, vb)
                self.assertNotEqual(code, 0,
                                    f"{name} must not be a pair")
                self.assertFalse(report.get("controlled_pair"))
                self.assertTrue(any("env_config" in f
                                    for f in report.get("failures", [])),
                                report.get("failures"))
                self.assertNotIn("Traceback", stderr)

    def test_normalizer_touches_only_the_trace_switch(self):
        key = "HALCYON_TRACE_WIRE"
        norm = sc.normalize_env_config
        env = {"HALCYON_NO_BOTS": "1", "HALCYON_NO_TAPE": None,
               key: "C:/x/wire-1.jsonl"}
        normalized = norm(env)
        self.assertEqual(normalized["HALCYON_NO_BOTS"], "1",
                         "non-trace flags keep their exact recorded value")
        self.assertIsNone(normalized["HALCYON_NO_TAPE"])
        # enabled vs disabled is the ONLY distinction the switch carries
        self.assertNotEqual(normalized[key], norm({key: ""})[key])
        self.assertNotEqual(normalized[key], norm({key: None})[key])
        self.assertEqual(normalized[key], norm({key: "D:/other/wire-9.jsonl"})[key],
                         "two enabled trials are equivalent whatever they "
                         "recorded")
        self.assertEqual(norm({key: None}), norm({key: ""}),
                         "null and empty are both disabled")
        # malformed (non-string) evidence is carried verbatim, never coerced,
        # and can never collide with a valid switch value (the earlier
        # boolean form made True == 1 a false PASS)
        self.assertEqual(norm({key: 5})[key], 5)
        self.assertNotEqual(norm({key: 1})[key], norm({key: "1"})[key])
        self.assertNotEqual(norm({key: True})[key], norm({key: "x"})[key])
        self.assertNotEqual(norm({key: 0})[key], norm({key: ""})[key])
        self.assertNotEqual(norm({key: False})[key], norm({key: None})[key])
        # a non-dict env_config is returned untouched for the caller to fail
        self.assertEqual(norm([1]), [1])
        self.assertEqual(norm(None), None)

    def test_malformed_trace_value_types_fail_through_the_cli(self):
        """The witnessed false PASS: a malformed numeric 1 normalized to the
        same value as a valid enabled string. Every malformed shape must be a
        structured per-record FAIL, cross-pair AND identical on both sides."""
        cases = [(value, reference_label, reference)
                 for value in (1, 0, True, False)
                 for reference_label, reference in (
                     ("enabled_string", self.trace_a),
                     ("disabled_null", None),
                     ("disabled_empty", ""))]
        cases += [(value, "enabled_string", self.trace_a)
                  for value in (1.0, ["C:/x"], {"path": "C:/x"})]
        for value, reference_label, reference in cases:
                with self.subTest(case=f"{value!r}_vs_{reference_label}"):
                    vb = json.loads(json.dumps(self.vb))
                    va = json.loads(json.dumps(self.va))
                    vb["provenance"]["env_config"]["HALCYON_TRACE_WIRE"] = value
                    va["provenance"]["env_config"]["HALCYON_TRACE_WIRE"] = reference
                    code, report, stderr = self._cli(
                        f"malformed-{type(value).__name__}-{reference_label}",
                        va, vb)
                    self.assertNotEqual(code, 0,
                                        f"{value!r} must not pair with "
                                        f"{reference_label}")
                    self.assertFalse(report.get("controlled_pair"))
                    self.assertTrue(
                        any("HALCYON_TRACE_WIRE" in f
                            for f in report.get("failures", [])),
                        report.get("failures"))
                    self.assertNotIn("Traceback", stderr)
        for value in (1, 0, True, False):
            with self.subTest(case=f"identical_malformed_{value!r}_both_records"):
                va = json.loads(json.dumps(self.va))
                vb = json.loads(json.dumps(self.vb))
                for record in (va, vb):
                    record["provenance"]["env_config"][
                        "HALCYON_TRACE_WIRE"] = value
                code, report, stderr = self._cli(
                    f"identical-malformed-{type(value).__name__}", va, vb)
                self.assertNotEqual(
                    code, 0,
                    "identical malformed evidence is rejected per record, "
                    "never accepted by equality")
                self.assertFalse(report.get("controlled_pair"))
                self.assertTrue(any("HALCYON_TRACE_WIRE" in f
                                    for f in report.get("failures", [])),
                                report.get("failures"))
                self.assertNotIn("Traceback", stderr)


class TestProofMatrix(unittest.TestCase):
    """Mandatory proof matrix (review): each row mutates ONE thing from a
    known-valid driver-produced pair and runs the PUBLIC compare-pair CLI.
    OFFLINE seam-driven evidence, not live proof."""

    @classmethod
    def _produce_valid_pair(cls, base: Path):
        from server.test.test_scenario_client import produce_pair
        return produce_pair(base)

    @classmethod
    def _cli(cls, result_a: Path, result_b: Path):
        import subprocess
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
             "--mode", "compare-pair",
             "--result-a", str(result_a),
             "--result-b", str(result_b)],
            capture_output=True, text=True, timeout=120)
        report = None
        try:
            report = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError):
            pass
        return completed.returncode, report, completed.stderr

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-matrix-"))
        va, vb = cls._produce_valid_pair(cls.base)
        cls.base_va = va
        cls.base_vb = vb
        (cls.base / "matrix-pass.json").write_text(
            json.dumps([va, vb]), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _write_pair(self, name, va, vb):
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        return pa, pb

    def _run_pair(self, name, va, vb):
        pa, pb = self._write_pair(name, va, vb)
        code, _report, _stderr = self._cli(pa, pb)
        return code

    def _run_pair_report(self, name, va, vb):
        pa, pb = self._write_pair(name, va, vb)
        code, report, stderr = self._cli_with_report(pa, pb)
        return code, report, stderr

    def _cli_with_report(self, pa, pb):
        import subprocess
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
             "--mode", "compare-pair",
             "--result-a", str(pa),
             "--result-b", str(pb)],
            capture_output=True, text=True, timeout=120)
        try:
            report = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError):
            report = {"raw_stdout": completed.stdout,
                      "raw_stderr": completed.stderr}
        return completed.returncode, report, completed.stderr

    def test_row1_no_semantic_change_passes(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        code = self._run_pair("matrix-unchanged", va, vb)
        self.assertEqual(code, 0)

    def test_row2_fresh_match_identity_only_passes(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        # fresh-match identity: match id, tick, connection, trace, pid/time.
        # Each record must stay INTERNALLY coherent (its diagnostics receipt
        # belongs to the match its own manifest measured); the pair is never
        # required to share those fresh-session identities.
        vb["fixture_manifest"]["match_id"] = "fresh-second-match"
        vb["fixture_manifest"]["tick"] = 9999
        # fresh-session identity covers BOTH endpoint receipts: the record
        # stays internally coherent (same process/match across its own
        # trial, end strictly later) without matching record A.
        self._rehome_connection(vb, 999999)
        for receipt in ("diagnostics", "diagnostics_end"):
            vb["provenance"][receipt]["match_id"] = "fresh-second-match"
            vb["provenance"][receipt]["pid"] = 424242
            vb["provenance"][receipt]["startup_at"] = 42.0
        vb["provenance"]["diagnostics"].update({"tick": 9999, "time": 4242.5})
        vb["provenance"]["diagnostics_end"].update({"tick": 9999 + 40,
                                                    "time": 4242.5 + 2.0})
        # record A also sits on a connection of its own, so the pair proves
        # that two genuinely fresh sessions normalize to PASS
        self._rehome_connection(va, 111111)
        code, _report = self._run_pair_with_b("matrix-fresh-identity", va, vb)
        self.assertEqual(code, 0, "fresh-session identity differences must "
                                  "normalize to PASS")

    @staticmethod
    def _rehome_connection(record, connection):
        """Move a record onto its OWN fresh-session connection id.

        A new session does not inherit its peer's connection: it names the new
        one in the manifest and in every piece of carried causal evidence
        (input, acknowledgment, timer receipt, attributed damage). Re-homing
        only the top-level field would leave the record incoherent with its own
        measured outcome, which is exactly what the causal gate refuses.
        """
        record["connection"] = connection
        record["fixture_manifest"]["connection"] = connection
        observations = record.get("observations") or {}
        for key in ("client_input", "acknowledgment", "cooldown_tag"):
            receipt = observations.get(key)
            if isinstance(receipt, dict):
                receipt["connection"] = connection
        classification = observations.get("damage_classification") or {}
        for hit in classification.get("attributed") or []:
            if isinstance(hit, dict):
                hit["connection"] = connection

    def _run_pair_with_b(self, name, va, vb):
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        import subprocess
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
             "--mode", "compare-pair",
             "--result-a", str(pa),
             "--result-b", str(pb)],
            capture_output=True, text=True, timeout=120)
        try:
            report = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError):
            report = {}
        return completed.returncode, report

    def _run_pair_report_named(self, name, va, vb):
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        import subprocess
        completed = subprocess.run(
            [sys.executable, "-B", str(ROOT / "Tools" / "run_scenarios.py"),
             "--mode", "compare-pair",
             "--result-a", str(pa),
             "--result-b", str(pb)],
            capture_output=True, text=True, timeout=120)
        try:
            report = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError):
            report = {}
        return completed.returncode, report

    def test_row3_different_source_digest_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        vb["provenance"]["source_startup_digest"] = "a" * 64
        vb["provenance"]["source_current_digest"] = "a" * 64
        code, report = self._run_pair_report_named("matrix-src", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("source" in f for f in report.get("failures", [])),
                        report.get("failures"))

    def test_row4_different_loaded_tape_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        vb["provenance"]["tape_loaded"] = {"records": 999,
                                           "sha256": "c" * 64}
        code, report = self._run_pair_report_named("matrix-tape", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("tape_loaded" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row5_different_client_build_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        vb["provenance"]["client_version"] = {"version_name": "4.20.0",
                                              "version_code": 999999}
        code, report = self._run_pair_report_named("matrix-client", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("client_version" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row6_different_profile_digest_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        vb["fixture_manifest"]["profile_digest"] = "b" * 64
        code, report = self._run_pair_report_named("matrix-profile", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("profile" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row7_startup_ne_current_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        vb["provenance"]["source_current_digest"] = "0" * 64
        code, report = self._run_pair_report_named("matrix-startcur", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("source_current" in f or "changed" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row8_measured_level_differs_from_declaration_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        vb["fixture_manifest"]["declared_fixture"]["skye_level"] = 99
        code, report = self._run_pair_report_named("matrix-decl99", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("declared" in f or "level" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row8b_inventory_differs_across_runs_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        va["fixture_manifest"]["skye"]["inventory"] = [
            {"slot": 0, "item": 3100, "instance": 77}]
        code, report = self._run_pair_report_named("matrix-inv", va, vb)
        self.assertNotEqual(code, 0)

    def test_row9_required_actor_field_missing_on_both_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        for r in (va, vb):
            r["fixture_manifest"]["enemy"]["level"] = None
        code, report = self._run_pair_report_named("matrix-nolevel", va, vb)
        self.assertNotEqual(code, 0)

    def test_row10_scenario_slot_mismatch_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        va["scenario"] = "skye-a"
        vb["scenario"] = "skye-a"
        va["fixture_manifest"]["slot"] = "A"
        vb["fixture_manifest"]["slot"] = "C"
        code, report = self._run_pair_report_named("matrix-slotmm", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("slot" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row11_damage_evidence_removed_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        for r in (va, vb):
            r["observations"]["damage_classification"]["attributed"] = []
        code, report = self._run_pair_report_named("matrix-nodmg", va, vb)
        self.assertNotEqual(code, 0)

    def test_row11b_basic_tail_relabeled_as_ability_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        attributed = (vb["observations"]["damage_classification"]
                      ["attributed"])
        # relabel a basic-tail hit (000500) as attributed
        attributed[0]["payload"] = struct.pack(
            ">IIf", 1517, 1500,
            attributed[0]["delta"]).hex() + bytes.fromhex("0005000000000000").hex()
        code, report = self._run_pair_report_named("matrix-basicrelabel",
                                                   va, vb)
        self.assertNotEqual(code, 0)

    def test_row12_changed_attributable_count_or_total_fails(self):
        # The record stays INTERNALLY coherent — one fewer measured hit, and
        # its own outcome summary updated to that shorter attribution — so the
        # refusal here comes from the PAIR's exact event-count/total comparison
        # and not from a per-record causal failure. (A record whose summary
        # contradicts its own attribution is refused by the causal gate; see
        # TestSkyeBCausalEvidence.test_outcome_summary_tamper_is_refused_exactly.)
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        classification = vb["observations"]["damage_classification"]
        classification["attributed"].pop()
        vb["observations"]["outcome"] = {
            "attributed_events": len(classification["attributed"]),
            "outcome_total": round(sum(hit["delta"] for hit in
                                       classification["attributed"]),
                                   sc.OUTCOME_TOTAL_DECIMALS)}
        code, report = self._run_pair_report_named("matrix-count", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("counts differ" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row13_malformed_nested_entry_is_structured_fail(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        vb["observations"]["damage_classification"]["attributed"] = [
            None, {"delta": "bad", "payload": 5}]
        code, report = self._run_pair_report_named("matrix-malformed",
                                                   va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("malformed" in f or "payload" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row2b_process_id_and_time_differ_passes(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        # a different PROCESS (pid/startup_at) is fresh-session identity:
        # both receipts of record B carry it, so the trial stays coherent
        for receipt in ("diagnostics", "diagnostics_end"):
            vb["provenance"][receipt]["pid"] = 424242
            vb["provenance"][receipt]["startup_at"] = 42.0
        code, report = self._run_pair_report_named("matrix-pidtime", va, vb)
        self.assertEqual(code, 0, report.get("failures"))

    def test_row7b_unknown_loaded_tape_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        vb["provenance"]["tape_loaded"] = {"identity": "UNKNOWN"}
        code, report = self._run_pair_report_named("matrix-unknowntape",
                                                   va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("tape_loaded" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row11c_healing_only_damage_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        for r in (va, vb):
            r["observations"]["damage_classification"]["attributed"] = [
                {"time": 1.0, "delta": 5.0,
                 "payload": struct.pack(">IIf", 1517, 1500, 5.0).hex()
                 + bytes.fromhex("0005040000000000").hex(),
                 "reason": "COMBAT_DELTA_TAIL (non-basic source)"}]
            r["observed"]["outcome_total"] = 5.0
        code, report = self._run_pair_report_named("matrix-healonly",
                                                   va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("damage" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))

    def test_row11d_empty_attributed_list_fails(self):
        va = json.loads(json.dumps(self.base_va))
        vb = json.loads(json.dumps(self.base_vb))
        for r in (va, vb):
            r["observations"]["damage_classification"]["attributed"] = []
            r["observations"]["damage_classification"]["window"] = [1.0, 2.0]
            r["observations"]["cooldown_tag"] = {"slot": "A",
                                                 "tag": "43a890d8"}
        code, report = self._run_pair_report_named("matrix-emptya", va, vb)
        self.assertNotEqual(code, 0)
        self.assertTrue(any("no attributed" in f or "attributed" in f for f in
                            report.get("failures", [])),
                        report.get("failures"))


class TestRunClientRefusals(unittest.TestCase):
    def _args(self, **overrides):
        namespace = {"adb_serial": "emulator-5554", "qa_dir": "Z:/nope",
                     "wire_trace": "Z:/nope.jsonl", "timeout": 1.0,
                     "output": None, "connection": None, "client_profile": None,
                     "reference": None}
        namespace.update(overrides)
        return types.SimpleNamespace(**namespace)

    def test_missing_adb_serial_is_setup_failure(self):
        result = sc.run_client("skye-a", self._args(adb_serial=None))
        self.assertEqual(result["first_failed_stage"], "SETUP")
        self.assertTrue(Path(result["result_path"]).is_file(),
                        "partial failure evidence must be written")

    def test_missing_qa_dir_is_setup_failure(self):
        result = sc.run_client("skye-a", self._args(qa_dir=None))
        self.assertEqual(result["first_failed_stage"], "SETUP")

    def test_unsupported_scenario_is_refused(self):
        result = sc.run_client("skye-d", self._args())
        self.assertEqual(result["status"], "FAIL")

    def test_bad_profile_json_is_setup_failure(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-profile-test-"))
        try:
            bad = base / "profile.json"
            bad.write_text("{broken", encoding="utf-8")
            result = sc.run_client("skye-a",
                                   self._args(client_profile=str(bad)))
            self.assertEqual(result["first_failed_stage"], "SETUP")
            self.assertIn("profile", result["failure_detail"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_qa_submit_clamps_stage_timeout_to_mailbox_bound(self):
        """Live-run finding 2026-09-10: the driver's stage --timeout (e.g. 25 s)
        was passed into the QA mailbox whose legal bound is 0..10 s."""
        harness = Harness("skye-a")
        try:
            driver = harness.driver(timeout=25.0)
            seen = {}

            def spy(command, *, timeout=5.0, request_id=None):
                seen["timeout"] = timeout
                return {"id": request_id, "ok": True, "result": {}}

            driver.qa._submit = spy
            driver.qa.submit({"command": "snapshot"}, label="snapshot",
                             timeout=25.0)
            self.assertLessEqual(seen["timeout"], 10.0)
        finally:
            harness.cleanup()

    def test_undeclared_fixture_refusal_is_a_stable_setup_failure(self):
        """Live finding 2026-09-12 (ckpt13corr9): with the built-in profile —
        resource policies declared, level/ranks/points deliberately unknown —
        the cast gate refuses before input. That refusal must be a structured
        SETUP/FAIL that persists a client-result artifact; it must not die on
        the failure path itself (the contract was previously assigned only
        AFTER validation passed, so the failure handler raised AttributeError
        and wrote nothing)."""
        harness = Harness("skye-a")
        try:
            qa_dir = harness.base / "qa"
            qa_dir.mkdir(exist_ok=True)
            (qa_dir / "state.json").write_text(json.dumps({"tick": 100}),
                                               encoding="utf-8")
            # Exactly the live default declaration set (policies only);
            # camera settle shortened because this test is about the
            # refusal, not camera framing.
            profile_path = harness.base / "profile-live-default.json"
            profile_path.write_text(json.dumps({
                "camera_settle_s": 0,
                "declared_fixture": dict(sc.DEFAULT_PROFILE["declared_fixture"]),
            }), encoding="utf-8")
            out_dir = harness.base / "runner-out"
            real_qa_class = sc.QaSession

            def fake_qa(qa_dir, *, submit=None):
                return real_qa_class(qa_dir, submit=harness.qa.submit)

            with mock.patch.object(sc, "QaSession", fake_qa), \
                    mock.patch.object(sc, "Adb", lambda serial: harness.adb):
                result = sc.run_client("skye-a", types.SimpleNamespace(
                    adb_serial="emulator-5554", qa_dir=str(qa_dir),
                    wire_trace=str(harness.trace_path), timeout=2.0,
                    output=str(out_dir), connection=424242,
                    client_profile=str(profile_path), reference=None))

            self.assertEqual(result["status"], "FAIL",
                             "a fixture refusal is a classified failure")
            self.assertEqual(result["first_failed_stage"], "SETUP")
            self.assertEqual(result["stages"]["SETUP"]["status"], "FAIL")
            self.assertNotIn("failure_kind", result,
                             "this is a pre-input refusal, not an "
                             "infrastructure ERROR")
            detail = result["failure_detail"]
            self.assertIn("declared fixture contract violated before input",
                          detail)
            for field in ("skye level", "skye ranks", "skye ability_points",
                          "enemy level"):
                self.assertIn(field, detail)
            # The refused contract is carried verbatim: undeclared stays
            # None, policy declarations mirror the profile, nothing is
            # synthesized.
            contract = result["fixture_contract"]
            self.assertIsNotNone(contract)
            self.assertIsNone(contract["skye"]["level"])
            self.assertIsNone(contract["skye"]["ranks"])
            self.assertIsNone(contract["skye"]["ability_points"])
            self.assertIsNone(contract["enemy"]["level"])
            self.assertEqual(contract["declared_fixture"],
                             sc.DEFAULT_PROFILE["declared_fixture"])
            # The structured record reaches disk.
            self.assertTrue(result["result_path"], "failure result persisted")
            persisted_path = Path(result["result_path"])
            self.assertEqual(persisted_path.parent, out_dir)
            persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "FAIL")
            self.assertEqual(persisted["failure_detail"], detail)
            # JSON has no tuples; the persisted contract is the same value
            # the returned record carries.
            self.assertEqual(persisted["fixture_contract"],
                             json.loads(json.dumps(contract)))
        finally:
            harness.cleanup()

    def test_repository_output_destination_is_refused(self):
        unsafe = str(ROOT / "Docs" / "halcyon-client-out-test")
        result = sc.run_client("skye-a", self._args(output=unsafe))
        self.assertEqual(result["first_failed_stage"], "SETUP")
        self.assertIn("invalid output directory", result["failure_detail"])
        self.assertFalse(Path(unsafe).exists(),
                         "a refused destination must not be created")


class TestSchemaInvariant(unittest.TestCase):
    """Focused regression coverage for the schema invariant end-to-end.

    A generated valid record (NOT a live QA driver result) is mutated with
    one named defect at a time, fed through the public compare-pair CLI,
    and verified to surface a structured FAIL with field-specific reasons
    and a nonzero exit code. No mocked cast delays, no live QA.

    Witnesses reproduced (matching the dispatch list):
      - missing_inventory_both, missing_statuses_both, missing_enemy_x_both
      - contract_declared_ranks_string
      - stage_null, actor_list, observations_list, contract_actor_list
      - contract_tolerance_string, contract_exact_string
      - hit_delta_string  (preserved structured FAIL)
    """

    def _base_record(self):
        """A generated valid record carrying the full new schema fields.

        Built entirely from constants; never uses a live QA result. Mirrors
        the shape ``run_client`` actually emits so the new validator (which
        consumes the carried contract and manifest) accepts it cleanly —
        including the causal block (input / acknowledgment / timer tag /
        window / outcome), which is self-consistent by construction rather
        than measured. The witnesses below mutate one field at a time and
        assert the structured refusal, so the class needs a validator-accepted
        base; the writer-produced positive lives in
        TestSkyeBCausalEvidence.
        """
        contract = sc.build_fixture_contract(
            {**sc.DEFAULT_PROFILE,
             "declared_fixture": {
                 **sc.DEFAULT_PROFILE["declared_fixture"],
                 "skye_level": 6,
                 "skye_ranks": {"0": 1, "1": 1, "2": 1},
                 "skye_points": 1,
                 "enemy_level": 6}},
            "B")
        # build a 1054 payload matching the dispatch's COMBAT_DELTA_TAIL
        # (ability tail kind 0x04 at byte 14, f32 delta).
        from server.test.test_scenario_client import build_damage
        payload = build_damage(1517, 1500, -30.0)
        return {
            "schema_version": sc.PAIR_SCHEMA_VERSION,
            "scenario": "skye-b",
            "status": "PASS",
            "stages": {k: {"status": "PASS"} for k in (
                "SETUP", "UI_COMMAND_SUBMITTED", "CLIENT_INPUT_OBSERVED",
                "SERVER_ACKNOWLEDGED", "AUTHORITATIVE_EFFECT")},
            "fixture_manifest": {
                "slot": "B",
                "match_id": "match-x",
                "tick": 100,
                "connection": 424242,
                "skye": {"hero_id": sc.SKYE_HERO_ID, "eid": 1500, "team": 1,
                         "level": 6, "ranks": {"0": 1, "1": 1, "2": 1},
                         "ability_points": 1, "hp": 1200.0, "max_hp": 1200.0,
                         "energy": 560.0, "max_energy": 560.0,
                         "inventory": [], "default_items": [], "statuses": [],
                         "alive": True, "x": 0.0, "y": 38.0},
                "enemy": {"hero_id": 243, "eid": 1517, "team": 2,
                          "level": 6, "hp": 4000.0, "max_hp": 4000.0,
                          "energy": 200.0, "max_energy": 200.0,
                          "ability_points": 1,
                          "inventory": [], "default_items": [], "statuses": [],
                          "alive": True, "x": 4.0, "y": 38.0,
                          "ranks": {"0": 0, "1": 0, "2": 0}},
                "cooldowns": {"1": 0.0},
                "declared_fixture": {
                    "skye_level": 6,
                    "skye_ranks": {"0": 1, "1": 1, "2": 1},
                    "skye_points": 1,
                    "enemy_level": 6,
                    "skye_energy_policy": "full",
                    "skye_hp_policy": "full",
                    "enemy_hp_policy": "full"},
                "positions": {"skye": [0.0, 38.0], "enemy": [4.0, 38.0]},
                "placement_tolerance": 1.5,
                "profile_digest": "0" * 64,
            },
            "fixture_contract": contract,
            "provenance": {
                "source_startup_digest": "a" * 64,
                "source_current_digest": "a" * 64,
                "tape_loaded": {"records": 100, "sha256": "b" * 64},
                "tape_file_identity": {"file_sha256": "c" * 64},
                "env_config": {"HALCYON_NO_BOTS": "1"},
                "client_version": {"version_name": "4.13.4",
                                   "version_code": 147219},
                "qa_dir": "q",
                "diagnostics": {"pid": 4242, "startup_at": 1.0,
                                "match_id": "match-x", "phase": "world",
                                "match_finished": False, "tick": 100,
                                "time": 5.0},
                "diagnostics_end": {"pid": 4242, "startup_at": 1.0,
                                    "match_id": "match-x", "phase": "world",
                                    "match_finished": False, "tick": 140,
                                    "time": 7.0}},
            "observations": {
                # Synthetic but SELF-CONSISTENT causal evidence: one B cast by
                # this record's own actor (eid 1500) on this record's own
                # connection (424242), its native timer tag bound to that
                # actor, each receipt carrying the wire bytes it was matched
                # on inside the observed window [10.0, 12.0], and one
                # attributed hit whose exact total the outcome summary
                # repeats. This is a fixture for the schema witnesses only —
                # it is not measured evidence from any trial; the real
                # writer-produced record is the positive in
                # TestSkyeBCausalEvidence.
                "client_input": {"time": 10.0,
                                 "action": sc.SKYE_NATIVE_ACTIONS["B"],
                                 "connection": 424242,
                                 "payload": build_ground_cast_payload(
                                     sc.SKYE_NATIVE_ACTIONS["B"])},
                "acknowledgment": {
                    "time": 10.05,
                    "action": sc.SKYE_NATIVE_ACTIONS["B"],
                    "connection": 424242,
                    "payload": build_position_event(
                        1500, sc.SKYE_NATIVE_ACTIONS["B"])},
                "cooldown_tag": {
                    "slot": "B", "tag": f"{sc.SKYE_COOLDOWN_TAGS['B']:08x}",
                    "eid": 1500, "time": 10.06, "connection": 424242,
                    "payload": build_timer(1500, sc.SKYE_COOLDOWN_TAGS["B"])},
                "damage_classification": {
                    "window": [10.0, 12.0],
                    "attributed": [
                        {"time": 10.5, "delta": -30.0, "payload": payload,
                         "connection": 424242,
                         "reason": "COMBAT_DELTA_TAIL (non-basic source)"},
                    ]},
                "outcome": {"attributed_events": 1,
                            "outcome_total": -30.0},
            },
            "connection": 424242,
        }

    def _cli(self, a_path, b_path):
        import subprocess
        completed = subprocess.run(
            [sys.executable, "-B",
             str(ROOT / "Tools" / "run_scenarios.py"),
             "--mode", "compare-pair",
             "--result-a", str(a_path),
             "--result-b", str(b_path)],
            capture_output=True, text=True, timeout=120)
        try:
            report = json.loads(completed.stdout)
        except (json.JSONDecodeError, ValueError):
            report = {}
        return completed.returncode, report

    def _assert_structured_fail(self, code, report, expected_substrings):
        """A malformed record must exit nonzero with field-specific reasons
        and NO Python traceback."""
        self.assertNotEqual(code, 0,
                            f"malformed record must fail with nonzero exit, "
                            f"got report={report}")
        self.assertIsInstance(report.get("failures"), list)
        self.assertTrue(report["failures"],
                        "structured failures must list field-specific reasons")
        joined = " | ".join(report["failures"])
        for needle in expected_substrings:
            self.assertIn(needle, joined,
                          f"expected {needle!r} in failures, got: {joined}")
        # confirm no Python traceback string survived
        self.assertNotIn("Traceback", joined)
        self.assertNotIn("AttributeError", joined)
        self.assertNotIn("TypeError", joined)

    # -- witnesses ----------------------------------------------------------

    def test_witness_missing_inventory_both(self):
        """Both records drop skye.inventory; validator must surface a
        structured FAIL (a missing known-empty collection cannot equal a
        valid empty collection)."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        a["fixture_manifest"]["skye"].pop("inventory")
        b["fixture_manifest"]["skye"].pop("inventory")
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["manifest skye inventory is None — a missing known-empty "
                 "collection cannot equal a valid empty collection"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_missing_statuses_both(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        a["fixture_manifest"]["skye"].pop("statuses")
        b["fixture_manifest"]["skye"].pop("statuses")
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["manifest skye statuses is None — a missing known-empty "
                 "collection cannot equal a valid empty collection"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_missing_enemy_x_both(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        a["fixture_manifest"]["enemy"].pop("x")
        b["fixture_manifest"]["enemy"].pop("x")
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["manifest enemy x is None — a missing known-empty "
                 "collection cannot equal a valid empty collection"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_contract_declared_ranks_string(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        a["fixture_contract"]["skye"]["ranks"] = "invalid"
        b["fixture_contract"]["skye"]["ranks"] = "invalid"
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report, ["fixture_contract.skye.ranks 'invalid' "
                               "must be a dict"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_stage_null(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        b["stages"]["SETUP"] = None
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report, ["required stage SETUP"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_actor_list(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        # Replace skye with a list to break the actor-dict invariant.
        b["fixture_manifest"]["skye"] = [1, 2, 3]
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report, ["manifest.skye missing or malformed"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_observations_list(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        b["observations"] = [1, 2, 3]
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report, ["observations missing or not an object"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_contract_actor_list(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        b["fixture_contract"]["skye"] = [1]
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["fixture_contract.skye missing or malformed"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_contract_tolerance_string(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        b["fixture_contract"]["skye"]["position_tolerance"] = "invalid"
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["fixture_contract.skye.position_tolerance 'invalid' must "
                 "be finite and nonnegative"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_contract_exact_string(self):
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        b["fixture_contract"]["skye_hp_policy"] = "exact"
        b["fixture_contract"]["skye_hp_exact"] = "invalid"
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["skye_hp_policy is exact but skye_hp_exact='invalid' is not "
                 "a finite number"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_hit_delta_string(self):
        """Preserved structured FAIL: a non-finite damage delta is a
        structured FAIL, never a silently coerced default."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        b["observations"]["damage_classification"]["attributed"][0]["delta"] = "invalid"
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["attributed[0].delta 'invalid' must be a finite number"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_baseline_record_passes(self):
        """Sanity: the generated valid record itself produces a controlled
        pair through the public CLI."""
        a = self._base_record()
        b = self._base_record()
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self.assertEqual(code, 0,
                             f"generated valid record must PASS, "
                             f"got {report.get('failures')}")
            self.assertTrue(report.get("controlled_pair"))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    # -- 2026-09-11 schema-consistency parent-review witnesses -----------

    def test_witness_duplicate_level99_vs_measured6(self):
        """Both records set declared_fixture.skye_level=99 but
        contract.skye.level stays 6 — declaration copies must agree."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_manifest"]["declared_fixture"]["skye_level"] = 99
            r["fixture_contract"]["declared_fixture"]["skye_level"] = 99
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["declared_fixture.skye_level=99 disagrees with "
                 "contract.skye.level=6"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_required_skye_hp_inapplicable(self):
        """Marking a required resource policy inapplicable must FAIL —
        the contract is the canonical source and only full/exact are
        legal for actors with that resource pool."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["skye_hp_policy"] = "inapplicable"
            r["fixture_contract"]["declared_fixture"][
                "skye_hp_policy"] = "inapplicable"
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["skye_hp_policy 'inapplicable' is not full/exact"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_missing_enemy_inventory_flag(self):
        """Removing enemy.inventory on both records: a missing
        known-empty collection cannot equal a valid empty collection."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        a["fixture_manifest"]["enemy"].pop("inventory")
        b["fixture_manifest"]["enemy"].pop("inventory")
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["manifest enemy inventory is None — a missing known-empty "
                 "collection cannot equal a valid empty collection"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_same_team(self):
        """Skye and enemy must be on opposing teams — controlled-fixture
        identity."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_manifest"]["enemy"]["team"] = 1
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["skye and enemy share team"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_boolean_actor_alive(self):
        """alive must be a boolean (True/False), never a string."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_manifest"]["skye"]["alive"] = "unknown"
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["manifest skye alive='unknown' must be a boolean"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_scenario_array(self):
        """scenario must be a string before any dict lookup."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["scenario"] = []
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report, ["result.scenario [] is not a string"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_presentation_array(self):
        """observations.presentation must be a dict if present; a list is
        a structured FAIL."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["observations"]["presentation"] = []
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["observations.presentation is list, not an object"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_tape_identity_array(self):
        """Optional provenance.tape_file_identity must be a dict; a list
        is a structured FAIL."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["provenance"]["tape_file_identity"] = [1]
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["provenance.tape_file_identity is list, not an object"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_missing_declared_positions(self):
        """Both records drop contract.skye.position and
        contract.enemy.position — declared placement is REQUIRED."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["skye"].pop("position")
            r["fixture_contract"]["enemy"].pop("position")
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["fixture_contract.skye.position missing — declared "
                 "placement is required"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    # -- 2026-09-11 schema-invariant parent-review witnesses ------------

    def test_witness_both_actors_dead(self):
        """Each actor must independently be alive — both alive=False is
        a structured FAIL (a controlled fixture requires both alive)."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_manifest"]["skye"]["alive"] = False
            r["fixture_manifest"]["enemy"]["alive"] = False
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["skye is not alive at validation time (alive=False)",
                 "enemy is not alive at validation time (alive=False)"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_flat_hp_exact_overrides_declared_full(self):
        """Flattened contract.skye_hp_policy='exact' with exact=400.0
        must FAIL when the declared_fixture says 'full' — the resource
        check actually reads the flattened key."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["skye_hp_policy"] = "exact"
            r["fixture_contract"]["skye_hp_exact"] = 400.0
            r["fixture_manifest"]["skye"]["hp"] = 400.0
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["declared_fixture.skye_hp_policy='full' disagrees with "
                 "contract.skye_hp_policy='exact'"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_declared_eid_mismatch(self):
        """contract.skye.eid=9999 must FAIL when measured skye.eid=1500."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["skye"]["eid"] = 9999
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["contract skye eid 9999 != measured skye eid 1500"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_declared_team_mismatch(self):
        """contract.enemy.team=99 must FAIL when measured enemy.team=2."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["enemy"]["team"] = 99
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["contract enemy team 99 != measured enemy team 2"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_contract_slot_mismatch(self):
        """contract.slot='A' must FAIL when manifest.scenario='skye-b'
        (which expects slot='B')."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["slot"] = "A"
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["contract.slot 'A' != manifest.slot 'B'"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_zero_tolerance_missed_placement(self):
        """nested tolerance=0.0 with measured Skye displaced 0.5u must
        FAIL — a legitimate zero tolerance is an exact placement check,
        not a silent fallback to the default."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            for actor in ("skye", "enemy"):
                r["fixture_contract"][actor]["position_tolerance"] = 0.0
            r["fixture_manifest"]["skye"]["x"] += 0.5
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["skye actual position (0.5, 38.0) is 0.50u from the "
                 "declared position (0.0, 38.0) (tolerance 0.0u)"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_preinput_exact_string_returns_structured_fail(self):
        """Direct validate_fixture() on a contract with a non-finite
        exact value returns STRUCTURED_FAIL, never a Python exception."""
        r = self._base_record()
        r["fixture_contract"]["skye_hp_policy"] = "exact"
        r["fixture_contract"]["skye_hp_exact"] = "invalid"
        r["fixture_contract"]["declared_fixture"]["skye_hp_policy"] = "exact"
        r["fixture_contract"]["declared_fixture"]["skye_hp_exact"] = "invalid"
        # both entry points must return labeled structured failure
        failures = sc.validate_fixture(
            r["fixture_manifest"], r["fixture_contract"])
        self.assertTrue(failures,
                        "direct validate_fixture must surface structured "
                        "failures, never a Python exception")
        joined = " | ".join(failures)
        self.assertIn("skye_hp_exact", joined,
                      "the validator must name the malformed exact field")

    def test_preinput_bad_position_returns_structured_fail(self):
        """Direct validate_fixture() on a contract with a non-finite
        declared position returns STRUCTURED_FAIL, never a Python
        exception (math.dist must not be reached with a string)."""
        r = self._base_record()
        r["fixture_contract"]["skye"]["position"] = ["invalid", 38]
        failures = sc.validate_fixture(
            r["fixture_manifest"], r["fixture_contract"])
        self.assertTrue(failures,
                        "direct validate_fixture must surface structured "
                        "failures, never a Python exception")
        joined = " | ".join(failures)
        self.assertIn("position", joined.lower(),
                      "the validator must name the malformed position "
                      "field")

    # -- 2026-09-11 schema-required witnesses (required declaration
    #    presence + declared-vs-measured hero identity) -------------------

    def test_witness_missing_declared_enemy_team(self):
        """contract.enemy.team missing on both records: required identity
        declarations cannot silently become optional."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["enemy"].pop("team")
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["contract enemy team missing — required identity "
                 "declaration"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_declared_skye_hero_id_mismatch(self):
        """contract.skye.hero_id=999 versus measured 265 must FAIL — the
        declared hero identity must match the measured snapshot row."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["skye"]["hero_id"] = 999
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["contract skye hero_id 999 != measured skye hero_id"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_required_identity_declarations_missing(self):
        """Analogous required-presence cases: contract.skye.hero_id /
        skye.eid / skye.team / enemy.team each missing is a structured
        FAIL through the pre-input entry point."""
        for field, actor in (("hero_id", "skye"), ("eid", "skye"),
                             ("team", "skye"), ("team", "enemy")):
            r = self._base_record()
            del r["fixture_contract"][actor][field]
            failures = sc.validate_fixture(
                r["fixture_manifest"], r["fixture_contract"])
            joined = " | ".join(failures)
            self.assertTrue(
                any(f"contract {actor} {field} missing" in f
                    for f in failures),
                f"missing contract {actor}.{field} must be a required-"
                f"declaration failure, got: {joined}")

    def test_declared_enemy_hero_id_mismatch_when_declared(self):
        """When the contract explicitly declares enemy.hero_id, it must
        match the measured enemy hero_id (analogous mismatch case)."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["enemy"]["hero_id"] = 999
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["contract enemy hero_id 999 != measured enemy hero_id"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_declared_skye_eid_string_is_structured_fail(self):
        """contract.skye.eid='1500' (string) must FAIL through the CLI —
        a malformed declaration must not disable the equality check."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_contract"]["skye"]["eid"] = "1500"
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["contract skye eid '1500' must be a finite integer when "
                 "present"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_missing_measured_skye_points_fails(self):
        """Deleting the measured Skye ability_points key must FAIL when
        the contract declares skye_points — preparation must produce the
        measured state; optional bypass is gone."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            r["fixture_manifest"]["skye"].pop("ability_points")
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["manifest skye ability_points is None"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    # -- 2026-09-11 enemy-ranks declaration enforcement ------------------

    def _apply_enemy_ranks(self, r, nested_ranks, declared_ranks):
        r["fixture_contract"]["enemy"]["ranks"] = copy.deepcopy(nested_ranks)
        r["fixture_contract"]["declared_fixture"]["enemy_ranks"] = \
            copy.deepcopy(declared_ranks)
        r["fixture_manifest"]["declared_fixture"]["enemy_ranks"] = \
            copy.deepcopy(declared_ranks)

    def test_witness_declared_enemy_ranks_match_passes(self):
        """A declared enemy rank expectation that matches the measured
        row passes (the declaration is enforced, not relabeled)."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            measured = r["fixture_manifest"]["enemy"]["ranks"]
            self._apply_enemy_ranks(r, measured, measured)
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self.assertEqual(code, 0,
                             f"matching declared enemy ranks must PASS, "
                             f"got {report.get('failures')}")
            self.assertTrue(report.get("controlled_pair"))
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_declared_enemy_ranks_mismatch_fails(self):
        """Declaring enemy rank 1 while the measured row carries 0 must
        FAIL through the CLI (declared-vs-measured rank equality)."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            measured = r["fixture_manifest"]["enemy"]["ranks"]
            declared = copy.deepcopy(measured)
            declared["0"] = 1
            self._apply_enemy_ranks(r, declared, declared)
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["enemy rank 0 0 != declared 1"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_witness_enemy_rank_declaration_copies_disagree_fails(self):
        """Nested contract enemy ranks agreeing with the measured row
        while both declared_fixture copies say otherwise must FAIL
        (canonical declaration-copy agreement covers enemy_ranks)."""
        a = json.loads(json.dumps(self._base_record()))
        b = json.loads(json.dumps(self._base_record()))
        for r in (a, b):
            measured = r["fixture_manifest"]["enemy"]["ranks"]
            declared = copy.deepcopy(measured)
            declared["0"] = 1
            self._apply_enemy_ranks(r, measured, declared)
        base = Path(tempfile.mkdtemp(prefix="halcyon-witness-"))
        try:
            pa = base / "a.json"; pb = base / "b.json"
            pa.write_text(json.dumps(a), encoding="utf-8")
            pb.write_text(json.dumps(b), encoding="utf-8")
            code, report = self._cli(pa, pb)
            self._assert_structured_fail(
                code, report,
                ["declared_fixture.enemy_ranks="])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_enemy_ranks_missing_and_extra_slots_fail(self):
        """Analogous rank-map shape cases for the enemy: a declared slot
        absent from the measured row, and a measured slot absent from
        the declaration, each fail."""
        # missing slot: declared has '2' at rank 1, measured has 0 there
        r = self._base_record()
        measured = r["fixture_manifest"]["enemy"]["ranks"]
        declared = copy.deepcopy(measured)
        declared["2"] = 1
        self._apply_enemy_ranks(r, declared, declared)
        failures = sc.validate_fixture(
            r["fixture_manifest"], r["fixture_contract"])
        self.assertTrue(any("enemy rank 2 0 != declared 1" in f
                            for f in failures), failures)
        # extra slot: measured carries a slot the declaration omits
        r = self._base_record()
        measured = r["fixture_manifest"]["enemy"]["ranks"]
        declared = {k: v for k, v in measured.items() if k != "1"}
        self._apply_enemy_ranks(r, declared, declared)
        failures = sc.validate_fixture(
            r["fixture_manifest"], r["fixture_contract"])
        self.assertTrue(any("enemy ranks carry undeclared slots ['1']" in f
                            for f in failures), failures)

    def test_enemy_malformed_rank_value_fails(self):
        """A malformed declared enemy rank value (string) is a structured
        failure, never a silent skip."""
        r = self._base_record()
        measured = r["fixture_manifest"]["enemy"]["ranks"]
        declared = copy.deepcopy(measured)
        declared["0"] = "invalid"
        self._apply_enemy_ranks(r, declared, declared)
        failures = sc.validate_fixture(
            r["fixture_manifest"], r["fixture_contract"])
        self.assertTrue(any("enemy ranks" in f and "invalid" in f
                            for f in failures), failures)


# ---------------------------------------------------------------------------
# Real-QA integration: production world + real SandboxQA.pump
# ---------------------------------------------------------------------------

REAL_QA_MATCH_ID = "scenario-integration"

# EXPLICITLY SYNTHETIC test tape: two frames in the production record grammar
# (server/world_tape.py RECORD_HEAD = ">IH"). Test input only — never a corpus
# payload, never a live-client acceptance claim. The fixture loads it through
# the PRODUCTION loader so `tape_loaded` (loaded frames) and
# `tape_file_identity` (on-disk file) are both real receipts.
SYNTHETIC_TAPE_FRAMES = (
    (0, 1087, struct.pack(">II", 1500, 0)),
    (500, 1086, struct.pack(">II", 1500, 1500)),
)

# Environment keys the fixture OWNS for a trial's WHOLE lifetime. The
# production world reads them at construction (HALCYON_QA_DIR, HALCYON_BOTS),
# at tape load (HALCYON_NO_TAPE) and inside every diagnostics receipt
# (HALCYON_NO_TAPE, HALCYON_TRACE_WIRE). An override scoped to the constructor
# alone would let a supported operator setting silently produce a different
# fixture than the one the receipts declare — with HALCYON_NO_TAPE=1 in the
# caller environment the production loader skips the declared tape entirely
# (0 loaded frames, loaded identity UNKNOWN). HALCYON_NO_WAVE is deliberately
# NOT scoped: this fixture never arms a wave director (it never enters the
# world through _enter_world), so that switch cannot change it.
SCOPED_ENV_KEYS = ("HALCYON_QA_DIR", "HALCYON_NO_TAPE", "HALCYON_BOTS",
                   "HALCYON_TRACE_WIRE")


def write_synthetic_tape(path: Path):
    frames = [(at, struct.pack(">H", opcode) + payload)
              for at, opcode, payload in SYNTHETIC_TAPE_FRAMES]
    path.write_bytes(b"".join(struct.pack(">IH", at, len(body)) + body
                              for at, body in frames))
    return frames


def synthetic_tape_digest() -> str:
    """The digest the production receipt must compute over the LOADED frames
    (server/sandbox_qa.py: re-serialize each frame, digest the bytes)."""
    digest = hashlib.sha256()
    for at, opcode, payload in SYNTHETIC_TAPE_FRAMES:
        body = struct.pack(">H", opcode) + payload
        digest.update(struct.pack(">IH", at, len(body)))
        digest.update(body)
    return digest.hexdigest()


class SubprocessTripwire:
    """Offline guard around integration execution.

    Production ADB runs through ``Tools.scenario_client.subprocess``; if the
    fake-adapter patch is ever lost, that call would spawn ``adb`` against
    whatever device happens to be attached. Every spawning entry point is
    replaced by a RECORDED REFUSAL — the attempted command is preserved for
    the report and is never executed — while constants and exception types
    still resolve to the real module, so the driver keeps importing normally.
    """

    def __init__(self) -> None:
        self.attempts: list[dict] = []

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def _refuse(self, name: str, args: tuple, kwargs: dict):
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, (list, tuple)):
            argv = [str(item) for item in argv]
        self.attempts.append({"entry_point": name, "argv": argv})
        raise AssertionError(
            f"offline tripwire: subprocess.{name}({argv!r}) refused — the "
            "integration fixture must never spawn a process, because a real "
            "adb would touch the attached device")

    def run(self, *args, **kwargs):
        self._refuse("run", args, kwargs)

    def Popen(self, *args, **kwargs):
        self._refuse("Popen", args, kwargs)

    def call(self, *args, **kwargs):
        self._refuse("call", args, kwargs)

    def check_call(self, *args, **kwargs):
        self._refuse("check_call", args, kwargs)

    def check_output(self, *args, **kwargs):
        self._refuse("check_output", args, kwargs)

    def getoutput(self, *args, **kwargs):
        self._refuse("getoutput", args, kwargs)

    def getstatusoutput(self, *args, **kwargs):
        self._refuse("getstatusoutput", args, kwargs)


class RealQaStack:
    """One trial's REAL production QA stack.

    The world is the production ``SnapshotStream`` built with the same
    fixture shape as ``server.test.test_sandbox_simulation.session()``
    (synthetic navmesh, dormant jungle, no live structures), but with Skye as
    the local hero. The QA authority is the REAL ``SandboxQA`` mailbox the
    production server creates from ``HALCYON_QA_DIR``, and the world's own
    fixed ticks are pumped on a thread, so ``state.json``, snapshots, learn/
    teleport/resources preparation and BOTH diagnostics receipts are produced
    by production code. Only the client-side ADB/rendering/wire observations
    stay mocked (``Harness``), exactly as the offline suites do.

    The fixture OWNS its environment and tape path from construction through
    the last diagnostics read, and restores both on ``close()``: the scoped
    inputs are the ones the receipts describe, and the caller's process state
    is left exactly as it was found.
    """

    def __init__(self, base: Path, trial: int) -> None:
        self.qa_dir = base / f"real-qa-{trial}"
        self.qa_dir.mkdir(parents=True, exist_ok=True)
        self.tape_path = base / f"synthetic-tape-{trial}.bin"
        self.loaded_frames = write_synthetic_tape(self.tape_path)
        self.restart_after: str | None = None
        self.restarts = 0
        self.frames: list[tuple[int, bytes]] = []
        self.lock_waits: list[dict] = []
        self.adb_tripwire: SubprocessTripwire | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False
        # caller state, saved for exact restoration
        self.caller_env = {key: os.environ.get(key) for key in SCOPED_ENV_KEYS}
        self.caller_tape_path = match_server.WORLD_TAPE_PATH
        self._open_scope()
        try:
            self._build()
        except BaseException:
            self.close()                    # never leak the scoped state
            raise

    # -- fixture scope -------------------------------------------------------

    def _open_scope(self) -> None:
        for key in SCOPED_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["HALCYON_QA_DIR"] = str(self.qa_dir)
        # the production path IS the declared synthetic tape for this trial:
        # both tape receipts must describe the fixture's own inputs, never an
        # operator corpus file that happens to sit at the production path
        match_server.WORLD_TAPE_PATH = str(self.tape_path)

    def close(self) -> None:
        """Stop the tick thread and restore the caller's environment and tape
        path exactly. Idempotent, and safe to call after a failed build."""
        if self._closed:
            return
        self._closed = True
        self.stop()
        for key, value in self.caller_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        match_server.WORLD_TAPE_PATH = self.caller_tape_path

    def __enter__(self) -> RealQaStack:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _build(self) -> None:
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                       [(0, 1, 2), (0, 2, 3)])
        players = roster.default_solo_bots("scenario-integration",
                                           REAL_QA_MATCH_ID)
        players[0].hero_id = sc.SKYE_HERO_ID          # eid 1500, team 1
        players = [players[0], players[3]]            # eid 1517, team 2
        players[1].hero_id = 243
        self.world = match_server.SnapshotStream(
            None, players, REAL_QA_MATCH_ID,
            lambda opcode, payload: self.frames.append((opcode, payload)),
            log=lambda _message: None, navigation_mesh=mesh)
        # production loader, inside the scope: the declared tape is loaded
        # whatever the caller's HALCYON_NO_TAPE said
        self.world._load_tape()
        assert len(self.world.tape_frames or []) == len(SYNTHETIC_TAPE_FRAMES), (
            f"the declared fixture tape did not load: "
            f"{len(self.world.tape_frames or [])} frames")
        self.world._finalize()
        self.world.hero_sims[1500].teleport(*sc.DEFAULT_PROFILE["skye_position"])
        self.world.hero_sims[1517].teleport(
            *sc.DEFAULT_PROFILE["enemy_position"])
        self.world.jungle = jungle.JungleManager(open_time=1000000)
        for building in self.world.structures.structures.values():
            building.is_alive = False
        self.world.phase = self.world.WORLD
        self.qa = self.world.qa                        # REAL SandboxQA
        if self.qa is None:                            # pragma: no cover
            raise AssertionError("production QA authority was not created")

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self.qa.pump(self.world)      # publish the first real state.json
        self._thread = threading.Thread(target=self._pump_forever,
                                        name=f"halcyon-real-qa-{id(self)}",
                                        daemon=True)
        self._thread.start()

    def _pump_forever(self) -> None:
        while not self._stop.is_set():
            if self.restart_after is not None and not self.restarts \
                    and self._journal_completed(self.restart_after):
                self.restart_authority()
            # Same order as the production world loop: drain queued c2s
            # frames, then run one fixed tick.
            self.world._pump(0)
            self.world.advance_simulation()
            time.sleep(0.02)

    # -- production intent feed ---------------------------------------------
    #
    # A UI gesture is a CLIENT intent. The production server receives it as a
    # c2s frame on its inbound queue (``SnapshotStream.submit`` -> ``_pump``
    # -> ``_apply_event``), applied in the world thread under the same state
    # lock as the fixed ticks. Feeding the same intent through the same queue
    # is what makes SERVER_ACKNOWLEDGED and the accepted-operation checks read
    # REAL authoritative state (payment, cooldown, damage) instead of a
    # canned receipt; only the client-side observation layer stays mocked.

    def submit_client(self, opcode: int, payload: bytes) -> None:
        self.world.submit(opcode, payload)     # conn=None -> players[0] (Skye)

    def order_basic_attack(self, target_eid: int) -> None:
        self.submit_client(wire.OP.TARGET_ENTITY,
                           roster.build_target_entity(target_eid))

    def wait_for_lock(self, target_eid: int, *, timeout: float = 6.0) -> dict:
        """Block until the real basic attack LANDED its 1086 lock.

        Production creates Skye's lock on the attack's impact
        (``SkyeKit.on_basic_attack``), and the dependent B cast is lock-gated
        (``can_cast`` -> ``_valid_lock``): a tap and its cast in the same tick
        would be refused. A live client waits for the HUD lock indicator
        before swiping; this wait is the same gate, read from authoritative
        state instead of the rendered HUD.
        """
        started = time.monotonic()
        deadline = started + timeout
        kit = self.world.hero_kits.get(SKYE_EID)
        locked = False
        while time.monotonic() < deadline:
            target = getattr(kit, "locked_target", None)
            if target is not None and target.eid == target_eid:
                locked = True
                break
            time.sleep(0.01)
        record = {"target": target_eid, "locked": locked,
                  "waited_s": round(time.monotonic() - started, 3),
                  "sim_time": round(self.world.sim_time, 3)}
        self.lock_waits.append(record)
        return record

    def commit_ground_cast(self, action: int) -> None:
        """The released cast gesture: 1042 with the production payload grammar
        (``roster.parse_ground_cast``: f32 x, height, y, u8 slot, u8 flags)."""
        enemy = self.world.hero_sims[ENEMY_EID]
        self.submit_client(wire.OP.GROUND_CAST,
                           struct.pack(">fffBB", enemy.x, 0.0, enemy.y, action, 0))

    def real_effects(self) -> dict:
        """What the PRODUCTION world actually emitted (evidence, not a receipt).

        Parsed with the driver's own wire readers, so a real frame and a
        recorded one are read the same way.
        """
        damage, locks, opcodes = [], [], set()
        for opcode, payload in list(self.frames):
            opcodes.add(opcode)
            record = {"opcode": opcode, "payload": payload.hex()}
            hit = sc.damage_identity(record)
            if hit is not None:
                damage.append({"victim": hit[0], "attacker": hit[1],
                               "delta": round(hit[2], 4)})
                continue
            lock = sc.lock_identity(record)
            if lock is not None:
                locks.append({"target": lock[0], "source": lock[1],
                              "kind": lock[2]})
        return {"damage": damage, "locks": locks, "opcodes": sorted(opcodes),
                "tick": self.world.sim_tick}

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # -- mid-trial authority restart (the bounded failure) -------------------

    def _journal_completed(self, name: str) -> bool:
        path = self.qa_dir / "journal.jsonl"
        if not path.is_file():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            # the ACCEPTED entry carries the request; "completed" carries its
            # result and is not yet published when the marker is reserved
            if entry.get("event") == "accepted" \
                    and (entry.get("command") or {}).get("command") == name:
                return True
        return False

    def restart_authority(self) -> None:
        """A REAL same-directory restart of the QA authority: the production
        constructor mints a fresh startup identity (startup_at), while the
        world keeps the same match and the same pid."""
        self.qa = server_qa.SandboxQA(self.qa_dir)
        self.world.qa = self.qa
        self.restarts += 1


def raw_receipt(record: dict, label: str) -> dict:
    """The raw result of the QA receipt the driver recorded under that label.

    The driver's typed ``provenance.diagnostics`` linkage carries the identity
    fields; the full production reply (tape identities, effective environment)
    stays verbatim in ``qa_receipts``.
    """
    for entry in record["qa_receipts"]:
        if entry.get("label") == label:
            return entry["result"]["result"]
    raise AssertionError(f"no {label!r} receipt recorded")


def real_qa_profile(base: Path) -> Path:
    """The declared fixture of the REAL prepared state.

    Measured from the production world after the same legal preparation the
    driver performs (learn slot B -> rank 1, then full hp/energy through the
    production resources clamp): Skye level 1 / ranks {B: 1} / 0 leftover
    points, enemy hero (243) level 1 with its starting point. Level, ranks and
    points are declared EXACTLY because the contract demands equality.
    """
    profile = json.loads(json.dumps({
        **sc.DEFAULT_PROFILE,
        "camera_settle_s": 0,
        "declared_fixture": {
            **sc.DEFAULT_PROFILE["declared_fixture"],
            "skye_level": 1,
            "skye_ranks": {"0": 0, "1": 1, "2": 0},
            "skye_points": 0,
            "enemy_points": 1,
            "enemy_level": 1,
            "skye_energy_policy": "full",
            "skye_hp_policy": "full",
            "enemy_hp_policy": "full",
        }}))
    path = base / "profile-real-qa.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


class RealWireAdb(FakeAdb):
    """``FakeAdb`` plus the PRODUCTION intent feed.

    The client observation layer is unchanged (mocked ADB, mocked rendering,
    the same scripted wire records the offline suites assert on). Each gesture
    the driver issues is ALSO submitted to the real world as the c2s frame a
    live client would send, so the authoritative snapshot keeps a real
    payment/cooldown/damage behind the same UI action. No stage is faked: the
    mocked records stand for the client's own observations, the production
    frames stand for what the server really computed.
    """

    def __init__(self, harness, stack: RealQaStack, action: int) -> None:
        super().__init__(harness)
        self.stack = stack
        self.action = action
        self._require_tripwire()

    @staticmethod
    def _require_tripwire() -> None:
        """Fail loud if the offline guard is not armed where an ADB step runs:
        losing it would let a regression spawn ``adb`` for real."""
        if not isinstance(sc.subprocess, SubprocessTripwire):
            raise AssertionError(
                "the offline subprocess tripwire is not armed during "
                "integration execution: a real ADB call could reach a device")

    def wm_size(self):
        self._require_tripwire()
        return super().wm_size()

    def tap(self, x, y):
        # A UI tap on the enemy body is the 1060 target order; the basic
        # attack it orders must LAND before the lock-gated cast can follow.
        self._require_tripwire()
        self.stack.order_basic_attack(ENEMY_EID)
        self.stack.wait_for_lock(ENEMY_EID)
        super().tap(x, y)

    def swipe(self, x1, y1, x2, y2, *, duration_ms=250):
        # The released cast gesture is the 1042 ground order at the aim.
        self._require_tripwire()
        self.stack.commit_ground_cast(self.action)
        super().swipe(x1, y1, x2, y2, duration_ms=duration_ms)


def run_real_trial(base: Path, trial: int, *, restart_after: str | None = None):
    """One full writer trial through the REAL QA integration path.

    Returns ``(result, stack, harness)``. The fixture's environment/tape-path
    scope is closed (and the caller's state restored) before returning, on
    every path.
    """
    harness = Harness("skye-b")               # mocked ADB/rendering/wire only
    profile_path = real_qa_profile(base)
    out_dir = base / f"real-trial-{trial}"
    tripwire = SubprocessTripwire()
    with RealQaStack(base, trial) as stack:
        if restart_after is not None:
            stack.restart_after = restart_after
        stack.adb_tripwire = tripwire
        stack.start()
        try:
            # The QA side stays REAL (QaSession + Tools.sandbox_qa.submit +
            # SandboxQA mailbox). ADB MUST be the fake, and the subprocess
            # tripwire refuses (and records) any process spawn, so a
            # regression in the adapter patch cannot reach a device. Both
            # patches are armed BEFORE the adapter exists.
            with mock.patch.object(sc, "Adb", lambda serial: adapter), \
                    mock.patch.object(sc, "subprocess", tripwire):
                adapter = RealWireAdb(harness, stack, sc.SKYE_NATIVE_ACTIONS["B"])
                result = sc.run_client("skye-b", types.SimpleNamespace(
                    adb_serial="emulator-5554", qa_dir=str(stack.qa_dir),
                    wire_trace=str(harness.trace_path), timeout=2.0,
                    output=str(out_dir), connection=424242,
                    client_profile=str(profile_path), reference=None))
            assert adapter.calls, "the fake ADB adapter must have been used"
            assert not tripwire.attempts, (
                "integration execution attempted a subprocess: "
                f"{tripwire.attempts}")
        finally:
            # keep the mocked client/wire observation the driver classified
            # alongside the writer's own artifacts
            if out_dir.is_dir() and harness.trace_path.is_file():
                shutil.copyfile(harness.trace_path,
                                out_dir / "wire-trace-mocked.jsonl")
            harness.cleanup()
    return result, stack, harness


def produce_real_pair(base: Path):
    """Two unpatched writer trials through the real QA integration path.

    Returns the serialized records (the bytes the public CLI consumes), what
    the production world really emitted during each trial, and each trial's
    subprocess-tripwire attempts.
    """
    records, effects, attempts = [], [], []
    for trial in (1, 2):
        result, stack, _harness = run_real_trial(base, trial)
        assert result["status"] == "PASS", result.get("failure_detail")
        records.append(json.loads(
            Path(result["result_path"]).read_text(encoding="utf-8")))
        effects.append(stack.real_effects())
        attempts.append(list(stack.adb_tripwire.attempts))
    return records[0], records[1], effects, attempts


class TestRealQaIntegration(unittest.TestCase):
    """Checkpoint 5: the production QA path, end to end.

    Diagnostics, snapshots, learn/teleport/resource preparation and the
    endpoint read all travel through the REAL ``SandboxQA`` mailbox (the same
    ``Tools.sandbox_qa.submit`` the live stack uses) against a real
    production ``SnapshotStream`` world advanced by its own fixed ticks. The
    two serialized records must pass the PUBLIC compare-pair CLI, and a real
    same-match authority restart mid-trial must surface as a TRIAL_CONTINUITY
    evidence failure with the earlier observed stages intact.

    The whole class fixture is produced with ``HALCYON_NO_TAPE=1`` SET in the
    caller environment: the supported production tape-skip switch must not be
    able to change the declared fixture, and the fixture must hand the caller
    environment and the production tape path back untouched.
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-real-qa-"))
        cls.caller_env = dict(os.environ)
        cls.caller_tape_path = match_server.WORLD_TAPE_PATH
        with mock.patch.dict(os.environ, {"HALCYON_NO_TAPE": "1"}):
            expected_env = dict(os.environ)
            cls.va, cls.vb, cls.effects, cls.tripwires = \
                produce_real_pair(cls.base)
            # asserted INSIDE the patch scope on purpose: mock's own
            # restoration must not be allowed to mask a fixture leak
            cls.env_delta = {key: (expected_env.get(key), os.environ.get(key))
                             for key in set(expected_env) | set(os.environ)
                             if expected_env.get(key) != os.environ.get(key)}
            cls.tape_path_after_pair = match_server.WORLD_TAPE_PATH

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def _cli(self, name, va, vb):
        pa = self.base / f"{name}-a.json"
        pb = self.base / f"{name}-b.json"
        pa.write_text(json.dumps(va), encoding="utf-8")
        pb.write_text(json.dumps(vb), encoding="utf-8")
        return run_compare_cli(pa, pb)

    def test_real_qa_pair_passes_the_public_cli(self):
        code, report, stderr = self._cli("real-qa-pass", self.va, self.vb)
        self.assertEqual(code, 0, report.get("failures") or stderr)
        self.assertTrue(report["controlled_pair"], report.get("failures"))

    def test_pair_restores_the_caller_environment_and_tape_path(self):
        self.assertEqual(self.env_delta, {},
                         f"the fixture changed the caller environment: "
                         f"{self.env_delta}")
        self.assertEqual(self.tape_path_after_pair, self.caller_tape_path)
        self.assertEqual(self.caller_env, dict(os.environ),
                         "producing the pair changed the caller environment")

    def test_no_subprocess_or_device_attempts_during_pair_production(self):
        """The adapter patch must be the only ADB path: the tripwire refuses
        (and records) every process spawn, so an empty record is the proof."""
        self.assertEqual(self.tripwires, [[], []], self.tripwires)

    def test_tripwire_refuses_an_unpatched_adapter_command(self):
        """The guard itself, offline: with the adapter patch lost — the exact
        regression this guards — the real spawn path is recorded and refused
        before any process exists, so no device can be touched."""
        tripwire = SubprocessTripwire()
        with mock.patch.object(sc, "subprocess", tripwire):
            with self.assertRaises(AssertionError) as caught:
                sc.Adb("emulator-5554")._run(
                    "shell", "input", "tap", "348", "218")
        self.assertIn("offline tripwire", str(caught.exception))
        self.assertEqual(tripwire.attempts, [{
            "entry_point": "run",
            "argv": ["adb", "-s", "emulator-5554", "shell", "input", "tap",
                     "348", "218"]}])

    def test_fixture_is_self_contained_under_no_tape(self):
        """The independently reproduced defect, now covered end to end.

        With ``HALCYON_NO_TAPE=1`` in the caller environment the old fixture
        restored the switch before ``_load_tape`` and loaded ZERO frames. The
        fixture now owns the environment and the tape path for the whole
        trial, so the receipts produced INSIDE the trial describe the declared
        synthetic tape, and the caller's process state comes back untouched.
        """
        base = Path(tempfile.mkdtemp(prefix="halcyon-real-qa-notape-"))
        try:
            with mock.patch.dict(os.environ, {"HALCYON_NO_TAPE": "1"}):
                before_env = dict(os.environ)
                self.assertEqual(before_env["HALCYON_NO_TAPE"], "1")
                before_tape = match_server.WORLD_TAPE_PATH
                result, stack, _harness = run_real_trial(base, 1)
                self.assertEqual(result["status"], "PASS",
                                 result.get("failure_detail"))
                record = json.loads(Path(result["result_path"]).read_text(
                    encoding="utf-8"))
                self.assertEqual(record["provenance"]["tape_loaded"],
                                 {"records": len(SYNTHETIC_TAPE_FRAMES),
                                  "sha256": synthetic_tape_digest()})
                identity = record["provenance"]["tape_file_identity"]
                tape_file = base / "synthetic-tape-1.bin"
                self.assertEqual(identity["path"], str(tape_file))
                self.assertEqual(
                    identity["file_sha256"],
                    hashlib.sha256(tape_file.read_bytes()).hexdigest())
                # the scope was ACTIVE at the in-trial diagnostics read, not
                # just at construction
                self.assertIsNone(
                    raw_receipt(record, "provenance-diagnostics")["env"]
                    ["HALCYON_NO_TAPE"],
                    "the fixture scope must be in force when the receipts "
                    "are read")
                self.assertEqual(stack.adb_tripwire.attempts, [])
                self.assertEqual(stack.restarts, 0)
                # the caller's process state survives the whole trial
                self.assertEqual(os.environ, before_env,
                                 "the fixture leaked environment state")
                self.assertEqual(match_server.WORLD_TAPE_PATH, before_tape)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_records_carry_real_pump_derived_receipts(self):
        for label, record in (("A", self.va), ("B", self.vb)):
            self.assertEqual(record["schema_version"], sc.PAIR_SCHEMA_VERSION)
            self.assertEqual(record["status"], "PASS")
            self.assertEqual(record["stages"]["TRIAL_CONTINUITY"]["status"],
                             "PASS")
            initial = record["provenance"]["diagnostics"]
            end = record["provenance"]["diagnostics_end"]
            # REAL process/linkage identity: this interpreter, this fixture
            # match, an active WORLD at both endpoints
            self.assertEqual(initial["pid"], os.getpid())
            self.assertEqual(end["pid"], os.getpid())
            self.assertEqual(initial["match_id"], REAL_QA_MATCH_ID)
            self.assertEqual(end["match_id"], REAL_QA_MATCH_ID)
            self.assertEqual(initial["phase"], "world")
            self.assertEqual(end["phase"], "world")
            self.assertIs(initial["match_finished"], False)
            self.assertIs(end["match_finished"], False)
            self.assertIsInstance(initial["startup_at"], float)
            # the receipts describe the FIXTURE's scoped inputs: the pair is
            # produced with HALCYON_NO_TAPE=1 in the caller environment (see
            # the class docstring), so the declared tape must have loaded
            for receipt_label in ("provenance-diagnostics",
                                  "endpoint-diagnostics"):
                self.assertIsNone(
                    raw_receipt(record, receipt_label)["env"]["HALCYON_NO_TAPE"],
                    f"{receipt_label} receipt env")
            # the production world genuinely advanced between the two reads
            self.assertGreater(end["tick"], initial["tick"])
            self.assertGreater(end["time"], initial["time"])
            self.assertEqual(end["tick"] * match_server.SIM_TICK, end["time"])
            # REAL source + tape receipts. Both identities describe THIS
            # fixture's declared inputs: the loaded-frame receipt digests the
            # frames the production loader actually loaded from the declared
            # synthetic tape, and the file receipt is a live read of that same
            # declared file at the production path (which the fixture owns for
            # the whole trial). They are different concepts and are NOT
            # required to differ — here they coincide because the fixture
            # writes the file in the loaded-frame record grammar.
            self.assertEqual(record["provenance"]["source_startup_digest"],
                             record["provenance"]["source_current_digest"])
            self.assertEqual(len(record["provenance"]["source_startup_digest"]),
                             64)
            tape_file = self.base / f"synthetic-tape-{1 if label == 'A' else 2}.bin"
            tape = record["provenance"]["tape_loaded"]
            self.assertEqual(tape, {"records": len(SYNTHETIC_TAPE_FRAMES),
                                    "sha256": synthetic_tape_digest()},
                             "tape_loaded must digest the declared frames the "
                             "process loaded, not a canned or foreign value")
            identity = record["provenance"]["tape_file_identity"]
            self.assertEqual(identity["path"], str(tape_file),
                             "the file receipt names the fixture's own tape, "
                             "never an operator corpus file")
            self.assertEqual(identity["file_sha256"],
                             hashlib.sha256(tape_file.read_bytes()).hexdigest(),
                             "the file receipt is a live read of that file")
            self.assertEqual(identity["bytes"], tape_file.stat().st_size)
            # REAL preparation: the learn receipt is a production reply
            learn = [r for r in record["qa_receipts"]
                     if r["command"].get("command") == "learn"]
            self.assertTrue(learn, "the real learn preparation must be kept")
            self.assertTrue(learn[0]["result"]["ok"])
            self.assertEqual(learn[0]["result"]["result"]["rank"], 1)
            self.assertEqual(learn[0]["result"]["result"]["eid"], SKYE_EID)
            teleports = [r for r in record["qa_receipts"]
                         if r["command"].get("command") == "teleport"]
            self.assertGreaterEqual(len(teleports), 2,
                                    "both fixture actors are placed by the "
                                    "production teleport command")

    def test_real_cast_backs_the_acknowledgment(self):
        """The accepted-operation evidence is a REAL production cast.

        The UI gestures are the driver's; what backs SERVER_ACKNOWLEDGED is
        the world's own state after the production client frame
        (1060 target order -> real basic attack/lock; 1042 ground order ->
        real Skye B payment, cooldown and Suri missiles).
        """
        for label, record, effect in zip(("A", "B"), (self.va, self.vb),
                                        self.effects):
            observed = record["observed"]
            resources = record["observations"]["resources"]
            self.assertTrue(observed["energy_paid"], (label, observed))
            self.assertTrue(observed["cooldown_running"], (label, observed))
            cost = sc.DEFAULT_PROFILE["ability_costs"]["B"]
            drop = resources["energy_before"] - resources["energy_after"]
            # the native Skye B cost (server/abilities.py create_skye_kit):
            # regeneration during the effect window can only reduce the drop
            self.assertGreater(drop, 0.0, f"{label}: no real energy payment")
            self.assertLessEqual(drop, cost,
                                 f"{label}: drop {drop} exceeds the native "
                                 f"cost {cost}")
            # a real 1086 lock on the enemy hero, from the real basic attack
            self.assertIn({"target": ENEMY_EID, "source": SKYE_EID, "kind": 602},
                          effect["locks"], f"{label}: {effect['locks']}")
            # ... and the real Suri missiles really damaged that hero
            hits = [frame for frame in effect["damage"]
                    if frame["victim"] == ENEMY_EID
                    and frame["attacker"] == SKYE_EID]
            self.assertTrue(hits, f"{label}: no real production damage frames")
            self.assertTrue(all(frame["delta"] < 0 for frame in hits), hits)
            self.assertGreater(effect["tick"], 0)

    def test_same_match_authority_restart_is_a_continuity_failure(self):
        """A REAL restart of the QA authority mid-trial (same match, same
        process, new startup identity) must fail TRIAL_CONTINUITY — with the
        already-observed input/ack/effect stages intact and the initial
        receipt retained."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-real-qa-restart-"))
        try:
            result, stack, _harness = run_real_trial(
                base, 1, restart_after="learn")
            self.assertEqual(stack.restarts, 1,
                             "the fixture must have restarted the authority")
            self.assertEqual(result["status"], "FAIL",
                             result.get("failure_detail"))
            self.assertEqual(result["first_failed_stage"], "TRIAL_CONTINUITY")
            self.assertEqual(result["stages"]["TRIAL_CONTINUITY"]["status"],
                             "FAIL")
            for stage in ("UI_COMMAND_SUBMITTED", "CLIENT_INPUT_OBSERVED",
                          "SERVER_ACKNOWLEDGED", "AUTHORITATIVE_EFFECT"):
                self.assertEqual(result["stages"][stage]["status"], "PASS",
                                 f"{stage} was observed before the restart "
                                 "and must keep its own status")
            initial = result["observations"]["diagnostics_linkage"]
            self.assertEqual(initial["pid"], os.getpid())
            self.assertEqual(initial["match_id"], REAL_QA_MATCH_ID)
            self.assertNotIn("diagnostics_linkage_end", result["observations"])
            self.assertIn("startup_at changed within the trial",
                          result["failure_detail"])
            self.assertIn("the process or match restarted mid-trial",
                          result["failure_detail"])
            # the raw endpoint reply is preserved: same match, same pid,
            # different startup identity — a restart, not a different match
            endpoint = [r for r in result["qa_receipts"]
                        if r["label"] == "endpoint-diagnostics"]
            self.assertEqual(len(endpoint), 1)
            raw = endpoint[0]["result"]["result"]
            self.assertEqual(raw["match_id"], initial["match_id"])
            self.assertEqual(raw["pid"], initial["pid"])
            self.assertNotEqual(raw["startup_at"], initial["startup_at"])
            self.assertGreater(raw["tick"], initial["tick"],
                               "the endpoint read is a later live state")
            self.assertTrue(Path(result["result_path"]).exists())
        finally:
            shutil.rmtree(base, ignore_errors=True)


_POSITIVE_RECORD: dict = {}


def positive_minion_record():
    """The UNMODIFIED record the production writer produces for the accepted
    lane, produced once per test session.

    ``run_minion_trial`` runs the real ``run_client`` entry point with the
    scripted census/wire lane, so this record is exactly what a live trial
    serializes — nothing here edits it before the validator sees it.
    """
    if "record" not in _POSITIVE_RECORD:
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-record-positive-"))
        rows = [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]
        result, harness = run_minion_trial(
            base, 1, rows=rows,
            structures=[MINION_LANE_STRUCTURE, MINION_FRIENDLY_STRUCTURE],
            script=lambda h, s, r: script_lane(h, s, r), window=8.0)
        _POSITIVE_RECORD.update({
            "result": result, "harness": harness, "base": base,
            "record": json.loads(Path(result["result_path"])
                                 .read_text(encoding="utf-8"))})
    return _POSITIVE_RECORD["record"]


def _dispose_positive_record():
    entry = _POSITIVE_RECORD.pop("harness", None)
    if entry is not None:
        entry.cleanup()
    base = _POSITIVE_RECORD.pop("base", None)
    if base is not None:
        shutil.rmtree(base, ignore_errors=True)
    _POSITIVE_RECORD.clear()


class TestMinionRecordValidation(unittest.TestCase):
    """Checkpoint 12: ONE serialized minion observation record, judged by the
    production record validator (``sc.validate_minion_record``).

    The single-record contract is: scenario, source/client/config/tape
    provenance, initial/end diagnostics continuity, the DECLARED observation
    duration against the observed frame, actor and team identities,
    timestamped census timelines, payload-backed combat/death/structure/slot
    evidence and the same-participant chronological sequence. Everything
    derived (episodes, summary counts, stage statuses) is RECOMPUTED from the
    carried evidence and compared with what the record saved, so a saved
    status is an assertion to check, never evidence.

    The positive here is the unmodified writer record. Every tamper case
    starts from that same record and changes exactly one thing — including
    BOTH serialized copies of the observation window, which is what a forger
    editing the record has to do to stay self-consistent.

    The two-record pair equivalence contract is NOT part of this class and is
    not implied by ``accepted``: a validator PASS here says one record is
    coherent and complete, never that two records agree.
    """

    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(_dispose_positive_record)

    def _positive(self):
        return positive_minion_record()

    @staticmethod
    def _window(record):
        return record["observations"]["minion_window"]

    def _tamper(self, mutate):
        """Deep copy of the positive with the two serialized window copies
        aliased to ONE object, so the case's edit is consistently present in
        both; nothing else about the record is touched."""
        record = copy.deepcopy(self._positive())
        window = record["observations"]["minion_window"]
        record["observed"] = window
        mutate(record, window)
        return record

    def _rejected(self, label, mutate):
        record = self._tamper(mutate)
        verdict = sc.validate_minion_record(record)
        self.assertFalse(verdict["valid"],
                         f"{label} was accepted: {verdict['reasons']}")
        self.assertFalse(verdict["accepted"], label)
        return verdict

    def _assert_reason(self, verdict, needle, label):
        joined = " | ".join(verdict["reasons"])
        self.assertIn(needle, joined,
                      f"{label}: expected {needle!r} in {joined!r}")

    # -- the unmodified writer record --------------------------------------

    def test_unmodified_writer_positive_is_accepted(self):
        record = self._positive()
        verdict = sc.validate_minion_record(record)
        self.assertEqual(verdict["reasons"], [])
        self.assertEqual(verdict["incomplete"], [])
        self.assertTrue(verdict["valid"])
        self.assertTrue(verdict["accepted"])
        self.assertTrue(all(verdict["checks"].values()), verdict["checks"])
        # the recomputation reproduces the saved claims from the record's own
        # evidence: stage statuses, per-actor episodes and every summary count
        window = self._window(record)
        for stage, status in verdict["recomputed"]["stage_status"].items():
            self.assertEqual(record["stages"][stage]["status"], status, stage)
        for eid, episode in verdict["recomputed"]["episodes"].items():
            self.assertEqual(window["per_actor_timelines"][eid]["episode"],
                             episode, eid)
        for name, value in verdict["recomputed"]["summary"].items():
            self.assertEqual(window[name], value, name)

    def test_positive_carries_one_unmodified_census_frame_series(self):
        """The frame evidence the recomputation rests on is really carried:
        one frame per census, strictly ordered, and every timeline a tail of
        them."""
        record = self._positive()
        window = self._window(record)
        frames = window["census_instants"]
        self.assertEqual(len(frames), window["movement_samples"] + 1)
        self.assertEqual(frames, sorted(frames))
        self.assertEqual(len(set(frames)), len(frames))
        for entry in window["per_actor_timelines"].values():
            instants = [point[0] for point in entry["points"]]
            self.assertEqual(instants, frames[len(frames) - len(instants):])

    # -- the carried census clock: TYPED before any arithmetic --------------
    #
    # The parent review's witness set ``census_sim_times[1]`` to a string and
    # the pair comparator raised ``TypeError: unsupported operand type(s) for -:
    # 'str' and 'float'`` — the type gate had refused the entry, and a later
    # loop subtracted it anyway. Every malformed shape a JSON entry can take is
    # a STRUCTURED failure below, named by frame, with no exception raised
    # anywhere (a blanket except would hide the very divergence these records
    # exist to expose).

    def _with_clock_entry(self, key, value, index=1):
        """The positive record with ONE census clock entry replaced."""
        def mutate(record, window):
            window[key] = list(window[key])
            window[key][index] = value
        return mutate

    def test_a_malformed_census_sim_time_entry_is_a_typed_failure(self):
        for value in ("bad", ["bad"], {"time": 1.0}, True,
                      float("nan"), float("inf"), float("-inf")):
            with self.subTest(time=repr(value)):
                verdict = self._rejected(
                    f"clock time {value!r}",
                    self._with_clock_entry("census_sim_times", value))
                self._assert_reason(verdict, "census frame 1 simulation clock",
                                    f"clock time {value!r}")
                self._assert_reason(verdict,
                                    "is not an integer tick with a finite time",
                                    f"clock time {value!r}")
                self.assertIs(verdict["checks"]["census_sim_clock"], False,
                              "a malformed entry is a FAILED check, never a "
                              "silent pass and never a not-carried gap")

    def test_a_malformed_census_sim_tick_entry_is_a_typed_failure(self):
        for value in ("148", 1.5, True, [148], {"tick": 148}):
            with self.subTest(tick=repr(value)):
                verdict = self._rejected(
                    f"clock tick {value!r}",
                    self._with_clock_entry("census_sim_ticks", value))
                self._assert_reason(verdict, "census frame 1 simulation clock",
                                    f"clock tick {value!r}")
                self._assert_reason(verdict,
                                    "is not an integer tick with a finite time",
                                    f"clock tick {value!r}")

    def test_a_tick_beyond_float_arithmetic_is_refused_not_multiplied(self):
        """A tick so large that Python cannot multiply it by the record's own
        rate raises OverflowError if it is computed. It is refused by the type
        gate instead: the check never performs arithmetic the entry has not
        been typed for."""
        def mutate(record, window):
            window["census_sim_ticks"] = list(window["census_sim_ticks"])
            window["census_sim_times"] = list(window["census_sim_times"])
            window["census_sim_ticks"][1] = 10 ** 400
            window["census_sim_times"][1] = 1e300

        verdict = self._rejected("oversized tick", mutate)
        self._assert_reason(verdict, f"is beyond {sc.MAX_CLOCK_TICK}",
                            "oversized tick")
        self._assert_reason(verdict, "cannot be checked in float arithmetic",
                            "oversized tick")

    def test_a_malformed_trial_endpoint_clock_is_a_typed_failure(self):
        for value in ("later", True, float("nan"), ["t"], {"time": 1.0}):
            with self.subTest(time=repr(value)):
                def mutate(record, window, value=value):
                    record["provenance"]["diagnostics_end"]["time"] = value

                verdict = self._rejected(f"endpoint time {value!r}", mutate)
                self._assert_reason(verdict,
                                    "provenance.diagnostics_end: time "
                                    f"{value!r} is not a finite number",
                                    f"endpoint time {value!r}")
                self._assert_reason(verdict,
                                    "the census clock cannot be placed inside "
                                    "the trial that read it",
                                    f"endpoint time {value!r}")

    def test_an_endpoint_that_is_not_a_receipt_object_is_a_typed_failure(self):
        def mutate(record, window):
            record["provenance"]["diagnostics_end"] = "later"

        verdict = self._rejected("endpoint not an object", mutate)
        self._assert_reason(verdict, "provenance.diagnostics_end str",
                            "endpoint not an object")
        self._assert_reason(verdict, "is not a receipt object",
                            "endpoint not an object")
        self.assertFalse(verdict["accepted"])

    def test_a_numeric_clock_that_contradicts_its_own_rate_is_refused(self):
        """The check the typed gate protects: an entry that IS a finite number
        but is not this record's own rate × tick is a real failure, so the
        typing above never becomes a way to skip the relation."""
        def mutate(record, window):
            window["census_sim_times"] = list(window["census_sim_times"])
            window["census_sim_times"][1] += 0.25

        verdict = self._rejected("rate contradiction", mutate)
        self._assert_reason(verdict, "is not tick ", "rate contradiction")
        self._assert_reason(verdict, "on this record's own rate",
                            "rate contradiction")

    # -- forged claims ------------------------------------------------------

    def test_forged_stage_status_is_rejected(self):
        def mutate(record, window):
            record["stages"]["STRUCTURE_INTERACTION"] = {
                "status": "NOT_OBSERVED", "detail": "forged"}

        verdict = self._rejected("forged stage status", mutate)
        self._assert_reason(verdict, "stage STRUCTURE_INTERACTION is recorded "
                                     "'NOT_OBSERVED' but the carried evidence "
                                     "recomputes it as 'PASS'",
                            "forged stage status")

    def test_forged_summary_count_is_rejected(self):
        def mutate(record, window):
            window["survivors_resumed"] = 7

        verdict = self._rejected("forged summary count", mutate)
        self._assert_reason(verdict, "summary.survivors_resumed is recorded 7 "
                                     "but recomputing it from the carried "
                                     "evidence gives 1",
                            "forged summary count")

    def test_forged_episode_claim_is_rejected(self):
        def mutate(record, window):
            window["per_actor_timelines"]["4610"]["episode"][
                "structure_sequence"] = {"structure": 3539, "time": 1.0,
                                         "structure_team": 2}

        verdict = self._rejected("forged episode claim", mutate)
        self._assert_reason(verdict,
                            "per_actor_timelines[4610].episode differs from "
                            "the episode recomputed from its own timeline",
                            "forged episode claim")

    def test_forged_participation_is_rejected(self):
        """A record claiming an actor took part in combat its own carried
        evidence does not contain."""
        def mutate(record, window):
            window["per_actor_timelines"]["4610"]["episode"][
                "combat_participant"] = False

        verdict = self._rejected("forged participation", mutate)
        self._assert_reason(verdict,
                            "per_actor_timelines[4610].episode differs from "
                            "the episode recomputed from its own timeline",
                            "forged participation")

    def test_first_failed_stage_naming_a_passing_stage_is_rejected(self):
        def mutate(record, window):
            record["status"] = "FAIL"
            record["first_failed_stage"] = "SURVIVOR_RESUMPTION"
            record["failure_detail"] = "forged"

        verdict = self._rejected("first_failed_stage names a PASS stage",
                                 mutate)
        self._assert_reason(verdict, "first_failed_stage 'SURVIVOR_RESUMPTION' "
                                     "is recorded PASS", "first failed stage")

    def test_pass_claim_without_continuity_receipt_is_rejected(self):
        """A PASS claim whose own continuity stage is not PASS contradicts
        itself: the endpoint receipt is read before the writer can reach
        PASS."""
        def mutate(record, window):
            record["stages"]["TRIAL_CONTINUITY"] = {"status": "NOT_OBSERVED",
                                                    "detail": "forged"}

        verdict = self._rejected("PASS without continuity", mutate)
        self._assert_reason(verdict,
                            "the record claims PASS but TRIAL_CONTINUITY is "
                            "recorded 'NOT_OBSERVED'", "continuity")

    def test_honest_record_without_continuity_is_not_accepted(self):
        """The same stage missing from an honestly FAILED record is not a
        malformed record: the trial simply never reached its endpoint."""
        record = self._tamper(lambda r, w: None)
        del record["stages"]["TRIAL_CONTINUITY"]
        record["provenance"]["diagnostics_end"] = None
        record["status"] = "FAIL"
        record["first_failed_stage"] = "AUTHORITATIVE_EFFECT"
        record["failure_detail"] = "the session stopped answering"
        verdict = sc.validate_minion_record(record)
        self.assertTrue(verdict["valid"], verdict["reasons"])
        self.assertFalse(verdict["accepted"])
        self.assertFalse(verdict["checks"]["trial_continuity"])
        self.assertFalse(verdict["checks"]["complete_claim"])
        joined = " | ".join(verdict["incomplete"])
        self.assertIn("no TRIAL_CONTINUITY stage was collected", joined)
        self.assertIn("carries no typed receipt", joined)
        self.assertIn("the record's own verdict is 'FAIL'", joined)

    # -- timeline and frame damage -----------------------------------------

    def test_missing_or_malformed_timeline_is_rejected(self):
        def missing(record, window):
            window["per_actor_timelines"] = {}

        def not_an_object(record, window):
            window["per_actor_timelines"]["4610"] = "not a timeline"

        def short_point(record, window):
            window["per_actor_timelines"]["4610"]["points"][0] = [1.0, 2.0]

        def unknown_present(record, window):
            window["per_actor_timelines"]["4610"]["points"][0][4] = "yes"

        def unknown_hp(record, window):
            window["per_actor_timelines"]["4610"]["points"][0][3] = "300"

        def going_backwards(record, window):
            window["per_actor_timelines"]["4610"]["points"][1][0] -= 100.0

        cases = (("missing timelines", missing,
                  "per_actor_timelines empty"),
                 ("timeline not an object", not_an_object,
                  "per_actor_timelines[4610] is str, not an object"),
                 ("point is not 5 fields", short_point,
                  "is not a 5-field [t, x, y, hp, present] sample"),
                 ("present is not a boolean", unknown_present,
                  "present is str, not a boolean"),
                 ("hp is neither number nor null", unknown_hp,
                  "hp is '300', neither a finite number nor null"),
                 ("timestamps go backwards", going_backwards,
                  "precedes the previous sample"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)

    def test_timeline_that_skips_census_frames_is_rejected(self):
        def mutate(record, window):
            window["per_actor_timelines"]["4610"]["points"].pop(1)

        verdict = self._rejected("timeline skips a frame", mutate)
        self._assert_reason(verdict, "skips census frames", "frame gap")

    def test_frame_and_sample_counts_are_recomputed(self):
        def forged_sample_count(record, window):
            window["movement_samples"] = 3

        def fewer_frames(record, window):
            window["census_instants"].pop(1)

        def unsorted_frames(record, window):
            window["census_instants"][1], window["census_instants"][2] = (
                window["census_instants"][2], window["census_instants"][1])

        def no_frames(record, window):
            del window["census_instants"]

        cases = (("forged sample count", forged_sample_count,
                  "the saved sample count is not what the frames support"),
                 ("a census frame removed", fewer_frames,
                  "the saved sample count is not what the frames support"),
                 ("frames out of order", unsorted_frames,
                  "does not advance past the previous frame"),
                 ("no frames carried", no_frames,
                  "does not carry the census frames it observed"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)

    # -- evidence identity --------------------------------------------------

    def test_forged_or_malformed_payload_evidence_is_rejected(self):
        def odd_hex(record, window):
            window["combat_log"][0]["payload"] = "abc"

        def not_hex(record, window):
            window["combat_log"][0]["payload"] = "zz"

        def delta_not_in_payload(record, window):
            window["combat_log"][0]["delta"] = -99.0

        def victim_not_in_payload(record, window):
            window["combat_log"][0]["victim"] = 4611
            window["combat_log"][0]["victim_team"] = 2

        def wrong_opcode(record, window):
            window["structure_log"][0]["opcode"] = sc.OP_ENTITY_DEATH

        def no_payload(record, window):
            del window["death_log"][0]["payload"]

        cases = (("odd-length payload", odd_hex,
                  "combat_log[0].payload is not an even-length hex string"),
                 ("non-hex payload", not_hex,
                  "combat_log[0].payload is not an even-length hex string"),
                 ("delta not its payload", delta_not_in_payload,
                  "combat_log[0].delta -99.0 != -30.0 re-derived from its own "
                  "payload"),
                 ("victim not its payload", victim_not_in_payload,
                  "re-derived from its own payload"),
                 ("opcode not the claimed publication", wrong_opcode,
                  "structure_log[0].opcode 1072 is not the 1054 combat-delta "
                  "publication"),
                 ("payload missing", no_payload,
                  "death_log[0].payload is None, not a non-empty hex string"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)

    def test_short_or_truncated_evidence_payloads_are_rejected(self):
        """A payload shorter than the grammar its own opcode reads is not
        evidence: the identities the entry claims cannot be re-derived from
        it, so the entry must be rejected outright, never accepted on its
        metadata. Both serialized window copies carry the same edit (that is
        what ``_tamper`` does), so the rejection cannot come from a stale
        second copy."""
        def combat_one_byte(record, window):
            window["combat_log"][0]["payload"] = "00"

        def combat_truncated(record, window):
            payload = window["combat_log"][0]["payload"]
            window["combat_log"][0]["payload"] = payload[:16]      # 8 bytes

        def combat_empty(record, window):
            window["combat_log"][0]["payload"] = ""

        def structure_one_byte(record, window):
            window["structure_log"][0]["payload"] = "0d"

        def structure_truncated(record, window):
            payload = window["structure_log"][0]["payload"]
            window["structure_log"][0]["payload"] = payload[:20]   # 10 bytes

        def structure_empty(record, window):
            window["structure_log"][0]["payload"] = ""

        def death_one_byte(record, window):
            window["death_log"][0]["payload"] = "12"

        def death_truncated(record, window):
            payload = window["death_log"][0]["payload"]
            window["death_log"][0]["payload"] = payload[:12]       # 6 bytes

        def death_empty(record, window):
            window["death_log"][0]["payload"] = ""

        cases = (
            ("combat: one byte where 12 are read", combat_one_byte,
             "combat_log[0].payload decodes to 1 byte(s), below the 12 byte(s) "
             "the 1054 combat-delta grammar reads"),
            ("combat: truncated below the delta", combat_truncated,
             "combat_log[0].payload decodes to 8 byte(s), below the 12 byte(s)"),
            ("combat: empty payload", combat_empty,
             "combat_log[0].payload is '', not a non-empty hex string"),
            ("structure: one byte where 12 are read", structure_one_byte,
             "structure_log[0].payload decodes to 1 byte(s), below the 12 "
             "byte(s) the 1054 combat-delta grammar reads"),
            ("structure: truncated below the delta", structure_truncated,
             "structure_log[0].payload decodes to 10 byte(s), below the 12 "
             "byte(s)"),
            ("structure: empty payload", structure_empty,
             "structure_log[0].payload is '', not a non-empty hex string"),
            ("death: one byte where 8 are read", death_one_byte,
             "death_log[0].payload decodes to 1 byte(s), below the 8 byte(s) "
             "the 1072 ENTITY_DEATH grammar reads"),
            ("death: truncated below the killer", death_truncated,
             "death_log[0].payload decodes to 6 byte(s), below the 8 byte(s)"),
            ("death: empty payload", death_empty,
             "death_log[0].payload is '', not a non-empty hex string"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                record = self._tamper(mutate)
                window = self._window(record)
                self.assertEqual(record["observed"], window,
                                 f"{label}: the two serialized copies must "
                                 "agree for this case to mean anything")
                verdict = sc.validate_minion_record(record)
                self.assertFalse(verdict["valid"],
                                 f"{label} was accepted: {verdict['reasons']}")
                self.assertFalse(verdict["accepted"], label)
                self._assert_reason(verdict, needle, label)
                self.assertNotIn(
                    "disagree", " | ".join(verdict["reasons"]),
                    f"{label}: the edit was applied to BOTH copies, so the "
                    "rejection must come from the payload itself")

    def test_slot_order_evidence_is_grammar_checked(self):
        """The 1016 grammar the writer decodes is one byte (the slot), so a
        coherent slot attribution is accepted, a payload that cannot name the
        slot it claims is rejected, and a longer payload is allowed because
        the grammar reads a prefix."""
        def eid_of(window):
            return int(next(iter(window["per_actor_timelines"])))

        def inject(record, window, **overrides):
            entry = {"time": window["census_instants"][-1], "slot": 5,
                     "owner": eid_of(window),
                     "connection": record["connection"], "payload": "05"}
            entry.update(overrides)
            window["move_log"].append(entry)
            window["tracked_move_orders"] = len(window["move_log"])
            return entry

        def coherent(record, window):
            inject(record, window)

        def lower(record, window):
            inject(record, window, slot=6)

        def empty(record, window):
            inject(record, window, payload="")

        def odd_hex(record, window):
            inject(record, window, payload="0")

        def longer_prefix(record, window):
            inject(record, window, payload="0500")

        def declared_opcode(record, window):
            inject(record, window, opcode=sc.OP_MOVE_ORDER)

        def wrong_opcode(record, window):
            inject(record, window, opcode=sc.OP_DAMAGE)

        def no_payload(record, window):
            entry = inject(record, window)
            del entry["payload"]

        record = self._tamper(coherent)
        verdict = sc.validate_minion_record(record)
        self.assertEqual(verdict["reasons"], [],
                         f"a coherent slot attribution was refused: "
                         f"{verdict['reasons']}")
        self.assertTrue(verdict["accepted"], verdict["recomputed"])
        self.assertEqual(verdict["recomputed"]["summary"]["tracked_move_orders"],
                         1)

        # the writer names the kind by the move_log key and carries no opcode;
        # an opcode it DOES carry must be the 1016 it was read as
        for label, mutate in (("longer payload", longer_prefix),
                              ("carried opcode", declared_opcode)):
            with self.subTest(label):
                verdict = sc.validate_minion_record(self._tamper(mutate))
                self.assertEqual(verdict["reasons"], [], f"{label}: "
                                 f"{verdict['reasons']}")
                self.assertTrue(verdict["accepted"], label)

        cases = (("slot does not match its payload", lower,
                  "move_log[0].slot 6 != 5 re-derived from its own payload"),
                 ("empty payload", empty,
                  "move_log[0].payload is '', not a non-empty hex string"),
                 ("odd-length payload", odd_hex,
                  "move_log[0].payload is not an even-length hex string"),
                 ("payload removed", no_payload,
                  "move_log[0].payload is None, not a non-empty hex string"),
                 ("opcode is not the 1016 it was read as", wrong_opcode,
                  "move_log[0].opcode 1054 is not the 1016 move-order "
                  "publication the entry claims"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)

    def test_container_and_untyped_identities_are_structured_failures(self):
        """An identity that is a list/dict/string/float/bool is reported as
        such BEFORE anything looks it up: a container cannot be a dict key, so
        it must never reach a membership test or a lookup."""
        def eid_of(window):
            return int(next(iter(window["per_actor_timelines"])))

        def combat_victim_container(record, window):
            window["combat_log"][0]["victim"] = []

        def combat_attacker_container(record, window):
            window["combat_log"][0]["attacker"] = {"eid": 4610}

        def combat_team_container(record, window):
            window["combat_log"][0]["victim_team"] = []

        def structure_container(record, window):
            window["structure_log"][0]["structure"] = [[]]

        def structure_attacker_container(record, window):
            window["structure_log"][0]["attacker"] = []

        def death_victim_container(record, window):
            window["death_log"][0]["victim"] = []

        def death_killer_container(record, window):
            window["death_log"][0]["killer"] = {}

        def move_slot_container(record, window):
            window["move_log"].append(
                {"time": window["census_instants"][-1], "slot": [],
                 "owner": eid_of(window), "connection": record["connection"],
                 "payload": "05"})
            window["tracked_move_orders"] = 1

        def move_owner_container(record, window):
            window["move_log"].append(
                {"time": window["census_instants"][-1], "slot": 5,
                 "owner": {}, "connection": record["connection"],
                 "payload": "05"})
            window["tracked_move_orders"] = 1

        def combat_victim_string(record, window):
            window["combat_log"][0]["victim"] = "4610"

        def combat_victim_float(record, window):
            window["combat_log"][0]["victim"] = 4610.0

        def combat_victim_bool(record, window):
            window["combat_log"][0]["victim"] = True

        cases = (
            ("combat victim is a list", combat_victim_container,
             "combat_log[0].victim [] (list) is not an integer entity "
             "identity"),
            ("combat attacker is a dict", combat_attacker_container,
             "combat_log[0].attacker {'eid': 4610} (dict) is not an integer "
             "entity identity"),
            ("combat team is a list", combat_team_container,
             "combat_log[0].victim_team [] is not a team identity"),
            ("structure is a list", structure_container,
             "structure_log[0].structure [[]] (list) is not an integer entity "
             "identity"),
            ("structure attacker is a list", structure_attacker_container,
             "structure_log[0].attacker [] (list) is not an integer entity "
             "identity"),
            ("death victim is a list", death_victim_container,
             "death_log[0].victim [] (list) is not an integer entity "
             "identity"),
            ("death killer is a dict", death_killer_container,
             "death_log[0].killer {} (dict) is not an integer entity "
             "identity"),
            ("move slot is a list", move_slot_container,
             "move_log[0].slot [] (list) is not an integer entity identity"),
            ("move owner is a dict", move_owner_container,
             "move_log[0].owner {} (dict) is not an integer entity identity"),
            ("combat victim is a string", combat_victim_string,
             "combat_log[0].victim '4610' (str) is not an integer entity "
             "identity"),
            ("combat victim is a float", combat_victim_float,
             "combat_log[0].victim 4610.0 (float) is not an integer entity "
             "identity"),
            ("combat victim is a bool", combat_victim_bool,
             "combat_log[0].victim True (bool) is not an integer entity "
             "identity"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)
                self.assertIsInstance(verdict["reasons"], list)

    def test_wrong_actor_team_or_connection_is_rejected(self):
        def untracked_actor(record, window):
            window["combat_log"][0]["attacker"] = 999999

        def untracked_death(record, window):
            window["death_log"][0]["victim"] = 999999

        def flipped_team(record, window):
            entry = window["combat_log"][0]
            entry["victim_team"] = entry["attacker_team"]

        def untyped_team(record, window):
            window["per_actor_timelines"]["4610"]["team"] = "1"

        def opposite_stream(record, window):
            window["combat_log"][0]["connection"] = 111

        def window_stream(record, window):
            window["connection"] = 111

        def window_not_the_record(record, window):
            record["connection"] = 111

        cases = (("untracked attacker", untracked_actor,
                  "combat_log[0] names victim 4610 / attacker 999999 that "
                  "this record does not track"),
                 ("death for an untracked actor", untracked_death,
                  "death_log[0].victim 999999 is not a tracked actor"),
                 ("carried team contradicts the census", flipped_team,
                  "victim_team 2 contradicts the census team of 4610 (1)"),
                 ("team is not an integer", untyped_team,
                  "per_actor_timelines[4610].team '1' is not a team identity"),
                 ("evidence from another stream", opposite_stream,
                  "combat_log[0].connection 111 != the observed connection"),
                 ("window from another stream", window_stream,
                  "minion_window.connection 111 != result.connection 424242"),
                 ("window not the record's stream", window_not_the_record,
                  "minion_window.connection 424242 != result.connection 111"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)

    def test_structure_identity_is_required_and_checked(self):
        def no_team_for_structure(record, window):
            window["structure_log"][0]["structure"] = 9999

        def served_team_flipped(record, window):
            window["structure_teams"]["3539"] = 1

        def non_team_served(record, window):
            window["structure_teams"]["3539"] = 3

        cases = (("structure with no carried team", no_team_for_structure,
                  "structure_log[0].structure 9999 has no carried team"),
                 ("served team contradicts the hit", served_team_flipped,
                  "structure_log[0].structure_team 2 contradicts the served "
                  "team of structure 3539 (1)"),
                 ("served team is not a team", non_team_served,
                  "structure_teams[3539] 3 is neither null nor a team "
                  "identity"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)

    def test_duplicate_window_copies_must_agree(self):
        """The writer serializes the observation window twice; editing only
        one copy is detected even when the edited copy is internally
        consistent."""
        record = self._tamper(lambda r, w: None)
        self.assertIsNotNone(record.get("observed"))
        record["observed"] = copy.deepcopy(self._window(record))
        record["observed"]["survivors_resumed"] = 7
        verdict = sc.validate_minion_record(record)
        self.assertFalse(verdict["valid"])
        self._assert_reason(verdict,
                            "result.observed and observations.minion_window "
                            "disagree", "single-copy edit")

    # -- declared duration and provenance ----------------------------------

    def test_declared_observation_duration_is_verified(self):
        def shorter_frame(record, window):
            window["window_end"] = window["window_start"] + 0.5

        def no_declaration(record, window):
            record["fixture_contract"]["observational_window_s"] = None

        def untyped_declaration(record, window):
            record["fixture_contract"]["observational_window_s"] = "8"

        cases = (("frame shorter than declared", shorter_frame,
                  "short of the declared observation duration"),
                 ("declared duration missing", no_declaration,
                  "observational_window_s None is not a positive finite "
                  "declared duration"),
                 ("declared duration not a number", untyped_declaration,
                  "observational_window_s '8' is not a positive finite "
                  "declared duration"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)

    def test_provenance_and_endpoint_continuity_are_required(self):
        def no_provenance(record, window):
            del record["provenance"]

        def no_endpoint(record, window):
            record["provenance"]["diagnostics_end"] = None

        def changed_source(record, window):
            record["provenance"]["source_current_digest"] = "0" * 64

        def other_match(record, window):
            record["provenance"]["diagnostics"]["match_id"] = "0" * 8

        def window_unnamed(record, window):
            window["match_id"] = ""

        def window_digest(record, window):
            window["profile_digest"] = "not-a-sha256"

        cases = (("provenance removed", no_provenance,
                  "provenance is NoneType, not an object"),
                 ("endpoint receipt removed", no_endpoint,
                  "provenance.diagnostics_end missing — no process/startup/"
                  "session linkage evidence"),
                 ("source changed under the trial", changed_source,
                  "loaded source changed since server startup"),
                 ("linkage names another match", other_match,
                  "the receipt and the observation are not the same match"),
                 ("window has no match id", window_unnamed,
                  "match_id '' is not a non-empty string"),
                 ("window has no profile digest", window_digest,
                  "profile_digest 'not-a-sha256' is not a sha256"))
        for label, mutate, needle in cases:
            with self.subTest(label):
                verdict = self._rejected(label, mutate)
                self._assert_reason(verdict, needle, label)

    def test_malformed_records_never_raise(self):
        """A record that is not even shaped like a record gives structured
        reasons instead of an exception."""
        samples = ("not a record", None, [], 17,
                   {}, {"observations": []},
                   {"observations": {"minion_window": "no"}},
                   {"observations": {"minion_window": {}}},
                   {"observations": {"minion_window": {"per_actor_timelines":
                                                       None}}})
        for sample in samples:
            with self.subTest(sample=repr(sample)[:40]):
                verdict = sc.validate_minion_record(sample)
                self.assertFalse(verdict["valid"])
                self.assertFalse(verdict["accepted"])
                self.assertTrue(verdict["reasons"])
                self.assertIsInstance(verdict["reasons"], list)
                self.assertIn("checks", verdict)
                self.assertIn("recomputed", verdict)

    def test_a_record_with_no_minion_window_is_not_valid(self):
        record = copy.deepcopy(self._positive())
        del record["observations"]["minion_window"]
        verdict = sc.validate_minion_record(record)
        self.assertFalse(verdict["valid"])
        self._assert_reason(verdict, "observations.minion_window missing",
                            "no window")

    # -- honest negatives: an incomplete trial is coherent, not malformed ---

    def test_honest_incomplete_record_is_valid_but_not_accepted(self):
        """A trial that really observed a partial sequence must be reported
        as such, not as a malformed record: no closure, a hit, no resumption.
        """
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-record-noclose-"))
        rows = [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]

        def script(harness, sample, rows):
            script_lane(harness, sample, rows, kill_at=None,
                        structure_at=5, march=(3, 4))

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, window=8.0)
        try:
            record = json.loads(Path(result["result_path"])
                                .read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "FAIL")
            self.assertEqual(record["stages"]["OPPOSING_COMBAT"]["status"],
                             "PASS")
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "NOT_OBSERVED")
            verdict = sc.validate_minion_record(record)
            self.assertTrue(verdict["valid"], verdict["reasons"])
            self.assertFalse(verdict["accepted"])
            self.assertTrue(verdict["incomplete"],
                            "the missing parts are named, not inferred")
            self.assertEqual(verdict["recomputed"]["stage_status"],
                             {"LANE_APPROACH": "PASS",
                              "OPPOSING_COMBAT": "PASS",
                              "SURVIVOR_RESUMPTION": "NOT_OBSERVED",
                              "STRUCTURE_INTERACTION": "NOT_OBSERVED"})
            episode = verdict["recomputed"]["episodes"]["4610"]
            self.assertIsNone(episode["structure_sequence"])
            self.assertIsNone(episode["engagement_end"],
                              "the opponent never died: no closure instant")
            self.assertIn("engagement has no carried end instant",
                          " | ".join(episode["structure_unverified"]
                                     ["reasons"]))
            # and the forged upgrade of that honest record is rejected
            def mutate(forged, window):
                forged["stages"]["STRUCTURE_INTERACTION"] = {
                    "status": "PASS", "detail": "forged"}
                forged["status"] = "PASS"
                forged["first_failed_stage"] = None
                forged["failure_detail"] = None

            forged = copy.deepcopy(record)
            window = forged["observations"]["minion_window"]
            forged["observed"] = window
            mutate(forged, window)
            upgraded = sc.validate_minion_record(forged)
            self.assertFalse(upgraded["valid"])
            self._assert_reason(upgraded,
                                "the record claims PASS while its carried "
                                "evidence recomputes an incomplete sequence",
                                "forged structure claim")
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_movement_before_the_closure_is_not_an_accepted_resumption(self):
        """The actor marches while the fight is still open, then holds: the
        closure is the opponent's later death, so the pre-closure movement is
        not a resumption — and the record can never be accepted on it."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-record-open-"))
        rows = [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4612, "team": 1, "x": 12.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]

        def script(harness, sample, rows):
            actor = rows[0]
            mate = rows[1] if len(rows) > 1 else None
            opponent = rows[2] if len(rows) > 2 else None
            if sample == 1:
                actor["x"] += 2.0
            if sample == 2 and opponent is not None:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(opponent["eid"],
                                                      actor["eid"], -40.0)})
            if sample in (3, 4):
                actor["x"] += 2.0
            if sample == 5 and opponent is not None:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(mate["eid"],
                                                      opponent["eid"], -60.0)})
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242,
                              "opcode": sc.OP_ENTITY_DEATH,
                              "payload": build_entity_death(opponent["eid"],
                                                            actor["eid"])})
                del rows[2]

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[], script=script, window=8.0)
        try:
            record = json.loads(Path(result["result_path"])
                                .read_text(encoding="utf-8"))
            self.assertEqual(record["stages"]["SURVIVOR_RESUMPTION"]["status"],
                             "NOT_OBSERVED")
            verdict = sc.validate_minion_record(record)
            self.assertTrue(verdict["valid"], verdict["reasons"])
            self.assertFalse(verdict["accepted"])
            episode = verdict["recomputed"]["episodes"]["4610"]
            self.assertEqual(episode["resumed_after_combat"], 0.0,
                             "only post-closure movement is credited")
            self.assertIsNotNone(episode["engagement_end"])
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_friendly_structure_hit_is_not_an_accepted_sequence(self):
        """The same participant hits its OWN team's structure after its
        resumption: a raw hit, an unverified sequence, no acceptance."""
        base = Path(tempfile.mkdtemp(prefix="halcyon-minion-record-friendly-"))
        rows = [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]
        actor, opponent = rows

        def script(harness, sample, rows):
            if sample in (1, 2):
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(actor["eid"],
                                                      opponent["eid"],
                                                      -30.0)})
            if sample == 2:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242,
                              "opcode": sc.OP_ENTITY_DEATH,
                              "payload": build_entity_death(opponent["eid"],
                                                            actor["eid"])})
                del rows[1]
            if sample in (3, 4):
                actor["x"] += 2.0
            if sample == 5:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  MINION_FRIENDLY_STRUCTURE["eid"],
                                  actor["eid"], -40.0)})

        result, harness = run_minion_trial(
            base, 1, rows=rows,
            structures=[MINION_LANE_STRUCTURE, MINION_FRIENDLY_STRUCTURE],
            script=script, window=8.0)
        try:
            record = json.loads(Path(result["result_path"])
                                .read_text(encoding="utf-8"))
            verdict = sc.validate_minion_record(record)
            self.assertTrue(verdict["valid"], verdict["reasons"])
            self.assertFalse(verdict["accepted"])
            self.assertEqual(verdict["recomputed"]["stage_status"]
                             ["SURVIVOR_RESUMPTION"], "PASS")
            self.assertEqual(verdict["recomputed"]["stage_status"]
                             ["STRUCTURE_INTERACTION"], "NOT_OBSERVED")
            episode = verdict["recomputed"]["episodes"]["4610"]
            self.assertIsNone(episode["structure_sequence"])
            self.assertIn("own team", " | ".join(
                episode["structure_unverified"]["reasons"]))
        finally:
            harness.cleanup()
            shutil.rmtree(base, ignore_errors=True)

    def test_post_death_and_pre_resumption_hits_are_not_accepted(self):
        """Two lanes in one test: a hit published after the actor's own death,
        and a hit published before its resumption could be measured. Both are
        carried raw, neither is a proven sequence, and neither record can be
        accepted."""
        lanes = (
            ("post-death", self._post_death_lane, "post-death hit cannot "
                                                  "qualify"),
            ("pre-resumption", self._pre_resumption_lane,
             "not later than the engagement-end instant"),
        )
        for label, build, needle in lanes:
            with self.subTest(label):
                base = Path(tempfile.mkdtemp(
                    prefix=f"halcyon-minion-record-{label}-"))
                rows, script = build()
                result, harness = run_minion_trial(
                    base, 1, rows=rows,
                    structures=[MINION_LANE_STRUCTURE], script=script,
                    window=8.0)
                try:
                    record = json.loads(Path(result["result_path"])
                                        .read_text(encoding="utf-8"))
                    verdict = sc.validate_minion_record(record)
                    self.assertTrue(verdict["valid"], verdict["reasons"])
                    self.assertFalse(verdict["accepted"])
                    episode = verdict["recomputed"]["episodes"]["4610"]
                    self.assertIsNone(episode["structure_sequence"])
                    self.assertIn(needle, " | ".join(
                        episode["structure_unverified"]["reasons"]))
                    # the forged upgrade of the stage is rejected outright
                    forged = copy.deepcopy(record)
                    window = forged["observations"]["minion_window"]
                    forged["observed"] = window
                    forged["stages"]["STRUCTURE_INTERACTION"] = {
                        "status": "PASS", "detail": "forged"}
                    upgraded = sc.validate_minion_record(forged)
                    self.assertFalse(upgraded["valid"])
                    self._assert_reason(upgraded,
                                        "stage STRUCTURE_INTERACTION is "
                                        "recorded 'PASS' but the carried "
                                        "evidence recomputes it as "
                                        "'NOT_OBSERVED'", label)
                finally:
                    harness.cleanup()
                    shutil.rmtree(base, ignore_errors=True)

    @staticmethod
    def _exchange(harness, rows, actor, opponent, *, kill):
        harness.emit({"time": time.time(), "direction": "s2c",
                      "connection": 424242, "opcode": 1054,
                      "payload": build_damage(actor["eid"], opponent["eid"],
                                              -30.0)})
        if kill:
            harness.emit({"time": time.time(), "direction": "s2c",
                          "connection": 424242,
                          "opcode": sc.OP_ENTITY_DEATH,
                          "payload": build_entity_death(opponent["eid"],
                                                        actor["eid"])})
            for index, row in enumerate(rows):
                if row is opponent:
                    del rows[index]
                    break

    @staticmethod
    def _lane_rows():
        return [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]

    def _post_death_lane(self):
        rows = self._lane_rows()
        actor, opponent = rows

        def script(harness, sample, rows):
            if sample == 1:
                self._exchange(harness, rows, actor, opponent, kill=False)
            if sample == 2:
                self._exchange(harness, rows, actor, opponent, kill=True)
            if sample in (3, 4):
                actor["x"] += 2.0
            if sample == 5:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242,
                              "opcode": sc.OP_ENTITY_DEATH,
                              "payload": build_entity_death(actor["eid"],
                                                            opponent["eid"])})
                for index, row in enumerate(rows):
                    if row is actor:
                        del rows[index]
                        break
            if sample == 7:
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  MINION_LANE_STRUCTURE["eid"], actor["eid"],
                                  -40.0)})

        return rows, script

    def _pre_resumption_lane(self):
        rows = self._lane_rows()
        actor, opponent = rows

        def script(harness, sample, rows):
            if sample == 1:
                self._exchange(harness, rows, actor, opponent, kill=False)
                harness.emit({"time": time.time(), "direction": "s2c",
                              "connection": 424242, "opcode": 1054,
                              "payload": build_damage(
                                  MINION_LANE_STRUCTURE["eid"], actor["eid"],
                                  -40.0)})
            if sample == 2:
                self._exchange(harness, rows, actor, opponent, kill=True)
            if sample in (3, 4):
                actor["x"] += 2.0

        return rows, script


# ---------------------------------------------------------------------------
# Checkpoint 13: TWO minion observation records through the PUBLIC CLI
# ---------------------------------------------------------------------------

MINION_PAIR_STRUCTURES = [MINION_LANE_STRUCTURE, MINION_FRIENDLY_STRUCTURE]

# an epoch-second token (1.0e9 .. 2.0e9): the wall clock the writer stamps the
# minion window with, in JSON numbers and inside its own reason strings
_EPOCH_TOKEN = re.compile(r"\b1[0-9]\d{8}(?:\.\d+)?")


def minion_pair_lane(*, swap_roles=False, extra_combat=None, extra_first=True,
                     event_delay=0.0):
    """Rows and script for one ACCEPTED minion lane.

    The base lane is the checkpoint-12 positive: the two minions exchange a
    1054, the team-2 minion's death is published, the team-1 survivor marches
    twice toward the opposing base and then hits the opposing structure.

    ``extra_combat`` = ``(victim, attacker, delta)`` adds a SECOND combat event
    in the same sample as the exchange, so a pair can differ in event counts
    and damage totals while every measured stage still passes.
    ``extra_first`` decides whether that event is published BEFORE or AFTER the
    exchange, so two productions of the same lane can differ in nothing but the
    ORDER of their carried combat events.

    ``event_delay`` publishes every event this many seconds LATER in the same
    window (the census cadence is untouched — the delay is stamped into the
    published instant, it does not sleep the sampler), so two productions of
    the same lane can differ in nothing but their event SPACING. Everything the
    writer derives is derived from those instants, so the member stays
    coherent and accepted on its own.

    ``swap_roles`` follows the TEAM-2 minion instead: it marches toward its own
    enemy base (low x), closes the exchange and hits the team-1 structure. The
    team each actor carries never changes — only the cohort and the structure
    the outcome belongs to do.
    """
    team1 = {"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
             "max_hp": 300.0, "alive": True}
    team2 = {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
             "max_hp": 300.0, "alive": True}
    rows = [team2, team1] if swap_roles else [team1, team2]
    actor, opponent = rows
    step = -2.0 if swap_roles else 2.0
    structure = (MINION_FRIENDLY_STRUCTURE if swap_roles
                 else MINION_LANE_STRUCTURE)

    def script(harness, sample, rows):
        def emit(opcode, payload):
            harness.emit({"time": time.time() + event_delay, "direction": "s2c",
                          "connection": 424242, "opcode": opcode,
                          "payload": payload})

        def extra():
            emit(1054, build_damage(*extra_combat))

        def exchange():
            emit(1054, build_damage(actor["eid"], opponent["eid"], -30.0))
            emit(sc.OP_ENTITY_DEATH,
                 build_entity_death(opponent["eid"], actor["eid"]))
            for index, row in enumerate(rows):
                if row is opponent:
                    del rows[index]
                    break

        if sample == 2 and extra_combat is None:
            exchange()
        elif sample == 2:
            first, second = ((extra, exchange) if extra_first
                             else (exchange, extra))
            first()
            second()
        if sample in (3, 4):
            actor["x"] += step
        if sample == 5:
            emit(1054, build_damage(structure["eid"], actor["eid"], -40.0))

    return rows, script


def run_minion_pair_lane(base: Path, trial: int, *, prepare=None, window=8.0,
                         **lane):
    """ONE independent writer trial of the accepted lane (or a named variant)
    through the real ``run_client`` entry point, read back from the serialized
    record the CLI consumes."""
    clock_offset = lane.pop("clock_offset", 0)
    rows, script = minion_pair_lane(**lane)
    result, harness = run_minion_trial(base, trial, rows=rows,
                                       structures=MINION_PAIR_STRUCTURES,
                                       script=script, prepare=prepare,
                                       window=window,
                                       clock_offset=clock_offset)
    try:
        return json.loads(Path(result["result_path"])
                          .read_text(encoding="utf-8"))
    finally:
        harness.cleanup()


def write_pair_record(path: Path, record: dict) -> Path:
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    return path


def relabel_minion_actors(record: dict, mapping: dict) -> dict:
    """The same record with every ACTOR identity renamed by ``mapping``.

    Everything the writer saved that names an actor — the census keys, the
    episode claims, the reason strings that embed an eid, and the PAYLOAD BYTES
    themselves — is renamed together, so the relabelled record is still
    internally coherent and still accepted on its own evidence. Only the
    identities change; nothing about the observed outcome does. That is what
    makes it the honest witness for "two records that carry no actor mapping":
    nothing but the carried identity distinguishes the members.
    """
    def rename(value):
        return mapping.get(value, value)

    edited = copy.deepcopy(record)
    window = edited["observations"]["minion_window"]
    window["per_actor_timelines"] = {
        str(rename(int(key))): entry
        for key, entry in window["per_actor_timelines"].items()}
    for entry in window["per_actor_timelines"].values():
        episode = entry.get("episode")
        if not isinstance(episode, dict):
            continue
        for field in ("opponents", "unaccounted_opponents"):
            if episode.get(field):
                episode[field] = sorted(rename(eid) for eid in episode[field])
        closure = episode.get("opponent_closure")
        if isinstance(closure, dict):
            episode["opponent_closure"] = {
                str(rename(int(eid))): claim for eid, claim in closure.items()}
    for log, fields in (("combat_log", ("victim", "attacker")),
                        ("structure_log", ("structure", "attacker")),
                        ("death_log", ("victim", "killer")),
                        ("move_log", ("owner",))):
        for entry in window[log]:
            for field in fields:
                if field in entry:
                    entry[field] = rename(entry[field])
    # every REMAINING reference — the reason strings the writer wrote around an
    # eid — is renamed in the serialized text: a bare 4-digit token is an
    # identity, digits inside a longer number or a fraction are not
    text = json.dumps(edited)
    for old, new in mapping.items():
        text = re.sub(rf"(?<![\d.]){old}(?![\d.])", str(new), text)
    edited = json.loads(text)
    window = edited["observations"]["minion_window"]
    edited["observed"] = window
    # the payload BYTES are identities too: they are rebuilt from the renamed
    # values, never text-substituted
    for entry in window["combat_log"]:
        entry["payload"] = build_damage(entry["victim"], entry["attacker"],
                                        entry["delta"])
    for entry in window["structure_log"]:
        entry["payload"] = build_damage(entry["structure"], entry["attacker"],
                                        entry["delta"])
    for entry in window["death_log"]:
        entry["payload"] = build_entity_death(entry["victim"], entry["killer"])
    return edited


def shift_record_clock(record: dict, delta: float) -> dict:
    """The same record on a different clock: every instant moved by ``delta``.

    The relative structure of the observation is untouched (the frame, the
    census schedule and the order of every event keep their offsets), so the
    claim is the same claim — which is exactly what a contract that compares
    the recomputed outcome instead of the wall clock has to accept. Every epoch
    token is shifted in the serialized text, so the writer's own saved episode
    claims and the instants embedded in its reason strings move with the
    evidence they were derived from. ``delta`` should be a whole number of
    seconds: the shift is then exact at every decimal precision the record
    renders.
    """
    assert not delta % 1, "use a whole-second delta: the shift must be exact"

    def shifted(match):
        token = match.group()
        decimals = len(token.partition(".")[2])
        return f"{float(token) + delta:.{decimals}f}"

    edited = json.loads(_EPOCH_TOKEN.sub(shifted, json.dumps(record)))
    window = edited["observations"]["minion_window"]
    edited["observed"] = window
    return edited


def shift_census_frame(record: dict, index: int, delta: float) -> dict:
    """The same record with ONE census frame moved ``delta`` seconds later.

    The frame's own instant moves and every census point that was stamped at
    that instant moves with it — exactly how the parent's nonuniform witness
    was built — so positions, hp and presence, and every outcome derived from
    them, are untouched: nothing but the SAMPLING schedule changes.
    """
    edited = copy.deepcopy(record)
    window = edited["observations"]["minion_window"]
    edited["observed"] = window
    old_instant = window["census_instants"][index]
    window["census_instants"][index] = old_instant + delta
    for entry in window["per_actor_timelines"].values():
        entry["points"] = [
            [point[0] + delta if point[0] == old_instant else point[0]]
            + list(point[1:]) for point in entry["points"]]
    return edited


class TestMinionPairComparison(unittest.TestCase):
    """Checkpoint 13: the minion pair contract through the PUBLIC compare-pair
    CLI (``--mode compare-pair``), one entry point, dispatched by the scenario
    each record declares.

    The positive is two INDEPENDENTLY produced, unedited writer records of the
    accepted lane, serialized to disk and judged by the CLI. The fresh-session
    identities the contract normalizes demonstrably differ between them (the
    fake server assigns a fresh pid/startup per trial, the window clock is wall
    clock and each trial owns its qa directory), so a controlled pair here is
    evidence that the contract normalizes exactly what it says it does.

    Every negative changes ONE thing: a member that is not accepted on its own,
    a mixed scenario, a semantic provenance or config difference, a divergent
    recomputed outcome (counts, damage totals, cohort/structure sequence), a
    wrong chronology, and two members that carry no actor mapping at all.
    """

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix="halcyon-minion-pair-"))
        cls.a = run_minion_pair_lane(cls.base / "member-a", 1)
        cls.b = run_minion_pair_lane(cls.base / "member-b", 2)
        cls.positive_cli = run_compare_cli(
            write_pair_record(cls.base / "positive-a.json", cls.a),
            write_pair_record(cls.base / "positive-b.json", cls.b))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    @staticmethod
    def _window(record):
        return record["observations"]["minion_window"]

    def _cli(self, name, a, b):
        return run_compare_cli(
            write_pair_record(self.base / f"{name}-a.json", a),
            write_pair_record(self.base / f"{name}-b.json", b))

    def _assert_refused(self, name, a, b, *needles):
        code, report, _stderr = self._cli(name, a, b)
        joined = json.dumps(report.get("failures"))
        self.assertNotEqual(code, 0, f"{name} was accepted: {report}")
        self.assertFalse(report.get("controlled_pair"), name)
        for needle in needles:
            self.assertIn(needle, joined, f"{name}: {needle!r} not in {joined}")
        return report

    def _accepting(self, label, *records):
        for index, record in enumerate(records):
            verdict = sc.validate_minion_record(record)
            self.assertTrue(verdict["accepted"],
                            f"{label}[{index}]: {verdict['reasons']} "
                            f"{verdict['incomplete']}")

    def test_two_independent_writer_records_are_a_controlled_pair(self):
        a, b = self.a, self.b
        # each member is accepted ONE AT A TIME, by its own evidence
        self._accepting("positive", a, b)
        # the identities the contract normalizes really do differ here
        diagnostics_a = a["provenance"]["diagnostics"]
        diagnostics_b = b["provenance"]["diagnostics"]
        self.assertNotEqual(diagnostics_a["pid"], diagnostics_b["pid"])
        self.assertNotEqual(diagnostics_a["startup_at"],
                            diagnostics_b["startup_at"])
        self.assertNotEqual(a["provenance"]["qa_dir"], b["provenance"]["qa_dir"])
        self.assertNotEqual(self._window(a)["window_start"],
                            self._window(b)["window_start"])
        self.assertNotEqual(self._window(a)["census_instants"],
                            self._window(b)["census_instants"])
        self.assertEqual(self._window(a)["match_id"],
                         self._window(b)["match_id"],
                         "this lane's match id is constant in the fake session "
                         "— it is still normalized, never compared")

        code, report, stderr = self.positive_cli
        self.assertEqual(code, 0, f"{report} {stderr}")
        self.assertTrue(report["controlled_pair"], report["failures"])
        self.assertEqual(report["failures"], [])
        self.assertTrue(all(gate["ok"] for gate in report["gates"].values()),
                        report["gates"])
        self.assertIn("minion", report["dispatched_contract"])
        # the required equalities the report carries
        self.assertEqual(report["actor_mapping"]["mapping"],
                         {"4610": "4610", "4611": "4611"})
        self.assertEqual(report["actor_mapping"]["teams"],
                         {"4610": [1, 1], "4611": [2, 2]})
        self.assertEqual(report["outcome"]["summary"]["A"],
                         report["outcome"]["summary"]["B"])
        self.assertEqual(report["outcome"]["stage_status"]["A"],
                         report["outcome"]["stage_status"]["B"])
        self.assertEqual(report["outcome"]["combat_damage_total"][0],
                         report["outcome"]["combat_damage_total"][1])
        self.assertEqual(report["outcome"]["structure_damage_total"][0],
                         report["outcome"]["structure_damage_total"][1])
        self.assertEqual(report["outcome"]["combat_damage_by_actor"]["A"],
                         report["outcome"]["combat_damage_by_actor"]["B"])
        self.assertEqual(report["observation"]["presence"]["A"],
                         report["observation"]["presence"]["B"])
        self.assertEqual(report["chronology"]["merged_order"]["A"],
                         report["chronology"]["merged_order"]["B"])
        # the wall-clock values are REPORTED, never required, and each record's
        # own origin is recorded
        self.assertNotEqual(report["measured_time"]["A"]["origin"],
                            report["measured_time"]["B"]["origin"])
        self.assertFalse(report["measured_time"]["required_equal"])
        self.assertTrue(report["measured_time"]["A"]["census_frame_offsets"])
        # the absolute instants differ (two independent runs, seconds apart):
        # only the OFFSET from each record's own origin is reported, and even
        # that is not required to be equal
        raw_a = self._window(a)["death_log"][0]["time"]
        raw_b = self._window(b)["death_log"][0]["time"]
        self.assertNotEqual(raw_a, raw_b)
        for side in ("A", "B"):
            offsets = report["measured_time"][side]["episode_instant_offsets"]
            self.assertLess(offsets["4610"]["engagement_end"],
                            self._window(a)["window_end"]
                            - self._window(a)["window_start"])
            self.assertIn("4610", report["measured_time"][side]
                          ["census_point_offset_spans"])
        # slot ownership is explicitly withheld, not assumed
        self.assertEqual(report["slot_ownership"]["status"], "UNVERIFIED")
        self.assertTrue(any("ownership" in claim
                            for claim in report["not_claimed"]))
        self.assertTrue(any("absolute clock origin" in claim
                            for claim in report["not_claimed"]))
        # the ELAPSED-TIME contract is a comparison, not a drop: both records
        # carry the simulation clock of every census frame and both clocks were
        # normalised to their own first frame before being compared
        elapsed = report["elapsed_time"]
        self.assertEqual(elapsed["status"], "VERIFIED")
        self.assertTrue(report["gates"]["elapsed_time"]["ok"])
        self.assertEqual(elapsed["sim_clock"]["A"],
                         elapsed["sim_clock"]["B"])
        self.assertEqual(elapsed["sim_clock"]["A"][0], 0.0,
                         "the sim clock is normalised to the record's own first "
                         "frame, so its own origin is 0 by construction")
        self.assertEqual(self._window(a)["census_sim_ticks"],
                         self._window(b)["census_sim_ticks"])
        self.assertNotEqual(elapsed["sim_clock"]["A"], [0.0] * len(
            elapsed["sim_clock"]["A"]), "the window really advanced the world")
        self.assertEqual(elapsed["sampling"]["margin_s"],
                         sc.FIXTURE_SAMPLING_MARGIN_S)
        offsets_a = elapsed["sampling"]["frame_offsets"]["A"]
        offsets_b = elapsed["sampling"]["frame_offsets"]["B"]
        self.assertEqual(len(offsets_a), len(offsets_b))
        for index, (offset_a, offset_b) in enumerate(zip(offsets_a,
                                                        offsets_b)):
            self.assertLessEqual(abs(offset_a - offset_b),
                                 sc.FIXTURE_SAMPLING_MARGIN_S, f"frame {index}")
        for side in ("A", "B"):
            self.assertLessEqual(
                elapsed["sampling"]["declared_schedule"][side]
                ["max_deviation_s"], sc.FIXTURE_SAMPLING_MARGIN_S,
                "the sampler stayed inside its own declared cadence")
        # ... and the scope of that margin is stated, never implied: it is a
        # FIXTURE calibration, reported beside the verdict, and the live claim
        # it cannot support is reported UNVERIFIED in every verdict
        calibration = elapsed["fixture_calibration"]
        self.assertEqual(calibration["label"], "fixture")
        self.assertEqual(calibration["productions"],
                         sc.FIXTURE_CALIBRATION_PRODUCTIONS)
        self.assertEqual(calibration["measured_worst_deviation_s"],
                         sc.FIXTURE_CALIBRATION_WORST_DEVIATION_S)
        self.assertIn("NOT production measurement uncertainty",
                      calibration["scope"])
        self.assertEqual(elapsed["sim_clock"]["comparison"][:5], "EXACT")
        self.assertIn("exactly", elapsed["sim_clock"]["required_equal"])
        self.assertIn("no live measurement establishes any non-zero allowance",
                      elapsed["sim_clock"]["required_equal"])
        live = elapsed["live_sampling_equivalence"]
        self.assertEqual(live["status"], "UNVERIFIED")
        self.assertIn("not the same event", live["why"])
        self.assertEqual(live["measured_offline"]["requests"],
                         sc.OFFLINE_QA_BRACKET_REQUESTS)
        self.assertEqual(live["measured_offline"]["receipt_minus_service_max_s"],
                         sc.OFFLINE_QA_BRACKET_MAX_S)
        self.assertIn("NEVER used as a margin", live["measured_offline"]["scope"])
        self.assertTrue(any("census_sim_ticks" in item
                            for item in live["missing_evidence"]))
        self.assertNotIn("sampling_unverified", elapsed,
                         "nothing here was out of margin")
        # the raw instants and sim times are still carried and reported
        self.assertTrue(self._window(a)["census_sim_times"])
        self.assertTrue(report["measured_time"]["A"]["census_frame_offsets"])

    def test_a_member_that_is_not_accepted_cannot_pass(self):
        """An honest incomplete trial is coherent but is NOT an accepted
        observation, so the pair is refused on that member — the resolution
        says which member and why."""
        base = self.base / "no-closure"
        rows = [{"eid": 4610, "team": 1, "x": 10.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True},
                {"eid": 4611, "team": 2, "x": 20.0, "y": 2.0, "hp": 300.0,
                 "max_hp": 300.0, "alive": True}]

        def script(harness, sample, rows):
            script_lane(harness, sample, rows, kill_at=None, structure_at=5,
                        march=(3, 4))

        result, harness = run_minion_trial(
            base, 1, rows=rows, structures=[MINION_LANE_STRUCTURE],
            script=script, window=8.0)
        try:
            incomplete = json.loads(Path(result["result_path"])
                                    .read_text(encoding="utf-8"))
        finally:
            harness.cleanup()
        verdict = sc.validate_minion_record(incomplete)
        self.assertTrue(verdict["valid"], verdict["reasons"])
        self.assertFalse(verdict["accepted"])
        report = self._assert_refused("incomplete-member", self.a, incomplete,
                                      "record_B", "not PASS")
        self.assertFalse(report["gates"]["record_B"]["ok"])
        self.assertTrue(report["gates"]["record_A"]["ok"])

    def test_a_mixed_scenario_pair_is_refused(self):
        """One minion record and one cast record is never a pair, in either
        order, and the dispatch follows the DECLARED scenario."""
        cast = {"scenario": "skye-b", "schema_version": sc.PAIR_SCHEMA_VERSION}
        self._assert_refused("mixed-a-minion", self.a, cast,
                             "record B declares scenario 'skye-b'")
        self._assert_refused("mixed-b-minion", cast, self.a,
                             "record A declares scenario 'skye-b'")
        self.assertEqual(sc.compare_pair(cast, cast)["dispatched_contract"],
                         "cast trial pair")
        self.assertEqual(sc.compare_pair(cast, self.a)["dispatched_contract"],
                         "minion observation pair")
        self.assertEqual(sc.compare_pair(self.a, cast)["dispatched_contract"],
                         "minion observation pair")

    def test_semantic_provenance_or_config_difference_is_refused(self):
        """Same scenario, both members accepted, but the loaded tape, the
        semantic config, the loaded source or the declared observation
        duration differ: not the same observation."""
        def other_tape(harness):
            mutate_diagnostics(harness, tape_loaded={"records": 1457,
                                                     "sha256": "c" * 64})

        def other_env(harness):
            mutate_diagnostics(harness, env={"HALCYON_NO_BOTS": "1",
                                             "HALCYON_NO_WAVE": "1"})

        def other_source(harness):
            mutate_diagnostics(harness, source_startup_digest="1" * 64,
                               source_current_digest="1" * 64)

        cases = (
            ("other-tape", dict(prepare=other_tape),
             "provenance.tape_loaded differs"),
            ("other-env", dict(prepare=other_env),
             "provenance.env_config differs"),
            ("other-source", dict(prepare=other_source),
             "provenance.source_current_digest differs"),
            ("other-window", dict(window=6.0), "declared durations differ"))
        for name, kwargs, needle in cases:
            with self.subTest(name):
                member = run_minion_pair_lane(self.base / name, 7, **kwargs)
                self._accepting(name, member)
                self._assert_refused(name, self.a, member, needle)

    def test_a_divergent_recomputed_outcome_is_refused(self):
        """Both members accepted, both fully passing on their own, and the
        recomputed outcome still differs: counts, exact damage totals, and the
        cohort/structure sequence the survivor's claim belongs to."""
        extra = (4610, 4611, -10.0)
        with self.subTest("event count"):
            member = run_minion_pair_lane(self.base / "divergent-count", 7,
                                          extra_combat=extra)
            self._accepting("divergent-count", member)
            self._assert_refused("divergent-count", self.a, member,
                                 "minion_vs_minion_events")
        with self.subTest("exact damage total"):
            member_a = run_minion_pair_lane(self.base / "divergent-damage-a", 7,
                                            extra_combat=extra)
            member_b = run_minion_pair_lane(self.base / "divergent-damage-b", 8,
                                            extra_combat=(4610, 4611, -20.0))
            self._accepting("divergent-damage", member_a, member_b)
            report = self._assert_refused("divergent-damage", member_a, member_b,
                                          "damage_totals",
                                          "combat_damage_total")
            self.assertTrue(report["gates"]["outcome_counts"]["ok"],
                            "the event COUNTS are equal here: the only thing "
                            "that diverges is the exact total")
            self.assertTrue(report["gates"]["stages"]["ok"])
        with self.subTest("cohort and structure sequence"):
            member = run_minion_pair_lane(self.base / "divergent-cohort", 7,
                                          swap_roles=True)
            self._accepting("divergent-cohort", member)
            report = self._assert_refused("divergent-cohort", self.a, member,
                                          "episodes", "chronology")
            self.assertTrue(report["gates"]["outcome_counts"]["ok"],
                            "the counts are equal; the COHORT the sequence "
                            "belongs to is what diverges")
            self.assertEqual(report["chronology"]["structure_sequence"]["A"],
                             [[3539, 4610]])
            self.assertEqual(report["chronology"]["structure_sequence"]["B"],
                             [[3540, 4611]])

    def test_a_wrong_chronology_is_refused(self):
        """Two independently produced members of the SAME lane that published
        the two combat events in the opposite order: both are accepted on their
        own evidence, every count, total, stage and episode agrees, and the
        ORDER does not — which is exactly what the pair contract refuses. The
        same refusal covers a member whose carried order contradicts its own
        instants, so the order is a claim and not a by-product of the clock."""
        extra = (4611, 4610, -10.0)
        member_a = run_minion_pair_lane(self.base / "chronology-a", 7,
                                        extra_combat=extra, extra_first=True)
        member_b = run_minion_pair_lane(self.base / "chronology-b", 8,
                                        extra_combat=extra, extra_first=False)
        self._accepting("chronology", member_a, member_b)
        self.assertEqual(self._window(member_a)["combat_log"][0]["victim"],
                         4611)
        self.assertEqual(self._window(member_b)["combat_log"][0]["victim"],
                         4610)
        report = self._assert_refused("chronology", member_a, member_b,
                                      "chronology", "event_chronology")
        self.assertTrue(report["gates"]["outcome_counts"]["ok"])
        self.assertTrue(report["gates"]["damage_totals"]["ok"])
        self.assertTrue(report["gates"]["episodes"]["ok"])
        self.assertTrue(report["gates"]["stages"]["ok"])
        self.assertEqual(report["chronology"]["combat_sequence"]["A"],
                         [[4611, 4610], [4610, 4611]])
        self.assertEqual(report["chronology"]["combat_sequence"]["B"],
                         [[4610, 4611], [4611, 4610]])

        with self.subTest("carried order contradicts its own instants"):
            swapped = copy.deepcopy(member_b)
            window = swapped["observations"]["minion_window"]
            swapped["observed"] = window
            first, second = window["combat_log"][0], window["combat_log"][1]
            first["time"], second["time"] = second["time"], first["time"]
            self._accepting("contradiction", swapped)
            self._assert_refused("contradiction", member_a, swapped,
                                 "chronology", "combat_sequence")

    def test_the_carried_claim_is_compared_never_the_clock(self):
        """The boundary stated positively: a member whose whole clock moved by
        3600 s carries the same claim (same frame offsets, same carried order,
        same recomputed outcome) and IS the same observation, while every
        absolute instant it carries differs. The instants are reported per
        record with the offset from that record's own origin — that is the whole
        role they play."""
        shifted = shift_record_clock(self.b, 3600.0)
        self._accepting("shifted-clock", self.a, shifted)
        self.assertEqual(self._window(shifted)["window_start"],
                         self._window(self.b)["window_start"] + 3600.0)
        self.assertNotEqual(self._window(self.a)["window_start"],
                            self._window(shifted)["window_start"])
        self.assertNotEqual(self._window(self.a)["census_instants"],
                            self._window(shifted)["census_instants"])

        def frame_offsets(record):
            window = self._window(record)
            return [round(instant - window["window_start"], 3)
                    for instant in window["census_instants"]]

        self.assertEqual(frame_offsets(shifted), frame_offsets(self.b))
        code, report, stderr = self._cli("shifted-clock", self.a, shifted)
        self.assertEqual(code, 0, f"{report} {stderr}")
        self.assertTrue(report["controlled_pair"], report["failures"])
        self.assertEqual(report["chronology"]["merged_order"]["A"],
                         report["chronology"]["merged_order"]["B"])
        self.assertEqual(report["gates"]["provenance"]["ok"], True)
        self.assertEqual(report["gates"]["declared_observation"]["ok"], True)
        self.assertNotEqual(report["measured_time"]["A"]["origin"],
                            report["measured_time"]["B"]["origin"])
        self.assertEqual(report["measured_time"]["B"]["origin"]
                         - self._window(self.b)["window_start"], 3600.0)

    def test_records_without_a_carried_actor_mapping_are_refused(self):
        """Two records that carry no correspondence between their actors are
        refused as unverified — never sorted into an invented equivalence."""
        renamed = relabel_minion_actors(self.a, {4610: 4710, 4611: 4711})
        self._accepting("no-mapping", renamed)
        report = self._assert_refused("no-mapping", self.a, renamed,
                                      "actor_mapping",
                                      "no carried actor mapping")
        self.assertEqual(report["actor_mapping"]["mapping"], {})
        self.assertEqual(report["actor_mapping"]["tracked_a"], [4610, 4611])
        self.assertEqual(report["actor_mapping"]["tracked_b"], [4710, 4711])
        self.assertIn("4710", report["boundary"])
        self.assertIn("refuses the pair as unverified", report["boundary"])

    # -- the elapsed-time contract -----------------------------------------

    @staticmethod
    def _strip_census_clock(record):
        """The same accepted record as it was written BEFORE the census clock
        was carried: every other field untouched, the clock keys removed."""
        edited = copy.deepcopy(record)
        window = edited["observations"]["minion_window"]
        edited["observed"] = window
        window.pop("census_sim_ticks", None)
        window.pop("census_sim_times", None)
        return edited

    @staticmethod
    def _with_malformed_clock(record, value="bad"):
        """The parent review's clock-type witness, exactly: ONE entry of the
        carried census clock replaced, in BOTH serialized copies of the
        window."""
        edited = copy.deepcopy(record)
        window = edited["observations"]["minion_window"]
        edited["observed"] = window
        window["census_sim_times"] = list(window["census_sim_times"])
        window["census_sim_times"][1] = value
        return edited

    def test_a_malformed_census_clock_member_is_refused_without_a_traceback(self):
        """The parent review's witness through the PUBLIC CLI: one census clock
        entry replaced by a string/list/object/bool, in both serialized copies.
        The pair must be refused with a structured reason naming the member and
        the frame, with NO traceback and no error output — the defect this case
        exists for was a TypeError raised by a loop that subtracted the value
        the type gate had already refused."""
        for value in ("bad", ["bad"], {"time": 1.0}, True):
            with self.subTest(value=repr(value)):
                broken = self._with_malformed_clock(self.b, value)
                code, report, stderr = self._cli(
                    f"clock-type-{abs(hash(repr(value))) % 100000}", self.a,
                    broken)
                self.assertEqual(code, 1, f"{value!r} was not refused")
                self.assertEqual(stderr.strip(), "",
                                 "the CLI must not raise or print an error")
                self.assertFalse(report["controlled_pair"])
                self.assertFalse(report["gates"]["record_B"]["ok"])
                self.assertIn("census frame 1 simulation clock",
                              report["gates"]["record_B"]["detail"])
                self.assertIn("is not an integer tick with a finite time",
                              report["gates"]["record_B"]["detail"])
                self.assertTrue(report["gates"]["record_A"]["ok"],
                                "the untouched member is still accepted on its "
                                "own evidence")

    def test_a_non_finite_clock_entry_cannot_reach_the_comparator_at_all(self):
        """Non-finite entries are refused EARLIER than the record contract: the
        public CLI loads result JSON strictly and exits 2 with a structured
        report naming the constant, so a NaN or an Infinity never enters the
        comparator. Both boundaries are structured; neither raises."""
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=repr(value)):
                broken = self._with_malformed_clock(self.b, value)
                code, report, stderr = self._cli(
                    f"clock-nonfinite-{abs(hash(repr(value))) % 100000}",
                    self.a, broken)
                self.assertEqual(code, 2, f"{value!r}: {report} {stderr}")
                self.assertEqual(report, {},
                                 "no comparator report is produced: the pair "
                                 "never reached the contract")
                payload = json.loads(stderr)
                self.assertIn("non-finite JSON constant", payload["error"])
                self.assertIn("malformed result JSON", payload["error"])
                self.assertNotIn("Traceback", stderr)

    def test_a_member_with_a_malformed_endpoint_clock_is_refused(self):
        """The trial endpoint the census clock is placed inside is typed too:
        a non-finite endpoint time is a structured refusal, not a crash."""
        def mutate(record):
            edited = copy.deepcopy(record)
            window = edited["observations"]["minion_window"]
            edited["observed"] = window
            edited["provenance"]["diagnostics_end"]["time"] = "later"
            return edited

        report = self._assert_refused("endpoint-clock", self.a, mutate(self.b),
                                      "record_B",
                                      "provenance.diagnostics_end: time",
                                      "is not a finite number")
        self.assertIn("is not a finite number",
                      report["gates"]["record_B"]["detail"])

    def test_a_pair_without_the_carried_simulation_clock_is_unverified(self):
        """The elapsed gameplay time is not evidenced by a record that carries
        no census clock, so the pair is refused as UNVERIFIED naming the
        missing field — and each member is STILL an accepted single record,
        which is the whole distinction between one record's status and two
        records' equivalence. Timing is never dropped to make a pair pass."""
        dry_a = self._strip_census_clock(self.a)
        dry_b = self._strip_census_clock(self.b)
        self._accepting("no-clock", dry_a, dry_b)
        for record in (dry_a, dry_b):
            verdict = sc.validate_minion_record(record)
            self.assertEqual(verdict["reasons"], [])
            self.assertEqual(verdict["incomplete"], [],
                             "carrying no census clock is not incoherence and "
                             "does not make a record incomplete")
            self.assertIsNone(verdict["checks"]["census_sim_clock"],
                              "the check reports not-carried, not a pass")
            self.assertFalse(verdict["recomputed"]["sim_clock"]["carried"])
        report = self._assert_refused("no-clock", dry_a, dry_b, "elapsed_time",
                                      "UNVERIFIED",
                                      "census_sim_ticks")
        elapsed = report["elapsed_time"]
        self.assertEqual(elapsed["status"], "UNVERIFIED")
        self.assertIsNone(elapsed["sim_clock"]["A"])
        self.assertIsNone(elapsed["sim_clock"]["B"])
        self.assertEqual(elapsed["sim_clock"]["carried"],
                         {"A": False, "B": False})
        self.assertIn("census_sim_times", elapsed["missing_evidence"])
        self.assertEqual(report["gates"]["elapsed_time"]["ok"], False)
        # every other gate really is satisfied here: this refusal is about the
        # timing evidence and nothing else
        for gate in ("record_A", "record_B", "provenance", "profile",
                     "declared_observation", "actor_mapping", "evidence",
                     "observation", "outcome_counts", "stages",
                     "damage_totals", "episodes", "chronology"):
            self.assertTrue(report["gates"][gate]["ok"], gate)
        self.assertFalse(report["controlled_pair"])

    def test_one_member_without_the_clock_is_unverified_too(self):
        """The refusal is a property of the PAIR: one member carrying the
        clock and the other not is still unverified, and the report names
        exactly which member is missing it."""
        report = self._assert_refused("half-clock", self.a,
                                      self._strip_census_clock(self.b),
                                      "elapsed_time", "UNVERIFIED",
                                      "census_sim_ticks")
        self.assertEqual(report["elapsed_time"]["status"], "UNVERIFIED")
        self.assertEqual(report["elapsed_time"]["sim_clock"]["carried"],
                         {"A": True, "B": False})
        self.assertIn("record B", report["elapsed_time"]["unverified_detail"])
        self.assertTrue(report["gates"]["record_B"]["ok"],
                        "the member without the clock is still accepted on "
                        "its own: only the pair's timing claim is missing")

    def test_a_nonuniform_frame_shift_is_refused(self):
        """The parent's witness, on records that carry the clock: frame 3 is
        moved +0.8010764s in ONE member, with the census points that were
        stamped at that instant moved with it (positions and outcome
        unchanged, exactly as the witness was built). Every other contract
        still holds — the pair is refused for the elapsed timing alone, and
        because the margin the deviation exceeds is calibrated on the FIXTURE
        path only, the refusal is reported as NOT ESTABLISHED (UNVERIFIED) with
        the deviation named — never as a violation of a production bound,
        which the offline real-path measurement (0.4515s at the same cadence)
        shows this contract cannot support."""
        shift = 0.8010764
        shifted = shift_census_frame(self.b, 3, shift)
        self._accepting("nonuniform", shifted)
        report = self._assert_refused("nonuniform", self.a, shifted,
                                      "elapsed_time",
                                      "margin calibrated on the fixture path")
        self.assertEqual(report["elapsed_time"]["status"], "UNVERIFIED")
        self.assertTrue(report["gates"]["outcome_counts"]["ok"])
        self.assertTrue(report["gates"]["stages"]["ok"])
        self.assertTrue(report["gates"]["episodes"]["ok"])
        self.assertTrue(report["gates"]["chronology"]["ok"])
        joined = " | ".join(report["failures"])
        self.assertIn("census frame 3", joined)
        self.assertIn("beyond the 0.100s margin calibrated on the fixture path",
                      joined)
        self.assertIn("record B census frame 3 follows its predecessor by",
                      joined)
        # the deviation is carried verbatim and its boundary is stated: the
        # fixture margin does not reach a live sampler, so nothing here claims
        # that a live path could not produce it
        unverified = report["elapsed_time"]["sampling_unverified"]
        self.assertTrue(any("census frame 3" in row for row in unverified))
        self.assertIn("NOT ESTABLISHED",
                      report["elapsed_time"]["sampling_unverified_boundary"])
        self.assertIn("live_sampling_equivalence",
                      report["elapsed_time"]["sampling_unverified_boundary"])
        # the same records' SIMULATION clock was not touched, so the gameplay
        # timing claim itself still holds: the refusal is the sampler's
        self.assertEqual(report["elapsed_time"]["sim_clock"]["A"],
                         report["elapsed_time"]["sim_clock"]["B"])

    def test_a_shifted_simulation_clock_is_refused(self):
        """The other half of the same claim: the WALL clock untouched and the
        carried simulation clock of ONE member moved at a frame, so the two
        members did not observe the same elapsed gameplay time even though they
        sampled at the same real-time offsets. The move stays inside the
        record's own coherence — the frames still advance, still sit on the
        record's own tick rate and still precede the trial endpoint — so the
        record is accepted on its own and the PAIR is what refuses."""
        warped = copy.deepcopy(self.b)
        window = warped["observations"]["minion_window"]
        warped["observed"] = window
        window["census_sim_ticks"] = list(window["census_sim_ticks"])
        window["census_sim_times"] = list(window["census_sim_times"])
        window["census_sim_ticks"][1] += 10        # +0.5s of gameplay, frame 1
        window["census_sim_times"][1] += 0.5
        self._accepting("sim-warp", warped)
        report = self._assert_refused("sim-warp", self.a, warped,
                                      "elapsed_time", "GAMEPLAY",
                                      "elapsed SIMULATION time at census "
                                      "frame 1")
        self.assertEqual(report["elapsed_time"]["status"], "FAILED",
                         "the carried clocks themselves differ, so the elapsed "
                         "gameplay time is not the same: no margin is involved "
                         "in saying so")
        self.assertIn("no tolerance is applied",
                      report["elapsed_time"]["sim_clock"]["comparison"])
        self.assertEqual(report["elapsed_time"]["sim_clock"]["B"][0], 0.0,
                         "the series is normalised to its own first frame, so "
                         "the difference is between frame 1 and later")
        offsets = report["elapsed_time"]["sampling"]["frame_offsets"]
        for index, (offset_a, offset_b) in enumerate(zip(offsets["A"],
                                                        offsets["B"])):
            self.assertLessEqual(abs(offset_a - offset_b),
                                 sc.FIXTURE_SAMPLING_MARGIN_S,
                                 f"frame {index}: the real-time offsets are the "
                                 "untouched ones")
        self.assertNotIn("sampling_unverified", report["elapsed_time"],
                         "the sampling schedule is untouched: only the carried "
                         "simulation clock diverges")
        joined = " | ".join(report["failures"])
        self.assertNotIn("real-time offset differs", joined)

    def test_an_event_spacing_change_beyond_the_margin_is_refused(self):
        """An event published LATER inside its own window than in the other
        member: same events, same order, same counts, totals and stages — the
        spacing is what diverges, so the pair is refused and the elapsed_time
        report names the event index, as a sampling-schedule deviation beyond
        the FIXTURE-calibrated margin (UNVERIFIED: not established), never as a
        failure of the exact simulation-clock comparison, which still passes
        here. The member's carried EPISODE claims move with the instants they
        are derived from, so the refusal is reported by more than one gate;
        that is what the evidence says, not a redundancy to hide."""
        member = run_minion_pair_lane(self.base / "event-spacing", 7,
                                      event_delay=0.9)
        self._accepting("event-spacing", member)
        # the frames and the simulation clock are exactly where they were: the
        # delayed publication is the only difference
        self.assertEqual(self._window(member)["census_sim_ticks"],
                         self._window(self.b)["census_sim_ticks"])
        offsets_member = [instant - self._window(member)["window_start"]
                          for instant in self._window(member)
                          ["census_instants"]]
        offsets_b = [instant - self._window(self.b)["window_start"]
                     for instant in self._window(self.b)["census_instants"]]
        for index, (offset_member, offset_b) in enumerate(zip(offsets_member,
                                                             offsets_b)):
            self.assertLessEqual(abs(offset_member - offset_b),
                                 sc.FIXTURE_SAMPLING_MARGIN_S,
                                 f"frame {index}: the delay moved no census "
                                 "sample")
        report = self._assert_refused("event-spacing", self.b, member,
                                      "elapsed_time", "beyond the",
                                      "margin calibrated on the fixture path")
        elapsed = report["elapsed_time"]
        self.assertEqual(elapsed["status"], "UNVERIFIED")
        self.assertEqual(elapsed["sim_clock"]["A"], elapsed["sim_clock"]["B"],
                         "the carried simulation clock is untouched and is "
                         "compared exactly: it does not diverge here")
        self.assertTrue(any("event " in row
                            for row in elapsed["sampling_unverified"]))
        joined = " | ".join(report["failures"])
        self.assertIn("event ", joined)   # the index-carrying event report
        self.assertTrue(report["gates"]["chronology"]["ok"],
                        "the event ORDER is unchanged: only the spacing moved")
        self.assertTrue(report["gates"]["outcome_counts"]["ok"])
        self.assertTrue(report["gates"]["damage_totals"]["ok"])
        self.assertTrue(report["gates"]["stages"]["ok"])

    def test_a_uniform_simulation_clock_shift_is_the_same_observation(self):
        """The positive half of the sim-clock contract: a member produced by a
        world that had been running an hour longer — a different absolute
        clock origin with the same per-frame cadence, every receipt and frame
        moved with it — is the SAME elapsed timing, so the pair stays
        controlled. The origin is normalised away; the elapsed series is not."""
        rebased = run_minion_pair_lane(self.base / "sim-rebased", 7,
                                       clock_offset=72000)
        self._accepting("sim-rebased", rebased)
        self.assertAlmostEqual(
            self._window(rebased)["census_sim_times"][0]
            - self._window(self.b)["census_sim_times"][0], 3600.0, places=6)
        self.assertNotEqual(self._window(self.a)["census_sim_times"][0],
                            self._window(rebased)["census_sim_times"][0])
        code, report, stderr = self._cli("sim-rebased", self.a, rebased)
        self.assertEqual(code, 0, f"{report} {stderr}")
        self.assertTrue(report["controlled_pair"], report["failures"])
        self.assertEqual(report["elapsed_time"]["status"], "VERIFIED")
        self.assertEqual(report["elapsed_time"]["sim_clock"]["A"],
                         report["elapsed_time"]["sim_clock"]["B"],
                         "the elapsed series is identical although the two "
                         "worlds started an hour apart")
        self.assertEqual(report["elapsed_time"]["live_sampling_equivalence"]
                         ["status"], "UNVERIFIED",
                         "a VERIFIED verdict states its own scope and does not "
                         "claim the live equivalence beside it")
        self.assertEqual(self._window(rebased)["census_sim_ticks"][0]
                         - self._window(self.b)["census_sim_ticks"][0],
                         72000, "the two members really are on different "
                         "absolute clock origins")


if __name__ == "__main__":
    unittest.main()

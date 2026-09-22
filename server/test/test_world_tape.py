"""world_tape loader — format, trim, and failure modes."""
import os
import hashlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import match_server, roster, world_tape


def _body(op: int, payload: bytes = b"") -> bytes:
    return struct.pack(">H", op) + payload


def _record(t_ms: int, body: bytes) -> bytes:
    return struct.pack(">IH", t_ms, len(body)) + body


class _TapeCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".bin")
        os.close(fd)

    def tearDown(self):
        os.unlink(self.path)

    def _write(self, data: bytes):
        with open(self.path, "wb") as fh:
            fh.write(data)


class TestLoadTape(_TapeCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(world_tape.load_tape(self.path + ".absent"))

    def test_round_trip_and_monotone_times(self):
        self._write(_record(0, _body(1087, b"ab"))
                    + _record(50, _body(1053, b"c"))
                    + _record(50, _body(1010, b"dd")))
        frames = world_tape.load_tape(self.path)
        self.assertEqual([(t, b) for t, b in frames],
                         [(0, _body(1087, b"ab")),
                          (50, _body(1053, b"c")),
                          (50, _body(1010, b"dd"))])

    def test_skip_until_op_trims_prefix(self):
        self._write(_record(0, _body(1135, b"x"))
                    + _record(10, _body(1006, b"y"))
                    + _record(20, _body(1087, b"z"))
                    + _record(30, _body(1053, b"w")))
        frames = world_tape.load_tape(self.path, skip_until_op=1087)
        self.assertEqual([struct.unpack_from(">H", b)[0] for _, b in frames],
                         [1087, 1053])

    def test_skip_until_op_without_match_empties_tape(self):
        self._write(_record(0, _body(1135)))
        self.assertEqual(world_tape.load_tape(self.path, skip_until_op=1087), [])

    def test_truncated_record_raises(self):
        self._write(_record(0, _body(1087, b"abcd"))[:-2])
        with self.assertRaises(ValueError):
            world_tape.load_tape(self.path)

    def test_time_regression_raises(self):
        self._write(_record(100, _body(1053)) + _record(50, _body(1053)))
        with self.assertRaises(ValueError):
            world_tape.load_tape(self.path)


class TestBootstrapCompletion(_TapeCase):
    def setUp(self):
        super().setUp()
        # Synthetic entity state, never a proprietary replay fixture. Substitute
        # only its fingerprint; wire ordering/timing and session integration run
        # normally. The optional corpus gate checks the production fingerprint.
        self.original = [_record(0, _body(1087, b"synthetic entity")),
                         _record(12478, _body(1053, b"synthetic stat"))]
        self.data = b"".join(self.original)
        self._write(self.data)
        fingerprint = hashlib.sha256(self.data).hexdigest()
        self.enterContext(patch.object(world_tape, "_TRUNCATED_BOOTSTRAP_SHA256", fingerprint))

    def test_completion_preserves_prefix_and_exact_cancel_contract(self):
        frames = world_tape.load_tape(self.path, skip_until_op=1087)
        before = list(frames)
        completed = world_tape.complete_corpus_bootstrap(frames)
        self.assertEqual(frames, before)
        self.assertEqual(completed[:len(frames)], before)
        self.assertEqual(completed[len(frames):], [
            (16672, _body(1093, struct.pack(">II", eid, instance) + bytes(6)))
            for eid, instance in ((1500, 2024), (1515, 2021), (1516, 2018),
                                  (1517, 2015), (1518, 2012), (1519, 2009))
        ])
        self.assertEqual(world_tape.complete_corpus_bootstrap(completed), completed)

    def test_other_tapes_and_timestamps_do_not_cancel_unrelated_instances(self):
        frames = world_tape.load_tape(self.path)
        for other in ([], frames[:-1], [(1, frames[0][1]), frames[1]],
                      frames + [(17000, _body(1116))]):
            with self.subTest(other=other):
                self.assertEqual(world_tape.complete_corpus_bootstrap(other), other)

    def test_session_loads_repaired_tape_once_without_rewriting_file(self):
        players = roster.default_solo_bots("test-session", "00000000-1111-4222-8333-444455556666")
        stream = match_server.SnapshotStream(None, players,
            "00000000-1111-4222-8333-444455556666", lambda op, p: None, log=lambda *a: None)
        with patch.object(match_server, "WORLD_TAPE_PATH", self.path), patch.dict(os.environ):
            os.environ.pop("HALCYON_NO_TAPE", None)
            stream._load_tape()
            self.assertEqual(len(stream.tape_frames), 8)
            self.assertEqual(stream.tape_frames[-1][0], 16672)
            self.assertFalse(stream.tape_done)
            stream._load_tape()
            self.assertEqual(len(stream.tape_frames), 8)
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), self.data)


class TestAuthoritativeBootstrap(_TapeCase):
    def test_archived_turret_barriers_do_not_create_unmodeled_native_damage_pools(self):
        grant = lambda eid, value=100, kind=4: _body(1053,
            struct.pack(">IfB", eid, value, kind) + b"\x00\x01\x00\x00\x00")
        times = (9934, 10443, 10955, 11468, 11970, 12478)
        turrets = (3539, 3540, 3541, 3542, 3543, 3545, 3546, 3547, 3548, 3549)
        keep = [(0, _body(1087, b"allocation")), (9934, grant(1500)),
                (9934, grant(3544)), (9934, grant(3550)),
                (9934, grant(3539, 99)), (9934, grant(3539, kind=0)),
                (9935, grant(3539))]
        frames = sorted(keep + [(at, grant(eid)) for at in times for eid in turrets],
                        key=lambda record: record[0])
        original = list(frames)
        fingerprint = hashlib.sha256(b"".join(_record(t, b) for t, b in frames)).hexdigest()
        with patch.object(world_tape, "_TRUNCATED_BOOTSTRAP_SHA256", fingerprint):
            completed = world_tape.complete_corpus_bootstrap(frames)
            published = world_tape.authoritative_corpus_bootstrap(completed)
            self.assertEqual(published, keep + completed[len(frames):])
            self.assertEqual(len(completed) - len(published), 60)
            self.assertEqual(frames, original)
            self.assertEqual(world_tape.authoritative_corpus_bootstrap(published), published)
        self.assertEqual(world_tape.authoritative_corpus_bootstrap(completed), completed)

    def test_archived_handicap_does_not_change_native_combat_attributes(self):
        handicap = lambda eid: _body(1052, struct.pack(">IIfBB", eid, 0xffffffff, .1, 4, 2) + bytes(8))
        legitimate = _body(1052, roster.build_entity_attribute(1500, 10, 4))
        frames = [(0, _body(1087, b"allocation")),
                  *[(8517, handicap(eid)) for eid in (1500, 1516, 1515)],
                  (12478, legitimate)]
        original = list(frames)
        fingerprint = hashlib.sha256(b"".join(_record(t, b) for t, b in frames)).hexdigest()
        with patch.object(world_tape, "_TRUNCATED_BOOTSTRAP_SHA256", fingerprint):
            completed = world_tape.complete_corpus_bootstrap(frames)
            published = world_tape.authoritative_corpus_bootstrap(completed)
            self.assertEqual(published, [frames[0], frames[-1]] + completed[len(frames):])
            self.assertEqual(frames, original)
            self.assertEqual(world_tape.authoritative_corpus_bootstrap(published), published)
            self._write(b"".join(_record(t, b) for t, b in frames))
            players = roster.default_solo_bots("test-session", "00000000-1111-4222-8333-444455556666")
            stream = match_server.SnapshotStream(None, players,
                "00000000-1111-4222-8333-444455556666", lambda op, p: None, log=lambda *a: None)
            with patch.object(match_server, "WORLD_TAPE_PATH", self.path), patch.dict(os.environ):
                os.environ.pop("HALCYON_NO_TAPE", None)
                stream._load_tape()
                self.assertEqual(stream.tape_frames, published)
            self.assertEqual(world_tape.load_tape(self.path), frames)
        # Identical-looking records in unqualified tapes are not silently edited.
        self.assertEqual(world_tape.authoritative_corpus_bootstrap(completed), completed)


if __name__ == "__main__":
    unittest.main()

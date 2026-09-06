"""world_tape loader — format, trim, and failure modes."""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import world_tape


def _body(op: int, payload: bytes = b"") -> bytes:
    return struct.pack(">H", op) + payload


def _record(t_ms: int, body: bytes) -> bytes:
    return struct.pack(">IH", t_ms, len(body)) + body


class TestLoadTape(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".bin")
        os.close(fd)

    def tearDown(self):
        os.unlink(self.path)

    def _write(self, data: bytes):
        with open(self.path, "wb") as fh:
            fh.write(data)

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


if __name__ == "__main__":
    unittest.main()

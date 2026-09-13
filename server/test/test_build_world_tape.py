"""build_world_tape safety and validation tests.

The real reproduction runs against the owned corpus pcap when present; the
safety paths (destinations, exclusivity, digest distinction) always run.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "Tools"))

import build_world_tape as bwt   # noqa: E402

PCAP = Path(os.environ.get("TEMP", ".")) / "vg_max" / "vgfull.pcap"
MATCH = "b9f511e0-11cd-4cfa-ad62-dc8612b8d270"
HAVE_PCAP = PCAP.is_file()


def _run(argv):
    code = bwt.main(argv)
    return code


class TestSafetyPaths(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="halcyon-tape-test-"))

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_repo_destination_refused(self):
        dest = ROOT / "Docs" / "tape-should-not-exist.bin"
        code = _run(["--pcap", "Z:/missing.pcap", "--match-uuid", MATCH,
                     "--output", str(dest)])
        self.assertEqual(code, 2)
        self.assertFalse(dest.exists())

    def test_existing_output_never_overwritten(self):
        dest = self.base / "world_tape.bin"
        dest.write_bytes(b"operator data")
        code = _run(["--pcap", "Z:/missing.pcap", "--match-uuid", MATCH,
                     "--output", str(dest)])
        self.assertEqual(code, 2)
        self.assertEqual(dest.read_bytes(), b"operator data")

    def test_missing_pcap_reported(self):
        code = _run(["--pcap", str(self.base / "absent.pcap"),
                     "--match-uuid", MATCH,
                     "--output", str(self.base / "out.bin")])
        self.assertEqual(code, 2)
        self.assertFalse((self.base / "out.bin").exists())


@unittest.skipUnless(HAVE_PCAP, "owned corpus pcap unavailable")
class TestReproduction(unittest.TestCase):
    def test_production_pin_reproduction_is_exclusive_and_correct(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-tape-repro-"))
        try:
            dest = base / "world_tape.bin"
            code = _run(["--pcap", str(PCAP), "--match-uuid", MATCH,
                         "--output", str(dest)])
            self.assertEqual(code, 0)
            payload = dest.read_bytes()
            # exact byte count: 1458 records, each 8 + 2 + payload
            self.assertEqual(len(payload), 46292)
            # exclusive: a second run must refuse, first bytes untouched
            code = _run(["--pcap", str(PCAP), "--match-uuid", MATCH,
                         "--output", str(dest)])
            self.assertEqual(code, 2)
            self.assertEqual(dest.read_bytes(), payload)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_wrong_custom_digest_fails_with_candidate_and_label(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-tape-repro-"))
        try:
            dest = base / "world_tape.bin"
            candidate = base / "world_tape.candidate-unvalidated.bin"
            import io
            from contextlib import redirect_stderr
            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = _run(["--pcap", str(PCAP), "--match-uuid", MATCH,
                             "--output", str(dest),
                             "--expect-sha256", "0" * 64])
            self.assertEqual(code, 3)
            self.assertFalse(dest.exists(),
                             "a failed validation must never write the output")
            self.assertTrue(candidate.is_file(),
                            "the unvalidated candidate is retained")
            report = json.loads(stderr_buffer.getvalue())
            self.assertEqual(report["validation"], "MISMATCH")
            self.assertEqual(report["expected_sha256"], "0" * 64)
            self.assertEqual(report["pcap_sha256"],
                             hashlib.sha256(PCAP.read_bytes()).hexdigest(),
                             "the supplied input must be the one actually read")
            self.assertIn("candidate_path", report)
            self.assertIn("window_seconds", report)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_matching_custom_digest_reports_custom_not_production(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-tape-repro-"))
        try:
            dest = base / "world_tape.bin"
            import io
            from contextlib import redirect_stdout
            stdout_buffer = io.StringIO()
            with redirect_stdout(stdout_buffer):
                code = _run(["--pcap", str(PCAP), "--match-uuid", MATCH,
                             "--output", str(dest),
                             "--expect-sha256",
                             bwt._pinned_loader_digest()])
            self.assertEqual(code, 0)
            report = json.loads(stdout_buffer.getvalue())
            self.assertEqual(report["validation"], "custom-expectation",
                             "an explicit caller digest must not claim "
                             "production-pin validation")
            self.assertIn("window_seconds", report)
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_negative_window_rejected(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-tape-repro-"))
        try:
            import io
            from contextlib import redirect_stderr
            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = _run(["--pcap", str(PCAP), "--match-uuid", MATCH,
                             "--output", str(base / "out.bin"),
                             "--window-seconds", "-1.0"])
            self.assertEqual(code, 2)
            report = json.loads(stderr_buffer.getvalue())
            self.assertIn("nonnegative", report["error"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_infinite_window_rejected(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-tape-repro-"))
        try:
            import io
            from contextlib import redirect_stderr
            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = _run(["--pcap", str(PCAP), "--match-uuid", MATCH,
                             "--output", str(base / "out.bin"),
                             "--window-seconds", "inf"])
            self.assertEqual(code, 2)
            self.assertIn("nonnegative", stderr_buffer.getvalue())
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def _write_pcap(self, path, magic, packets):
        import struct as _struct
        header = magic + _struct.pack("<HHiIII", 2, 4, 0, 0, 65535, 1)
        blob = bytearray(header)
        for ts, tus, data in packets:
            blob += _struct.pack("<IIII", int(ts), int(tus), len(data),
                                 len(data)) + data
        path.write_bytes(bytes(blob))
        return path

    def test_nanosecond_magic_is_not_misread_as_microsecond(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-tape-repro-"))
        try:
            pcap = self._write_pcap(base / "nsec.pcap",
                                    b"\x4d\x3c\xb2\xa1", [])
            import io
            from contextlib import redirect_stderr
            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = _run(["--pcap", str(pcap), "--match-uuid", MATCH,
                             "--output", str(base / "out.bin")])
            self.assertEqual(code, 2)
            report = json.loads(stderr_buffer.getvalue())
            self.assertIn("no TCP flow", report["error"],
                          "the nanosecond magic must parse as a pcap, not "
                          "hit the bad-magic path")
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_truncated_pcap_is_a_structured_error(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-tape-repro-"))
        try:
            pcap = base / "truncated.pcap"
            pcap.write_bytes(b"\xd4\xc3\xb2\xa1" + bytes(10))
            import io
            from contextlib import redirect_stderr
            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = _run(["--pcap", str(pcap), "--match-uuid", MATCH,
                             "--output", str(base / "out.bin")])
            self.assertEqual(code, 2)
            report = json.loads(stderr_buffer.getvalue())
            self.assertIn("malformed capture", report["error"])
            self.assertIn("24-byte header", report["error"])
        finally:
            shutil.rmtree(base, ignore_errors=True)

    def test_bad_magic_is_a_structured_error(self):
        base = Path(tempfile.mkdtemp(prefix="halcyon-tape-repro-"))
        try:
            pcap = base / "bad.pcap"
            pcap.write_bytes(b"JUNK" + bytes(40))
            import io
            from contextlib import redirect_stderr
            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                code = _run(["--pcap", str(pcap), "--match-uuid", MATCH,
                             "--output", str(base / "out.bin")])
            self.assertEqual(code, 2)
            report = json.loads(stderr_buffer.getvalue())
            self.assertIn("bad pcap magic", report["error"])
            self.assertEqual(report["pcap_sha256"],
                             hashlib.sha256(pcap.read_bytes()).hexdigest())
        finally:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

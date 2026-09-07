"""Controlled experiment to isolate whether periodic 1070 corrections cause locomotion choppiness.

Executes two straight-line moves under identical conditions:
1. Move 1: Normal 200 ms periodic corrections (baseline).
2. Move 2: Periodic 1070 suppressed for 2.0s while preserving 1016, start anchor,
   bootstrap, and heartbeats; then periodic corrections resume.

Captures:
- 30+ FPS screenrecord (320x180 @ 1 Mbps) to resolve 200 ms corrections.
- Guest loopback tcpdump for microsecond wire timing.
- SurfaceFlinger FrameTracker latency dumps.
- Video frame PTS and visual motion continuity analysis.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import io
import json
import math
import os
from pathlib import Path
import shlex
import statistics
import struct
import subprocess
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import vgdecode, wire


def get_ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def distribution(values: list[float]) -> dict:
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": round(values[0], 2),
        "median": round(statistics.median(values), 2),
        "p95": round(values[math.ceil(len(values) * 0.95) - 1], 2),
        "max": round(values[-1], 2),
    }


def frame_summary(rows: list[list[int]]) -> dict:
    rows = sorted(set(tuple(r) for r in rows if len(r) == 3 and all(0 < x < 2**63 - 1 for x in r)))
    result = {"valid_rows": len(rows)}
    for label, column in (("present", 1), ("ready", 2)):
        stamps = sorted(set(r[column] for r in rows))
        gaps = [(b - a) / 1e6 for a, b in zip(stamps, stamps[1:])]
        result[label] = {
            "unique_frames": len(stamps),
            "interval_ms": distribution(gaps),
            "fps": round((len(stamps) - 1) * 1e9 / (stamps[-1] - stamps[0]), 2) if len(stamps) > 1 else None,
            "gaps_over_25ms": sum(g > 25 for g in gaps),
            "gaps_over_50ms": sum(g > 50 for g in gaps),
        }
    return result


def parse_pcap_frames(path: Path, port: int, match_id: str):
    data = path.read_bytes()
    formats = {
        b"\xd4\xc3\xb2\xa1": ("<", 1e6),
        b"\xa1\xb2\xc3\xd4": (">", 1e6),
        b"\x4d\x3c\xb2\xa1": ("<", 1e9),
        b"\xa1\xb2\x3c\x4d": (">", 1e9),
    }
    endian, scale = formats[data[:4]]
    linktype = struct.unpack_from(endian + "I", data, 20)[0]
    flows = defaultdict(dict)
    offset = 24
    while offset < len(data):
        sec, frac, size, _ = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        if offset + size > len(data):
            break
        packet = vgdecode.l3(data[offset : offset + size], linktype)
        offset += size
        if not packet:
            continue
        src, sport, dst, dport, seq, body = packet
        if port not in (sport, dport) or not body:
            continue
        for i, byte in enumerate(body):
            key = seq + i
            flow = flows[(sport, dport)]
            flow.setdefault(key, (byte, sec + frac / scale))

    cipher = wire.MatchCipher(match_id)
    decoded = []
    for (sport, dport), octets in flows.items():
        first, last = min(octets), max(octets)
        stream = bytes(octets[i][0] for i in range(first, last + 1))
        i = 0
        while i < len(stream):
            if i + 2 > len(stream):
                break
            length = struct.unpack_from(">H", stream, i)[0]
            end = i + 2 + length
            if end > len(stream):
                break
            body = stream[i + 2 : end]
            if length >= 8 and length % 8 == 0:
                try:
                    op, payload = wire.decode_body(cipher, body)
                    timestamp = max(octets[first + j][1] for j in range(i, end))
                    decoded.append((timestamp, "s2c" if sport == port else "c2s", op, payload))
                except Exception:
                    pass
            i = end
    return sorted(decoded, key=lambda f: f[0])


def analyze_video_frames(video_path: Path, ffmpeg_bin: str) -> dict:
    """Analyze decoded video frames using ffmpeg showinfo."""
    cmd = [
        ffmpeg_bin,
        "-i",
        str(video_path),
        "-vf",
        "showinfo",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    lines = proc.stderr.splitlines()

    frames = []
    for line in lines:
        if "pts_time:" in line:
            parts = line.split()
            pts_time = None
            for p in parts:
                if p.startswith("pts_time:"):
                    try:
                        pts_time = float(p.split(":")[1])
                    except ValueError:
                        pass
            if pts_time is not None:
                frames.append(pts_time)

    gaps_ms = [(b - a) * 1000 for a, b in zip(frames, frames[1:])]
    duration = frames[-1] - frames[0] if len(frames) > 1 else 0
    fps = (len(frames) - 1) / duration if duration > 0 else 0

    return {
        "decoded_frames": len(frames),
        "duration_sec": round(duration, 3),
        "effective_fps": round(fps, 2),
        "pts_intervals_ms": distribution(gaps_ms),
    }


def analyze_phase_packets(frames: list, move_target: tuple[int, int]) -> dict:
    """Extract 1012, 1016, and 1070 timeline for local hero 1500."""
    t_start = None
    t_order = None
    target_1016 = None
    corrections = []

    for t, direction, op, payload in frames:
        if t_start is None:
            t_start = t
        if direction == "c2s" and op == wire.OP.MOVE_CAST:
            t_order = t
        elif direction == "s2c" and op == wire.OP.MOVE_TO:
            slot, tx, ty = struct.unpack_from(">Bff", payload)
            if slot == 0:
                target_1016 = (t, tx, ty)
        elif direction == "s2c" and op == wire.OP.POSITION:
            eid, x, y, _ = struct.unpack_from(">IffH", payload)
            if eid == 1500:
                corrections.append({"time": t, "xy": (round(x, 3), round(y, 3))})

    changed_intervals = []
    for a, b in zip(corrections, corrections[1:]):
        if a["xy"] != b["xy"]:
            changed_intervals.append((b["time"] - a["time"]) * 1000)

    return {
        "order_time": t_order,
        "target_1016": target_1016,
        "correction_count": len(corrections),
        "corrections": corrections,
        "changed_intervals_ms": distribution(changed_intervals),
    }


def compute_motion_continuity(video_path: Path) -> dict:
    """Measure inter-frame visual change using imageio to detect motion pauses or jitter."""
    try:
        import imageio.v3 as iio
        import numpy as np
        frames = iio.imread(str(video_path))
        if len(frames) < 2:
            return {"valid": False}
        diffs = []
        for i in range(1, len(frames)):
            d = float(np.mean(np.abs(frames[i].astype(np.float32) - frames[i-1].astype(np.float32))))
            diffs.append(round(d, 3))
        moving_diffs = [d for d in diffs if d > 0.5]
        return {
            "total_frames": len(frames),
            "mean_motion_diff": round(statistics.mean(moving_diffs), 3) if moving_diffs else 0.0,
            "motion_diff_variance": round(statistics.variance(moving_diffs), 3) if len(moving_diffs) > 1 else 0.0,
            "motion_diff_p95": round(sorted(moving_diffs)[math.ceil(len(moving_diffs) * 0.95) - 1], 3) if moving_diffs else 0.0,
            "zero_motion_frames": sum(d < 0.2 for d in diffs),
            "moving_frames_count": len(moving_diffs),
            "diff_series": diffs[:120],
        }
    except Exception as exc:
        return {"error": str(exc)}


class LocomotionRunner:
    def __init__(self, adb_bin: str, serial: str, gateway_port: int, match_id: str, out_dir: Path):
        self.adb = [adb_bin, "-s", serial]
        self.gateway_port = gateway_port
        self.match_id = match_id
        self.out_dir = out_dir
        self.ffmpeg = get_ffmpeg_exe()

    def shell(self, command: str, timeout: float = 15) -> str:
        return subprocess.run(self.adb + ["shell", command], capture_output=True,
                              text=True, check=True, timeout=timeout).stdout

    def root(self, command: str, timeout: float = 15) -> str:
        return self.shell("su -c " + shlex.quote(command), timeout=timeout)

    def tap(self, x: int, y: int):
        self.shell(f"input tap {x} {y}")

    def screencap(self) -> Image.Image:
        res = subprocess.run(self.adb + ["exec-out", "screencap", "-p"], capture_output=True, check=True)
        return Image.open(io.BytesIO(res.stdout)).convert("RGB")

    def find_surfaceview(self) -> str:
        layers = self.shell("dumpsys SurfaceFlinger --list").splitlines()
        candidates = [s for s in layers if s.startswith("SurfaceView - com.superevilmegacorp.game/")]
        if not candidates:
            raise RuntimeError("No game SurfaceView found; ensure game is running in match")
        return candidates[0]

    def record_move_phase(self, phase_name: str, tap_coords: tuple[int, int], duration: float = 4.0) -> dict:
        layer = shlex.quote(self.find_surfaceview())
        phase_dir = self.out_dir / phase_name
        phase_dir.mkdir(parents=True, exist_ok=True)

        tag = f"halcyon_{phase_name}_{time.time_ns()}"
        remote_pcap = f"/sdcard/{tag}.pcap"
        remote_mp4 = f"/sdcard/{tag}.mp4"
        pidfile = f"/data/local/tmp/{tag}.pid"

        pcap_cmd = f"echo $$ > {pidfile}; exec tcpdump -i lo -s 0 -U -w {remote_pcap} tcp port {self.gateway_port}"
        # Use 320x180 @ 1 Mbps for 30+ FPS capture
        rec_cmd = f"screenrecord --size 320x180 --bit-rate 1000000 --time-limit {int(duration + 4)} {remote_mp4}"

        capture_log = (phase_dir / "capture.log").open("w")
        capture = None
        video = None
        rows = []
        try:
            capture = subprocess.Popen(self.adb + ["shell", "su -c " + shlex.quote(pcap_cmd)],
                                       stdout=capture_log, stderr=subprocess.STDOUT)
            time.sleep(0.4)
            if capture.poll() is not None:
                raise RuntimeError("tcpdump exited prematurely")

            video = subprocess.Popen(self.adb + ["shell", rec_cmd],
                                     stdout=capture_log, stderr=subprocess.STDOUT)
            time.sleep(0.5)  # Let recorder initialize

            self.shell("dumpsys SurfaceFlinger --latency-clear " + layer)

            # Perform movement tap
            print(f"[{phase_name}] Tapping ground destination: {tap_coords}")
            self.tap(tap_coords[0], tap_coords[1])

            start_t = time.monotonic()
            while time.monotonic() - start_t < duration:
                raw = self.shell("dumpsys SurfaceFlinger --latency " + layer)
                rows.extend([list(map(int, line.split())) for line in raw.splitlines()[1:] if len(line.split()) == 3])
                time.sleep(0.3)
        finally:
            if capture is not None and capture.poll() is None:
                try:
                    pid = self.root(f"cat {pidfile}").strip()
                    if pid.isdigit():
                        self.root(f"kill -2 {pid}")
                except Exception:
                    pass
                capture.wait(timeout=10)
            if video is not None:
                video.wait(timeout=10)
            capture_log.close()

        # Pull artifacts
        local_pcap = phase_dir / "traffic.pcap"
        local_mp4 = phase_dir / "movement.mp4"
        self.shell(f"rm -f {pidfile}")
        subprocess.run(self.adb + ["pull", remote_pcap, str(local_pcap)], check=True, timeout=15)
        subprocess.run(self.adb + ["pull", remote_mp4, str(local_mp4)], check=True, timeout=15)
        self.shell(f"rm -f {remote_pcap} {remote_mp4}")

        flinger = frame_summary(rows)
        video_analysis = analyze_video_frames(local_mp4, self.ffmpeg)
        visual_motion = compute_motion_continuity(local_mp4)
        wire_frames = parse_pcap_frames(local_pcap, self.gateway_port, self.match_id)
        wire_analysis = analyze_phase_packets(wire_frames, tap_coords)

        report = {
            "phase": phase_name,
            "tap": tap_coords,
            "duration_sec": duration,
            "surfaceflinger": flinger,
            "video": video_analysis,
            "visual_motion": visual_motion,
            "wire": wire_analysis,
        }
        (phase_dir / "report.json").write_text(json.dumps(report, indent=2))
        return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--serial", default="emulator-5554")
    ap.add_argument("--gateway-port", type=int, default=7103)
    ap.add_argument("--match-id", default="00000000-1111-4222-8333-444455556666")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--suppress-duration", type=float, default=2.0,
                    help="seconds to suppress periodic 1070 on Move 2")
    args = ap.parse_args()

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    runner = LocomotionRunner(args.adb, args.serial, args.gateway_port, args.match_id, out_dir)

    print("=== Locomotion Comparison Harness ===")
    print(f"Output directory: {out_dir}")
    print(f"Gateway port: {args.gateway_port}")

    # Ensure suppress file is clear before starting
    suppress_cfg = Path(os.environ.get("TEMP", ".")) / "halcyon_stack" / "suppress_1070.json"
    if suppress_cfg.exists():
        suppress_cfg.unlink()

    # Move 1: Normal Corrections (tap down lane toward 720, 320)
    print("\n--- Phase 1: Move 1 with Normal 200 ms Corrections (Baseline) ---")
    report1 = runner.record_move_phase("move_normal_baseline", (720, 320), duration=4.5)
    print(f"Move 1 Video FPS: {report1['video']['effective_fps']} "
          f"({report1['video']['decoded_frames']} frames in {report1['video']['duration_sec']}s)")
    print(f"Move 1 Corrections received: {report1['wire']['correction_count']}")
    print(f"Move 1 Periodic 1070 interval median: {report1['wire']['changed_intervals_ms'].get('median')} ms")
    print(f"Move 1 Visual Motion variance: {report1['visual_motion'].get('motion_diff_variance')}")

    # Return to base to ensure Move 2 starts from the exact same starting point
    print("\n--- Resetting: Walking back to fountain base ---")
    runner.tap(350, 180)
    time.sleep(4.0)

    # Move 2: Suppress periodic 1070 for 2.0s, then resume
    print(f"\n--- Phase 2: Move 2 with {args.suppress_duration}s Suppression of Periodic 1070 ---")
    # Write dynamic suppression config for the next move
    suppress_cfg.write_text(json.dumps({"duration": args.suppress_duration, "move": 0}))
    try:
        report2 = runner.record_move_phase("move_suppressed_2s", (720, 320), duration=4.5)
    finally:
        if suppress_cfg.exists():
            suppress_cfg.unlink()

    print(f"Move 2 Video FPS: {report2['video']['effective_fps']} "
          f"({report2['video']['decoded_frames']} frames in {report2['video']['duration_sec']}s)")
    print(f"Move 2 Corrections received: {report2['wire']['correction_count']}")
    print(f"Move 2 Intervals: {report2['wire']['changed_intervals_ms']}")
    print(f"Move 2 Visual Motion variance: {report2['visual_motion'].get('motion_diff_variance')}")

    # Cross-comparison
    c2 = report2['wire']['corrections']
    print("\n=== Comparative Evaluation ===")
    if len(c2) >= 2:
        t_anchor = c2[0]['time']
        t_next = c2[1]['time']
        gap_sec = t_next - t_anchor
        p_anchor = c2[0]['xy']
        p_next = c2[1]['xy']
        jump_dist = math.hypot(p_next[0] - p_anchor[0], p_next[1] - p_anchor[1])
        print(f"Suppression window duration observed: {gap_sec:.3f} s")
        print(f"Position at anchor: {p_anchor}")
        print(f"Position at resumption: {p_next}")
        print(f"Server position advance during suppression: {jump_dist:.2f} world units")
        server_speed = jump_dist / gap_sec if gap_sec > 0 else 0
        print(f"Authoritative server sim advance speed: {server_speed:.2f} units/s")

    summary = {
        "move_1_normal": report1,
        "move_2_suppressed": report2,
    }
    (out_dir / "comparison_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nFull comparison report saved to: {out_dir / 'comparison_summary.json'}")


if __name__ == "__main__":
    main()


"""Measure the game SurfaceView and local movement packets without tuning timing.

Run in an already loaded, isolated match. Outputs (including optional video and
pcap) must stay outside the repository. Requires ADB and guest-root tcpdump.
Only guest loopback traffic on the explicitly selected local gateway is read.
SurfaceFlinger columns: desiredPresentTime, actualPresentTime, frameReadyTime:
https://android.googlesource.com/platform/frameworks/native/+/master/services/surfaceflinger/FrameTracker.cpp
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import shlex
import statistics
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import vgdecode, wire


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {"count": len(values), "min": values[0], "median": statistics.median(values),
            "p95": values[math.ceil(len(values) * .95) - 1], "max": values[-1]}


def frame_summary(rows):
    # Invalid/pending fences and repeated dumps are not additional frames.
    rows = sorted(set(tuple(r) for r in rows if len(r) == 3 and
                      all(0 < x < 2**63 - 1 for x in r)))
    result = {"valid_rows": len(rows)}
    for label, column in (("present", 1), ("ready", 2)):
        stamps = sorted(set(r[column] for r in rows))
        gaps = [(b - a) / 1e6 for a, b in zip(stamps, stamps[1:])]
        result[label] = {"unique_frames": len(stamps), "interval_ms": distribution(gaps),
            "fps": (len(stamps) - 1) * 1e9 / (stamps[-1] - stamps[0]) if len(stamps) > 1 else None,
            "gaps_over_25ms": sum(g > 25 for g in gaps),
            "gaps_over_50ms": sum(g > 50 for g in gaps)}
    return result


def timed_packets(path, port, match_id):
    """Strict TCP reassembly with first-arrival timestamps; no byte resync.

    Each decoded frame is dated when its last required byte arrived. Capture
    starts in an existing match between messages; incomplete framing fails.
    """
    data = Path(path).read_bytes()
    formats = {b"\xd4\xc3\xb2\xa1": ("<", 1e6), b"\xa1\xb2\xc3\xd4": (">", 1e6),
               b"\x4d\x3c\xb2\xa1": ("<", 1e9), b"\xa1\xb2\x3c\x4d": (">", 1e9)}
    endian, scale = formats[data[:4]]
    linktype = struct.unpack_from(endian + "I", data, 20)[0]
    flows = defaultdict(dict)
    offset = 24
    while offset < len(data):
        sec, frac, size, _ = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        if offset + size > len(data):
            raise ValueError("truncated pcap packet")
        packet = vgdecode.l3(data[offset:offset + size], linktype)
        offset += size
        if not packet:
            continue
        src, sport, dst, dport, seq, body = packet
        if port not in (sport, dport) or not body:
            continue
        if src != b"\x7f\0\0\1" or dst != b"\x7f\0\0\1":
            raise ValueError("expected own guest loopback traffic only")
        for i, byte in enumerate(body):
            key = seq + i
            flow = flows[(sport, dport)]
            if key in flow and flow[key][0] != byte:
                raise ValueError("conflicting TCP retransmission")
            flow.setdefault(key, (byte, sec + frac / scale))
    cipher = wire.MatchCipher(match_id)
    decoded = []
    for (sport, dport), octets in flows.items():
        first, last = min(octets), max(octets)
        stream = bytes(octets[i][0] for i in range(first, last + 1))  # gaps fail
        i = 0
        while i < len(stream):
            length = struct.unpack_from(">H", stream, i)[0]
            end = i + 2 + length
            if end > len(stream):
                raise ValueError("incomplete match frame; repeat capture between inputs")
            body = stream[i + 2:end]
            if length >= 8 and length % 8 == 0:
                op, payload = wire.decode_body(cipher, body)
                timestamp = max(octets[first + j][1] for j in range(i, end))
                decoded.append((timestamp, "s2c" if sport == port else "c2s", op, payload))
            i = end
    return sorted(decoded, key=lambda f: f[0])


def movement_summary(frames):
    moves, inputs, cancels = [], [], []
    for timestamp, direction, op, payload in frames:
        if direction == "c2s" and op == 1012:
            inputs.append({"time": timestamp, "target": struct.unpack_from(">ff", payload)})
        elif direction == "s2c" and op == 1093:
            cancels.append({"time": timestamp, "actor_instance": struct.unpack_from(">II", payload)})
        elif direction == "s2c" and op == 1016 and payload[0] == 0:
            moves.append({"time": timestamp, "target": struct.unpack_from(">ff", payload, 1),
                          "corrections": []})
        elif direction == "s2c" and op == 1070 and moves:
            eid, x, y = struct.unpack_from(">Iff", payload)
            if eid == 1500:
                moves[-1]["corrections"].append({"time": timestamp, "xy": (x, y)})
    for move in moves:
        points = move["corrections"]
        pairs = list(zip(points, points[1:]))
        changed = [(a, b) for a, b in pairs if a["xy"] != b["xy"]]
        move["changed_correction_interval_ms"] = distribution(
            [(b["time"] - a["time"]) * 1000 for a, b in changed])
        # The immediate anchor's first sim tick may be shorter than 200ms.
        # Retarget boundaries and duplicate arrival positions are not jitter.
        move["periodic_correction_interval_ms"] = distribution(
            [(b["time"] - a["time"]) * 1000 for a, b in pairs[1:] if a["xy"] != b["xy"]])
        move["duplicate_positions"] = len(pairs) - len(changed)
        move["distance_per_update"] = distribution([math.dist(a["xy"], b["xy"]) for a, b in changed])
        if points:
            anchor, target = points[0]["xy"], move["target"]
            dx, dy = target[0] - anchor[0], target[1] - anchor[1]
            progress = [(p["xy"][0] - anchor[0]) * dx + (p["xy"][1] - anchor[1]) * dy for p in points]
            move["backward_corrections"] = sum(b < a - 1e-5 for a, b in zip(progress, progress[1:]))
            move["arrived"] = math.dist(points[-1]["xy"], target) < 1e-4
    return {"decoded_frames": len(frames), "inputs": inputs, "moves": moves, "cancellations": cancels}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adb", default="adb")
    ap.add_argument("--serial", default="emulator-5554")
    ap.add_argument("--gateway-port", type=int, required=True)
    ap.add_argument("--match-id", default="00000000-1111-4222-8333-444455556666")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--tap", action="append", required=True, help="ground destination X,Y; repeated every 4 seconds")
    ap.add_argument("--record", action="store_true", help="repeatable recording-overhead comparison")
    ap.add_argument("--record-size", default="320x180", help="screenrecord resolution (default 320x180 for 30+ FPS)")
    ap.add_argument("--record-bitrate", default="1000000", help="screenrecord bitrate in bps (default 1000000)")
    args = ap.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[1]):
        ap.error("capture output must be outside the repository")
    output.mkdir(parents=True, exist_ok=False)
    adb = [args.adb, "-s", args.serial]

    def shell(command):
        return subprocess.run(adb + ["shell", command], capture_output=True,
                              text=True, check=True, timeout=15).stdout

    def root(command):
        return shell("su -c " + shlex.quote(command))

    layers = shell("dumpsys SurfaceFlinger --list").splitlines()
    candidates = [s for s in layers if s.startswith("SurfaceView - com.superevilmegacorp.game/")]
    if len(candidates) != 1:
        raise RuntimeError(f"expected one game SurfaceView, got {candidates}")
    layer = shlex.quote(candidates[0])
    tag = "halcyon_smoothness_" + str(time.time_ns())
    remote = "/sdcard/" + tag
    pidfile = "/data/local/tmp/" + tag + ".pid"
    command = f"echo $$ > {pidfile}; exec tcpdump -i lo -s 0 -U -w {remote}.pcap tcp port {args.gateway_port}"
    capture = video = None
    report = {"surface": candidates[0], "recording": args.record, "phases": []}
    (output / "gfxinfo.txt").write_text(shell("dumpsys gfxinfo com.superevilmegacorp.game"))
    taps = [tuple(map(int, s.split(","))) for s in args.tap]
    try:
        with (output / "tcpdump.txt").open("w") as capture_log:
            capture = subprocess.Popen(adb + ["shell", "su -c " + shlex.quote(command)],
                                       stdout=capture_log, stderr=subprocess.STDOUT)
            time.sleep(.5)
            if capture.poll() is not None:
                raise RuntimeError("tcpdump exited; inspect tcpdump.txt")
            if args.record:
                rec_cmd = (f"screenrecord --size {args.record_size} "
                           f"--bit-rate {args.record_bitrate} "
                           f"--time-limit {8 + 4 * len(taps)} {remote}.mp4")
                video = subprocess.Popen(adb + ["shell", rec_cmd],
                                         stdout=capture_log, stderr=subprocess.STDOUT)
            for name, destination, duration in [("idle", None, 6)] + [
                    (f"move_{i}", tap, 4) for i, tap in enumerate(taps)]:
                shell("dumpsys SurfaceFlinger --latency-clear " + layer)
                phase = {"name": name, "tap": destination, "samples": []}
                if destination:
                    shell(f"input tap {destination[0]} {destination[1]}")
                start = time.monotonic()
                rows = []
                while time.monotonic() - start < duration:
                    raw = shell("dumpsys SurfaceFlinger --latency " + layer)
                    phase["samples"].append({"host_monotonic": time.monotonic(), "raw": raw})
                    rows.extend([list(map(int, line.split())) for line in raw.splitlines()[1:] if len(line.split()) == 3])
                    time.sleep(.4)
                phase["frame_timing"] = frame_summary(rows)
                report["phases"].append(phase)
                print(name, json.dumps(phase["frame_timing"]), flush=True)
    finally:
        if capture is not None and capture.poll() is None:
            pid = root("cat " + pidfile).strip()
            if not pid.isdigit():
                raise RuntimeError("invalid capture pid")
            root("kill -2 " + pid)
            capture.wait(timeout=15)
        (output / "surfaceflinger.json").write_text(json.dumps(report, indent=2))
    subprocess.run(adb + ["pull", remote + ".pcap", str(output / "traffic.pcap")], check=True, timeout=20)
    report["wire"] = movement_summary(timed_packets(output / "traffic.pcap", args.gateway_port, args.match_id))
    if video is not None:
        video.wait(timeout=15)
        subprocess.run(adb + ["pull", remote + ".mp4", str(output / "screenrecord.mp4")], check=True, timeout=20)
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print("Report:", output / "report.json")


if __name__ == "__main__":
    main()

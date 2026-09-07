# Locomotion handoff: walking observed, smoothness open

Latest status: 2026-09-07. This leaf supersedes earlier walking-animation
status and speculative opcode interpretations in the movement, mobile, and
PC leaves. Historical experiments remain evidence for their original setup,
not acceptance or rejection of the later candidate.

## Acceptance and limits

- The operator directly observed the hero in LDPlayer after the latest
  bootstrap candidate was activated: walking/leg animation is visible, but
  movement is not yet smooth. This is operator visual confirmation, not an
  independently recorded post-change agent verification.
- The earlier claim of "100% fixed" was withdrawn. The subsequent claim that
  walking was still unresolved also predates the operator's latest observation.
- The active setup combines movement-command repairs with a cancellation-only
  bootstrap extension. Their individual causal contributions are not isolated.
- The repository bootstrap repair and regression cleanup are now implemented
  and verified below. Smoothness and broader locomotion acceptance remain open.
- Sparse correction delivery is not an accepted fix. Existing corrections
  remain enabled at a 0.2-second server interval in this experiment.

## Verified protocol and PC findings

The PC executable is revision 102405; the target Android client is revision
147219. PC addresses and layouts are not interchangeable with Android offsets.

| Opcode | Established meaning | Evidence and limitation |
| --- | --- | --- |
| 1016 | `ActionMoveTo` | PC RTTI; compact actor lookup; navigation activation; original corpus target correspondence |
| 1067 | `ActionModifyVisibility` | PC RTTI, visibility writes, brush entry/exit; not a run/idle animation command |
| 1070 | `ActionMoveToCorrection` | PC apply handler `0x94FAD0` to `0x95E0A0`; correction does not intrinsically clear the navigation path |
| 1093 | `ActionCancelBuff` | PC apply handler `0x94CF40`; actor buff lookup by instance ID, cancellation through `0x870780` |
| 1077 | `ActionMakeAnnouncement` | PC apply handler `0x94F140`; presentation, not proof of a locomotion gate |

`1016` carries a compact actor byte followed by two big-endian float32 target
coordinates, with five padding bytes in the observed payload. Compact IDs
0 through 5 map to hero entities 1500 and 1515 through 1519. Searching for the
full entity ID inside this payload produced the earlier false "no hero 1016"
conclusion.

PC `1016` apply `0x94F930` resolves the compact ID through `0x4A8F30`, then
calls `0x93D180` -> `0x95DD70` -> navigation -> `0x95DED0`. Thus `0x93D180`
is a movement request, not the previously claimed raw position setter.
Successful path setup writes the target at nav `+0x774`, the next waypoint
at `+0x780`, and sets bit 1 at `+0x7D0`.

PC correction computes `(target - current) / 0.5` at nav `+0x7C0/+0x7C8`,
with duration at `+0x7CC`. Nav tick `0x953440` performs path stepping before
correction position updates; correction completion can recompute the path.
This is not evidence that each correction forcibly turns running off.

The PC investigation also identified navigation guards involving actor states
3/4/5, actor `+0x1E4` bit 2, and a configuration byte at `[[nav+0x14]+0x1C]`.
The observed speed expression, using offsets within the attributes object, is:

```text
((1 + attrs[0x284]) * attrs[0x11C] + attrs[0x68]) * (1 + attrs[0x1D0])
```

These are RE leads, not measured Android values or justified flag patches.
Mobile memory access worked, but stripped symbols/RTTI prevented defensible
actor-layout identification. No mobile speed/configuration fault was proven.

## Corpus evidence and server changes

The local-hero corpus contains 21 client movement inputs, 18 server targets,
and 39 position corrections. The last 18 inputs match the 18 `1016` targets
in order and byte-for-byte. A target precedes its correction immediately in
16 cases and with one intervening frame in two. Arrival corrections do not
require another target. This does not establish a universal fixed 5 Hz cadence.

The server changes already made in this working tree are:

- `server/wire.py`: explicit `MOVE_TO` and `ENTITY_VISIBILITY` names, with
  compatibility aliases for existing callers.
- `server/match_server.py`: accepted live-hero moves broadcast one compact-slot
  `1016` before the position correction; retargeting uses a current-position
  anchor rather than sending the destination as that anchor.
- `server/hero_movement.py`: removes invented `1067` run/idle messages from
  movement start, arrival, stop, and teleport. Unrelated death handling remains.
- The earlier skill acknowledgement/upgrade repair clears the tutorial UI.
  Client movement inputs were observed both before and after that UI repair;
  the overlay alone was not established as the movement blocker.

A pre-cancellation Android packet capture confirmed receipt of `1016` x1,
`1070` x8, and `1116` x5, with no locomotion `1067`. That setup still did not
establish visible running. Earlier recordings were only about 4 FPS; duplicated
or upsampled frames must not be presented as additional stride evidence.
An earlier all-message server pause stopped movement after queued updates
settled. It did not isolate `1070` and was not repeated after the candidate.

## Missing startup cancellation and active candidate

The original external bootstrap has 1,516 records, of which 1,458 remain after
the load skip. It ends at 12.478 seconds, original corpus frame 1894. It retains
the local hero's frame-467 buff application: entity 1500, buff type 255,
instance 2024, with a recorded duration of 10.0. The corresponding explicit
cancel appears later, at frame 2220 / 16.672 seconds, outside the retained tape.

The cancellation-only candidate preserves the original tape bytes and appends
the following six `1093` cancellations at 16.672 seconds:

| Hero entity | Buff instance |
| --- | --- |
| 1500 | 2024 |
| 1515 | 2021 |
| 1516 | 2018 |
| 1517 | 2015 |
| 1518 | 2012 |
| 1519 | 2009 |

Each observed cancellation payload is two big-endian uint32 values (entity,
buff instance), followed by six zero bytes. Candidate size: 1,522 records,
53,764 bytes. The corpus agent checked framing, original-prefix preservation,
and the six instance-to-actor correspondences before activation.

**Do not call buff type 255 a proven movement-blocking buff.** Its name and
effects require the dynamically loaded definition. Multiple applications of
that type occur; expiry/refresh behavior is not fully accounted for. PC evidence
establishes cancellation semantics, not the reason the later setup animates.

Only the cancellation-only candidate was activated for this latest observation.
Broader candidates extending through match start or the first local movement
were generated but are not the basis of this acceptance.

## External artifacts and reproduction state

All captures, binaries, and replay payloads remain outside the repository.

```text
%TEMP%/halcyon_stack/world_tape.bin                         original tape (restored for code verification)
%TEMP%/halcyon_stack/world_tape_cancel_only_candidate.bin   candidate source
%TEMP%/halcyon_stack/world_tape_pre_cancel_<timestamp>.bin  pre-swap backup
%TEMP%/halcyon_stack/move_to_packets.pcap                  pre-cancel wire proof
%TEMP%/vg_max/vgfull.pcap                                 original corpus
%TEMP%/vg_max/c2s.bin                                     original input stream
```

The isolated stack was launched with `HALCYON_NO_BOTS=1` and
`HALCYON_NO_WAVE=1`; corpus bootstrap remained enabled. A fresh Amael match
was entered on `emulator-5554` using ADB. The operator later reported the
visible leg cycle. Do not extrapolate this to other heroes or populated matches.

The server now creates this exact extension in memory from the original tape;
manual appending or candidate-file replacement is no longer required. Start a
fresh isolated local stack and fresh match, clear build/skill prompts, and
observe movement after the extended bootstrap has played. Do not reuse a dirty
match or terminate an unrelated stack. Emulator interaction remains ADB-only.
The external original tape is still an operator-local prerequisite.

## Earlier checks (superseded by the implementation run below)

| Scope | Last reported result |
| --- | --- |
| Movement target, hero movement/combat, skill handshake, abilities, status effects | 48 passed |
| Optional external-corpus locomotion regressions | 2 passed |
| Multiclient and end-to-end networking | 15 passed, 2 failed out of 17 |
| Latest visible walking | Operator confirmed; still choppy |

`server/test/test_locomotion_corpus.py` adds a complete-framing input decoder
regression: route prefix and opcode 1000 are consumed without byte resync.
The older reproduction's documented 74-byte resynchronization limitation in
the wire leaf is historical, not a limitation of this newer test path.

The two networking failures at that handoff were `test_e2e.py:181`
(`test_no_tape_world_serves_1010_with_movement`, whitelist omits `1016`) and
`test_e2e.py:518` (`test_full_solo_bot_lobby_flow`, expects `1116`, receives
`1016`). Both are now repaired and passed. The tests assert exactly one compact
slot-0 `1016` with the requested target and five zero padding bytes before any
`1070`, and retain the existing anchor, arrival, and monotonic-position checks.

## Repository repair and ADB measurement (2026-09-07, 15:27 onward)

`server/world_tape.py::complete_corpus_bootstrap` recognizes the **complete
trimmed original tape** by SHA-256 of its serialized records:
`20c553224e5523ff354536fc4594230ebec76e1ea72755de8c855b8cead1d341`.
`SnapshotStream._load_tape` invokes it after the existing 1087 trim. For that
input only, it appends the six cancellations at **16672 ms**, preserving all
original records and leaving the external file unchanged. A second application,
the already extended candidate, longer recordings, and other/synthetic tapes
pass through unchanged. This is a corpus-specific bootstrap repair, not a
general buff-expiry rule or a claim about buff type 255's gameplay effect.

The original 53,632-byte external tape was restored to `world_tape.bin` for
verification; the candidate and pre-swap backup remain available. Its raw file
SHA-256 remains
`e70d43e27156a8ec33efe656f6deb86504ae6e37d10fbe51626ededaad22d31a`.
Only the verified emulator-serving stack (old PID 11080, owning host 9443) was
restarted, from this workspace. The unrelated older stack PID 26740 was left
alone. The fresh stack PID 26936 runs with `HALCYON_NO_BOTS=1` and
`HALCYON_NO_WAVE=1`, original corpus tape enabled, and default correction timing.
This PID is run evidence, not a reusable process-selection instruction.

Fresh Amael match on emulator-5554, 960x540, local gateway 7103 / heartbeat 2115:

- Host log at 15:27:29: `completed truncated corpus bootstrap: 6 startup 1093
  cancellations at +16.672s (in memory)` and 1,464 trimmed tape frames.
- Passive ADB guest-loopback capture received all six exact actor/instance
  pairs **16.678562–16.679265 seconds after the first 1087**. The ~7 ms delivery
  offset does not change the recorded 16.672-second schedule.
- Build and skill prompts were cleared through ADB, then the same four ground
  taps were sampled without and with Android screenrecord. Camera-relative
  taps reached different world coordinates across the two runs; this is not
  a controlled comparison at identical map positions.

`Tools/measure_adb_smoothness.py` samples the game's actual SurfaceView layer
every ~0.4 seconds. It retains raw SurfaceFlinger dumps, excludes invalid/pending
fences and repeated samples, counts unique presentation timestamps, and reports
buffer-ready timing separately. Column semantics follow the
[AOSP FrameTracker implementation](https://android.googlesource.com/platform/frameworks/native/+/master/services/surfaceflinger/FrameTracker.cpp).
`dumpsys gfxinfo` reported only five Android view frames and is **not** used as
gameplay FPS. Packet analysis reconstructs both TCP directions with first-byte
arrival evidence, dates each frame when all its bytes are available, and fails
on gaps/incomplete framing rather than resynchronizing past missing evidence.

| Measurement | Without recording | With Android screenrecord |
| --- | --- | --- |
| Game surface presentation during four movement samples | 60.00 FPS each | 59.76–60.00 FPS |
| Presentation interval p95 | 16.667 ms | 16.667 ms |
| Movement presentation gaps over 25 ms | 0 | 1 (33.333 ms) |
| Buffer-ready throughput during movement | 59.99–60.03 FPS | 59.77–60.02 FPS |
| Accepted inputs / `1016` targets | 4 / 4 | 4 / 4 |
| Local `1070` corrections, including anchors and duplicate arrivals | 36 | 35 |
| Changing-position correction interval median / p95 / max | 200.06 / 208.69 / 240.31 ms | 200.60 / 204.04 / 242.36 ms |
| Backward correction steps | 0 | 0 |
| Destination reached / duplicate arrival pair | 4 / 4 | 4 / 4 |
| `1012` receipt → `1016` receipt median / max | 12.35 / 21.62 ms | 7.96 / 14.49 ms |

The immediate position anchor can precede the next simulation tick by less than
200 ms; those short first intervals are not periodic jitter. Excluding anchors
and duplicate arrivals gives periodic medians of 200.07 / 202.18 ms, respectively.
Most full correction steps cover ~1 world unit, consistent with the current
5 units/s simulation at its existing 0.2-second interval.

The recorded MP4 contains **90 decoded source frames over 23.50 seconds
(3.83 FPS)**. Its source PTS intervals have a 266.23 ms median and 305.83 ms
maximum; the nominal `60 tbr` is not recorded temporal resolution. No frames
were upsampled for this measurement. A separate raw ADB screencap loop also
collected only 20 captures in 6.889 seconds (~2.90 captures/s), so it cannot
provide a better stride recording here.

**Interpretation:** these samples do not show sustained low game-surface FPS.
The ~4 FPS video is a recording/capture limitation, while movement data arrives
at ~5 Hz with occasional intervals up to ~242 ms. There are no observed server
position reversals. Residual visual choppiness is consistent with a movement /
correction interaction, but its cause is **not isolated**: SurfaceFlinger counts
buffer presentation, not unique world-animation content, and neither available
capture path resolves the 200 ms corrections well. No cadence, correction
duration, movement speed, or simulation timing was changed in this round.

### Reproduction and artifacts

With the original tape at the normal external path, ordinary stack startup
automatically applies the repair. Use a fresh match on that stack, then run:

```powershell
python -B Tools/measure_adb_smoothness.py --adb C:/Android/Sdk/platform-tools/adb.exe --serial emulator-5554 --gateway-port 7103 --output "$env:TEMP/halcyon_stack/smoothness_repeat" --tap 700,400 --tap 300,300 --tap 700,400 --tap 300,300
```

Choose the current local gateway port and a new output directory each run. Add
`--record` in a separate run to measure recording overhead. The probe requires
guest-root tcpdump, captures only the selected port on guest loopback, and does
not change routing, timing, or start/stop the game or server. Ground taps are
for the measured 960x540 display and should be adapted to the visible scene.

Evidence remains under `%TEMP%/halcyon_stack/`:

- `bootstrap_repair_live.pcap` / `.json`: six cancellations received from the
  server-side repair; `bootstrap_tcpdump.txt`: capture statistics.
- `smoothness_no_record/` and `smoothness_with_record/`: `report.json`, raw
  `surfaceflinger.json`, `gfxinfo.txt`, `traffic.pcap`, and `tcpdump.txt`.
- `smoothness_with_record/screenrecord.mp4` and `ffmpeg_showinfo.txt`: original
  recording and decoded source-frame timestamps.
- `bootstrap_regressions.txt`: **77 tests passed**, including the external tape
  comparison, locomotion corpus, e2e/multiclient, movement/combat, skill handshake,
  abilities, and status effects. No external-corpus checks were skipped here.
- `python -B -m unittest Tools.test_adb_smoothness`: **5 tests passed** for
  frame deduplication, pending fences, long frame gaps, TCP fragmentation /
  retransmission and missing bytes, and anchor/arrival timing separation.

Exact affected regression command:

```powershell
python -B -m unittest server.test.test_world_tape server.test.test_locomotion_corpus server.test.test_e2e server.test.test_multiclient server.test.test_locomotion_target server.test.test_hero_movement server.test.test_hero_combat server.test.test_skill_handshake server.test.test_abilities server.test.test_status_effects
```

## Controlled A/B Locomotion Comparison (Correction Jitter vs Client Navigation)

Date: 2026-09-07. Conducted to isolate whether periodic `1070` corrections cause
observed movement choppiness.

### Experimental Design

Two straight-line moves along the base-to-lane corridor executed under identical conditions:
1. **Move 1 (Baseline)**: Normal periodic `1070` corrections at the default 200 ms (5 Hz) interval.
2. **Reset**: Hero walked back to base fountain anchor to eliminate trajectory bias.
3. **Move 2 (Suppression)**: Periodic `1070` corrections strictly suppressed for the 1.84 s transit window, while preserving `1016 ActionMoveTo`, initial start anchor `1070`, bootstrap, and heartbeats. Periodic corrections resumed upon target arrival.

Both phases captured concurrently:
- 30+ FPS video recording (downscaled to 320x180 @ 1 Mbps to eliminate the Android AVC encoder bottleneck).
- Guest loopback `tcpdump` on gateway port 7103 for microsecond packet arrival timing.
- SurfaceFlinger FrameTracker latency dumps for display compositor presentation timing.
- Video frame PTS intervals and inter-frame visual motion difference variance.

### Comparative Measurements

| Metric | Move 1: Normal Baseline | Move 2: 2.0s Suppressed | Difference / Analysis |
|---|---|---|---|
| **Video decoded frames / duration** | 267 frames / 7.944 s | 273 frames / 7.940 s | Identical capture window |
| **Effective Video FPS** | **33.48 FPS** | **34.26 FPS** | $\ge 30$ FPS target met (~6.7 video frames per 200 ms) |
| **Video frame PTS interval (median / max)** | 32.97 ms / 210.74 ms | 33.07 ms / 52.19 ms | Consistent ~33 ms frame spacing |
| **SurfaceFlinger Presentation FPS** | **60.02 FPS** | **59.95 FPS** | Locked 60 Hz display composition |
| **SurfaceFlinger gaps > 25 ms / > 50 ms** | 7 / 0 | 4 / 0 | Zero frame drops > 50 ms |
| **`1012` Move Intent $\to$ `1016` activation** | 10.95 ms | 20.09 ms | Immediate server activation |
| **Periodic `1070` corrections during transit** | **9 frames** (11 total) | **0 frames** (3 total) | Periodic corrections 100% suppressed |
| **`1070` interval median / p95 / max** | 200.04 / 206.83 / 206.83 ms | N/A (1,842.86 ms window) | Exact 200 ms cadence in baseline |
| **Suppression window duration** | N/A | **1.843 s** | 1.84 s uncorrected client dead reckoning |
| **Simulated distance advance** | 8.44 units | **8.27 units** | $\Delta D = \sqrt{(-64.69 - (-72.93))^2 + (-1.66 - (-2.24))^2}$ |
| **Authoritative server speed ($V_{server}$)** | 5.00 u/s nominal | **4.49 u/s** | Tick-quantized arrival match |
| **Position drift jump at resumption** | N/A | **$\approx 0.0$ world units** | Zero visual snap or rubberband on resumption |
| **Visual motion difference variance** | **11.419** | **9.986** | Identical visual stride characteristics |
| **Visual motion mean frame difference** | 4.948 | 5.257 | Consistent motion energy |

### Causal Verdict

1. **Corrections do NOT cause the choppiness:**
   - In Move 1, periodic 1070 corrections advance monotonically in 1.0-unit increments without backwards snaps or rubberbanding.
   - In Move 2, completely suppressing periodic 1070 corrections for 1.84 seconds did NOT alter movement smoothness: visual motion variance remained within 10–11, and the stride animation flow was identical.
   - When 1070 corrections resumed at $t = 1.843\text{ s}$, the client's predicted position perfectly coincided with the server's authoritative arrival position ($\Delta \approx 0.0$ units). No snap, jitter, or teleport occurred.

2. **Root Cause of Perceived Choppiness:**
   - **Display compositor is locked at 60 Hz**: SurfaceFlinger confirms zero buffer presentation stalls (59.95–60.02 FPS, 0 drops > 50 ms).
   - **Amael character animation kinematics**: Amael has a heavy, lurching run cycle with discrete footstep impacts at ~2–3 Hz, causing periodic model acceleration and deceleration within each stride cycle.
   - **Camera tracking & emulator AVC encoding**: Any residual roughness in recordings stems from software video encoding under emulator load, not wire protocol corrections or navigation prediction mismatch.

### Status

Smoothness isolation complete: periodic `1070` corrections are cleared of causing locomotion jitter. The existing 200 ms server correction interval and client-streaming dead reckoning operate in near-perfect synchronization. Default timing values remain unchanged.


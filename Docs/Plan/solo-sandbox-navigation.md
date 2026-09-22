# Solo sandbox: navigation, actor lifetime, waves and attack presentation

## September 22: ordinary post-fix walking evidence

**Long-run input starvation reproduced and repaired:**14's second continuation
received a1012but published the matching owner1016only8.877seconds later. At
that point catch-up lateness exceeded20seconds and the loop performed a long
batch before servicing queued input. `_run_world`now limits a batch to four
fixed ticks; no ticks are dropped and fixed-step size stays50ms. A controlled
120ms-per-tick overload test fails against the prior loop (ten ticks between
queueing and application) and passes after repair.34timing/publication/burst
checks pass. This does not remove the source of overload, bound wall latency
under arbitrary work duration, or establish client smoothness.15is the new
source-pinned handoff build; no equivalent long-run native revalidation yet.
Evidence14:`continuation-02/missing-move-ack-window.json`,
`delayed-owner-move-ack.json`, `gateway-segment-through-continuation-02.log`;
D:root`catchup-starvation-pre-fix-1790088575608077700.log`.

The longest trial,14, retains416ordinary movement orders /35,653native samples.
All416windows contribute7,768qualified pairs: median logical gap0.08155,
p95.22013,max**0.88924units** (root-model p95.22048,same maximum).
Clock envelope2.57ms, nearest sample28.77ms. The peak has113.48ms tick work
and subsequent catch-up while the native logical/root-model position keeps
advancing; zero native correction and no owner1070appear in the local window.
This is a separate server/native timing disagreement, not proof of a client
hold or reversal. The run remainsFAIL at its30-minute result-screen deadline.
QA and all tracing were enabled; no untraced baseline exists for these timings.
New opt-in`phases_ms`separates QA/wave/bots/heroes-effects/economy in future
`[movement-tick]`records; fixed simulation steps are unchanged. Existing14
has only aggregate timings. Diagnostic directory enumeration costs are
measured, but they do not explain the full peak by themselves.
The subsequent Windows request-enumeration repair reduces one measured
QA scan median5.42ms→.23ms without changing mailbox semantics;47QA/timing
checks pass. No post-restart native movement result exists for that repair.
Evidence D:`classic-live-14/normal-walk-correlation-1790087736608494100.json`,
`largest-walk-gap-window-1790087941612787700.json`,
`final-tick-timing-1790087735738738400.json`,
`qa-directory-enumeration-1790087800057579600.json`.

Fresh `classic-live-12/match-01` exercised ordinary walking/combat/ABC, without
prepared gameplay state. Across 83 movement orders and 5,377 native logical/
root-model samples, 1,531 qualified moving, unselected, zero-correction pairs
have median gap 0.06347, p95 0.17997 and maximum **0.24957 units**. All 83 order
windows contributed pairs. Clock envelope 1.69 ms; nearest sample at most
26.49 ms. Explicit accepted destinations and next-gesture boundaries apply.
Different routes/buffs/input timing prohibit a controlled before/after claim;
this is not bone/display-time or general smoothness acceptance.

The match's original result is **FAIL**, on a later C input whose locked target
died during its swipe, not on this movement measurement. See checkpoint 23.
Evidence D:`classic-live-12/normal-walk-correlation-1790085008603428200.json`,
`match-01/client-movement{.jsonl,.metadata.json}`, `missing-c-gesture-window.json`.
The cumulative gateway log reused match IDs and retained 13 buffered rows
from the preceding runtime after the startup byte offset: offset/match ID
alone do not qualify a session. The timing audit retains the rejected mixed
attempt and its contiguous-tick1-based correction. Movement pairing uses
the independently bracketed native/input window, not those preceding rows.

Follow-up13retains38orders /2,101samples /705qualified pairs: median0.06888,
p95.15587,max**0.48321units**. The maximum coincides with an exact native
logical/root-model hold across100.96ms while navigation bit0 remains set and
correction time is zero, followed by a0.672-unit planar native advance. Nearby tick
lateness≤1.36ms/work≤2.37ms; no owner1070 appears in the window. First-wave
minion publication coincides with this interval, but causation is **unknown**.
This is targeted actor-state observation, not an FPS/display-time measurement.
An offline audit of the retained independent CE short run also finds an
111.82ms exact logical-position hold under the same active/zero-correction
predicate; the broad run has none. Different heroes, scenes, sample periods,
latency and unmeasured model state prohibit treating this as a tolerance or
equivalence claim. Evidence13:`post-recall-walk-gap.json`,
`normal-walk-correlation-1790085812892660400.json`; D:root
`reference-active-position-holds-1790086111306192600.json`.

## September 22: qualified prepared pursuit repair

The revised1017preserve-selection command fixes the command side effect but
does not alone fix speed. Read-only native attribute18/type30-component
observation proves the remaining split: authoritative5.7, native3.7 and no
native speed modifier. Adding the archived Skye600perk-control initialization
does **not** change that finding (10trial); it is not the speed fix.

Default-off`HALCYON_PUBLISH_SKYE_SPEED=1` now publishes only Skye's temporary
bonus via additive1052attribute18, including backward reduction and expiry;
equipment remains separate. The same identified attribute repairs omitted
equipment movement-speed publication and reconnect restoration.51focused
checks plus all seven exact production headless comparisons pass.

11`a-pursuit-01` measures0.30195-unit maximum logical/root-model gap, but its
overall result remainsFAIL: the verifier checked cooldown after the extra
diagnostic outlasted it. Expenditure is now checked against retained
post-ability/pre-diagnostic state, with a regression.17nonvisual ability
checks pass. Fresh11`a-pursuit-02` **PASS**:23paired reads, nine moving server
rows and nine active native-navigation rows, selected target retained,
maximum logical/root-model gap**0.25612units**. The living-target07baseline
was2.28697units with zero native navigation. This qualifies one prepared
post-A pursuit transition, not arbitrary motion, bone animation, six-client
PvP or official parity.12is the fresh ordinary ABC/Recall full-match trial.
Evidence D:`classic-live-11/a-pursuit-{01,02}`,`a-pursuit-01-model-audit.json`,
`pursuit-harness-02/pin.json`, and`pursuit-speed-headless-03/summary.json`.

## September 22: pursuit transition exposes a separate publication gap

Frozen06retained117ordinary move inputs and8466logical/root-model samples.
Offline pairing qualifies2193moving, unselected, zero-correction samples across
all117input windows (next-gesture boundaries, accepted target, clock envelope
1.28ms, nearest native sample≤25.2ms). Median gap0.05752units/p95.16491,
but one post-Barrage pursuit→walk transition reaches1.56427. This is diagnostic
data from a full-match exercise that later failed; not a smoothness verdict.
The remaining116windows are at most0.32343in this pairing, not a controlled
cross-run comparison.

At that transition the native client remains at`(4.377,5.839)` after A while
the server resumes pursuit. Native navigation flags stay0; five1070corrections
move it incrementally, leaving a gap inherited by the following ground order.
At the1.56-unit gap, tick lateness is below1ms and work below11ms. This specific
disagreement is not explained by a scheduler stall or straight-path geometry.

Default-off`HALCYON_PUBLISH_PURSUIT_INTENT=1` experimentally publishes accepted
human pursuit routes and a current-point stop at attack range. The initial08
1016experiment activates native navigation but **fails**: it clears native
selection and still reaches2.00467-unit disagreement. The stricter probe now
requires retained native selection too. Native927c40→d05d08 and callback
a124e0 identify1017XYZ movement with an explicit preserve-selection flag;
all244such records in the owned match6corpus set that flag. The workspace
experiment now uses that1017form; fresh qualification is pending. These are
publication changes, not new simulation orders; other subscribers retain
corrections. Earlier70checks/seven headless passes cover the initial1016form,
not proof of this revised client behavior.
See the prepared pursuit extension in the scenario leaf and checkpoint20.
Evidence D:`classic-live-06/normal-walk-correlation-1790079456391426200.json`,
`movement-divergence-01-pairs.json`, `movement-divergence-01-wire.json`.

## September 22: exact native path reproduction, remaining steering gap

The external `detour-oracle/` diagnostic builds public RecastNavigation v1.6.0
Detour against the owned baked asset. Native `df09f8` parameters (nearest-poly
extents1.5, 256-polygon corridor, three steering points, step1.0, slop0.01,
moveAlongSurface/fixupCorridor and detail height) reproduce a retained native
five-point corner path to float32 precision; a second four-point route matches
byte-exactly as float32. Native `df0f78` budgets distance in **3D**, unlike the
default planar server walk. This initial two-route finding was extended to
39active native routes and an opt-in3D backend; see the experimental qualification
under Checks below. Two path matches alone do not establish full query equivalence or
general client smoothness. Source/license/build provenance and comparisons stay
under the [ten-hour evidence root](classic-ten-hour-run.md).

## September 22: start/arrival correction repair and world-coordinate input

Fresh baked-mesh baseline `detour-live/model-short-01` retained2692 samples:
the first straight leg still reversed0.007335units, and the corner ended
0.178484units off target. Geometry helped but did not fix additive correction.

Production now withholds **normal accepted-walk start/retarget/arrival1070
from the owning connection**. The accepted1016 destination still publishes;
simulation, explicit stops/rejections, forced displacement, pursuit, reconnect
and other subscribers retain their contracts. `arrived_this_step` distinguishes
normal arrival from forced stops. `HALCYON_OWNER_WALK_ANCHORS=1` restores only
the historical anchors for diagnostic comparison; it is not the default.
**78 relevant server checks pass**, including unchanged interruption/reconnect
and observer semantics. The old anchor-count tests were explicitly revised to
the evidenced publication policy, not treated as smoothness tests.

Fresh Skye265/owner1500/slot0, connection2506693987664, clientPID32696:

| Existing no-recorder scenario run | Inputs / native samples | Measured result |
|---|---:|---|
| `anchor-policy-live/model-short-01` | 6 /2693 | Five straight legs: zero backward steps; all six final logical/root-model positions equal accepted float destinations |
| `anchor-policy-live/model-full-01` | 7 /4162 | Two straight legs: zero backward steps; five completed destinations equal; two deliberately superseded retargets |

Both measurement channels are real native reads. A few non-atomic samples
straddle entity/model updates (maximum observed difference0.06315); these are
not silently converted into atomic samples or animation claims. **Endpoint
agreement is not trajectory equivalence:** nearest-time server/native pairing
has a0.4642-unit moving discrepancy at the short corner and0.3664 on a later
retarget, with clock envelopes below1.6ms and nearest native samples within30ms.
This still requires route/steering and latency investigation. One early order
ack took68.3ms; retained timing reports expose catch-up rather than inferring
stalls from sparse1070. Logging cost remains outside `work_ms`.

**Reusable nonvisual world input is now live-qualified.** Native
`81ef94 -> 8bbfb0 -> 8bd5c8 -> 8b891c` identifies the active camera,
column-major view/projection and viewport. `camera_view()` rejects dirty,
changed, malformed or unowned state; `project_position()` performs scalar
projection. `movement-walk` accepts `world_points` (XYZ), retaining fresh
matrix provenance and refusing targets outside the qualified central playfield.
It never renders or reads pixels. A single projected probe ended0.0086units
from the intended world point (pixel rounding); the existing driver then
completed three world-point inputs /1152 native samples, all reaching accepted
destinations with zero measured reversals. A sloped-ground point differed0.2766
from the supplied world point: native ground picking is not assumed to be an
exact inverse of projection. **72 projection/driver/report/runner checks pass.**

The first world-route attempt correctly sent no input because its point was
off-screen: the idle owner had naturally died and respawned at base. Native
HP/EP/death counter agreed on inspection. No QA teleport or forced heal was
used in these walking/projection trials. General smoothness, combat-position
fidelity and complete-match acceptance remain open.

Evidence under the [ten-hour run root](classic-ten-hour-run.md):
`anchor-policy-live/*-analysis-*.json`, `wire-tick-timing-01.json`,
`client-tick-distance-1790068533719217700.json`, `native-camera-*`,
`projected-world-01/`, `world-route-01/` (refused), `world-route-02/`.

## September 22: native baked navigation replaces authoring geometry

**A client/server geometry mismatch is now proven and repaired in code.**
Native `c60ff4 -> df09b4/df09f8` binds the owner's navigation query to manager
`3110ca8`, mesh index0. Its 870 Detour-v7 tiles match the owned store asset
`4D/4D562D63B9D0796F7FCC5EC61ADB111B` byte-exactly for headers, vertices,
polygons and detail geometry (runtime-mutated links excluded). SHA256:
`9145ded654b5e0b6a542af63e00da09d40c3e24e75301bd7cda9267ff71a3fe2`.
The asset contains 1361 ground polygons /2530 detail triangles, connected,
with agent radius0.5 baked into clearance. This is not actor combat radius.

The previous raw A001 route from `(-73.935333,9.342721)` to
`(-73.786499,13.805074)` used corner `(-72.740685,12.202225)`, which is
**inside the client's baked obstacle**. Its first segment intersects the
baked boundary at `(-73.427959,10.557169)`. Server and client were not merely
choosing different routes across identical walkable geometry.

`server/navigation_store.py` now validates/imports this owned tiled ground
mesh; default production and scenario loading uses it. Legacy A001 remains
available explicitly for historical comparisons, never a silent fallback.
No geometry or proprietary tile bytes are tracked. The existing fixed-point
funnel remains; native `df09f8` uses Detour straight-path/moveAlongSurface
steering, so exact client/server route-algorithm equivalence is not claimed.

The corrected obstacles exposed a real melee/structure deadlock: a minion
stopped2.238units from a turret center while the old center-range gate was2.
Native `ca1284` adds the target's scaled definition radius; `c5b404` confirms
its bounding-radius formula. Qualified live values are2.15 for all ten turrets
and2.5 for both crystals. Pursuit and basic-attack checks now include those
structure radii. Other actors retain the explicit existing point-target
policy; sandbox minion ranges and ability AoE semantics were not relabeled.
**118 focused checks and seven exact production headless comparisons pass.**
Fresh client validation is recorded above; geometry alone left overshoot.

### Root model and remaining correction defect

The owned observer now optionally samples the **owner-bound root model world
matrix**, not just entity position. `c58004 -> interface+50/vslot168 ->
8ad524 -> d7cce0` leads to model translation; `d7ccd0` returns its matrix.
Component/model ownership, vtables, mesh resource, type, generation and affine
matrix are checked. This is not bone pose, camera projection or display time.

Before the baked-mesh repair, `spawn-live/model-short-01` retained2691 native
samples over six ordinary Skye inputs. One straight leg reversed0.007954units;
the corner leg ended0.434068units away from the accepted target. Its arrival
1070 started a half-second correction while native walking was still active;
native walking then stopped but correction continued, overshooting the target.
`c60dac/c6140c` independently explain this correction-plus-walking sequence.
This is a measured client-position defect, not proof of scheduler stalls.
The subsequent start/arrival publication repair and fresh comparison are above.

Evidence: `spawn-live/native-detour-1790065396004555700/`,
`asset-mesh-comparison-*`, `route-mesh-comparison-*`, `native-ranges-*`,
`movement-detail-*`, and `detour-range-headless-01/`, under the
[ten-hour run root](classic-ten-hour-run.md). No smoothness/full-match claim.

The [differential-validation decision](differential-validation.md) now defines
the scalable workflow. The existing movement inspector accepts `--client-run`
and explicit `--straight-walk` labels for offline native-state analysis; seven
retained runs reproduce the findings below in 3.49 seconds without live input.

## September 22 ten-hour run: funnel/edge repair and fresh client evidence

Deterministic portal string-pulling replaces midpoint detours without changing
A* corridor selection or collision checks. Owned return route: 19.36597→17.02884
units; independent square-hole route: 9.61693→analytic 8.32456. A separately
reproduced diagonal fixed-point edge stall is repaired with bounded two-
microunit safe-neighbour selection for ordinary hero/minion walking, preserving
the original distance budget. Forced displacement keeps first-wall behavior.

62 focused tests, 49 real-map traversals and the then-six production scenarios
passed. Fresh existing no-recorder client runs produced **14 inputs / 7,850
native samples** (Amael 925, EID1500/slot0). Six declared short straight legs
had zero backward logical steps. Five broad legs reached accepted targets
within 0.0000014 units; two were deliberately superseded. All 40 owner 1070
publications match adjacent simulation positions, without missing ticks or
unmatched updates. **Logical entity position is not model/render smoothness.**

Bots-active maxima: tick lateness 47.44 ms, work 82.29 ms, start gap 84.21 ms.
Logging overhead is not included in work_ms; profiling these peaks remains
open. Locale-encoded server prose no longer breaks the strict JSON trace
reader. Evidence: `navigation-live/` under the
[ten-hour run root](classic-ten-hour-run.md), including final `*-analysis-v3.json`
and retained failed setup/analysis attempts.

## External CE movement reference — 2026-09-22

**Independent service data is now available, not merely an unfilled reference
interface.** Only ordinary owned-client entry/input and passive observation
were used. No backend probes, crafted remote packets, screenshots or video.
The local Halcyon process stayed running while its guest-only routing was
reversibly removed. The exact local profile and routing were restored afterward.

### Qualified reference window

CE 4.13.4/build 147219; same pinned ARM64 library as the local observation.
External match `6dca139e-2b05-4952-884d-efac53841ba1`, connection **47546**,
server port 7028; owner **1500 / slot 0 / Amael 925** verified independently
from `1001`/`1011` and the native entity registry. Native draft labels reported
HARD despite the VERY EASY entry selection; difficulty is not independently
qualified. Bootstrap speed **3.9** agrees with Halcyon's Amael base stat.

The existing `Tools/run_scenarios.py --mode client --scenario movement-walk`
ran against passive reference JSONL, with the retained local short/full
profiles, `capture_backend=none`, and the same runtime observer:

| Window | Real inputs | Client samples | Result |
|---|---:|---:|---|
| `ce-short-fourth/` | 7 | 5,267 | Data-only PASS, no observer errors |
| `ce-full-fourth/` | 7 | 4,763 | Data-only PASS, no observer errors |

All 14 inputs have owner `1016` acknowledgements. Client-interface request to
ack intervals are **187.62–214.30 ms**: neither server processing time, pure
network RTT nor client-consumption latency. Start/end host/guest clock
brackets are retained; guest wall time was about 16.78 seconds ahead.
The broad battery has six published arrivals and one intentionally superseded
leg, not a missing-arrival regression. Presentation remains UNVERIFIED.

### What the independent reference changes

- Short straight legs have **2–3 owner `1070` updates**, compared with eight
  under the old local five-sample walking burst and three under the local fix.
  This falsifies assuming that the old local burst reproduced CE's sampled
  policy. It does **not** identify every CE publication rule.
- The six CE 4.6626-unit legs all contain backward logical steps using the
  same `>0.0001`-unit projection discriminator: totals **0.17767–0.33245 units
  per leg**, final target error at most **0.0000306 units**. Correction timers
  are active during those reversals. The patched local reproduction remains
  0/6; this is **not** a controlled cross-service A/B because latency and
  initial transient movement state differ. Do not copy CE's reversals or
  claim either service's model/render smoothness from this metric.
- Of **15,041 native `.vgr` frames**, none are `1070`, while the corresponding
  wire window contains **45 owner `1070` corrections**. All **14 ordinary
  owner `1016` records match wire payloads and order exactly**; one additional
  shorter native `1016` is also present. Replays are useful semantic evidence,
  but are not a complete post-decryption wire log or correction oracle.
  The empty final replay chunk is retained, not presented as a complete match.

No simulation/publication change was justified solely by this reference.
The local correction repair below stands on its controlled local experiment;
route quality, attack pursuit, remote observers and model transforms remain
separate open work. Saved reference packets/replays can now support offline
semantic extraction without spending another live entry window.

### Infrastructure findings, retained failures and evidence

Cached `Player.2.dat` contained a Halcyon-issued identity token, which failed
ordinary external login. After preserving the profile and clearing only
`uuid` / `initialAccount`, ordinary CE login succeeded. No token is copied
into source/docs. The fresh CE profile is retained privately for future use.

The initial reference adapter repeatedly decoded the whole growing capture,
delaying export beyond the driver's two-second input guard. The failed second
run's four inputs really exist on the wire: this is observation lag, not
missing input. Incremental processing removed that bottleneck: a retained
30,728-frame corpus took about 401 ms initially and 0.020 ms for an unchanged
decoder feed; live polls including ADB were about 62–97 ms in spot checks.
This is processing overhead, not an FPS or end-to-end latency measurement.

A third setup stopped with owner EID absent: wire-ready preceded native entity
creation. A bounded native-HUD wait before observer attachment allowed the
fourth entry to complete. The reusable movement observer still requires the
entity to exist when attached; `1137` alone is not a sufficient entry gate.
Native replay manifest **contents**, not its persistent session-named filename,
identify a fresh match. Earlier failed runs are retained and excluded from PASS.

Evidence root:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/reference-oracle-fbe90d43d76e4c3b9fe86693bd88f6ad/`.
Key artifacts: `passive-fourth/`, `fourth-match.pcap`, `fourth-match-vgr/`,
`ce-short-fourth/`, `ce-full-fourth/`, `ce-short-client-comparison.json`,
`ce-*-fourth-timing.json`, `native-wire-crosscheck.json`, `crosscheck_native.py`,
`fourth-entry.json`, `fourth-loading-labels.jsonl`, routing/profile backups,
`cleanup.json`, and source/diff manifests. Earlier match traces/replays are
preserved in their own first/second/third paths. New adapter/timestamp tests:
**20 pass**; prior full/headless results were not rerun or relabeled.

## Measured owner correction reversal and walking fix — 2026-09-22

**This supersedes the five-sample WALK mitigation and the input/UI unknown
below.** No screenshots, images, video or capture tooling were used. The
code-anchored accessor now measures the walking owner, not only a bot.

### Native UI blocker resolved

The active native widget tree identified **Choose a Build**. One Android
Back, guarded by that exact native title, removed the panel; a fresh tree
read verified its absence. The existing movement scenario then observed
**7/7 inputs and 4,194 owner position/correction samples**, without observer
errors. This was a setup/UI obstruction, not evidence of broken movement.
In that seven-input window, all 52 owner position publications match
adjacent authoritative tick states; maximum tick lateness/work is
3.86/15.72 ms. Server-observed input-to-ack time is 1.00–11.56 ms, not RTT or
client-consumption latency. This window does not support a scheduler-stall
explanation for the subsequently measured correction reversal.

The durable observer now checks native UI text before walking. Only an
identified build panel permits one setup Back; a remaining build/settings
panel or failed read stops execution. A bounded 25-second setup wait observes
native loading/Prepare For Battle text without input, then requires `BUY:`
and a match-clock label. Other/untranslated panels remain unclassified, and
missing `1012` still stops the scenario without retries.
The public movement path never enters its historical image-based driver.

New ELF anchors on the same pinned library:

- Root getter `0xe0061c`, global `0x3110ce8`; hit-test `0xe02710` walks
  first-child `+0x28` / next-sibling `+0x30`, requiring active flags `0x0c`.
- Text vtable `0x2726530`; destructor `0xe0d3a4`, storage getter `0xe08be8`
  and copy `0x810394` establish UTF-16 count `+0xd8`, buffer `+0xe0`.
- Reads are bounded to 1,024 active-tree nodes and 4,096 code units per label.
  This is structural traversal, not a heap scan or an ARM function call.

### Controlled short-walk comparison

Owned CE 4.13.4/build 147219, Amael 925, owner EID 1500, slot 0,
connection `2248447178448`, client PID 8322. After a declared warmup,
alternate screen inputs C `(620,330)` and A `(740,300)` every five seconds:
each accepted straight leg is approximately **4.6626 world units**.

| Policy / sequence | Short legs with backward logical motion | Owner `1070` per completed leg |
|---|---:|---:|
| Baseline five-sample walking burst, A1 | 6/6 | 8 |
| Diagnostic periodic-owner suppression, B | 0/6 | 3 |
| Restored baseline, A2 | 2/6 | 8 |
| Restarted production fix, no suppression file | 0/6 | 3 |

Baseline backward totals were **0.002060–0.012984 units per affected leg**.
The client correction timer/velocity remained active after reaching the
destination and pulled its logical position backward. The `1070` consumer
applies corrections over **0.5 s**. Removing periodic samples eliminated
the measured reversal in B; restoring them reproduced it in A2. This is a
phase-dependent defect, not an assertion that every baseline walk reverses.
All paired legs ultimately reached their accepted destinations.

Analysis projects successive client XZ samples onto each straight leg,
counting backward steps greater than `0.0001` units. Windows end at the
**next scripted input start**, not its later server receipt: local prediction
can already retarget before the server sees that packet. The threshold is a
measurement discriminator, not a smoothness acceptance threshold. Host/guest
monotonic alignment retains start/end RPC brackets; reads are non-atomic.
Arbitrary cornering paths must not be judged by straight-line projection.

### Scoped production change

`LOCAL_WALK_POSITION_BURST_SAMPLES = 0`: accepted walk orders retain their
start/retarget anchor and arrival/stop corrections, but no periodic owner
burst. Other clients retain 5 Hz updates. Attack pursuit retains its existing
five-sample policy; knockback, teleport, reconnect and authoritative movement
are unchanged. A walk also clears an unconsumed attack-pursuit burst.

**40 targeted tests pass** across `test_position_burst`,
`test_movement_publication`, `test_movement_timing`, and
`test_nonvisual_movement`: 37 initially, then the changed nonvisual module's
18 tests passed, including three new loading/HUD guards. The old five-sample WALK test premise was changed
because measured client evidence falsified it; authority, other-subscriber,
stop, knockback and reconnect assertions remain. Earlier full/headless
results were not rerun or relabeled as fresh client acceptance.

### Restarted default-path verification

The temporary suppression file was removed before restart and remained absent.
New connection **1808024818640**, owner **1500/slot 0/Amael 925**, client PID
**16490**, with identity checked from `1001`/`1011` and native entity state.
Native Android activity, text and widget-layout reads drove fresh Classic
Solo Bots 3v3 entry without images. An Android Google sign-in activity was
dismissed only after positive activity identification. Draft completed on its
normal timer; no server time acceleration or forced hero placement was used.

- **Short reproduction:** 7 inputs including a new-spawn warmup, **3,534
  samples**, no observer errors; all six paired 4.6626-unit legs have **zero
  measured backward steps**, three owner positions each, and zero final XZ
  error against accepted targets. All 21 publications match tick positions.
  Host/guest clock brackets: 2.223/2.030 ms, midpoint-offset drift 0.026 ms.
- **Broader battery:** 7 inputs, **4,197 samples**, no observer errors; six
  server arrivals and one server-superseded leg, all 19 publications match
  tick positions. The five fully settled client windows end within
  **0.0000011 units** of accepted targets. The two short retarget windows
  are not judged as client-arrival failures: conservative next-gesture
  boundaries exclude the subsequent ADB dispatch/receipt interval (about
  0.2 s here). Initial position was C after the paired run, not the earlier
  full battery's spawn; this is not an identical-initial-state A/B.
- Across both windows, maximum tick lateness/work is **3.61/17.91 ms**.
  Server-observed input-to-ack is **0.87–7.37 ms**, not RTT or consumption.
  Median native state-read duration is about **0.061 ms**; maxima are
  1.498/0.998 ms. This excludes other observer overhead and is not an FPS
  measurement. Tick `work_ms` excludes the movement-log write.

Retained failed setup runs informed the guard, not the movement metric:
`short-patched-default/` tapped after the wire ready echo but during native
loading; its missing input stopped execution. `short-patched-guarded/`
then demonstrated that an `Item Shop` label also remains beside the ordinary
HUD, so that label alone is not a modal discriminator. No movement was
attempted in that second run. The corrected known-panel/HUD guards passed
the successful `short-patched-hud/` and `full-patched-hud/` runs.

### Independent remaining finding and limits

The full walk's return path exposes a separate navigation-quality issue:
the current server route is **19.36597 units**; an external integer funnel
through the **same A* corridor** yields **17.02884 units**, with every segment
walkable. The current midpoint shortcut retains an avoidable detour. All
264 distinct sampled client positions on that leg lie on the server mesh,
but client and server routes differ. `server/navigation.py` was **not changed**;
the external probe is a candidate, not a qualified navigation repair.

Client logical-state reversal is now measured and a scoped publication repair
is implemented. **Model/render transforms, general movement smoothness,
attack-pursuit behavior and independent retail fidelity remain unverified.**
Server tick work excludes the movement-log write itself; logging and observer
overhead are present in every live comparison and must not be called zero.

Evidence root:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-consumer-7afd66619b9844dc9be89c3baa7541f6/`.
Key artifacts: `guarded-build-dismissal.json`, `owned-walk/`,
`owned-wire-tick-correlation.json`, `short-baseline/`,
`short-suppressed-paired/`, `short-baseline-return/`,
`paired-client-comparison.json`, `compare_client.py`, `funnel_probe.py`,
`prepatch-complete-wire.jsonl`, `short-patched-hud/`, `full-patched-hud/`,
their `*-correlation.json` / `*-ticks.log`, `short-patched-hud-analysis.json`,
`patched-runtime-costs.json`, `native-label-action-*.json`, and source/diff
manifests. The failed
`short-suppressed/` warmup was retained: it targeted the already reached C
and emitted no new input; the subsequent explicit paired profile omitted
that redundant warmup. It is not counted as a successful trial.

## Nonvisual client position and correction accessor — 2026-09-22

**Actual advance:** client logical position and navigation correction state
are now observable on the existing LDPlayer/Houdini installation. This
supersedes the earlier "no verified CE position accessor" limitation below.
It does **not** establish smooth owned-hero walking or observe a model/render
transform. No movement-publication policy changed in this round.

**Invariant:** AGENTS.md forbids image/video dependencies, including setup/UI
guards, FPS investigation and capture-tool work. Older screenshot/recording
procedures in this leaf are retained as historical evidence only. The
existing `Tools/run_scenarios.py --mode client --scenario movement-walk`
path now requires `capture_backend: none`, `drive_entry: false`, an explicit
live wire trace/connection, exact client build, focused game and matching
wire/runtime owner identity. It never invokes the historical visual entry.
Unqualified same-game panels remain an explicit unknown: a missing first
`1012` stops the battery, without another blind tap or entry retry.

### Qualified anchor chain

Owned CE 4.13.4/build 147219, ARM64 `libGameKindred.so`, SHA-256
`cd1b8831f82c469274613fc30f1f1f6e78c788102cdad7db5db2c04b96580a47`.
Addresses here are **ELF VAs**; existing Ghidra addresses add `0x100000`.
Runtime addresses must add the offset-zero file mapping's ASLR base, never
reuse this session's absolute pointers.

| Code anchor | Read-only structure/meaning |
|---|---|
| `1070` handler `0x8284bc` → action constructor `0xc05a8c` → apply `0xc05af8` | EID-attributed XYZ correction; apply passes duration **0.5 s**. |
| Entity lookup `0xc9e390` → registry enumeration `0x18889cc` / `0x18864b4` | Manager global `0x3114978`; registered entity type `0x2b09220`; pool descriptor stride `0x2e8`, entity EID `+0x260`. Enumerate bounded active indices, excluding pending removal. |
| Position accessor `0xc55794` | Raw XYZ at entity `+0x250/+0x254/+0x258`; planar server `(x,y)` corresponds to client `(X,Z)`. |
| Apply's component lookup; nav type global `0x304f724` | Entity component list `+0x18`, next `+0x20`, descriptor/type `+8/+0xa4`; nav owner `+0x10` must equal entity. |
| Correction setter `0xc60dac`, update near `0xc6140c` | Nav `+0x808/+0x80c/+0x810`: correction velocity; `+0x814`: remaining seconds. Distance threshold about **0.01 units** (`0x1a98284`). Updates integrate velocity over the smaller of elapsed time and remaining correction time. Non-null nav `+0x18` gates this correction path. |

`Tools/Teardown/observe_client_movement.py` and
`client_movement_observer.js` pin the owned library digest, compare mapped
handler/accessor bytes, derive the registry/entity/component chain, validate
identity/lifetime and read finite scalars. They use Frida's **native realm
for memory reads**, not translated ARM `Interceptor`/`NativeFunction` calls.
The only native function called is native-realm libc `clock_gettime`.
No broad heap search, ARM hook retry, game-state write or proprietary bytes
were added to Git. An already-owned Frida endpoint is required; this helper
does not install/start a daemon. The rooted process maps, not native module
enumeration, provide the ARM image base.

### Observations and limits

- Current match identity was **Amael 925, owner EID 1500, slot 0**, connection
  `2248448552144`, PID 8322; not the earlier Skye walk's session. The default
  Skye profile correctly failed SETUP before input. The explicit Amael
  profile qualified the stationary owner's position at spawn.
- A separate **moving bot EID 1515** observation retained **779 samples in
  7.987 s**, **193 distinct XYZ positions**, and **17 correction-timer resets**.
  All 17 had a preceding server `1070` within 150 ms; this is temporal
  association, not measured packet-consumption latency. The padded wire
  window contains 32 bot corrections. Maximum adjacent sampled displacement
  was 0.098144 units; this is not a smoothness acceptance threshold.
- Read duration median/max was **0.064/0.850 ms**, excluding other observer
  overhead. Samples are non-atomic and may straddle a client update. Start/end
  host↔guest monotonic RPC brackets were **2.475/2.537 ms** with midpoint
  offset drift **0.329 ms**. Keep the brackets; do not align guest wall time
  directly or treat midpoint estimates as exact clocks.
- The owned-hero walk stopped on its first missing `1012`. A bounded held-touch
  probe likewise failed input observation. Targeted Java forwarding then
  native-queue inspection proved correct `(870,365)` delivery: DOWN populated
  slot 0, ID 1, flags 9; flags advanced during the hold; UP produced flags 76;
  the slot was cleared afterward. The game view was initialized, not suspended
  and focused. JNI `0x7f638c` has a live context/callback and scale 1.0; callback
  `0x18843c8` writes through `0x1884460` into manager global `0x3114448`.
  Queue update `0x1881058` copies input into the consumer view and advances
  flags. **Native UI/world-input selection after that remains unknown.** No
  new world order was observed; do not call this a walking regression or
  infer that Android input is still hung. Further retries need a new guard
  or downstream anchor, not guessed coordinates.
- The namespace split no longer blocks anchored data reads. ARM interception
  and broad heap scans remain closed. Next useful client anchors are the
  native touch consumer (`0x18807cc` → `0x1881254`) and the downstream world/UI
  decision, plus a model-transform accessor if presentation needs separating
  from logical locomotion. The owned-hero client/server trajectory comparison
  remains unperformed in this match.

**Checks:** 24 tests passed: `test_nonvisual_movement` (12),
`test_movement_timing` (9), `test_entry_foreground` (3). New tests reject
capture/legacy-entry profiles, wrong/ambiguous/stale identity and unpinned
libraries; stop after missing input or observer failure; retain cleanup/error
evidence; and explicitly refuse smoothness acceptance on a data-only PASS.
The full server/headless suites were not repeated without a simulation change.

External evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-anchor-5fcfccbd88744b74955364341709dd92/`
contains `source.json`, `entity-qualification.json`, `stationary-client.jsonl`,
`observer-bot1515.jsonl` and clock metadata, `bot-client-wire-correlation.json`,
`bot-window-wire.jsonl`, `nonvisual-walk/`, `nonvisual-amael/`,
`held-input-probe/`, `java-forward-input.json`, `java-to-native-touch.json`,
text-only Android activity/input state and bounded external disassembly.
No images/video were used or produced for this round.

## Walking-stutter investigation — 2026-09-20

Operator reports the local hero jerking while walking. **Visible stutter is
still OPEN**, not fixed by the following bounded investigation. Classic mode
was restored; same-hero mode and temporary correction suppression are off.

Owned CE 4.13.4/build 147219, emulator-5554 at 960x540, Catherine, normal local
simulation. After ordinary Recall to the fountain, scripted walks used one
UI tap each. The first uncontrolled recording contained 47 movement requests
and one target request in 12 seconds; it was not accepted as a controlled walk.
An earlier menu-return launch failure is setup failure, not a movement defect.

Two controlled comparisons retained the same fountain start `(-78.18, 0.88)`
and effectively the same destination `(-64.37434, 1.65080)` (native float
rounding differences under 0.00002 units). In each comparison, normal mode
published 19 sampled `1070` positions; the existing temporary suppression
diagnostic published two start/end samples. Each walk had exactly one `1012`,
reached its target, and had no sampled backward route progression. These
samples do not measure client animation or all intermediate simulation ticks.

Android screenrecord produced only about 4 FPS while LDPlayer was minimized.
It cannot resolve a claimed 5 Hz correction jerk. After restoring the window,
the FPS overlay read 60 and host-window capture supplied 270 frames per clip
at approximately 30 FPS. A background-patch phase-correlation diagnostic did
not establish a clear improvement from correction suppression. It measures
camera/scene motion, **not** tracked hero-sprite motion; repeated retargeting,
corners and Skye-specific animation still need controlled tests. The legacy
`HALCYON_SPARSE_1070` budget is set but not consumed by publication; no new
sparse policy or speculative default change was enabled in this pass.

**Separate concrete fix:** `_apply_event` formerly emitted `1016` toward the
raw click after `HeroMovement.set_target` had projected or rejected its route.
It now publishes the accepted `sim.move_target` only when navigation actually
starts. Rejected disconnected destinations emit no new client movement order;
existing stop/position frames remain intact. This removes a client/server
destination inconsistency, but does not establish the cause of all stutter.

`python -B -m unittest server.test.test_movement_publication
server.test.test_hero_movement server.test.test_navigation_lifecycle
server.test.test_navigation_clipping server.test.test_same_hero` passed **56
tests**. The new tests exercise projected endpoints on both client streams,
disconnected-route rejection, valid clicks and stop-frame preservation through
the production input handler. Videos precede this patch; rendered acceptance
of the destination fix is not claimed. The patched Classic stack was restarted.

External evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-a4108d0c32dd45a19e46550a11b19190/`
contains `controlled-summary.json`, `host-summary.json`, `host-A.mp4`,
`host-B.mp4`, per-walk geometry reports, preserved wire traces,
`host-motion-diagnostic.json`, `surface-latency.txt` and `result.json`.
Temporary `suppress_1070.json` was removed in a `finally` block; no QA teleport,
forced cast, altered movement speed or disabled simulation subsystem was used.

2026-09-07 implementation and corpus audit. This is a record of measured
contracts and explicit sandbox rules, not a claim that live-client acceptance
or full Vainglory fidelity is complete.

## Walking-stutter — corpus-faithful burst publication, rendered A/B — 2026-09-21

Follow-up to the 2026-09-20 investigation. A candidate correction-publication
change is implemented server-side and verified on the wire; visible-smoothness at full
framerate is staged for human review (videos retained), not human-accepted.

**Measured publication difference; causal hypothesis.** Against the owned CE client the local server answered its
own hero's accepted walk with a continuous ~5 Hz stream of periodic `1070`
locomotion corrections for the whole walk (before trace
`wire-1789932914385631100.jsonl`: 22 position frames in a 4.05 s straight
walk, ~0.21 s gaps, stream exactly spans `is_moving`). The native corpus
(vgfull eid 1500) answers each accepted order with a 2–6 sample burst and
then goes quiet while the client walks its own hero locally — 39 `1070`s in
the whole match, none mid-walk. Surplus corrections may conflict with client
locomotion; these observations do not by themselves establish that they cause
the reported visible jerking.

**Fix (server/match_server.py).** `LOCAL_POSITION_BURST_SAMPLES = 5`: each
accepted move/attack order arms a 5-sample burst consumed by the periodic
locomotion stream; after exhaustion, periodic locomotion `1070`s are
withheld **from the owner only** (every other client keeps the full stream),
and order-anchored frames (1016 echoes, start/stop doubles, teleports,
knockback) never reach the gate. Publication gate only — the simulation,
its tick, and every other subscriber are untouched (asserted by
`test_position_burst.test_burst_consumption_never_touches_the_simulation_state`
and `test_owner_presence_cannot_change_the_trajectory`). The legacy
`HALCYON_SPARSE_1070` budget remains set-but-unconsumed and no suppression
env/file is in play; Classic is enabled.

**Wire A/B (same 7-tap plan, same walk targets).** BEFORE (run-18): 98
hero-position frames in the battery window, 5 Hz stream spanning each walk.
AFTER (run-08, run-10): 52–54 frames — per order ≤5 burst samples plus the
order-anchored arrival double (straight walk: 8 frames vs 22), multi-second
owner silence mid-walk. Accepted-endpoint repair verified on the rendered
client in both runs: every completed walk's last published position equals
its `1016` target exactly (e.g. run-10: tap0 → (-63.23, -1.16), tap6 →
(-80.65, -6.47)); the interrupted retarget leg is superseded by the next
order, as designed. The off-mesh projection case stays **UNVERIFIED on the
client** (unit-tested only; the walk plan contains no off-mesh destination).

**Rendered A/B (LDPlayer 960x540, 30 FPS host capture, CE 4.13.4 build
147219).** before-run-18 and after-run-10 both PASS the battery gates
(SETUP world bootstrap, 7/7 c2s `1012` wire-truth, live capture with
distinct-frame share 0.77–1.0). Frame strips through the straight walk show
the same fountain→lane path completing in both. The hero-relative motion
instrument (nameplate centroid minus phase-correlated world shift) on the
clean-tracking walks: corners/retarget BEFORE 26/43/14 backward frames and
rms 1.17–2.62 px → AFTER 0/0/0 and rms 0.10–0.16 px; the straight window is
confounded by pre-walk world-settle frames (walk-only recomputation: 35 →
18 frame-to-frame reversals, dominated by nameplate run-cycle bob), so
cross-run excursion counts are indicative, not decisive.

**Human visual acceptance remains the deciding step** for "the jerk is
gone": the two 30 FPS recordings are retained for full-framerate review at
`C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-qualify-skye-wip/`
(`before-run-18/host-movement-walk-20260921-023611.mp4`,
`after-run-10/host-movement-walk-20260921-041259.mp4`, with
`motion-analysis.json`, per-walk CSVs, wire traces
`wire-1789932914385631100/1789937626750734900/1789938720272174000.jsonl`
under `%TEMP%/halcyon_stack`, and per-run `client-result-*.json`).

**Entry-drive hardening (Tools/scenario_client.py)** — required to obtain
stable rendered entries; mock-free changes verified live:
late sign-in dialogs can pop between any two draft taps and dismissing one
can leave the draft aborted on the plain menu (after-run-05/07/09). The
drive now (a) dismisses GPG/sign-in dialogs before every draft tap,
(b) positively re-verifies the mode dialog before the tap that leaves it,
(c) detects swallowed taps by exact-frame comparison (measured 0.0 for
swallowed, ≥9.5 for advanced) and restarts the whole entry chain from PLAY
(bounded ×3) instead of driving blind, (d) cancels the re-popping GMS
sign-in activity in a bounded loop, and (e) gates the battery on a
host-vs-guest surface comparison (store-ad/black presentation wedge:
matching world 7.5, ad 31.0, black 56.2; threshold 15) so a wasted battery
cannot be filmed against an ad. Focused movement suites pass 62 (56 prior +
6 `test_position_burst`); the scenario-client/runner suites pass 306.

2026-09-21 implementation and A/B audit. Sim verification is exact;
rendered smoothness is staged, not yet human-accepted; full Vainglory
fidelity remains open.

## Direct follow-up — 2026-09-21 evening

No new server movement policy was introduced in this follow-up. Added production
regression coverage for an exhausted owner burst: stun stop doubles still reach
owner and observer, knockback positions still reach both, and reconnect catch-up
includes the current route and position. The six focused movement suites passed
**65 tests**. These are simulation/wire checks, not rendered acceptance.

`Tools/scenario_client.py` now cancels the observed native GMS sign-in activity
with Android Back rather than an obsolete fixed Cancel coordinate, avoids
relaunching a game that already regained focus, and does not interpret a static
sign-in dialog as a frozen renderer. Recovery rechecks the foreign package on
each retry. Three focused foreground regression tests pass. Entry exhaustion
and host-surface mismatch diagnostics no longer assert an unobserved cause.

Owned LDPlayer and the Classic stack were restarted; guest routing/certificate
overlays were restored through the existing `server.platform.guest_setup`.
Three bounded attempts are retained in external evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-direct-ca0737b2a005498ab5a455e9e3692d71/`.
`live-default` failed connection setup; `live-routed` was blocked by the native
sign-in activity; `live-entry-fixed` reached a fresh Skye match (CE 4.13.4 build
147219), then correctly failed the pre-battery capture gate. Its host screenshot
showed an unrelated covering desktop window while its guest screenshot showed
the live game (host/guest difference 36.9). No walking battery ran in these
attempts. Keep LDPlayer visible and uncovered for the next controlled recording.
Visible walking smoothness and rendered off-mesh behavior remain **OPEN**.

Broader harness check: `test_entry_foreground`, `test_scenario_client`, and
`test_scenario_runner` completed 308 tests in 978.476 seconds with one failure
(307 passed). `TestMinionPairComparison.test_an_event_spacing_change_beyond_the_margin_is_refused`
failed its census-schedule premise: frame 6 differed by 0.603942 seconds versus
the unchanged 0.1-second fixture limit. An isolated rerun passed in 30.666 seconds
without modifying the test or limit, supporting a timing-sensitive fixture
failure; the full run is still recorded as failed, not retroactively green.
The final foreground module (three tests, including retry-package refresh) was
checked separately after the broad run loaded its earlier two-test version.
`direct-check-summary.json` records these results in the external directory.
`git diff --check` passes. No commits were made.

## ADB walking capture — 2026-09-21 late evening

At the operator's request, movement-walk now defaults to the existing owned
ADB screenrecord lifecycle (`capture_backend: adb`); the optional `host` backend
retains its host-surface gate, which is not used for ADB. Decode inspection is
streamed instead of allocating the whole video. Native timestamp probing avoids
mistaking imageio's CFR-expanded frames for actual capture cadence.

Fresh Skye entry and seven scripted taps succeeded on CE 4.13.4/147219. All seven
`1012` inputs reached the server. Four completed legs in the recording ended
exactly at their accepted `1016` target; two legs were deliberately retargeted.
The final return finished after recording ended, as seen in the retained trace.
Six routes with a preceding position sample had no sampled backwards progress;
the first route lacks that preceding `1070` and its geometry remains unverified.

**Capture limitation:** the approximately 40.14-second ADB file contains only
166 native frames (~4.11 FPS; maximum gap 0.3002 seconds), not the 2,424 frames
reported by CFR-expanding decode. This is insufficient for judging the reported
walking jerk. Harness PASS means captured live input, not smoothness acceptance.
Native cadence reporting was added after this run; the original result is
preserved alongside the corrected `adb-verification.json`.

Evidence directory:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-adb-54b8e33054f84a4e95664d2105b43c3e/`
contains the MP4, original client result, native timestamp log, wire snapshot,
`walk-geometry.json`, and `accepted-targets.json` (the latter is bounded by the
recording interval). Capture ownership/failure/lifecycle and entry checks passed
15 tests; final syntax and whitespace checks passed. Smoothness remains OPEN.

## Data-only scheduler investigation — 2026-09-21

Operator explicitly prohibited video. `movement-walk` now defaults to
`capture_backend: none`; it runs the existing UI/wire sequence without starting
either recorder or running video/surface liveness checks. Entry UI guards remain.
Presentation is explicitly UNVERIFIED; a data-only PASS is not client smoothness.

**Concrete scheduler defect fixed:** `_run_world` waited `WORLD_PUMP_TICK` (50 ms)
after tick work, even when the next deadline was sooner. A controlled-clock
regression through the production world loop, with 12 ms tick work, reproduced
tick 2 at 112 ms rather than 100 ms before the fix. The pump now waits only until
the next fixed-tick deadline (bounded to 0–50 ms). Twenty ticks meet their exact
deadlines in that fixture after the fix. This changes scheduling, not simulation
step size, and does not establish the cause of the operator's visible jerk.

`HALCYON_TRACE_MOVEMENT=1` enables `[movement-tick]` JSON records in the existing
server log: simulation tick/time, host timestamps, deadline lateness, tick work
duration, and each human hero's fixed-point position/order/target/burst budget.
Disabled by default. Logging costs time; measured live lateness includes probe
overhead. Wall-clock diagnostics never feed simulation state.

The existing inspector now supports `trace <path> --timing --slot 0 --eid 1500`
without loading a mesh. It attributes `1016` acknowledgements to the selected
slot and position samples to the EID, respecting retarget boundaries. On the
retained seven-input trace, server input-to-ack delays were 0.916–3.179 ms;
five legs arrived, two were superseded. These are server-observed intervals,
not client consumption latency or network RTT.

**Client instrumentation qualification:** PID 6675's `/proc/maps` contains
ARM64 `libGameKindred.so` and Houdini. A same-session no-op Frida native observer
enumerated 195 modules, including Houdini but not Kindred. This confirms the
namespace visibility split; it does not provide a client-position hook. No
blind ARM hook/heap scan was attempted. The temporary Frida daemon was stopped.

A fresh data-only client attempt failed SETUP on a 15-second ADB input-tap
timeout before any movement battery. Its result is retained, not a regression
claim; no new live scheduler measurements or client smoothness acceptance.

Checks: **69 focused tests pass**, including the formerly failing scheduling
fixture, timing attribution and non-mutating telemetry. All **six production
headless scenarios pass exact two-seed comparison**. Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-data-924b22d09c3e436d8015635944f1d099/`
(`wire-timing.json`, maps/module qualification, `live-data` setup failure,
`headless-after/summary.json`). No video was recorded for this investigation.

## No-recorder live tick/wire correlation — 2026-09-21

**Walking smoothness remains OPEN.** This follow-up validates the existing
deadline scheduler repair in a fresh local run; it does not establish a new
movement-policy fix or client smoothness. No video, recording, FPS work,
delegation, forced movement or QA preparation was used.

### Setup and identity

The existing Classic stack was still listening (launcher 28936, server 1148).
ADB responded, but the game process was absent and Android was on the launcher.
A harmless `input keyevent 0` completed in 0.209 s. One normal package launch
restored CE process 8322, followed by **one** existing `movement-walk` invocation
with explicit `capture_backend: none`. Its bounded entry guards handled the
sign-in flow, and the client reached WORLD. No emulator restart or blind entry
retry was needed. Afterwards the same game PID remained foreground and the
input-health check completed in 0.212 s.

The retained crash buffer contains an earlier 22:05:18 SIGSEGV, PID 6526,
fault address `0x2a0`, with Houdini frames. This is not the previous qualification
PID 6675 and does **not** establish the cause of the latest missing process or
input timeout. That setup failure is not reclassified as a gameplay regression.

Owned CE **4.13.4/build 147219**, LDPlayer `127.0.0.1:5555`, 960×540. Connection
**2248426425296** is pinned in the copied wire trace. Identity was verified from
`1001` line 1 (owner EID 1500), and `1011` line 462 (hero 265/Skye, EID 1500,
compact slot 0). The initial published movement speed is float32
3.700000047683716, consistent with the server's 3.7 units/s base speed.

### Measured results and limits

- The driver reports **7/7 C2S 1012 inputs**, data-only PASS, presentation
  UNVERIFIED. Its other gameplay stages are not promoted from PENDING by that
  PASS; the separate correlation below establishes the measured server effects.
- Input-to-1016 intervals are **0.890–3.108 ms** at server trace points. These
  precede S2C `sendall`; they are **not** delivery, RTT or client-consumption
  measurements.
- **Six** requests reached their accepted destination, and **one** was
  superseded. Unlike the older seven-input battery, the second retarget leg
  completed 1.079 s after input, just before the next input. Do not carry the
  older five-arrival/two-superseded census onto this run. The final return
  arrived after the driver's four-second final wait; retained trace coverage
  includes that arrival at 4.150 s after input.
- All **54** owner `1070` publications match either the preceding or following
  authoritative tick's position **exactly as float32**. This includes order
  anchors, the five periodic samples per order and stop doubles, with no
  unmatched or unbracketed publications. Matching server records cannot reveal
  the correction distance from the client's own predicted position.
- Across the seven input-to-next-intent/10-second windows, tick-start gaps are
  **47.121–52.586 ms**, maximum lateness **3.478 ms**, maximum tick work
  **34.091 ms**. No missing ticks, zero-distance same-order moving steps, or
  steps beyond **0.185 units** (3.7 × 0.05) were found. Short final steps are
  expected at arrival. All window order versions are distinct, 1 through 7.
- Authoritative positions stay within **0.000008 units** of the reconstructed
  accepted routes, with no backwards route progression above 0.02 units.
  The labels `corner-a` and `corner-b` are actually direct routes in this run;
  the **return** is the measured two-segment route through
  `(-78.270912, -3.673187)`. Labels alone do not prove corner coverage.
- A separate 8,790-tick sample, simulation 0.05–439.5 s, has no tick work above
  50 ms. Only the first two startup ticks exceed 50 ms lateness (91.689 and
  61.899 ms), before the walking inputs. The last 60 simulated seconds have
  maximum lateness 3.306 ms and maximum work 20.277 ms. This finite observation
  is not a 30-minute stability result or multiplayer-load acceptance.

`HALCYON_TRACE_WIRE` and `HALCYON_TRACE_MOVEMENT` were both enabled. Wire logging
inside simulation contributes to `work_ms`; movement JSON serialization and
log I/O occur **after** that duration is measured. Their costs still affect
subsequent tick gaps/lateness. The observed wall/monotonic offset spread in the
joined window is 0.0234 ms; timestamps from different clock domains were not
equated. No logging-free performance claim is made.

### Reproduction and checks

External evidence root:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-followup-1a4cd047a84a41cf83ad262c73597a5d/`.
It retains the initial worktree diff, relevant source copies/hashes, health
checks, explicit no-video profile, original `live-data/client-result-1790007484.json`,
`wire.jsonl`, `gateway-log.txt`, `identity.json`, `correlation.json`,
`authoritative-route-check.json`, and targeted test output. Old evidence was
not deleted. The already-patched runtime was not restarted in this round.

```powershell
$evidence = 'C:/Users/terasumi/AppData/Local/halcyon-evidence/movement-followup-1a4cd047a84a41cf83ad262c73597a5d'
# Live command used a fresh output subdirectory and no-video.json containing:
# {"movement_walk":{"capture_backend":"none"}}
python -B Tools/run_scenarios.py --mode client --scenario movement-walk --adb-serial 127.0.0.1:5555 --client-profile "$evidence/no-video.json" --output <new-external-directory> --timeout 25
# Read-only analysis of this retained session; identity is verified above.
python -B Tools/Teardown/inspect_movement_trace.py trace "$evidence/wire.jsonl" --connection 2248426425296 --timing --eid 1500 --slot 0 --tick-log "$evidence/gateway-log.txt"
python -B -m unittest server.test.test_movement_timing
```

The existing inspector now provides `--tick-log` and optional `--match-id`
selection for timing reports. It preserves retarget boundaries, rejects mixed
sessions/tick resets/clock reversals, reports missing ticks and partial log
tails, and does not interpolate positions across missing ticks. **Nine tests
pass**, including bounded synthetic log cases and production-loop fixtures
with 8 ms telemetry cost and a transient 120 ms tick overrun. The scheduler
recovers deadlines while retaining every fixed 50 ms simulation step and the
same final authoritative movement. The earlier full focused/headless results
are retained; they were not needlessly rerun for this analysis-only extension.

**Remaining uncertainty:** there is still no verified CE position accessor on
translated LDPlayer. The previously proven Kindred/Houdini namespace split
remains the instrumentation limit; no blind ARM hooks or heap scans were
repeated. Client receipt/consumption timing, local path interpolation and
presentation are unmeasured. These results do not support ongoing server
scheduling catch-up or stale server-coordinate publication as the explanation
**within the measured walking windows**; they do not rule out client-side
correction conflicts or untested scenarios. Keep smoothness acceptance open.

## Terrain and deterministic movement

`server/navigation.py` reads the operator's external Halcyon Fold A001 mesh.
The local verified source is:

```text
D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/4B/4BD271EAAC785AEB0C2BCED99515D401
```

It has 793 vertices and 832 triangles. No mesh data is copied into the repo.
Set `HALCYON_NAVMESH` to use a different operator-owned copy. Missing or
malformed input fails explicitly; it does not fall back to straight-line
travel through walls. Format reference:
`Docs/Teardown/vainglory-3v3-map-structure.md`.

Positions use a lattice of one million units per world unit. Triangle A*
uses integer costs and deterministic ties; visibility smoothing removes
unnecessary portal waypoints. Clicks outside the mesh project to a walkable
edge; disconnected destinations do not yield a wall-crossing route. Ordinary
movement and knockback clamp to the walkable segment. Dash crossing follows
the attachment's rule: a requested endpoint past the midpoint of a thin wall
can land beyond it, while a thick wall stops the dash at its near edge.

Movement speed is evaluated each tick as:

```text
((1 + attr_0x284) * attr_0x11C + attr_0x68) * (1 + attr_0x1D0)
```

Hero movement, minion pursuit and jungle pursuit use the same mesh. Path
planning is repeated after a moving target shifts by at least 0.25 units.

The nearest-point query formerly projected onto every edge using Fraction
objects. It now visits conservative triangle bounds in distance order,
uses exact integer rational projection, and caches bounded immutable queries.
The rounding and distance/index/coordinate tie order remain unchanged. An
independent comparison against the former exhaustive Fraction calculation
matched all coordinates and triangle IDs for 66 queries across the external
mesh, including obstacle and off-map regions: 2,405.55 ms became 35.79 ms.
The 60-second production workload then met all 1,200 fixed-tick deadlines:
maximum 29.79 ms, previously 88.96 ms; p99 13.50 ms, previously 40.61 ms.
These are local measurements, not a guarantee for arbitrary load or hardware.

A later 935–945-second workload exposed repeated path smoothing. Bounded
immutable full-path (4,096 entries) and segment-interval (16,384 entries)
caches now avoid recomputing identical geometry. Public route lists are
copied to prevent one actor mutating another actor's cached path. Forty-eight
actual-mesh paths and segments matched the uncached routines exactly;
mutation of every returned route left subsequent queries unchanged. A hot
batch of 4,800 path queries took 5.05 ms. The final production workload is
verified separately rather than extrapolating that microbenchmark.

### Late clipping bursts, 2026-09-08

The final old-fixture run exposed three repeatable CPU stalls at simulation
seconds 952.70, 956.55 and 956.75. Individual tick profiles identified bursts
of uncached path smoothing: respectively 12, 12 and 19 new paths performed
313, 226 and 390 raw segment clips. Clipping consumed 43, 31 and 59 ms of
the instrumented ticks. The aggregate 946–960-second profile had instead
been dominated by routine wave targeting. A separate garbage-collection
diagnostic found no collection within 0.12 seconds of any of these stalls.

Clipping now uses precomputed exact integer edge half-planes, rejects
triangles whose bounds are strictly disjoint from the segment bounds, and
returns once a convex triangle covers the entire segment. Boundaries and
corner touches remain inclusive. Integer rational interval comparisons and
the resulting union are preserved. Three independent exhaustive Fraction
oracle tests cover 449 segment cases, including holes, negative cells,
clockwise input, zero-length segments, external mesh routes and microunit
edge crossings. All 96 focused navigation, lifecycle and wave tests passed.

An external copy of the original failed source pin changed only
`server/navigation.py` and reran all 19,200 ticks. Its 4,379,174-byte wire
stream, 1,942,184-byte canonical final state and all 960 state checkpoints
were directly byte-equal to the original run. Coverage was also identical.
All ticks met 50 ms: p95 7.273 ms, p99 9.485 ms and maximum 26.428 ms.
The three former stalls measured 23.869, 18.638 and 26.428 ms respectively.
This original controller still completed no Recall; the strengthened final
fixture's full acceptance is recorded in `solo-sandbox-performance.md`.

Artifacts remain external under TEMP:
`halcyon-sandbox-exact-spikes-20260908/` contains the individual profiles;
`halcyon-sandbox-gc-946-960-20260908/gc-events.json` contains collection
observations; `halcyon-sandbox-nav-optimized-old-fixture-20260908/` contains
the isolated source copy and complete comparison run.

## Compact actor slots: the bootstrap collision correction

The byte at +116 in the 126-byte `1010` actor creation record is a reusable
actor slot. `1016 ActionMoveTo` addresses that same slot. It is **not** an
ever-increasing sequence counter. The six hero slots are 0 through 5.

The complete external `vgfull.pcap` contains 174 actor creations and 116 slot
reuses. Every reuse follows destruction and removal of the prior owner.
Example: frame 4583 assigns slot 34 to EID 4579 after EID 4315's `1073` at
4375 and `1035` at 4391. Every one of the 100 lane spawns has a subsequent
`1016` with its assigned slot; four captain spawns insert an attribute record
before that movement action.

`server/actor_slots.py` owns one map per match:

- `register(eid, slot)` records measured hero/static/tape mappings.
- `allocate(eid)` keeps an existing mapping or chooses the lowest free slot.
- `release(eid)` frees a removed actor; hero death does not remove its actor.
- `observe(opcode, payload)` registers 126-byte creations and observes `1035`.

Jungle, lane, static and hero publication share that allocator. A reconnect
keeps the original mapping. Live ownership conflicts and capacity exhaustion
raise an error instead of wrapping onto a hero or another living actor.

The live bootstrap trace exposed five actual collisions in the previous
counter implementation: slots 28 through 32, still owned by EIDs 3561 through
3565, were overwritten by jungle EIDs 100000 through 100004. Counting the
26 static tape records was not equivalent to reading their assigned slots.
The session now seeds the allocator from each record's actual EID and slot.

## Jungle creation and objectives

`server/entity_spawn.py` loads external 126-byte actor templates instead of
embedding unknown serializer bytes. `HALCYON_SPAWN_CORPUS` accepts directories
containing the operator's VGR chunks, separated by the OS path separator.
Default local inputs are under `$TEMP/vg_phaseB/vgr_live`,
`$TEMP/vg_max/vgr5/vgr5` and `$TEMP/vg_max/vgr/vgrtmp`.

The decoded registry and corpus agree on these archetypes:

| Archetype | Actor |
|---|---|
| 357 | Treant |
| 358 | Elder Treant |
| 359 | Big Bear |
| 360 | Small Bear |
| 361 | Crystal Miner |
| 362 | Gold Miner |
| 363 | Neutral Kraken |
| 364 | Captured Kraken, registry-proved only |

The measured jungle class is `4dd5b7d0`; +0 is the archetype and +8 is the
actual actor EID. Unresolved bytes +92 through +95 vary between captures and
remain in the external template. Known identity, position, facing and actor
slot fields are patched explicitly. Jungle EIDs start at 100000 to avoid
collision with lane allocation, which starts at 4610.

Gold Miner appears at 240 seconds at `(0, 23.6)`, accumulates up to 300 gold,
pays the capturing team and remains as its guardian. Kraken appears at 900
seconds, replaces Gold Miner, and uses the requested 5000 HP, 400 armor and
100 shield. Capturing it changes authoritative ownership and sends it via
the lane to vulnerable enemy structures.

Neutral Kraken creation is directly measured in match
`a683aa80-9811-47c3-bb64-0731a802e889`, chunk 72, row 1062 under
`$TEMP/vg_phaseB/vgr_live`. An 830-file VGR scan found no archetype-364
creation. Faction-changing actor replacement is therefore an explicit
own-client adapter behind `HALCYON_EXPERIMENTAL_CAPTURE`, with bounded
team-1 Gold/Kraken live acceptance recorded in the jungle leaf. It does not
claim complete native capture-protocol recovery. The adapter emits death for the defeated actor,
retains its corpse/slot, and creates a fresh owned actor with an explicit
current/max-HP snapshot. Lethal damage still addresses the old EID before
those messages. The old assumption that +120 means `team - 1` was falsified;
that actor-specific byte is preserved. See
[jungle wire lifecycle and client QA](solo-sandbox-jungle-wire.md) for the
22 native death chains, capture adapter, faction evidence and remaining gates.

The attachment leaves several coefficients unspecified. Current sandbox
policy is gold fill 1 per second, buffs for 90 seconds, Weapon Buff slow 15%
for 2 seconds and 10 true damage per second for 3 seconds, Crystal Buff +30
CP and +5 energy regeneration. These are explicit implementation choices.

## Waves and formation

The measured wave cadence is 25 seconds; the first wave begins at 22.974
seconds. The requested sandbox composition is three melee and two ranged
units per side, with one extra siege unit every third wave. Melee range is
2 units and ranged range is 6.5. Registry 367 is siege; 368 is captain.
`corpus_profile=True` preserves the previous measured wave composition for
comparisons instead of conflating it with the attachment's desired profile.

Current policy increases HP 10% and damage 5% per elapsed spawn minute and
uses 0.75-unit ally spacing. Survivors pursue targets and then vulnerable
structures. In a standalone lane without structures they close the next
enemy formation instead of parking just outside aggro range and blocking
all subsequent waves. Paused movement time is not accumulated into a later
teleport.

The early spawn grammar is verified: `1010`, slot-addressed `1016`, current
`1070`, then measured visibility-field messages `1067`. Visibility messages
are not movement or animation state selectors. Fifty early `vgfull` lane
spawns match the current builder byte for byte. Fifty later spawns vary
bytes +88 and +119. Their exact growth/stage meaning remains open, so the
server's stat-growth rule does not establish matching native growth display.

### Lane death, corpse retention and reconnect

The full `vgfull.pcap` contains 83 lane-minion removals. Every one has a
preceding `1072 [victim EID][killer EID][six zeros]`. Death precedes `1073`
by 3.759–3.861 seconds of TCP receive time; `1073` and `1035` themselves
share the same receive timestamp in all 83 cases. The implementation uses
a fixed 3.8-second corpse period. This is a measured approximation of the
native timing, not evidence for an arbitrary delay between destroy and removal.

For EID 4315, the lethal `1054` is frame 3753 at 73.905560 seconds from the
capture origin; death `1072` is frame 3761 at 74.005112; destroy `1073` is
frame 4375 at 77.788933; removal `1035` is frame 4391 at that same instant.
Its slot 34 is subsequently reused by EID 4579 at frame 4583. This corrects
the old immediate `1073`/`1035` minion-death path, which omitted `1072`.
It has not yet established that this omission caused the live client crash.

`Director.on_minion_death(victim, killer_eid, now)` sets HP to zero,
prevents further movement and attacks, emits `1072`, and retains the compact
slot. `pump` emits the due `1073`/`1035` pair and releases the slot before
allocating any new wave actors. Repeated damage/death calls do not duplicate
the lifecycle. Reconnect includes retained corpses through creation,
zero-HP snapshot and `get_death_frames()`; removed actors are excluded.

### Native static creation and current actor state

`NativeActorCatalog` reads external records with the actual nonhero identity
layout: archetype at +0, class at +4, EID at +8, position at +12/+20, compact
slot at +116 and team at +121. A 126-byte creation has no HP fields. The
122-byte VGR snapshot carries current/max HP at +36/+40 and retains the slot
at +116; it does **not** shift that slot four bytes earlier. Unknown fields
remain in the external template. No proprietary payload fixture is added.

The static class is `0xc10b41da`: archetypes 371/370/369 are outer/middle/base
turrets, 372 is a Vain turret, and 292/293 are the two Vain crystals. All
twelve authored placements are retained so shared archetypes keep their
individual height and facing. Across eight audited matches, Vain turret
snapshots have maximum HP 3000; the old 5000 premise was wrong and the four
server Vain turrets now use 3000. Other turret and crystal HP tiers are
unchanged. The test validates all 24 retained structure creation/snapshot
templates byte for byte against the external source.

`StructureManager.get_spawn_1010_frames()` now builds actual 126-byte
creations, including persistent destroyed structures. Its separate
`get_state_1010_frames()` reads current HP. Lane reconnect helpers likewise
retain current EIDs, slots, positions and HP without scheduling a new wave.
The 122-byte form is proved in VGR state snapshots; its live reconnect use
is an explicit client integration experiment and remains to be validated.

## Hero energy, recall, death and resurrection

`1053` uses resource type 0 for HP, 2 for energy, and 6 for gold. Damage event
`1054` is victim first, attacker second. Ordinary damage is sent once via
`1054`; a duplicate negative-HP `1053` would apply the same loss again.
Energy spending and positive regeneration use their corresponding `1053`.

Recall channels for 4 seconds, cancels on movement/damage/control, and
teleports to the friendly spawn with `1070`. Friendly fountain regeneration
adds 15% max HP and energy each second. The enemy fountain deals the
requested 1000 true damage per second. Dynamic respawn uses the requested
`6 + level * 2.5` seconds plus the explicit policy of one second per completed
match minute.

`server/lifecycle_wire.py` implements the actual hero lifecycle:

| Event | Opcode and fields |
|---|---|
| Death | `1072`: victim EID, killer EID, six zero bytes |
| Countdown | `1075`: EID, float seconds, six zero bytes |
| Corpse hiding | `1073`: EID and two zero bytes, approximately 1.8 seconds after death; no `1035` actor removal |
| Pre-return | `1033`: EID, x, measured spawn height, y, flag 1 and five zero bytes; hero remains dead |
| Position confirmation | `1070`: EID, x, y, zero tail |
| Completed revival | `1074`: EID, x, the same height and y, six zero bytes; approximately 0.3 seconds after pre-return |

All six deaths, six countdowns and five resurrections in `vgfull` match the
builders byte for byte. The original two-frame resurrection check omitted
the preceding `1073`; the local Baron client subsequently remained in its
death pose after the server sent `1033`/`1070`. The complete five native
intervals and seven local-player VGR intervals all include corpse hiding
before resurrection. Adding corpse hiding alone did not resolve the client
failure; the final native `1074` was also missing. All 129 expanded-corpus
flag1 returns precede `1074`, and native snapshots between the two actions
still have zero HP. The server now sends `1033`/`1070` 0.3 seconds before
the deadline while keeping the hero dead, then `1074` at the deadline to
complete revival. It retains the actor slot throughout. Slots 1500 and 1515 use measured height 1.3;
1517, 1518 and 1519 use 1.5. The full correction, exact origins and the
successful fresh Gwen client acceptance are in
[solo-sandbox-hero-respawn.md](solo-sandbox-hero-respawn.md).

No full-HP/full-energy delta accompanies the final native `1074`; a local
snapshot after it shows full HP/energy. The earlier claim that `1033`
restores pools was false: it only starts the return transition. The old `1162` tag
`b855d752` is an initialization record, not a death countdown: it occurs
exactly once for each of the six heroes before play. Its float starts at
+12, not +10.

## Basic attack presentation and unresolved cycle timing

`server/attack_wire.py` emits `1045` followed immediately by `1070` for the
attacker's **current** position at each windup start. `1045` is source EID,
target EID, one observed variant byte and five zero bytes. It repeats for
each attack against the same target; a one-time target-acquire message does
not reproduce the observed stream.

Adagio uses variants 7 and 8 in 127 ordinary attacks; Baptiste uses 7, 8, 10
and 11 in 108 attacks. Every one of these 235 actions has the immediate
source-position message. Variant semantics remain unresolved. Selecting
among observed variants deterministically is presentation policy, not a
claim to recover the native selector. No independent Adagio basic-projectile
builder is established by this audit; live attack/projectile animation is
still an acceptance check.

A second bounded audit joins `1006` hero IDs to `1045` and matching negative
`1054` class-5 damage in 591,070 frames across 11 canonical VGR matches.
`attack_wire.MEASURED_BASIC_VARIANTS` supplies ordinary candidate variants for
28 recorded kits; uncovered kits return `None`, without borrowing another
hero's action. Special or empowered variants are excluded from this default
selection. In particular, Baptiste 10/11 corresponds to initial damage 78,
while the 7/8 examples deal 105.3, consistent with an empowered attack.

| Hero ID | Registry identity | Ordinary candidate variants |
|---|---|---|
| 242 | Catherine | 9, 10 |
| 244 | Adagio | 7, 8 |
| 245 | Koshka | 9, 10 |
| 253 | Joule | 7, 8 |
| 254 | Hero009 | 7, 8 |
| 256 | Sayoc | 11, 12 |
| 258 | Vox | 10, 11 |
| 260 | Hero016 | 10, 11 |
| 265 | Skye | 13, 14 |
| 266 | Reim | 7, 8 |
| 267 | Kestrel | 7, 8 |
| 268 | Alpha | 9, 10 |
| 274 | Ozo | 14, 15 |
| 275 | Lance | 8, 9 |
| 279 | Phinn | 7, 8 |
| 393 | Flicker | 7, 8 |
| 396 | Grumpjaw | 10, 11 |
| 397 | Tony | 10, 11 |
| 399 | Baptiste | 10, 11 |
| 408 | Churnwalker | 8, 9 |
| 409 | Lorelai | 7, 8 |
| 418 | Magnus | 7, 8, 9 |
| 432 | Silvernail | 9, 10 |
| 439 | Yates | 8, 10, 12 |
| 913 | Leo | 8, 9 |
| 915 | Caine | 8, 9 |
| 924 | Viola | 11, 12 |
| 925 | Amael | 8, 9 |

Amael's direct examples are match `0e7de8af-96d9-4e3a-b3c2-609ed5e71120`,
chunk 15 rows 1057→1096 (variant 8) and chunk 29 rows 252→285 (variant 9),
under `$TEMP/vg_phaseB/vgr_live`. Koshka's example is match
`591146df-33f2-4f12-9a04-8d800d239821`, chunk 5 rows 815→870, under
`$TEMP/vg_max/vgr2`. Phinn's examples are match
`045f86d4-7ef2-4125-a835-e70a96288c88`, chunk 4 rows 344→361 and 1067→1082,
under `$TEMP/vg_max/vgr5b`. These full payload pairs are checked from external
files, alongside Catherine's recorded variants.

The initialization timer tagged `d60c580b` is not sufficient evidence for a
hero's complete basic-attack cycle. Its native symbol is unresolved. In
`vgfull`, Baptiste has timer 0.7 seconds, but starts attacks at receive times
70.378530, 71.387102 and 72.394655 seconds, with impacts approximately 0.20
seconds after each action. Adagio has the same timer, first measured start
spacing 1.012785 seconds and approximately 0.60-second action-to-impact delay,
which includes flight. Receive timing and bot scheduling do not identify
the exact native windup/recovery formula. Do not replace an explicit cycle
policy with this timer while claiming a measured full cycle.

Reproduce the independent attack, slot and wave audit:

```powershell
python Tools/Teardown/inspect_attack_sequence.py --pcap "$env:TEMP/vg_max/vgfull.pcap" --match b9f511e0-11cd-4cfa-ad62-dc8612b8d270 --source-eid 1516 --limit 3
python Tools/Teardown/inspect_attack_sequence.py --vgr "$env:TEMP/vg_phaseB/vgr_live" --match 0e7de8af-96d9-4e3a-b3c2-609ed5e71120 --variant-census
```

The inspector reads captures only and prints scalar findings. Pcap times
are completion times from the first observed TCP bytes; VGR times use the
record's float timestamp. Neither is silently treated as an engine tick.

## September 22: fixture teleport is not a movement correction

The ten-hour native ability trials exposed a QA placement defect: after a
long teleport, authoritative target `(4,38)` corresponded to native logical
target `(15.323611,29.273438)`. The sole 1070 correction integrated through
client navigation/collision and did not establish an instant relocation.
This explains a failed Target Lock trial; it is not an ability rejection.

`SandboxQA.teleport` now emits native flag-zero1033 before its position
correction. Surface Y comes from owned navmesh vertices via integer-weighted
barycentric interpolation; it does not change the 2D simulation/path costs or
claim a model/feet offset. The identified 1033 consumer is ELF `c07b80`.
Ordinary walking/dash and Recall policies were not changed by this QA repair.
Fresh native target position `(4,37.999992)` and subsequent A/B/C inputs prove
the fixture repair locally. Both native actor positions are mandatory before
combat input. Evidence: `relocation-live/` in [the active run](classic-ten-hour-run.md).

## Checks

### September22 opt-in native steering qualification — still experimental

`ClientMovementObserver.native_path()` now reads the bounded native array/cursor
with repeated content/lifetime checks. Native `c60208` requires flag bit0 to
advance it: stopped/dead entities can retain old arrays while overwriting the
destination, so those are not valid query pairs. During ordinary local play,
39 active routes were retained; the pinned public Detour query reproduces38
exactly at float32 and one with a single height ULP difference (`2.98e-8`).
This is client query reproduction, not an official-server computation oracle.

Build in an MSVC x64 developer shell with
`python Tools/Teardown/build_detour_oracle.py --recast-archive <pinned-v1.6.0.zip> --output <new-external-dir>`.
Compare with `python Tools/Teardown/detour_route_oracle.py --library <external-dll> --native-paths <paths.jsonl> --output <new-report.json>`.
No downloaded source, compiled library or owned mesh is added to Git.

Explicit `HALCYON_NATIVE_STEERING_LIBRARY=<qualified-dll>` activates experimental
hero one-unit surface steering and fixed-point3D movement. The default remains
the integer triangle-funnel path. Capped/partial paths and native height-query
failures keep the existing planar policy with diagnostic fallback counters;
they are not silently called native-equivalent. Geometry/route collision checks
remain independent. Canonical replay state includes height cursor/waypoints.
Both backends pass all seven production headless comparisons, but experimental
steering still requires live qualification before any default change.

The expanded production sweep reproduced a separate integration error: coordinate
rounding could keep a partial step inside the mesh yet make its remaining line
to the waypoint cross a wall. `clamp_walk_step` now checks both lines before
accepting the rounded point. The synthetic L-corner test failed before and
passes after;59 focused checks pass. A consumed waypoint inside a fixed tick
must be included in the collision check: the endpoint chord alone need not
follow the actual path. Evidence and current sweep outcome are in
[checkpoint18](classic-ten-hour-run.md#checkpoint-18--scalable-route-comparison-and-isolated3d-steering).

### September 22 initial spawn contract repair

Native Skye before its first movement started at donor Adagio's `(-77.03,-1.94)`
while the server started at `(-78.18,.88)`, about3.05 units apart. Five bot slot
constants also copied `1011+22` (vertical height) into simulation Y instead of
`+26` (map Z). `HERO_SPAWNS` now uses measured canonical X/Z, and separate
`HERO_SPAWN_HEIGHTS` supplies height. `build_hero_block` replaces the selected
hero/donor's captured XYZ with the owning slot's coordinates. This also prevents
mirrored team2 heroes from appearing initially on team1's side.

The production regression fails before and passes after, including six mirrored
heroes and all five bot coordinates. 91 focused checks and seven two-process
headless scenarios pass. See `spawn-live/` / [active run](classic-ten-hour-run.md)
for native verification. Fresh Skye now reads
`(-78.180000305,1.267069578,.879999995)` before any walking, matching the
authoritative planar spawn. This repair does not prove general smoothness.

The latest focused static/reconnect, minion-lifecycle, actor-slot, structure
and wave set passes 60 tests, including the 83 native minion removal chains
and full external structure payload comparisons. The earlier owned
navigation/lifecycle, jungle, wave, actor-slot and attack-wire set passed
132 tests, including external-corpus golden comparisons. A separate
1,000-second lane simulation completes without slot collisions. The slot
regression covers 600 successive minion creations and removal-based reuse.
The production benchmark is tracked separately by `Tools/verify_sandbox.py`.
No commits were made. Live client gameplay and the unresolved capture,
growth-field, variant-selection and exact attack-cycle meanings remain
separate acceptance gates.

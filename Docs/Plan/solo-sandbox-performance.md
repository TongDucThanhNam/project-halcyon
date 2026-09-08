# Production sandbox performance and determinism verification

**Status after the operator's Skye failure:** the 758-test/960-second figures
below describe the previous source revision. Skye skills, targeted projectile
creation and minion movement have since changed. Their new verification is
separate; these historical figures do not establish visible client acceptance.

`Tools/verify_sandbox.py` drives `SnapshotStream.advance_simulation()` for
960 seconds at its production 50 ms tick. It uses the operator's external
A001 navigation mesh (793 vertices, 832 triangles), normal waves, normal
structures, and the normal jungle/objective clock. No captured gameplay
stream, stat boosts, faster timers, or disabled structures are used.

The final 2026-09-08 pair passes every enforced gate: byte determinism,
full coverage, unchanged source/worktree and every 50 ms tick deadline.
The two maxima are **14.6694/15.5164 ms**. This is the same source that passed
all **758 tests**. The final section records the pin and artifacts; earlier
failures, diagnoses and repairs remain below. The 2 ms aspiration is exceeded
on many ticks; no enforced gate has been relaxed.

Six authored controllers, selecting Adagio/Ringo/Celeste/Amael/Gwen/Catherine,
purchase items, learn abilities, clear camps, activate items, recall, and
approach the timed objectives. Adagio was added after the live client exposed
an Arcane Fire metadata crash on the slotted production minion class; this
path also has a dedicated `test_adagio_minion` regression. Cast packet forms
follow each ability's targeting type. Off-mesh movement requests remain in the
scenario because they exposed a real navigation cost. Their outcomes go
through production intent validation, movement, combat, economy, and
ability code.

```powershell
python Tools/verify_sandbox.py
```

The default output is a new directory under TEMP. `--output` selects an
explicit artifact directory; `--navmesh` overrides the external A001 path.
`--seconds 60` is a diagnostic run and is explicitly insufficient for the
sixteen-minute coverage check.

## What is compared and measured

The verifier copies only authored Python source into a fresh external
directory, after checking that no edit raced the copy. It starts two
separate Python processes with hash seeds 11 and 7919. Both import those
same pinned files. The report records every source-file digest and whether
the worktree still matches the pinned version when the comparison ends.

Each process writes its complete emitted stream, with tick/opcode/length
framing, a canonical final gameplay state, and 960 state checkpoints. The
comparison reads the artifact files and checks their bytes directly.
Canonical state includes pending projectiles, channels, effects, cooldowns,
movement remainders, navigation routes, economics, minions, jungle state,
structures, and controller state. It also includes the shared compact actor
slots, next buff identity, status interruption serials, queued presentation
frames, Recall presentation and completion markers, vision banks, shop
permission identities and refresh times, item instance/ready timers, level
progression, and reconnect death/resource caches. Permanent buff expiries
and uninitialized manager clocks retain their intentional infinity sentinels
as canonical strings; NaN remains rejected and hero-resource invariants
still require finite values every tick. Immutable external geometry is identified
by its SHA-256. Transport locks, wall-clock menu deadlines, and sockets are
outside the fixed-step gameplay state.

Tick timings include production intent handling, item activation, and
`advance_simulation`. Transcript file writes, controller decision logic,
runtime assertions, and state serialization are outside the timed region.
Optional cProfile recording likewise includes only production calls.
The callback queues generated messages in memory; these measurements do
not include socket I/O, encryption, client rendering, or emulator latency.

Workers remove `HALCYON_QA_DIR` before importing gameplay code, including
when invoked directly with `--worker`, so the live QA command directory
cannot affect or be consumed by a benchmark. Spawn overrides, experimental
capture and optional emission switches are also cleared; the production
world tape is disabled. Initial jungle actors are published through the
same production publisher used by `_run_world`, before fixed ticking starts.
The verifier reads the external navmesh and the operator-owned external spawn
corpus; proprietary inputs remain outside the authored source pin.

The current controller learns with native 1078, casts targeted/self actions
with 1041 and ground actions with 1042, and uses owned equipment instances
through native 1096. Cast and Recall fields are converted from the authored
UI choice through `ability_wire.hero_action_variant`; 1078 retains its UI
slot. The older 22-byte 1102 adapter is not exercised. An item
echo is not counted as a successful activation: authoritative item cooldown
state must change. The fixture never calls `activate_item` directly.

The report contains p50/p95/p99/max/mean tick cost, counts above 2 ms and
50 ms, and the twenty slowest ticks with population/message counts. The
2 ms target is aspirational; any measured 50 ms deadline miss fails the
deadline check. Windows thread-CPU accounting was quantized in these runs,
so individual thread-CPU samples should not be interpreted as precise
sub-millisecond timings.

Coverage requires the full duration, the expected number of waves from the
production schedule, camp deaths and respawns, both objective spawns,
successful purchases/casts/item activations, combat emissions, and a world
that stayed active throughout. The current gate additionally requires
completed Recalls, skill upgrades, level gains, visibility messages and
shop permission refreshes. Every tick also checks finite bounded hero
resources, nonnegative economics, minion HP, and cross-system entity-id
uniqueness. Assertions are not included in the reported server tick cost.

## Initial measured findings, 2026-09-07

The first 60-second run had p99 40.61 ms and max 88.96 ms, with six ticks
over 50 ms. Profiling seconds 50–60 attributed 2.608 of 3.885 profiled
seconds to exhaustive nearest-point projection. The navigation change
retained exact rational projection and tie-breaking while adding bounding
box pruning and a bounded query cache. An independent 66-point comparison
against the prior Fraction implementation returned identical triangle ids
and coordinates; runtime for that query set fell from 2405.55 to 35.79 ms.
The subsequent 60-second production run had max 29.79 ms and no deadline
misses.

Two subsequent full 960-second runs with the initial mirrored
Ringo/Celeste/Amael fixture each completed 19,200 invariant-checked
ticks, 38 waves, 404 lane-minion spawns, 146 camp deaths, 136 camp respawns,
478 successful casts, 35 purchases, 36 item activations, and five recalls.
The gold miner and Kraken spawned at their normal stages. Peak live lane
population was 23; retained entity history brought the total to 572.

| Initial full run | p50 ms | p95 ms | p99 ms | Max ms | Ticks over 50 ms |
|---|---:|---:|---:|---:|---:|
| Process 1 | 2.878 | 9.619 | 20.209 | 84.300 | 20 |
| Process 2 | 1.875 | 5.218 | 12.748 | 70.587 | 12 |

The streams, final state and all checkpoints matched byte for byte. Source
edits occurred during this pair, so the source guard rejected it as final
evidence for one stable revision. Its artifacts remain at
`$env:TEMP/halcyon-sandbox-960-first/`. Neither run met the 50 ms deadline.

A separate pinned profile of seconds 935–945 found the remaining dominant
cost: 1699 `find_path` calls consumed 4.812 of 6.098 profiled production
seconds. There were 33,462 `segment_walkable` calls during path smoothing;
minion pursuit initiated 1618 `set_target`/`set_path` calls in 200 ticks.
By comparison, `_entities` took 0.036 seconds. Retained dead entity scans
were therefore not the principal cause of this late spike. That profile
is at `$env:TEMP/halcyon-sandbox-late-profile/run/tick-profile.txt`.

## Full verification after navigation caches, 2026-09-07

Bounded full-route and segment-interval caches removed the repeated late
path-smoothing work. Both fresh processes then completed the six-kit
960-second fixture with all 19,200 runtime invariant checks passing.

| Final full run | p50 ms | p95 ms | p99 ms | Max ms | Ticks over 2 ms | Ticks over 50 ms |
|---|---:|---:|---:|---:|---:|---:|
| Process 1 | 1.170 | 2.972 | 5.137 | 26.691 | 3264 | 0 |
| Process 2 | 1.447 | 2.968 | 5.974 | 27.504 | 3988 | 0 |

The complete 3,693,608-byte streams, final state, and all 960 checkpoints
matched byte for byte. Both workers imported the same pinned source, that
source stayed unchanged during each run, and the workspace still matched
the pin when comparison finished. All duration, coverage, determinism, and
50 ms deadline gates passed; the verifier exited zero. The 2 ms aspiration
was not met on every tick.

Each run produced 38 waves and 404 minions, 144 camp deaths and 134 camp
respawns, 396 successful casts, 44 purchases, 37 item activations, eight
recalls, 50 skill upgrades, and 6318 damage messages. All six selected kits
emitted cast acknowledgements. The gold miner and Kraken appeared on the
production schedule. Peak live lane population was 23, with 570 entities
including retained history. The match stayed active throughout. One hero
died at 931.5 seconds; its scheduled respawn was 970 seconds, beyond this
run's horizon, so this pair does not demonstrate a completed hero respawn.

Artifacts and per-file source hashes are external at
`$env:TEMP/halcyon-sandbox-six-kits-960-final/summary.json`, with the authored
source pin in `source-snapshot-bvndln6a/` beneath that directory. SHA-256:

| Artifact | Digest |
|---|---|
| Emitted stream | `0bfeae63f7fa4aad4c4ca88bc93a932d565c6b01aac048525d6fb8508a15d3c5` |
| Final state | `53713d1463ea3ed10356036b59b9c27d57645970026d7af51780c1231b046881` |
| Checkpoint log | `e7ed60590364ec5d9d7492323676fb319a36b20b53c5f6e443f485be1695d91b` |

This is evidence for the pinned revision before the subsequent reconnect
catchup work. These offline measurements do not establish smooth visible
play on the mobile client, complete hero kits, reconnect correctness, or
the unresolved native combat timing rules.

The later native-item audit disproved the old 1096 skill-upgrade binding
used by that pinned fixture. The current verifier uses 1078 for skill
upgrades. That earlier pair is not evidence that its authored input
vocabulary matched the real client. The subsequent native-input and
lifecycle verification is recorded below.

## Pinned lifecycle pair before native-action correction, 2026-09-07

The updated harness ran the full 960-second scenario in two independent
processes with hash seeds 11 and 7919. Both completed 19,200 invariant-checked
ticks. Their 3,955,918-byte emitted streams, canonical final states, and all
960 state checkpoints matched byte for byte. Both workers imported the
same 39-file authored source pin, which stayed unchanged in each process.

| Current run | p50 ms | p95 ms | p99 ms | Max ms | Ticks over 2 ms | Ticks over 50 ms |
|---|---:|---:|---:|---:|---:|---:|
| Process 1 | 3.681 | 9.502 | 16.454 | 268.105 | 15951 | 19 |
| Process 2 | 3.553 | 7.386 | 12.863 | 83.790 | 16117 | 2 |

The verifier exited **1**. The 50 ms deadline failed in both processes.
The source guard also failed because `server/match_server.py` changed in
the worktree during the pair: reconnect bootstrap now credits previously
allocated skill points before replaying the rank allocations. The two
workers remained pinned to the same earlier bytes. This is reproducible
evidence for that pin, not an unchanged-worktree acceptance result or a
test of the later reconnect edit. No thresholds were relaxed and no
replacement timing run was selected to hide these failures.

Later native-client checks also established that cast requests carry the
hero's action-vector ordinal, including Catherine A=1/B=2/C=3/Recall=5.
This pair's harness and server adapter still interpreted those fields as
UI slots. The cast counts below therefore describe accepted actions under
that pinned adapter; they do not prove native Catherine/Gwen action mapping
or native Recall input fidelity. The current harness now converts those
fields through `hero_action_variant`, pending a new stable-source run.

Each process produced 38 waves, 404 lane minions, 149 camp/objective deaths,
136 camp respawns, 428 successful casts, 17 purchases, 36 successful item
activations, one started and completed Recall, 64 hero level increases,
70 skill upgrades, 6233 damage messages, 2729 visibility messages and 31
shop permission refreshes. Both timed objectives appeared normally and
the world remained active throughout. Peak live lane population was 23;
peak entity count, including retained history, was 425. No hero died, so
this fixture does not exercise a completed hero death/respawn lifecycle.
It also does not disconnect/reconnect a transport client.

Process 1's slowest tick was at 494.20 simulated seconds, with 11 live
minions, one current jungle entity and six messages; elapsed production
cost was 268.1047 ms and the quantized thread-CPU sample was 15.625 ms.
Process 2's slowest tick was at 596.10 seconds: 83.7903 ms elapsed and a
0 ms quantized thread-CPU sample. These samples do not identify the cause
of the stalls. No profiler was enabled during either full run. A separate
bounded diagnostic of the same pin is described below.

The independent one-second harness smoke also set an external QA-directory
sentinel before invoking `run_worker` directly. QA and tape stayed disabled,
the sentinel directory was never created, and the expanded state graph
serialized the permanent shop presentation successfully.

Artifacts are external at
`$env:TEMP/halcyon-sandbox-current-960-20260907/summary.json`.
The source pin is its `source-snapshot-sxf6anbc/` directory. Each worker's
`result.json` records the per-file manifest, environment isolation, exact
percentiles, twenty slowest ticks and artifact paths. The source-pin digest
below is SHA-256 of the canonical JSON path-to-file-digest manifest.

| Artifact | SHA-256 |
|---|---|
| Source pin manifest | `af17344b85ac8cb14621b1a58d16c8551b49392baeb03f8058f26c73dcb762f3` |
| Emitted stream | `1b94db69f55412fbdb9db15c82e311daf9c6d56df2be313de4d426202c31982d` |
| Final state | `f0e0482f3683fec736f8af63d2eb0a9407551df6a868e53562b872536116acc1` |
| Checkpoint log | `38073e13bd9f015b1ad830d711b6cbbd5cf7b44526bef34f71c67460b8ac489e` |

## Acceptance attempt after live gameplay repairs, 2026-09-08

The two independent processes each completed 19,200 ticks and produced
byte-identical streams, final state and all 960 checkpoints. The source
remained pinned in both workers, and the workspace matched it when comparison
finished. The verifier exited **1**: the deadline and full-coverage gates
both failed. Artifacts are external at
`$TEMP/halcyon-sandbox-acceptance-960-20260908-final/summary.json`, pin
`898e9f3656c8d1f7f738fbd91435c3c3ad0d1d79fc8766147b9f2dcfce27c0cc`.

| Process | p50 ms | p95 ms | p99 ms | Max ms | Ticks over 50 ms |
|---|---:|---:|---:|---:|---:|
| 1 | 3.981 | 10.407 | 14.045 | 87.128 | 2 |
| 2 | 3.738 | 10.192 | 14.382 | 135.771 | 2 |

Process 1's two misses occur at simulated 952.70 and 956.75 seconds,
with 65 and 62 living minions. Thread-CPU samples are 62.5 and 93.75 ms,
respectively, so a late-window CPU profile is required before selecting a
repair. No capture or live QA ran concurrently with this pair.

Both runs produced 38 waves/404 minions, 199 camp deaths/186 respawns,
435 casts, 12 purchases, 36 item activations, 66 level increases, 70 skill
upgrades and 5592 damage messages. Gold Miner and Kraken spawned normally;
the world stayed active. No hero fell below the controller's emergency-Recall
threshold, so it issued **zero Recalls** and full-duration coverage correctly
failed despite all other exercised systems.

The revised controller therefore includes a deliberate return-to-shop trip:
after 120 seconds, one player walks through normal movement input to the
friendly lane outside base, then uses native Recall and waits for completion.
It does not set HP, teleport, accelerate time or change any coverage threshold.
The failed scenario remains the baseline for profiling and verifying the CPU
repair, so the added trip cannot conceal the measured late-game hotspot.

A separate final audit also found transient windup CC being lost between
ticks. Attack-specific interruption serials now retain STUN/KNOCKBACK/DISARM
even after expiry or cleanse, while preserving committed shots and allowing
silence/root. This correction and the deliberate Recall fixture are newer
than this failed source pin and require new final verification.

The 946–960-second profile of the unchanged failed pin reproduced the complete
stream, final state, checkpoints and coverage exactly. Across 280 ticks it
recorded 13.10 million calls and 6.322 profiled seconds. Lane processing took
4.719 seconds, including 34,460 target selections and 1,079,411 distance calls.
Aggregate navigation cost was smaller, so this profile alone does not identify
the three exceptional ticks; a profile of those exact ticks follows separately.

A GC callback diagnostic also reproduced all baseline bytes. No collection
occurred within 0.12 seconds of the three recurring slow ticks at 952.70,
956.55 and 956.75. Generation-2 collections instead occurred at checkpoint
times, outside timed simulation. This rules out GC as their measured cause.

That investigation separately exposed a retained recursive-function cycle in
the checkpoint encoder. `freeze_state` now clears its recursive closure cell
in `finally` after synchronous encoding, including exceptions. Three snapshots
matched the original encoder byte for byte; completed calls and a rejected
NaN left zero retained freezer functions with automatic GC disabled solely in
the diagnostic process. Production and verifier GC settings are unchanged.
This memory cleanup is not claimed to repair the three CPU spikes.

A 160-second diagnostic of the deliberate Recall trip completed one native
Recall and returned to normal shopping, with all 3200 runtime invariant checks
passing. Its shortened duration remains insufficient for final acceptance.

### Exact slow-tick diagnosis and geometry repair

Individual profiles of the three recurring ticks identify bursts of path
smoothing, rather than the aggregate lane-scan cost, as the exceptional work.
The unchanged old fixture again produced exactly the baseline stream, state
and all checkpoints. Rounded **instrumented** costs are:

| Simulation time | Whole tick ms | Pathfinding ms | Raw clipping ms | Uncached paths | Raw clips |
|---|---:|---:|---:|---:|---:|
| 952.70 | 75 | 51 | 43 | 12 | 313 |
| 956.55 | 59 | 36 | 31 | 12 | 226 |
| 956.75 | 93 | 70 | 59 | 19 | 390 |

The last tick makes 564 segment checks and 60,933 cross-product calls.
These diagnostic costs include cProfile overhead and are not deadline results.
Profiles are external at `$TEMP/halcyon-sandbox-exact-spikes-20260908/`,
`tick-19053`, `tick-19130` and `tick-19134` (`.txt`/`.pstats`). GC event evidence
is at `$TEMP/halcyon-sandbox-gc-946-960-20260908/gc-events.json`.

`navigation.py` now precomputes exact integer triangle half-planes, rejects
triangles whose bounds cannot intersect the requested segment, and returns
immediately when a convex triangle covers the entire segment. Edge/corner
touches remain included; interval unions and path choices retain the original
semantics. No movement rule, lane rule, tick duration or deadline changes.

Three new regressions compare the optimized query with an exhaustive Fraction
oracle that clips every triangle without grid or bounds pruning. They cover
holes, boundaries, negative cells, clockwise input, zero-length segments,
long routes and microunit crossings on the external map. The 96 focused
navigation, lifecycle, wave and jungle tests pass. An unchanged old-scenario
960-second comparison isolates this production geometry change before the
strengthened Recall fixture is used for final acceptance.

That isolated comparison passed. Its external source copy differs from the
failed pin in **`navigation.py` only**, retaining the old controller, encoder
and combat/status code. The complete 4,379,174-byte stream, 1,942,184-byte final
state and 86,808-byte checkpoint log are directly byte-identical to the failed
baseline; all 960 checkpoint records and coverage counts match. Every one of
19,200 ticks meets 50 ms: p95 **7.272710 ms**, p99 **9.485448 ms**, mean
**3.294340 ms**, maximum **26.428200 ms**. Former spikes at 952.70/956.55/956.75
now cost **23.8688/18.6375/26.4282 ms**, respectively.

Artifacts are external at
`$TEMP/halcyon-sandbox-nav-optimized-old-fixture-20260908/`; navigation SHA-256
is `1c55bdc9422eb0701c6086ccdffd07b46d1920c7cc9e9cd76acb8cf98e8d6f97`.
This establishes the CPU repair without relying on a changed gameplay
scenario. The old fixture still has zero Recalls and is not the final
full-coverage result; that result must use all final source changes together.

## Final verified acceptance pair, 2026-09-08

The complete final source passes **758 tests in 61.721 seconds**. The test
runner's source/test manifests remain unchanged across the run. They match
the following two-process replay's source manifest and the final worktree.
The suite output and manifest record are external at
`$TEMP/halcyon-sandbox-full-suite-20260908-postaudit.txt` and `.json`.

Two fresh processes with hash seeds 11 and 7919 each execute 960 seconds,
19,200 fixed ticks and 960 checkpoints. Their complete **4,382,444-byte wire
streams**, canonical final states and all checkpoints match directly byte
for byte. Source remains unchanged within each worker and the worktree
matches the shared 40-file pin after comparison. All coverage and deadline
gates pass; the verifier exits **0**.

| Final process | p50 ms | p95 ms | p99 ms | Max ms | Ticks over 2 ms | Ticks over 50 ms |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 2.426550 | 6.387555 | 8.006253 | 14.669400 | 12467 | 0 |
| 2 | 2.375450 | 6.478030 | 8.457790 | 15.516400 | 12025 | 0 |

Each run produces 38 waves/404 minions, 197 camp deaths/184 respawns,
443 casts, 20 purchases, 38 item activations, **two completed Recalls**,
66 level increases, 70 skill upgrades, 5598 damage messages, 3416 visibility
messages and 47 shop permission messages. The deliberate Recall trip completes
and ordinary gameplay resumes. Gold Miner and Kraken appear on their normal
schedules; the match stays active throughout. Peak living minions is 64;
peak entity count, including retained history, is 425. All per-tick resource,
economy and entity-identity invariants pass.

Both workers have QA and captured world-tape input disabled. The earlier
isolated old-fixture comparison proves that the navigation optimization fixes
the measured CPU stalls without relying on the new Recall inputs. The final
pair then verifies that optimization, transient-CC repair, encoder cleanup,
deliberate Recall and all previous gameplay repairs together.

Artifacts are external at
`$TEMP/halcyon-sandbox-verified-960-20260908/summary.json`; the authored source
copy is `source-snapshot-_prc77_i/` beneath that directory. Exact timings,
source manifests, coverage and artifact paths are in `run-1/result.json` and
`run-2/result.json`.

| Artifact | SHA-256 |
|---|---|
| Source pin manifest | `3cb517cb5193433122945a754c2f0c71efa70e9fd494c1d2cf6a1d79dd93a29c` |
| Emitted stream | `13ffed63653fe8b187710fb4f2f19dbeb0f4748bd355204df676d48994ce99a3` |
| Final state | `f43254b0345ac51ee2b256a88ecad5c647ea8daaac09cad685a3b0cdc74a3a82` |
| Checkpoint log | `0ca4144a8e3147be921c84f53f95bf54804d98a1ce38f41493e7b8f0c762c785` |

The 2 ms aspiration is not met on every tick. These timings measure production
intent dispatch and simulation, with the socket/encryption/rendering exclusions
described above. No hero dies in this performance fixture; death/respawn and
Victory are established by separate production tests and the completed client
scenarios. Full hero-kit/native animation parity and transport reconnect
hardening remain documented fidelity work, not claims made by this pair.
| External A001 mesh | `71ebf471a0566036f83390cd3af8245d074c845fcbff0d3ba4f10b959ef87f7e` |

## Bounded profile and CPU fixes, 2026-09-07–08

One diagnostic replay used the unchanged `af17344...` source pin, seed 11,
and a 494–504-second profile window. It contains the largest elapsed-time
outlier and the nearby 501.05-second tick with the largest recorded
thread-CPU bucket (31.25 ms). Exactly 200 production ticks were profiled;
controller decisions, checkpoint serialization and transcript writes stayed
outside the profile. The diagnostic's stream and checkpoint log are exact
prefixes of process 1's full artifacts, and its final state matches that
run's checkpoint at tick 10,080. Thus enabling this profile did not change
the replayed outcomes.

The window recorded 4,684,439 calls in 2.066 profiled seconds. Cumulative
times below overlap for parent/child functions and must not be added.

| Function | Calls | Cumulative seconds | Finding |
|---|---:|---:|---|
| `HeroKit._targets` | 2414 | 0.699 | About 34% of the profile; repeated retained-entity filtering |
| `HeroKit._step_projectiles` | 1200 | 0.356 | 0.352 s spent building targets while this window had no projectile/burn work |
| `HeroKit._step_stormguard` | 1200 | 0.346 | 0.343 s spent building targets while this window had no reflection/burn work |
| `wave.Director.pump` | 200 | 0.497 | Minion movement and targeting |
| `ItemManager.step` | 200 | 0.240 | Includes 38,326 repeated dead-target status clears |
| `StatusManager.clear_target` | 38328 | 0.128 | Only two calls came from actual death publication |
| `Vision.update` | 200 | 0.169 | Lower cost than the empty ability scans |
| `StructureManager.step` | 200 | 0.147 | Includes turret scans of retained minion history |
| `NavMesh.find_path` | 1833 | 0.014 | Cache effective: one actual path search and one segment check |

At the end of the window, `Director.minions` retained 212 minions, of which
21 were alive. Across the repeated ability scans, `_alive` ran 520,642 times
and `getattr` ran 1,825,139 times. The profile identifies avoidable work;
it does not establish the cause of the much larger elapsed-time stalls in
the two full runs. The shortened, instrumented diagnostic is not a new
deadline acceptance result.

Two bounded fixes followed on 2026-09-08. `_step_projectiles` returns before
building targets when both projectile and Hellfire-burn lists are empty.
Stormguard builds targets only for queued reflections or a due burn pulse;
caster-death presentation cleanup still runs, and queued reflections still
resolve before that cleanup. `ItemManager.step` visits only EIDs present in
mechanical status or active presentation maps for dead cleanup. It preserves
the existing EID removal order and does not remove retained actor history.

Seven new regressions in `server/test/test_idle_effect_work.py` prohibit
idle history scans, retain between-pulse timing, verify launched projectile
and queued reflection damage after caster death, cancel dead-anchor/bubble
presentation, and preserve item-ready timers and one-time ordered cleanup.
The Stormguard production fixture now sends measured native action 2 and
asserts that B started; its damage/barrier/bounty expectations were retained.
The focused ability/item/buff checks passed 165 tests, followed by 27 passing
status/native-action/session checks. The root task's full suite subsequently
passed all 676 tests in 61.348 seconds. Production and harness edits were
frozen, and the root task confirmed stable source before the fresh pair
below. Native-client acceptance is tracked separately.

Profile artifacts are external at
`$env:TEMP/halcyon-sandbox-current-profile-494-504-20260907/`, including
`tick-profile.pstats`, `tick-profile.txt`, and the source-pinned `result.json`.

## Fresh stable native-action pair after CPU fixes, 2026-09-08

One fresh two-process pair ran the full 960-second scenario after the native
action conversion and the two CPU fixes. Both seeds completed 19,200 ticks
with every runtime invariant passing. The 3,955,918-byte streams, canonical
final states, and all 960 checkpoints matched byte for byte between workers.
All 39 source files stayed pinned in both workers, and the worktree still
matched the pin when comparison finished. QA and world-tape input remained
disabled in both processes. Every enforced gate passed; the verifier exited
**0**.

| Fresh run | p50 ms | p95 ms | p99 ms | Max ms | Ticks over 2 ms | Ticks over 50 ms |
|---|---:|---:|---:|---:|---:|---:|
| Process 1 | 1.948 | 4.300 | 7.661 | 43.516 | 9114 | 0 |
| Process 2 | 1.958 | 4.014 | 7.279 | 36.326 | 9201 | 0 |

The 2 ms aspiration is still exceeded on many ticks. These measurements
include production intent dispatch and fixed-tick simulation, with the
same exclusions described above; they do not measure client rendering or
socket latency.

Coverage was identical to the preceding pair: 38 waves, 404 minions, 149
camp/objective deaths, 136 camp respawns, 428 successful casts, 17 purchases,
36 item activations, one completed Recall, 64 hero level increases, 70 skill
upgrades, 6233 damage messages, 2729 visibility messages and 31 shop refreshes.
Both objectives appeared on schedule and the match stayed active. The final
gameplay state and all checkpoints also matched the earlier pin byte for
byte. The emitted stream changed with the corrected native rank wire fields.
The fixture still contains no hero death/respawn or transport reconnect.

Artifacts are external at
`$env:TEMP/halcyon-sandbox-native-actions-960-20260908/summary.json`.
The 39-file source pin is `source-snapshot-_gitabxb/` beneath that directory.
Per-file source hashes, exact unrounded timings, slowest ticks and coverage
are in the two `run-*/result.json` files.

| Artifact | SHA-256 |
|---|---|
| Source pin manifest | `445a241160fcb2e88a05e70638d36a339d5e25430f46f19d3820d2457af68f43` |
| Emitted stream | `94faff892499b459f9912bd7a2361dc383cc96cca5b1427bcc7479a4965a7b74` |
| Final state | `f0e0482f3683fec736f8af63d2eb0a9407551df6a868e53562b872536116acc1` |
| Checkpoint log | `38073e13bd9f015b1ad830d711b6cbbd5cf7b44526bef34f71c67460b8ac489e` |

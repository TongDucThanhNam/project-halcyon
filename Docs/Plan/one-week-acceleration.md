# One-week acceleration workflow — audit checkpoint 2026-10-04

## Decision and completion boundary

**One owner; no delegation. Binary-first, CPU-only for the inner loop.** Reuse
the existing production simulation and scenario runner. Do not launch LDPlayer
for each hypothesis, rewrite the engine, hunt leaked sources, or revive broad
binary/codec dead ends. No images, recording or visual acceptance dependencies.

The mission remains **100% faithful, self-hosted private Vainglory PvP**. Seven
days is an execution timebox, not evidence that all kits and engine rules can
be reproduced in that time. The week-one release candidate is a complete
private 3v3 match with an explicitly qualified composition, normal lifecycle,
six real clients and retained nonvisual evidence. A restricted composition
does **not** close the full mission; every unsupported kit/mechanic stays on
the fidelity backlog. If any release gate is red, Day 7 reports an incomplete
candidate, not a renamed success.

## Execution checkpoint — 2026-10-09

The October 4 audit table below is historical and retained, including its red
checks. Discovery on source `bda39c2` remeasured 1,470 tests / 28 reviewed skips,
seven exact headless pairs, and a clean 960-second verifier pair (max
21.4335/22.3473 ms, zero ticks above 50 ms). Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/discovery-run-1791562480510-fac7cde6-{all,headless,verifier}/`.
This is a **clean remeasurement, not an attributed performance repair**: the old
tick-2714 255.2873-ms outlier is retained and was not reproduced. Tick 19031
is a distinct measured workload peak (wave pursuit/target selection, 26 paths).

The [declared coverage matrix](week-one-coverage-matrix.md) inventories every
factory, all 36 catalog items, defaults and shared-mechanic gaps. Skye/Ringo/
Catherine/Gwen/Adagio/Amael are a **declared candidate, not qualified**.
Day 1 is not closed merely by the old green counts: declaration refusal,
guest failure propagation, matrix/status and final checks require evidence.

Execution `run-1791564257036-9a4bad79` follows the revised two-stage contract:
declaration/reachability before any gesture; unchanged measured equality after
legal ordinary learning, before casting. The retained negative control at
`C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791564084425-64b2b43b-a1-unlearned-negative/result.json`
records one upgrade tap before undeclared-fixture refusal on HEAD. The first
focused repair check (`run-1791564257036-9a4bad79-a1-a2/result.json` in the same
evidence root) passed 14 tests. The execution results below supersede that
initial check; no client or fidelity acceptance is inferred from test counts.

### Execution results and final-source gate locations

This October 9 dispatch continued past midnight into October 10 local time.
Here **R** means
`C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791564257036-9a4bad79/`.
Day 1 repair checks and Day 2 offline work are evidenced, not an overall release:

| Check | Measured result / retained artifact under R |
|---|---|
| Declaration/refusal and real-QA post-learning contract; legacy causal/identity/continuity negatives | `a-legacy-cadence-fixed/result.json`: **291 PASS**, 0 skips, 872.086 s. `a-client-final/result.json`: **119 PASS**, 0 skips, 0.297 s |
| Either-guest failure propagation | Three `test_live_up` cases in the 14-test initial focused pass and `a-fixed-focused` 26-test PASS; both setups are still attempted |
| Pool/native/verifier-focused regressions | `b-focused`: **53 PASS**; `b-combat`: **99 PASS**; `b-movement`: **52 PASS**; `b-workflow`: **40 PASS**; all zero skips |
| Native aggregate component | `b-native/result.json`: **901 cases / 1,802 native executions / 894 exact production comparisons**, including 11 sequential hits and 5 measurement-only decimal cases; 27.679 s. Largest native-minus-decimal-production delta **0.000003051757815342171**; no rounding-policy change |
| Production scenarios | `b-headless/summary.json`: **seven exact two-process pairs** |
| Instrumented verifier | `b-verifier/summary.json`: **two × 19,200 ticks**, max **21.7158 / 21.1300 ms**, **0 >50 ms**. `b-baseline-comparison.json`: event/state/checkpoint hashes of both workers equal discovery |
| Retained movement contract | `movement/review.json`: classified unknown, detailed below; no movement repair or native smoothness claim |

Self-review retained and repaired two distinct failures, rather than weakening
their assertions. The first legacy run (sibling evidence directory
`run-1791564257036-9a4bad79-a-legacy`) failed one established error-message
assertion; the wording was restored. `a-legacy-fixed` then failed two minion
pair comparisons (**290 tests, 2 failures, 0 errors/skips, 854.590 s**): actual
sample offsets accumulated beyond the unchanged 100-ms fixture margin.
The comparator correctly refused them. The sampler now schedules from one
monotonic origin while retaining actual receipt timestamps. The named synthetic
25-ms wake-up / 20-ms service-delay regression failed at **380 ms** accumulated
drift before the fix (`sampler-test-negative`) and passes at **65 ms** after it;
both formerly failing pair tests also pass (`sampler-fixed-focused`, 3 tests).
This is a sampler correction, **not attribution of the historical verifier
stall** and not a live sampling-equivalence claim. `final-source-review.json`
proves the full measured validator, diagnostic cast flow and strict native
executor remain unchanged; pair validators and margins were not modified.

**Day 3: SETUP/BLOCKED after two actual-instance attempts.** Both LDPlayer 0/1
booted, passed `setup_local --check --profile client` (4.13.4/build 147219,
root and OBB), passed existing dual-guest `live_up` routing, and focused
`NuoActivityGame`. The local journal contains two guest/session startup sequences
but **zero `joinLobby` requests and no WORLD wire trace**. The existing
`run_scenarios.py --mode client --scenario movement-walk` refused each at SETUP
with **zero gestures**, requiring an explicit existing WORLD connection.
Evidence: `c-result.json`, `c-setup-{0,1}.txt`, `c-live-up.txt`,
`c-client-{0,1}/client-result-*.json`, activity snapshots and `c-runtime/rpc.jsonl`.

Owner/slot, WORLD freshness, native HUD/accessors, opposite-team placement,
target lock, damage/death, disconnect/rejoin and late join remain **UNVERIFIED /
UNRUN**, not gameplay regressions. This does not diagnose matchmaking admission.
Smallest missing capability: anchored **nonvisual menu-to-WORLD entry in the
existing driver**, or independently qualified existing WORLD sessions; no
screenshot-dependent entry, blind taps, second driver or native hooks were used.
Day 4 was not opened. Six actual clients remain a machine/device-capacity
prerequisite, not satisfied by socket tests.

Both guests' routing rules/policies, reverses, hosts/CA source and mounted
contents, and mount state were verified against their baselines, then both
emulators and owned stack PIDs 25336/4764 were stopped. Original platform
configuration/input hashes are unchanged. The first read-only helper quoting
error and Android `quota2` full-table restore failure are retained; targeted
removal of this run's tagged rules completed restoration. Comparison excludes
only save timestamps and runtime traffic counters, not rules or policies.
See `c-*-restoration-check.json` and `c-final-emulators.txt`.

Final-source freeze gates run sequentially with both emulators/stack stopped:
`freeze-{smoke,client,combat,movement,workflow,focused,all}/result.json`,
`freeze-headless/summary.json`, `freeze-verifier/summary.json`, and
`freeze-native/result.json`. Their machine-readable status is authoritative;
an absent/red result is unrun/failed, never implied green by this checkpoint.
The final execution report supplies counts, timings and the reviewed skip delta.

**Hygiene / operator decision:** 12 tracked `.pyc` and 9 historical PNG files
remain unchanged. Filename inventory agrees with discovery; no images opened.
Untracking/deletion is excluded from this run and remains an explicit operator
decision, not a hidden cleanup or a release-qualified asset audit.

### Bounded offline movement contract — 2026-10-09

Selected retained contract: `classic-live-14/continuation-02`, owner EID 1500,
slot 0, connection 2872100183888, pinned CE147219 native library
`cd1b8831f82c469274613fc30f1f1f6e78c788102cdad7db5db2c04b96580a47`.
The existing `Tools/Teardown/inspect_movement_trace.py trace --timing` reproduces
**8.877278089523315 s** from retained c2s1012 to the later owner1016 destination
`(-75.296142578125, 3.4107539653778076)`. The pre-input actor is alive, unselected,
navigation inactive, correction timer zero. This is not a rejected-input claim.

Evidence: `C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791564257036-9a4bad79/movement/`
contains `review.py`, source hashes, the explicitly labelled retained-row excerpt,
exact inspector command/stdout/stderr and `review.json`. The original command's
full wire path is absent; the excerpt does not prove absence of other traffic.
The tick-log join succeeds structurally but has **zero ticks in the request
interval**; it cannot add causal work/latency attribution. The existing four-tick
catch-up repair and named `test_sustained_overload_services_input_between_bounded_fixed_tick_batches`
remain the headless regression, not fresh native validation.

**Classified unknown: post-repair native acknowledgment-to-movement effect under
equivalent long-run load.** A client run must bind owner/slot/build and retain
c2s1012 → matching s2c1016 → native destination/navigation flag plus logical/root-model
displacement, correction timer, clock brackets and contiguous tick/load phases.
No movement change or experiment switch is enabled by this offline review;
general smoothness and the distinct classic-live-13 native hold remain unknown.

### Offline pool and timing scope — 2026-10-09 dispatch

Named pool regressions now cover earliest-expiry barriers, insertion-order ties,
post-barrier fortified half absorption capped by current HP, expiry equality,
expiry publication before combat, and pre-pool 1054 for full/partial absorption.
These lock **authored rules**, not independent native individual-effect ordering.
The native helper adds three persistent aggregate sequences (11 hits) and five
non-dyadic measurement cases. Its original exact dyadic comparison and strict
float32-input refusal stay intact; decimal input quantization and arithmetic
deltas are reported separately, without a new production rounding policy.
Native multi-effect ordering/refresh ties/expiry remain **UNKNOWN**.

Caller classification (source inspected with syntax-level call searches):
`HeroMovement.apply_damage`'s optional `status_manager` / `modifier_queue`
branches and `DamageModifierQueue.resolve(..., status_manager)` omit current HP.
They are **standalone pool-consumption fallbacks, not the live integrated pool
path**. `SnapshotStream._deal_damage` calls `resolve(ctx)` **without** pools,
then consumes pools with `current_hp=target.hp`, and calls `target.apply_damage`
without a manager (no second pool consumption). Live ability casts/steps,
minions, jungle, structures and item effects supply this callback; `HeroKit._damage`
uses its standalone queue only when that callback is absent. Source anchors:
`server/match_server.py:_deal_damage,_step_heroes,advance_simulation`,
`server/hero_movement.py:apply_damage`, `server/abilities.py:HeroKit._damage`,
`server/status_effects.py:DamageModifierQueue.resolve`. No caller arithmetic
change is needed for the live HP cap. Standalone adapters remain unqualified
for capped fortified absorption; future integration must supply HP. The separate
fountain lifecycle calls plain `apply_damage` without a status manager, so its
pool semantics are not qualified by these tests either.

Verifier telemetry uses the existing QA/wave/bots/heroes-effects/economy phase
boundaries plus scripted-intent timings and per-phase/total thread CPU. Every
tick is measured; the slowest 20 retain the rows. Timing does not feed rules,
the 50-ms gate is unchanged, and serialization/invariant work remains outside
the historical tick-cost definition. Windows thread CPU quantization is
disclosed; a >50-ms tick with <=10% thread CPU is labelled a **host/scheduler
stall inference**, not a proven root cause. CPU-heavy rows name their measured
dominant phase. No pathfinding optimization or experiment promotion is included.
The old tick-2714 root cause remains **UNKNOWN** (wall-dominated, no retained
phase rows); see `run-1791564257036-9a4bad79/retained-verifier-attribution.json`
under the evidence root. New hashes must equal the discovery baseline before
this timing-only change is accepted.

## What this audit actually established

Scope: repository/worktree and authored implementation inventory; current
acceptance/performance/navigation/scenario records; setup check; full unittest
discovery; production scenario/source-pin paths; an executable original ARM64
kernel. This is not a line-by-line proof of the whole codebase or a live-client
acceptance run. No client/emulator was launched for this audit.

| Area | Measured state | Consequence |
|---|---|---|
| Local inputs | Headless setup check passes with the real navmesh, spawn catalog and volley inputs | Develop offline without booting Android |
| Baseline tests | 1,386 run in 506.408 s; 25 failures, 8 errors, 28 skips | Historical green counts are not the current baseline |
| Final full discovery | 1,398 run in 523.799 s; 11 failures, 8 errors, 28 skips; source stable | All remaining failures/errors are in `test_scenario_client`; class setup errors leave some causal tests unexecuted. Release gate stays **FAIL** |
| Fast loop and workflow checks | Smoke: 71 run/70 non-skipped, no failure/error, 10.738 s. Changed-tool integration: 44/44 pass; separate repaired-contract check: 20/20 pass | Smoke is a measured subset, not an equivalent replacement for full discovery |
| Long verifier | Source-only pin incorrectly searched for `Local/` inside its temporary source directory | Repaired: resolve original inputs first, pass absolute paths; copy no private payloads |
| Repaired 960 s pair | Two independent processes, 19,200 ticks each; event/state/checkpoint bytes exact, source stable, duration coverage satisfied | Determinism demonstrated for this workload, not client/PvP fidelity |
| Deadline gate | First run: 15 ticks above 50 ms, max 255.2873 ms; second: 0, max 27.2024 ms | **FAIL** overall. Preserve both runs; attribute outliers before claiming a performance repair |
| Native health kernel | 885 cases / 1,770 original ARM64 executions; 883 exact numeric production comparisons; native repeats byte-exact | One reusable component oracle, not a whole-game oracle |
| Stale test premises | Wave HP initialization, owner-walk correction policy, fraction-preserving level-up and barrier publication had changed | Tests now assert the current evidenced contracts, including negative/observer cases; no gameplay change to satisfy old assertions |
| Legacy client harness | `run_client` now dispatches Skye through native nonvisual qualification; old fixtures lack focus, bootstrap identity, native state and the new result contract | Keep failures visible. Migrate fixtures/contracts, not bypass guards or restore screenshot paths |
| Gameplay breadth | Ten kit factories; several explicitly incomplete. Assists not implemented. Complete human-match/six-client acceptance open | Shared mechanics and a declared playable composition before breadth expansion; catalog selection is not kit completion |
| Independent reference | Retained CE records do not supply controlled rank/items/input/target evidence for the missing combat questions | `UNAVAILABLE` where no valid fixture exists; local Halcyon recordings are not an independent oracle |
| Git hygiene | Twelve tracked bytecode files and nine historical screenshot PNGs found by filenames, not opened | Preserve unrelated work; do not hide diffs, force-add Local, or auto-commit |

Evidence root for this audit:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/one-week-audit-14190973a25d46f2b54d2e1bc7ccc8b5/`.
`REPORT.md` records final checks, failures/skips, exact source identities and
artifact paths. Baseline failures and failed verifier attempts are retained.
The pre-existing tracked `server/platform/__pycache__/local_stack.cpython-314.pyc`
modification is not part of the authored repair and was not reverted.
The28 full-suite skips comprise27 external-fixture availability checks and one
Windows symlink-privilege limitation. Missing files at configured paths do not
prove they are absent from every owned archive; retain these as coverage gaps.
The older client suite consumed439.619 seconds of summed individual test time
in the final run (class setup/teardown excluded). This measured concentration,
not a guessed engine deadlock, is why it is outside the edit-by-edit smoke loop.

## The shortest useful development loop

1. Read `git status` and the single relevant subsystem leaf. Name **one behavior
   contract**, its observed failure/unknown, version, initial state and input.
2. Reuse an existing native/wire anchor. If pure arithmetic/control flow, run
   the original bounded helper on CPU first. Preserve code fingerprint, memory
   layout, flags, time/rank/items and discriminating boundary cases. A Python
   rewrite of our own implementation is not an independent native oracle.
3. Repair the production entry point, then run its focused unittest lane and
   named existing headless scenario. Do not add another simulator. Keep exact
   internal determinism; document normalization separately for client/reference
   comparisons. Never widen tolerance just to obtain PASS.
4. Run a real client **only** for a question the offline evidence cannot answer:
   input delivery, native consumer state, model movement, UI transition or an
   independently missing gameplay outcome. State the expected scalar signal
   before starting. Use existing `run_scenarios.py --mode client` and anchored
   reads; missing guards remain SETUP/UNVERIFIED, not permission to use images.
5. Preserve the external result, update the behavior board, and proceed to the
   next contract. Full discovery and full production gates still run at freeze.

Bounded RE rule: spend at most 60–90 minutes on one **known-anchor** experiment
before recording what is missing. After two failed setup attempts without new
evidence, stop that experiment and continue an independent offline item. Do not
spend the week retrying the same emulator path or guessing ARM hooks/heap roots.
These are scheduling bounds, never a reason to declare a check passed.

Each work item records:
`contract | source/client fingerprint | anchor | initial state + intents |
expected vs observed | production entry point | negative control |
client/reference needed and why | result + external artifacts | remaining unknown`.
Measure closed behavior contracts and remaining release blockers, not test
counts, log volume or number of recovered symbols.

### Ready-to-run commands (PowerShell, repository root)

```powershell
# Once per environment; does not start an emulator.
.venv/Scripts/python.exe -B Tools/setup_local.py --check --profile headless

# Fast recipes are explicitly SUBSETs, not a substitute for full discovery.
.venv/Scripts/python.exe -B Tools/run_checks.py --suite smoke
.venv/Scripts/python.exe -B Tools/run_checks.py --suite movement
.venv/Scripts/python.exe -B Tools/run_checks.py --suite combat
.venv/Scripts/python.exe -B Tools/run_checks.py --suite transport
.venv/Scripts/python.exe -B Tools/run_checks.py --suite client
.venv/Scripts/python.exe -B Tools/run_checks.py --suite workflow

# Optional original ARM64 leaf, no Android or client process.
.venv/Scripts/python.exe -m pip install -r requirements-native.txt
.venv/Scripts/python.exe -B Tools/Teardown/verify_native_health.py --grid

# Freeze/release gates: do not run performance measurements concurrently
# with heavy tests, native grids, builds or source edits.
.venv/Scripts/python.exe -B Tools/run_checks.py --suite all
.venv/Scripts/python.exe -B Tools/run_scenarios.py --mode headless --scenario all
.venv/Scripts/python.exe -B Tools/verify_sandbox.py
```

All commands allocate unique external evidence by default. Explicit `--output`
must be external and empty/new; old journals are never overwritten. The test
wrapper is only a timed unittest launcher: `result.json`, complete stdout/stderr,
`issues.log`, per-test events and periodic thread traces expose progress and
failures. A thread dump is diagnostic, not proof of deadlock. It rejects an empty
or entirely skipped test run and source drift. `--tests` selects precise unittest
IDs; `--list` prints recipes. Every skip must be reviewed for missing coverage.

`--suite client` tests the current nonvisual adapters with mocks; it is **not**
live acceptance. `--suite legacy-client` retains the older schema/driver suite;
`--suite all` still discovers it. Both were red at the October 4 audit; the
dated checkpoint above records subsequent measurements and execution failures.
Do not omit either from a release report. Migration must retain causal/identity/continuity negatives
under the new native contract, not invent focus/native observations to make an
old PASS fixture work.

### What the native pilot does, exactly

`Tools/Teardown/verify_native_health.py` executes ELF VA `0xCAA5A0`, 180 bytes,
from owned CE 4.13.4/build 147219 ARM64 `libGameKindred.so`, SHA-256
`cd1b8831f82c469274613fc30f1f1f6e78c788102cdad7db5db2c04b96580a47`.
It resolves the executable ELF segment and refuses other fingerprints; no game
bytes are embedded in source. Two independent Unicorn engines reset registers
and synthetic buffers for every case; only inspected reads/output writes are
allowed; 256-instruction/one-second bounds, unchanged inputs and four initialized
outputs are enforced. Optional dependency is pinned in `requirements-native.txt`.

Comparison invokes the real `StatusManager.absorb_damage_with_barrier`. Grid
values are dyadic and exactly representable in float32: numeric equality is
exact, with signed zero equivalent; native repetition remains byte-exact.
Healing and alternate-pool flag cases execute natively but are not counted as
production comparisons. Original hit/damage calculation is an **input**, not
recovered by this leaf. Multiple-pool ordering, expiry and arbitrary float
rounding are not qualified. Do not present 885 cases as 885 recovered mechanics.

### Real-client/reference lane

Reuse retained owned evidence first. Prefer the same-build owned physical ARM64
device for new missing cases rather than making LDPlayer a dependency of every
iteration. This is a direction, **not a claim that physical-device routing,
ABI/accessors or automation have been qualified**. Prove package/build, owner,
slot, WORLD freshness, native HUD and accessor availability before input.
Emulator/physical migration must not become an engine rewrite or a second driver.

Independent CE comparison means passive nonvisual observation while operating
our own ordinary client, within existing boundaries. Never probe/inject into a
remote backend or treat its accessibility as source access. Replay/server output
alone is not the authoritative computation oracle. Missing independent evidence
remains open even when local native consumer behavior matches Halcyon output.

## Seven-day dependency schedule

Relative days begin with the execution sprint, not the host clock. One owner
works sequentially; long checks run while doing non-overlapping documentation
or read-only analysis. Do not edit hashed code during a measured run.

| Day | Highest-leverage work | Exit evidence, not a promise |
|---|---|---|
| 1 | Stabilize the audited workflow; migrate legacy client fixtures to the new nonvisual contract; lock a declared hero/item coverage matrix | Full discovery with every failure/skip classified; no bypassed focus/native guards; CPU/native and source-pin commands reproducible |
| 2 | Shared movement/pursuit, combat pool ordering and long-run overload attribution before new kits | Named regression and exact two-process scenario; phase/tick attribution for deadline misses; targeted native client trajectory evidence where needed |
| 3 | Two actual clients first, then six owned headless sessions against our local server | Team/owner isolation, target locks, damage/death, disconnect/rejoin and late-join state; headless six-session success is not six-device acceptance |
| 4 | One ordinary complete match on the declared composition | Shop/skills, lane/jungle/objectives, turret protection/aggro, death/respawn, base destruction, result and menu return, without forced casts/kills |
| 5 | Close critical shared fidelity gaps and the chosen composition's remaining mechanics; assists/vision where exposed | Native/reference-backed boundary cases and retained contradictory evidence; unqualified broader kits remain listed |
| 6 | Freeze a source/config/input pin; full tests, seven headless pairs, 960 s verifier and real-duration client soak | All release gates pass on the candidate; real client stability observation includes the previously problematic ~30-minute window |
| 7 | Six actual clients play a fresh private match; reproduce prior critical defects | Nonvisual input→acceptance→authoritative outcome→client effect evidence, consistent results/rejoin/menu return; otherwise explicit failed gate and next fix |

### Release blockers and order

1. **Legacy nonvisual contract migration** — October 4 setup/schema errors hid
   portions of the causal pair suite; later discovery passed, but the dated
   checkpoint's declaration/sampler regressions need final-source evidence.
   Preserve the writer/validator contract; no legacy capture-tool restoration.
2. **Deadline/overload attribution** — use existing phase/tick telemetry and
   verifier profiling on a named outlier. The October 4 pair failed; later
   clean pairs are remeasurements, not attribution of that failure. A clean
   second process cannot erase a failed first. No 50 ms threshold relaxation.
3. **Actual two-client correctness**, then six-client full-match delivery.
   Existing six-owned-session tests are transport/simulation evidence only.
4. **Shared mechanics and declared composition gaps** — assists, pursuit/native
   movement disagreement, target/area/timing/perk gaps, vision and lifecycle.
5. **Independent fidelity expansion and remaining kits** — required for the full
   mission, not silently removed to satisfy the week-one milestone.

Release gate = full unittest discovery with reviewed skips, all seven production
headless comparisons exact on one pin, full-duration verifier with every tick
deadline met, ordinary real-duration client stability, complete multi-client
match acceptance, and explicit independent-reference coverage/unknowns. A fixed
960-second simulation runs faster than wall time and does **not** replace a real
client soak. The long verifier's current workload has no hero deaths/respawns or
match finish; separate lifecycle/client evidence is mandatory.

Routes: [current status](current-status.md), [differential validation](differential-validation.md),
[scenario contracts](solo-sandbox-scenarios.md), [performance](solo-sandbox-performance.md),
[navigation](solo-sandbox-navigation.md), [setup](../Setup/windows-local-development.md).

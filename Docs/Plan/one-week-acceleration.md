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
`--suite all` still discovers it and currently stays red. Do not omit it from a
release report. Migration must retain its causal/identity/continuity negatives
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

1. **Legacy nonvisual contract migration** — setup/schema errors currently hide
   portions of the causal pair suite. Repair the fixture model and current
   writer/validator contract together; no legacy capture-tool restoration.
2. **Deadline/overload attribution** — use existing phase/tick telemetry and
   verifier profiling on a named outlier. The 960 s pair still fails; a clean
   second process cannot erase the first. No 50 ms threshold relaxation.
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

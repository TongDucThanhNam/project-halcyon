# Repeatable scenario verification — pilot record

Updated 2026-09-12 to reflect the reviewed evidence through the ckpt13corr20
round (the declared-fixture live A/B/C runs, the corpus-restored headless
integration run, the failure-path fix, and the two finite minion-push
negatives). This leaf records the verification pilot and its acceptance
evidence; dated sections below retain the history they were written with, and
claims that later evidence superseded are marked inline in this summary.

Status summary:

- **Live rendered-client A/B/C: observed live behind a declared-fixture gate;
  A has no fresh-match pair, and no presentation is reviewed.** The gate pins
  the measured pre-input state to a declared profile; all six attempts below
  were accepted by it. Freshness is taken from each record's own process /
  startup / connection fields, not assumed:
  - **A (`skye-a`, corr12): two PASS attempts inside ONE live session.** Both
    records carry `pid 23684 startup 1789171203.113506`, the same match id and
    the same connection `1677315684560`, at world 147.8→171.8 s and
    184.3→197.75 s. They are two attempts in one match, **not two fresh
    matches**. The earlier A match (corr9) was separate and fresh but was
    refused at `SETUP` before any input there — no record was written then; the
    failure path that lost it is fixed by corr10.
  - **B (`skye-b`, corr14): two PASS attempts on two separate fresh matches**
    (startups `1789172654.53` / `1789173219.45`, connections `2148944721232` /
    `2148950881488`, one wire trace each).
  - **C (`skye-c`, corr16): two PASS attempts on two separate fresh matches**
    (startups `1789174897.94` / `1789176036.07`, connections `1745004052816` /
    `1745004065360`) inside the level-6 window (world 500–648 s), where the
    legal QA `learn` granted zero XP and zero points, by receipt.
  - **Equal totals are not a passed pair contract.** A's two totals (−554.187),
    B's (−113.1417) and C's (−361.8338) agree within their own stages as
    same-implementation observations with byte-identical damage payloads; that
    is **not** the production compare-pair contract (the pair CLI was not run),
    **not** exact determinism for the sim, and **not** official fidelity.
    **Presentation is captured but UNREVIEWED** in every stage. Each stage
    declared one ability slot only (A, then B, then C — never two in one match).
    That is not an ownership proof, and the ownership question stays open as a
    different one: binding the chronological network `1016` movement-slot
    assignments and releases to entity identity. The live driver does build
    that timeline from a live trace — `1010` publications bind eid→slot and
    `1035`/`1073` removals release the slot (`server/actor_slots.py`: slots are
    reused), which is how the minion records attribute `1016` orders via the
    slot map — but the preserved records carry none of those lifecycle
    publications, so the slot→owner binding cannot be shown from them and the
    pair report keeps `slot_ownership.status` `UNVERIFIED`. Ability slots A/B/C
    are not that proof. **C's
    publication-to-pulse causality is also not proven** (one volley-actor publication
    and 20 pulses are both recorded; the record does not order cause and
    effect).
  - Superseded by the above: the 2026-09-10/11 statements that "A still lacks a
    corrected comparable pair" and that the corrected B/C runs had drifted
    starting states. The declaration gate removed the drift and A's two
    same-match passes are recorded, but no compare-pair contract was run in any
    stage, so no stage is a passed pair. The QA teleports that place both heroes
    are QA preparation, not read-only observation.
- **Minion approach and opposing combat: observed live; resumption to a
  structure is a finite negative in all three bounded observation windows.**
  corr17 ran two
  observation attempts (its trial-1 was an infrastructure error and is not an
  observation), each on its own fresh match (connections `2759997060176` /
  `2759996865616`) with a declared 35 s window (measured 35.507 s / 35.472 s,
  34 census frames each): `LANE_APPROACH` and `OPPOSING_COMBAT` PASS, while
  `SURVIVOR_RESUMPTION`, `STRUCTURE_INTERACTION` and `AUTHORITATIVE_EFFECT`
  are `NOT_OBSERVED` → the records FAIL (163 minion-vs-minion events, 14 deaths
  and 0 structure hits in each). corr20 then ran one fresh match (pid 27196,
  connection `1402554169808`, world entered at tick 0) with a declared 60 s
  window (measured 61.054 s, census world 46.75→107.75 s) and reproduced the
  same verdict (267 events, 24 deaths, 0 structure hits): the last ranged pairs
  closed to the 6.5 u standoff and destroyed each other **mutually**
  (4626↔4627 at world 81.78, 4628↔4629 at 86.97). Precisely, corr20 measured
  **zero contiguous observed-alive samples after any combat participant's own
  carried engagement end** — for each of the 26 combat participants the
  engagement-end instant and the actor's own death fall inside a single census
  interval (the record's 26 "unverified claims"; of the 40 tracked actors none
  shows a qualifying run) — which is why `SURVIVOR_RESUMPTION` is
  `NOT_OBSERVED`. That proves no
  qualifying resumption inside the measured interval; it does **not** say zero
  minions survived (a further ranged pair died 2.9 s
  after the last census sample, world ≈ 110.64/110.65, and later play was not
  observed). These are finite negatives for those
  three windows only — not a claim about all later play. Trace lines carry no target
  field, so target identity is unknown; the per-sample geometric proximity and
  the ±0.75 s combat association stay diagnostics, never acceptance criteria.
  The earlier survivor counts remain withdrawn (corr19 correction, per actor).
- **Headless scenarios: shipped and verified on a recorded source pin,
  including the recorded wave-elimination fixture.** All six scenarios PASS in
  two independent seeded processes (`PYTHONHASHSEED=11` / `7919`) over one
  pinned source snapshot (`source_pin_sha256 de53b6eb…`,
  `workspace_matches_snapshot true`) with byte-identical `events.bin`,
  `initial-state.json`, `final-state.json` and `state-checkpoints.jsonl`
  (corr8). `minion-push`'s PASS depends on the recorded post-contact wave
  elimination (side 2 at tick 790, ≈0.1 s of natural phase): it is declared in
  `fixture_operations` and never presented as a production input, so that
  scenario proves the integrated pipeline, not a natural push. A final run
  against the eventual stabilized source remains required.
- **External corpus prerequisites are explicit and were rebuilt from owned
  artifacts.** Production headless startup needs `HALCYON_SPAWN_CORPUS` (a
  directory holding the match-6 Kraken archetype-363 126-byte creation record;
  rebuilt in corr3) and `HALCYON_SKYE_VOLLEY_CORPUS` (volley chunks 32 and 36;
  rebuilt in corr7). Without them `server/entity_spawn.py` raises
  `external jungle spawn records missing for 363` and the runner suite fails
  for that documented environment reason. The recovered world tape is rebuilt
  byte-faithfully by `Tools/build_world_tape.py`, whose production loader digest
  matches its pin.
- **Failure-path fix (corr10): a refused declared fixture now persists its own
  record.** The contract is carried before validation and initialized on the
  driver, so a `SETUP` refusal serializes the contract it was refused against
  instead of dying in its own handler with `AttributeError`; the evidence is the
  in-repo harness regression plus the pre-change reproduction, not a live
  re-run.
- **Latest accepted engineering milestone: the declaration gate itself**
  (supersedes the 2026-09-11 enemy-rank statement as the newest milestone — that
  enforcement is part of this gate). Reviewed corrections reject missing or
  contradictory identity, teams, prepared resources/ability points, declared
  levels/ranks/points, placement and required record fields instead of reporting
  false PASS; the 2026-09-12 live runs above are the first evidence produced
  through it. Verification-tool progress, not gameplay acceptance.
- **Independent reference: interface shipped; no compatible fixture exists.**
  Every reference status stays `UNAVAILABLE`, including corr8's
  (`no external reference fixture provided`). Local Halcyon recordings prove
  Halcyon behavior only.

The full faithful private PvP target remains open. Reviewed live work now covers
one gate-respecting A/B/C chain (six accepted attempts, no compare-pair
contract) and the three bounded minion observation windows; it did not
close a controlled fresh-match pair, the ~30-minute idle WORLD client crash
(fault 0x38), the live minion sampling/pair gap, or official fidelity.

Reviewed evidence (all under `%LOCALAPPDATA%\halcyon-evidence\`; of the two
2026-09-11 `%TEMP%` paths this summary used to cite, the enemy-ranks-repair one
was lost with the round's `%TEMP%` artifacts and is kept as dated history only):

| Round | Directory | What it establishes |
|---|---|---|
| ckpt13corr3 | `halcyon-ckpt13corr3-kraken-spawn-corpus-06cc680a-20260912` | spawn-corpus dependency diagnosed; archetype-363 chunk rebuilt from owned caches |
| ckpt13corr7 | `halcyon-ckpt13corr7-volley-anchors-ce646625-20260912` | volley chunks 32/36 rebuilt row-exact; skye-c headless PASS |
| ckpt13corr8 | `halcyon-ckpt13corr8-all-scenarios-headless-70afda4a-20260912` | all six scenarios, two seeds, byte-identical; source pin `de53b6eb…` |
| ckpt13corr11 | `halcyon-ckpt13corr11-declared-fixture-profile-readiness-6aa49348-20260912` | the declared-fixture candidate derived from live evidence (read-only) |
| ckpt13corr12 | `halcyon-ckpt13corr12-client-skye-a-declared-fixture-4b7c1e92-20260912` | A: two PASS attempts in one match |
| ckpt13corr14 | `halcyon-ckpt13corr14-client-skye-b-slot-declaration-5f175750-20260912` | B: two PASS attempts on two fresh matches |
| ckpt13corr16 | `halcyon-ckpt13corr16-client-skye-c-level6-window-9ff91aea-20260912` | C: two PASS attempts on two fresh matches (level-6 window) |
| corr17 | `halcyon-corr17-client-minion-push-d63d5ad8-20260912` | two 35 s live minion windows; `SURVIVOR_RESUMPTION` `NOT_OBSERVED` |
| corr18 | `halcyon-corr18-headless-vs-live-minion-diff-4b1f9d27-20260912` | headless-vs-live comparison; fixture-manufactured PASS identified |
| corr19 | `halcyon-corr19-clearance-correction-d9c83185-20260912` | per-actor correction: withdrawn survivor claims, death-bound reconciliation |
| corr20 | `halcyon-corr20-live-window60-8c93d740-20260912` | one 60 s live window; mutual annihilation; no contiguous alive run after any engagement end |

`corr9` (live A refused at `SETUP`), `corr10` (the failure-path fix with its
prefix/postfix reproduction), `corr13` (B refused: the declaration was
slot-specific) and `corr15` (C blocked: no level-3 slot-C declaration exists)
are in same-named directories under the same root.

## What this pilot is and is not

| Evidence layer | What establishes it | What it cannot establish |
|---|---|---|
| Harness repeatability | Two seeded processes, byte-identical deterministic artifacts | Nothing about correctness of the rules themselves |
| Internal determinism | Exact event/state comparison (no tolerance) | Visible client presentation, official fidelity |
| Rendered acceptance | The live client driver's stages + human-reviewed capture | Official-server parity |
| Official fidelity | Independent external reference fixture within stated tolerances | Raw-packet equality claims |

Short scenarios do not replace the sixteen-minute `Tools/verify_sandbox.py`
coverage/deadline gate, which is unchanged and remains the production soak
fixture.

## Headless scenarios (`Tools/run_scenarios.py`)

All scenarios use the actual external A001 navigation mesh and an initialized
production `SnapshotStream` with waves, structures, turret stepping, jungle
and hero lifecycle enabled, advanced only through
`advance_simulation()` at the 50 ms fixed tick. Missing navigation is a
reported setup failure; there is no rectangle fallback and no disabled
manager. Fixture operations (teleport to the live-verified positions, XP/HP
grants, the post-contact wave elimination) are recorded separately in
`fixture_operations` and are never presented as production inputs.

| Scenario | Proves | Cannot establish |
|---|---|---|
| `skye-a` | Forward Barrage: 1078 learn, 1042 ground cast (native action 0 @offset 12), energy payment, 1046 ack (action @16), attributed 1054 damage through the live world | Presentation; official damage parity |
| `skye-b` | Negative control: B without a lock produces no ack/damage/energy change; real basic-hit lock (1086 kind 602) then dash with exactly 4 attributed missile hits | Presentation; B's native trajectory |
| `skye-c` | Lock + immediate 70-energy payment, 1046 ack action 4, damage delayed exactly 26 ticks, stun applied, HP reduced | Presentation; C reconnect actor recreation |
| `skye-lock-neg` | B/C without a lock and B with an expired lock produce no output at all | Positive behavior (covered above) |
| `minion-push` | Full-world lane: wave 1 walks the A001 mesh, sides meet at lane center (the measured production stalemate), then one recorded post-contact elimination lets survivors resume through production navigation, stepped turret fire and minion-attributed structure damage | Natural long-match push without the fixture; presentation |
| `minion-wave-regression` | With wave 2 spawning distant during the push, a survivor with no eligible nearby target keeps advancing toward its enemy outer turret (guard-window distance delta ≤ 2 u). Protects the `structures is None` precondition in `wave.Director._select_target`; removing that guard was the rejected experiment and is reverted | Presentation |

The earlier removal of the wave combat guard is described accurately as the
failed experiment: it made survivors chase a distant wave instead of
advancing on the vulnerable structure. It was reverted in `wave.py`; the
regression in `server/test/test_wave_sandbox.py` and the
`minion-wave-regression` scenario both protect that decision.

### Commands

```powershell
# Production startup requires the two external corpus variables (see the
# status summary: corr3 rebuilt the archetype-363 spawn chunk, corr7 the
# volley chunks 32/36); without them entity_spawn refuses to build the world.
$env:HALCYON_SPAWN_CORPUS       = "<dir with the match-6 Kraken spawn record>"
$env:HALCYON_SKYE_VOLLEY_CORPUS = "<dir with volley chunks 32 and 36>"

# All six scenarios, two seeded processes each, byte comparison, unique
# external output directory:
python Tools/run_scenarios.py --mode headless --scenario all

# One scenario:
python Tools/run_scenarios.py --mode headless --scenario skye-b

# With an external semantic reference fixture:
python Tools/run_scenarios.py --mode headless --scenario skye-a --reference Z:\path\fixture.json
```

`--output` selects an explicit directory; it must stay outside the repository,
must not traverse a symlink/junction, and a non-empty directory is never
overwritten. `--navmesh` overrides the external A001 path (default
`HALCYON_NAVMESH` or the production default). Exit code 0 requires every
scenario to PASS in both workers, all compared artifacts byte-identical, the
worktree still matching the pin, and any requested reference `VERIFIED`.

### Per-worker artifacts (outside the repository)

| File | Content | Compared |
|---|---|---|
| `events.bin` / `events.jsonl` | Every wire frame as `[u32 tick][u8 phase][u16 opcode][u16 len][payload]` (bootstrap, intent-attributed, simulation phases) | bytes |
| `initial-state.json` | Canonical freeze (`Tools.verify_sandbox.freeze_state`) after setup, before authored intents | bytes |
| `final-state.json` | Canonical freeze at the final tick | bytes |
| `state-checkpoints.jsonl` | Hashed canonical-state checkpoints every 20 ticks | bytes |
| `evidence.json` | Observed metrics, stage details, intents, fixture operations | no |
| `result.json` | Scenario result: status, stages, observed/expected, configuration, manifest digest | no |
| `process-stdout.log` / `process-stderr.log` | Complete worker output with native exit codes | no |

`result.json` records the source manifest digest, per-file SHA-256 hashes, the
navigation mesh digest, `PYTHONHASHSEED` label and runtime module paths that
must resolve inside the snapshot. Wall times, output paths and the seed label
never enter the compared artifacts. Two PASS labels never constitute a
determinism claim: `run_headless` byte-compares the four artifacts, and a
deliberately altered event or state byte fails the comparison even when both
reports say PASS (tested).

### Result schema (scenario `result.json`)

- `status`: `PASS` | `FAIL` | `ERROR` (infrastructure error, never a gameplay
  verdict).
- `stages`: `SETUP`, `INPUT_NOT_OBSERVED`, `INPUT_UNACKNOWLEDGED`,
  `ACCEPTED`, `AUTHORITATIVE_EFFECT`, `PRESENTATION`; each with a stable
  scalar status (`PASS`, `FAIL`, `N/A`, `UNVERIFIED`, `PENDING`) and detail.
- `first_failed_stage` + `failure_detail`: the earliest classified failure.
  A missing cast input (`INPUT_NOT_OBSERVED` failure) is distinct from input
  that arrived but was never acknowledged (`INPUT_UNACKNOWLEDGED`); an
  explicit server rejection would be recorded as such, and an unobserved
  rejection reason stays unknown rather than being inferred.
- `observed` / `expected`: semantic outcome fields.
- `observed_metrics`: the numeric values an external reference may bind.
- `fixture_operations`: every non-production placement/grant, with ticks.
- Wire emission is evidence of authoritative behavior only;
  `PRESENTATION` is `UNVERIFIED` in headless mode.

## Rendered-client driver (`Tools/scenario_client.py`)

**Implemented and mock-tested; live execution is a separate bounded
validation phase.** The runner forwards to it:

```powershell
python Tools/run_scenarios.py --mode client --scenario skye-b `
    --adb-serial emulator-5554 --qa-dir Z:\halcyon_sandbox_qa `
    --wire-trace Z:\halcyon_stack\wire-<ts>.jsonl `
    --timeout 30 --output Z:\halcyon-client-out [--connection ID]
    [--client-profile profile.json] [--reference fixture.json]
```

Supported scenarios: `skye-a`, `skye-b`, `skye-c`, `minion-push`.

### Stage classification

`SETUP` → `UI_COMMAND_SUBMITTED` → `CLIENT_INPUT_OBSERVED` →
`SERVER_ACKNOWLEDGED` → `AUTHORITATIVE_EFFECT` → `PRESENTATION`, with the
same scalar-status discipline as headless. Setup verifies: explicit owned QA
directory outside the repository, supported 960x540 resolution (`wm size`),
a fresh matching trace connection, and progressing WORLD simulation proven
through the driver's own acknowledged read-only QA snapshot requests. A stale
`state.json` after a disconnect is refused even when `match_finished` is
false, and no UI mutation is sent against a refused session.

### Verified wire anchors (current builders, not assumptions)

- c2s `1042`: 14 bytes, native action byte at offset 12. Skye native actions
  A=0, B=2, C=4 (`HERO_ACTIONS[265]`), distinct from UI upgrade slots 0/1/2.
- s2c `1046`: hero u32 at offset 0, native action byte at offset 16.
- `1086`: target u32 @0, source u32 @4, f16 duration @8, instance @10, kind
  u16 @14; Target Lock kind is 602 (`server/abilities.py`).
- s2c `1162` cooldown tag bytes: A `43a890d8`, B `46a89591`, C `45a893fe`
  (FNV-1a of `Ability__Skye__{A,B,C}`, matching the live traces). B may also
  reset the A timer, so the driver only accepts the B/C tag as that ability's
  cooldown evidence; an A-tag movement alone is never B proof.
- Skye C volley actor publication: `1010` with class `0xF59CDB08` @4 and the
  casting hero's eid @112 (`server/skye_wire.build_volley`); an arbitrary
  wave-spawn `1010` does not count.
- Not every `1037`/`1010`/`1054` inside a broad window belongs to the skill:
  damage attribution excludes incoming damage and other actors by
  victim/attacker identity, and classifies a hero→enemy hit as
  `basic_correlated` (excluded) when one Skye basic release (`1037` socket
  `0x77B4B72A`/`0xB1AB2985`, kind 108) precedes it within 0.5 s, one hit per
  release.

### Bounded lock-to-cast sequencing (B/C)

The driver taps the enemy body, waits for the actual `1086` kind-602 lock,
then issues the ability swipe in the same bounded script — no model round
trip and no QA mailbox call between the observed lock and the dependent cast.
Ordinary basic attacks continue inside the window but are classified as
above. Legal QA operations (`learn`, `resources`, teleport of THIS hero to
the verified profile positions) are recorded as `preparation`; forced casts,
forced locks and QA damage are never issued.

### Presentation evidence

The driver captures bounded video/screenshots with unique external names and
start/end/action timestamps, retains partial evidence on failure, and stops
only capture processes it created. An unreviewed recording leaves
`PRESENTATION` at `UNVERIFIED`; capture failure never fails the scenario but
is recorded. In `minion-push` (observational; minions are never teleported or
killed by the driver) a missing event inside the window is reported as that
specific absence (`NOT_OBSERVED`/`UNVERIFIED`), never as success.

### Known profile (explicit current-session validation still required)

Android CE `com.superevilmegacorp.game`, 960x540; Skye at `(0,35)`, enemy at
`(4,35)` away from fountain/turrets; enemy body tap `(603,235)`, feet
`(603,267)` for A aim (body aim previously missed A); A/B/C controls
approximately `(406,496)`, `(480,496)`, `(550,496)`; B drag to `(510,285)`,
C drag to `(603,260)`; points allocated legally so upgrade overlays cannot
intercept skill input; camera/positions re-verified between scenarios,
especially after B. These coordinates must not be applied to an unverified
layout (`--client-profile` may override; resolution mismatch is refused).

## External semantic-reference interface

A reference fixture is externally authored JSON:

```json
{
  "schema_version": 1,
  "provenance": {"source": "...", "captured_at": "..."},
  "compatibility": {"scenario": "skye-a", "hero_id": 265, "enemy_hero_id": 243,
                    "navmesh_sha256": "...", "mode": "headless"},
  "metrics": [{"name": "energy_spent", "expected": 40.0, "tolerance": 0.5}]
}
```

- Missing/unreadable/invalid JSON, wrong schema version, missing provenance
  or malformed metrics → `MALFORMED`; declared setup conditions that do not
  match the run → `INCOMPATIBLE`. Incompatible setups are never silently
  compared.
- Expected values are never generated from the run under test. Synthetic
  fixtures exist only inside unit tests and are identified as such.
- `VERIFIED` means semantic metrics matched within the stated tolerances;
  it is never a raw-packet-equality claim and never official fidelity.
  Without a compatible fixture the status is `UNAVAILABLE`. Internal
  determinism comparisons remain exact (zero tolerance).
- Optional `mode` (`headless`/`client`) restricts the fixture to one driver;
  a fixture without `mode` binds either.

## Verification record, 2026-09-09

Focused checks (this date, this worktree):

- `python -B -m unittest server.test.test_scenario_runner` → **24 tests OK**
  (two-process repeatability, tamper detection, pinning, refusals, registry,
  worker-dispatch regression, client CLI exit mapping, reference handling).
- `python -B -m unittest server.test.test_scenario_client` → **28 tests OK**
  (driver stages and classification over fakes).
- Full pilot: `python Tools/run_scenarios.py --mode headless --scenario all
  --output $TEMP/halcyon-scenario-pilot-20260909` exited **0**. Both workers
  (seeds 11 and 7919) imported one pinned snapshot — pin manifest SHA-256
  `01b91cc2040c09993f3ed9d23def239ae03f7e5f2dcbf65747fbff996c592f3c` — and the
  worktree still matched the pin after the run. Every scenario PASS in both
  workers with byte-identical `events.bin`, `initial-state.json`,
  `final-state.json` and `state-checkpoints.jsonl`. Complete worker stdout/
  stderr and native exit codes are preserved in the run's
  `run-seed*/process-*.log` files; `summary.json` records the per-scenario
  byte-comparison table. Key observed metrics (seed-11 worker): `skye-a`
  energy 24.428 spent, 30 attributed damage events; `skye-b` 4 missile hits,
  dash 4.0 u, zero no-lock acks; `skye-c` 70.0 energy, damage delayed 25
  ticks after the cast tick, stun applied; `skye-lock-neg` all zero;
  `minion-push` 65 combat events, 27.08 u survivor advance, turret damage
  attributed; `minion-wave-regression` additionally wave 2 spawned with
  guard max distance delta 0.0 u (no retreat toward the distant wave).
- Full suite (`python -B -m unittest discover -s server/test`): **873 tests,
  83.321 s, OK (1 skipped, exit 0)**; complete log external at
  `$TEMP/halcyon-scenario-pilot-20260909/full-suite-20260909.log`.
  `git diff --check` exits 0 on the same worktree.

Live client execution of `scenario_client` has NOT been performed; the
rendered-client validation and any independent reference fixture remain the
open next steps. Late-match minion accumulation was observed live; its cause
and its relation to native behavior were not established, and the later match
disconnect's cause is unknown — no claim beyond the observations recorded in
the acceptance-status leaf is made.

## Live rendered-client validation attempt, 2026-09-10 (blocked by a lost
## external prerequisite)

Pre-flight honestly recorded: the 2026-09-09 external pilot directory
(`%TEMP%/halcyon-scenario-pilot-20260909`) was NOT present at session start
(TEMP cleanup) — its recorded results remain historical worker-reported
evidence, and fresh evidence was produced instead.

What was exercised live against the owned LDPlayer 9 emulator
(emulator-5554, 960x540) and the local stack:

- The stack was rebuilt from scratch: regenerated platform CA re-installed
  into the guest trust overlay, a TLS legacy-cipher compatibility fix in
  `server/platform/local_stack.py` (`DEFAULT@SECLEVEL=0`; the client's
  2019-era TLS1.2 CBC suites were rejected with `NO_SHARED_CIPHER` before
  it), and an `answers.json` rebuilt from leaf/libGameKindred.so evidence
  (raw-body bootstrap authority `rpc.kindred-live.net:8443`; full session
  object incl. `notifyUrl` ws://, `bucketIncrementer`, `failoverThreshold`,
  `playerInfo`). With that, menu boot, PLAY→SOLO BOTS→3V3→VERY EASY, Skye
  (265) selection and LOCK IN, roster finalize and WORLD entry all worked
  live (screenshots and gateway/http/rpc logs preserved).
- One driver defect was found and fixed by live execution: the driver
  passed its stage `--timeout` (e.g. 25 s) into the QA mailbox whose legal
  bound is 0..10 s; `QaSession.submit` now clamps. Covered by a new test
  (`test_qa_submit_clamps_stage_timeout_to_mailbox_bound`).

**[SUPERSEDED 2026-09-11 — the "destroyed/unrecoverable" claims below were
wrong: the `vg_max/` corpus, its extraction helpers and the in-repo match
UUID had survived a shallower check. The two WORLD null-deref crashes of
this round (faults 0x0 without tape, 0x8 with an evenly-paced synthesized
tape) and the third round's draft-time abort remain valid observations; the
recovery was completed the next day — see the 2026-09-11 section below.]**

What appeared blocked at the time: three fresh matches entered WORLD and
the client (SIGSEGV, GLThread null-deref) died 6–8 s after world init —
fault 0x0 without `world_tape.bin`, fault 0x8 with a synthesized tape
derived from the surviving phaseB `.vgr` recording. The round concluded,
incorrectly, that the original 53,632-byte `world_tape.bin`, its extraction
scripts (`$TEMP/vg_max/world_after_1137.py`, `decode_world_frames.py`) and
the corpus match UUID had been destroyed. Evidence retained: crash buffer
entries, gateway/http/rpc logs, screenshots and
`%TEMP%/halcyon-client-live-20260910/LIVE-BLOCKED-RECORD.md` (whose
"unique unrecoverable" framing the acceptance-status leaf now supersedes).

Independent reference: still `UNAVAILABLE` — the only owned captures are
Halcyon-side recordings, which prove Halcyon behavior only.

## Prepared next live stage (not executed this round)

Because mid-match passive XP raises levels/ranks between trials, the two
comparable executions per Skye case must come from FRESH MATCHES — one
trial per fresh match with identical legal preparation (the driver's
fixture contract + manifest make any drift visible). The staged commands:

```powershell
# fresh cycle (existing drive sequence): boot client, queue, Skye, lock,
# Manual Build, BACK-dismiss the build panel
python -B Tools/run_scenarios.py --mode client --scenario skye-a `
    --adb-serial emulator-5554 --qa-dir <qa-dir> `
    --wire-trace <fresh trace> --connection <id> --timeout 20 `
    --output <unique dir>            # trial 1
# repeat in the NEXT fresh match with the identical command/profile       # trial 2
# ... likewise skye-b, skye-c
# pair gate for each case (no new executable):
python -B Tools/run_scenarios.py --mode compare-pair `
    --result-a <trial1 client-result.json> `
    --result-b <trial2 client-result.json>
```

The compare-pair gate fails on differing levels/ranks/inventory/maxima or
missing provenance; identity/time-only differences normalize; positions
must sit within 1.5 u and resource drift within measured tolerances. For
the minion structure-interaction stage, a bounded scripted UI attack (the
driver's existing enemy-tap machinery aimed at an OPPOSING MINION) may
clear the stalemate as disclosed NORMAL player assistance — profile and
script prepared, not yet executed; its inputs, authoritative outcomes and
video would all be retained.

## Verification record update, 2026-09-10

- `server.test.test_scenario_client` → **32 tests OK**;
  `server.test.test_scenario_runner` → **24 tests OK**; platform
  identity/fsm suites green against the TLS change.
- Full pilot re-run on the new source pin (worktree == pin):
  `python Tools/run_scenarios.py --mode headless --scenario all --output
  $TEMP/halcyon-scenario-pilot-20260910` exited 0; all six scenarios PASS
  in both seeded workers with byte-identical compared artifacts; worker
  logs and exit codes preserved under the run directory.
- Full suite: **877 tests in 88.929 s, OK (2 skipped, exit 0)**; complete
  log external at `%TEMP%/halcyon-scenario-pilot-20260910/
  full-suite-20260910.log`. The two skips are pre-existing
  environment-conditional cases (operator-owned Catherine input trace;
  external bootstrap comparison tapes not present at their expected paths —
  cause unverified, speculation removed). `git diff --check` exits 0 on the
  same worktree.

## Live rendered-client validation, 2026-09-10/11 (main-review round):
## tape recovered byte-faithfully; Skye A/B/C PASS live

> Superseded in part (2026-09-12, see the status summary). The A/B/C runs
> recorded in this section were the first live casts after the tape recovery;
> their A totals mixed basic hits into the skill attribution and their B/C
> runs had drifted starting states. The declared-fixture gate later replaced
> the drift: A then passed twice inside one match (corr12), B and C twice each
> on fresh matches (corr14, corr16). This section's own observations stand as
> dated history.

The main review corrected the previous round's central premise: the corpus
inputs were never destroyed. `C:/Users/terasumi/AppData/Local/Temp/vg_max/`
still holds `vgfull.pcap`, `s2c.bin`/`c2s.bin` and the original extraction
helpers (`world_after_1137.py`, `decode_world_frames.py`,
`trace_after_lock.py`), and the corpus match UUID
`b9f511e0-11cd-4cfa-ad62-dc8612b8d270` is documented in
`Docs/Teardown/vainglory-protocol-wire.md` (§ around lines 929/975).

**Tape recovery (validated offline, then live):** the authored
`Tools/build_world_tape.py` reassembles the corpus TCP streams, takes the
ACK-causal s2c frames after the client's 1137, floors each frame's
milliseconds relative to the first 1087 allocation, and keeps the documented
12.5 s window. The rebuild is BYTE-FAITHFUL: after the loader's
skip-until-1087 its digest matches the pinned
`20c55322…d341` exactly (1458 records, last t=12478 ms; the 7.3 kB
difference to the historical 53,632-byte file is the loader-skipped
pre-1087 prefix, by design). With that tape, a fresh match entered WORLD
and the client rendered and played.

**Live Skye results on the recovered world** (owned LDPlayer emulator-5554,
960x540; fresh solo-bots match; evidence under
`%TEMP%/halcyon-client-live-20260910/`):

- `skye-a` individual PASS casts live: UI swipe → c2s 1042 action 0 →
  1046 ack → energy payment → 1162 cooldown → attributed barrage damage.
  (The first round's "30/28 events, −788/−841" totals predate the
  tail-kind attribution fix and mixed basic hits into the ability count;
  they are superseded as ATTRIBUTION evidence — and skye-a still has NO
  corrected controlled pair: that is PENDING.)
- `skye-b` two individual PASS casts (2026-09-11, corrected tail
  attribution): 4/4 COMBAT_DELTA_TAIL missile hits each, totals
  −120.0/−116.47, lock→c2s 599.9/569.4 ms (the pre-fix gap was 4.4–5.4 s;
  an aim screenshot sat between lock and cast). These two runs came from
  the SAME match at DIFFERENT declared states (hero/enemy level and rank
  drift) — they are NOT a controlled comparable pair; a controlled pair
  from fresh matches is PENDING.
- `skye-c` two individual PASS casts: 20/16 volley pulses
  −404.41/−333.33, volley actor published, lock→c2s 540.7/624.7 ms —
  same-match runs with drifted levels; NOT a controlled comparable pair
  (fresh-match pairs are PENDING). One earlier C volley demonstrably
  killed the enemy (1072 death at +1.9 s).
- `minion-push` client mode, corrected with the read-only `lane_minions`
  QA census (both teams, uncapped — the snapshot's nearest-64 window had
  truncated discovery to one team): two 35 s windows tracked 37/43 lane
  minions; LANE_APPROACH PASS (34/36 advanced) and OPPOSING_COMBAT PASS
  (141/140 opposing-team 1054 events) remain valid. The original
  SURVIVOR_RESUMPTION counts (34/35) are WITHDRAWN: offline
  reclassification (`%TEMP%/halcyon-client-live-20260910/
  reclassification-20260911/`) shows only 13 of the 34 and 12 of the 35
  claimed survivors intersect the actual combat participant sets (21 and
  23 respectively were nonparticipants), and the episode semantics
  (participant -> engagement end -> proven-alive resume) were not
  evaluated in those windows. STRUCTURE_INTERACTION was not observed
  (equal waves stalemate at lane center, matching the headless
  measurement; the elimination fixture the HEADLESS scenario uses is a
  forced minion death, forbidden client-side — a bounded scripted UI-attack
  assistance profile is prepared for the next live round, disclosed as
  player contribution). Current status:
  `INCOMPLETE_STRUCTURE_INTERACTION` with resumption pending a new
  episode-based window. Survivor counts in the earlier windows are also
  WITHDRAWN under the episode semantics (only 13/34 and 12/35 of the
  claimed survivors were combat participants; 21/23 were
  nonparticipants).

**Driver defects found by live execution and fixed (with tests):** the QA
mailbox timeout clamp; TraceTail must read history (connection discovery);
fresh-connection enforcement; client-controlled-Skye identity (slot-0 eid,
not "any Skye"); explicit enemy placement with strict re-verification; rank
/ leftover-point / cooldown / energy readiness (level-cap leftovers
recorded, not failed); adaptive enemy-bar aiming (orange gradient, ≥10 px
runs; ground aim +100 px, body tap +68 px at the bar's left quarter — the
fixed September taps no longer matched the live camera); one-tap-at-a-time
point spending (burst taps walked the hero 11 u out of framing); capture
lifecycle starting before the first gesture and finalizing on every exit;
failure results retaining all completed stages/gestures/observations/
receipts; damage classification polls the trace after the effect sleeps
and attributes causally by the PRODUCTION 1054 tail byte (basic vs other),
with release/time pairing removed as unsafe for interleaved fire.

**Client-side platform compatibility fix (narrowed after main review):**
the actual blocker is PYTHON'S OWN default context cipher list, which
drops ECDHE-RSA-AES128-SHA (the suite the CE client completes TLS1.2
with); OpenSSL's DEFAULT list at the NORMAL security level 2 includes it
(main-review probe `tls-security-level2-probe.json` + local reproduction).
`build_tls_context()` therefore applies `DEFAULT@SECLEVEL=2` — no security
lowering; the earlier `DEFAULT@SECLEVEL=0` claim of level-necessity is
retracted. Verified live: with the narrowed context the client boots,
menus and full match flow work. Listeners bind 0.0.0.0 (guest
adb-reverse loopback plus the documented LAN deployment), serving this
private deployment; modern peers negotiate TLS1.3 AEAD from the same
context (`server/test/test_tls_context.py` pins legacy + modern +
level).

**Remaining open:** crash classes are distinct — round 1/2 produced two
WORLD-entry null-derefs (faults 0x0/0x8 under missing/synthesized tape),
one draft-time abort (no WORLD entry), and later long-running WORLD
sessions (~30 min idle) crashed with fault 0x38 on otherwise normal wire
traffic — that idle-crash class is an open production-side lead with the
full trace preserved; the controlled trials here all completed inside
short sessions. The minion-push structure-interaction stage remains
NOT_OBSERVED client-side (lane-center stalemate; the headless fixture that
breaks it is a forced minion death, forbidden in live windows).
Independent reference evidence: still `UNAVAILABLE` — no owned capture
satisfies the native reference requirements; specific native metrics are
not derived from this server.

**Checks this round:** focused scenario/client/platform/TLS suites green
(38 client + 24 runner + TLS + platform identity/fsm); headless six-case
two-process comparison re-run on the final pin; full suite after final
changes; logs and exit codes retained externally.

## Offline pair-gate repair, 2026-09-11 (fixture contract + record schema)

Main-review follow-up on the compare-pair path. The gate previously had
two validation paths (a pre-input fixture check built from the live
profile and a pair-time re-derivation from defaults) and could raise on
malformed input instead of reporting. Repaired, all offline:

- **One complete validation path.** `validate_trial_record` now validates
  the record's CARRIED `fixture_contract` + `fixture_manifest` (never a
  reconstruction from `DEFAULT_PROFILE`) and is the single validator used
  by `compare_pair`. `build_fixture_contract` likewise carries
  `declared_fixture` in the contract it returns, so writer and validator
  agree on the schema-v2 keys; schema tests cannot invent a schema.
- **Structured failures, no exceptions.** Structure/type checks precede
  nested access; malformed payloads (non-hex, short, NaN, contradictory
  policies) become named failure strings.
- **Payload-backed attribution.** Every attributed event must be backed by
  its own recorded 1054 payload: victim/attacker identity, the
  f32-exact delta, and the attributed COMBAT_DELTA_TAIL kind byte
  (`payload_backs_hit`); positive (heal/zero) deltas are rejected before
  attribution counting.
- **CLI repaired.** `--mode compare-pair` registers `--result-a`/
  `--result-b` before parsing (it previously crashed after argparse);
  the proof matrix (rows 1–11b) and the round-trip tests now run the
  PUBLIC CLI subprocess on real driver-produced serialized pairs.
- **minion-push schema conformance.** Its client record carries the
  schema-v2 `fixture_contract` key as an honest observational contract
  (`declared_fixture: {}` + census window) — it claims no Skye resource
  fixture it does not validate.

Checks: `server.test.test_scenario_client` → **83 tests OK**;
`server.test.test_scenario_runner` + `server.test.test_wave_sandbox` →
**42 tests OK** (125 total). No live/emulator work in this round; the
fresh-match controlled pairs (two trials per Skye case) remain PENDING
for the next live stage, per the staged commands above.

## Offline pair-gate schema invariant, 2026-09-11 (writer + validator end-to-end)

Continued the 2026-09-11 repair above. The writer/validator pair
previously disagreed on schema completeness (writer omitted `team`,
`enemy.inventory`, `enemy.default_items`, `enemy.statuses`, and a
manifest-level `placement_tolerance`; validator accepted the omissions
silently or crashed on null/list nested objects). End-to-end invariant
implemented, all offline:

- **Writer emits the same required identity/state fields for both actors.**
  The `run_skill` manifest writer now publishes `team`, `inventory`,
  `default_items`, `statuses`, `x`, `y`, `level`, `ranks`, `ability_points`,
  `hp`, `max_hp`, `energy`, `max_energy`, `alive`, `hero_id`, `eid` for
  BOTH Skye and the enemy hero (the QA snapshot already exposes these
  for heroes); enemy fields explicitly inapplicable to the Skye contract
  (`energy_policy = "inapplicable"`) are recorded, not invented zeros.
  The manifest also carries `placement_tolerance` at the top level.
- **Validator consumes the carried contract.** `validate_fixture`,
  `validate_contract_structure`, `validate_trial_record`, and
  `compare_pair` now operate on the record's CARRIED `fixture_contract`
  and `fixture_manifest` end-to-end — never a reconstruction from
  defaults, never a flattened `placement_tolerance` key that does not
  exist. Tolerance and exact resource values are read from the nested
  contract paths.
- **Manifest/contract/declared_fixture agreement.** The validator
  refuses a record whose manifest `declared_fixture` and contract
  `declared_fixture` disagree, whose `exact` policy is declared without
  a finite numeric `*_exact` value, or whose declared positions are not
  finite 2-sequences.
- **Nested type guards come first.** A non-dict contract actor,
  non-dict manifest actor, non-dict observations, non-dict stages, or
  non-dict `stages[name]` entry is a structured FAIL string
  (e.g. `"fixture_contract.skye missing or malformed: [1]"`,
  `"required stage SETUP is NoneType"`) — never an exception, never a
  silently coerced default.
- **Finite-number guards precede `math.dist` / `float()` / sum.** A
  non-finite tolerance, position, exact value, rank value, or coordinate
  becomes a labeled structured FAIL.
- **compare_pair outcome totals are robust to malformed entries.** A
  non-dict `attributed[]` or non-finite `attributed[].delta` is skipped
  from the sum and the per-record failure is reported; the totals gate
  uses the safe sum rather than crashing on `sum(h["delta"] for ...)`.
- **Focused regression coverage.** A new `TestSchemaInvariant` class
  generates a valid schema-v2 record from constants (no live QA, no
  mocked cast delays) and mutates one named defect at a time, asserting
  field-specific structured FAIL with nonzero exit via the PUBLIC
  compare-pair CLI. All 11 named mutation witnesses (missing fields,
  null stages, list actors/observations/contract actors, string tolerance,
  string exact, string ranks, malformed damage delta) produce structured
  FAIL with the expected reason substring and zero Python tracebacks.

Checks: `server.test.test_scenario_client` → **95 tests OK**
(83 prior + 12 new schema-invariant witnesses); focused
`server.test.test_scenario_runner` + `server.test.test_wave_sandbox` →
**42 tests OK**. Total focused offline tests: **137/137**.

Evidence: `C:/Users/terasumi/AppData/Local/Temp/
halcyon-fixture-schema-repair-20260911T113143Z/`
per-case stdout/stderr/exit + regenerated PASS fixtures +
`regenerate_fixtures.py` (the offline writer-shape forward patch used
to carry the static baseline fixtures to the new writer's emitted
schema).

| Witness                       | Expected                  | Observed              | Exit |
|-------------------------------|---------------------------|-----------------------|------|
| baseline                      | PASS                      | PASS (controlled)     | 0    |
| actual_custom_profile         | PASS                      | PASS (controlled)     | 0    |
| fresh_match                   | PASS                      | PASS (controlled)     | 0    |
| missing_inventory_both        | STRUCTURED_FAIL           | skye inventory missing or not a list (both records) | 1 |
| missing_statuses_both         | STRUCTURED_FAIL           | skye statuses missing or not a list (both records) | 1 |
| missing_enemy_x_both          | STRUCTURED_FAIL           | enemy x missing or non-finite (both records) | 1 |
| contract_declared_ranks_string | STRUCTURED_FAIL         | fixture_contract.skye.ranks 'invalid' must be a dict (both records) | 1 |
| stage_null                    | STRUCTURED_FAIL           | required stage SETUP is MISSING + record schema FAIL | 1 |
| actor_list                    | STRUCTURED_FAIL           | manifest.skye missing or malformed: [...] (no traceback) | 1 |
| observations_list             | STRUCTURED_FAIL           | observations missing or not an object: list (no traceback) | 1 |
| contract_actor_list           | STRUCTURED_FAIL           | fixture_contract.skye missing or malformed: [1] | 1 |
| contract_tolerance_string     | STRUCTURED_FAIL           | fixture_contract.skye.position_tolerance 'invalid' must be finite and nonnegative | 1 |
| contract_exact_string         | STRUCTURED_FAIL           | skye_hp_policy is exact but skye_hp_exact='invalid' is not a finite number | 1 |
| hit_delta_string              | STRUCTURED_FAIL (preserved) | attributed[0].delta 'invalid' must be a finite number | 1 |
| trace_path_only               | deferred (next stage)     | structured FAIL (env_config diverges) | 1 |

**Honest pending gates** (next stage, deferred from this dispatch):
- `trace_path_only` — trace-path-only provenance acceptance is an
  independent gate that needs the actual `HALCYON_TRACE_WIRE` env_config
  equivalence rule (the current divergence check is too coarse).
- Real diagnostics integration in tests — `TestPairCliRoundTrip` and
  `TestCausalOutcomeEvidence` still use canned `FakeQa` diagnostics; a
  real `SandboxQA` → client → writer → CLI integration with session and
  process linkage is an open lead.
- Causal outcome evidence for the minion-push structure-interaction
  stage — the minion-push structure-interaction stage remains
  `NOT_OBSERVED` client-side (lane-center stalemate; the headless
  fixture that breaks it is a forced minion death, forbidden in live
  windows).
- Live fresh-match controlled pairs — two full Skye A/B/C trials per
  scenario over a fresh session are the next live stage.

## Offline schema consistency, 2026-09-11 (coherent invariant)

Parent review follow-up. The previous validator admitted several
inconsistencies the contract should have caught (duplicate level vs
measured, inapplicable required resource policies, missing typed
alives, same-team actors, malformed optional metadata reaching the
comparator). End-to-end invariant corrected, all offline:

- **Single canonical contract.** `validate_fixture` reads the carried
  `fixture_contract` as the authoritative source for declared values.
  The validator now compares every nested `contract.skye.*` /
  `contract.enemy.*` value against the corresponding
  `contract.declared_fixture.*` and the `manifest.declared_fixture`
  copy. Equal copies are NOT sufficient — they must also agree with the
  measured manifest and the nested contract values.
- **Resource policies are full/exact ONLY.** `inapplicable` is no
  longer a legal policy value for any actor with that resource pool
  (Skye HP, Skye energy, enemy hero HP). The contract builds
  `skye.energy_policy` / `skye.hp_policy` / `enemy.hp_policy` from
  `declared_fixture.*_policy` directly (None when undeclared) — no
  synthesized default that could later disagree with the
  `declared_fixture` copy.
- **Required identity/state fields are always checked.** The
  `*_required` boolean flags are gone: the validator always checks
  `team`, `inventory`, `default_items`, `statuses`, `ranks`,
  `ability_points`, `hp`, `max_hp`, `energy`, `max_energy`, `alive`,
  `x`, `y` on both actors. A serialized record cannot disable
  `inventory_required` to bypass the inventory check.
- **Real QA-exposed enemy state is now recorded.** The writer's
  `enemy_fields` tuple now publishes the same QA-snapshot fields the
  enemy hero exposes in `SandboxQA.snapshot(world)` (ranks,
  ability_points, energy, max_energy) alongside the existing
  hp/max_hp/x/y. No invented zeros; only fields the production actor
  model exposes are recorded.
- **Typed actor identities and alive booleans.** A new `typed_field`
  helper requires each identity/state field on both actors to be the
  correct JSON-native type (int / float / bool / list / dict). String
  `alive='unknown'`, list `inventory=[…]`, non-dict actor objects all
  become labeled structured FAILs.
- **Distinct eids + opposing teams.** A controlled fixture requires
  Skye and the enemy hero to have different `eid` values and different
  `team` values. `same_team` is a structured FAIL.
- **Declared positions REQUIRED, finite 2-sequences.** Both
  `contract.skye.position` and `contract.enemy.position` are required
  keys on the carried contract; missing or non-finite-2-sequences are
  structured FAIL. Measured placement is checked against them within
  the carried `position_tolerance` (nested on the contract actor, not
  on a flattened key).
- **Structural validation on every nested container.** `scenario` must
  be a STRING before any dict lookup. `observations` must be a dict.
  `result.stages` and `result.stages[name]` must be dicts. The
  optional `provenance.tape_file_identity`, the optional
  `result.presentation`, and the optional `observations.presentation`
  are checked for type if present (a list in any of these is a
  structured FAIL); missing/None remains UNVERIFIED, not FAIL.
- **Same pre-input / serialized invariant.** `validate_fixture` and
  `validate_trial_record` apply the same finite-number / type / list /
  dict guards, the same canonical agreement checks, and the same
  resource-policy semantics. No exception is silently coerced; no
  arithmetic is performed on invalid values.

Checks:
- `server.test.test_scenario_client` → **104 / 104 OK**
  (95 prior + 9 new schema-consistency witnesses).
- `server.test.test_scenario_runner` → **24 / 24 OK**.
- `server.test.test_wave_sandbox` → **18 / 18 OK**.
- **Total focused offline tests: 146 / 146 OK**.

Source hashes at the final stable source:

| Path                                  | sha256 |
|---------------------------------------|--------|
| `Tools/scenario_client.py`            | `2c4bd280d218a8917029d130f103961a8a2b394df9c4dc412fcd50a8c7639e7d` |
| `Tools/run_scenarios.py`              | `828143d06407c54442c965e3dabaabf0dc5d4b6c3de4e05061bd7580e0646c71` |
| `server/sandbox_qa.py`                | `1d31a922b2eeb9ed33184759243f52afbc33d1ab11848ae9e252621250e5c172` |
| `server/test/test_scenario_client.py` | `ecc7587ca000d781164414e5043649fdac3950324fea8eff9c21cddb9548c498` |

Public CLI witness evidence:
`C:/Users/terasumi/AppData/Local/Temp/halcyon-schema-consistency-repair-20260911T120723Z/`
— per-case `a.json`/`b.json` (regenerated from the CURRENT writer, not
patched from old fixtures), `stdout.txt`, `stderr.txt`, `exit.txt`, plus
`regenerate_pass_fixtures.py` and `regenerate_mutations.py` (the offline
writer-shape reproduction scripts).

| Witness                       | Expected          | Exit | First failure string(s) |
|-------------------------------|-------------------|------|--------------------------|
| writer_baseline               | PASS              | 0    | —                        |
| writer_custom                 | PASS              | 0    | —                        |
| missing_inventory             | STRUCTURED_FAIL   | 1    | `manifest skye inventory missing or not a list` |
| stage_null                    | STRUCTURED_FAIL   | 1    | `required stage SETUP is MISSING` |
| exact_string                  | STRUCTURED_FAIL   | 1    | `skye_hp_policy is exact but skye_hp_exact='invalid' is not a finite number` |
| duplicate_level99_vs_measured6 | STRUCTURED_FAIL  | 1    | `declared_fixture.skye_level=99 disagrees with contract.skye.level=6 — declaration copies must agree` |
| required_skye_hp_inapplicable  | STRUCTURED_FAIL  | 1    | `skye_hp_policy 'inapplicable' is not full/exact` |
| missing_enemy_inventory_flag   | STRUCTURED_FAIL  | 1    | `manifest enemy inventory missing or not a list` |
| same_team                      | STRUCTURED_FAIL  | 1    | `skye and enemy share team 1 — the enemy must be on the opposing team` |
| boolean_actor_alive            | STRUCTURED_FAIL  | 1    | `manifest skye alive='unknown' must be a boolean` |
| scenario_array                 | STRUCTURED_FAIL  | 1    | `result.scenario [] is not a string` |
| presentation_array             | STRUCTURED_FAIL  | 1    | `observations.presentation is list, not an object` |
| tape_identity_array            | STRUCTURED_FAIL  | 1    | `provenance.tape_file_identity is list, not an object` |
| missing_declared_positions     | STRUCTURED_FAIL  | 1    | `fixture_contract.skye.position missing — declared placement is required` |

Zero Python tracebacks across all 14 witnesses (grep for
`Traceback|AttributeError|TypeError|ValueError|KeyError|IndexError|NameError`
in `stderr.txt` files returned no matches).

## Offline schema invariant, 2026-09-11 (coherent invariant; later gaps found)

Parent review follow-up. The previous dispatch admitted several
divergences between the carried contract and the measured manifest,
plus the validator silently substituted 1.5 for a legitimate zero
tolerance and the `alive` check passed when both actors were dead.
The pre-input entry point also raised `ValueError`/`TypeError` on
malformed shapes. Corrected offline; NOTE: later rounds found further
gaps (required prepared points, declaration presence, hero identity —
see the sections below), so this section's fixes are preserved but the
invariant was NOT complete at this point.

- **Each actor must independently be alive.** The previous
  `if skye.get("alive") is True and enemy.get("alive") is not True`
  chain let both alive=False pass; both actors now FAIL with
  per-actor labels (`skye is not alive at validation time
  (alive=False)` / `enemy is not alive at validation time
  (alive=False)`).
- **Canonical agreement covers the flattened top-level keys too.** The
  previous canonical check compared only nested contract values
  against `declared_fixture`. The flattened keys
  (`skye_hp_policy`, `skye_hp_exact`, `skye_energy_policy`,
  `skye_energy_exact`, `enemy_hp_policy`, `enemy_hp_exact`) are the
  ones the `resource()` check actually reads, so they too must agree
  with `declared_fixture` and the nested contract values.
- **Declared identity must match the measured row.** The carried
  contract's `skye.eid` / `enemy.eid` / `skye.team` / `enemy.team`
  must equal the corresponding values on the measured manifest
  actors; the controlled-fixture identity is the actor that actually
  exists in the snapshot.
- **`contract.slot` must equal the manifest slot and the scenario's
  expected slot.** The validator now checks `contract.slot`,
  `manifest.slot`, and `manifest.scenario` for mutual agreement
  (scenario `skye-b` requires slot `B`, `skye-a` requires slot `A`,
  `skye-c` requires slot `C`).
- **Legitimate zero tolerance is honored, not silently substituted.**
  `position_check` now uses the carried tolerance directly (a zero
  tolerance means an exact placement check). The old
  `tol_sk or 1.5` mask is gone.
- **Pre-input entry returns labeled structured FAIL, never a
  Python exception.** The `resource()` `exact` branch uses
  `finite_number()` on the exact value before any
  `float(exact)` coercion; the `position_check` defensively
  re-checks declared-pos element types before reaching
  `math.dist`. Both pre-input negatives
  (`preinput_exact_string` and `preinput_bad_position`) now return
  a list of structured failure strings.
- **Production QA shape is preserved, not fabricated.** The
  `FakeQa` harness enemy hero row no longer fakes
  `ability_points=0` / `gold=0` / `xp=0` — production
  `SandboxQA.snapshot(world)` exposes these as `None` before an
  economy exists, and the `resources` command creates the economy.
  The validator's `typed_field` now accepts `None` for
  `ability_points` only (the only field production exposes as
  None before an economy). All other typed fields remain strict.
- **Audit of currently declared but ignored actor fields.**
  `skye.energy`/`skye.max_energy` (always required, always typed
  float), `enemy.energy`/`enemy.max_energy` (same — production
  exposes them for both heroes), `skye.ability_points` (optional,
  None before economy). The `compare_eq` skip-on-None path is the
  only place a None value is allowed past the typed check.

Checks:
- `server.test.test_scenario_client` → **112 / 112 OK**
  (104 prior + 8 new schema-invariant witnesses).
- `server.test.test_scenario_runner` → **24 / 24 OK**.
- `server.test.test_wave_sandbox` → **18 / 18 OK**.
- **Total focused offline tests: 154 / 154 OK**.

Source hashes at the final stable source:

| Path                                  | sha256 |
|---------------------------------------|--------|
| `Tools/scenario_client.py`            | `143bf2ea8fc49ce41299dd5e189e6c1b9cbf027c1c049be8a839f00ecb05538f` |
| `Tools/run_scenarios.py`              | `828143d06407c54442c965e3dabaabf0dc5d4b6c3de4e05061bd7580e0646c71` |
| `server/sandbox_qa.py`                | `1d31a922b2eeb9ed33184759243f52afbc33d1ab11848ae9e252621250e5c172` |
| `server/test/test_scenario_client.py` | `8c3d6e82852c79e297a824aaca51566c1cfc9e1355f645a4683076316b0a0db2` |

Public CLI witness evidence:
`C:/Users/terasumi/AppData/Local/Temp/halcyon-schema-invariant-repair-20260911T124129Z/`
— per-case `a.json`/`b.json` regenerated from the CURRENT writer
(writer_baseline: default positions, full resource policies;
writer_custom: shifted positions `[10.0, 38.0]`/`[14.0, 38.0]`,
`placement_tolerance=0.5`, actual exact HP=1100.0 and exact
energy=900.0 policies). The trial roots are preserved under each
case so QA receipts, harness traces, the prepared `profile.json`
and the `out/` artifacts remain in the evidence directory.
Companions: `regenerate_pass_fixtures.py`,
`regenerate_mutations.py`, `preinput_negatives.py`.

| Witness | Expected | Exit | First failure string(s) |
|---|---|---|---|
| writer_baseline | PASS | 0 | — |
| writer_custom | PASS | 0 | — |
| missing_inventory | STRUCTURED_FAIL | 1 | `manifest skye inventory is None — required list` |
| stage_null | STRUCTURED_FAIL | 1 | `required stage SETUP is MISSING` |
| exact_string | STRUCTURED_FAIL | 1 | `skye_hp_policy is exact but skye_hp_exact='invalid' is not a finite number` |
| duplicate_level99_vs_measured6 | STRUCTURED_FAIL | 1 | `declared_fixture.skye_level=99 disagrees with contract.skye.level=6 — declaration copies must agree` |
| required_skye_hp_inapplicable | STRUCTURED_FAIL | 1 | `skye_hp_policy 'inapplicable' is not full/exact` |
| missing_enemy_inventory_flag | STRUCTURED_FAIL | 1 | `manifest enemy inventory is None — required list` |
| same_team | STRUCTURED_FAIL | 1 | `skye and enemy share team 1 — the enemy must be on the opposing team; contract enemy team 2 != measured enemy team 1 — the controlled-fixture team must match the measured snapshot row` |
| boolean_actor_alive | STRUCTURED_FAIL | 1 | `manifest skye alive='unknown' must be a boolean` |
| scenario_array | STRUCTURED_FAIL | 1 | `result.scenario [] is not a string` |
| presentation_array | STRUCTURED_FAIL | 1 | `observations.presentation is list, not an object` |
| tape_identity_array | STRUCTURED_FAIL | 1 | `provenance.tape_file_identity is list, not an object` |
| missing_declared_positions | STRUCTURED_FAIL | 1 | `fixture_contract.skye.position missing — declared placement is required` |
| both_actors_dead | STRUCTURED_FAIL | 1 | `skye is not alive at validation time (alive=False); enemy is not alive at validation time (alive=False)` |
| flat_hp_exact_overrides_declared_full | STRUCTURED_FAIL | 1 | `declared_fixture.skye_hp_policy='full' disagrees with contract.skye_hp_policy='exact' — the flattened key the resource check actually reads must agree` |
| declared_eid_mismatch | STRUCTURED_FAIL | 1 | `contract skye eid 9999 != measured skye eid 1500 — the controlled-fixture identity must match the measured snapshot row` |
| declared_team_mismatch | STRUCTURED_FAIL | 1 | `contract enemy team 99 != measured enemy team 2 — the controlled-fixture team must match the measured snapshot row` |
| contract_slot_mismatch | STRUCTURED_FAIL | 1 | `contract.slot 'A' != manifest.slot 'B' — the carried contract's slot must match the manifest's slot` |
| zero_tolerance_missed_placement | STRUCTURED_FAIL | 1 | `skye actual position (0.5, 38.0) is 0.50u from the declared position (0.0, 38.0) (tolerance 0.0u)` |
| preinput_exact_string | STRUCTURED_FAIL (pre-input, no CLI) | — | `declared_fixture.skye_hp_policy='full' disagrees with contract.skye_hp_policy='exact'` |
| preinput_bad_position | STRUCTURED_FAIL (pre-input, no CLI) | — | `contract skye position ['invalid', 38] must be a finite 2-sequence` |

Zero Python tracebacks across all 22 cases (grep for
`Traceback|AttributeError|TypeError|ValueError|KeyError|IndexError|NameError`
in `stderr.txt` files and pre-input `result.json` files returned no
matches).

**Honest pending gates** (still open, deferred to the next stage):

- `trace_path_only` provenance equivalence rule (current check too
  coarse).
- Real `SandboxQA` → client → writer → CLI integration in tests
  (`TestPairCliRoundTrip`, `TestCausalOutcomeEvidence` still canned
  `FakeQa`; session/process linkage still discarded by setup).
- Causal outcome evidence for the minion-push structure-interaction
  stage — remains `NOT_OBSERVED` client-side.
- Live fresh-match controlled pairs — two full Skye A/B/C trials per
  scenario over a fresh session are the next live stage.
- Skye causal serialized evidence and minion offline lifecycle/order
  correction remain pending before any live stage.

## Offline required prepared state + declaration enforcement, 2026-09-11 (GLM-5.3-Flash correction)

Continuation after a quota-blocked round; the interrupted worker's
partial changes (FakeQa resources economy, prepared-points profiles,
slot type guards, required measured points) were preserved and
validated against production evidence, then the two remaining
acceptance failures were fixed.

**Production preparation fidelity (validated, not mock-matched).**
Main's actual `SandboxQA.pump(resources)` receipts
(`halcyon-schema-required-review-cpulrrbp/production-preparation.json`)
show both heroes move from `ability_points=null, gold=null` to
`ability_points=1, gold=600.0, xp=0.0` with successful receipts. The
fixture seam (`FakeQa.resources`) now reproduces exactly that
economy creation on the targeted hero per resources call, and the
writer validates AFTER preparation — so the writer's default/custom
profiles declare `skye_points=1` / `enemy_points=1` and the measured
manifest carries `ability_points=1` for both actors. Pre-preparation
snapshots (points null) stay honest as NEGATIVES: a record whose
declaration says 1 but whose measured points are null/missing fails
(`current_writer_unknown_points`, `missing_measured_skye_points`).

**Required declaration presence + declared hero identity.** The two
remaining parent failures are fixed:
- `missing_declared_enemy_team` — `contract.enemy.team` is a REQUIRED
  identity declaration; missing (or `contract.skye.hero_id`/`eid`/
  `team` missing) is a structured FAIL, never a silent skip.
- `declared_skye_hero_id_mismatch` — declared `hero_id` is compared
  with the measured row for Skye (and for the enemy when a producer
  explicitly declares it); 999 vs measured 265 fails.

**Emitted-contract field audit** (documented in
`build_fixture_contract`): enforced fields (slot; skye hero_id/eid/
team; enemy team; declared level/ranks/points; positions and
tolerances; flattened resource policies the resource check actually
reads) vs explicitly observational metadata (`enemy.hero_id`=None —
contract built before the enemy row is measured, measured enemy
hero_id still required on the manifest; enemy energy policy —
preparation restores enemy HP only; top-level placement_tolerance
reference copy). Inventory/default_items/statuses are measured
manifest state only, pair-compared at the state gate.

**Pre-input structural guards.** `contract.slot=[]` no longer raises
TypeError and `contract.slot='Z'` no longer raises KeyError — both
return labeled structured failures; missing `manifest.slot` is a
structured failure. Shared slot validation runs in BOTH entry points
(direct `validate_fixture` and serialized CLI).

**Checks (final stable source, focused only).**
`server.test.test_scenario_client` → **118/118 OK** (112 prior +
6 new: missing enemy team, hero_id mismatch + analogous required-
presence/declared-enemy-hero-id/eid-string/missing-measured-points);
`server.test.test_scenario_runner` → 24/24;
`server.test.test_wave_sandbox` → 18/18. Total focused: **160/160**.
Full per-test log: `focused-suite.log` in the evidence directory.

**Source hashes at the final stable source:**
`Tools/scenario_client.py`
`9ab80512dc3649cee2581984c493091a34dd92067e97b9b93db6fd6a9c6dd5e1`;
`Tools/run_scenarios.py`
`828143d06407c54442c965e3dabaabf0dc5d4b6c3de4e05061bd7580e0646c71`;
`server/sandbox_qa.py`
`1d31a922b2eeb9ed33184759243f52afbc33d1ab11848ae9e252621250e5c172`;
`server/test/test_scenario_client.py`
`9ab99bbf76d86820e7c34eb22041d60c3851bf34552d72f39b11ed3924561533`.

**Evidence:**
`C:/Users/terasumi/AppData/Local/Temp/halcyon-schema-required-repair-glm-2026-09-11T14-45-49/`
— fresh unpatched writer default/custom pairs (trial roots retained
with QA receipts, harness traces, prepared profile.json, out/
artifacts), `known_points_control` (historical self-consistent
fixture), 6 CLI negatives, 3 pre-input negatives, per-case
stdout/stderr/exit, `hashes.json` (source + all 23 inputs),
`focused-suite.log` (169 lines, 160 pass), and the regeneration /
runner scripts. Prior partial evidence preserved untouched at
`...halcyon-schema-required-repair-20260911T132741Z/`.

| Case | Expected | Exit | First failure string |
|---|---|---|---|
| writer_baseline (fresh, prepared) | PASS | 0 | — |
| writer_custom (fresh, prepared, exact policies) | PASS | 0 | — |
| known_points_control (historical) | PASS | 0 | — |
| current_writer_unknown_points (old null-points output) | STRUCTURED_FAIL | 1 | `manifest skye ability_points is None — a missing known-empty collection cannot equal a valid empty collection; required int` |
| missing_measured_skye_points | STRUCTURED_FAIL | 1 | same field-specific points failure |
| declared_skye_eid_string | STRUCTURED_FAIL | 1 | `contract skye eid '1500' must be a finite integer when present` |
| missing_declared_enemy_team | STRUCTURED_FAIL | 1 | `contract enemy team missing — required identity declaration (the carried contract always emits it)` |
| declared_skye_hero_id_mismatch | STRUCTURED_FAIL | 1 | `contract skye hero_id 999 != measured skye hero_id 265 — the declared hero identity must match the measured snapshot row` |
| malformed_declared_inventory | STRUCTURED_FAIL | 1 | `contract skye inventory 'invalid' must be a list when present` |
| preinput_slot_list | STRUCTURED_FAIL | — | `contract.slot [] is not a string — the skill-slot lookup requires a string` |
| preinput_slot_unknown | STRUCTURED_FAIL | — | `contract.slot 'Z' is not A/B/C — the skill-slot lookup requires a known slot` |
| preinput_missing_slot | STRUCTURED_FAIL | — | `manifest.slot missing — required to identify the skill slot the contract gates` |

Zero Python tracebacks across all CLI stderr and pre-input results.

**Still pending (unchanged scope):** full diagnostics-to-writer
integration and trace config normalization; causal Skye serialized
evidence; minion offline lifecycle/order; controlled live pairs and
presentation review; final acceptance. No unqualified
"invariant complete" claim is made: the schema gates above are the
measured state of THIS offline correction.

## Offline enemy-rank declaration enforcement, 2026-09-11 (GLM-5.3-Flash)

Small correction closing the last emitted-contract audit gap:
`build_fixture_contract` documents enemy ranks as enforced when
declared, but `validate_fixture` compared ranks only for Skye and the
canonical declaration-copy map omitted `enemy_ranks`. Now applied
consistently to BOTH actors:

- **Declared-vs-measured rank equality (both actors).** A shared
  `compare_ranks` covers matching values, unequal values, missing
  slots (declared key absent from measured) and extra slots (measured
  key absent from the declaration). Undeclared (None) enemy ranks
  stay observational — an explicitly supplied expectation is
  enforced, never dropped or relabeled.
- **Declaration-copy agreement covers `enemy_ranks`.** The canonical
  map now checks `declared_fixture.enemy_ranks` against the nested
  `contract.enemy.ranks` (and via the existing manifest-copy equality)
  for both actors.
- **Malformed rank values** (non-dict map, non-string keys, non-finite
  values) were already reported by the contract shape guard for both
  actors; unchanged.

Measured CLI outcomes (fresh unpatched writer positives + mutations;
evidence directory below):

| Case | Expected | Exit | First failure |
|---|---|---|---|
| writer_baseline (fresh, prepared) | PASS | 0 | — |
| writer_custom (fresh, prepared, exact policies) | PASS | 0 | — |
| missing_declared_enemy_team (preserved) | STRUCTURED_FAIL | 1 | `contract enemy team missing — required identity declaration` |
| declared_skye_hero_id_mismatch (preserved) | STRUCTURED_FAIL | 1 | `contract skye hero_id 999 != measured skye hero_id 265` |
| declared_enemy_ranks_match | PASS | 0 | — |
| declared_enemy_ranks_mismatch | STRUCTURED_FAIL | 1 | `enemy rank 0 0 != declared 1` |
| enemy_rank_declaration_copies_disagree | STRUCTURED_FAIL | 1 | `declared_fixture.enemy_ranks=... disagrees with contract.enemy.ranks=... — declaration copies must agree` |

Both entry points checked: each negative also produces the same
labeled failure through direct pre-input `validate_fixture`.

**Checks:** `server.test.test_scenario_client` → **123/123 OK**
(118 prior + 5 new: ranks match/mismatch/copies-disagree CLI
witnesses + missing/extra-slot and malformed-value pre-input cases).
Runner suite untouched (no runner dependency changed); the verified
160-test focused log from the prior round is retained — no
wave/full-suite/headless/TLS/tape rerun. Zero tracebacks.

**Source hashes:** `Tools/scenario_client.py`
`f9fc694b0e954e19379e5b61979529474dacd4b96e1ea69590d73c75af91f623`;
`server/test/test_scenario_client.py`
`e7edd345b97a8010c98390ab971550aafb0869477cfb379afc3724dffa052555`;
runner/QA unchanged
(`828143d0…`, `1d31a922…`).

**Evidence:**
`C:/Users/terasumi/AppData/Local/Temp/halcyon-enemy-ranks-repair-glm-2026-09-11T15-05-17/`
— fresh writer_baseline/writer_custom pairs with retained trial roots
(QA receipts, harness traces, prepared profile.json, out/ artifacts),
7 CLI witness cases with stdout/stderr/exit, `hashes.json` (5 source
+ 14 input hashes), `client-suite.log` (123 pass), regeneration
script.

**Still pending (unchanged):** full diagnostics-to-writer integration
and trace config normalization; causal Skye serialized evidence;
minion offline lifecycle/order; controlled live pairs and
presentation review; final acceptance.

> Superseded in part (2026-09-12, see the status summary). The causal Skye
> evidence and the minion offline lifecycle/order items were closed by the
> checkpoint series below; the diagnostics linkage now reaches the records
> (live) and the pair CLI (offline). The pending list is better read as dated:
> of it, the controlled live pairs and the presentation review are the ones
> still open today.


## Offline diagnostics linkage: setup boundary + record serialization, 2026-09-11 (DeepSeek-V4-Flash, early checkpoints)

Two bounded checkpoints toward the real offline provenance stage. **The full
diagnostics integration is still incomplete** — endpoint restart/progress
linkage, trace-output-path normalization and the real `SandboxQA.pump`
integration remain open.

> Superseded in part (2026-09-12): this paragraph describes the state before
> the checkpoint series below. The linkage it calls incomplete is what later
> rounds exercised — it is carried into every writer record as
> `provenance.diagnostics`, and the 2026-09-12 live declared-fixture gate used
> it (corr9/corr13 refused, corr12/corr14/corr16 passed). See the status
> summary for what remains open.

**Checkpoint 1 (accepted):** `ClientDriver.setup()` no longer swallowed the
`ClientStageFailure` raised by the diagnostics-linkage validator. A receipt
that was RECEIVED and cannot be vouched for (different match than the
session snapshot, malformed/untyped fields, non-world or finished session)
now fails SETUP before any gameplay gesture; a genuinely missing receipt
(transport error) keeps the pre-existing best-effort path. Measured witness:
mismatched-match diagnostics raise `[SETUP/FAIL] diagnostics receipt lacks
coherent trial linkage: diagnostics match_id 'different-match' != session
snapshot match_id 'qa-session' …` with zero tap/swipe calls, and matching
diagnostics still permit setup with the typed linkage retained.

**Checkpoint 2 (this round):** the linkage validated at setup is carried
verbatim into every writer-produced record as `provenance.diagnostics`
(pid, startup_at, match_id, phase, match_finished, tick, time) and
re-validated per record by the public compare-pair CLI. `PAIR_SCHEMA_VERSION`
is now **3**; the setup boundary and the record validator share ONE
field-checker, so the receipt accepted at setup is exactly the receipt the
pair gate re-reads (no reconstruction from defaults, no invented values when
a receipt never arrived). A record whose linkage is missing, malformed,
finished/ended, or belongs to a different match than its own
`fixture_manifest.match_id` can never be a `controlled_pair`.
Fresh-session identity (pid, startup_at, match_id, tick, time) is judged
**per record only** — the two records of a pair are never required to share
it, so a legitimate second process/match still passes.

Measured CLI outcomes (unpatched writer pair + mutations; evidence dir below):

| Case | Expected | Exit | First failure |
|---|---|---|---|
| writer-pair-default (fresh writer output) | PASS | 0 | — |
| different-fresh-session-identities | PASS | 0 | — |
| missing-linkage | STRUCTURED_FAIL | 1 | `record_B: provenance.diagnostics missing — no process/startup/session linkage evidence; acceptance blocked` |
| malformed-pid | STRUCTURED_FAIL | 1 | `provenance.diagnostics: pid '4242' is not an integer` |
| malformed-phase | STRUCTURED_FAIL | 1 | `phase 'draft' is not an active WORLD session` |
| malformed-match_finished | STRUCTURED_FAIL | 1 | `match_finished True is not False — the match has ended or the state is unknown` |
| malformed-tick | STRUCTURED_FAIL | 1 | `tick '100' is not an integer` |
| malformed-time | STRUCTURED_FAIL | 1 | `time '5.0' is not a finite number` |
| wrong-match-linkage | STRUCTURED_FAIL | 1 | `diagnostics match_id 'some-other-match' != fixture_manifest match_id 'qa-session' — the receipt and the measured fixture are not the same match` |
| previous-schema record (kept as a NEGATIVE input) | STRUCTURED_FAIL | 1 | `schema_version 2 != 3; provenance.diagnostics missing …` |

**Checks (python -B, focused only; no full client suite/headless/wave/TLS/
tape rerun):** `server.test.test_scenario_client` → new
`TestDiagnosticsLinkagePair` **6 passed + 8 subtests**; focused run over
`TestSetupDiagnosticsLinkage + TestFixtureContract + TestCausalOutcomeEvidence
+ TestPairCliRoundTrip + TestSchemaInvariant + TestProofMatrix` → **79 passed
+ 19 subtests**. Zero tracebacks in every CLI case. Synthetic record
constructors were updated for the required schema; previous evidence files
were NOT edited — they stay valid negative inputs.

**Source hashes:** `Tools/scenario_client.py`
`a0c4bed0a1c9e6df47266059b58ea530bc99fa256e7f8f355529573956be8c2a`;
`server/test/test_scenario_client.py`
`bc9d84f2e1e1e2fc6bd23ab30ddbaa30c8100ec0685384654360b9dce77c3709`;
runner/QA unchanged (`828143d0…`, `1d31a922…`).

**Evidence:** `C:/Users/terasumi/AppData/Local/Temp/halcyon-linkage-serialize-20260911T132527Z/`
— unpatched writer trial roots (`writer-pair/`), per-case CLI records with
stdout/stderr/exit (`cli/<case>/`), `evidence-summary.json`, focused logs
(`linkage-pair.log`, `focused-suite.log`), `reviewed-source/`.
Checkpoint-1 evidence remains at
`.../halcyon-setup-diagnostics-linkage-20260911T131908Z/`.

**Still pending (unchanged):** endpoint restart/progress linkage, trace
config normalization, real `SandboxQA.pump` integration; causal Skye
serialized evidence; minion offline lifecycle/order; controlled live pairs
and presentation review; final acceptance.


### Trace enable-switch equivalence (checkpoint 3 + correction, 2026-09-11)

`HALCYON_TRACE_WIRE` was compared as semantic configuration, so two
otherwise identical trials failed merely for enabling tracing with different
recorded values. Production semantics (`server/match_server.py`: `if
os.environ.get("HALCYON_TRACE_WIRE")`) read only the variable's TRUTHINESS
and then generate their own `wire-<time_ns>.jsonl` — the variable is an
**enable switch**, so the recorded string is the switch setting, not
necessarily the file actually written.

`compare_pair` now compares `provenance.env_config` through
`normalize_env_config`, which reduces that single entry to an explicit
enable/disable TOKEN and leaves every other entry — including
`HALCYON_NO_BOTS` / `HALCYON_NO_TAPE` / `HALCYON_NO_WAVE` — at its exact
recorded value. `None` and `""` are recorded-disabled and compare equal to
each other; an ABSENT key is **not** a disabled value and never compares
equal to one. Raw records are not rewritten: both records keep their raw
recorded value, and the pair verdict reports `env_trace_normalization` with
the raw values.

**Correction (reviewer witness):** the first form normalized the switch to a
BOOLEAN, and Python's `True == 1` let malformed numeric/boolean values
collide with valid ones — a recorded integer `1` compared equal to a valid
enabled string (`halcyon-parent-trace-review-yy50hgts`, exit 0). A PRESENT
trace entry is now validated PER RECORD as string-or-null
(`validate_trial_record`); any other type is malformed receipt evidence and
is rejected before any comparison, and the comparison token is no longer a
boolean.

Measured CLI outcomes (public `--mode compare-pair`; evidence dir below):

| Case | Expected | Exit |
|---|---|---|
| reviewer witness: B integer `1` vs A enabled string | STRUCTURED_FAIL | 1 |
| integer `1` / `0` / boolean `true` / `false` vs enabled string | STRUCTURED_FAIL | 1 |
| integer `1` / `0` / boolean `true` / `false` vs disabled `null` | STRUCTURED_FAIL | 1 |
| identical malformed value in BOTH records (`1`, `false`) | STRUCTURED_FAIL | 1 |
| two enabled records with different recorded values | PASS | 0 |
| two disabled records (`null` vs `""`) | PASS | 0 |
| enabled vs disabled | STRUCTURED_FAIL | 1 |
| disabled vs absent key | STRUCTURED_FAIL | 1 |
| `HALCYON_NO_BOTS` value changed / `HALCYON_NO_WAVE` added | STRUCTURED_FAIL | 1 |

**Checks:** `TestEnvTraceNormalization` **6 passed + 25 subtests**;
focused pair/provenance regression subset (setup boundary, linkage pair,
fixture contract, causal outcome, CLI round trip, schema invariant, proof
matrix) **91 passed + 52 subtests**. Zero tracebacks; the CLI never rewrote
its input records (`inputs_unchanged_by_cli: true` in every case).

**Source hashes:** `Tools/scenario_client.py`
`ee2bec46c8e164658e57e875a96a0c0c808125c99923397cd5bfd8b639cc959c`;
`server/test/test_scenario_client.py`
`58dc3da350871b1a84cdf74e814bafa57657a26e486ef3148d5b658c5e769bf0`;
runner/QA unchanged (`828143d0…`, `1d31a922…`).

**Evidence:** `C:/Users/terasumi/AppData/Local/Temp/halcyon-trace-type-correction-20260911T134206Z/`
— reviewer-witness replay with the exact copied inputs, per-case CLI
records/outputs/exits, before/after sources with scoped diff,
`evidence-summary.json`, focused logs. The pre-correction run remains at
`halcyon-trace-env-normalize-20260911T133439Z/`.

**Still pending (unchanged):** endpoint restart/progress linkage, real
`SandboxQA.pump` integration; causal Skye serialized evidence; minion
offline lifecycle/order; controlled live pairs and presentation review;
final acceptance.


### Trial endpoint continuity (checkpoint 4, 2026-09-11)

`PAIR_SCHEMA_VERSION` is now **4**. Every writer trial reads a SECOND
diagnostics receipt — the endpoint receipt — AFTER the whole time-sensitive
action sequence (never between the basic hit and the dependent cast) and the
record carries it raw as `provenance.diagnostics_end` alongside the existing
initial `provenance.diagnostics` (both mirrored in `observations`). The pair
validator requires both receipts per record, validates each with the same
shared field-checker, requires each to agree with that record's own
`fixture_manifest.match_id`, and then compares the two receipts INSIDE the
trial: same `pid`, `startup_at` and `match_id`, `phase == "world"` and
`match_finished is False` at both ends, and strictly advancing `tick` and
simulation `time`. A trial that changed process/match, or whose world stalled
or regressed, is not a live trial and can never be a `controlled_pair`.
Fresh-session identity is still judged per record: two separate trials may
legitimately differ in pid, startup_at, match_id, tick and time origins.

Endpoint evidence failures are EVIDENCE failures: an unacknowledged receipt
(mailbox bound) is `TRIAL_CONTINUITY / UNVERIFIED`, a malformed or
non-object receipt is `TRIAL_CONTINUITY / FAIL`, and the already-observed
`CLIENT_INPUT_OBSERVED` / `SERVER_ACKNOWLEDGED` / `AUTHORITATIVE_EFFECT`
stages keep their own statuses — a collection problem is never reported as a
failed UI action, and a failed endpoint read never fabricates a linkage.

The offline fake was made honest rather than convenient: `FakeQa` derives
every linkage field (pid/startup_at per fake process, match_id/phase/
match_finished/tick/time) from its own live state, and its snapshot advances
`tick += 2` with `time = tick * 0.05`, mirroring production
`server/match_server.py` (`SIM_TICK = 0.05`, `sim_time = sim_tick * SIM_TICK`),
so an endpoint receipt is later because the fake world advanced — not
because successful fields were inserted into the serialized record.

Measured CLI outcomes (public `--mode compare-pair`, unpatched writer pair +
one mutation each; evidence dir below):

| Case | Expected | Exit |
|---|---|---|
| unpatched writer pair (both receipts, tick 104→118, time 5.2→5.9) | PASS | 0 |
| endpoint pid changed (same match) | STRUCTURED_FAIL | 1 |
| endpoint startup_at changed | STRUCTURED_FAIL | 1 |
| endpoint match_id changed | STRUCTURED_FAIL | 1 |
| endpoint phase `draft` / `match_finished true` | STRUCTURED_FAIL | 1 |
| endpoint receipt missing / non-object (list) | STRUCTURED_FAIL | 1 |
| endpoint tick string / time missing | STRUCTURED_FAIL | 1 |
| endpoint tick stalled (104→104) / regressed (104→64) | STRUCTURED_FAIL | 1 |
| endpoint time stalled (5.2→5.2) / regressed (5.2→3.2) | STRUCTURED_FAIL | 1 |
| identical malformed endpoint in BOTH records | STRUCTURED_FAIL | 1 |
| previous schema-3 record (no endpoint receipt) | STRUCTURED_FAIL | 1 |

**Checks (python -B, focused only; no full client suite / headless / wave /
TLS / tape rerun):** new `TestTrialEndpointContinuity` **10 passed** (writer
positive + 16 CLI cases + 3 driver-level evidence failures); regression
subset `TestSetupDiagnosticsLinkage + TestDiagnosticsLinkagePair +
TestEnvTraceNormalization + TestFixtureContract + TestCausalOutcomeEvidence +
TestSchemaInvariant` **70 passed**; `TestProofMatrix + TestPairCliRoundTrip`
**21 passed**. Zero tracebacks in every CLI case. Synthetic record
constructors and the two fresh-session positive rows were updated for the
required schema; earlier records were NOT edited and stay valid negative
inputs.

**Source hashes:** `Tools/scenario_client.py`
`3151c1531d8d606644288dfa9c74a695de6d564a022c67ed43a62fd806bddd0c`;
`server/test/test_scenario_client.py`
`f8d1abed54ebb68d5a28ecaf4e0ad808400e951665b63f542148009bbe980edd`;
runner/QA unchanged.

**Evidence:** `C:/Users/terasumi/AppData/Local/Temp/halcyon-trial-endpoint-continuity-20260911T150814Z/`
— `before/` (the accepted checkpoint-3 sources) and `after/` with scoped
diffs, both serialized writer records, per-case CLI inputs/outputs/exits
(`cli/`, `cli-cases.jsonl`), focused logs (`endpoint-suite.log`,
`linkage-trace-fixture-schema.log`, `proof-matrix-pair-cli.log`),
`evidence-run.py`, `hashes.json`, `evidence-summary.json`.

**Still pending:** real `SandboxQA.pump` integration for the endpoint read;
the minion-push client window (which does not yet collect an endpoint receipt
and therefore cannot enter a controlled pair); causal Skye serialized
evidence; minion offline lifecycle/order; controlled live pairs and
presentation review; final acceptance.

### Real-QA offline integration (checkpoint 5 + correction, 2026-09-11)

This supersedes the checkpoint-4 "still pending: real `SandboxQA.pump`
integration for the endpoint read" line for the Skye path.
`server/test/test_scenario_client.py:TestRealQaIntegration` runs the writer
against the REAL production stack offline: a real
`server/match_server.SnapshotStream` world advanced by its own fixed ticks,
driven through the real `SandboxQA` mailbox (`Tools/sandbox_qa.submit`, the
same entry point the live stack uses) and the real `run_client` writer. Two
serialized records PASS the public compare-pair CLI (exit 0,
`controlled_pair: true`); only the client-side observations stay mocked (ADB
adapter, rendering, wire trace), and the client intents are fed through the
production inbound queue so `SERVER_ACKNOWLEDGED` / `AUTHORITATIVE_EFFECT`
read real authoritative state (real Skye B energy payment, slot-1 cooldown,
Suri missiles). A real same-match authority restart stays a bounded
`TRIAL_CONTINUITY` failure with the earlier stages intact.

Fixture discipline, measured: the fixture OWNS its environment and production
tape path for the whole construction/loading/diagnostics lifetime and hands
the caller's back exactly (caller env and `WORLD_TAPE_PATH` identical before
and after). It is self-contained under a caller `HALCYON_NO_TAPE=1`: the
declared tape still loads its two frames (loaded digest `89441fbf…`, 32-byte
declared file, both receipts live reads of that declared input rather than the
operator corpus file). A `SubprocessTripwire` refuses and records every
process spawn during integration execution (zero attempts in the accepted
pair, and the unpatched-ADB regression case refused by its recorded argv
`adb -s emulator-5554 shell input tap 348 218`).

**Evidence:** `C:/Users/terasumi/AppData/Local/Temp/halcyon-ckpt5-correction-20260911T154657Z/`
— `evidence-summary.json`, both writer records, the restart-failure record,
verbatim CLI stdout/stderr, raw QA receipts, the correction diff and
baselines, focused logs. The accidental-live-run disclosure and its artifacts
from the earlier checkpoint-5 revision are retained untouched.

### Minion observation endpoint continuity (checkpoint 6, 2026-09-11)

`ClientDriver.run_minion_push` now reads the SAME endpoint diagnostics receipt
the cast trial reads — after the bounded observation window and before the
result is constructed — through `collect_endpoint_linkage`: shared typed field
checks, `collect_trial_continuity_failures`, and the same serialization into
`provenance.diagnostics_end` (mirrored in `observations`). Nothing else in the
observational path changed: no new lifecycle inference, no participant, order
or outcome rule changes.

The four independently measured gameplay stages are set BEFORE the endpoint
read, so a missing, unacknowledged, malformed, restarted or stalled endpoint
leaves `LANE_APPROACH` / `OPPOSING_COMBAT` / `SURVIVOR_RESUMPTION` /
`STRUCTURE_INTERACTION` exactly as they were measured. A continuity PASS is
never enough: the incomplete-sequence check still runs afterwards.

Measured (focused offline, fake session + real writer; evidence dir below):

| Case | Record | Outcome |
|---|---|---|
| full lane sequence | PASS | four stages PASS, `TRIAL_CONTINUITY` PASS, endpoint tick 104→108, time 5.2→5.4 |
| endpoint `startup_at` changed (same pid, same match) | FAIL | `TRIAL_CONTINUITY` FAIL, four stages keep PASS |
| endpoint reply pending (mailbox bound) | FAIL | `TRIAL_CONTINUITY` UNVERIFIED, four stages keep PASS |
| endpoint reply rejected | FAIL | `TRIAL_CONTINUITY` UNVERIFIED, four stages keep PASS |
| endpoint receipt malformed (fields missing) | FAIL | `TRIAL_CONTINUITY` FAIL, four stages keep PASS |
| endpoint result non-object (list) | FAIL | `TRIAL_CONTINUITY` FAIL, four stages keep PASS |
| movement + combat only (no resumption/structure) | FAIL | `TRIAL_CONTINUITY` PASS, `AUTHORITATIVE_EFFECT` NOT_OBSERVED |

**Boundary (explicit, not glossed):** a minion record is still NOT one half of
a controlled pair. The public compare-pair CLI judges the cast-trial contract
(cast stages PASS, skill slot A/B/C, `fixture_manifest`) and refuses a
minion-push record — exit 1, `controlled_pair: false`, failures
`required stage UI_COMMAND_SUBMITTED is N/A; …; fixture_manifest
missing/malformed`. This stage closes the endpoint-collection gap only; the
remaining acceptance gates are unchanged and unclaimed.

**Checks (python -B, focused only; no full client / wave / TLS / tape suite
rerun):** new `TestMinionEndpointContinuity` **4 passed**;
`TestMinionPushClient + TestTrialEndpointContinuity + TestRealQaIntegration`
**22 passed** (the Skye endpoint classes and the real-QA integration
unchanged); `server.test.test_scenario_runner` **24 passed**. Zero tracebacks.

**Source hashes:** `Tools/scenario_client.py`
`3a361e02f476356b7768fb24d72a01aad981c828969c4dbf904365181009f148` (was
`3151c153…`; 16 insertions, 1 deletion — all inside `run_minion_push`);
`server/test/test_scenario_client.py`
`5c513c49c540f79207f6584e8ca50ec145f12f39e772a5619ab3b7324a17a4a9` (was
`1862d5c5…`); `server/sandbox_qa.py` and `server/match_server.py` unchanged.

**Evidence:** `C:/Users/terasumi/AppData/Local/Temp/halcyon-ckpt6-minion-endpoint-20260911T155659Z/`
— `before/` and `after/` with scoped diffs, the exact writer record of every
case above (`*.writer-record.json`), `evidence-summary.json`,
`cli-minion-boundary.stdout.json`, focused logs (`logs/`), and
`evidence-run.py`.

**Still pending after this stage:** minion offline lifecycle/order validation
(the causal sequence above the observation window); controlled live minion
pairs and presentation review; causal Skye serialized evidence; independent
reference fixtures; final acceptance. **Correction (checkpoint 7):** the
sentence that stood here — "the Skye live pair remains accepted" — was wrong
and is withdrawn. No controlled live A/B/C pair has been accepted. What is
accepted is the OFFLINE real-QA integration above (real world + real QA
mailbox + real writer, mocked client-side observation). The 2026-09-11
rendered-client result is a record of INDIVIDUAL live observations — Skye A,
B and C each rendered and passed their own stages, twice each, with a
reviewed kill video — not a controlled pair, not a repeatability claim, and
not an acceptance of the live path. Controlled live A/B/C pairs, live
repeatability and presentation review remain open.

### Skye B serialized causal evidence (checkpoint 7, 2026-09-11)

`validate_trial_record` now runs `collect_skye_b_causal_failures` (renamed to
`collect_skye_cast_causal_failures`, now shared with `skye-a`, in checkpoint 8)
on every
`skye-b` record: the carried input, the acknowledgment, the cooldown-timer
receipt and the attributed damage must describe ONE action by ONE actor on ONE
connection inside the observed action window, and the outcome summary must
repeat the carried attribution at EXACT counts and four-decimal totals — no
tolerance, no percentage, no invented default. A slot-only timer tag, or damage
from another actor, connection or time, cannot establish the cast's outcome.

Two serialization gaps had to close first, in the existing capture path (no new
path, no second writer): no record could previously bind the timer tag to its
actor or the attributed damage to its session.

- `observations.cooldown_tag.eid` — the actor the tag was matched against.
- `observations.damage_classification.attributed[].connection`.

Measured (focused offline — unmodified writer output and the public
compare-pair CLI; evidence directory below):

| Case | Single change | CLI verdict |
|---|---|---|
| writer pair | none (raw `run_client` output) | exit 0, `controlled_pair: true` |
| checkpoint-5 writer pair | none (historical bytes, unedited) | exit 1 — slot-only tag, unbound attributed rows |
| timer receipt | slot-only / other actor / A's tag / before its ack | exit 1 |
| input | action / connection / missing | exit 1 |
| acknowledgment | action / before input / missing | exit 1 |
| attributed damage | connection / time outside window / other-actor payload / edited delta | exit 1 |
| action window | opens before the input / does not advance | exit 1 |
| outcome summary | count +1 / total ±0,0001 / missing | exit 1 |

All 19 negatives: exit 1, `controlled_pair: false`, structured failure lines
naming the linkage, empty stderr, no traceback. The positive carries
`client_input.connection` = record connection = manifest connection, the B
native timer tag `46a89591` bound to the trial hero eid 1500, four attributed
hits inside `[input, input + 2.659 s]`, `attributed_events` 4 and
`outcome_total` −120.0 (four × −30.0).

**Boundary (explicit, not glossed):** the slice covers `skye-b` only. `skye-a`
must still bind its own input/ack/window evidence and `skye-c` must bind the
volley publications; the minion window needs its own causal slice; setup,
provenance, fixture-contract and endpoint-continuity checks are untouched. The
synthetic `TestSchemaInvariant` fixture now carries a self-consistent causal
block built from constants — a fixture for one-defect-at-a-time schema
witnesses, explicitly not measured evidence; the writer-produced positive lives
in `TestSkyeBCausalEvidence`. No live pair, no gameplay claim and no
raw-packet-equality fidelity claim is made here.

**Checks (python -B, focused only; no client / wave / TLS / tape suite rerun):**
`server.test.test_scenario_client` **167 passed** (includes new
`TestSkyeBCausalEvidence`, 6 tests, and the re-homed `TestProofMatrix` /
`TestSchemaInvariant` fixtures); `server.test.test_scenario_runner` **16 of 24
passed, 8 blocked by a missing external prerequisite** — every blocked test
starts a scenario worker that refuses without the archetype-363 Kraken spawn
capture ("external jungle spawn records missing for 363"), which is no longer
present anywhere on this machine (`%TEMP%/vg_phaseB/vgr_live` is gone and no
surviving corpus directory carries 363). Those failures are worker-startup
setup failures, not a regression of this slice: `Tools/run_scenarios.py` and
the worker path are untouched (hashes below), and the same tests passed at
checkpoint 6 when that capture was still present.

**Source hashes:** `Tools/scenario_client.py`
`e4b7f44ba1702f0863821a108080036babaaf99da3bf58f8a06be1d0d47b1922` (was
`3a361e02…`; 257 insertions, 1 deletion — the causal validator, its wiring and
the two serialization additions); `server/test/test_scenario_client.py`
`4584bc52f1471ca5abad004bea9e55855494a669137e5d52954b21b947ad0cc1` (was
`5c513c49…`); `server/sandbox_qa.py` and `server/match_server.py` unchanged.

**Evidence:**
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt7-skye-b-causal-20260911T162859Z/`
(mirrored to `%TEMP%/halcyon-ckpt7-skye-b-causal-20260911T162859Z/`) — `before/`
copies with scoped diffs, the exact writer records (`writer-record-a/b.json`),
the unedited historical pre-slice records (`preslice-*.json`), per-case CLI
stdout/stderr for the positive and all 19 negatives, `evidence-summary.json`,
`hashes.json`, the focused logs and `evidence-run.py`. **Disclosure:** the
first checkpoint-7 evidence directory
(`halcyon-ckpt7-skye-b-causal-20260911T161546Z`) and the earlier
`halcyon-ckpt5-correction-20260911T154657Z` directory disappeared from `%TEMP%`
after being written and read back; sibling directories survived and no
deletion was issued by this work, and the cause is not established. The result
was regenerated from the unchanged sources, the evidence is now mirrored
outside `%TEMP%`, and the historical pre-slice bytes were re-taken from the
surviving checkpoint-5 real-QA directory. This is reported rather than hidden:
the loss is environmental, and it is the same event that removed the external
spawn capture the runner suite needs.

**Still pending after this stage:** skye-a causal binding (input/ack/window),
skye-c causal binding (volley publications), the minion causal/lifecycle slice,
controlled live A/B/C pairs and presentation review, independent reference
fixtures, and final acceptance.

### Checkpoint 7 correction: receipt window and wire binding (2026-09-11)

**The proven false PASS:** a writer-produced pair whose acknowledgment was
moved to `window_end + 100 s` and whose timer receipt was moved to
`window_end + 101 s` still returned exit 0 and `controlled_pair: true`,
because the receipts were only ordered against each other (`ack >= input`,
`timer >= ack`) and never bounded by the window the driver had recorded. A
receipt timestamped outside the observed window cannot establish the cast.

**Fix (bounded to `skye-b`, existing writer/validator path):**

- The receipts now carry their own wire bytes and session:
  `client_input.payload` (c2s 1042), `acknowledgment.connection` +
  `.payload` (s2c 1046), `cooldown_tag.connection` + `.payload` (1162). No new
  executable path and no second writer.
- `collect_skye_b_causal_failures` re-derives each receipt from those bytes
  with the SAME parsers the driver matched with (`ground_cast_action`,
  `position_event_action` + eid @0, `timer_tag_eid`) and requires agreement
  with the metadata, the trial's connection and actor; a receipt with no bytes
  is refused ("its action/eid metadata cannot bind itself to an observed
  packet").
- Both the acknowledgment and the timer receipt must lie INSIDE the driver's
  own recorded observation window (`_receipt_window_check`). The window is
  production observation semantics — it opens at the observed c2s input and
  closes when the driver classified the effect — and no timing tolerance is
  invented on top of it.

**Measured (offline, public compare-pair CLI; evidence directory below):**

| Case | Verdict |
|---|---|
| current writer pair, unmodified | exit 0, `controlled_pair: true` |
| parent's preserved witness (`ack = window_end+100`, `timer = window_end+101`) | exit 1 — window violation in `record_B`, plus the missing receipt bytes/connection of records that predate this correction |
| the same mutation applied to a CURRENT writer record | exit 1 — both receipts "outside the observed action window … cannot establish this cast" |
| 13 single-linkage negatives (ack/timer past window, ack/timer/input on another connection, ack payload action/eid, timer payload tag/eid, input payload action, ack/timer payload absent, ack connection absent) | all exit 1, `controlled_pair: false`, structured reasons, empty stderr, no traceback |
| historical checkpoint-5 pre-slice pair | still exit 1 |

The writer positive keeps exact counts and four-decimal totals (4 events,
−120.0) and still binds input/ack/timer to one actor (eid 1500), one
connection (424242), their own wire bytes, and time inside
`[input, input + 2.659 s]`. Prior actor/damage/count/total and endpoint
checks are unchanged.

**Checks (python -B, focused only):** `TestSkyeBCausalEvidence` **9 passed**;
the directly impacted writer classes (`TestProofMatrix`, `TestSchemaInvariant`,
`TestPairCliRoundTrip`, `TestTrialEndpointContinuity`, `TestSkyeBFlow`,
`TestSkyeCVolleyAttribution`, `TestSlotAttribution`,
`TestCausalOutcomeEvidence`, `TestMinionPushClient`,
`TestMinionEndpointContinuity`, `TestRealQaIntegration`) **95 passed**.
`TestProofMatrix`'s fresh-session witness now re-homes the receipts too, and
`TestSchemaInvariant`'s synthetic base carries receipt bytes — both fixtures,
not measured evidence (the writer-produced positive remains the acceptance
one). The suite was NOT run in full this round.

**Source hashes:** `Tools/scenario_client.py`
`d62eb19413de864790fc2596b7fc3dc8400e4938b0f075705c50b37de7c68902` (was
`e4b7f44b…`; 167 insertions, 38 deletions); `server/test/test_scenario_client.py`
`bdc145403d6ee1fdf5047c71c6fe6b70d497b910ca1260a01169abfcc21c54db` (was
`4584bc52…`); `server/match_server.py`, `server/sandbox_qa.py` and
`Tools/run_scenarios.py` unchanged.

**Evidence:**
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt7corr-receipt-window-20260911T164907Z/`
— `before/` (the checkpoint-7 state, reconstructed from the recorded
checkpoint-7 diff and verified byte-identical to the checkpoint-7 hashes),
scoped diffs, the unmodified writer records, the parent's witness records
copied byte-for-byte (their recorded sha256 are reproduced in `hashes.json`),
per-case CLI stdout/stderr for the positive, the parent witness, the
parent-shaped mutation and all 13 negatives, `evidence-summary.json`,
`hashes.json`, and the focused logs. Prior artifacts and the `%TEMP%` loss
disclosures above are preserved; everything new is written under
`%LOCALAPPDATA%/halcyon-evidence/`.

**Unresolved dependency (unchanged, explicit):** the 8 `test_scenario_runner`
setup failures from the missing archetype-363 Kraken spawn capture remain
unresolved; no asset recovery or corpus search was performed this round. They
are candidate regressions until final validation, not verified non-regressions.

**Still pending:** skye-a input/ack/window binding, skye-c volley binding, the
minion causal slice, controlled live A/B/C pairs and presentation review,
independent reference fixtures, and final acceptance.

### Checkpoint 7 final window correction: input timestamp (2026-09-11)

The parent's second preserved witness
(`halcyon-parent-input-window-tq9cnrjn/`, `a.json` sha256 `0c4e7d93…`,
`b.json` sha256 `271b900a…`) proved a second false PASS on the same writer
path: with the writer untouched in A and only
`observations.client_input.time` moved 100 s earlier in B — the acknowledged
input, the acknowledgment, the cooldown receipt and the attributed damage all
otherwise byte-identical — the CLI still exited 0 with
`controlled_pair: true`. The cause was the one-sided bound
`window_start < input_time`: it rejects a window that opens *before* the
input, but accepts any input timestamp at or before the window start, so a
cast could be re-dated arbitrarily far into the past.

**The writer's actual relationship, measured not invented.** In the driver's
own cast path (`run_skye_b_cast`) the classification window is opened at the
c2s record it observed — `window_start = cast_time = client_input["time"]` —
and closed when the driver observes the effect. The relationship is therefore
an exact equality at the window start, with no tolerance of any kind. The
validator now enforces `window_start != input_time` directly, citing that
driver relationship in the failure text, rather than any invented ordering
tolerance. On the fresh writer witness the measured values are identical
(`window_start` == `client_input.time` == 1789145942.4069319, `equal: true`),
and on the parent's witness the refusal names both actual values
(1789145636.3450499 vs 1789145536.3450499).

**Measured table (`python -B`, focused):**

| case | exit | controlled pair |
|---|---|---|
| unchanged writer A/B positive | 0 | **true** |
| parent witness (input.time −100 s) | 1 | false |
| input.time −100 s on our writer | 1 | false |
| input.time +1 s (inside window) | 1 | false |
| input.time past window end | 1 | false |
| ack past window end | 1 | false |
| timer past window end | 1 | false |
| ack payload action disagreement | 1 | false |
| timer payload tag disagreement | 1 | false |
| ack other connection | 1 | false |

All ten refusals exit 1 with `controlled_pair: false`, empty stderr and no
traceback; the previously corrected ack/timer window bounds, connection
binding and payload re-derivation are retained unchanged.

**Checks (focused only, not the 95-test set and not the full suite):**
`TestSkyeBCausalEvidence` **9 passed**; the directly necessary writer checks
`TestProofMatrix` + `TestSchemaInvariant` **59 passed**.

**Source hashes:** `Tools/scenario_client.py`
`e3c1f34b4b175d5d4b038fb0f5243b1c795feef54de1d2f8d96e77d41e431629` (was
`d62eb194…`); `server/test/test_scenario_client.py`
`91d1cd6aca43b1194b6bfe58fc3a7121fb2e50998295cb718fb69333feffc65e` (was
`bdc14540…`); `server/match_server.py`, `server/sandbox_qa.py` and
`Tools/run_scenarios.py` unchanged.

**Evidence:**
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt7fin-input-window-20260911T165740Z/`
— `before/` (the receipt-window correction state, reconstructed from its
recorded diffs and verified byte-identical to its hashes), scoped diffs, the
unmodified writer records, the parent's witness copied byte-for-byte, per-case
CLI stdout/stderr for the positive, the parent witness, the parent-shaped
mutation and all 8 negatives, `evidence-summary.json`, `hashes.json` and the
focused logs. Older witnesses were kept immutable. All new evidence lives
under `%LOCALAPPDATA%/halcyon-evidence/`; the earlier `%TEMP%` loss
disclosures stand.

**Unresolved dependency (unchanged, explicit):** the 8 `test_scenario_runner`
setup failures from the missing archetype-363 Kraken spawn capture remain
unresolved and are candidate regressions until final validation, not verified
non-regressions.

**Still pending:** skye-a input/ack/window binding, skye-c volley binding, the
minion causal slice, controlled live A/B/C pairs and presentation review,
independent reference fixtures, and final acceptance.

### Checkpoint 8: Skye A serialized causal binding (2026-09-12)

The B slice is accepted; this round extends the appropriate checks to
`skye-a`, sharing them rather than copying the B checker. Reading A's capture
path first showed the semantics are the same: `ClientDriver.run_cast_scenario`
captures every cast slot through the identical `wait_client_input` /
`wait_acknowledgment` / `wait_cooldown_tag` / `classify_damage(window_start=
cast_time)` calls, so the only slot-specific values are the native action (A
0, B 2) and the native timer tag (A `43a890d8`, B `46a89591`). The one capture
difference — B and C additionally require an observed Target Lock
(`requires_lock=slot in ("B", "C")`) — is a capture step only and is
deliberately absent from the shared checker; the writer-produced A record is
asserted to carry **no** `lock` observation while still being a controlled
pair, so no B-only lock requirement is imported into A.

`collect_skye_b_causal_failures` is therefore renamed
`collect_skye_cast_causal_failures(result, manifest, slot)` and gates A and B
from `validate_trial_record` (C and minion unchanged this round). The checks
are B's own, unchanged: input action/connection/its own c2s bytes; the window
relationship `window_start == client_input.time` with no tolerance; ack
action/actor/connection/its own 1046 bytes/inside the window; timer
slot/tag/actor/connection/its own 1162 bytes/inside the window; attributed
damage actor/connection/time/delta; and the carried outcome's exact event
count and four-decimal total. A's measured writer relationship is the same
equality: `window_start == client_input.time` == 1789146779.1626785 with the
window closing at 1789146783.520939 (mocked offline harness, explicitly not
live evidence).

**Measured (`python -B`, offline; public compare-pair CLI):**

| case | exit | controlled pair |
|---|---|---|
| unchanged writer A pair (skye-a) | 0 | **true** |
| unchanged writer B pair (skye-b, retained) | 0 | **true** |
| parent's B window witness (read-only) | 1 | false |
| parent's B input witness (read-only) | 1 | false |
| 34 single-link A negatives | 1 | false |

The 34 A negatives cover: input action to another skill / payload carrying
another action / payload missing / other connection / −100 s / +1 s / past
window end / missing; ack action / payload action / payload actor eid /
payload missing / other connection / past window / before its own input /
missing; timer slot / tag / payload tag / payload eid / payload missing / eid
missing (slot-only) / other connection / past window / before its own ack /
missing; attributed damage other connection / outside window / other actor /
edited delta / emptied attribution; and the summary's count +1, total ±0.0001
and missing. All exit 1 with an empty stderr and no traceback.

**Checks (focused only):** `TestSkyeACausalEvidence` + `TestSkyeBCausalEvidence`
**16 passed**; the directly impacted writer classes (`TestProofMatrix`,
`TestSchemaInvariant`, `TestPairCliRoundTrip`, `TestTrialEndpointContinuity`,
`TestSkyeBFlow`, `TestSkyeCVolleyAttribution`, `TestSlotAttribution`,
`TestCausalOutcomeEvidence`, `TestMinionPushClient`,
`TestMinionEndpointContinuity`, `TestRealQaIntegration`, `TestFixtureContract`,
`TestDiagnosticsLinkagePair`) **114 passed**. The full suite was NOT run.

**Source hashes:** `Tools/scenario_client.py`
`300c2c44b09818b6c2a2965153e78c0da5e90d67691582b1acf2bb54dd554bee` (was `e3c1f34b…`); `server/test/test_scenario_client.py`
`9a6cb4506141ea879cd206fdcbcb5d7082b4306e1b7107d00b8b980c868bf504` (was `91d1cd6a…`); `Docs/Plan/solo-sandbox-scenarios.md` was
`4a927494cc65bc832b170ffaf3c5797692a6cd00c9670b04a321090b78c2c36b` before this section was appended (a file's own hash cannot include
itself; the resulting file's hash is in the evidence dir's `hashes.json`); `server/match_server.py`, `server/sandbox_qa.py` and
`Tools/run_scenarios.py` unchanged. (Exact values in the evidence dir's
`hashes.json`.)

**Evidence:**
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt8-skye-a-causal-20260912T001228Z/`
— `before/` (the checkpoint-7 final state, reconstructed from its recorded
diffs and verified byte-identical to its hashes), scoped diffs, unmodified A
and B writer records, per-case CLI stdout/stderr for both positives, both
preserved parent witnesses and all 34 negatives, `evidence-summary.json`,
`hashes.json`, `README.md` and the focused logs. Older witnesses and prior
evidence dirs are untouched; everything new is under
`%LOCALAPPDATA%/halcyon-evidence/`.

**Boundary (explicit, not glossed):** this slice is A and B only, and it is
offline — the fake harness supplies the observations, so nothing here is live
client evidence. skye-c still has to bind its volley publications, the minion
window needs its own causal slice, and controlled live A/B/C pairs,
presentation review, independent reference fixtures and final acceptance
remain open. The 8 `test_scenario_runner` setup failures from the missing
archetype-363 Kraken spawn capture remain unresolved and are candidate
regressions until final validation, not verified non-regressions.

### Checkpoint 9: Skye C receipts and volley publication binding (2026-09-12)

A/B were accepted; this round extends the common receipt/window/connection/
exact-outcome checks to C and closes the volley-publication hole. C's capture
path is the same shared `run_cast_scenario` flow, so the shared checker now
gates slots A, B and C unchanged — C's native action 4 and tag `45a893fe` are
the slot-specific values. What was missing was C's own evidence: the writer
matched its 1010 publications and recorded only
`observations["volley_actors"] = <count>`, which establishes no publisher, no
session and no instant.

The matched publications now travel with their own bytes:
`observations["volley_publications"] = [{time, connection, payload}, …]`, and
`collect_skye_c_volley_failures` re-derives each one with the existing parser
(`volley_owner`: class @4, owner @112, the parser's own hex-length convention),
binding owner == trial hero, class == `f59cdb08`, connection == trial
connection, and time inside the driver's own observed window
`[window_start, window_end]` — the same window rule the input/ack/timer
receipts and the attributed damage are held to. The carried count must equal
the carried publications.

**What is deliberately NOT claimed:** a publication establishes the volley's
publisher, class, session and instant — not that the volley caused the
attributed damage. No per-publication ↔ per-pulse identity is carried anywhere
in this record, so the damage evidence remains exactly the payload-backed 1054
attribution with its exact event count and four-decimal total. Binding a
publication to the individual damage pulses would need evidence this path does
not carry; that is a separate bounded slice and is not invented here.

**Measured C relationships (unmodified writer record, offline fake session):**
window `[1789147450.7550209, 1789147455.11875]` with `window_start ==
client_input.time` (no tolerance); input/ack action 4; timer slot C tag
`45a893fe`; a Target Lock IS observed in the C capture step (as for B, and
still never a validator requirement); one publication of 126 bytes, class
`f59cdb08`, owner 1500 == hero eid, connection 424242 == trial connection,
0.6507 s after the input and inside the window; 8 attributed events totalling
−169.2.

**Measured (`python -B`, public compare-pair CLI):**

| case | exit | controlled pair |
|---|---|---|
| unchanged writer C pair (skye-c) | 0 | **true** |
| unchanged writer A pair (retained) | 0 | **true** |
| unchanged writer B pair (retained) | 0 | **true** |
| parent's B window witness (read-only) | 1 | false |
| parent's B input witness (read-only) | 1 | false |
| 28 single-link C negatives | 1 | false |

The 28 C negatives: publications missing / emptied / not a list (count-only
evidence); count above, below and zero; publication owner, class, connection
and time (past the window end and before the recorded input); publication
payload missing / not hex / too short / time missing; the shared receipt checks
on C's own action and tag (input action, input earlier by 100 s, input past the
window, input payload action, input connection, ack past window, ack payload
action, ack connection, timer payload tag, timer past window, timer slot,
damage connection, outcome total ±0.0001). All exit 1 with `controlled_pair:
false`, empty stderr and no traceback.

**Checks (focused only):** `TestSkyeCVolleyCausalEvidence` +
`TestSkyeACausalEvidence` + `TestSkyeBCausalEvidence` + `TestSkyeCVolleyAttribution`
**25 passed**; the directly affected writer classes (`TestSchemaInvariant`,
`TestProofMatrix`, `TestCausalOutcomeEvidence`, `TestPairCliRoundTrip`)
**62 passed**. The full suite was NOT run.

**Source hashes:** `Tools/scenario_client.py` and
`server/test/test_scenario_client.py` changed; `server/match_server.py`,
`server/sandbox_qa.py`, `Tools/run_scenarios.py` unchanged. Exact after/before
values and the scoped diffs are in the evidence dir's `hashes.json`;
`Docs/Plan/solo-sandbox-scenarios.md` was
`a3cbc1065f9ea2c86e97064dc715d04467f9dd64a439b6939effdb0801d1e61b` before this
section was appended.

**Evidence:**
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt9-skye-c-volley-20260912T002339Z/`
— `before/` (the checkpoint-8 state, reconstructed from its recorded diffs and
verified byte-identical to its hashes), scoped diffs, unmodified C/A/B writer
records, per-case CLI stdout/stderr for all three positives, both preserved
parent witnesses and all 28 negatives, `evidence-summary.json`, `hashes.json`,
`README.md` and the focused logs. Prior witnesses and evidence dirs are
untouched.

**Boundary (explicit, not glossed):** this slice is offline and covers A, B and
C only. The minion window still needs its own causal slice; controlled live
A/B/C pairs and presentation review, independent reference fixtures and final
acceptance remain open. The 8 `test_scenario_runner` setup failures from the
missing archetype-363 Kraken spawn capture remain unresolved and are candidate
regressions until final validation, not verified non-regressions.

#### Correction: decoded payload bounds for C publications (2026-09-12)

The parent's preserved witness
(`halcyon-parent-volley-length-ucfqbik0/`, `b.json` sha256 recorded in the
evidence dir) proved the new publication guard was still checking hex
CHARACTERS while `bytes.fromhex` ignores whitespace: a payload of `'00'` plus
252 spaces is 254 characters but decodes to a single byte, passed the
character count, and then raised `struct.error` out of the public CLI when the
owner read ran past the buffer (exit 1 **with a traceback**, which is not a
structured refusal).

The guard now counts DECODED bytes against the declared publication shape
(`VOLLEY_PUBLICATION_BYTES = 126`, class @4, owner @112) and reports a
structured failure *before* any parser read; the class read uses the decoded
buffer directly rather than re-decoding. The valid writer payload is unchanged
at 252 hex characters / **126 decoded bytes** and is still accepted, so the
earlier 252-decoded-byte mistake is not repeated.

**Measured (`python -B`, public compare-pair CLI):** the unmodified writer C
pair is still a controlled pair (exit 0); the parent's witness is now exit 1,
`controlled_pair: false`, **empty stderr and no traceback**, refused with
"decodes to 1 byte(s) — whitespace-padded, so its character count is not its
byte count, fewer than the 126-byte C volley publication shape". The
correction's focused negatives — one byte padded with whitespace, whitespace
only (decodes to zero bytes), a real publication truncated to 60 bytes both
padded and unpadded (class readable, owner not), and a two-byte payload — all
give structured refusals; the retained owner/class/connection/window/count
checks and the count-only negative still refuse. 12 negatives in total, all
exit 1 with `controlled_pair: false`, empty stderr and no traceback.

**Checks (focused only):** `TestSkyeCVolleyCausalEvidence` **7 passed**; the
directly necessary parser tests (`TestWireParsers`) **6 passed**. No broad
suite was run.

**Source hashes:** `Tools/scenario_client.py` and
`server/test/test_scenario_client.py` changed; exact before/after values and
the scoped diff are in the evidence dir's `hashes.json`.
`Docs/Plan/solo-sandbox-scenarios.md` was
`d74ffbbe9a9efddf395dec74baf0343b41d9a5cd9dbbdeebc80813d54aaaaf4a` before
this note.

**Evidence:**
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt9corr-volley-length-20260912T002912Z/`
— `before/` (the checkpoint-9 state, reconstructed from its recorded diffs and
verified byte-identical to its hashes), the scoped diffs, the unmodified C
writer records, the parent witness's own hashes and verdict, per-case CLI
stdout/stderr for the positive, the witness and all 12 negatives,
`evidence-summary.json`, `hashes.json`, `README.md` and the two focused logs.

**Unchanged by this correction:** the publication-to-pulse identity limitation
stands — a publication binds publisher, class, session and instant, and is
still NOT claimed to prove that the volley caused the attributed damage, since
no per-publication ↔ per-pulse identity is carried. The 8
`test_scenario_runner` setup failures from the missing archetype-363 Kraken
capture remain unresolved candidate regressions, and the minion causal slice,
controlled live A/B/C pairs and presentation review, independent reference
fixtures and final acceptance all remain open.

### Checkpoint 10: minion survivor-resumption evidence (2026-09-12)

**What was wrong.** `SURVIVOR_RESUMPTION` credited a combat participant with a
"survivor resumption" whenever it moved after *its own last recorded damage
event*. Its opponent's fate did not enter the criterion at all: the episode
builder's docstring promised `engagement_end` = "last involvement or
death/absence", but `absent_since` was never assigned and the only remaining
input was the actor's own combat times. The lane census itself serves living
minions only (`server/sandbox_qa.py` `lane_minions`) and the driver only ever
recorded rows for actors it saw, so "the opponent stopped appearing" was
silently readable as an ending and movement after any hit as survival. The
earlier live-window counts (34/35 claimed survivors) were already WITHDRAWN for
the same reason; this stage replaces the criterion instead of re-measuring
those windows.

**The criterion now (production `run_minion_push` + `minion_episodes`).** A
resumption is a claim with three parts, each requiring evidence the record
actually carries:

1. **Participation** - the actor itself fought a tracked opposing minion
   (`combat_participant`; a bystander that marched after someone else's fight
   makes no claim at all, not even an unverified one).
2. **An evidenced end to the engagement** - `engagement_end` is the last
   recorded involvement of the actor **or of any opponent it engaged** (an
   opponent still fighting anybody keeps the engagement open, so movement
   before that instant is pursuit, never resumption). Every opponent must then
   be accounted for *after* that instant by one of exactly two kinds of
   evidence: an explicit **1072 ENTITY_DEATH publication** for it (the only
   wire signal that evidences a minion death), or a census sample in which it
   was **observed alive**. A census row recording `hp <= 0` counts as the
   weaker "death-sample" evidence kind. A missing row is *not* evidence: its
   cause is unknown, so the claim is reported as `end_evidence: "unknown"`.
3. **Alive resumption** - the first census sample after the end must observe
   the actor alive (`present` and `hp > 0`), and at least two such samples are
   needed to measure the push-direction net march
   (`resumed_after_combat >= 1.0` for the stage).

**Capture added on the existing path only.** The census loop now records an
**absence row** `(t, last_x, last_y, last_hp, present=False)` for every tracked
actor missing from that sample (one census = one instant for all its rows), and
the driver collects **1072 publications for tracked actors** into
`minion_window.death_log`. No new query, no parallel engine, no client-side
kill. A later death is reported separately (`death_time` / `death_evidence`)
and never erases an interval that was validly observed alive earlier.

**The record now reports the unknown instead of guessing.** Episodes carry
`opponents`, `end_evidence`, `opponent_accounting`, `unaccounted_opponents`,
`alive_samples_after_end`, `resumed_after_combat` (None unless proven) and
`resumption_unverified` with the precise reason; the stage detail states
`survivors_resumed` / `survivor_claims_unverified` and names the first
unverified reason. When no proven survivor exists the stage is
`NOT_OBSERVED` - never a pass borrowed from an inferred death.

**Measured (`python -B`, scripted lane through the real writer, offline).** The
positive case (exchange, the killed opponent's 1072 at the next sample, the
survivor pushing on, a structure hit) is a full **PASS** record:
`end_evidence: opponent-death-publication`, `resumed_after_combat: 14.0`,
`survivor_claims_unverified: 1` (the dead participant's own claim cannot be
verified and is named as such rather than dropped). The boundary case
(opponent stops appearing with **no** 1072) is `FAIL` /
`SURVIVOR_RESUMPTION NOT_OBSERVED` with `survivors_resumed: 0`,
`survivor_claims_unverified: 2`, `death_log: []`, `end_evidence: "unknown"` and
the reason "... were not observed alive after the engagement end and no death
publication for them is carried: the end of the engagement is unknown (an
absence is not a death)", while the movement itself stays measured and reported
(`march_after: 14.0`). The pre-end-movement case gives `engagement_end` = the
opponent's later hit on a teammate and `resumed_after_combat: 0.0` - the
advance made while the fight was still open is not credited, and
`STRUCTURE_INTERACTION` cannot inherit an unproven resumption.

**Focused tests:** `TestMinionEpisodes` (12) + `TestMinionSurvivorResumptionEvidence`
(3, through the writer) + the preserved `TestMinionPushClient` (3) and
`TestMinionEndpointContinuity` (5) - **23 passed**, plus `TestWireParsers` (6
passed) as the parser smoke check and the untouched cast causal classes
(`TestSkyeACausalEvidence` / `B` / `C`, **23 passed, 105 subtests**) as the
scope-boundary regression - the A/B/C checks are unchanged by this stage. No
broad suite was run. The old synthetic
positives were adjusted where their premise was the withdrawn inference: the
scripted lane now shows a *bounded* engagement (the team-2 minion holds after
the exchange, so both actors are observed alive and out of contact afterwards
- the end evidence the criterion requires) instead of both minions marching
back into each other.

**Boundaries carried, unchanged:** publication->pulse identity is still not
claimed (a 1072 names victim and killer; it does not by itself prove which
pulse landed), minion compare-pair support is still not built, the same-cohort
structure linkage and the minion serialized pair contract remain open, no live
window was re-run (the withdrawn counts stand withdrawn), the 8
`test_scenario_runner` setup failures from the missing archetype-363 Kraken
capture remain unresolved candidate regressions, and independent reference
fixtures and final acceptance remain open. `Tools/scenario_client.py` was
`f994ff773fb43cbb8e3d0453babe26be6c2ebaca25b13b1c9e629c4898921969` and
`server/test/test_scenario_client.py` was
`5767550e24358c7328ba100d49809f09b7b500224ff5410b871579d70b96bbe2`; this leaf
was `3ef75bd01e48e80bcd36179445756197b002132bec1a21ab22ac2591b0089f20` before
this note. Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt10-minion-survivor-20260912/`
- the verified `before/` baseline, scoped diffs, the three serialized writer
records, `writer-cases-summary.json`, focused test logs, `hashes.json` and
`README.md`.

> **Superseded by the correction below (read that instead of the criterion
> above):** the review REJECTED this section's end-evidence kind "a census
> sample in which it was observed alive". An engagement end must be a carried
> event with its own instant; an alive, holding or absent opponent evidences
> nothing, and movement is measured strictly after that instant. The parent's
> two independent witnesses are replayed in the correction section.

### Checkpoint 10 correction: the engagement end is a carried event with its instant (2026-09-12)

**Why this correction exists.** The criterion in the section above was REJECTED
in review because it still inferred the end of an engagement from *silence*. An
opponent observed alive (or merely absent) after the last contact was accepted
as proof that the exchange had ended, which then credited the actor's own
movement as post-engagement resumption. The review's two independently built
witnesses show exactly that:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-parent-resumption-l7vgl6md/witness.json`.
With the actor marching 2 u at t=2..3 while the opponent sits still and alive,
the rejected code reported `engagement_end: 1`,
`end_evidence: "opponent-observed-alive-after-end"` and
`resumed_after_combat: 2.0`. Adding an opponent death published at **t=10** —
after every movement sample in the record — still reported `engagement_end: 1`
and `resumed_after_combat: 2.0`: the event used to "prove" the end happened
seven seconds *after* the movement it certified. `observed_alive` also counted a
`hp=None` sample as alive evidence.

**The corrected criterion (production `minion_episodes` + `run_minion_push`).**

1. **Participation** is unchanged: the actor itself fought a tracked opposing
   minion; a bystander makes no claim at all, not even an unverified one.
2. **The end is a CARRIED EVENT WITH AN INSTANT.** `engagement_end` exists only
   when **every** opponent the actor engaged is evidenced **dead** — by an
   explicit 1072 ENTITY_DEATH publication for it, or by a census sample
   recording `hp <= 0` (the weaker `death-sample` kind; the earlier instant wins
   when both are carried). It is then the LATEST such death instant, never
   earlier than the actor's own last recorded involvement. An opponent observed
   alive, holding position, or simply absent carries **no** end: `engagement_end`
   stays None, `end_evidence` is `"unknown"`, the opponent is listed in
   `unaccounted_opponents`, and the claim is reported as unverified. Silence and
   life are not disengagement.
3. **Movement is measured strictly AFTER the closure instant**, over a
   **contiguous** run of census samples in which the actor is present with a
   **known `hp > 0`** (`observed_alive` no longer accepts `hp=None`). The run
   starts at the first sample after the closure; an absence, an unknown-HP
   sample or the actor's own death ends it, so a gap can never be stitched into
   one surviving interval. Fewer than two contiguous samples measure nothing.
4. A later death of the survivor is still reported separately (`death_time` /
   `death_evidence`) and does not erase an interval that was validly observed
   alive before it.

`opponent_accounting` becomes `opponent_closure` (per-opponent `kind@instant`,
or `no-death-evidence`); `unaccounted_opponents`, `alive_samples_after_end`,
`resumed_after_combat` and `resumption_unverified` keep their roles. **No new
query** was added for this — the carries already existed (the absence rows and
the 1072 collection from the previous stage) — and **no criterion was weakened
to preserve a test count**: the old synthetic positives were changed to carry an
actual end event (a published opponent death, with the survivor's march strictly
after it) instead of an opponent's posture.

**Measured (offline, `python -B`, production writer + production analysis).**
The parent witness replayed against the corrected analysis
(`witness-replay.json`): the `alive_opponent` variant now gives
`engagement_end: None`, `end_evidence: "unknown"`,
`resumed_after_combat: None`, `unaccounted_opponents: [2]` (was end=1 /
resumed=2.0); the `later_death` variant gives `engagement_end: 10.0` (the death),
`alive_samples_after_end: 0` and `resumed_after_combat: None`, so the t=2..3
movement is no longer certified by a later event. Three writer cases through the
real driver (`writer-cases-summary.json`, each record serialized): the positive
kill case is a full **PASS** with `end_evidence: opponent-death-publication`,
closure at the death instant, `resumed_after_combat: 12.0` over 7 post-closure
alive samples, and `TRIAL_CONTINUITY: PASS`; the vanished-opponent case is
`FAIL` / `SURVIVOR_RESUMPTION NOT_OBSERVED` with `end_evidence: "unknown"`,
`survivors_resumed: 0`, `survivor_claims_unverified: 2` and a reason that names
the absent opponent and states that an absence is not a death, while the
movement stays reported as `approach`; the movement-before-the-end case closes
at the opponent's death and reports `resumed_after_combat: 0.0` — the advance
made while the fight was still open is pursuit, and the actor's teammate in the
same engagement is measured the same way rather than grandfathered.

**Focused tests:** the five acceptance cases (opponent alive with no end event →
unknown; an opponent death after all the movement cannot validate that movement;
a published death followed by an alive march; an unknown-HP sample and an
absence gap each failing to fabricate survival; a valid resume retained across
the survivor's own later death) plus bystander exclusion, the death-sample kind
and the structure-hit scope case — `TestMinionEpisodes` (15) +
`TestMinionSurvivorResumptionEvidence` (3, through the writer) +
`TestMinionPushClient` (3) + `TestMinionEndpointContinuity` (5) +
`TestSlotAttribution` + `TestWireParsers` — **33 passed, 4 subtests**. The cast
A/B/C classes were **not** re-run: this correction changes no cast-path code
(only `minion_episodes`, the `run_minion_push` docstring and the minion test
helpers), and no broad suite was run.

**Boundaries carried, unchanged:** publication→pulse identity is still not
claimed (a 1072 names victim and killer; it does not by itself prove which pulse
landed), minion compare-pair support is still not built, the same-cohort
structure linkage and the minion serialized pair contract remain open, no live
window was re-run (the withdrawn counts stand withdrawn), the 8
`test_scenario_runner` setup failures from the missing archetype-363 Kraken
capture remain unresolved candidate regressions, and independent reference
fixtures and final acceptance remain open. This leaf was
`e01bdba4be51ac5f14d7fc8f2306926ea1d9f7807c4284b67514923964ecc64f` before this
note; `Tools/scenario_client.py` was
`9d6fa8eeead43a5420adea3d5ac6b00f570c0bfd71da35d45b2dc39617b3d909` and
`server/test/test_scenario_client.py` was
`925b659d062ea78a4ab7af029a02dd49dc43154686602a8db82c63da6bb9849b` (the
checkpoint-10 after-state, reconstructed and hash-verified in this round's
`before/`). Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt10corr-8ae53291-20260912/`
- the hash-verified `before/` baseline and its `reconstruct_baseline.py`, the
scoped diffs, `witness-replay.py` + `witness-replay.json`, the three serialized
writer records, `writer-cases-summary.json`, the focused test log,
`hashes.json` and `README.md`.

### Checkpoint 11: STRUCTURE_INTERACTION is bound to the same participant (2026-09-12)

**What was missing.** The stage counted *any* structure damage as the push's
conclusion: a different minion's hit, a hit on the actor's own team's structure,
a hit that landed while the fight was still open and a hit carried after the
actor was already dead were all accepted, and the accepted resumption sequence
was measured on one participant while the hit that certified it belonged to
another. The stage is now bound to the SAME participant whose resumption was
accepted — one actor's combat, closure, resumption and structure damage make one
claim; a second minion's hit cannot complete a first minion's sequence.

**The qualifying sequence (production `minion_episodes` + `run_minion_push`).**
A hit qualifies for an actor only when **all** of these hold:

1. The actor itself is an opposing-combat participant whose engagement has a
   **carried end instant** (`engagement_end`, per the correction above). A
   bystander that hit a structure makes no claim of its own.
2. The hit is **strictly later than that closure instant** — a hit that lands
   while the exchange is still open cannot be its consequence.
3. The hit is **strictly before the actor's own death**, when a death is
   carried: a post-death hit cannot qualify.
4. The structure's **recorded team is the opposing one** (team 1 ↔ team 2). A
   friendly structure is not the opposing push the stage measures, and a
   structure whose team the record does not carry is reported as unverified —
   never assumed to be opposing.
5. The **resumption was already measured before the hit**: the contiguous
   observed-alive run between the closure and the hit contains at least two
   samples whose push-direction net march is ≥ 1.0 u. (The sentence "later than
   that measured resumption interval" cannot mean "after the interval's last
   sample" — the accepted interval normally runs to the end of the observation
   window, which would make the claim unsatisfiable for a hit inside it. It is
   the *resumption already being measured* that the hit must follow, and that is
   what these samples establish; the hit still has to be later than each of
   them, in the serialized evidence.)

The first proven hit is retained as `structure_sequence` (time, structure,
structure_team, delta, `samples_before_hit`, `march_before_hit`). **Raw
observations are preserved, not filtered**: every hit is kept per actor in
`structure_hits` (time, structure, delta, structure_team) and in the window's
`structure_log` with `attacker_team`; hits that do not qualify are reported with
their reasons in `structure_unverified` (`hits`, `unproven`, `reasons`) and
counted in the window's `structure_claims_unverified`. A later death does not
erase an already measured sequence — the hit is evidence from the moment it was
measured.

**Capture added (no simulation change).** The structure's team comes from the
existing snapshot path: `run_minion_push` already reads the QA `snapshot`
structures once, and `SandboxQA`'s structure rows already carry
`"team": combat.team(actor)` — the window just had to keep it. The observed
window now also serializes `structure_teams` (eid → team) and
`resumed_cohort_structure_hits`. No server, query or simulation code was
touched, and no new executable path was invented.

**Measured (offline, `python -B`, production writer + production analysis).**
Seven cases through the real driver (`writer-cases-summary.json`, each record
serialized into this round's evidence dir, every case carrying its own
expectation — the run is a witness, not a transcript; 7/7 MATCH):

- **`positive-same-participant-sequence`** — full **PASS**:
  `structure_sequence` = {structure 3539, `structure_team` 2,
  `samples_before_hit` 3, `march_before_hit` 4.0, delta −40.0},
  `resumed_after_combat` 4.0, `resumed_cohort_structure_hits` 1,
  `structure_claims_unverified` 0, `structure_teams` `{"3539": 2, "3540": 1}`,
  `TRIAL_CONTINUITY` PASS. The hit is later than the ≥ 2 alive samples that
  measured the resumption in the record itself.
- **`bystander-structure-hit`** — `SURVIVOR_RESUMPTION` PASS, stage
  `NOT_OBSERVED`, `resumed_cohort_structure_hits` 0, one unverified claim whose
  reason is "the actor is not an opposing-combat participant, so it has no
  proven engagement end and no measured resumption of its own to bind this hit
  to"; the bystander's own `structure_hit` stays `True` (raw, preserved).
- **`friendly-structure-target`** — same participant, same moment, own team's
  structure: `NOT_OBSERVED` with "structure 3540 is on the actor's own team 1".
- **`structure-hit-before-the-sequence`** — the hit precedes the closure:
  `NOT_OBSERVED` with "the hit at t=… is not later than the engagement-end
  instant t=…" and "only 0 contiguous observed-alive census sample(s) lie
  between the engagement end and the hit".
- **`post-death-structure-hit`** — `NOT_OBSERVED` with "the hit at t=… is at or
  after the actor's own death t=…: a post-death hit cannot qualify"; the
  resumption measured before the death is still PASS.
- **`later-death-keeps-the-valid-hit`** — the valid hit at sample 5 then the
  participant's own death at 7: still a full **PASS** with the sequence intact.
- **`unverified-vanished-opponent`** (the preserved checkpoint-10 negative) — no
  end is carried for the opponent, so the resumption is `NOT_OBSERVED` *and* the
  hit is unverified rather than credited.

**Focused tests:** `TestMinionEpisodes` (23 — the checkpoint-10 criteria plus
the same-participant sequence, the bystander, a hit before the closure, a hit
before the resumption is measured, a friendly target, a post-death hit, a later
death that keeps a valid hit, and an uncarried team staying unverified) +
`TestMinionStructureSequence` (5, through the writer: positive, bystander,
friendly, before-the-sequence, post-death) +
`TestMinionSurvivorResumptionEvidence` (3, writer) + `TestMinionPushClient` (4)
+ `TestMinionEndpointContinuity` (4) + `TestSlotAttribution` (1) +
`TestWireParsers` (6) — **46 passed, 4 subtests**. The accepted resumption and
endpoint checks were preserved in every one of them: no existing positive was
weakened, and the scripted lane's defaults were moved only so the positives
carry a hit that occurs *after* the resumption is measurable (a hit at sample 4
with the kill at sample 2 and the march on 3..4 no longer describes the claim it
is meant to describe). The cast A/B/C classes were **not** re-run: this
checkpoint changes no cast-path code (only `minion_episodes`, the
`run_minion_push` docstring, the minion test helpers and the two minion-facing
writers), and no broad suite was run.

**Boundaries carried, unchanged:** the minion compare-pair schema is still not
built, publication→pulse identity is still not claimed, no live window was
re-run (the withdrawn counts stand withdrawn), the 8 `test_scenario_runner`
setup failures from the missing archetype-363 Kraken capture remain unresolved
candidate regressions, controlled live runs and the publication-to-pulse gap
remain open, and independent reference fixtures and final acceptance remain
open. This leaf was
`2c5f214287ebba570206a095e46d035b2fbf49710092513a08ec039e4a1b5e12`; production
`Tools/scenario_client.py` was
`e274ee272bb8e2020a8a25044567f20d84ddc6a9dbb32dafded376b4fc029f43` and
`server/test/test_scenario_client.py` was
`2988a3a4a6890538f26ba49a5ead6616c66411617ff8e71c72a44f98d02fb880` (the
checkpoint-10-correction after-state, reconstructed from the correction's own
diffs and hash-verified in this round's `before/`). Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt11-structure-binding-c3fec164-20260912/`
— the hash-verified `before/` baseline with `reconstruct_baseline.py`, the
scoped diffs with `diff-replay.py` + `diff-replay.json` (each recorded diff
really does rebuild the live file from that baseline), the seven serialized
writer records, `writer-cases-summary.json`, `evidence-run.py` +
`evidence-run.stdout.txt`, the focused test log, `hashes.json` and `README.md`.

#### Correction: an explicitly opposing team, and no gap before the hit (2026-09-12)

**Why this correction exists.** The checkpoint-11 stage above was REJECTED in
review (`changes_required`) with its own witness:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-parent-structure-8zb_os8u/witness.json`.
Two holes were independently reproduced on it. First, the structure's team was
only checked for "different from the actor's team", so the witness's invalid
**team 3** produced a full `structure_sequence` with `march_before_hit: 2`; an
unknown, invalid, boolean or non-integer team was read as an opposing side.
Second, the pre-hit alive run was used as a PREFIX: with the actor observed
alive at t=2 and t=3, an explicit **missing** census sample at t=4 and the hit
at t=5, the code kept `structure_sequence` even though the interval it measured
never reached the hit — `alive_run_before` stopped at the gap, and the earlier
prefix certified the later hit.

**What changed** (production `minion_episodes` + the `run_minion_push`
docstring; no simulation, no query, no schema):

1. **A real opposing team is required.** The structure's served team must be
   the integer `1` or `2` and the other side from the actor. A missing team, an
   unknown or out-of-range value, a boolean and any non-integer are all
   reported as unverified — a bare inequality to the actor's team is no longer
   a team identity.
2. **The measured resumption must REACH the hit.** Every census sample between
   the engagement-end instant and the hit must observe the actor alive
   (`present` with a known `hp > 0`). A gap — an absence, an unknown hp or a
   dead sample — inside that span is carried as its own reason
   (`"the observed-alive interval does not reach the hit: N of M …"`) and the
   hit stays unverified, because nothing in the record re-establishes the
   actor's identity or life inside the gap. The historical resumption claim
   (`resumed_after_combat`, measured from the contiguous alive run right after
   the closure) and the raw hit (`structure_hits`) are preserved exactly as
   before; only the certification of the hit changes.

**Measured (offline, `python -B`, production writer + production analysis).**
The parent's witness replayed against BOTH analyses (`witness-replay.json`):
the rejected code reproduces the parent's recorded numbers for both variants
(`samples_before_hit: 2`, `march_before_hit: 2`, `resumed_after_combat: 2`), so
the replay is demonstrably the same experiment; the corrected analysis returns
`structure_sequence: None` for team 2 (reason: the interval does not reach the
hit), for team 3 (reason: not one of the two teams of the match), for a
boolean `False` team (which the rejected code had credited) and for the
same lane with an unknown hp instead of an absence — while an uninterrupted
control lane is still proven with the identical verdict. Nine writer cases
through the real driver (`writer-cases-summary.json`, every case carrying its
own expectation, 9/9 MATCH, `TRIAL_CONTINUITY: PASS` throughout): the two
checkpoint-11 positives are unchanged (`samples_before_hit: 3`,
`march_before_hit: 4.0`) and still full PASS, and the two new negatives are
`NOT_OBSERVED` — `gap-before-the-hit` with `resumed_after_combat: 4.0`
preserved, a recorded `absent_since` and `"2 of 5 census sample(s) …"`, and
`invalid-structure-team` with `structure_teams: {"3539": 3}` and its
reason. Each added test was also run against the baseline copy of the analysis
(`rejected-tests.json`): the five pure correction cases and the two writer
negatives all FAIL on the rejected code and PASS on the corrected one, and the
preservation case passes on both — the isolation the review asked for, rather
than a claim about it.

**Focused tests:** `TestMinionEpisodes` (29 — the checkpoint-10/11 criteria
plus the six correction cases) + `TestMinionStructureSequence` (7, through the
writer) + `TestMinionSurvivorResumptionEvidence` (3) + `TestMinionPushClient`
(4) + `TestMinionEndpointContinuity` (4) — **47 passed, 4 subtests**. No
accepted resumption, participant/order or endpoint check was weakened, and the
cast A/B/C classes were not re-run (no cast-path code changed).

**Boundaries carried, unchanged:** the minion compare-pair schema is still not
built, publication→pulse identity is still not claimed, no live window was
re-run, the 8 `test_scenario_runner` setup failures from the missing
archetype-363 Kraken capture remain unresolved candidate regressions, and
controlled live runs, the publication-to-pulse gap, independent reference
fixtures and final acceptance remain open. This leaf was
`22883738780164c350ca35598116e352dc32cc6924e4c187957ea9da5dfe52b6`; production
`Tools/scenario_client.py` was
`9299c27074a32c1a68f2406be087586b101bdde312bbc292b49500dc55386489` and
`server/test/test_scenario_client.py` was
`d7e48b9e241176d499b59dadce307f6fcc38eaeb0e295208e183b8c6bf395dba` (the
checkpoint-11 after-state, reconstructed from that checkpoint's own diffs and
hash-verified in this round's `before/`). Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt11corr-bb119efe-20260912/`
— the hash-verified `before/` baseline with `reconstruct_baseline.py`, the
scoped diffs with `diff-replay.py` + `diff-replay.json`, `witness-replay.py` +
`witness-replay.json` (the parent's witness against both analyses),
`rejected-tests.py` + `rejected-tests.json`, the nine serialized writer
records, `writer-cases-summary.json`, `evidence-run.py` + its stdout, the
focused test log, `hashes.json` and `README.md`.

#### Checkpoint 12: the serialized minion record contract, one record at a time (2026-09-12)

**What this stage claims.** A minion observation trial currently exists only as
a serialized client record: the writer produces it, and nothing independently
re-reads it. This stage adds that reader — `validate_minion_record` in
`Tools/scenario_client.py` — and the minimal contract it enforces, judged ONE
record at a time. It is deliberately NOT the pair comparator: a validator PASS
says "this one record is coherent and complete", never "two records agree", and
`controlled_pair` is not enabled for minions.

**What the record now carries (writer, `ClientDriver.run_minion_push`).** The
raw evidence the contract is computed from, all of it unrounded:

1. **The observed frame**: `window_start`, `window_end`, the `connection`, the
   `match_id` the snapshot served, the prepared `profile_digest`, and
   `census_instants` — every census FRAME the window actually took, opening
   census included, in order.
2. **Raw census timelines**: each tracked actor's `points` are the raw
   `[t, x, y, hp, present]` tuples now (previously rounded), because the saved
   episode has to be recomputable from the same numbers it was computed from.
3. **Payload-backed evidence**: every combat, structure and death entry carries
   its own `connection`, `opcode` and raw `payload`, and the slot attribution
   log (`move_log`) carries `slot`, `owner`, `connection` and the 1016 payload.
4. **Provenance on both outcomes**: `provenance_frame()` (source digests,
   loaded tape, environment receipt, client build, qa dir and the two typed
   endpoint receipts) is now emitted by PASS **and** by both failure paths, so a
   FAIL record can evidence what it ran against instead of being unevidenced.

**What the validator checks.** Structure and types FIRST (a malformed record
gives structured reasons, never an exception, and unknown fields are never
defaults), then: (2) provenance — both source digests valid and equal, the
loaded tape identity, the client build, the environment receipt under the
shared trace-switch rule, the prepared profile digest, and initial/end
diagnostics continuity through the SAME typed linkage checks the cast records
use; (3) the observed frame — the declared `observational_window_s` against the
measured span, no cast slot or declared fixture, the two serialized window
copies agreeing; (4) identities and timelines — one team per tracked actor from
`{1, 2}`, five-field finite samples, ordered timestamps, and every timeline
being a TAIL of the carried census frames (a census stamps every tracked actor,
so a timeline that skips a frame cannot be one actor watched frame by frame);
(5) payload-backed evidence — the carried victim/attacker/delta and
victim/killer are re-derived from each entry's own bytes and must match, teams
must agree with the census and with the served structure teams, and every
entry must belong to the observed connection and window; (6) recomputation.

**Recomputation is the point.** Episodes, every summary count, the census frame
count, the four observed stage statuses and the per-actor episodes are
RECOMPUTED from the
carried timelines/logs through the production analysis (`minion_episodes`, no
parallel toy engine) and compared with what the record saved. A saved count,
stage status or episode is an assertion to be checked, never evidence: a forged
stage, a forged summary count or an edited episode is reported as contradicting
the record's own evidence.

**Two verdicts, deliberately.** `valid` means internally coherent and
recomputable; `accepted` means valid AND a complete PASSING claim.
`incomplete` names the honest gaps that block acceptance without making the
record incoherent — the trial's own FAIL verdict, a missing endpoint receipt or
TRIAL_CONTINUITY stage (a window that ended early), a partly-lost session. An
honest partial trial is not called malformed; a record is INVALID only when it
cannot be true on its own terms. A PASS claim missing its continuity receipts,
or one whose stage statuses its own evidence does not recompute, is invalid.

**Measured (offline, `python -B`).** The evidence run
(`record-validator-run.py` + `record-validator-summary.json`) carries 45 cases,
0 mismatches, each with its own expectation: the unmodified writer record of the
accepted lane (`valid` and `accepted`, every check true, and every saved
stage/episode/count reproduced by the recomputation); five honest
negatives through the real writer — no closure (opponent alive), pre-closure
movement, a friendly structure hit, a post-death hit and a pre-resumption hit —
each `valid` with `accepted` false, its stage `NOT_OBSERVED`, and the specific
unverified reason recomputed from the carried evidence ("no carried end
instant", `resumed_after_combat: 0.0`, "own team", "post-death hit cannot
qualify", "not later than the engagement-end instant"); five forged upgrades of
those same honest records (stage flipped to PASS) rejected outright; 25
single-edit tampers of the positive (forged stage/summary/episode, missing or
malformed timeline, a timeline that skips a frame, malformed or non-matching
payload identity, wrong team/actor/connection/structure team, a frame shorter
than declared, forged sample count, missing census frames, changed source,
another match's linkage, missing provenance or endpoint receipt,
`first_failed_stage` naming a PASS stage, wrong schema version) all rejected
with their specific reason; the edit of only ONE of the two serialized window
copies; and 8 records that are not records at all, each answered with structured
reasons and no exception.

**Focused tests:** `TestMinionRecordValidation` (24 tests, 46 subtests) — the
positive, the tamper families, the malformed-record family and the honest
negatives. Re-run together with the existing minion classes and the
capture/provenance tests the failure-path change touches: **78 passed, 50
subtests**. No accepted criterion was weakened: the writer only ADDED carried
evidence and the validator reads it; the analysis (`minion_episodes`) keeps its
behavior, and the cast A/B/C classes were not re-run.

**Explicitly NOT claimed (the remaining pair equivalence contract).** The
two-record comparator for minions does not exist yet: the public compare-pair
CLI still judges records against the CAST contract (skill slot A/B/C, cast
stages, fixture manifest), so a minion record is not one half of a pair there,
`controlled_pair` is not enabled for minion records, and no second CLI command
was invented. When that contract is built it must compare, across two
independently produced minion records: identical provenance identity
(startup/current source digests, loaded tape, config, client build, profile
digest), fresh-session identity (match id, pid, startup, ticks) that is
expected to DIFFER, and agreement of the recomputed quantities — the per-actor
episodes, the summary counts, the stage statuses and the structure-sequence
verdicts — with tolerances only where the record itself fixes them.

**Boundaries carried, unchanged:** no live ADB/QA run, no simulation edit, no
corpus recovery, no commit; publication→pulse identity is still not claimed;
independent reference fixtures remain an interface only (`UNAVAILABLE`); the 8
`test_scenario_runner` setup failures from the missing archetype-363 Kraken
capture remain unresolved candidate regressions; and live/reference/final
acceptance remains open. This leaf was
`3a063b25f0d7718e88ea39cf1fa6b24e707ef55788b8a00cbc4bfbff8b154aac`; production
`Tools/scenario_client.py` was
`45aef1f3a76f96690ebc628f33e4d6d34975897359488b0682cb6fd54f7542a9` and
`server/test/test_scenario_client.py` was
`716df54a4ec6d85db64956603563c1289400da5b4055aa8d3d90a77c44b53f44` (the
checkpoint-11-correction after-state, reconstructed from that correction's own
diffs and hash-verified in this round's `before/`). Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt12-serialized-minion-record-ab911330-20260912/`
— the hash-verified `before/` baseline with `reconstruct_baseline.py`, the
scoped diffs with `diff-replay.py` + `diff-replay.json`, the 45-case
`record-validator-run.py` + its stdout with the serialized record and verdict
JSON of every case, `record-validator-summary.json`, the focused test log,
`hashes.json` and `README.md`.

#### Checkpoint 12 correction: strict payload grammar and typed identities (2026-09-12)

Parent review of the checkpoint above returned **changes_required** with two
demonstrated holes, both preserved as byte witnesses in
`halcyon-parent-minion-validator-8hhoezdo/`:

* `short-both-copies.json` — a 1054 combat entry edited to `payload: "00"` in
  BOTH serialized window copies was reported `{"valid": true, "accepted": true,
  "reasons": []}`: every decode/identity check was gated on `len(payload) >= 12`,
  so a payload too short to carry the fields the entry claimed was skipped
  instead of rejected.
* `unhashable.json` — a combat entry whose `victim` was a list made the
  VALIDATOR raise `TypeError: cannot use 'list' as a dict key` at the
  `victim in tracked_teams` membership test instead of returning a verdict.

The same visit found the combat identity/team block duplicated verbatim, so a
combat entry ran the identity re-derivation and the carried-team cross-check
twice.

**Fix (validator only; no capture, analysis or CLI change).**
`EVIDENCE_GRAMMAR` now states, per opcode, the publication and the minimum
decoded payload BYTES its grammar reads — 1054 combat-delta 12, 1072
ENTITY_DEATH 8, 1016 move-order 1 — exactly the minimums the writer decodes
before it logs an entry, so no legitimately carried evidence can be refused.
`check_evidence_payload()` requires the entry to publish the opcode it claims
and to decode to at least that minimum: a shorter payload is a structured
failure ("its identities cannot be re-derived from it, so the entry is not
evidence of what it claims"), never a skipped check, and the identity
re-derivation then always runs. `entity_identity()` type-checks every carried
identity (combat victim/attacker, structure/attacker, death victim/killer, move
slot/owner) as an integer — rejecting bool, float, str and containers with a
structured reason — BEFORE it is used as a dict key or an operand, so a
container identity is reported instead of raising. The duplicated combat block
was merged into one typed block, and slot evidence now re-derives the carried
`slot` from the 1016 payload's first byte. The writer names the kind of a slot
attribution by the `move_log` key and carries no opcode there, so the 1016
opcode is enforced on any entry that does carry one rather than invented by the
validator.

**Witness replay on the review's own bytes** (`parent-witness-replay.py`,
`witness-verdicts.json`): on the checkpoint-12 baseline the one-byte payload
record was `accepted: true` with zero reasons and the container record RAISED;
on the corrected validator the same bytes give `valid: false, accepted: false`
with "combat_log[0].payload decodes to 1 byte(s), below the 12 byte(s) the 1054
combat-delta grammar reads…" and "combat_log[0].victim [] (list) is not an
integer entity identity" respectively — no exception, no accepted hole, and the
review's third witness (`short.json`, one edited copy) is still rejected.

**Focused tests:** `TestMinionRecordValidation` (27 tests, 74 subtests) adds
three families — one-byte/truncated/empty combat, structure and death payloads
rejected with BOTH serialized copies coherently edited (each case asserts the
two copies agree and that no copy-disagreement reason contributed to the
verdict); the 1016 slot grammar (a coherent attribution accepted, a longer
payload accepted because the grammar reads a prefix, mismatched / empty / odd /
payload-less and wrong-opcode slot entries rejected); and container/untyped
identities answered with structured reasons and no exception — list, dict, str,
float and bool on the combat, structure and death identities, plus list and
dict on the slot/owner identities of an injected 1016 attribution. The
unmodified writer
positive is still `accepted`, and the retained honest incomplete records are
still `valid` but not `accepted` — acceptance semantics are unchanged.

**Explicitly NOT claimed:** the pair equivalence contract above remains a
contract only — nothing about minion pairs, `controlled_pair` or a second CLI
command changed in this correction. Live/reference/final acceptance remains
open, as do the prior boundaries (no live ADB/QA, no simulation edit, no corpus
recovery, no commit). Production `Tools/scenario_client.py` is
`eea48123ecf07f6aabad5e8897587a1ff4596be8e8da1918fb93f27f75ebd768`,
`server/test/test_scenario_client.py` is
`853588941edcf678f714a7303a412c1cc60fad739d4e8d3b70004591359caaa9`, and this
leaf was
`63732e4f9e6d13b73f82ad91da3452746a92dbe1be77ffdb85192c337a9b4e28`. The
checkpoint-12 baseline this correction started from is
`6592001bab26cd123bcc25ec30a158b14948e166cd04b854dc36bfe67db066c5` /
`fec842c1c6c0108b6f1a0dfa5a164b9ec68c4c9874876ffebeb83200e1c47ee7` /
`63732e4f9e6d13b73f82ad91da3452746a92dbe1be77ffdb85192c337a9b4e28`, reconstructed
from that checkpoint's own diffs and hash-verified in this round's `before/`.
Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt12corr-strict-payload-b70b3007-20260912/`
— the hash-verified `before/` baseline with `reconstruct_baseline.py`, the
scoped diffs with `diff-replay.py` + `diff-replay.json`, the parent-witness
replay with its verdict JSON, the focused test log, `hashes.json` and
`README.md`.

#### Checkpoint 13: minion pairs through the existing compare-pair CLI (2026-09-12)

**What this stage claims.** Two minion observation records can now be judged as
a controlled pair — through the SAME public entry point as before. The dispatch
lives INSIDE `compare_pair`: it is now the dispatcher (`MINION_SCENARIO` in
either declared scenario → `compare_minion_pair`, anything else → the cast
contract), the cast contract was moved to `compare_cast_pair`, and no second
CLI command, no new mode and no new executable path were added.
`--mode compare-pair` still reports one meaning of `controlled_pair`, with
`dispatched_contract` naming which contract answered. The cast contract's
EXECUTABLE BODY is byte-identical to the baseline's `compare_pair` (296 lines,
sha256 `6617d3f9a74308787624ce7ad8ffbe057197f92818f0b99343f099039f90381b`,
proved in `cast-body-equality.json`); its docstring was edited to say what it is
and that the dispatcher routes to it.

**The bounded equivalence contract between two accepted minion records.**
EQUAL: the semantic provenance identity (source startup/current digests under
their own coherence rule, loaded tape identity, environment receipt under the
shared trace-switch rule, client build and qa dir, prepared profile digest); the
declared observation duration; the carried actor mapping and each mapped actor's
team; the census shape (frames, loop samples, presence); every carried census
OBSERVATION (x, y, hp, alive); the recomputed summary counts, stage statuses and
per-actor episode projections; the exact combat and structure damage totals per
actor at 4 decimals with no tolerance; the carried order of every log and the
merged event chronology; and the ordered raw slot frames. NORMALISED (expected
to differ, never compared): fresh-session identity — match id, connection, the
process/startup receipts, `window_start`/`window_end` and every instant, the
trace path and wall times. REFUSED: a member that is not ACCEPTED on its own
evidence; a mixed scenario (in either order); a provenance, config or declared
duration difference; a divergent recomputed outcome (counts, exact totals,
cohort, structure sequence); a divergent chronology; and two records whose
carried actor sets do not correspond — that last one returns an explicit
`boundary` naming both sets and the evidence gap ("no carried actor mapping"),
instead of sorting actors into an invented equivalence.

**Explicitly NOT claimed.** (a) Instant equality, absolute or relative: the
minion window clock is wall clock, so instants are compared as presence and
ORDER only, and `measured_time` reports each record's values with the offset
from that record's own `window_start` (`required_equal: false`). A member whose
whole clock was moved by +3600 s carries the same claim and IS accepted as a
controlled pair; two productions carrying the same events in the opposite order
are refused. (b) Slot→owner ownership: a 1016 move frame carries a slot and the
owner the record attributed to it, but no 1010 assignment or 1035/1073 release
publication is carried, so the binding cannot be shown from these two records;
only the ordered raw frames are compared and `slot_ownership.status` is
`UNVERIFIED`. (c) Presentation/video and publication→pulse identity.

**One contract claim corrected inside this stage.** The first implementation
compared the carried census POINTS exactly, and a census point carries the
wall-clock instant it was stamped with — which two independent productions can
never satisfy (measured on the positive: "the carried census points of actor
4610 differ (9 vs 9 samples)"). The comparison now covers every carried
observation and reports the instants; the corrected positive shows identical
observations, identical ordering and different instants.

**Measured through the PUBLIC CLI** (`Tools/run_scenarios.py --mode
compare-pair`, 18 cases, `cases.json` plus every stdout/stderr verbatim under
`cli/`, exact writer bytes under `records/`):

* the positive — two INDEPENDENT writer productions of the accepted lane
  (trials 1 and 2), unedited: `controlled_pair: true`, exit 0, with the
  normalised identities demonstrably different (pid, `startup_at`, qa dir,
  `window_start` and every census instant differ; the match id is equal and
  still normalised, never compared);
* `shifted-clock` (+3600 s, exact at every rendered precision): controlled
  pair, exit 0 — the clock is not part of the claim;
* the three checkpoint-9 cast writer pairs (A/B/C, unmodified records from that
  round): still `cast trial pair` with `controlled_pair: true`, exit 0, so the
  new dispatch preserved the cast route;
* 13 refusals, exit 1, no case printing a traceback: other loaded tape, other
  environment, other source, other declared window; an honest incomplete member
  (valid, not accepted — the resolution names member B and its own reason); a
  mixed scenario in both orders; a divergent event count; a divergent exact
  damage total with EQUAL counts; a divergent cohort and structure sequence
  (team-2 survivor, structure 3540); a divergent chronology, plus a member
  whose carried order contradicts its own instants; and two records carrying no
  actor mapping at all.

**Focused tests.** `TestMinionPairComparison` (8 tests, 8 subtests) covers the
positive, the mixed-scenario dispatch in both orders and against
`compare_pair` directly, the four provenance/config/duration negatives, the
three divergent-outcome negatives, the two chronology negatives, the
clock-shift boundary positive and the no-mapping refusal, each driven through
the public CLI on serialized records. One pre-existing boundary test was
UPDATED, not weakened: it asserted that the public CLI refused a minion record
because the cast contract was the only contract; the boundary it protects (a
minion record is not a cast trial — cast stages, skill slot, fixture manifest)
is now asserted directly against `compare_cast_pair` with the same two failure
reasons, and the CLI is asserted to DISPATCH the pair to the minion contract.
Regressions re-run: **67 passed, 8 subtests** across `TestProofMatrix` +
`TestPairCliRoundTrip` + `TestDiagnosticsLinkagePair` + `TestSchemaInvariant`
(the cast contract, including the A/B/C writer positives and their negatives),
and **70 passed, 78 subtests** across the five minion classes
(`TestMinionRecordValidation`, `TestMinionEpisodes`,
`TestMinionSurvivorResumptionEvidence`, `TestMinionStructureSequence`,
`TestMinionEndpointContinuity`).

**Boundaries carried, unchanged:** no live ADB/QA run, no writer or simulation
change, no new executable path, no agents, no commit and no corpus recovery.
Controlled live runs, the publication→pulse gap, missing-capture checks,
independent reference fixtures (still an interface only, `UNAVAILABLE`) and
final acceptance all remain open, as do the 8 `test_scenario_runner` setup
failures from the missing archetype-363 Kraken capture. This leaf BEFORE this
section (i.e. the checkpoint-12-correction after-state, reconstructed from that
round's own diffs and hash-verified in this round's `baseline/`) was
`714f3a02ccbd6c61109fde38a4b1993f8bc56705236f4422ad2ecc077237f688`, on
`Tools/scenario_client.py`
`eea48123ecf07f6aabad5e8897587a1ff4596be8e8da1918fb93f27f75ebd768` and
`server/test/test_scenario_client.py`
`853588941edcf678f714a7303a412c1cc60fad739d4e8d3b70004591359caaa9`; the
after-state hashes are in this round's `hashes.json` and `diff-replay.json`.
Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt13-minion-pair-4d15c335-20260912/`
— the hash-verified `baseline/` with `reconstruct_baseline.py`, the scoped
baseline→worktree diffs with `replay_diffs.py` + `diff-replay.json`, the
18-case `produce_cases.py` with `cases.json`, the exact writer records, every
CLI stdout/stderr verbatim, the focused test logs, `hashes.json` and
`README.md`.

#### Checkpoint 13 correction: the elapsed-time contract (2026-09-12)

**What was wrong.** The checkpoint-13 contract above dropped timing
altogether: `measured_time.required_equal: false` and the census points were
compared with their instants trimmed, so two members that observed the same
events at substantially different times were accepted as a controlled pair.
The parent review's preserved witness
(`halcyon-parent-pair-time-umosqx_t/{a.json,b.json,verdict.json}`) proves it:
member B's census frame 3 sits **+0.7981517 s** (3.8032093 s vs 3.0050576 s
from each record's own origin) with the actor points stamped at that instant
moved with it, positions and outcome unchanged — and that round's verdict
recorded `controlled_pair: true`, `failures: []`, with no `elapsed_time`
section at all. The clause "(a) Instant equality ... presence and ORDER only"
in the section above is **corrected by this section**: elapsed timing is now
compared, and only the absolute origin is normalised away.

**The carried evidence the contract needed.** The census reply now reports the
world clock it was served at, exactly as `snapshot` does
(`SandboxQA.lane_minions` → `tick`/`time`), the writer records
`minion_window.census_sim_ticks` / `census_sim_times` parallel to the frames,
and `validate_minion_record` checks that clock's coherence when it is carried
(parallel to the frames, non-decreasing, on the record's own rate from its own
diagnostics receipts, not past the trial endpoint). A record written before
this change carries no clock: that is an explicit **not-carried** gap
(`checks["census_sim_clock"] is None`, `recomputed.sim_clock.carried false`),
never invalidity and never incompleteness — such a record stays ACCEPTED on
its own evidence.

**The elapsed-time contract, `gates.elapsed_time`.** (a) VERIFIED / FAILED:
the carried simulation clock per census frame index, normalised to each
record's own first frame, must agree within `SAMPLING_BOUND_S`; so must every
census frame's and every carried event's real-time offset from each record's
own origin (per index); and each record's own cadence must sit inside its own
declared schedule (no gap between consecutive frames beyond the declared
duration / declared loop-sample count plus the bound — the deviation from that
uniform model is reported as well, as sampler characterisation, not as a
gate). (b) UNVERIFIED when a member carries no census clock: the elapsed
gameplay time cannot be established from such a record, so the gate names
`minion_window.census_sim_ticks / census_sim_times` as `missing_evidence`
while every other gate still runs and can pass. `controlled_pair` is false in
both non-VERIFIED cases; timing is never dropped to make a pair pass.

**Why the bound is not arbitrary.** `SAMPLING_BOUND_S = 0.100 s` is measured:
across this round's clock-carrying productions the worst deviation from each
record's own declared cadence is **0.0086 s** (see `measured_deviations` in
`cases.json`), an order of magnitude inside the bound, while the parent's
witness shift is ~8× the bound and cannot pass. The bound bounds the SAMPLER;
the simulation clock is compared with the same bound because the sampler reads
both clocks at the same instant, and no tighter sim-clock bound is evidenced
yet (no live client production carries the census clock). The absolute clock
origin is still NOT required to be equal.

> **Corrected by "Checkpoint 13 correction 2" below.** Two claims in the
> paragraph above do not survive the evidence: the 0.100 s is a **fixture**
> calibration and not a measured production bound (the offline real path
> already deviates by 0.4515 s at the same cadence), and it is **not** applied
> to the simulation clock — the carried simulation clock is compared exactly,
> per frame index. `SAMPLING_BOUND_S` is renamed
> `FIXTURE_SAMPLING_MARGIN_S` there, and the sim-clock wording in contract
> clause (a) above is likewise superseded.

**Measured through the PUBLIC CLI** (12 cases, `cases.json` + verbatim
stdout/stderr; 6 controlled, 6 refused, no traceback):

* the parent's EXACT witness bytes → **refused**, exit 1:
  `census frame 3 real-time offset differs by 0.798s (3.005s vs 3.803s),
  beyond the 0.100s sampling bound` plus record B's own cadence violation
  (`1.802s` gap against its `1.000s+0.100s` schedule) and the named
  UNVERIFIED gap for the clock those bytes do not carry;
* the positive — two INDEPENDENT writer productions, both carrying the clock
  (`census_sim_ticks` `[124, 148, … 288]`), each accepted on its own:
  `controlled_pair: true`, `elapsed_time: VERIFIED`, exit 0;
* uniform clock shifts stay controlled: the whole wall clock +3600 s
  (exact at every rendered precision) and an independent production by a
  world that had been running an hour longer (`census_sim_times[0]` differs
  by 3600.0 s, same elapsed series);
* the parent's shift applied to a CLOCK-CARRYING record: `FAILED`
  (`0.796s` offset, exit 1) — the nonuniform warp is caught by the offset
  comparison itself, not only by the missing clock;
* the wall clock untouched and the SIMULATION clock moved 0.5 s at frame 1:
  `FAILED` (`elapsed SIMULATION time at census frame 1 differs by 0.500000s …
  did not observe the same elapsed GAMEPLAY time`);
* an event published 0.9 s later inside the same window, census cadence and
  clock untouched: `FAILED` naming the three events and their offsets;
* the same two records with the clock keys removed: the pair is UNVERIFIED
  naming the field, each member is still ACCEPTED, and every outcome gate
  (`outcome_counts`, `stages`, `damage_totals`, `episodes`, `chronology`)
  still passes — single-record status and pair equivalence stay distinct;
  one member without the clock is UNVERIFIED too, naming that member;
* the PRODUCTION mailbox (`RealQaStack` + `Tools.sandbox_qa.submit`, the same
  `HALCYON_QA_DIR` path the live stack uses): the real `lane_minions` reply
  carries `tick`/`time` beside `count`/`minions`, matching the `snapshot` read
  next to it — the capture field's production shape;
* cast routing preserved: the three checkpoint-9 cast writer pairs through
  the same CLI are still `cast trial pair`, `controlled_pair: true`, exit 0.

**Focused tests.** `TestMinionPairComparison` is now **14 tests / 8 subtests**
(the 8 above plus the no-clock pair, the one-sided clock, the parent-style
nonuniform frame shift, the simulation-clock warp, the event-spacing refusal
and the world-ahead positive), each driven through the public CLI on
serialized records; a new `shift_census_frame` helper builds the nonuniform
witness for both the test and the evidence script. Regressions re-run:
**67 passed, 8 subtests** (cast contract: `TestProofMatrix` +
`TestPairCliRoundTrip` + `TestDiagnosticsLinkagePair` + `TestSchemaInvariant`),
**70 passed, 78 subtests** (the five minion classes incl.
`TestMinionRecordValidation`), and **8 passed** for
`TestRealQaIntegration` (the production QA stack, incl. the real-stack cast
pair through the public CLI) — that class is verified under
`python -m unittest` because one of its own assertions compares the process
environment around the fixture, which pytest cannot satisfy while it sets
`PYTEST_CURRENT_TEST` (pre-existing instrument interaction, not a regression).

**Still not claimed.** The simulation INSTANT of an individual event (only the
census frames carry the sim clock, so event timing rests on the frame clock
and the bound); the absolute clock origin; slot→owner ownership
(`UNVERIFIED`); presentation/video; publication→pulse identity. A live client
production carrying the census clock is still not on record — that is what
would evidence a tighter sim-clock bound — and controlled live runs, the
missing-capture checks, independent reference fixtures and final acceptance
all remain open. Boundaries carried: no live ADB/QA, no simulation/gameplay
change, no new executable path, no agents, no commit, no corpus recovery.

**Baseline and hashes.** The baseline is byte-proven, not assumed:
`Tools/scenario_client.py` `95c1090534e0b75e…`,
`server/test/test_scenario_client.py` `33ba1b084ae23653…` and this leaf
`4cea54f715e90e42…` are checkpoint 13's recorded after-state, rebuilt from
that round's own diffs and verified against its recorded hashes;
`server/sandbox_qa.py` `1d31a922b2eeb9ed…` is the state checkpoints 7–9corr
independently recorded, rebuilt by removing exactly this correction's seven
inserted lines. Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt13corr-elapsed-time-e45192be-20260912/`
— `reconstruct_baseline.py` + `reconstruct-baseline.stdout.txt`, the scoped
baseline→worktree diffs with `replay_diffs.py` + `diff-replay.json` (which
also carry the after-state hashes), the 12-case `produce_correction.py` with
`cases.json` (including the parent witness copy, every CLI stdout/stderr and
the production probe), the contract witnesses under `records/`, `cli/` and
`witness/`, the focused test logs, `hashes.json` and `README.md`.

#### Checkpoint 13 correction 2: typed clock failures and the bound's real scope (2026-09-12)

**What was wrong (two things, both from the parent review).** (1) A malformed
census-clock entry was refused by the type gate and then **subtracted anyway**
by the tick-rate loop below it: the parent's preserved witness
(`halcyon-parent-clock-type-2eluo2ph/{a.json,b.json,error.txt}`, one entry of
`census_sim_times` set to `'bad'` in both copies) made `compare_pair` raise
`TypeError("unsupported operand type(s) for -: 'str' and 'float'")`. (2) The
previous correction's 0.100 s was labelled a *measured* bound and applied to
the **simulation** clock. It is neither production uncertainty nor evidence
for sim-clock tolerance: it is calibrated on four FIXTURE productions, and the
server stamps the world clock when it SERVES a census request while the client
receives the reply afterwards — the two instants are not simultaneous.

**Typed first, everywhere.** `validate_minion_record` now types every clock
entry ONCE (integer tick, finite time, inside the float-exact tick range)
into a validated list, and only that list reaches the arithmetic: the tick-rate
relation and the endpoint comparison can no longer see a value the gate
refused. Every malformed shape a JSON entry can take is a **structured record
refusal naming the frame** — a string, a list, an object, a boolean (never a
number: `True == 1`), a non-finite float — and a tick beyond `2**53`
(`MAX_CLOCK_TICK`, where `tick * rate` cannot be computed in floats at all:
Python raises `OverflowError`) is refused rather than multiplied. The trial
endpoint the clock is placed inside is typed the same way
(`provenance.diagnostics_end`). **No blanket `except` was used**: the boundary
is type-and-range checks, so a real divergence can never be swallowed by a
catch-all. Verified through the public CLI: the parent's witness bytes are now
refused with `record_B: census frame 1 simulation clock (148, 'bad') is not an
integer tick with a finite time`, exit 1, no traceback, and each of the ten
malformed shapes (clock time ×4, clock tick ×4, oversized tick, endpoint ×4)
behaves the same; a non-finite value cannot even enter the comparator — the
CLI's strict result loader refuses it first (exit 2, `non-finite JSON constant
'NaN'`), which is a second, earlier structured boundary rather than a gap.

**The bound's scope, corrected.** `FIXTURE_SAMPLING_MARGIN_S = 0.100 s`
(renamed from `SAMPLING_BOUND_S`) is what it says: a margin calibrated on the
**fixture** path — four independent productions of one writer, worst deviation
from the declared 1.0 s cadence **0.0086 s** (reported per record in
`sampling.declared_schedule`). It is applied only to the sampling schedule
(census frame offsets per index, carried event offsets per index, each record's
own cadence against its own declared schedule) — **never** to the simulation
clock. The **elapsed simulation clock is now compared EXACTLY**, per frame
index, with no tolerance at all: equal elapsed simulation time is what
same-implementation determinism produces, and this round's productions show it
(the four carry identical normalised series). An out-of-margin sampling
deviation is refused as **UNVERIFIED — not established**, never as a violation
of a production bound the contract cannot evidence. Every verdict therefore
carries `elapsed_time.fixture_calibration` (label `fixture`, productions,
measured 0.0086 s, scope) and `elapsed_time.live_sampling_equivalence`
(status `UNVERIFIED`, why, what is missing, and the offline measurement
below), and a `VERIFIED` verdict explicitly does not claim the live
equivalence beside it.

**The offline real-QA bracket, measured (not assumed).** `measure_qa_bracket.py`
drives the REAL `SandboxQA` service over the REAL mailbox in one process (the
production path the live stack uses, no device/emulator/network) and records
the instants instead of arguing about them: over **50 back-to-back requests**
the client's receipt followed the server's own service instant by **0.038 s**
median / **0.0486 s** worst (the 0.05 s mailbox poll quantum dominates; the
handler itself took 0.00009 s median), and a **census-shaped 9-frame window**
at the declared 1.0 s cadence deviated from that cadence by **0.4515 s** at its
worst frame — **52× the fixture calibration**. The served world clock advanced
19.65 s while the client's wall clock advanced 8.45 s in the same window (the
production tick thread runs at its own cadence), which is why the elapsed
SIMULATION clock is the primary claim and the wall-clock offsets are only a
sampling-schedule comparison. These numbers are REPORTED beside the verdict
(`live_sampling_equivalence.measured_offline`) and **never used as a margin**:
they are offline evidence and cannot bound a live device path. Preserved
separately and unchanged: **internal determinism** — the pair contract's exact
sim-clock equality is the same-implementation determinism claim observed across
two records, and this correction changes neither the simulation nor the writer.
The two-process `run_scenarios.py --mode headless` path could NOT be re-run
this round: its worker fails on the missing external jungle spawn corpus
(archetype 363 / match 6 Kraken) — the pre-existing condition recorded in
checkpoint 13, with corpus recovery out of scope — and that blocked attempt is
kept verbatim as `headless-determinism-attempt.txt` rather than being
claimed as a check that passed.

**Measured through the PUBLIC CLI** (29 cases, `cases.json` + verbatim
stdout/stderr; 6 controlled, 23 refused, no traceback, none unexpected):

* the parent's EXACT clock-type witness → **refused**, exit 1, the record-level
  reason above (the parent's own `error.txt` is carried beside it);
* ten malformed clock shapes and four malformed endpoint shapes → all refused
  with structured reasons, the census-clock check `False` (never a silent
  `None`), the untouched member still accepted;
* the positive — two independent clock-carrying productions: `controlled_pair:
  true`, `elapsed_time: VERIFIED`, exit 0, with the exact sim clock (identical
  series) and the fixture/live scopes reported;
* uniform origin shifts stay controlled: whole wall clock +3600 s and a world
  that had been running an hour longer (`census_sim_times[0]` differs by
  3600.0 s, the elapsed series identical);
* both nonuniform frame witnesses refused: the parent's preserved
  `halcyon-parent-pair-time-umosqx_t` bytes (`census frame 3 … differs by
  0.798s … beyond the 0.100s margin calibrated on the fixture path`, record B's
  own `1.802s` gap) and the same shift on clock-carrying records — UNVERIFIED,
  with the deviation carried verbatim in `sampling_unverified`;
* the simulation-clock warp: `FAILED` — `elapsed SIMULATION time at census
  frame 1 differs by 0.500000s (1.200000s vs 1.700000s) and is compared with no
  tolerance at all` — with the wall-clock offsets untouched;
* an event published 0.9 s later inside its own window: refused, UNVERIFIED,
  naming the event index and offset while the exact sim clock still matches;
* the clock absent from both records, and from one: UNVERIFIED naming the field
  and the member, each member still ACCEPTED on its own evidence, every outcome
  gate still passing;
* cast routing preserved: the three checkpoint-9 cast pairs still dispatch to
  `cast trial pair`, `controlled_pair: true`, exit 0.

**Focused tests.** `TestMinionPairComparison` is now **17 tests / 15 subtests**
(the positive extended with the calibration/live-scope assertions, the uniform
shift, both nonuniform refusals, the sim-clock warp, the event-spacing refusal,
the no-clock and one-sided-clock pairs, and new: a malformed clock member
refused through the CLI without a traceback, the non-finite entries refused by
the CLI's loader, and a malformed endpoint clock); `TestMinionRecordValidation`
is now **33 tests / 91 subtests**, including five new typed-clock tests that
sweep string/list/object/bool/non-finite entries for both halves of the clock,
the oversized tick, the malformed endpoint clock and the endpoint that is not
an object, each asserting the structured reason and that a numeric-but-wrong
entry still fails the rate relation (so typing never becomes a way to skip the
check). Regressions re-run unchanged: **67 passed, 8 subtests** (cast contract:
`TestProofMatrix` + `TestPairCliRoundTrip` + `TestDiagnosticsLinkagePair` +
`TestSchemaInvariant`) and **43 passed, 4 subtests** across the four other
minion classes (`TestMinionEpisodes`,
`TestMinionSurvivorResumptionEvidence`, `TestMinionStructureSequence`,
`TestMinionEndpointContinuity`), each as its own preserved log.

**Still not claimed.** Live sampling equivalence (UNVERIFIED; the missing
evidence is a live production record carrying the census clock and a bracket
measurement on the device path); the simulation instant of an individual event;
the absolute clock origin; slot→owner ownership (`UNVERIFIED`);
presentation/video; publication→pulse identity. The writer and the production
QA reply were NOT changed by this correction: `server/sandbox_qa.py` is byte-
identical to the baseline (`diff` empty, sha256 `127cabbf35ec33b0…`), and the
scoped diff for it is recorded as unchanged. Boundaries carried: no live
ADB/QA service, no gameplay change, no slot-owner overhaul, no agents, no
commit, no model change, no broad-suite run, no corpus recovery; controlled
live runs and final acceptance remain open.

**Baseline and hashes.** The baseline is the previous correction's recorded
after-state, re-verified by hash rather than assumed:
`Tools/scenario_client.py` `36944797766c8e9f…`,
`server/test/test_scenario_client.py` `c00e07c19b98e8cb…`,
`server/sandbox_qa.py` `127cabbf35ec33b0…` and this leaf
`44eaa3967d6006d7…` (`baseline-verify.json` records the comparison, and
`diff-replay.json` the after-state). Evidence:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/halcyon-ckpt13corr2-typed-clock-scope-8f3c2a71-20260912/`
— `snapshot_baseline.py` + `baseline-verify.json`, the scoped baseline→worktree
diffs with `replay_diffs.py` + `diff-replay.json`, the 29-case
`produce_cases.py` with `cases.json` (every CLI stdout/stderr verbatim, the
typed-entry verdicts, the parent witnesses under `witness/`), the offline
bracket calibration `measure_qa_bracket.py` + `qa-bracket.json` + its run
records, the focused test logs, `hashes.json` and `README.md`.

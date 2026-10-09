# Current implementation and validation status

## Audit and execution workflow — 2026-10-04

**Acceptance remains OPEN; no complete faithful-gameplay or PvP claim.**
The active operating plan is [the one-week acceleration workflow](one-week-acceleration.md):
one owner/no delegation, CPU/native-first RE, focused production regression,
targeted nonvisual client evidence, then full freeze/release gates. Seven days
is a timebox, not a guarantee of 100% gameplay. No emulator/client was launched
in this audit; the process IDs and “running” state in older entries below are
historical observations, not a current service-health report.

The full discovery test suite is **1,470 tests, 0 failures, 0 errors, 28 skips, 781.250 seconds** (PASS).
All legacy client fixture contracts were migrated to the nonvisual contract without weakening assertions
or bypassing native guards: `--suite legacy-client` passes cleanly (**284/284 tests PASS**, 715.810 seconds).
The smoke lane passes 71 tests (70 non-skipped, 1 skipped) in 10.901 seconds.

**Seven production headless scenarios pass**, byte-exact across two independent
seeds on one source pin (`Tools/run_scenarios.py --mode headless --scenario all`).
The long verifier (`Tools/verify_sandbox.py`) runs two independent 960-second workers
(38,400 ticks total), matching event stream, canonical state, and checkpoints byte-for-byte,
and **meets the 50 ms deadline gate on every tick** (Run 1 max 22.65 ms, 0 over 50 ms; Run 2 max 30.15 ms, 0 over 50 ms).

The executable original ARM64 health-helper pilot covers 885 cases / 1,770 native
executions, with 883 exact numeric comparisons to the production pool kernel.
All release blockers for Day 1 of the one-week acceleration workflow are resolved;
Day 2 priorities focus on multi-client synchronization, shared pursuit/steering, and match lifecycle.

## Ten-hour run handoff — September22,21:55 local

**The requested complete, bug-free official-like match was not achieved.**
The bounded run delivered measured repairs, not full-game acceptance. Latest
candidate15is running from immutable`scenario-source-gxn14mxg`: launcher23756,
server24800, listeners7100/9443. Fresh Skye265/EID1500 Classic world entry and
native HUD are qualified; server stderr is empty. The first entry attempt
failed on a late, identified Google SignInActivity; its bounded dismissal and
fresh readiness check recovered entry. This is setup evidence, not a new
post-fix movement or complete-match pass. No automated gameplay driver remains.
Temporary crash-log watcher stopped; no commits or unrelated work overwritten.

Highest-priority remaining work: long-run overload attribution with the new
phase timings, native-steering fallback growth, fresh full-match acceptance
after the input-starvation repair, unresolved native movement outliers,
assists and six rendered-client PvP. Tests are not official-parity evidence.
Full evidence/checks: [ten-hour run](classic-ten-hour-run.md).

**Newest evidenced server defect (September22,21:50):** sustained overload
starved received movement input behind unbounded catch-up work. In14's second
late continuation, a1012received at1790088399.236147got its owner1016only at
1790088408.113425: **8.877seconds later**. The loop was already20.4seconds
behind schedule; this was not a missing client tap. Catch-up is now bounded
to four fixed ticks before servicing input, without dropping ticks or changing
step size. A controlled120ms-per-tick reproduction delays input ten ticks in
the prior loop and passes the bounded-batch contract after repair.34relevant
checks pass. This repairs starvation, not the underlying overload or general
smoothness. See [checkpoint26](classic-ten-hour-run.md#checkpoint-26--sustained-overload-starves-received-input).

**Latest long trial (September 22, 21:40 local):** the source-pinned
`classic-live-14/match-01` ran its full 30-minute budget without a client crash
or server stderr, but **FAIL**: it did not reach a result screen. It retained
416 ordinary moves, 51 accepted casts (A19/B16/C16), 12 purchases, 12 upgrades,
10 Flask inputs and 20 qualified Recalls. Across 2,506 resource samples,
native/server K/D/farm agree; max-HP error is below0.000098 and max-energy
error is zero. This does not establish current-resource agreement or assists.

Its 35,653 native logical/root-model samples qualify7,768 moving pairs:
median gap0.0816,p95.2205,max**0.8893units**. The peak coincides with113.5ms
tick work and catch-up; native positions keep advancing with zero correction.
This is not the same observation as13's native hold. Instrumented tick work
has median14.0ms,p95.38.0ms,max182.4ms; lateness peaks288.0ms. QA-directory
enumeration alone measures5.6ms median, but full attribution remains open.
Opt-in per-phase tick timings are now implemented and33 relevant checks pass;
they are not present in the still-running14source pin.
The subsequently qualified Windows request enumeration preserves the same
mailbox ordering/durability/validation while reducing the retained-directory
microbenchmark median from5.42ms to.23ms (100interleaved samples each,
3,304entries).47QA/timing checks pass. No whole-tick or live-smoothness
improvement is claimed;14's running code remains unchanged.

The ordinary driver needlessly recalled for unspendable gold after filling
six inventory slots; its shared purchase/Recall policy is repaired. A late
diagnostic continuation then stopped on a Flask tap33ms after authoritative
death, with no1096input. Fresh native liveness now guards that tap;41Classic
checks pass. Original failures remain. The second late continuation is not
fresh uninterrupted full-match acceptance. See
[checkpoint25](classic-ten-hour-run.md#checkpoint-25--thirty-minute-ordinary-trial-and-long-run-diagnostics).

**Newest native result (September 22):** prepared post-A pursuit passes with
retained selection and active navigation: maximum logical/root-model gap
**0.256 units**, versus **2.287** in the baseline. The ordinary `classic-live-12`
exercise then retained 83 walking orders / 5,377 native samples; 1,531 qualified
pairs had a maximum gap of **0.250 units**. The later13run's705pairs reached
**0.483 units**: native logical/root-model position held for about100ms during
active navigation, then advanced, around the first minion spawn; no owner
correction and nearby server ticks were timely. Cause remains unresolved.
These are diagnostics, not general smoothness or a controlled comparison.

That fresh match successfully cast A/B/C but its verifier stopped when a C
target died and its exact lock was cancelled during the swipe. The original
FAIL is preserved. A strict interruption classification now requires that
gesture-window evidence plus native death/destruction; it never counts a
cast or retries the input. **37 driver checks pass**, as does a new six-owned-
connection production movement check.13completed two ordinary Recalls but a
second, unguarded HUD traversal bypassed the existing bounded reader and
failed transiently;59Classic/movement checks pass after routing every Classic
HUD guard through that reader. `classic-live-14` is the fresh ABC/Recall run.
Complete-match acceptance, six rendered-client
PvP, assists and official parity remain open. See
[checkpoint 23](classic-ten-hour-run.md#checkpoint-23--ordinary-movement-evidence-and-target-death-input-race)
and [qualified pursuit evidence](solo-sandbox-navigation.md#september-22-qualified-prepared-pursuit-repair).

The chronological checkpoints below retain their original pending states;
the newest result above supersedes them.

**Latest September22 checkpoint:** native measurements now isolate a pursuit
publication gap after abilities: the server resumes walking while native
navigation remains inactive and follows corrections. A clean living-target
prepared baseline reaches2.287units disagreement. Explicit pursuit1016
publication is implemented behind a default-off experiment and is undergoing
the matching live comparison. A separate stale-route-after-target-death bug
is fixed; seven exact production headless comparisons pass, not client
acceptance. Prepared post-fix B now retains matching native/server selection.
The latest ordinary run stopped at423.8s on a death overlapping an ability
gesture; full fresh-match acceptance remains open. See
[checkpoint20](classic-ten-hour-run.md#checkpoint-20--measured-pursuit-publication-gap-and-invalid-target-repair).

**Ongoing September22 update:** the previous ordinary diagnostic match reached
native Defeat with matching final structure HP and K/D/farm, but its result-UI
transition verifier failed; this is not full-match acceptance. A new fresh run
exposed and corrected a verifier assumption:1045 starts an attack, not immediate
1060 pursuit acceptance. A later valid enemy pick outside the policy's aim
radius corrected a second verifier assumption: that radius selects the aim,
not every enemy whose selection capsule can overlap it.

Read-only native path sampling now supports an offline pinned Detour comparison:
38 of39 active routes match exactly at float32; one height differs by one ULP.
An optional, default-off3D-steering backend has production regression coverage,
but no live movement acceptance yet. All500 broader production traversals now
arrive (453surface routes,45partial/cap fallbacks, two height fallbacks).
Traversal reproduced a rounded step leaving an invalid future segment; the
collision guard now checks both. A prepared native B trial also reproduced
Suri Strike retaining native selection while dropping authoritative pursuit;
guarded restoration is implemented and regression-tested. Fresh`classic-live-06`
is now exercising both changes from one immutable external source snapshot.
See [checkpoints17–19](classic-ten-hour-run.md#checkpoint-17--natural-result-fresh-trial-and-target-observation-correction)
for exact scope, failures, tests and C:/D: evidence locations.

**Latest live combat findings:** a fresh ordinary Classic exercise verifies
all ten turret barriers now start at zero. It then exposed two further
client/server disagreements: Skye's native selected target survives Barrage,
but the server discarded it; later-wave minions retained native base HP475
while the server assigned735 or805. Scoped target restoration and explicit
spawn maximum/current-HP publication are implemented, with67 and90 relevant
checks respectively (three skips in the latter), plus all seven exact
production headless comparisons. Fresh native reads now verify matching
minion HP/maxHP720,525,560 and retained target restoration after Barrage.
The ordinary match driver has not yet completed acceptance.
See [checkpoint13](classic-ten-hour-run.md#checkpoint-13--ordinary-combat-exposes-target-and-minion-health-disagreements).

The ongoing ordinary-client exercise also identified an input-automation
latency problem. A source-pinned persistent wrapper around Android's existing
ordinary input class removes per-tap VM startup (27ms median tap transport in
one trial). Exact wire/native target gates remain; overlapping enemy picks and
concurrent target deaths are now explicitly distinguished. No full-match or
general smoothness claim follows from this harness improvement.

**Earlier additional defect:** native turrets carried an unmodeled600-point
barrier imported from the archived startup tape. Complete wire accounting and
native HP/barrier reads explain why destroyed outer turrets retained600 HP.
The exact60 grants are now omitted only from the fingerprint-qualified live
bootstrap;21 relevant tests pass and fresh native verification confirms zero
barrier on all ten turrets. The prior
match naturally reached native Defeat at22:33, but was mostly idle, not full
human-played acceptance. An external public Detour diagnostic now reproduces
two native routes; production steering/3D distance still differs. See
[checkpoint12](classic-ten-hour-run.md#checkpoint-12--native-route-oracle-and-archived-turret-barrier-defect).

**Active work window:** [ten-hour Classic implementation run](classic-ten-hour-run.md),
September 22, 11:55–21:55 local time. **Latest:** the native client's baked
navigation mesh is now verified against an owned asset and replaces the raw
authoring mesh used by the server. A reported corner route demonstrably crossed
a client obstacle. Structure target-radius checks also repair the melee stall
exposed by the corrected geometry. 118 focused checks and all seven production
headless comparisons pass. A fresh baked-mesh comparison still showed overshoot;
withholding normal owner start/arrival corrections then produced **13 ordinary
inputs /6855 logical+root-model samples**, zero reversals on seven straight
legs and exact final accepted destinations on all11 completed legs (two
retargeted). Other subscribers/stops/forced movement remain regression-covered.
Active native camera projection now drives world-coordinate inputs through the
existing scenario without images; three further world-point trials pass.
Root-model matrix observation is now qualified, but an earlier Skye corner
trial measured0.434-unit correction overshoot. Endpoint drift is repaired in
the measured cases; up to0.464-unit moving client/server disagreement still
needs investigation. General movement/full-match acceptance remains open.
See [exact evidence and boundaries](solo-sandbox-navigation.md#september-22-native-baked-navigation-replaces-authoring-geometry).

Earlier navigation repairs have fresh native
client evidence (14 inputs/7,850 samples; logical positions, not model transforms).
Healing Flask now passes the native resource gate, including 150→50→0 barrier
absorption and exactly matching final HP. A discovered wounded-level-up drift
is fixed and live-verified at level 3→4 (HP error below 0.000001).
Kill/death/farm publication now has native live validation, including retained
counters across natural respawn; assist eligibility remains open. One bot match reached Defeat at 19:24
and returned to the menu, exposing missing player K/D/A. Complete human-played
match acceptance and official parity remain open.

The same run now has **ordinary native A/B/C casts and Recall completion /
movement cancellation** passing position/resource gates. A QA-only teleport
defect was found through native target positions and repaired with explicit
relocation; a collision-constrained 1070 correction was not sufficient.
These are disclosed prepared trials, not full-match or model-animation acceptance.

Native inventory inspection additionally found **client-only +10% weapon power
from three archived startup-tape modifiers**; the qualified live bootstrap now
omits them, and a fresh native read confirms zero multiplier. A separate spawn
defect mixed vertical height with planar depth for five bot slots and copied
donor positions into other hero selections. Slot-specific XYZ publication is
fixed; 91 focused checks and seven exact headless comparisons pass. Fresh native
spawn now agrees before movement. Ordinary Weapon Blade purchase and Heavy Steel
upgrade pass exact cost/instance/native weapon-power gates without QA preparation.
Complete-match acceptance remains open; the later model accessor and geometry
findings above supersede the prior instrumentation limitation.

## Validation approach selected — 2026-09-22

[Reference-driven differential validation](differential-validation.md) combines
independent CE evidence, cheap production regression and targeted native client
measurement. The existing movement inspector now analyzes retained client runs
with identity, clock and input-boundary qualification. **Seven runs / 47 inputs /
27,323 client samples were analyzed offline in 3.49 seconds**, reproducing the
prior reversal counts without a new live session. **20 focused tests pass**;
straight-path metrics cannot silently classify corners, failed setup or unknown
targets. Smoothness and cross-service comparability remain unverified.
Fixture extraction, automated failure minimization and controlled-latency client
tests remain next work, not implemented features of this analysis pass.

## Independent CE reference acquired — 2026-09-22

The ordinary owned client reached the **external CE service**, with only
passive packet observation and anchored native-state reads. The existing
movement driver completed **14 inputs / 10,030 client samples** across two
batteries (Amael 925, owner 1500/slot 0). No image/video path was used.

- CE sent **2–3 owner corrections per short walk**, versus eight in the old
  local burst policy. All six CE short legs nevertheless showed backward
  logical steps; CE is not a zero-reversal baseline. Different latency and
  initial transient state prevent a controlled CE-versus-local smoothness claim.
- **Replay-only evidence is insufficient:** 15,041 native replay frames
  contain none of the **45 owner `1070` corrections** present on the paired
  wire. All 14 ordinary owner `1016` acknowledgements match byte-for-byte;
  the replay also adds a shorter movement record.
- New passive incremental adapter feeds the **same scenario driver**, excludes
  login tokens from JSONL, retains clock provenance, and avoids whole-capture
  re-decryption on every poll. **20 focused tests pass.**
- Original local profile/routing restored; local stack left running. Existing
  no-image/video invariant and uncommitted work preserved; no new server
  movement-policy change follows from this unequal-latency reference alone.

See [reference measurements and evidence](solo-sandbox-navigation.md#external-ce-movement-reference--2026-09-22)
and the [passive workflow](../Teardown/vainglory-runtime-reconstruction.md#2026-09-22-external-ce-passive-reference-workflow).
General smoothness and faithful full-match acceptance remain open.

## Active 3v3 priorities — 2026-09-22

Return to Classic-mode work; novelty modifiers are not the acceptance track.
Close shared systems before expanding hero-specific implementation:

1. **Movement — measured client-side defect repaired:** native UI text
   identified the blocking build panel; guarded dismissal restored walking.
   An A/B/A comparison found backward logical motion on **8/12 short walks**
   with the five-sample owner burst, versus **0/6** with periodic corrections
   suppressed. Production walking now retains start/retarget and arrival/stop
   updates but omits periodic owner corrections; other subscribers, attack
   pursuit and authoritative movement are unchanged. After restart, the
   **default patched path reproduced 0/6 reversals**, with no diagnostic
   suppression file. Two live batteries produced **14 inputs / 7,731 client
   samples**; all 40 owner publications match authoritative tick states.
   **40 focused tests pass** (latest changed-driver run: 18). The driver now
   waits through native loading/countdown text and verifies gameplay-HUD text
   before input. Scheduler and accepted-destination repairs remain in place;
   earlier full/headless results were not relabeled as fresh verification.
   **General smoothness remains OPEN:** this historical A/B/A observed logical
   positions only. Root-model observation and geometry repairs are now available
   (above); newer Skye evidence still shows an arrival-correction defect.
   See the [measured correction repair](solo-sandbox-navigation.md#measured-owner-correction-reversal-and-walking-fix--2026-09-22).
2. **Combat and resources:** basic hit/damage/death, healing/barrier/cooldown
   contracts. The [Flask evidence pilot](solo-sandbox-items.md) identifies
   missing default-item dispatch/mechanics but does not claim Flask is fixed.
3. **3v3 map loop:** wave combat, survivor movement, turret aggro/damage,
   jungle, respawn and crystal ending, using production scenario integration.
4. **Multi-client agreement:** separate human identities, movement/combat
   observation, reconnect and a completed match before claiming playable PvP.

Use one emulator/runtime owner; parallel work should have disjoint subsystem
files and named evidence outputs. AGENTS.md now makes **no image/video
dependency** an invariant, including setup guards. Older visual-review
milestones below are historical, not instructions to resume capture work.
Each defect needs a reproducible input, an authoritative result and measured
client behavior. Headless passes or repeated
delegation attempts do not substitute for that closure. The faithful full
gameplay target is unchanged; this is execution order, not reduced scope.

Reviewed **2026-09-13**, using repository source and the evidence records
through September 12. **Halcyon is an experimental, self-hosted private
server; overall gameplay acceptance remains OPEN.** The target remains a
faithful PvP implementation. Neither a complete ordinary match nor an
independently validated replacement service is established by the current
record.

## Source and evidence baseline

The public baseline at the start of this review was commit `5e8b867`.
The reviewed local worktree also contained subsequent source, tooling, tests
and documentation, including the scenario pilot and September 12 Skye C
corrections. Claims about those additions must be read against the commit
containing them, not attributed to `5e8b867`. Historical source pins and
test counts below are preserved evidence, not a fresh verification of every
later change.

This summary audits existing records. It does not claim a new September 13
LDPlayer recording or rendered-client acceptance. Fresh demonstration
evidence needs its own source identity, setup disclosure and observed result.

## Verification on September 13

**Later setup/relocation pass:** the fresh venv and imported, Git-ignored
project-local inputs passed **1,176 tests in 904.996 seconds, OK (27 skipped),
exit 0**. All six headless scenarios passed exact comparison on source pin
`e5a71f214dc5f2671fb8d1e8bf93eceac07df8ce83c28cfd193acf613dc87fd2`.
See the [setup validation record](../Setup/windows-local-development.md#13-relocation-and-validation-record)
for commands, input inventory, evidence paths and remaining capture limits.
This pass did not restart the live stack or establish new rendered acceptance.

The earlier status-review unittest suite completed with **1,152 tests in 907.377
seconds, OK (27 skipped), exit 0**, using `-B -W error::ResourceWarning`.
The skips concern external captured evidence (some checks use their original
default paths), including native attack/lifecycle/volley records; they are
not claimed as passing corpus comparisons. The full log is
`halcyon-demo-20260913-093835/full-suite-verbose.txt` outside Git.
The subsequent recorder startup-race correction passed all six recorder
checks, including the two new empty-receipt regressions. Real LDPlayer smoke
recordings also completed and finalized after both natural timeout and an
early stop of the owned recorder. These smoke recordings show the launcher,
not accepted gameplay. No test or skip condition was weakened.

The six production headless scenarios pass on the current source snapshot in
both independent processes (`PYTHONHASHSEED=11` and `7919`). Events, initial
state, final state and checkpoints are byte-identical for every scenario;
`workspace_matches_snapshot` is true. Source manifest SHA-256:
`153f7a12e0f7b571af28eab648f00aa4a5be3a100f257f26b3ff1c58c17505ca`.
The command was `python -B Tools/run_scenarios.py --mode headless --scenario all`
with an explicit external output directory and the recovered owned corpus
paths. The evidence is `halcyon-demo-20260913-093835/headless-final/summary.json`
outside the checkout. Independent reference remains `UNAVAILABLE`, and the
minion-push fixture still includes its declared wave elimination.

**Skin selection and Skye A/B presentation repair pass (2026-09-13):**
- **Candidate implementation:**
  - Skin manifest (`getSkinManifest`: 290 skins, 192 themes) and account unlocks (276 entries with `canUseAllHeroes: true`) integrated into `Local/runtime/halcyon_stack/answers.json`. Backup preserved at `.zcode-dispatch/contract-1789291507236-ea8017/tasks/skins-skye-repair/attempt-2/answers_backup/answers.json`.
  - Hero catalog resolution (`server/hero_catalog.py`) maps all 275 items to canonical hero identities and aliases (`Krul` -> `Hero009`, `Rona` -> `Hero016`, `Skaarf` -> `Hero010`, `Taka` -> `Sayoc`).
  - `server/match_server.py` permits cosmetic skin updates during the draft lock phase when base hero matches the locked hero, maintaining `player.selection_hash` and configuring base hero balance on `_finalize`.
  - Skye Forward Barrage (A) presentation: emits Opcode 1039 (46 B, kind 110, socket `0x259fd523`, 2D direction vectors) on pulses, applies Buff 607 (`Buff_Skye_Barrage`) to Skye, and Buff 608 (`Buff_Skye_BarrageSlow`) on hits.
  - Skye Suri Strike (B) presentation: emits Opcode 1027 dash translation (22 B, speed 18.0), Buff 609 (`Buff_Skye_Executing_B_Dash`), Buff 610 (`Buff_Skye_Firing_B_Missiles`), 4 curved missiles via Opcode 1038 (30 B, kind 111, alternating RocketPod_L `0x4578de4f` curve=1.0 / RocketPod_R `0x3b78ce91` curve=-1.0), and Buff 611 (`Buff_Skye_HitBy_B_Missiles`) on impact.
  - Skye C volley actors (1010) and buffs 612..618 preserved.
- **Worker-tested behavior:**
  - New unit test suites `server/test/test_skin_selection.py` (14 tests) and `server/test/test_skye_ab_presentation.py` (9 tests) pass with explicit known-bad/pre-fix and known-good calibration suites (`TestSkinSelectionCalibration`, `TestSkyeABCalibration`).
  - All 6 production headless scenarios (`Tools/run_scenarios.py --mode headless --scenario all`) continue to pass byte-identical across independent process seeds 11 and 7919 (output: `AppData/Local/Temp/halcyon-scenario-pilot-20260913-162241/summary.json`).
  - Core pinned regression suites (130 tests across 10 modules) pass with 0 failures, 0 errors, 5 skipped.
- **Live observed rendering & platform validation:**
  - Real Android CE client connected to local stack on `emulator-5554`: successfully fetched `getSkinManifest` (290 skins / 192 themes), rendered skin selection cards on draft screen (`screen_skin_panel.png`), and acknowledged skin lock with wire trace `c2s 1118`/`1119` (hero 925, selection_hash `0x2fd7245d`). Screencaps preserved at `C:/Users/terasumi/AppData/Local/halcyon-evidence/agy-skins-skye-328174e8e46f4131befdef14dfe02b07/live-verification/`.
  - Machine-emitted packet frames (1027, 1038, 1039) are proven at the wire/unit level; full human visual rendering review of in-world ability VFX remains unreviewed / pending visual acceptance.
- **Dispatcher verification:**
  - Frozen gates `focused-regression` (10 suites) and `headless-all` executed independently without modification to pinned files.

## What currently exists

| Layer | Implemented behavior | Validation boundary |
|---|---|---|
| Local platform | Preauth/authentication, catalog, lobby/draft and match entry | Android CE 4.13.4/build 147219 has entered local matches. Catalog selectability is broader than implemented kits. |
| Gateway and sessions | Framing/encryption, shared match routing, heartbeat, draft synchronization and reconnect handling | Automated integration coverage exists. Repeatable combat with two real clients remains an acceptance milestone. |
| Authoritative simulation | Fixed 50 ms ticks; movement, attacks, selected abilities, items/economy, minions, structures, jungle objectives and death/respawn | Bounded solo-client observations exist, including Victory and prepared QA scenarios. Full ordinary-match acceptance remains open. |
| Hero kits | Explicit factories for Ringo, Catherine, Gwen, Celeste, Lance, Taka, Adagio, Koshka, Amael and Skye | Factories include partial kits and calibration policies; ten factories do not mean ten complete faithful kits. Other selections receive no substitute hero kit. |
| Verification tooling | Production headless scenarios, a rendered-client driver, declared-fixture checks, pair comparison and an external reference interface | A tool's existence is separate from a successful live run or a passed comparison contract. Independent reference remains `UNAVAILABLE`. |

The [main acceptance record](solo-sandbox.md) and
[seven-gate checklist](solo-sandbox-acceptance-status.md) link the original
bounded navigation, attack, item, jungle, lifecycle and match-ending evidence.

## Latest measured progress and limits

- **Skye A/B/C through the declared-fixture gate:** September 12 records carry
  two PASS attempts per ability. A's attempts share one match; B's and C's
  attempts each use two fresh matches. Setup includes declared QA placement
  and state checks. Matching damage totals are same-implementation
  observations. The production compare-pair contract was not run, those
  presentations remain unreviewed, and preserved records do not establish
  chronological movement-slot ownership. See the corrected
  [scenario summary](solo-sandbox-scenarios.md).
- **Skye C implementation corrections:** owned-record and native-contract
  inspection supports publishing activation before the first damage pulse
  and selecting the cluster form only strictly inside two units of the
  marked target. The record reports 37 focused tests and a production
  headless Skye C PASS with exact outputs across seeds 11 and 7919. Fresh
  rendered acceptance of these changes remains pending. The native damage
  tag/flags, footprint eligibility and active-field recreation on reconnect
  remain open. See the [September 12 contract record](solo-sandbox-abilities.md#2026-09-12-skye-c-native-contract-and-two-production-corrections).
- **Lane minions:** three live windows, two of 35 seconds and one of 60
  seconds, establish approach and opposing combat. All FAIL the remaining
  observation stages: no qualifying post-combat survivor resumption or
  structure interaction/effect was observed inside those windows. This is
  a finite observation, not a conclusion about every later match. The
  headless `minion-push` PASS uses a declared post-contact wave elimination;
  it proves the integrated fixture path, not natural live pushing.
- **Internal repeatability:** the recorded six-scenario headless run passed
  exact event, initial/final state and checkpoint comparison across two
  seeded processes on source pin `de53b6eb…` (corr8). That predates subsequent
  corrections and requires a final run on the source being reviewed. A
  recorded full suite passed 898 tests, with 2 skipped, on September 11;
  it is historical environment-specific evidence, not a current test count.
- **Long-session reliability:** the roughly 30-minute idle WORLD client
  crash remains open and is distinct from earlier missing-tape startup
  failures. A short successful demonstration cannot close this issue.

Local recordings prove Halcyon's visible behavior. Exact local outputs
establish internal repeatability. Neither establishes official gameplay
fidelity without an independently measured reference. The latest owned
Skye C cache provides structural evidence but is not a complete normalized
gameplay reference fixture.

## Reproduction prerequisites

The recorded live workflow uses Windows, rooted LDPlayer 9, ADB and the
owned Android CE client. Python 3.11+ and PyCryptodome are required by the
server tooling; Pillow is required for the rendered-client driver/tests and
the optional native-contract inspector also uses Capstone.
The Windows `live_up` helper is not a portable Linux launcher.

Captured payloads and client data intentionally remain outside Git:

| Input | Configuration / purpose |
|---|---|
| A001 navigation record | `HALCYON_NAVMESH`, an absolute path to the owned extracted record; production scenarios require the actual mesh. |
| Jungle spawn corpus | `HALCYON_SPAWN_CORPUS`, including the owned match-6 Kraken archetype-363 creation record. |
| Skye volley corpus | `HALCYON_SKYE_VOLLEY_CORPUS`, containing the owned volley chunks 32 and 36. |
| World initialization tape | Ignored `Local/runtime/halcyon_stack/world_tape.bin`, rebuilt from owned capture data by `Tools/build_world_tape.py` and validated against the production loader digest. |
| Platform configuration and trust | Ignored `Local/runtime/halcyon_stack/answers.json`, certificate/key and guest routing/CA trust; legacy TEMP paths remain fallback locations. |
| Verification artifacts | Unique external output directories; preserve existing captures and journals. Current durable pilot records are under `%LOCALAPPDATA%/halcyon-evidence/`. |

A fresh clone without these inputs is not a self-contained runnable demo.
Missing spawn or volley data can fail integration tests during setup; record
that prerequisite failure separately from a simulated gameplay regression.
The September 13 relocation adds ignored `Local/vainglory`, `Local/research`,
and `Local/runtime/halcyon_stack` defaults, a verified importer, input inventory
and setup checker. Original captures remain distinct from minimal reconstructed
runtime records; missing full capture fixtures are still unavailable. Use
`Local/runtime/halcyon_stack/world_tape.bin` for the current local layout.
Follow the [complete Windows reproduction guide](../Setup/windows-local-development.md)
and [scenario commands](solo-sandbox-scenarios.md#commands).

## Next acceptance milestones

1. Verify a pinned source with documented external prerequisites and retain
   the complete test/scenario results.
2. Establish nonvisual client-state evidence for movement and the current
   Skye corrections, complete the controlled pair contract, and retain input,
   authoritative outcome and measured client behavior together. Resolve the
   native-input-to-world-order guard before another owned-hero walk; logical
   entity position alone is not a rendered/model-transform measurement.
3. Establish natural minion progression into structures with a stated
   observation window, and investigate the long-session crash.
4. Demonstrate two actual clients entering one match and exchanging attacks
   with consistent health changes, then verify one server-side balance
   parameter change in-game under comparable conditions.
5. Extend hero/mechanics coverage and independent reference comparisons
   before claiming faithful complete matches or maintainable service readiness.

The repository's private, non-commercial scope is unchanged. This status
update does not grant commercial rights or permissions over Vainglory assets.

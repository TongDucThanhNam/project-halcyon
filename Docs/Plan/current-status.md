# Current implementation and validation status

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
2. Review fresh rendered-client evidence for the current Skye corrections,
   complete the controlled pair contract, and retain the input, authoritative
   outcome and visible presentation together.
3. Establish natural minion progression into structures with a stated
   observation window, and investigate the long-session crash.
4. Demonstrate two actual clients entering one match and exchanging attacks
   with consistent health changes, then verify one server-side balance
   parameter change in-game under comparable conditions.
5. Extend hero/mechanics coverage and independent reference comparisons
   before claiming faithful complete matches or maintainable service readiness.

The repository's private, non-commercial scope is unchanged. This status
update does not grant commercial rights or permissions over Vainglory assets.

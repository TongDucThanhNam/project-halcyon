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

## Host-input ownership execution — 2026-10-10 rev5

**Accepted Live1 retained; Live2 ordinary SETUP/BLOCKED; Live3 UNRUN.**
Dispatch `run-1791609724221-29dd246d` adds run-shared lock receipts, immediate
pre/post-gesture host ownership checks and a no-further-input latch. Activation
and its after_foreground check are byte-for-byte unchanged from rev4. The
pre-attach guard requires three stable ready PID/activity/native Resume samples
at least one second apart, using the initialized-only Resume code anchor.
The rev4 strict leaf rule and all native guards remain unchanged.

A's single cold start initially lacked native Resume; one explicit Android
activity reactivation retained the PID and qualified readiness before attach.
A reached one qualified PLAY gesture, but Chrome gained foreground immediately
afterward. B was still stopped. The new guard stopped input and released the
lease. No guessed controls, second PLAY, force-stop cycles or focus bypass.
A never reached draft, so reciprocal A/B background liveness, dual admission/HUD
and movement isolation remain unverified. A desktop interval without external
foreground changes is needed; the cause of Chrome's activation is not established.
See [rev5 receipts/readiness/limits](solo-sandbox-scenarios.md#current-rev5-ownership-guarded-external-foreground-loss-blocks-live2).

Evidence **V** =
`C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791609724221-29dd246d/`.
Cleanup completed: A's full guest baseline restored, owned four hashes unchanged;
B never booted; both emulators, Frida and stack stopped. Platform/full lanes use
`HALCYON_STACK_DIR=<V/test-runtime>` (copied owned inputs); client-02 uses the
unchanged owned default. Checks run sequentially:

| Command (`python -B`; first seven rows use `Tools/run_checks.py`) | Result |
|---|---|
| `--suite client --output <V/final-client-02>` | 172 PASS |
| `--suite workflow --output <V/final-workflow-02>` | 40 PASS |
| `--suite transport --output <V/final-transport-02>` | 39 PASS |
| `--suite smoke --output <V/final-smoke-02>` | 73 PASS / 1 reviewed missing-owned-capture skip |
| `--tests server.test.test_multiclient server.test.test_platform_fsm server.test.test_platform_identity --output <V/final-platform-02>` | 36 PASS |
| `--suite legacy-client --output <V/freeze-legacy-client-02>` | 291 PASS |
| `--suite all --output <V/freeze-all-02>` | 1519 PASS / 28 reviewed skips (1547 run) |
| `Tools/run_scenarios.py --mode headless --scenario all --output <V/freeze-headless-all-02>` | 7 exact independent pairs PASS |
| `Tools/verify_sandbox.py --output <V/freeze-verify-sandbox-02>` | 2×960 s simulation: exact stream/state/checkpoints; every tick <50 ms |

All seven unit-result manifests and both scenario/verifier pins match the final
workspace. Full discovery's 28 reviewed skips match rev4: 27 unavailable owned
capture/corpus inputs and one Windows symlink-privilege case; none is counted
as an executed pass (`reviewed-freeze-skips.json`). The independent gameplay
reference remains UNAVAILABLE. Verifier: 38,400 ticks across two 960-second runs,
full-duration coverage, **27.3683 / 49.9362 ms** maxima, zero ticks over 50 ms.
This passes the measured deadline, not a claim of large performance headroom.
`final-source-review.json` retains source equality, 15 Python syntax checks,
valid example JSON, diff hygiene and unchanged owned inputs. Post-freeze
`emulators-after-freeze.txt` / `processes-after-freeze.json` confirm stopped
runtime; `owned-after-freeze.json` reconfirms all four input hashes.

Self-review: preserve missing initialization as UNKNOWN, not false; tolerate only
pidof's absent-process exit1 while retaining real shell failures; always unlock
on receipt-publication failure. Concurrent-driver tests assert actual exclusive
activation→gesture ordering, not scheduler-dependent post-unlock log ordering.
Readiness additionally matches the activity record header and refuses a Resume
older than the latest renderer initialization-start marker. Both negative cases
pass, and the retained live three-sample readiness passes this final parser
(`readiness-final-parser-recheck.json`). The first freeze was deliberately
interrupted for this review fix; its partial results are not counted as a pass.
No native gameplay observer or server implementation changed in this dispatch.
No screenshot/video work or commits. Prior rev4 gates below are historical.

## Leaf-flags entry execution — 2026-10-10 rev4

**Live1 PASS; Live2 SETUP/BLOCKED, not REPLAN; Live3 UNRUN.** Dispatch
`run-1791605229771-8926354d` authorizes the strict leaf-only UNCLASSIFIED flag
exception, not the withdrawn opacity inference. Both candidate and final pairs
retain every permitted change and keep exact control/ancestry, `0x1C`, input-bit,
structure, layout and overlap guards. New tests cover all permitted bits,
protected regions/non-leaves/text/events, changed geometry/structure/methods,
ancestor settling, immediate descendant `0x1C` replan, and missing1123/1119 or
native LOCKED (one tap, no repeat). No gameplay or native observer code changed
in this dispatch. Focus errors now retain Windows API results rather than only
a generic failure; no foreground check is waived.

Here **U** is
`C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791605229771-8926354d/`.
One cold-menu run (`single-entry-01`) passed the ordinary path through nine
qualified gestures, server-confirmed selection/lock/finalization/load and
native HUD: connection2290320937168, EID1500, slot0, team1, explicit device guest.
No build-panel dismissal was needed. The [scenario record](solo-sandbox-scenarios.md#earlier-rev4-single-client-world-passed-dual-setup-blocked)
contains exact leaf flag deltas and traversal maxima, plus unresolved bit/hit-test
semantics. Local entry success does not accept movement, smoothness or fidelity.

The first dual run failed host foreground qualification before draft. Bounded
focus-only/instrumented diagnostics passed20 switches but did not establish
the full driver's missing signal. Two later cold preparations failed before
driver entry, first with B's game PID absent, then A's. ActivityManager logs show
`remove task` killing the teardown-spawned game process and `failed to attach`;
an inserted two-second gap was insufficient. Stopped under the setup-attempt
bound, with zero dual-draft locks. Do not call this a gameplay regression or a
rev4 replan trigger. Dual admission/HUD and movement isolation remain unverified;
the isolation extension is not implemented. Next resolution is a measured
cold-launch lifecycle guard and qualified per-driver foreground ownership.

Final-code checks (`HALCYON_STACK_DIR=<U/test-runtime>`, copied owned inputs):

| Command via `python -B Tools/run_checks.py` | Result |
|---|---|
| `--suite client --output <U/final-client>` | 163 PASS |
| `--suite workflow --output <U/final-workflow>` | 40 PASS |
| `--suite transport --output <U/final-transport>` | 39 PASS |
| `--suite smoke --output <U/final-smoke>` | 73 PASS / 1 reviewed missing-owned-capture skip |
| `--tests server.test.test_multiclient server.test.test_platform_fsm server.test.test_platform_identity --output <U/final-platform>` | 36 PASS |
| `--suite legacy-client --output <U/freeze-legacy-client>` | 291 PASS |
| `--suite all --output <U/freeze-all>` | 1510 PASS / 28 reviewed skips (1538 run) |
| `Tools/run_scenarios.py --mode headless --scenario all --output <U/freeze-headless-all>` | 7 exact independent pairs PASS |
| `Tools/verify_sandbox.py --output <U/freeze-verify-sandbox>` | 2×960 s simulation: exact stream/state/checkpoints; every tick <50 ms |

Verifier maxima: **21.6946 / 20.6932 ms**, zero ticks over50 ms, full-duration
coverage in both19,200-tick runs. All final check/source manifests and both
headless/verifier pins match the unchanged workspace. Full discovery's28 skips
are27 unavailable owned capture/corpus inputs and one Windows symlink privilege
case; all are retained in `reviewed-freeze-skips.json`, not executed passes.
The independent reference remains UNAVAILABLE. No test or deadline was waived.
Live1's pin precedes only the later host-focus diagnostic enrichment and test
additions, not a qualification-rule change. Self-review also fixed field-presence
comparison so adding/removing a null-valued native field is not silently omitted.

Both emulators stopped before these gates. Cleanup: both full guest IPv4/IPv6,
hosts/CA sources/targets, mounts and reverse maps equal baseline
(`c-emulator-555{4,6}-restoration-check.json`); Android UID10021 media/download
and UID10015 Google policy rules preserved. Frida PIDs4237/4637 verified and
stopped; added forwards removed (`frida-cleanup.json`), stack29364 stopped.
`emulators-final.txt`, `processes-final-qualified.json` confirm stopped runtime;
`owned-after.json` confirms four unchanged hashes. A first overly broad process
query matched its own PowerShell command and refused; the corrected query
requires the executable class as well, and found no live runtime. The second
guest's missing retained `fsrv` was installed from the owned first guest with
matching SHA, and left installed/stopped (`second-frida-install.json`).
No image/video use, blind game inputs, gameplay-rule changes or commits.

## Animated-descendant inference — 2026-10-10 rev3

**BLOCKED (REPLAN): the low-bit invariance premise is contradicted.** Dispatch
`run-1791604424986-0a47aa99` required ≥50 complete no-input DRAFT reads before
the proposed bits7–14 animation tolerance. Collected **60 reads over 12.471 s**,
same root throughout, maxima **1,196 visited / 670 active / 51.393 ms**. The
corresponding LOCK IN image descendant (`0x7638650cc0d0`, vtable `0x27266f0`,
490×221, no text/events) matches the prior target's full vtable/dimension/event
ancestry. Flags varied across 35 values, with cumulative XOR **`0x7F81`**.
Reads36→37 changed **`0x2B4C → 0x0B4D`** (bit0 changed); read38 returned low
bits to `0x4C`. All other fields of that node stayed constant. This is the exact
rev3 rule3 contradiction; animation opacity remains an inference, not a measured
semantic property. We did not mask bit0, enable the exception or send LOCK IN.

Here **T** is
`C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791604424986-0a47aa99/`.
Artifacts: `draft-series-01.json` (all reads),
`draft-series-01-observer.metadata.json` (pinned library, zero errors),
`draft-series-01-analysis.json` (all 12 varying nodes, fields, changed bits and
before/after samples), `animation-target-lineage.json`, and
`animation-inference-verdict.json` (exact contradiction). Per-node table and
all menu-stage maxima are in the [scenario record](solo-sandbox-scenarios.md#earlier-rev3-animation-inference-contradicted--blocked-replan).

Only preparatory changes were made: a bounded `draft_observation_only: 50..100`
entry option and its no-lock regression. The staging attempt reached draft
after four menu gestures and two measured scrolls, then correctly refused an
overlapping mutation before the next scroll. The read-only follow-up used the
same qualified production observer directly. No selection or WORLD acceptance
is claimed for this run. No animation-tolerance implementation or added
animation-rule regressions were attempted after the contradiction.

Check: `python -B Tools/run_checks.py --tests server.test.test_nonvisual_entry
--output <T/observation-unit-01>` with copied owned config via
`HALCYON_STACK_DIR=<T/test-runtime>`: **38 PASS**, source unchanged. Remaining
client/legacy-client/workflow/transport/smoke/platform suites and final
all/headless-all/verifier are **UNRUN after REPLAN**, not reused from the earlier
freeze. Live WORLD/HUD, two-client admission and movement isolation are unrun.
Smallest resolution: revise the inference/qualification decision in light of
the preserved low-bit transitions; no expansion of the mask was authorized.

Cleanup: full IPv4/IPv6, hosts/CA source/target, mounts and reverse maps match
baseline (`c-emulator-5554-restoration-check.json`). UID10021 again resolves to
Android media/download providers; UID10015 to Google services. Their Android
policy rules were preserved. Both emulators/stack and owned Frida are stopped,
the added forward removed, and all four owned runtime hashes unchanged
(`emulators-final.txt`, `processes-final.json`, `frida-cleanup.json`,
`owned-after.json`). No image/video use, gameplay-rule changes or commits.

## Selected-control entry execution — 2026-10-10

**SETUP/BLOCKED at LOCK IN; not a replan trigger or Day 3 completion.** Dispatch
`run-1791600566706-3174527e` replaces superseded whole-tree equality with the
authorized complete-tree/selected-control/full-ancestry/overlap qualification.
UI-only cap stays 4,096; gameplay cap stays 1,024 with unchanged gameplay body
and owner/navigation guards. Outside differences are permitted only when the
selected subtree/ancestry/region, root, screen and blocker inventory agree;
every permitted field difference is retained. Up to 20 complete candidate
pairs can settle before preparing a receipt; the final boundary cannot retry.

Here **S** is
`C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791600566706-3174527e/`.
`single-entry-03` and `single-entry-05` each performed four qualified menu
controls, three measured scrolls and Skye selection with the expected 1118
echo. The latter binds connection `3018772917584`, EID1500/slot0/team1, to the
explicit emulator5554 guest/listener; its 8 input receipts retain 30 allowed
outside differences. No lock gesture was sent. LOCK IN's descendant changed
flags at candidate qualification in the first run and at final revalidation
in the second (`76 → 204`); both refused SETUP with no further gestures.
`lock-in-final-boundary-diagnostic.json` and `entry-run-summary.json` retain
classification and maxima. The no-input follow-up `lock-readonly-pairs.json`
qualified 3/20 pairs (16 descendant refusals, one ancestry refusal), so it does
not meet the user's revised never-stable-ancestry REPLAN condition. Live work
stopped under the bounded-stage rule. New concrete evidence supporting a stable
final LOCK IN receipt is needed before another attempt. Ignoring those changed
descendants is not authorized by the current decision.

Routine repairs/self-review: exact observed retiring-menu labels are read-only
transition state, never an actionable fallback; identified size accessors are
fingerprinted and unknown bounds remain conservative; selected/descendant
settling and final-boundary refusal have separate regression tests. Cold-launch
attempt04 failed native Resume with zero inputs; attempt05 measured the native
MENU then reactivated the ordinary activity to establish Resume before entry.
No screenshot, guessed control, forced cast or gameplay change was used.
Post-draft build/shop close and Android sign-in-dialog handling remain
incomplete/unqualified. Two actual clients and the movement-isolation contract
are **UNRUN**; no implementation/fidelity claim follows from mocked passes.

Checks use external copied owned configuration:
`$env:HALCYON_STACK_DIR='<S/test-runtime>'`. Each `run_checks.py` command also
uses `--output <the listed new external directory>`.

| Command/procedure | Result | Artifact under S |
|---|---|---|
| `python -B Tools/run_checks.py --suite client` | 156 PASS, zero skips | `client-candidate-01` |
| Same runner `--suite workflow` | 40 PASS | `workflow-candidate-01` |
| Same runner `--suite transport` | 39 PASS | `transport-candidate-01` |
| Same runner `--suite smoke` | 74 run: 73 PASS, 1 skip (external VGR timing unavailable) | `smoke-candidate-01` |
| `--tests server.test.test_multiclient server.test.test_platform_fsm server.test.test_platform_identity` | 36 PASS | `platform-candidate-01` |
| `--tests server.test.test_nonvisual_entry server.test.test_nonvisual_classic server.test.test_nonvisual_movement` | 99 PASS after final code edits | `entry-pair-05` |
| Same runner `--suite legacy-client` | 291 PASS, zero skips; source unchanged | `freeze-legacy-client` |
| Same runner `--suite all` | 1,531 run: 1,503 PASS / 28 skips, zero failures/errors; source unchanged | `freeze-all` |
| `python -B Tools/run_scenarios.py --mode headless --scenario all --output <external>` | 7 PASS, byte-exact independent process pairs | `freeze-headless-all` |
| `python -B Tools/verify_sandbox.py --output <external>` | PASS: two 960-s runs; stream/state/checkpoints exact; max 32.0046 / 20.7234 ms, zero >50 ms | `freeze-verify-sandbox` |
| Live cold menu → qualified WORLD/HUD | FAIL SETUP at LOCK IN | `single-entry-01` through `single-entry-05` |
| Two actual clients / per-client native movement isolation | UNRUN | None |

An earlier focused invocation used the nonexistent module `test_classic_client`
and failed import; retained as `entry-pair-03`. Corrected invocation uses the
actual `test_nonvisual_classic` module and passes (`entry-pair-04`, then expanded
`entry-pair-05`). No failing assertion or skip was weakened to fix that typo.
The full discovery's 28 skips are reviewed in `reviewed-freeze-skips.json`:
27 require unavailable owned capture/corpus evidence and one requires Windows
symlink privileges. Those contracts remain unverified, not counted as passes.
All four sequential freeze commands exited zero (`freeze-exit-codes.jsonl`).
The final functional manifest matches the client/subset/full checks and pinned
headless/verifier sources. `final-source-review.json` records Python syntax and
configuration checks and byte-exact preservation of the gameplay observer body;
the added UI-only accessors do not change that body's owner/navigation checks.

Cleanup is **baseline-equal in this run**, unlike the earlier runs below:
`c-emulator-5554-restoration-check.json` passes full IPv4/IPv6 rule/policy
comparison, hosts/CA sources/targets/mounts and reverse mappings. The baseline
was taken after boot settling. Fresh `cleanup-uid-observation.json` again maps
UID10021 to Android media/download providers and UID10015 to Google services;
Android netpolicy allowlist rules were preserved, not deleted. Both emulators
and the owned stack are stopped, Frida/its forward removed, and all four owned
runtime input hashes unchanged (`emulators-final.txt`, `processes-final.json`,
`frida-cleanup.json`, `owned-after.json`). LDPlayer1 was never booted in this
dispatch. No commits.

## Revised entry execution — 2026-10-10

**BLOCKED (REPLAN): capacity accommodated; full-tree stability not qualified.**
Dispatch `run-1791599711016-5f09ca4c` continued the preserved worktree with the
operator's revised UI-only 4,096-node budget. Gameplay mode remains at 1,024
nodes and its owner/EID/navigation checks are unchanged. Added per-read
visited/active counts and native-monotonic duration, plus measured per-screen
maxima. Negative tests now exercise the production entry SETUP boundary for
focus/paused state, duplicate/stale/clipped/offscreen controls, mutation, failed
scroll progress, wrong/newest-other-guest binding, premature HUD and early lock.
The known MENU bridge after a bound draft opener is a read-only transition;
no MENU gesture is permitted there.

Here **R** is
`C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791599711016-5f09ca4c/`.
`live-pin-01.json` pins the same source for the stack and existing runner.
`single-entry-01` reached draft connection `2006190450000`, EID1500, slot0/team1,
after four qualified menu inputs and the observed successful `joinLobby` reply.
It failed SETUP before any Skye scroll: the complete pre-input tree changed in
four unrelated nodes. A no-input follow-up (`draft-stability-comparison.json`)
read the complete draft twice: **1,196 visited / 670 active**, **30.912 / 34.204
ms**. Root, labels and node identities agreed, but a non-text node's flags
changed **108 → 8940**, changing the full-tree signature. An earlier equal pair
during settling did not make this later action receipt stable. This meets the
explicit revised stability replan condition; no further functional/live work,
input retry or relaxed comparison followed.

The largest draft read was **1,210 / 678 nodes, 71.510 ms**, below the budget.
All stage maxima and a bounded subtree-scoped qualification option are in the
[entry record](solo-sandbox-scenarios.md#opt-in-nonvisual-entry--2026-10-10).
The option is not implemented: action-relevant ancestry/callback/clip stability
plus complete uniqueness/blocker enumeration would replace whole-tree equality
only under a revised decision.

Check command (external copied owned configuration):
`python -B Tools/run_checks.py --tests server.test.test_nonvisual_entry server.test.test_nonvisual_classic server.test.test_platform_fsm server.test.test_platform_identity server.test.test_multiclient --output <R/entry-focused-01>`.
**104 PASS**, zero failures/errors/skips; source unchanged during the check.
The prior candidate's broader suite results below are retained, not rerun or
relabeled as current-source passes. Current `--suite client`, `legacy-client`,
`workflow`, `transport`, `smoke`, and final `all` / headless-all / verifier gates
are **UNRUN after replan stop**. Live WORLD/HUD failed at SETUP; two actual
clients and movement isolation are **UNRUN**. Post-draft controls/sign-in-dialog
handling and remaining integration coverage are still incomplete.

UID10021 classification: guest Android9 package manager resolves the shared UID
to `com.android.providers.media`, `com.android.providers.downloads` and
`com.android.providers.downloads.ui`. `dumpsys netpolicy` records policy4
`ALLOW_METERED_BACKGROUND`, default background whitelist and power-save lists.
`uid10021-observation.json` retains commands/output. This is Android-managed
background-data allowlisting, consistent with
[netd's bandwidth controller](https://android.googlesource.com/platform/system/netd/+/refs/heads/android10-gsi/server/BandwidthController.cpp),
not our tagged routing rules (`guest_setup.ensure_firewall`). No Android-managed
rule was deleted. During cleanup, UID10015 also appeared after the early-boot
baseline: package manager maps it to Google Play services/framework/login/backup
transport, and netpolicy likewise records policy4/default allowlisting
(`cleanup-uid-observation.json`). These two known Android rule additions were
preserved, not removed to manufacture a baseline PASS.

Cleanup is complete for our routing: `c-emulator-5554-restoration-check.json`
passes hosts/CA source and target contents, mounts and ADB reverses.
`firewall-cleanup-differences.json` shows no removed baseline rules and no
Halcyon-tagged rules remaining. Full IPv4/IPv6 equality is explicitly **failed**
on the two preserved Android allowlist additions. Both LDPlayers and the owned
stack are stopped (`emulators-final.txt`, `processes-final.json`); Frida and its
forward were removed. `owned-after.json` verifies all four original input
hashes unchanged. LDPlayer1 was never booted in this dispatch. No commits.

## Entry execution checkpoint — 2026-10-10

**BLOCKED (REPLAN), not Day 3 completion.** Dispatch
`run-1791596543434-0bbf43bf` added an opt-in stage to the existing runner, a
UI-only production observer, fresh native-control/Java readiness receipts,
device/guest/wire correlation and per-device platform FSM isolation. No gameplay
rules changed. Runtime-copy `joinLobby` scripting followed an observed -32601
reply, rather than treating the prior missing answer as an assumed cause.
Owned answers/certificate/key/tape were not modified.

Decision 1 fixes UI traversal at 1,024 nodes / 4,096 UTF-16 units. The menu
reader runs without the owner and four controls were qualified, reaching one
explicitly bound draft connection. Stable-draft observation then failed the
node limit twice (`visited=1024; active=546`); no more inputs were sent. We did
not raise the limit or accept an incomplete tree. This contradicts sufficiency
of the prescribed bounded traversal, not owner independence. Replan the UI-only
draft qualification design/budget while preserving gameplay guards. Details and
remaining unimplemented/unqualified stages:
[entry record](solo-sandbox-scenarios.md#opt-in-nonvisual-entry--2026-10-10).

Here **E** is
`C:/Users/terasumi/AppData/Local/halcyon-evidence/run-1791596543434-0bbf43bf/`.
Evidence: `single-entry-05` (missing RPC answer), `single-entry-07` and
`live-pin-07.json` (pinned menu-to-draft attempt),
`single-07-draft-bound-diagnostic.json` (two no-input bound refusals).
Only LDPlayer0 was used in this dispatch; LDPlayer1 was never booted.

All following passes are **intermediate candidates**, not a final freeze:

| Command/check | Result | Artifact under E |
|---|---|---|
| `python -B Tools/run_checks.py --suite client --output <external>` | 138 PASS; later candidate 140 PASS | `prelive-client`, `entry-unit-04` |
| Same runner `--suite legacy-client` | 291 PASS | `prelive-legacy-client` |
| Same runner `--suite workflow` | 40 PASS, repeated after pin/config edits | `prelive-workflow`, `entry-config-workflow` |
| Same runner `--suite transport` | 39 PASS | `prelive-transport` |
| Same runner `--suite smoke` | 74 run: 73 PASS, 1 skip (external VGR timing unavailable) | `prelive-smoke` |
| Same runner `--tests server.test.test_platform_fsm server.test.test_platform_identity server.test.test_multiclient` | 35 PASS | `prelive-platform` |
| Same tests plus `server.test.test_nonvisual_entry` | 58 PASS | `entry-unit-05` |
| `--tests server.test.test_nonvisual_entry server.test.test_scenario_runner` | 46 PASS, before diagnostic-only JS error edit | `entry-unit-06` |
| Live cold menu → WORLD/HUD | SETUP failure; menu → draft evidence only | `single-entry-01` through `single-entry-07` |
| Two actual clients / movement isolation | UNRUN | None |
| Final `--suite all`; `run_scenarios.py --mode headless --scenario all`; `verify_sandbox.py` | UNRUN after replan stop | None |

Initial two Classic regression failures were fixed by retaining the shared
helper's existing output contract; later checks pass without weakened tests.
Review also fixed mode classification, per-device tokenless RPC state, actual
truncated wire-token identity differentiation, lock-admission revalidation and
source-pin inclusion. Remaining negative-test integration and post-draft gaps
are explicit in the entry record, not implied complete by mocked passes.

Cleanup: `owned-after.json` verifies all four owned input hashes unchanged;
`emulators-final.txt` / `processes-final.json` show both emulators and owned stack
stopped. Frida and its added forward were removed. Hosts/CA source and target
contents, mounts and reverses match baseline. **Full firewall equality fails:**
IPv4 and IPv6 each gained the unrelated rule
`-A bw_happy_box -m owner --uid-owner 10021 -j RETURN`, which was preserved.
`firewall-cleanup-differences.json` records that sole rule delta, no removed
baseline rules, and no remaining Halcyon-tagged rules. The original restore
refusal and final comparison failure are retained; no check was weakened to
claim full restoration. No commits or image/video use.

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

**Hygiene resolved (superseding the October 9 report):** `25db815` untracked
12 `.pyc` files and removed 9 historical PNGs. No image review was performed;
this is repository hygiene, not a release-qualified asset audit.

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

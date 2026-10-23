# Current implementation and validation status

## Unmodified physical Android — 2026-10-23

**One owned phone's transport and recorded-input replay PASS; not native
gameplay acceptance.** Unrooted Redmi Note 11 `af339028`, original Android CE
4.13.4/build 147219, official WireGuard, owned-domain public TLS: HTTP preauth,
HTTPS guest/session RPC, WebSocket notify, gateway, Skye draft/readiness and
WORLD transport were observed. No APK/OBB change, CA installation, root, client
hooks or image/video capture. Operator-assisted game menu entry supplied the
ordinary inputs; see the
[deployment evidence and containment limits](../Teardown/vainglory-community-ecosystem-tricks.md#owned-android-execution--2026-10-23).

The ~538-second recorded session was deliberately closed through ADB, then
replayed via the existing `Tools/run_scenarios.py --mode replay --journal ...`
path. Both independent seeds pass: **10,780 operations, 374 checkpoints,
54,488 events, final tick 9,855**; all six comparison artifacts are byte-identical
and every live anchor matches. Source remained unchanged throughout recording
and replay. Evidence:
`Local/evidence/phone-vpn-journal-1792731479464021600/replay/summary.json`.

The phone supplied 321 applied inputs, including 266 moves, 18 attack orders,
9 ground casts, 4 learns and 12 shop requests. Server acknowledgements cover
all 9 ground casts, 4 learns and 6 purchases; the other shop requests are not
automatically classified as gameplay regressions. Skye's one null-target
`1041/action 1` was **A cancellation**, acknowledged by `1045` plus `1093` and
an empty barrage state, not an unacknowledged new cast. Its existing production
regression test passes. Receive→apply latency: median 0.187 / p95 0.246 /
max 24.436 ms, not end-to-end client latency. Zero recorded send errors precede
`remove_client`; all 2,698 failed recipient events occur afterward during
shutdown. `semantic-audit-v2.json` retains these distinctions; its earlier
draft's wrong `1041` echo assumption is explicitly superseded.

This is not a natural completed match, 30-minute soak, independent fidelity,
or a replacement for native HUD/scalar WORLD guards. Fresh-guest UI, exact-client
bad-certificate controls, iOS, multiple VPN peers and remaining M5/M7 gates are
open. The game was closed for replay; the owned stack and VPN remain running.
No simulation changes or commits were made in this follow-up. The previous
round's 93 targeted platform/VPN tests are not a new full-suite qualification.

## M5 phase C live — 2026-10-21

**M5 step C PASS** — 2026-10-23. One CE plus five protocol participants; corrected conditions below.
`4m`–`4y`: composition/barriers and QUALIFIED_WORLD established; paced opponent/self-pick safety followed. Corrected acceptance is clean-disk-before-1060 and reconnect at exercise ≥75 s, strictly after engagement; own-stage ordering is evidence only.
`4z`: all-actor coverage/stale-target reset/staged wait gated; no staging/reconnect amid 252 holds (**inference:** partial-projection refusal of an offscreen neutral). Evidence: `Local/evidence/run-1792695520542-24d01817/`; earlier records retained.
`4aa`: conditions 1–7 PASS, pulse audit failed; null-size whole-clip transient remains **unresolved** (**inference:** countdown/header label). Evidence: `Local/evidence/run-1792697695633-24b8411f/`.
`4ab`: staging/reconnect/reciprocal effects and pulse audit PASS; CE exit 1, no resumed effect. **Inference:** sub-near all-projected neutral 100010 caused post-respawn pick holds. Evidence: `Local/evidence/run-1792713087386-c2329de8/`.
`4ac` — **2026-10-23**: H1 uses all-projected only with all four anchors at w≥n, otherwise F1 clipping/unknown refusal; retains hold camera. Pacing, world clearance and classifiers unchanged.
`4ac` gates: 642 module tests, smoke 73 + known VGR skip, transport 39, seven exact pairs and diff check PASS; pin `97cab2d55fad0410be61c2637cdcb0152cc31b39c1715a512f9480b84ec99dd4`.
`4ac` live conditions: 1 PASS, 2 PASS, 3 PASS, 4 PASS, 5 PASS, 6 PASS, 7 PASS, 8 PASS; ce_to_participant 8/2 before/after reconnect; participant_to_ce 9/3 before/after reconnect; 0 misfires; 1 boot(s).
`4ac` evidence and measured limits: `Local/evidence/run-1792714193636-6a7c91c5/REPORT.md`, `dispatch-acceptance.json`; cleanup/restoration and pre-doc source seal PASS.
Scope boundary: this proves only the recorded one-CE/five-participant exercise; not two CE, not a complete match, not long-duration stability, not independent gameplay fidelity. Remaining M5 gates stay open.
This authorized post-seal status edit changes the manifest; the seal proves zero tracked drift through the pre-doc seal, not equality after this edit.

## Workflow revision — 2026-10-11

The operator approved a revised workflow: one integration/runtime owner plus at
most one disjoint offline worker, per-change versus per-candidate gate cadence,
operator-assisted menu entry and protocol participants for the remaining slots.
The ordered list in the 2026-10-10 hand-off below (Live2 → secondary desktop) is
**superseded** by the [milestones](one-week-acceleration.md#workflow-revision--2026-10-11);
automated dual entry and secondary-desktop measurement are optional tooling.
Six-real-client acceptance remains deferred. No acceptance status changes with this entry.

**Milestone 2 PASS (server/session scope).** `Tools/protocol_participants.py`:
six wire-only participants (Skye/Catherine/Adagio vs Ringo/Gwen/Amael, slots
0/1/2 vs 3/4/5) pass draft/readiness with production defaults and each reach an
authoritative outcome for learn (`1078`→1082/1162), native cast (`1041/1042`),
move (1016), attack (1054), purchase (1085) and Recall; Skye reconnects with the
same identity. Evidence `Local/evidence/protocol-participants-cd784e2192ec44a482f89274dcdc7255/`.
This does not prove native-client behavior, complete kits or a finished match.

**Late-match deadline regression found and repaired.** The default verifier
failed the unchanged 50 ms gate twice on this source, once on a CPU-qualified
host (max 77.4 / 53.5 ms; `Local/evidence/halcyon-sandbox-verify-4ezdhojw/`),
dominated by wave-phase scans over retained minion history. `server/wave.py`
now uses live/spatial indexes preserving iteration order; profile 900–960 s wave
time 16.9→10.8 s, distance calls 5.31M→0.64M. Stream/state/checkpoint hashes are
identical to the failing run, and the qualified rerun passes (max 17.6 / 21.2 ms;
`Local/evidence/halcyon-sandbox-verify-i9ofyrwi/`). Retained objects are not
pruned; memory growth over 30 minutes remains an M3 measurement.

**Milestone 4 PASS (exact replay of a six-participant live session).** Opt-in
`server/input_journal.py` records application order inside `_apply_event`
(tick, sequence, uuid, EID, connection generation, payload, receive/apply
times) plus lifecycle transitions and live checkpoints; journal off leaves all
56 headless artifacts byte-identical. `Tools/run_scenarios.py --mode replay
--journal <path>` replays through production dispatch in two processes: 1,508
records / 93 checkpoints / 27,309 recipient events byte-identical and every
live anchor equal. Exclusions (wall-paced `1113`/`1116`, thread/lock/scheduler
fields) are listed with reasons in `Local/evidence/m4-run-1791739138078-replay-final/summary.json`.
Open for M3: receive→apply latency p50 17.8 / p95 534.8 / max 687.8 ms (72
inputs) and live socket tick work up to ~56–61 ms with or without the journal.
Candidate gates: `--suite all` PASS 1592 run / 1564 executed / 28 reviewed skips
(`Local/evidence/halcyon-checks-p17001r4`); CPU-qualified default verifier PASS,
max 19.2/18.6 ms, stream/state/checkpoint hashes unchanged from M2
(`Local/evidence/halcyon-sandbox-verify-40muyztg`, qualification
`Local/evidence/m4-verifier-cpu-qualification-20261012`).

**Milestone 3 PASS (natural wire-only match to crystal result, exactly replayed).**
New `Tools/protocol_observer.py` (s2c-only registry: `1010` EID at +8, `1035` slot
release, lifecycle, resource pools, progression, inventory, result; bounded frame
retention) and `Tools/protocol_policy.py` (team 1 pushes with waves, team 2 one
defender + two farmers; learn/shop/Recall; wait for `1074`). Two acceptance runs, each
`--self-host --full-match --journal --telemetry` with production defaults:
`Local/evidence/m3-run-1791742653262-live-1/` (291.2 s, team 1) and, after the
checkpoint encoder repair, `Local/evidence/m3-run-1791744282869-live-1/` (321.2 s,
team 1, 14 deaths / 13 revivals, 16 purchases, 46 learns, Adagio gen-2 reconnect with
ordinary readiness). All six streams observed `1106 → 1072 → 1009` (reason 0, result
120 ticks after the crystal). Replay `…-replay-1/summary.json`: 6,813 records / 328
checkpoints / 145,052 events, exact across seeds, live anchors equal, no new
exclusions. Gameplay receive→apply p95 27.6 ms / max 89.6 ms; peak RSS 100.7 MiB.
Gates: `--suite all` PASS 1613 / 1585 / 28 skips (`Local/evidence/halcyon-checks-yt0oe5m2`);
qualified verifier PASS max 27.0/18.6 ms, hashes unchanged
(`Local/evidence/halcyon-sandbox-verify-b0g0lz5g`).
**Open (blocks M7 soak):** live checkpoint work still grows ~3.8 ms per simulation
minute because canonical `wave_director` history retains dead minions (35 KB → 553 KB
in five minutes); server histories (`join_sequence`, `keepalive_ticks`, buff
allocations, interruption serials) are also unbounded. Seven non-checkpoint live
ticks > 50 ms are attributed in `Local/evidence/m3-run-1791744282869-report/report.md`.

**M7 preparation: bounded server histories and a separate-process host. M7 is not
claimed.** Dead wave minions are pruned after the ordinary corpse/`1035` removal.
Removed-EID interruption serials are forgotten. Production buff/shop allocators
validate against a monotonic high-water mark. Join/keepalive diagnostics keep the
latest 256. Probe and journal lists stream to disk. The scenario harness, not the
server, now retains despawned-minion evidence; its classifications and thresholds
are unchanged. `Tools/protocol_participants.py --self-host --server-process`
(`Tools/protocol_host.py`) runs the production gateway/match in a child process
with PID/source/readiness receipts. This removes participant GIL contention from
live tick timing.

One 30-minute soak ran with six participants on a defend/farm workload: live
minions 4–100, 23 hero and 63 neutral deaths, Adagio gen-2 reconnect, and no
structure orders (stability only, no natural result). Evidence is in
`Local/evidence/m7-run-1791751582054-soak-1/`. Its replay is exact: 38,391
operations, 1,390 checkpoints, 1,027,103 events (`…-replay/`).

**Residuals remain open for M7 attribution**
(`Local/evidence/m7-run-1791751582054-report/report.md`):
- checkpoint work is +0.069 ms/min after minute two with live minions held fixed
  (95% CI excludes zero), and ≈0 when canonical state size is held fixed;
- server RSS is +0.17 MiB/min;
- six ordinary ticks exceed 50 ms (max 62.4 ms). No periodic checkpoint tick
  exceeds 50 ms (max 40.0 ms).

Gates: `--suite all` PASS, 1638 run / 1610 executed / 28 skips
(`Local/evidence/halcyon-checks-42d_e7em`). An earlier run on this candidate
failed on a stale history assertion and on a venv-launcher PID mismatch; both
were fixed without loosening the guard (`…/halcyon-checks-wtm03m_f`). The
CPU-qualified default verifier passes: max 23.8/21.5 ms, zero ticks over 50 ms,
identical across runs (`Local/evidence/halcyon-sandbox-verify-yg5dkfl5`,
qualification `Local/evidence/m7prep-verifier-cpu-qualification-20261012`). The
stream hash `210800b1…` is unchanged. State/checkpoint hashes changed
(`69d2193a…`/`7135c875…`) because pruned corpses leave canonical state. This is
an expected canonical difference, not a wire change.

Disk note: D: had about 1 GB free. Existing `Local/evidence` was NTFS-compressed
in place (about 3:1); nothing was deleted.

## Entry checkpoint — 2026-10-10

**Session hand-off (operator ended the day after rev8).** Committed state:
desktop-independent entry (no host activation; owned window only needs to be
non-minimized), framework quiet-window and CPU-qualified verifier guards, the
read-only `DRAFT_WAIT` classifier, and the corrected single same-PID guest
HOME→owned-activity recovery after cold launch. Pre-commit checks: smoke
PASS/1 reviewed skip and client PASS, plus the rev7 full-discovery, headless and
verifier results below (source manifests unchanged since then). Next session,
in order:
1. Live2 with the corrected cold-launch recovery on the current desktop
   (LDPlayer windows non-minimized; operator keeps working), then Live3.
2. Secondary virtual desktop measurement only when a desktop2 target exists:
   either the operator creates and keeps it, or the operator authorizes the
   worker to create it without switching. Rev8's helper provenance is retained.
3. Day 7 (six actual clients) stays deferred by the operator.

**Current rev8: BLOCKED (REPLAN), secondary desktop absent.** Registry and
read-only COM enumeration on build26200.9457 both report only desktop1
`3dd72074-ede1-4370-8bcb-5677601417c1`; the specified secondary target
`4bf7a1f3-20bb-45ad-a0c8-88bcd27801e2` is missing. Active desktop is unchanged.
Measurement NOT QUALIFIED at SETUP preflight; window movement support and
client behavior remain untested, not proved unsupported. No emulator/stack/
Frida startup, desktop/window mutation or secondary-driver option. Live2/Live3
remain UNRUN. See [rev8 evidence and corrected cold-launch recovery](solo-sandbox-scenarios.md#rev8-secondary-desktop-preflight-blocked-target-desktop-absent).

**Earlier rev7: Live2 SETUP/BLOCKED before input; Live3 UNRUN.** The entry
path no longer activates or requires host foreground: it qualifies the owned
window's executable/PID and non-minimized state, permits one nonactivating
restore, and retains shared input ownership plus every guest/native guard.
Rev6's read-only DRAFT_WAIT work is preserved.

Both emulators booted without observed foreground takeover. Android frameworks
qualified 63.390/62.113-second quiet windows with boot_completed=1. A's one
60-second-timeout `am start` returned in0.295 seconds. Of47 pre-attach samples,
44 had its activity resumed (PID4297), but none had native `Resume - Post`;
initialization remains UNKNOWN. No Frida attach or gesture occurred. B's game
was not launched because A never reached the draft hold. Background PLAY
consumption, reciprocal client liveness, dual HUD and Live3 remain UNRUN—not
failed input or a gameplay regression. No REPLAN trigger was observed.

Both full guest baselines are restored, emulators/stack stopped, Frida never
started, and four owned hashes unchanged. Client187, workflow44, transport39
and platform36 PASS; smoke73 PASS/1 reviewed skip; full discovery1538 PASS/28
reviewed skips. Seven exact headless pairs PASS, independent reference
UNAVAILABLE. The once-only default verifier also PASS: exact2×960 s,
38,400 ticks, maxima21.1525/33.1944 ms and zero ticks over50 ms. Its pre-run CPU
guard qualified60.735 seconds <=20% after about7.1 minutes/77 samples, within
the30-minute bound. All final unit/simulation manifests match current source.
The earlier rev6 FAIL remains historical; no threshold, priority or measurement
method changed. Other workloads were neither stopped nor blamed.
See [rev7 procedure/evidence](solo-sandbox-scenarios.md#current-rev7-desktop-independent-entry-pre-attach-native-readiness-blocks-live2)
and [rev7 checks](one-week-acceleration.md#shared-desktop-execution--2026-10-10-rev7).
Rev8 clarifies that exactly one same-PID guest HOME→owned-activity return is
allowed after the cold launch when native Resume is absent; retain >=3 ready
samples and stop on PID change or missing readiness. Rev7 did not attempt it.
Accepted rev4
Live1 remains historical; full client/fidelity acceptance is still open.
No images/video, gameplay-rule changes or commits.

### Earlier rev6 idle-desktop rerun

**Earlier rev6: Live2 SETUP/BLOCKED; Live3 UNRUN; deadline gate FAIL.** Starting from
`8f5fdd6` with the desktop idle, A reached the Skye draft hold through eight
qualified inputs and explicit guest→connection→EID binding. B's initial
activity launch timed out; its Android SystemUI/Phone/GMS/ExtServices had
framework ANRs, with no game PID, Frida attach or input. No foreground-loss
failure occurred. A's admission guard timed out without LOCK IN; later server
pick-timeout finalization is not accepted admission. Both-client HUD, opposite-
team admission, reciprocal liveness and Live3 remain unverified.

An evidence-required read-only `DRAFT_WAIT` classifier handles the first
attempt's waiting-roster state; it authorizes no gesture and preserves two
settled ordinary DRAFT reads plus all existing control guards. Client175 PASS.
Partial background evidence:192 B-foreground samples found A unpaused and
initialized, with642 bound server1113 records; heartbeat/ack and reciprocal B
measurement remain unavailable. The next prerequisite is healthy LDPlayer1
framework startup, not another desktop-focus bypass.

Both guest baselines are restored; emulators, Frida and stack stopped; four
owned runtime hashes unchanged. Unit gates pass: client175, workflow40,
transport39, platform36; smoke73/1 reviewed skip; full discovery1522/28 reviewed
skips. Seven exact headless pairs pass. The once-only verifier matches both
960-second runs exactly, but **15 ticks exceed50 ms**: maxima167.8896/31.7241 ms.
Pre-run CPU40/34/54% means idle-host qualification was not achieved. The maximum
row is host/scheduler-stall **inferred**, not a proved cause or a waived deadline.
No threshold change or rerun. See [rev6 evidence and limits](solo-sandbox-scenarios.md#earlier-rev6-a-reaches-the-draft-hold-b-framework-startup-blocks-live2)
and [rev6 checks](one-week-acceleration.md#idle-desktop-rerun--2026-10-10-rev6).
Accepted rev4 Live1 remains historical; full gameplay acceptance stays open.
No images/video, gameplay-rule changes or commits.

### Earlier rev5 host-input result

**Earlier rev5: Live2 ordinary SETUP/BLOCKED; accepted rev4 Live1 retained.**
Dispatch `run-1791609724221-29dd246d` implements shared host-input ownership
receipts, pre/post-gesture focus checks and measured pre-attach readiness.
A passed the readiness guard and sent one qualified PLAY, then Chrome gained
foreground; the new guard stopped input and released the lock. B never booted.
The cause of that external focus change is unknown; a desktop interval without
external foreground changes is needed. No dual draft/HUD, reciprocal background
liveness or movement isolation was qualified. This is not a gameplay regression
or a triggered background-suspension REPLAN. All native/rev4 leaf guards remain.

Final-source checks: client172, legacy291, workflow40, transport39 and platform36
PASS; smoke73 PASS/1 reviewed skip. Full discovery: **1519 executed PASS /28
reviewed skips**. Seven exact headless pairs and two960-second verifier runs
PASS, all38,400 ticks below50 ms (max27.3683/49.9362 ms). Current source matches
all final unit manifests and both simulation pins; independent reference remains
UNAVAILABLE. Offline checks do not close the live acceptance gaps.
Both emulators, Frida and stack stopped; A's full guest baseline restored and
four owned runtime inputs unchanged. See [rev5 evidence and scope](solo-sandbox-scenarios.md#earlier-rev5-ownership-guarded-external-foreground-loss-blocks-live2)
and [current check table](one-week-acceleration.md#host-input-ownership-execution--2026-10-10-rev5).
No image/video work, gameplay changes or commits.

### Earlier rev4 accepted single-client result

**Earlier rev4: Live1 single-client WORLD PASS; Live2 SETUP/BLOCKED.** Dispatch
`run-1791605229771-8926354d` implements the authorized strict-descendant,
eventless/textless-leaf flags exception, with exact `0x1C` and input-bit guards.
Every permitted difference is recorded as UNCLASSIFIED, never inferred opacity.
One cold-menu run qualified Skye selection, LOCK IN (1123/native LOCKED), full
load/WORLD handoff and native HUD. Two-client work stopped at host focus and
repeated Android process-startup preparation failures, before dual draft/HUD.
This is an ordinary bounded setup blocker, **not a rev4 REPLAN trigger**.
Movement isolation is unrun and its extension remains undone; no Day3 or
independent gameplay-fidelity acceptance is claimed.

Final checks: client163, legacy-client291, workflow40, transport39, platform36
PASS; smoke73 PASS/1 reviewed skip. Full discovery: **1510 executed PASS / 28
reviewed skips**. Seven headless pairs and two960-second verifier simulations
match exactly; every tick meets50 ms (max21.6946/20.6932 ms). Details are in the
[rev4 check record](one-week-acceleration.md#leaf-flags-entry-execution--2026-10-10-rev4).
Both guests' full routing/hosts/CA/firewall/reverse baseline comparisons pass;
both emulators, Frida and stack are stopped, four owned runtime inputs unchanged.
See [receipts, maxima, exact blockers and evidence](solo-sandbox-scenarios.md#earlier-rev4-single-client-world-passed-dual-setup-blocked).
Further live work needs a measured stable cold-launch lifecycle and qualified
dual-driver foreground ownership. Changes are uncommitted; no image/video work.

### Earlier rev3 inference attempt

**BLOCKED (REPLAN), rev3 inference contradicted.** Dispatch
`run-1791604424986-0a47aa99` collected 60 complete, no-input DRAFT reads before
enabling any animation exception. The corresponding eventless/textless LOCK IN
descendant changed flag **bit0**, not only bits7–14: low bits `0x4C → 0x4D →
0x4C`, cumulative change mask `0x7F81`. Rev3 rule3 explicitly requires replan
for this evidence. No flag tolerance or LOCK IN gesture was applied.

Focused observation-stage checks: **38 PASS**. Requested animation-rule tests,
full suites and freeze gates are unrun after the mandated stop; the earlier
green results below are historical. WORLD/HUD, two actual clients and movement
isolation remain unverified. Both emulators/stack/Frida are stopped, complete
guest baseline comparisons pass, and all four owned runtime files are unchanged.
See [series, per-node changed fields/bits and measured maxima](solo-sandbox-scenarios.md#earlier-rev3-animation-inference-contradicted--blocked-replan)
and [rev3 execution](one-week-acceleration.md#animated-descendant-inference--2026-10-10-rev3).

### Earlier selected-control pair attempt (rev2)

**SETUP/BLOCKED at LOCK IN; acceptance remains OPEN.** Dispatch
`run-1791600566706-3174527e` implemented the revised control/ancestry/overlap
pair contract with complete 4,096-budget reads and fully recorded outside
differences. Two runs qualified menu entry, three measured Skye-list scrolls
and server-echoed Skye selection. Neither sent LOCK IN: a protected descendant
changed flags, including `76 → 204` at the final pre-gesture boundary. A bounded
read-only follow-up qualified 3/20 pairs, so this is **not** the revised
never-stable-ancestry replan condition. No flags or failed checks were dropped.
WORLD/HUD, two actual clients and movement isolation remain unverified/unrun.

Final-code checks: client **156 PASS**, legacy-client **291 PASS**, workflow
**40 PASS**, transport **39 PASS**, smoke **73 PASS / 1 reviewed skip**, platform
FSM/identity/multiclient **36 PASS**. Sequential freeze: **1,503 executed tests
PASS / 28 reviewed skips**, seven exact headless pairs, and two exact 960-second
verifier runs. Every tick met 50 ms (max **32.0046 / 20.7234 ms**); source pins
match the final code. These offline passes do not close the live entry blocker.
See [qualified-entry evidence](solo-sandbox-scenarios.md#opt-in-nonvisual-entry--2026-10-10)
and [current execution/checks](one-week-acceleration.md#selected-control-entry-execution--2026-10-10).
Both emulators/stack and owned Frida are stopped. All guest routing, firewall,
hosts/CA and reverse-map baseline comparisons **PASS** in this run; classified
Android UID10021/10015 policy rules were preserved. Four owned input hashes
are unchanged. Changes remain uncommitted; no image/video work occurred.

### Earlier full-tree equality attempt (superseded decision)

**BLOCKED (REPLAN); acceptance remains OPEN.** Revised dispatch
`run-1791599711016-5f09ca4c` raised only UI-mode traversal to 4,096 nodes and
measured every completed read. Draft fits (maximum 1,210 visited / 678 active,
71.510 ms), but full-tree equality fails during pre-input qualification and
again in a bounded consecutive-read comparison (1,196 / 670 both reads).
Zero draft gestures were sent. This triggers the revised stability replan;
no mutation guard was weakened. Focused checks: **104 PASS**. WORLD/HUD,
two actual clients, movement isolation and final all/headless/verifier gates
remain unverified/unrun. See [entry evidence and subtree option](solo-sandbox-scenarios.md#opt-in-nonvisual-entry--2026-10-10)
and [revised execution](one-week-acceleration.md#revised-entry-execution--2026-10-10).

Both emulators and stack are stopped; four owned input hashes are unchanged.
Our guest routing is restored, with no Halcyon-tagged rules remaining. Full
IPv4/IPv6 baseline equality retains two classified Android-managed allowlist
additions: UID10021 (media/download providers) and UID10015 (Google services).
Hosts/CA/mounts/reverses match baseline; Android policy rules were not deleted.

### Earlier attempt, before the UI-only budget revision

The opt-in owner-independent
nonvisual reader qualified four menu controls and reached a device-bound draft
connection, but stable draft exceeds Decision 1's unchanged 1,024-node limit
(two bounded reads: 1,024 visited / 546 active). No partial-tree acceptance or
budget increase was used. WORLD/HUD, two actual clients and movement isolation
remain unverified; final all/headless/verifier gates were not run after the
replan stop. See [entry contract](solo-sandbox-scenarios.md#opt-in-nonvisual-entry--2026-10-10)
and [measured results](one-week-acceleration.md#entry-execution-checkpoint--2026-10-10).

Partial tool/platform changes and evidence are preserved, uncommitted. Both
emulators and the local stack are stopped; four owned runtime inputs are
hash-unchanged. Hosts/CA/mounts/reverses match baseline and no Halcyon firewall
rules remain. Full IPv4/IPv6 baseline equality remains **failed** due to one
preserved unrelated `bw_happy_box` UID10021 rule; cleanup is not reported as a
blanket PASS. The October 9 results below remain historical, not final-source
qualification of these changes.

## Execution checkpoint — 2026-10-09

**Acceptance remains OPEN.** The [dated acceleration checkpoint](one-week-acceleration.md#execution-checkpoint--2026-10-09)
and [coverage matrix](week-one-coverage-matrix.md) distinguish declared composition,
headless/native contracts and actual-client qualification. The October 4 red
audit remains in the acceleration leaf; later green runs are not evidence that
its historical 255-ms outlier was repaired.

Fresh discovery (`bda39c2`) passed 1,470 tests / 28 reviewed skips, seven exact
headless pairs, and the 960-second verifier (max 21.4335/22.3473 ms; zero >50 ms).
Evidence root: `C:/Users/terasumi/AppData/Local/halcyon-evidence/`, prefix
`discovery-run-1791562480510-fac7cde6-`, suffixes `all`, `headless`, `verifier`.
The verifier is a **remeasurement, not an attributed repair**. The dispatch's
Day 1 repair checks pass (legacy-client **291**, client adapters **119**, zero
skips); full measured fixture equality and diagnostic behavior are unchanged.
The minion sampler's accumulated cadence drift was reproduced and repaired
without changing comparison margins or causal/identity/continuity negatives.
Day 2 offline checks pass: seven exact headless pairs, a baseline-identical
verifier pair (max **21.7158/21.1300 ms**, zero >50 ms), and the expanded native
aggregate grid (**901 cases**, decimal deltas retained, not rounded away).
The selected post-repair native movement effect remains a classified unknown.

**Day 3 is SETUP/BLOCKED.** Both actual LDPlayer instances passed build 147219
and local routing checks and focused the game, but neither established a WORLD
connection. Both existing nonvisual-runner attempts refused with zero gestures.
Nonvisual menu-to-WORLD entry in the existing driver is the missing capability;
opposite-team PvP and its native effects were not tested. No Day 4 match was
attempted. Guests were restored, both emulators/stack stopped, and original
configuration hashes verified unchanged. Evidence and final sequential freeze
gate locations: [execution results](one-week-acceleration.md#execution-results-and-final-source-gate-locations),
root `run-1791564257036-9a4bad79` under the evidence directory above.
The tracked-bytecode/PNG hygiene decision was resolved by `25db815`: twelve
bytecode files were untracked and nine historical PNGs removed. No image review
was performed. Complete faithful PvP, independent gameplay fidelity,
long-run native movement/stability and six-actual-client delivery remain open.

## Retained migration measurements following the 2026-10-04 audit

**Acceptance remains OPEN; no complete faithful-gameplay or PvP claim.**
The active operating plan is [the one-week acceleration workflow](one-week-acceleration.md):
one owner/no delegation, CPU/native-first RE, focused production regression,
targeted nonvisual client evidence, then full freeze/release gates. Seven days
is a timebox, not a guarantee of 100% gameplay. No emulator/client was launched
in this audit; the process IDs and “running” state in older entries below are
historical observations, not a current service-health report.

The full discovery test suite is **1,470 tests, 0 failures, 0 errors, 28 skips, 781.250 seconds** (PASS).
The legacy client fixture migration passed `--suite legacy-client`
(**284/284 tests PASS**, 715.810 seconds); discovery retained causal/identity/
continuity negatives but found an upgrade-before-declaration-refusal gap.
The smoke lane passes 71 tests (70 non-skipped, 1 skipped) in 10.901 seconds.

**Seven production headless scenarios pass**, byte-exact across two independent
seeds on one source pin (`Tools/run_scenarios.py --mode headless --scenario all`).
The long verifier (`Tools/verify_sandbox.py`) runs two independent 960-second workers
(38,400 ticks total), matching event stream, canonical state, and checkpoints byte-for-byte,
and **meets the 50 ms deadline gate on every tick** (Run 1 max 22.65 ms, 0 over 50 ms; Run 2 max 30.15 ms, 0 over 50 ms).

The executable original ARM64 health-helper pilot covers 885 cases / 1,770 native
executions, with 883 exact numeric comparisons to the production pool kernel.
These retained checks do not by themselves close Day 1 or attribute the old
deadline failure. The dated checkpoint above supersedes that earlier closure
claim; Day 2 covers shared movement/pools and overload attribution before
actual two-client synchronization and match lifecycle acceptance.

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

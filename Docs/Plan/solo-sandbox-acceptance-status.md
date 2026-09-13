# Seven solo sandbox acceptance gates

Current overview: [September 13 status report](current-status.md). Overall
acceptance remains **OPEN**. Later Skye C threshold/order repairs have focused
and headless evidence; the September 12 client records below predate those
repairs and do not establish their rendered acceptance. Preserve the distinction
between accepted fixture execution, reviewed visuals, compared trial pairs and
independent fidelity when reading the dated records.

Updated 2026-09-12 with the parent-reviewed state through the ckpt13corr20
round. **Current overall status: OPEN.** The latest accepted engineering work
is the declared-fixture gate: reviewed validators reject missing or
contradictory identity, teams, prepared resources/ability points, declared
levels/ranks/points, placement and required record fields instead of reporting
false PASS, and the 2026-09-12 live runs are the first evidence produced
through it. A passed twice inside **one** match; B and C passed twice each on
two separate fresh matches. Effect-total agreement within a stage is a
same-implementation observation, not a passed compare-pair contract;
presentation is captured but unreviewed, and no independent reference fixture
exists (`UNAVAILABLE`). Minion survivor-to-structure acceptance is a finite
negative in all three bounded live observation windows (two 35 s and one
60 s); independent fidelity
remains open. The 2026-09-11 "quota-blocked / diagnostics partially
implemented" statements are superseded — that work was completed by the
checkpoint series and exercised live (see the rendered-client update below).
See [the current scenario status](solo-sandbox-scenarios.md) for the
consolidated record. The operator-defect evidence below retains its original
dates.
**Status on 2026-09-08 operator defects:** The operator disproved an earlier
overly broad completion claim: Skye had no kit, basic projectiles lacked
visible bullets, and minion movement halted after spawn.
On 2026-09-09, defect repair and verification proceeded on our
unchanged owned Android client against the local authoritative server:
- **Gate 2 (Basic attacks)**: Closed for repaired mechanics — Skye basic attacks emit native `1037` targeted projectile creation with alternating LeftGun (`0x77b4b72a`) / RightGun (`0xb1ab2985`) sockets and kind 108 (`0x6c`), with visible bullets and impact flashes documented via resampled illustrations (fps10 extracted frames 49, 50, 57, 79 from original 11.7fps 30s `skye-basic-attacks.mp4`). Ranged minions emit kind 79 projectiles. Unrecovered visual profiles for other heroes remain an honest limit; native perfect fidelity for all heroes is not claimed.
- **Gate 3 (Abilities)**: **OPEN/PARTIAL**. Original Skye upgrades are repaired; real `1078`/`1082` upgrade handshake is verified live for A, B, and C in trace `wire-1788942557949012000.jsonl` (A at `1788942770.4508677` / `1082` at `.452012`, B at `1788942803.1498234` / `1082` at `.151304`, C at `1788943185.216853` / `1082` at `.226975`). In the subsequent trace `wire-1788947055923739400.jsonl` (connection `2607844752976`): A Forward Barrage `c2s 1042` (action 0) at `1788948535.097593`, `1046` at `.149051`, `1162` tag `43a890d8` at `.1494656`, outgoing `1054` victim `1517` / attacker `1500` −25.82 at `8535.1962216` and `.287958` (~22 min, via real ADB UI, QA prepared positions only). B Suri Strike `c2s 1042` (action 2) at `1788947918.1802444`, `1046` at `.1824353`, `1162` tag `46a89591` at `.1828282`, `1054` damage −232.686 at `7918.8148913` and −46.537 at `.9327095`. C Death from Above `c2s 1042` (action 4) at `1788947922.5289133`, `1046` at `.5424192`, `1162` tag `45a893fe` at `.5440266`, repeated outgoing `1054` −21.153 beginning `7923.7736433`. Bounded A/B/C operations and authoritative damage are verified. Repeatable gameplay acceptance, native trajectory/smoothness, C reconnect actor recreation, and independent official fidelity remain **OPEN**. Roster kit limits (10 implemented heroes) remain explicit boundaries.
- **Gate 5 (Waves/turrets)**: **OPEN/PARTIAL**. Continuous `1016` movement order re-issuance was verified (16–22 orders/actor across first 25s in `wire-1788894917131102000.jsonl`; 2557 order snapshot in `wire-1788942557949012000.jsonl`), providing smooth locomotion and ranged firing from behind melee. Short operator recordings illustrate directed locomotion: fresh 30s `skye-basic-attacks.mp4` and 45s `skye-combat-verify.mp4`. The older `halcyon_gate5_wave.mp4` is a >2-minute recording with separate provenance. Late-match wave accumulation was observed in botless runs; whether it represents an abnormal defect versus expected backlog requires reference-backed evaluation. The `wave.py` targeting-guard modification was **reverted** by its own worker; a new 17-line regression in `server/test/test_wave_sandbox.py` now protects this (76 focused wave/structure tests pass in 1.906s, `wave.py` is at clean HEAD). The earlier wave-only 110→87 comparison omitted production nav/turret steps and is not a production buildup fix. Gate 5 remains open pending reference-backed repeatable gameplay acceptance. Continuous `1016` repair is already in HEAD.


This checklist follows section II of the operator's original Tier 1 brief.
It distinguishes the seven requested manual scenarios from additional fidelity
and hardening work retained in the subsystem leaves. QA may prepare resources,
positions and incoming statuses; the actual client action and its resulting
behavior still supply the acceptance evidence.

**Rendered-client validation update 2026-09-11:** the lost corpus tape was
RECOVERED byte-faithfully — the `vg_max/` corpus and its extraction scripts
had survived (the earlier "destroyed" claim was a shallow-lookup error);
`Tools/build_world_tape.py` rebuilds `world_tape.bin` and the production
loader digest matches its pinned SHA exactly. With the recovered tape the
client rendered and played. Individual Skye A/B/C operations and damage
were observed live, including a reviewed kill video, but those executions
do not establish controlled comparable pairs. The early A totals mixed
basic hits into skill attribution and were superseded; corrected B runs
recorded 4/4 missile hits, and C recorded 20/16 pulses, with drifted starting
states. Fresh-match pairs and their native presentation review remain open.

**Declared-fixture gate update 2026-09-12:** the drift described in the update
above is gone. With a per-stage declared fixture profile the gate pins the
measured
pre-input state (level, ranks, ability points, full HP/energy policies,
teleport placement) before any gesture. A passed twice inside **one** match
(both records: `pid 23684 startup 1789171203.113506`, connection
`1677315684560` — two attempts, not two fresh matches; the earlier separate A
match was refused at `SETUP` before input). B and C passed twice each on **two
separate fresh matches** (B connections `2148944721232` / `2148950881488`; C
connections `1745004052816` / `1745004065360`, in the level-6 window where the
legal QA learn grants zero XP and zero points). Within each stage the effect
totals repeat (A −554.187, B −113.1417, C −361.8338, with byte-identical
damage payloads) — a same-implementation observation, **not** the compare-pair
contract, **not** a determinism proof, **not** official fidelity. Presentation
remains unreviewed; each stage declared one ability slot only (A, then B, then
C, in different matches) — that is not an ownership proof, and the ownership
question stays open as the chronological network `1016` movement-slot
assignment/release to entity identity: a `1016` move frame carries a slot and
the owner the record attributed to it, but no `1010` assignment or
`1035`/`1073` release publication is carried in the preserved records, so the
binding cannot be shown from them (`slot_ownership.status` `UNVERIFIED`). C's
publication-to-pulse causality is also not proven; the QA teleports used for
placement are QA preparation, not read-only observation.

Later minion windows tracked both teams and established approach plus
opposing combat, superseding the initial `INCOMPLETE_MOVEMENT_ONLY`
observations. The earlier survivor counts were withdrawn because they
included nonparticipants. Proven post-combat survivor resumption and
subsequent structure interaction remain incomplete.

**Minion finite negatives 2026-09-12:** three live observation windows — two
at 35 s declared (two fresh matches, corr17) and one at 60 s declared (one
fresh match, corr20) — all ended in
the same honest FAIL — `SURVIVOR_RESUMPTION`, `STRUCTURE_INTERACTION` and
`AUTHORITATIVE_EFFECT` `NOT_OBSERVED`, with 163 / 163 / 267
minion-vs-minion events, 14 / 14 / 24 deaths and zero structure hits. The
60 s window's census shows why: the last ranged pairs closed to their 6.5 u
standoff and destroyed each other mutually, and for each of the 26 combat
participants the carried engagement-end instant and the actor's own death fall
inside one census interval, so **zero contiguous observed-alive samples follow
any participant's own engagement end** (of the 40 tracked actors, none shows a
qualifying run). That is what makes `SURVIVOR_RESUMPTION`
`NOT_OBSERVED` in the measured interval; it does not say zero minions survived
(one further pair died 2.9 s after the last census sample, world ≈
110.64/110.65, and later play was not observed). These are finite
negatives for their windows only — no claim about later play; the trace
carries no target field, so geometric proximity stays a diagnostic.

Crash classes are separate: missing/synthesized-tape WORLD-entry faults,
a draft-time abort, and later roughly 30-minute idle WORLD crashes
(fault 0x38) after tape recovery. The latter remains an open production
lead. Evidence is preserved under `%TEMP%/halcyon-client-live-20260910/`;
see [the detailed corrected record](solo-sandbox-scenarios.md). Gate 3
gains individual live A/B/C observations; repeatable controlled acceptance
remains open. Driver defects
found by live execution and fixed with tests: QA mailbox timeout clamp,
trace-history reads, fresh-connection enforcement, client-controlled-Skye
identity, placement/readiness strictness, adaptive enemy-bar aiming,
capture lifecycle, failure-evidence retention, and the damage
classification poll/pairing race.
The recorded full suite passed **898 tests in 160.809 seconds (2 skipped, exit 0)**
on 2026-09-11, AFTER the `wave.py` targeting-guard revert, its new regression, the
scenario pilot (`Tools/run_scenarios.py`, `Tools/scenario_client.py`, the
client-driver fixes from the live executions, and the documentation changes). The complete output is external at
`%TEMP%/halcyon-scenario-pilot-20260911-final/full-suite-20260911.log`; `git diff --check`
exits 0 on the same worktree. This count is evidence of that worktree state, not a
definition of current faithful gameplay. The earlier
960-second pair provides an earlier source pin only. Historical 758-test /
960-second replay pins represent an earlier source baseline prior to operator
Skye defect testing, not current-source verification. See [the main plan](solo-sandbox.md#local-verification)
and [performance record](solo-sandbox-performance.md#final-verified-acceptance-pair-2026-09-08).

| Gate | Requested manual scenario | Recorded live evidence |
|---|---|---|
| 1. Navigation — 15% | Route around a jungle wall; stop immediately under knockback or stun. | **The bounded matrix scenario is met:** Catherine's real wall detour and [Gwen's moving-STUN stop](solo-sandbox-live-acceptance.md#2026-09-08-moving-gwen-stops-under-three-second-stun) are measured. Actual move line `56730` precedes STUN22 line `56811`, tick `22460`/time `1123`. No further position or movement input occurs before Victory; expiry is not automatic resumption. |
| 2. Basic attacks — 15% | Target a minion, move as the projectile releases, and retain the hit while moving smoothly. | **Verified live (2026-09-09):** Skye basic attacks emit native `1037` projectile creation (`LeftGun 0x77b4b72a` / `RightGun 0xb1ab2985`, kind `108`, float `0.0`) at release before `1054` hit; resampled fps10 illustrations (frames 49, 50, 57, 79 from original 11.7fps 30s `skye-basic-attacks.mp4`) isolate glowing in-flight bullets, muzzle flashes, and impact ticks. Ranged minions emit `1037` kind `79`. Prior [Celeste stutter sequence](solo-sandbox-attack-actions.md#celeste-minion-stutter-acceptance-2026-09-08) confirms release commitment and retreat motion. Other hero projectile kinds remain unrecovered; native perfect fidelity for all hero profiles is not claimed. |
| 3. Abilities — 20% | Show line, cone, delayed ground area and vector dash; spend energy, block a cast at zero energy, and interrupt a channel with stun. | **PARTIAL/OPEN (2026-09-09):** Skye A/B/C upgrades verified in `wire-1788942557949012000.jsonl`. In subsequent trace `wire-1788947055923739400.jsonl` (connection `2607844752976`): A `c2s 1042` action 0 at `1788948535.097593` with outgoing `1054` −25.82 at ~22 min; B `c2s 1042` action 2 at `1788947918.1802444` with `1054` damage −232.686 and −46.537; C `c2s 1042` action 4 at `1788947922.5289133` with repeated `1054` −21.153. All casts via real ADB UI; QA prepared positions only. Bounded A/B/C operations and authoritative damage verified. Repeatable gameplay acceptance, native B trajectory/smoothness, C reconnect actor creation, and independent official fidelity remain **OPEN**. Bounded 4-shape geometry (Gwen/Celeste/Taka/Ringo) previously verified. Roster coverage (10/50+ kits) is an explicit boundary. |
| 4. Items/shop — 15% | Lane purchase unavailable, base purchase succeeds; Boots increase speed, shield blocks stun, and Aftershock adds damage after a cast. | **The bounded matrix scenario is met:** native purchases, both item activations, QA incoming-STUN rejection and exact Aftershock damage are in [items](solo-sandbox-items.md#2026-09-08-local-gwen-item-acceptance); the speed comparison is below. An enemy ability is not an additional prerequisite for the allowed incoming-status fixture. |
| 5. Waves/turrets — 15% | Ranged minions fire from behind; a turret switches from minions to the hero damaging its ally; shots 2/3 hurt more; crystal destruction ends the match. | **PARTIAL/OPEN (2026-09-09):** Server continuously re-issues `1016` move orders (16–22 per actor per 25s window in `wire-1788894917131102000.jsonl`; 2557 order snapshot in `wire-1788942557949012000.jsonl`), providing active pathing and ranged minion firing from behind melee. Short recordings (`skye-basic-attacks.mp4` 30s fresh, `skye-combat-verify.mp4` 45s) illustrate directed locomotion; `halcyon_gate5_wave.mp4` is an older >2-minute recording. Late-match wave accumulation observed in botless runs; reference-backed evaluation needed. The `wave.py` targeting-guard change was reverted; a 17-line regression protects this (76 tests pass in 1.906s). Protective turret switch and Victory previously verified. |

| 6. Jungle — 10% | Treant grants burn on attacks; a full Gold Miner pays 300 to the team; the naturally timed 15:00 Kraken marches and attacks turrets after capture. | **The bounded matrix scenario is met:** [Celeste's natural Treant kill and subsequent attack](solo-sandbox-jungle-wire.md#2026-09-08-natural-treant-kill-and-three-attack-burn-ticks) produce exactly three visible/wire-confirmed −10 burn ticks without QA damage. [Gold capture](solo-sandbox-jungle-wire.md) paid all three allies; [Kraken](solo-sandbox-live-acceptance.md#2026-09-08-natural-kraken-capture-siege-and-victory) completed the pit-to-lane-to-six-structure push. Low-HP capture preparation does not change the natural 240/900-second schedules. [Gwen4 also verifies the separate Treant range repair live](solo-sandbox-jungle-wire.md#2026-09-08-gwen4-live-treant-range-repair-pass), with pursuit followed by two ordinary retaliation actions and hits. |
| 7. HUD/lifecycle — 10% | Recall channels four seconds, base HP/energy bars fill, and a level-scaled death countdown ends in revival at base. | **The bounded matrix scenario is met:** visible native Recall/refill, an 8.5-second level-1 countdown, and standing, controllable Gwen after 1074 are in [live acceptance](solo-sandbox-live-acceptance.md). Additional repeated-death/reconnect cases remain hardening work, not new conditions in this row. |



The automated checks below establish the implementation contracts alongside
the completed client observations above.

| Gate | Representative automated coverage |
|---|---|
| 1 | [Navigation/lifecycle](../../server/test/test_navigation_lifecycle.py): real-mesh routing, wall collision, thin-wall dash policy, stun/knockback stopping and dynamic speed. |
| 2 | [Attack FSM](../../server/test/test_attack_fsm.py), [production session](../../server/test/test_sandbox_simulation.py): release commitment, windup cancellation, recovery movement, travel and attack-speed scaling. |
| 3 | [Hitboxes](../../server/test/test_hitboxes.py), [abilities](../../server/test/test_abilities.py), [production session](../../server/test/test_sandbox_simulation.py): four shapes, delayed damage, energy and channel interruption. |
| 4 | [Item rules](../../server/test/test_items_sandbox.py), [native presentation](../../server/test/test_item_presentation.py): shopping, recipes, specified actives/passives, immunity, timers and buff lifetimes. |
| 5 | [Waves](../../server/test/test_wave_sandbox.py), [turret rules](../../server/test/test_turret_rules.py), [match ending](../../server/test/test_match_end.py): formation/growth, ally protection, heat/reset, backdoor protection and final result. |
| 6 | [Jungle objectives](../../server/test/test_jungle_objectives.py): 240/900-second boundaries, team payout, Kraken push, red-buff slow/burn and blue-buff stats. |
| 7 | [Navigation/lifecycle](../../server/test/test_navigation_lifecycle.py), [Recall session](../../server/test/test_recall_session_lifecycle.py), [native lifecycle](../../server/test/test_lifecycle_wire.py): exact deadlines, interruption, resource caps and native return sequence. |

## Boots speed from the completed Gwen trace

Source: `$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`, connection
`1788669376464`, Gwen EID `1500`. Actual Boots use is line `22399`, epoch
`1788804702.6004438`; buff 278 lasts three seconds. The following actual
movement request is line `22417`, epoch `1788804702.8868866`.

The production world advances every 50 ms and publishes moving positions
every four ticks (`roster.MOVE_TICK = 0.2`). Full, uninterrupted sample intervals
therefore allow the following **cadence-derived server-speed comparison**:

| Segment | Consecutive full 1070 intervals | Distance per interval | Rate at the production cadence |
|---|---:|---:|---:|
| Sprint, lines `22420..22500` | 8 | `1.179994709..1.179999103` units | `5.899973546..5.899995514` units/s |
| Later ordinary movement, lines `28889..28901` | 3 | `0.779998302` units | `3.899991510` units/s |

These agree with Gwen base speed `3.6`, passive Boots `+0.3`, and sprint `+2`.
The first individual steps independently measure approximately `0.295` and
`0.195` units. Both routes are straight and fully walkable; there is no
intervening input, cast, death, new buff or QA teleport within either segment.
Arrival/duplicate frames and the later QA relocation are excluded.

Logged wall gaps vary from `0.168` to `0.236` seconds; they are not simulation
durations. No absolute simulation tick is invented from those timestamps.
The active route ends before buff expiry. The later baseline, initiated by
actual 1012 line `28882` at `1788804839.8237512`, establishes ordinary equipped
speed, rather than the exact instant of the transition at expiry. The route
inspector verifies positions, while the rate calculation additionally uses
the production publication cadence; it does not measure rendered frame rate.

Reproduce the two bounded position audits:

```powershell
python -B Tools/Teardown/inspect_movement_trace.py trace "$env:TEMP/halcyon_stack/wire-1788804074149933400.jsonl" --connection 1788669376464 --request-line 22417 --seconds 2
python -B Tools/Teardown/inspect_movement_trace.py trace "$env:TEMP/halcyon_stack/wire-1788804074149933400.jsonl" --connection 1788669376464 --request-line 28882 --seconds 1
```

Read-only assertions checked all eleven full movement intervals against the
5.9/3.9 rates and excluded intervening orders and hero state changes.

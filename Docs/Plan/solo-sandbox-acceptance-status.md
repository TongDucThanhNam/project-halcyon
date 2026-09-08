# Seven solo sandbox acceptance gates

Updated 2026-09-08, after all seven client scenarios and the final scope audit.
**Correction after the operator's Skye session: gates 2, 3 and 5 are reopened.**
The selectable Skye/265 has no registered kit; ten real 1078 upgrade requests
receive zero 1078/1082 acknowledgements. Missing visible basic projectiles and
defective minion movement are also reported. The earlier prepared scenarios
and offline checks were insufficient to justify overall completion. Their
historical observations remain below as evidence of their narrower scope.
This checklist follows section II of the operator's original Tier 1 brief.
It distinguishes the seven requested manual scenarios from additional fidelity
and hardening work retained in the subsystem leaves. QA may prepare resources,
positions and incoming statuses; the actual client action and its resulting
behavior still supply the acceptance evidence.

The recorded full suite is **758 passing tests in 61.721 seconds**, exceeding
the requested 250-test threshold. The complete output is external at
`$TEMP/halcyon-sandbox-full-suite-20260908-postaudit.txt` (exit 0, source and
tests unchanged throughout).
The earlier two-process 960-second pair passed: both 19,200-tick runs had
byte-identical wire/state/all 960 checkpoints, complete coverage and zero
50 ms deadline misses. Maxima are 14.6694/15.5164 ms. Its source pin matches
the full-suite run and worktree recorded before the operator's test and these
repairs. See [the main plan](solo-sandbox.md#local-verification)
and [performance record](solo-sandbox-performance.md#final-verified-acceptance-pair-2026-09-08).
The operator's subsequent failures override the earlier overall completion
claim. Offline timing and damage-output checks do not establish correct visible
projectiles, selectable-hero skill allocation or normal minion movement.

| Gate | Requested manual scenario | Recorded live evidence |
|---|---|---|
| 1. Navigation — 15% | Route around a jungle wall; stop immediately under knockback or stun. | **The bounded matrix scenario is met:** Catherine's real wall detour and [Gwen's moving-STUN stop](solo-sandbox-live-acceptance.md#2026-09-08-moving-gwen-stops-under-three-second-stun) are measured. Actual move line `56730` precedes STUN22 line `56811`, tick `22460`/time `1123`. No further position or movement input occurs before Victory; expiry is not automatic resumption. |
| 2. Basic attacks — 15% | Target a minion, move as the projectile releases, and retain the hit while moving smoothly. | **Reopened: missing visible projectiles.** Earlier limited evidence: [Celeste's two minion sequences](solo-sandbox-attack-actions.md#celeste-minion-stutter-acceptance-2026-09-08) join native minion creation, ordinary attacks, actual movement and changed positions before retained hits. Videos show the attack-to-retreat transition, continued motion and rounded 116/120 damage while moving. The tested release-commitment contract supports this sequence; crowded recorded pixels do not isolate the precise airborne-projectile/release frame. |
| 3. Abilities — 20% | Show line, cone, delayed ground area and vector dash; spend energy, block a cast at zero energy, and interrupt a channel with stun. | **Reopened: Skye skill allocation unavailable.** Earlier limited evidence: [Gwen's cone and energy audit](solo-sandbox-abilities.md#owned-gwen-cone-and-empty-energy-acceptance-2026-09-08) confirms front/back discrimination and a ready B blocked at zero energy. [Celeste's ground-area audit](solo-sandbox-abilities.md#owned-celeste-delayed-ground-aoe-and-stun-2026-09-08) confirms two delayed hits and B stun. [Gwen C](solo-sandbox-abilities.md#gwen-c-line-acceptance-2026-09-08) hits the first hero on the line while rear/off-line controls are untouched. [Taka A](solo-sandbox-abilities.md#taka-a-vector-through-acceptance-2026-09-08) crosses the selected target and deals the matching shield-mitigated hit. [Ringo's paired casts](solo-sandbox-abilities.md#ringo-channel-interruption-acceptance-2026-09-08) establish an uninterrupted 250 hit plus four burns, followed by an incoming STUN during the second channel with no hit or burn. |
| 4. Items/shop — 15% | Lane purchase unavailable, base purchase succeeds; Boots increase speed, shield blocks stun, and Aftershock adds damage after a cast. | **The bounded matrix scenario is met:** native purchases, both item activations, QA incoming-STUN rejection and exact Aftershock damage are in [items](solo-sandbox-items.md#2026-09-08-local-gwen-item-acceptance); the speed comparison is below. An enemy ability is not an additional prerequisite for the allowed incoming-status fixture. |
| 5. Waves/turrets — 15% | Ranged minions fire from behind; a turret switches from minions to the hero damaging its ally; shots 2/3 hurt more; crystal destruction ends the match. | **Reopened: defective normal minion movement.** Earlier limited evidence: [Taka's fresh-wave clip](solo-sandbox-wave-turret-acceptance.md#2026-09-08-taka-fresh-wave-ranged-fire-from-behind-passes) visibly shows a ranged minion firing about 4.5 units behind living friendly melee, with joined ordinary actions and delayed damage. [Celeste2's live sequence](solo-sandbox-wave-turret-acceptance.md#2026-09-08-celeste2-protective-target-switch-heat-and-retreat) proves the protective switch and escalating hero shots. [Visible Victory after the Kraken push](solo-sandbox-live-acceptance.md#2026-09-08-natural-kraken-capture-siege-and-victory) establishes match end. Exact projectile timing and clip smoothness are not claimed. |
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

# Solo sandbox — local client acceptance

This record separates visible device behavior from simulation and corpus tests.
All sessions use the operator's own local stack and LDPlayer CE client.
Screenshots and wire traces remain outside the repository.

## 2026-09-07: turret action repair and first complete match

Stack PID 10248 started with `HALCYON_NO_BOTS=1` and
`HALCYON_TRACE_WIRE=1`. Local player 1500 selected Adagio (244).
Source was loaded before the later shop-permission and Recall-buff integration.

The previous idle crash followed an invalid turret action: 1045 action 0
(basic attack) addressed a null target after the victim died. Native turret
recordings instead release the target with self-directed action 2 then 3.
The repair also emits native action 0 for every turret shot, following action 1
on acquisition. Native golden tests independently check the recorded sequence.

The repaired session ran from build-close at 20:46:03 to the result at
21:12:00, **1557.248 seconds**, on one continuous connection. The client
displayed **Victory, 25:57**. Crystal-destruction 1106 was sent at
21:11:54.470172 and result 1009 at 21:12:00.450097 (5.980 seconds later).
The actor-order audit found zero creation, occupied-slot or reference errors;
626 corpse-removal chains had already completed when that audit was taken.
This run supports resolution of the reproducible idle turret crash. It does
not establish that every possible native client crash is resolved.

Visible observations:

- Adagio moved from spawn to the base shop and later toward the lane after
  minimap movement input. Full wall/path and stutter-step scenarios remain open.
- A learned through the native skill-upgrade control. A self-cast produced
  a visible cooldown and reduced energy. Exhaustion and all four hitbox
  scenarios remain open.
- Recall input at 20:53:53.394245 produced the hero-specific action, then
  the return position at +4.021 seconds. The hero visibly returned to base.
  This run predates native Withdraw/Ping buffs and return effects.
- The shop displayed “Must be near a shop” beside the actual base shop and
  sent no purchase request. Investigation found an expired bootstrap-only
  permission. The measured live refresh repair is described in
  `solo-sandbox-shop-permission.md`; a new session must verify purchasing.
- Waves and turrets continued until the crystal and result screen. Other
  subsystem-5 checks, including hero-protection aggro and heat, remain open.

Evidence under `$env:TEMP/halcyon_stack/`:

- `wire-1788788674860733600.jsonl`
- `turret-fix-actor-audit.json`
- `turret-fix-cast-mana.png`
- `turret-fix-recall-start.png`, `turret-fix-recall-done.png`
- `turret-fix-lane.png` (Victory screen)

The complete source test suite passed **588 tests in 54.359 seconds** before
shop and Recall integration. The subsequent shop/native-reconnect/combat
focused set passed 29 tests. These are engineering checks, not replacements
for the open device scenarios.

## 2026-09-07 evening: shop, levels, Recall and visibility

The session on PID 15372, trace `wire-1788791968523281700.jsonl`, visibly
offered Buy at the base shop after the permission repair. Clicking Buy sent
1081 for Sprint Boots 477 at 21:47:46 and added owned instance 2002 to the
HUD. Clicking that item sent 1096 at 21:53:38, displayed its sprint effect
and a 150-second cooldown. Screenshots: `shop-permission-ui.png`,
`shop-bought-boots.png`, `shop-boots-active.png`. These prove the input and
presentation; this run did not quantify the movement-speed increase.

The same session displayed the native Recall circle/column, completed the
return to base, and cancelled a separate channel after movement input.
Screenshots: `native-recall-channel.png`, `native-recall-complete.png`,
`native-recall-move-cancel.png`.

The later Catherine session on PID 16680, trace
`wire-1788799203725554700.jsonl`, visibly advanced hero levels after 1076
integration. QA prepared Catherine at level 6; untouched heroes separately
reached level 3 through ordinary XP. The visibility repair then made nearby
Baptiste visible and targetable (`vision-enemy-revealed.png`). Its old cast
index mapping still selected the wrong Catherine actions, so that session's
purported A-stun screenshot is not evidence of A. The fresh native-input
checks below supersede that interpretation.

## 2026-09-08: native Catherine inputs and a real wall detour

PID 28800 loaded the corrected native action mapping. Trace:
`wire-1788800745510618700.jsonl`, all screenshots in `$TEMP/halcyon_stack/`.
QA prepared A/C ranks, level 6, and nearby enemy positions. These fixture
changes do not establish natural rank allocation or enemy movement.

- Clicking C and the enemy's ground position sent 1042 with action 3 at
  1788800868.6228473. The cast started a visible 90-second cooldown and
  reduced energy; its delayed hit damaged Baptiste. Screenshots:
  `catherine-native-ultimate.png`, `catherine-native-ultimate-result.png`.
- Clicking A sent 1041 action 1 at 1788800909.6795824, followed by actual
  target input 1060 for Baptiste. The client displayed the empowered hit,
  damage and **STUNNED** (`catherine-native-a-stun.png`).
- B remained locked because the QA preparation had fabricated a server-only
  skill point at level 1. No B cast input was sent. This exposed a QA setup
  defect; it is not a successful Stormguard test. The fix grants ordinary
  XP/levels to obtain real points before learning.
- A real 1012 tap requested (-13.640995,25.678509) from (-15,20). The direct
  5.838866-unit segment is blocked by A001 terrain. The computed detour via
  (-10.826109,23.514562) is 9.007039 units. All 13 emitted hero-position
  samples remained on the mesh and followed the route within 0.000002554
  units; the endpoint arrived 2.143111 seconds after input. The visible
  obstacle is beside the Barrier Treant/central pit. Screenshots:
  `nav-wall-start.png`, `nav-wall-moving.png`; these static images are paired
  with the trace, not treated as a continuous recording.
- Clicking Recall sent action 5 and displayed its native channel. Starting
  from prepared 300 HP/20 energy, the hero returned to base and both bars
  filled. Screenshots: `catherine-native-recall-channel.png`,
  `catherine-native-recall-full.png`.

Reproduce the wall sample check with the read-only inspector:

```powershell
python -B Tools/Teardown/inspect_movement_trace.py trace "$env:TEMP/halcyon_stack/wire-1788800745510618700.jsonl" --request-line 11839 --seconds 8
```

This connection ended at 00:11:18 before the death/countdown scenario.
The subsequent QA damage request remained unconsumed and was removed before
another match. There is no death/respawn evidence from this attempt. Snapshot
publication can raise a Windows sharing violation while a reader holds
`state.json`; a bounded reproduction and QA repair are underway. The original
failure had no traceback because the match thread silently caught OSError,
so its precise cause remains an inference. Unexpected I/O failures now log
their traceback.

## 2026-09-08: death/countdown exposed incomplete revival

PID 29440 uses the repaired QA publisher. Trace
`wire-1788801940853511000.jsonl`; QA directory
`$TEMP/halcyon_qa_gwen_20260908/`. Despite that directory's label, the hero
actually selected was **Baron 261**, verified by the 1118 input and world
state. The scrolling selector moved between the screenshot and the intended
Gwen tap. This session is not evidence of Gwen's kit or ranged presentation.

QA damage at tick 3331/time 166.55 killed level-3 Baron with 929 HP through
the ordinary damage/lifecycle path. The client displayed the death banner,
corpse and countdown (`baron-death-countdown.png`). Native 1072/1075 were
sent at 1788802321.4014108/.4017384, with a 15.5-second deadline:
6 + 3*2.5 + 2 elapsed-minute seconds.

At simulation time 182.05, the server restored HP929/EP410 and sent 1033
at 1788802336.8097322, then position. The client moved the corpse to base
but retained the death pose and did not send movement after a minimap tap.
Screenshots: `baron-respawn-base.png`, `baron-respawn-move.png`. Thus the
death/countdown presentation passed this bounded check, while actual client
revival **failed**. The existing two-packet revival premise is under renewed
native-burst audit; restoring server state alone does not satisfy acceptance.

## 2026-09-08: Gwen visibly revives and accepts movement after 1074

Fresh PID 6488 loaded the two-stage native return repair. Trace
`$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`, connection
1788669376464, confirms Gwen 395 as the final selection in `1118` lines
569/570. QA directory: `$TEMP/halcyon_qa_gwen3_20260908/`.

Native evidence showed that `1033` relocates a still-dead hero, then
`1074` completes revival approximately 0.3 seconds later. The first
corpse-hiding repair had added `1073` but still omitted `1074`; a separate
Gwen run therefore remained stuck. Full native sequences and zero-HP
snapshots between the two actions are documented in
[solo-sandbox-hero-respawn.md](solo-sandbox-hero-respawn.md).

QA prepared a position and applied lethal true damage at tick 974/time
48.7, dealing 661 actual damage through the ordinary damage/lifecycle
path. This controlled fixture checks lifecycle presentation and return,
not enemy AI's ability to kill the hero.

| Event | Trace line | Wall timestamp |
|---|---:|---:|
| `1072` death | 3954 | 1788804314.3098120 |
| `1075` countdown, 8.5 seconds | 3955 | 1788804314.3103223 |
| `1073` corpse hide | 4062 | 1788804316.0548897 |
| `1033` pre-return at base | 4357 | 1788804322.4763572 |
| `1070` base position | 4358 | 1788804322.4768853 |
| `1074` completed revival | 4383 | 1788804322.7540178 |
| Actual subsequent `1012` move input | 9299 | 1788804427.1702957 |

`$TEMP/gwen3-revive-check.png` shows standing Gwen with full HP and energy
bars. A later actual minimap tap at (122,27) sent the listed `1012`;
`$TEMP/gwen3-revive-moving.png` shows Gwen running away from base. Both
screenshots were inspected. These static views establish the returned
standing model/bars and a later moving pose, alongside the recorded input.

The requested target was (-0.119459063,6.364209652). From base
(-78.180000305,0.879999995), the A001 route is 83.973207 units over four
walkable segments. All 119 emitted hero-position samples remained on the
mesh and followed that route within 0.000025122 units, without an
interposed intent or lifecycle event. The target was sampled at line
10486/time 1788804450.4696214, 23.299326 wall seconds after input, with
0.000000129-unit endpoint error. The first post-input position confirms
the starting point; the QA journal shows no teleport during this interval.

```powershell
python -B Tools/Teardown/inspect_movement_trace.py trace "$env:TEMP/halcyon_stack/wire-1788804074149933400.jsonl" --connection 1788669376464 --request-line 9299 --seconds 30
```

The reproducible stuck-corpse problem passes this bounded check: the client
visibly revived with full bars and accepted a real movement command. This
does **not** close the whole lifecycle gate. Repeated deaths, ordinary
combat deaths, dead-input rejection, timer scaling, and visible reconnect
during each death/return stage retain their separate acceptance checks.
Production code was unchanged during this evidence audit.

## 2026-09-08: Gold Miner capture and team payout

The same PID 6488/Gwen 395 match continued using the normal 240-second Gold
spawn and 900-second Kraken schedule. Trace remains
`$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`. Neutral Gold 100012
appeared in creation/snapshot lines 12972/12973 at
1788804506.7349906/.7381608. The current 1-gold/second policy filled its
300-gold cap by simulation time 540; no clock acceleration was used.

QA applied 1750 true damage at simulation time 695.25, preparing the Miner
at 50/1800 HP, and refilled Gwen at 695.6. An actual subsequent tap at
(470,275) sent `1060` for 100012 at line 36039/time 1788804991.7243633.
Gwen's ordinary action8 `1045` followed at line 36040, then a lethal
class5/type0 `1054` at line 36047/time 1788804992.1130445. The final hit
and capture used real client input; the prepared low HP means this does
not establish combat against a full-health Gold Miner.

Exactly three type6 `1053` rewards awarded +300 gold to heroes 1500, 1515
and 1516 at lines 36049/36054/36059. No enemy received a +300 award.
Old-actor death `1072` at line 36063 preceded new actor 100013's creation,
HP1800/1800 snapshot and position at lines 36064–36066. The replacement
uses team1 and slot50 while the defeated neutral corpse retains slot49.
Old `1073`/`1035` at lines 36250/36251 remove it approximately 3.8 seconds
later. The actor-order audit reported zero problems at this checkpoint.

The inspected screenshots `$TEMP/gwen3-goldminer-ready.png`,
`$TEMP/gwen3-miner-low.png` and `$TEMP/gwen3-miner-capture.png` show the
neutral model, prepared encounter and a standing blue team-owned Miner
with a blue bar after capture. The 50-HP fixture and 1800-HP replacement
are established by QA/wire state, not exact numeric UI readings.

This is a bounded team-1 capture and three-hero payout pass. Enemy
recapture, guardian combat, complete native capture effects, reconnect
during corpse overlap and Kraken remain separate checks. Exact packet
times, faction fields and fixture provenance are in
[solo-sandbox-jungle-wire.md](solo-sandbox-jungle-wire.md). Production was
unchanged during this read-only audit.

## 2026-09-08: moving Gwen stops under three-second STUN

The completed Gwen 395 trace remains
`$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`, connection
1788669376464. Actual client `1012` at line 56730/time1788805387.573277
requests (−0.119459,6.364210). Gwen's `1070` starts at (62,12), line56745,
then progresses through six further positions to (58.387798,10.529680),
line56807/time1788805388.6620605. Line56808 repeats that final position.

QA request `c55e3053d29d4a59859d18dcabf795f9` in
`$TEMP/halcyon_qa_gwen3_20260908/journal.jsonl` applies STUN for three
seconds at tick22460/simulation1123, expiring1126. The native `1086`
at line56811/time1788805388.6659505 addresses Gwen as target/source,
duration3.0, instance2009230, kind22. No further Gwen `1070` or client
movement/target intent appears before the match ends.

Inspected `$TEMP/gwen3-moving-stunned.png` shows STUNNED and stars at
client18:52; `$TEMP/gwen3-moving-resumed.png` at18:56 shows the normal
name and no stars. The filename does not establish resumed movement:
the trace shows that STUN cancels the old movement order. This passes
the requested moving-stop and visible expiry check. The status came
from an explicit QA fixture; no enemy skill is claimed for this sample.

## 2026-09-08: natural Kraken capture, siege and Victory

The same normal-clock Gwen match reached the 900-second Kraken schedule.
Owned Gold100013 retired; neutral Kraken100014 was created at line45205,
archetype363, slot57, HP5000/5000. After Gwen's ordinary revival, QA
request `2c600cf45ce9493e83adf6cfb87c1823` at tick19644/time982.2
reduced that Kraken to10 HP. No objective clock or captured-unit motion
was edited. Actual `1060` line49096 selected the neutral Kraken;
Gwen's action8 and lethal `1054` led to a fresh owned actor100015,
archetype364, team1, slot67, HP5000/5000 at lines49113/49114.

All882 recorded positions of captured100015 lie on the actual A001
mesh, with no blocked adjacent chord. They cover132.057741 units from
the pit through the lane near(0,0), then the enemy structures. The
Kraken delivers the final kill to3539,3540,3541,3543,3542 and crystal3544.
The first turret had337.5 damage from other sources beforehand; the
remaining five structures lose all their HP to Kraken. Crystal lethal
damage is line57613, native `1106` line57614, death line57615 and
`1009` line57621, approximately5.97 wall seconds after `1106`.
Inspected `$TEMP/gwen3-kraken-spawn.png`, `gwen3-kraken-capture.png`
and `gwen3-kraken-victory.png` show neutral, blue owned and Victory
states respectively; the result clock reads19:13.

This passes the bounded normal-clock capture, route, structure damage
and result flow. It used a prepared10-HP final-hit fixture. This trace
contains no Kraken `1045` attack presentation, so it cannot validate
the subsequent jungle action repair or full native attack animations.
Detailed timing, health preparation and packet identities are in
[solo-sandbox-jungle-wire.md](solo-sandbox-jungle-wire.md).

## 2026-09-08: Celeste turret heat and retreat

Celeste 285's next local match, PID 15676, is recorded in
`$TEMP/halcyon_stack/wire-1788805712141535000.jsonl`, connection1410964560464.
After explicit QA positioning, an actual target input at line31729 enters
third turret3541's radius. Five ordinary hits at lines31744,31787,31831,
31875 and31914 remove96.435501,156.225510,212.466705,254.960037 and
254.960037 HP. These match the implemented heat progression, armor65.914
and capped fourth/fifth shots. Actual retreat at line31932 leads to native
self-targeted release/idle actions2/3 at lines31959/31960 and no further
3541 damage to Celeste through the audited checkpoint.

Inspected `$TEMP/celeste-third-turret-hits.png` shows turret attack/warning
presentation and reduced hero HP. The bounded heat/cap/retreat check passes.
Celeste's attack stalls under the old range predicate and emits no1045 or
damage to Baptiste; this sample does not pass hero-protection aggro.

The same trace has a bounded formation sample: ranged4779 remains stationary
1.528296 units behind its nearest living friendly melee4775 while damage
contacts continue. It has no ranged1045. The subsequent lane repair adds
grounded actions and queues contacts after an empirical 10-tick melee or
27-tick ranged/siege delay. Its 68 focused tests pass; a fresh client
shooting-animation and visual-impact check remains open. These delays are
sandbox policy, not recovered native release/projectile constants. Exact
records, metadata and remaining timing limits are in
[wave and turret acceptance](solo-sandbox-wave-turret-acceptance.md).

## 2026-09-08: Celeste kills Treant and applies three burn ticks

Fresh Celeste 285 trace
`$TEMP/halcyon_stack/wire-1788808981133504900.jsonl`, connection
1920953706832, records actual Treant-target input at line 3869. Thirteen
ordinary Celeste damage contacts kill Treant 100000 naturally: final
`1054` line 4570 / epoch 1788809108.4407306, then `1072` line 4571 naming
killer 1500. QA prepared only positioning and a learned ability; it did
not damage the Treant, refill health or grant the buff.

After QA positions Celeste and Baptiste, actual target input at line 7343
starts one basic attack. Primary crystal damage is −68.0143585 at line
7359, followed by an actual movement input at line 7366. Exactly three
additional true-damage hits of −10 follow at lines 7410,7464,7517, with
no further attack, cast, item or QA damage in the interval. Inspected
`$TEMP/halcyon_stack/celeste2-treant-burn.png` shows the floating 10 over
Baptiste. This completes the bounded Treant-to-buff-to-burn check and,
with the recorded Gold Miner and Kraken evidence, the jungle gate.

The same loaded match exposed a separate Treant retaliation stall just
outside its 2-unit radius. The coordinate-grid repair passes 54 focused
tests but needs a fresh client run. Exact records, QA provenance and
the remaining animation limit are in
[jungle acceptance](solo-sandbox-jungle-wire.md#2026-09-08-natural-treant-kill-and-three-attack-burn-ticks).

## 2026-09-08: Celeste2 turret protection and escalating shots

The same fresh Celeste trace, connection 1920953706832, now proves the
protective target switch. First turret 3539 damages living minion 4685 at
lines 15001 and 15059. Actual hero input at line 15013 targets Baptiste;
Celeste's hit at line 15080 is immediately followed by turret acquire 1500
at line 15081. The previous minion victim remains alive.

Four turret hits remove 102.026505,165.282928,224.784790 and 269.741760 HP
at lines 15114,15169,15238,15295, matching the implemented heat progression
and level-8 armor. Actual retreat at line 15269 leads to release/idle at
15312/15313 and reacquisition of the same living minion at 15314. Viewed
`$TEMP/halcyon_stack/celeste2-protect-heat.png` shows the red 225 over
Celeste and the turret warning. Protective switching and escalating shots
pass their bounded live checks.

The accompanying 19.89-second/78-frame clip also contains a stationary
ranged actor behind a living front melee, with grounded `1045` actions and
later −55 contacts in the trace. Its crowded 3.92 fps images do not isolate
the ranged projectile clearly enough to close that visual check, and do
not establish smoothness. Later 480×270/16.91 fps and 640×360/9.73 fps
clips confirm the formation and additional ranged action/contact pairs,
but rear firing remains visually inconclusive at the recorded actor size.
Exact positions, action/contact pairs and video
limits are in [wave and turret acceptance](solo-sandbox-wave-turret-acceptance.md#2026-09-08-celeste2-protective-target-switch-heat-and-retreat).

## 2026-09-08: Gwen4 Treant retaliation after the range repair

Fresh Gwen trace `wire-1788810206949588100.jsonl`, connection
2598410757328, records actual Treant input at line 29350. After terrain
pursuit, Treant 100000 reaches the nominal 2-unit radius and sends ordinary
actions 0/1 at lines 29612/29688. Their adjacent damage packets remove
26.027466 HP from Gwen each. QA positioned the player at simulation
510.75; no Treant position, damage or status fixture prepared the fight.
Viewed `gwen4-treant-retaliates.png` shows the close-range exchange.

The bounded neutral pursuit/admission repair passes live. Exact native
animation/contact timing remains outside this check. Details are in
[the jungle record](solo-sandbox-jungle-wire.md#2026-09-08-gwen4-live-treant-range-repair-pass).
An earlier isolated ranged clip in this match retained its melee behind
the ranged actor, so it does not close the remaining ranged-fire-from-behind
observation; that fixture's ordering is recorded in the wave/turret leaf.

## 2026-09-08: Taka fresh-wave ranged firing completes gate 5

Trace `wire-1788811044288843600.jsonl`, connection 2207670451280, and
`$TEMP/halcyon_stack/taka-isolated-wave2.mp4` show one fresh ranged minion
4755 stopping behind living friendly melee 4749 and repeatedly firing at
enemy melee 4748. The screenshot `taka-isolated-wave2.png` shows the three
actors separately; the clip exposes the rear firing poses without overlap.
The ranged actor remains about 4.5 units behind its melee and 6.5 units
from the enemy. Native ordinary actions 0/1 and delayed 62.5-damage contacts
name those same actors, ending with the ranged actor's kill at line 20701.

QA cleared 20 other lane actors and positioned the player before combat;
the three retained actors received no damage, movement or status fixture.
The 153-frame/19.97-second clip proves this bounded behavior, without a
smoothness or exact projectile-time claim. With Celeste2's protective
turret switch, escalating heat and the recorded Victory, **gate 5 is met**.
Detailed positions, frames and packet records are in
[wave/turret acceptance](solo-sandbox-wave-turret-acceptance.md#2026-09-08-taka-fresh-wave-ranged-fire-from-behind-passes).

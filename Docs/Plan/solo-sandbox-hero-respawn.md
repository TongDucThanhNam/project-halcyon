# Hero corpse hiding and resurrection

The local client remained in its death pose after an incomplete return
sequence that omitted the final native `1074` revival action. `1033` moves a still-dead hero to
base approximately 0.3 seconds before `1074` completes resurrection. Native
snapshots between these actions still contain zero HP; snapshots after
`1074` contain full pools without an intervening healing delta.

The server now schedules `1073` corpse hiding approximately 1.8 seconds
after death, sends `1033`/`1070` 0.3 seconds before the deadline while
keeping the hero dead, then sends `1074` and restores life and pools at the
deadline. It preserves the actor and compact slot throughout. A fresh Gwen
client cycle visibly passed revival and subsequent movement; the bounded
acceptance and remaining lifecycle checks are recorded below.

## Actual local failure

External trace `$TEMP/halcyon_stack/wire-1788801940853511000.jsonl`, connection
1635645186640, hero 1500 (Baron 261):

| Event | Trace line | Wall timestamp |
|---|---:|---:|
| Lethal combat delta | 9393 | 1788802321.4008334 |
| `1072` death | 9394 | 1788802321.4014108 |
| `1075`, 15.5 seconds | 9395 | 1788802321.4017384 |
| `1033` at base | 10081 | 1788802336.8097322 |
| `1070` position | 10082 | 1788802336.8100748 |
| `1067` visibility update | 10088 | 1788802336.815413 |

No `1073` occurred between death and return. Authoritative state reported
alive, HP 929 and energy 410, but the client remained in the dead pose and
later movement taps emitted no `1012`. Existing external screenshots are
`baron-respawn-base.png` and `baron-respawn-move.png` in that trace directory.
This disproves the earlier acceptance premise that observing `1033` and
`1070` alone established a successful client resurrection.

The first correction added the missing `1073` stage and was tested again
with Gwen 395. It was insufficient: external trace
`$TEMP/halcyon_stack/wire-1788803243659481800.jsonl` contains death at
1788803393.6656, an 8.5-second countdown, `1073` at 1788803395.4174 and
height-1.3 flag1 `1033` at 1788803402.1039, but no `1074`. The client still
displayed a corpse at base without its HP bar and emitted no movement
intent from a later minimap tap. Server state was alive with positive HP.
External screenshots `gwen2-respawn.png` and `gwen2-hidden-corpse.png`
document that second failed client cycle. The subsequent audit used full
time windows rather than a fixed ±45-frame window, which had excluded
three of the five final native `1074` actions.

## Complete native evidence

All five completed `vgfull.pcap` resurrection intervals include one `1073`
between death and return, with no `1035` deletion. Indices are zero-based
decoded s2c frame indices. The existing decoder and tests load the external
capture; no payload fixture is checked into the repository.

| EID | Death `1072` | Timer `1075` | Corpse `1073` | Relocation `1033` | Revival `1074` | Corpse delay, TCP receive seconds |
|---|---:|---:|---:|---:|---:|---:|
| 1517 | 16703 | 16705 | 16970 | 17281 | 17328 | 1.840659 |
| 1517 | 23106 | 23108 | 23363 | 24096 | 24143 | 1.796617 |
| 1518 | 24046 | 24050 | 24296 | 24843 | 24895 | 1.836230 |
| 1519 | 25676 | 25679 | 25851 | 26295 | 26329 | 1.835495 |
| 1519 | 31279 | 31282 | 31488 | 32378 | 32404 | 1.830142 |

Each `1073` is `[u32 EID][u16 zero]`. All five relocations immediately
precede `1070`. The `1074` payload is the same EID and three coordinates
as `1033`, followed by six zero bytes. Relocation-to-revival delays are
0.309108, 0.307454, 0.305728, 0.304976 and 0.297903 TCP receive seconds.
The countdown-to-`1074` elapsed time exceeds its declared duration by only
0.042–0.087 seconds; `1033` arrives 0.216–0.267 seconds before that duration.
No full HP/energy restoration delta accompanies either action. These
actors belong to the opposing team, so local-player evidence was checked
separately rather than generalizing the absence of HP deltas.

Seven complete local-player 1500 death/return sequences independently
contain the same `1072` → `1073` → flag1 `1033` → `1074` order. Each row below gives
`chunk:row`, with zero-based VGR row indices. Filenames use prefix
`ea4c7fda-4b61-481d-abb7-1c757d24ae58-`, the full match UUID, and `.chunk.vgr`.

| Match UUID | Death | Corpse hide | Relocation | Revival | Corpse delay, VGR seconds |
|---|---|---|---|---|---:|
| 045f86d4-7ef2-4125-a835-e70a96288c88 | 26:421 | 26:634 | 26:1448 | 27:241 | 1.867767 |
| 045f86d4-7ef2-4125-a835-e70a96288c88 | 33:684 | 33:846 | 34:618 | 34:644 | 1.849945 |
| 0e7de8af-96d9-4e3a-b3c2-609ed5e71120 | 16:1001 | 16:1414 | 16:2131 | 16:2173 | 1.763260 |
| 0e7de8af-96d9-4e3a-b3c2-609ed5e71120 | 37:512 | 37:634 | 38:742 | 38:787 | 1.746979 |
| 5ac8f358-2683-4205-9b7b-969ea31b3c72 | 33:1525 | 34:379 | 35:316 | 35:355 | 1.781281 |
| a683aa80-9811-47c3-bb64-0731a802e889 | 10:407 | 10:611 | 10:734 | 10:758 | 1.799416 |
| a683aa80-9811-47c3-bb64-0731a802e889 | 35:364 | 35:529 | 36:587 | 36:648 | 1.766113 |

The first match lives under `$TEMP/vg_max/vgr5b`; the remaining three are
under `$TEMP/vg_phaseB/vgr_live`. Tests decode only the required original
chunks and compare complete death, corpse-hide and return payloads against
builders. VGR chunk-start snapshots may occur during a death interval and
are not fresh actor creation events or live reconnect requests.

All seven local flag1 returns use height 1.3. Six native flag1 returns for
1515 also use 1.3; the 45/37/34 observed flag1 returns for 1517/1518/1519 use
1.5. No 1516 flag1 return was found, so its previous 1.5 height remains an
explicit unmeasured fallback. Recall also uses `1033`, but with flag0 and
different measured relocation heights; it is excluded from this audit.

The expanded census across nine canonical VGR matches found 129 flag1
`1033` actions, each followed by `1074` with identical coordinates and a
zero tail. Delays range from 0.1999 to 0.4008 VGR seconds. Three additional
`1074` actions lack a preceding recorded `1033`, so 132 total `1074` records
must not be described as 132 complete pairs. No matched `1074` follows a
flag0 Recall relocation.

Two independent local-player snapshots make the resource transition
observable without assuming an opcode's internal class name:

| Match and snapshot | Relative stage | HP / maximum | Energy / maximum |
|---|---|---:|---:|
| 045f86d4… 27:8 | 0.267151 seconds after `1033`, before `1074` | 0 / 1578.9199 | 138.9628 / 370 |
| 0e7de8af… 17:8 | After `1074`, 0.848206 seconds after `1033` | 982 / 982 | 300 / 300 |

Both snapshots already contain the friendly-base position. The second
has no HP delta between `1074` and the snapshot. Three additional remote
snapshots between the two actions also contain zero HP. Thus relocation
must not mark the hero alive or refill its authoritative pools early.

## Implementation and limits

`HeroMovement.apply_damage` schedules corpse hiding at death + 1.8 seconds,
capped by the pre-return time for explicit short-duration test overrides.
`check_respawn`, called by both lifecycle and movement ticks, emits `1073`
once when due. At `max(death_time, respawn_at - 0.3)`, it emits `1033`/`1070`
and relocates the still-dead hero. At the saved deadline, it emits `1074`
and restores authoritative life, HP and energy. A sparse tick that first
reaches the deadline emits pending `1073`, `1033`, `1070`, `1074` in that
order. It never emits `1035`, and
`ActorSlots.observe` retains the hero's slot. A second death rearms the
corpse and relocation stages. Dead movement remains rejected until `1074`.

The 1.8-second corpse and 0.3-second return schedules are fixed-tick
approximations to measured receive/record intervals, not recovered native
internal timer constants.
Additional native death notifications include `1052` attribute 42 +1,
statistics and buff/action cleanup. This correction does not assign new
semantics to those fields or claim a complete implementation of every
death-side effect. It also does not add a speculative full HP/energy delta.

Checks:

```powershell
python -B -m unittest server.test.test_lifecycle_wire server.test.test_hero_combat server.test.test_navigation_lifecycle -q
```

All 56 checks passed after the two-stage correction. They cover five full native
remote sequences, seven local sequences, corpse timing boundaries,
idempotence, actor-slot retention, no movement while dead, short override
ordering, zero-HP native snapshots between stages, full pools after native
`1074` without healing deltas, and authoritative full pools only at revival.

The fresh cycle below verifies a returned standing model, full HP/energy
bars and a new post-return client movement intent. Together with the recorded
Recall/refill, it meets the brief's bounded lifecycle matrix scenario.
Further reconnect hardening includes visibly restoring
`1072`, remaining `1075`, and `1073` without releasing or duplicating the
actor; during pre-return it must also replay `1033` while retaining the
death state until `1074`. Repeated deaths, ordinary enemy-caused deaths,
dead input rejection and additional timer levels can receive separate device
checks; these are not extra acceptance prerequisites for the matrix row.

## Fresh local Gwen acceptance after the two-stage repair

PID 6488 loaded the corrected source. External trace
`$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`, connection
1788669376464, confirms the final Gwen 395 selection in `1118` lines 569/570.
QA journal `$TEMP/halcyon_qa_gwen3_20260908/journal.jsonl` records a prepared
teleport at simulation time 48.35 and lethal true damage at tick 974/time
48.7, applying 661 actual damage through the ordinary lifecycle path.
This is a controlled death fixture, not an enemy AI/combat acceptance case.

| Event | Trace line | Wall timestamp |
|---|---:|---:|
| Death `1072` | 3954 | 1788804314.3098120 |
| Countdown `1075`, 8.5 seconds | 3955 | 1788804314.3103223 |
| Corpse hide `1073` | 4062 | 1788804316.0548897 |
| Pre-return `1033`, height 1.3, flag1 | 4357 | 1788804322.4763572 |
| Position `1070`, friendly base | 4358 | 1788804322.4768853 |
| Completed revival `1074` | 4383 | 1788804322.7540178 |
| Actual post-return move input `1012` | 9299 | 1788804427.1702957 |

`$TEMP/gwen3-revive-check.png` visibly shows standing Gwen with full HP
and energy bars at base. A later actual minimap tap at screen coordinates
(122,27) produced the recorded `1012` and a running Gwen in
`$TEMP/gwen3-revive-moving.png`. Both images were independently inspected.
Their rendered clocks are 2:38 and 2:52; they are discrete observations,
not a continuous recording of the respawn transition or complete route.

The move requested (-0.119459063,6.364209652) from
(-78.180000305,0.879999995). The direct 78.252953-unit segment is blocked;
the 83.973207-unit A001 route follows four walkable segments via
(-51.891203,6.404573), (-32.668140,-4.525279) and
(-6.484216,1.204137). All 119 sampled `1070` positions stay on the mesh,
with maximum route error 0.000025122 units, no backward movement over
0.02 units, no blocked sample chords and no interposed movement intent
or lifecycle action. The endpoint at line 10486/time 1788804450.4696214
is 0.000000129 units from the projected target, 23.299326 wall seconds
after the request. This measures sampled movement, not a native speed rule.

The previous position record was old, but line 9301 at input +0.027364
seconds confirms the same starting position; line 9302 at +0.029533
seconds advances away from it. The QA journal has no fixture mutation
during this route; its next teleport is at simulation time 217.1, after
the route ends. That prepared position appears in `1070` line 11917 at
1788804482.7046206, over 32 seconds after the sampled route endpoint.
This supports successful post-revival control and movement.

Reproduce the numeric trajectory audit:

```powershell
python -B Tools/Teardown/inspect_movement_trace.py trace "$env:TEMP/halcyon_stack/wire-1788804074149933400.jsonl" --connection 1788669376464 --request-line 9299 --seconds 30
```

The stuck-corpse reproduction passes this bounded fresh-client check.
Current matrix status is in [the acceptance checklist](solo-sandbox-acceptance-status.md);
the lifecycle row is met. Additional device hardening retains the limits above.

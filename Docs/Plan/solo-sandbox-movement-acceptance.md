# Movement trace checks and remaining lifecycle scenarios

Prepared 2026-09-08 against the current external A001 mesh. This pass writes
only the independent inspector and this note. It sends no client input, QA
request or gameplay mutation, and changes no simulation/performance source.

## Reproducible jungle obstacle

Both endpoints of each case are on the 793-vertex, 832-triangle A001 mesh.
Their direct segment is blocked; every listed route segment is walkable.
Coordinates below use server `(x, y)`, equivalent to map `(x, z)`.

| Start | Requested destination | Intermediate waypoints | Direct / route distance |
|---|---|---|---|
| `(-15,20)` | `(-15,30)` | `(-10.826109,23.514562)` | `10 / 13.168986` |
| `(-22,18)` | `(-22,28)` | `(-10.657107,20.136771)`, `(-14.841680,25.326847)` | `10 / 25.850457` |
| `(-40,20)` | `(-40,30)` | `(-36.196141,26.831099)` | `10 / 12.769662` |

The first case is beside the western central-pit wall cluster. The current
external screenshots show stone ruins between the visible Barrier Treant
and central pit. Exact screen coordinates depend on the current camera;
use the actual decoded click coordinates when assessing a run.

Read-only plan command:

```powershell
python -B Tools/Teardown/inspect_movement_trace.py plan --start -15 20 --target -15 30
```

For a fresh diagnostic scenario, the following is **setup only**, to be run
by the operator driving that session. The server must already have the same
external `HALCYON_QA_DIR`. Then use an actual ground tap across the wall and
leave movement uninterrupted until arrival:

```powershell
python -B Tools/sandbox_qa.py teleport --eid 1500 --x -15 --y 20
```

Do not use a second teleport as arrival evidence. Keep the QA journal and
the initial/final client images outside the repository.

## Actual first tap: the direct route was already blocked

The parent operator performed setup and a real screen tap in
`$TEMP/halcyon_stack/wire-1788800745510618700.jsonl`, connection
`1262683747280`. The inspector reads the resulting stream:

- Line **11839**, time **1788801008.236463**, is a valid client `1012` with
  target **`(-13.6409950256,25.6785087585)`**.
- The last pre-request `1070` is `(-15,20)` at line 8179. The first
  post-request position repeats that same origin at +0.003784 seconds,
  corroborating the stationary starting point despite the older timestamp.
- Direct distance is **5.838866 units**, and that segment is blocked.
  The planned route goes through **`(-10.826109,23.514562)`**, for a total
  **9.007039 units**.
- All **13** following hero-position samples are exactly inside the mesh.
  Maximum deviation from the planned polyline is **0.000002554 units**.
  Progress is monotonic, and all sampled chords are also walkable here.
- Line **11942** reaches the requested destination at **+2.143111 seconds
  of wire wall time**, with no intervening client movement/cast/target/item
  intent or hero lifecycle event.

This is concrete evidence of the actual movement request producing a
detour in the sampled authoritative stream. A tap farther toward `y=30`
is optional additional coverage, rather than necessary to make the first
request a blocked-direct-path case.

The external images `nav-wall-start.png` and `nav-wall-moving.png` show
different moments, with client clock labels 2:38 and 3:41. They establish
the visible terrain context and hero presentation at those moments; the
two still images alone do not establish continuous motion around the wall.

```powershell
python -B Tools/Teardown/inspect_movement_trace.py trace "$env:TEMP/halcyon_stack/wire-1788800745510618700.jsonl" --limit 3
python -B Tools/Teardown/inspect_movement_trace.py trace "$env:TEMP/halcyon_stack/wire-1788800745510618700.jsonl" --request-line 11839 --seconds 8
```

For a different trace, first list requests, then select the exact one-based
JSONL line. Multiple movement connections require `--connection`; `--eid`
defaults to 1500 and must name the hero owned by that connection. The tool
validates native `1012` and `1070` lengths, padding and finite coordinates.
It reports an unfinished final trace line instead of treating it as a frame.

The inspector stops at arrival, the next client intent, hero death/respawn,
the selected time window, or end of trace. It reports distance from the mesh,
distance/progress along the calculated route, and the direct chords between
samples. It does not classify an interrupted or incomplete run as arrival.

## Measurement limits

Server positions are normally sampled every 0.2 seconds. A chord between
two samples can cut across a corner which the hero traversed between them.
Consequently a blocked sample chord is a diagnostic finding, not by itself
proof of wall crossing. Conversely, valid samples cannot prove every
unobserved fixed-tick position or every rendered client frame.

Route comparison uses the actual click and preceding server position. It
must be accompanied by a stationary known start and no QA teleport, recall,
knockback, dash or other forced movement during the interval. Check the
external QA journal when fixtures are enabled. Current source geometry and
route policy must match the source loaded in the tested server process.

Wire timestamps are wall time. They contain scheduling and transport delay
and are not sufficient to establish exact simulation speed or the 50-ms
deadline requirement. QA file I/O remains outside performance acceptance.

The inspector was checked with an authored 5-unit/second hero traversal on
the actual mesh, an intentionally invalid straight-wall sample, an
intervening target intent, four malformed/nonfinite payloads, and an
unfinished trace tail. The valid traversal reached the target with 14
samples; the invalid sample exposed both off-mesh and off-route distances.
Those diagnostic checks are separate from the actual client trace above.

## Remaining jungle and death/countdown gates

The earlier lifecycle documents contain native corpus and simulation proof;
the following still require explicit client observations. At this pass's
fresh-trace checkpoint there were **no jungle `1072` deaths and no hero-1500
`1072`/`1075` pair**. One later unpaired `1033` at 1788801058.8509634 is not
evidence that the hero died, displayed a countdown, and respawned.

| Scenario | Observe in the client and correlate with the trace |
|---|---|
| Treant and bear combat | Real `1060` target input, targetable model, ordinary attacks/damage, death animation; corpse must stop attacking/moving. Treant heal and bounty occur once. |
| Jungle leash | Pull a living monster more than the implemented 8.5 units from its own anchor; observe return and HP reset. A distant hero alone does not establish that the monster crossed its leash radius. |
| Corpse removal and camp return | Treant retains its actor for 4.0 simulation seconds; bears for 3.8. `1073`/`1035` precede slot reuse. Wait for fresh-EID camp creation and verify its visible return. |
| Buff camps | Confirm acquisition, actual weapon/energy behavior, visible duration and expiry; unspecified strength/duration coefficients remain documented sandbox policy. |
| Gold and Kraken | Normal schedules are 240/900 simulation seconds at `(0,23.6)`. Captured faction/model/HP, Gold team payout and guardian behavior, enemy recapture, Kraken march and structure attacks require visible proof. Capture remains the explicit external-template experiment. |
| Hero death and timer | Cause normal combat death; observe the actual death state and visible countdown. Correlate `1072(victim,killer)` followed by `1075(eid,seconds)`; dead movement/attack/cast inputs must not execute. |
| Hero revival | Observe `1073` corpse hiding approximately 1.8 seconds after death without `1035` or slot release. Observe `1033`/`1070` pre-return 0.3 seconds before the deadline while the hero stays dead, then `1074` at the deadline. Confirm the friendly spawn, standing model, restored HP/energy, usable controls and visibility. Native `1074` restores pools without an accompanying full-pool additive delta. See `solo-sandbox-hero-respawn.md` for both measured missing stages and native snapshots that distinguish them. |
| Reconnect during lifecycle | Reconnect once while a hero is dead or a jungle corpse is retained, and after removal. Remaining countdown, actor ownership, current health and retained/removed corpses must agree with authority. |

Useful camp anchors are left A `(-40.9,20.3)`, B `(-44.4,31.9)`,
C `(-21.95,24)`, and D `(-13.5,37.7)`; current server right anchors mirror
their x coordinates. Always identify current actors from `1010` archetype
and position. EIDs change on respawn; the captured labels can differ from
the sandbox's generic monster type.

Read the current QA state without submitting a command:

```powershell
$scenarioState = Get-Content -Raw (Join-Path $env:HALCYON_QA_DIR 'state.json') | ConvertFrom-Json
$scenarioState | Select-Object tick, time, phase
$scenarioState.heroes | Where-Object eid -eq 1500 | Select-Object eid, alive, level, hp, max_hp, energy, max_energy, x, y, respawn_at
$scenarioState.nearby_creatures | Where-Object alive | Select-Object eid, team, x, y, hp, max_hp
python -B Tools/Teardown/inspect_live_actor_order.py "$env:TEMP/halcyon_stack/wire-1788800745510618700.jsonl"
```

QA snapshots expose hero `respawn_at`, `level` and simulation `time`; remaining
time is `respawn_at - time`. The current formula fixes the deadline on death
using `6 + 2.5 * level_at_death + floor(match_time_at_death / 60)`. It is
explicit sandbox policy, and later leveling while dead must not move that
saved deadline. Observe timer accuracy against simulation timestamps, with
the normal next-tick resolution, separately from wall-time scheduling.

The current snapshot does **not** expose camp ID, monster anchor/target/leash
state, corpse deadlines, or camp respawn deadlines. Its nearby list is capped
at 64, is relative to any hero, may contain old dead minions, and currently
often has `kind: null`. Join to actual actor-creation records rather than
interpreting absence from that list as despawn.

The subsequent camp audit corrected return timers to **60 seconds for
Treants in A/C and 50 seconds for bear camps B/D** after the last member
dies. Exact native timestamps in the original source supersede the earlier
85/71-second chunk estimates; see `solo-sandbox-camp-respawn.md`. A process
started before that source correction retains its loaded implementation,
so record which build was actually used for the live return scenario.

# Jungle lifecycle, captured objectives and local client QA

This record covers jungle actor death/removal and the captured-objective
adapter. Team-1 Gold capture/payout and Kraken capture/push/Victory are now
observed in the local client, as recorded below. The Treant burn chain and
subsequent retaliation range repair also pass their bounded live checks.
The external corpus still has no captured Gold or archetype-364 record;
the working adapter is not claimed to reproduce every native capture field.

## Native lifecycle evidence

Every one of the 22 jungle removals in `vgfull.pcap` has a preceding
`1072 [victim EID][killer EID][six zeros]`. Destroy `1073` and removal `1035`
share the same receive timestamp. Death occurs earlier:

| Archetype | Actor | Complete chains | Death→destroy receive gap |
|---|---|---:|---|
| 357 | Treant | 7 | 3.914–3.988 seconds |
| 358 | Elder Treant | 1 | 3.985 seconds |
| 359 | Big Bear | 8 | 3.765–3.826 seconds |
| 360 | Small Bear | 6 | 3.779–3.850 seconds |

The server now emits death immediately, prevents further attacks/movement,
and keeps the corpse's compact slot. Bears retain their corpse for 3.8
seconds; Treants for 4.0 seconds. Due `1073`/`1035` pairs are emitted before
new spawns allocate slots. Repeated lethal calls do not create another
death, reward or respawn timer. Both hero and nonhero damage paths can use
`JungleManager.on_monster_death(monster, killer_eid, now)`.

The complete match-6 cache has 27 jungle removals with no missing death.
Its Gold Miner retirement is especially useful: chunk 70 row 940 is
`1054(self, self, -10000)` with the native `00 02 02` damage tail; row 946
is `1072(self, self)`. Chunk 71 rows 303/305 destroy/remove it 3.781189 VGR
seconds later. Match `f58e0359-8d83-4994-a33c-217cf863144b` independently
has the same full self-hit/death payloads in chunk 70 rows 1090/1096 and
removal in chunk 71 rows 322/326. These records are under
`$TEMP/vg_phaseB/vgr_live/cache`, with the session filename prefix
`ea4c7fda-4b61-481d-abb7-1c757d24ae58-`.

The scheduled Gold→Kraken replacement uses that self-hit/death shape and
retains the Gold corpse. Its requested 900-second schedule is separate
from the native timing: the observed match-6 Kraken creation is 17.023254
VGR seconds after Gold death. Captured Kraken corpse duration has no native
record here and uses an explicit 3.8-second policy.

Camp respawns now use **60 seconds for Treants in A/C and 50 seconds for
bears in B/D**, anchored to the final living member's death. The follow-up
in [native camp respawn reconciliation](solo-sandbox-camp-respawn.md) replaces
the old 85/71-second chunk estimates with 26 complete generations from two
native matches, including the original match-2 source. Every generation
is joined by native class/archetype and unchanged spawn position. All 13
`vgfull` intervals match byte-equal TCP events within 0.014808 seconds.
The earlier broad clock caveat is therefore not a reason to retain these
incorrect camp estimates. The separate hero UI-clock observations in
mechanics §19.3 remain limited to their own sessions. Fresh native respawns
use new EIDs; compact slots can be reused after removal.

Reproduce the bounded timestamp census:

```powershell
python Tools/Teardown/inspect_jungle_lifecycle.py --pcap "$env:TEMP/vg_max/vgfull.pcap" --match b9f511e0-11cd-4cfa-ad62-dc8612b8d270 --limit 4
python Tools/Teardown/inspect_jungle_lifecycle.py --vgr "$env:TEMP/vg_phaseB/vgr_live/cache" --match a683aa80-9811-47c3-bb64-0731a802e889 --limit 4
```

## Captured actor adapter

The already-decoded Kindred manifest independently resolves:

| Registry symbol | Archetype |
|---|---:|
| `HF_GoldMiner` | 362 |
| `HF_Kraken_Jungle` | 363 |
| `HF_Kraken_Captured` | 364 |

Creation records prove jungle class `0x4dd5b7d0`. The adapter reuses the
external neutral-362 serializer for owned Gold, and the neutral-363 sibling
for registry-364 Kraken. It changes only identified fields:

| Field | Offset | Handling |
|---|---:|---|
| Archetype | 0 | Gold 362 or captured Kraken 364 |
| Class | 4 | Retains measured jungle class |
| EID | 8 | Fresh actor identity |
| Ground-plane position | 12, 20 | Current authoritative coordinates |
| HP/maxHP in 122-byte snapshot | 36, 40 | Current authoritative pools |
| Team-state columns | 96–98 | Selected team gets 1 in creation, 15 in snapshot |
| Compact actor slot | 116 | Fresh occupied slot, shared allocator |
| Actor-specific index | 120 | Preserves neutral template's 255 by default |
| Team | 121 | Capturing team 1 or 2 |

The old +120=`team - 1` assumption was wrong. Native same-class Crystal
Miners use 4/5 for teams 1/2, while same-class owned shop actors use 255.
The exact purpose of this byte is unresolved. It can be varied only as an
explicit experiment via `capture_actor_index`; it is not used to establish
authoritative ownership. Team-state columns can also carry runtime
visibility bits; this adapter initializes the new team's measured state.

All unmapped bytes remain in externally loaded templates. Tests verify
that capture adaptation preserves every byte outside the allowed field
set. This is evidence about the serializer changes, not proof that the
client accepts this composition as native capture behavior.

With `experimental_capture=True`, capture publishes:

1. `1072` for the defeated actor, after the session's lethal `1054`.
2. A 126-byte `1010` creation for a fresh owned actor with a different slot.
3. A 122-byte `1010` snapshot for that actor's current/max HP.
4. `1070` at its current position.
5. After the corpse period, old-actor `1073`/`1035`, then slot release.

The Gold adapter supports enemy recapture, retaining each defeated faction's
corpse until removal. Kraken's authoritative movement still exits the pit,
joins the lane and targets vulnerable enemy structures. Both neutral and
captured objective creation include an HP snapshot under the experiment:
the recorded neutral Kraken has maxHP 15500, while the accepted sandbox
brief requests 5000. Gold uses the current server policy of 1800. The
snapshot explicitly expresses these server values.

## Session APIs and QA setup

Use the shared `ActorSlots` for every actor. Bind external creation/state
catalogs through `JungleManager(spawn_catalog=..., state_catalog=...)` or
`get_spawn_frames(catalog=..., state_catalog=..., actor_slots=...)`.
Reconnect reads state without advancing the simulation, in this order:

```python
frames = jungle_manager.get_spawn_frames(actor_slots=actor_slots)
frames += jungle_manager.get_state_1010_frames(
    catalog=native_actor_catalog, actor_slots=actor_slots)
frames += jungle_manager.get_death_frames()
```

This includes retained corpses with their old EIDs/slots and zero HP, then
replays their deaths. Removed actors are excluded. Do not rebuild captured
HP through an ungated exact-team template lookup: no such template exists.

For a short isolated local client experiment, set
`HALCYON_EXPERIMENTAL_CAPTURE=1` and `HALCYON_TRACE_WIRE=1` before launching
the local stack. Use the normal external `HALCYON_SPAWN_CORPUS` inputs.
For the QA session only, construct its manager with
`JungleRules(gold_spawn_at=10, kraken_spawn_at=45)`. Keep the normal default
240/900-second schedule for regular play. This is an explicit test setup;
the repository does not enable accelerated objective timing by default.

Observe these cases in the client and correlate them with the wire trace:

1. Kill a Treant and a bear: observe death animation, retained corpse, then
   removal; no corpse movement or attack. Wait for a fresh-EID camp respawn.
2. Capture Gold as team 1, then team 2: confirm the current owner, guardian
   target selection and displayed HP. The old corpse must not alias the
   new actor's slot.
3. Capture Kraken for each team: confirm model creation, team presentation,
   a 5000-point full health pool and movement toward enemy structures.
4. Reconnect once during the corpse period and once after removal: living
   ownership/HP/position and any retained corpse must agree with the server.
5. Run `Tools/Teardown/inspect_live_actor_order.py` on the resulting local
   trace to check creation, occupied slots and removal order. A clean trace
   does not replace the visible-client checks above.

If the default +120=255 capture experiment fails, record the actual failure
before changing the explicit `capture_actor_index` override. Do not claim
an inferred alternative index or a passing Python test is native behavior.

## Checks and open gates

The focused jungle/lifecycle, spawn, native actor, slot and reconnect set
passes 66 tests. This includes 22 complete native death chains, two Gold
self-retirement sequences, native registry resolution, both captured teams
and actor forms, opaque-byte preservation, corpse slot reuse and reconnect.
The read-only inspector reproduces the 32,640-frame `vgfull` and
112,686-frame match-6 cache censuses.

The team-1 Gold and Kraken captures below pass bounded visible-client checks.
Additional fidelity checks remain for team-2 capture/recapture and native
attack presentation beyond the live Treant check below; the full meaning of +120;
captured Kraken's native corpse timing; native capture-specific animations,
effects and notifications; native objective/hero UI-clock reconciliation.
These are not additional conditions for the completed jungle matrix row.
Ordinary camp timers are corrected as above. No proprietary payloads were
copied into the repository.

## 2026-09-08: naturally timed Gold and a real capture input

The same Gwen 395 match that passed the `1074` revival check continued on
PID 6488. External trace:
`$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`, connection
1788669376464. The default objective schedule remained 240/900 seconds;
there was no QA clock jump or accelerated objective rule. Neutral Gold
100012 appears in `1010` lines 12972/12973 at 1788804506.7349906/.7381608,
archetype 362, class `0x4dd5b7d0`, team 0, slot 49, HP 1800/1800.
The natural 240-second spawn and current 1-gold/second policy reach the
300-gold cap by simulation time 540, before this capture around time 727.
The fill rate remains an explicit sandbox policy.

QA journal `$TEMP/halcyon_qa_gwen3_20260908/journal.jsonl` records the
combat fixture precisely: 1750 true damage at tick 13905/time 695.25
reduced the Miner from 1800 to 50 HP; request
`2301a336851f4bd987093fb1579e30d1` completed normally. Gwen was refilled at
695.6. Thus the final hit/capture path was exercised by actual client
input, but this was not a full-health monster combat test.

An actual screen tap at (470,275) produced this sequence:

| Event | Trace line | Wall timestamp | Decoded result |
|---|---:|---:|---|
| Client `1060` target | 36039 | 1788804991.7243633 | Gold 100012 |
| Server `1045` attack | 36040 | 1788804991.7280064 | Gwen 1500 → 100012, ordinary action 8 |
| Server `1070` attack position | 36041 | 1788804991.7287693 | Gwen's current position |
| Lethal `1054` | 36047 | 1788804992.1130445 | Victim 100012, source 1500, −52.047619, class5/type0 |
| Friendly gold `1053` | 36049 | 1788804992.1144223 | EID 1500, type6, +300 |
| Friendly gold `1053` | 36054 | 1788804992.1170670 | EID 1515, type6, +300 |
| Friendly gold `1053` | 36059 | 1788804992.1200507 | EID 1516, type6, +300 |
| Old actor `1072` | 36063 | 1788804992.1224384 | Victim 100012, killer 1500 |
| Owned actor `1010` creation | 36064 | 1788804992.1230520 | New EID 100013, archetype362, team1, slot50 |
| Owned actor `1010` snapshot | 36065 | 1788804992.1235836 | HP 1800/1800 |
| Owned actor `1070` | 36066 | 1788804992.1241636 | Pit position (0,23.6) |
| Old corpse `1073` | 36250 | 1788804995.9165100 | EID 100012 |
| Old actor `1035` | 36251 | 1788804995.9170456 | EID 100012, release slot49 |

There are exactly three +300 type6 awards in this capture burst and none
for an enemy hero. XP and level notifications interleave those awards;
they are not additional gold payouts. The outgoing lethal damage value is
52.047619 against the server-prepared 50 HP; the trace value is preserved
here rather than relabelled as the clamped HP loss.

The new actor's creation team columns are `[0,1,0]` and snapshot columns
`[0,15,0]`; both retain actor-specific index +120=255 and team +121=1.
The neutral actor used `[1,0,0]`/`[15,0,0]`, index255, team0. The defeated
slot49 remains occupied while the replacement uses slot50. Removal occurs
3.794607 wall seconds after `1072`, consistent with the 3.8-second corpse
schedule. The actor-order inspector reported zero creation, reference or
occupied-slot problems at the audit checkpoint.

Inspected external screenshots:

- `$TEMP/gwen3-goldminer-ready.png`: rendered neutral Gold Miner in the pit.
- `$TEMP/gwen3-miner-low.png`: the prepared encounter; 50 HP is established
  by the QA acknowledgement, not a numeric readout in this image.
- `$TEMP/gwen3-miner-capture.png`: a standing blue team-owned Gold Miner
  with a blue bar after capture, while Gwen receives level presentation.

These observations establish one team-1 adapter capture, its actual target
and attack input, the three server gold awards, visible faction change,
and separate corpse/replacement identities. They do not establish every
native capture animation or notification, exact UI HP numbers, enemy
recapture, guardian combat, reconnect during the corpse overlap, or Kraken
capture. The adapter remains an explicit local composition experiment.

Reproduce the read-only ordering audit:

```powershell
python -B Tools/Teardown/inspect_live_actor_order.py "$env:TEMP/halcyon_stack/wire-1788804074149933400.jsonl"
```

No production code, client input or QA state was changed during this audit.

## 2026-09-08: natural Kraken capture and complete siege

The Gwen395/PID6488 match continued on external trace
`$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`, connection1788669376464,
with the unchanged240/900-second objective schedule. At the natural900-second
boundary owned Gold100013 retires with self-directed−10000 `1054` at
line45203/time1788805165.5465672 and `1072` at45204/.5474207. Neutral
Kraken100014 is created at45205/.5478394: archetype363, class`0x4dd5b7d0`,
team0, slot57, with HP5000/5000 in122-byte state45206/.5494037. Old Gold
`1073`/`1035` follow at45414/45415, approximately3.806 wall seconds later.

The neutral Kraken damaged Gwen in ordinary simulation. The first QA damage
attempt at927.75 and self-refill at928.9 were rejected because Gwen was dead;
they changed no state. After her subsequent revival, a self-teleport at981.65
and accepted true-damage request`2c600cf45ce9493e83adf6cfb87c1823` at
tick19644/time982.2 prepared the Kraken at10/5000 HP. These acknowledgements
are in`$TEMP/halcyon_qa_gwen3_20260908/journal.jsonl`. The preparation reduces
the combat required for the final-hit check; it does not prove full-health
combat. There were no objective-clock mutations and no captured-Kraken
teleports or damage fixtures during its subsequent siege.

| Event | Trace line | Wall timestamp | Decoded result |
|---|---:|---:|---|
| Actual client`1060` | 49096 | 1788805248.7687702 | Target100014 |
| Gwen`1045` | 49098 | 1788805248.8014827 | Source1500, target100014, action8 |
| Lethal`1054` | 49111 | 1788805249.1044580 | Victim100014, source1500,−24.219999, class5/type0 |
| Neutral`1072` | 49112 | 1788805249.1050484 | Victim100014, killer1500 |
| Owned creation`1010` | 49113 | 1788805249.1055200 | New100015, archetype364, team1, slot67 |
| Owned state`1010` | 49114 | 1788805249.1063710 | HP5000/5000 |
| Owned initial`1070` | 49115 | 1788805249.1069890 | (0,23.60000038) |
| First moving`1070` | 49116 | 1788805249.1205838 | (−0.132407,23.670486) |
| Neutral corpse`1073` | 49374 | 1788805252.9065993 | Old100014 |
| Neutral removal`1035` | 49375 | 1788805252.9072232 | Release old slot57 |

The new creation's team columns are`[0,1,0]`; state columns are`[0,15,0]`.
Actor-specific index+120 stays255 and team+121 is1. Its slot67 is distinct
from the retained neutral corpse's57. The corpse removal occurs about3.8022
wall seconds after death. Captured364 remains a local composition using
the neutral actor layout and the independently recovered archetype registry;
the recording corpus still contains no native captured364 creation golden.

All882`1070` positions of100015 are on the external A001 mesh, with no
blocked chord between adjacent samples. Total sampled distance is132.057741
units. The route leaves the pit, passes within0.053089 units of lane(0,0)
at line49929/time1788805262.090017, then reaches the enemy structures.
The last position is line55333/time1788805357.5921328 at
(75.589691,16.457762). Wall timestamps are used for ordering, not speed
calibration. Damage components retain the sandbox271 weapon+70 true policy.

| Enemy structure | Kraken damage packets | HP removed by Kraken | Death line / timestamp |
|---|---:|---:|---|
|3539 outer|13|2162.5|50720 /1788805276.461618|
|3540 middle|18|3000|51853 /1788805296.8527024|
|3541 base|21|3500|53230 /1788805320.389954|
|3543 Vain turret|18|3000|54479 /1788805341.334069|
|3542 Vain turret|18|3000|55243 /1788805355.8462765|
|3544 crystal|59|10000|57615 /1788805404.0116622|

All six final killers are100015. Outer3539 had337.5 damage from five earlier
other-source hits; the other five structures receive no non-Kraken damage.
Final crystal`1054` is line57613/time1788805404.0107665; `1106` at57614/
.0111947 has body`000000000000`, followed by the crystal death. The normal
result`1009` arrives at57621/time1788805409.981557 with body
`000000010000`, a5.9703623-second wall gap after`1106`.

Inspected screenshots under`$TEMP` show neutral Kraken damaging Gwen
(`gwen3-kraken-spawn.png`), a blue owned Kraken leaving the pit
(`gwen3-kraken-capture.png`), its arrival among enemy turrets
(`gwen3-kraken-turrets.png`, `gwen3-kraken-attack-visible.png`), and Victory
with result clock19:13 (`gwen3-kraken-victory.png`). The static image named
“attack-visible” does not establish animation: the completed trace has
zero1045 sourced by either Kraken actor. This run passes the bounded
natural spawn, prepared final-hit capture, faction model, route, damage,
corpse separation and result flow. Jungle attack animation required the
separate repair below and a fresh client check.

## 2026-09-08: grounded jungle attack actions

The missing attack presentation was in both `Monster.step` and the captured
Kraken siege path: they applied damage without a native1045 action. They now
emit one1045 per existing attack cadence, before the existing damage callback.
The Kraken's weapon and true components share that single action. Capture
resets the deterministic0/1 cycle for the fresh actor. Damage amounts,
cooldowns, contact timing, routing and capture scheduling are unchanged.

NPC metadata uses the direct pointer vector at first-revision PTCH+100.
Each entry's Ability__ symbol is referenced at entry+4. This differs from
the hero kit/shared/attack-group flattening at+108. The read-only
`Tools/Teardown/inspect_jungle_actions.py` reproduces the bounded structural
join without exporting INST payloads. The external CFF paths, relative to
`D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data`, are:

| Archetype | CFF path | Selected action entries |
|---|---|---|
|357 Treant|49/49C06DCA45B7A62D1658D7060775CDF9|0/1 DefaultAttack|
|358 Elder Treant|1D/1D445E1A9C41B6C0219159F85DD681CE|0/1 DefaultAttack|
|359 Big Bear|1B/1B0FA18811EC4D6F6027BF06081F9A5F|0/1 DefaultMeleeAttack|
|360 Small Bear|9A/9A66B107F6CF9BAB912D7DAD1436CBCF|0/1 DefaultMeleeAttack|
|361 Crystal Miner|5E/5EC683C4C7E2442DC2884382FB31F70A|0 DefaultRangedAttack,1 AltRangedAttack|
|362 Gold Miner|6F/6F2963E4A635C92A389523AA51F30969|0 DefaultRangedAttack,1 AltRangedAttack|
|363 neutral Kraken|F3/F30335D5EF888FC30E4944D370B9EC51|0 DefaultAttack,1 AltAttack|
|364 captured Kraken|95/95C3C182530326BD98A1D38E4289E28C|0 DefaultAttack,1 AltAttack|

The canonical recording census contains693 NPC1045 actions:357 has194,
358 has19,359 has286 and360 has194; all use0/1. The tests compare eight
complete independently recorded1045 payloads and later class5 damage pairs,
covering both variants for each of those four archetypes. Both Kraken CFFs
identify index2 as CritAttack and index3 as Spawn; captured adds4 Victory.
Those special entries are excluded. Treants also have additional actions
that are not selected by this bounded ordinary policy.

The recording join also corrects an initially considered hero analogy:
all693 NPC1045 actions immediately have1086 kind61, not the heroes'1070
pair. This repair emits the grounded1045 itself; ordinary movement replication
continues separately. Auxiliary kind61 semantics, native variation selection
and exact windup/contact timing remain uncalibrated. Alternating0/1 is explicit
deterministic presentation policy.361–364 use source-derived ordinals;
they do not yet have independent recorded1045 goldens in the local corpus.

Validation:53 focused tests pass across jungle action evidence, jungle,
objectives, session integration, death lifecycle and native camp respawn.
The five new tests cover all eight external CFFs, eight full native action
and damage pairs, every configured neutral monster's cadence, non-attacking
states and one captured-Kraken action for its two damage components.
A new client run must validate the added animations; the preceding Gwen
Victory trace predates this code. No proprietary payload entered the repo.

## 2026-09-08: natural Treant kill and three attack-burn ticks

The fresh Celeste 285 match is recorded in
`$TEMP/halcyon_stack/wire-1788808981133504900.jsonl`, connection
1920953706832. Line numbers below are one based. The journal at
`$TEMP/halcyon_qa_celeste2_20260908/journal.jsonl` records an A learn at
simulation 19.6 and a positioning fixture at 19.8, projected to
(−46.401685,20.098290). Neither operation supplies damage or a buff.
No QA damage or health/resource command precedes the Treant's death.

Actual target input `1060` at line 3869 / epoch 1788809098.3381236 names
Treant 100000. Celeste's first `1045` is line 3877 / 1788809098.5046246.
Thirteen ordinary class-5 crystal `1054` records name victim 100000 and
source 1500, each with damage −60. The first is line 3900; the final one
is line 4570 / 1788809108.4407306. Native death `1072` immediately follows
at line 4571 / 1788809108.4410899, naming killer 1500. This is a normal
basic-attack kill from full camp HP, including the final overkill amount
in the emitted damage value. `1073`/`1035` remove the corpse at lines
4755/4756 / 1788809112.4741528/.4747388. CampA's ordinary kill handler
grants the weapon buff; this buff currently has no separately decoded
wire grant marker.

After that kill, QA positions Celeste at (0,35), simulation 91.05, and
Baptiste 1517 at (4,35), simulation 91.3. No QA mutation intervenes in
the following action and burn interval. Actual `1060` at line 7343 /
1788809163.3785257 targets Baptiste; Celeste `1045` follows at line 7345 /
1788809163.3815231. The primary crystal contact at line 7359 /
1788809163.8189225 is −68.0143585. Actual movement input at line 7366 /
1788809164.1470258 stops further basic attacks. Exactly three additional
class-5/type-4 true-damage contacts name victim 1517 and source 1500:

| Burn | `1054` line | Wall timestamp | Damage |
|---|---:|---:|---:|
|1|7410|1788809164.8682024|−10|
|2|7464|1788809165.8435907|−10|
|3|7517|1788809166.8211071|−10|

There is no item purchase, item activation, ability cast or further attack
between the primary hit and the end of these ticks. Viewed
`$TEMP/halcyon_stack/celeste2-treant-burn.png` shows the floating **10**
on level-2 Baptiste beside level-3 Celeste, client clock 2:07. The packet
identities, unchanged source and exact three 10-damage ticks establish
the implemented Treant-kill → weapon-buff → basic-attack burn chain.
Together with the previously recorded full Gold Miner payout and natural
Kraken capture/push, this meets the bounded jungle acceptance scenario.
The camp assignment and buff coefficients remain explicit sandbox policy.

## 2026-09-08: Treant pursuit range boundary repair

The same match also exposed a separate neutral retaliation defect before
the Treant's death. Its authoritative coordinates stopped at
(−45.379500,17.534555), with Celeste at (−46.120217,19.392334).
Their distance is 2.000001121732185, slightly beyond its 2-unit range.
Wire positions repeat at lines 4097 onward, with no Treant `1045` or
Treant-to-Celeste `1054`. A standalone reproduction at those exact server
coordinates repeats `1070` without movement for six 50 ms steps: the old
float residual caps speed below a fixed-point movement quantum.

`Monster.step` now uses the shared integer `within_distance` predicate
and computes pursuit distance on the same coordinate grid, aiming two
coordinate quanta inside attack range to account for axis truncation.
This changes neither attack range nor cooldown. The actual-coordinate
regression fails before the fix, then proves a movement step without early
damage, entry into the nominal radius, and one ordinary `1045`/`1054` pair
on the next tick. All 54 focused jungle, objective, lifecycle and action
tests pass. Source is frozen after this repair. This loaded client trace
predates the fix, so neutral retaliation animation still needs a fresh
client check; the successful Treant kill/burn chain does not prove it.

## 2026-09-08: Gwen4 live Treant range-repair pass

Fresh Gwen 395 trace `$TEMP/halcyon_stack/wire-1788810206949588100.jsonl`,
connection 2598410757328, loads the neutral range correction. QA positions
only the player at simulation 510.75, request
`1ae76a180f8c45fdad46c112b8fd8002`, projected to
(−46.401685,20.098290). The journal contains no Treant 100000 position,
damage or status preparation for this fight.

Actual `1060` at line 29350 / epoch 1788810805.9605842 targets Treant
100000. Gwen starts her ordinary attack at line 29352 and hits at line
29382. The Treant pursues her from approximately 5.5 units away, following
the terrain route. Its last approach position at line 29611 /
1788810809.094782 is (−45.6609688,18.2405148), approximately 1.9999964
units from Gwen's unchanged published position. The next tick starts its
ordinary action rather than stalling outside the 2-unit boundary:

| Treant attack | `1045` line / wall timestamp | `1054` line / wall timestamp | Damage to Gwen |
|---|---|---|---:|
|Action 0|29612 / 1788810809.1475673|29613 / 1788810809.1480205|26.027466|
|Action 1|29688 / 1788810810.4101572|29689 / 1788810810.4105434|26.027466|

Both damage packets name victim 1500 and source 100000. At level 9,
Gwen's armor 61.368 gives `42 / 1.61368`, matching each f32 damage value.
Viewed `$TEMP/halcyon_stack/gwen4-treant-retaliates.png` shows the ordinary
close-range exchange and level-9 Gwen. Its visible 89 is Gwen's hit on the
Treant; the packet pairs above establish the Treant's retaliation damage.

This passes the bounded live pursuit, attack-admission and repeat-cadence
check for the range repair, in addition to its 54 focused tests. Native
attack ordinals 0/1 now occur in the loaded client fight. Exact native NPC
windup, release and visual-contact synchronization remain uncalibrated;
the current jungle action and damage remain in the same simulation tick.
No source changes were made for this acceptance audit.

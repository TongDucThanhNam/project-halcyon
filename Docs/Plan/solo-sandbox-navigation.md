# Solo sandbox: navigation, actor lifetime, waves and attack presentation

2026-09-07 implementation and corpus audit. This is a record of measured
contracts and explicit sandbox rules, not a claim that live-client acceptance
or full Vainglory fidelity is complete.

## Terrain and deterministic movement

`server/navigation.py` reads the operator's external Halcyon Fold A001 mesh.
The local verified source is:

```text
D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/4B/4BD271EAAC785AEB0C2BCED99515D401
```

It has 793 vertices and 832 triangles. No mesh data is copied into the repo.
Set `HALCYON_NAVMESH` to use a different operator-owned copy. Missing or
malformed input fails explicitly; it does not fall back to straight-line
travel through walls. Format reference:
`Docs/Teardown/vainglory-3v3-map-structure.md`.

Positions use a lattice of one million units per world unit. Triangle A*
uses integer costs and deterministic ties; visibility smoothing removes
unnecessary portal waypoints. Clicks outside the mesh project to a walkable
edge; disconnected destinations do not yield a wall-crossing route. Ordinary
movement and knockback clamp to the walkable segment. Dash crossing follows
the attachment's rule: a requested endpoint past the midpoint of a thin wall
can land beyond it, while a thick wall stops the dash at its near edge.

Movement speed is evaluated each tick as:

```text
((1 + attr_0x284) * attr_0x11C + attr_0x68) * (1 + attr_0x1D0)
```

Hero movement, minion pursuit and jungle pursuit use the same mesh. Path
planning is repeated after a moving target shifts by at least 0.25 units.

The nearest-point query formerly projected onto every edge using Fraction
objects. It now visits conservative triangle bounds in distance order,
uses exact integer rational projection, and caches bounded immutable queries.
The rounding and distance/index/coordinate tie order remain unchanged. An
independent comparison against the former exhaustive Fraction calculation
matched all coordinates and triangle IDs for 66 queries across the external
mesh, including obstacle and off-map regions: 2,405.55 ms became 35.79 ms.
The 60-second production workload then met all 1,200 fixed-tick deadlines:
maximum 29.79 ms, previously 88.96 ms; p99 13.50 ms, previously 40.61 ms.
These are local measurements, not a guarantee for arbitrary load or hardware.

A later 935–945-second workload exposed repeated path smoothing. Bounded
immutable full-path (4,096 entries) and segment-interval (16,384 entries)
caches now avoid recomputing identical geometry. Public route lists are
copied to prevent one actor mutating another actor's cached path. Forty-eight
actual-mesh paths and segments matched the uncached routines exactly;
mutation of every returned route left subsequent queries unchanged. A hot
batch of 4,800 path queries took 5.05 ms. The final production workload is
verified separately rather than extrapolating that microbenchmark.

### Late clipping bursts, 2026-09-08

The final old-fixture run exposed three repeatable CPU stalls at simulation
seconds 952.70, 956.55 and 956.75. Individual tick profiles identified bursts
of uncached path smoothing: respectively 12, 12 and 19 new paths performed
313, 226 and 390 raw segment clips. Clipping consumed 43, 31 and 59 ms of
the instrumented ticks. The aggregate 946–960-second profile had instead
been dominated by routine wave targeting. A separate garbage-collection
diagnostic found no collection within 0.12 seconds of any of these stalls.

Clipping now uses precomputed exact integer edge half-planes, rejects
triangles whose bounds are strictly disjoint from the segment bounds, and
returns once a convex triangle covers the entire segment. Boundaries and
corner touches remain inclusive. Integer rational interval comparisons and
the resulting union are preserved. Three independent exhaustive Fraction
oracle tests cover 449 segment cases, including holes, negative cells,
clockwise input, zero-length segments, external mesh routes and microunit
edge crossings. All 96 focused navigation, lifecycle and wave tests passed.

An external copy of the original failed source pin changed only
`server/navigation.py` and reran all 19,200 ticks. Its 4,379,174-byte wire
stream, 1,942,184-byte canonical final state and all 960 state checkpoints
were directly byte-equal to the original run. Coverage was also identical.
All ticks met 50 ms: p95 7.273 ms, p99 9.485 ms and maximum 26.428 ms.
The three former stalls measured 23.869, 18.638 and 26.428 ms respectively.
This original controller still completed no Recall; the strengthened final
fixture's full acceptance is recorded in `solo-sandbox-performance.md`.

Artifacts remain external under TEMP:
`halcyon-sandbox-exact-spikes-20260908/` contains the individual profiles;
`halcyon-sandbox-gc-946-960-20260908/gc-events.json` contains collection
observations; `halcyon-sandbox-nav-optimized-old-fixture-20260908/` contains
the isolated source copy and complete comparison run.

## Compact actor slots: the bootstrap collision correction

The byte at +116 in the 126-byte `1010` actor creation record is a reusable
actor slot. `1016 ActionMoveTo` addresses that same slot. It is **not** an
ever-increasing sequence counter. The six hero slots are 0 through 5.

The complete external `vgfull.pcap` contains 174 actor creations and 116 slot
reuses. Every reuse follows destruction and removal of the prior owner.
Example: frame 4583 assigns slot 34 to EID 4579 after EID 4315's `1073` at
4375 and `1035` at 4391. Every one of the 100 lane spawns has a subsequent
`1016` with its assigned slot; four captain spawns insert an attribute record
before that movement action.

`server/actor_slots.py` owns one map per match:

- `register(eid, slot)` records measured hero/static/tape mappings.
- `allocate(eid)` keeps an existing mapping or chooses the lowest free slot.
- `release(eid)` frees a removed actor; hero death does not remove its actor.
- `observe(opcode, payload)` registers 126-byte creations and observes `1035`.

Jungle, lane, static and hero publication share that allocator. A reconnect
keeps the original mapping. Live ownership conflicts and capacity exhaustion
raise an error instead of wrapping onto a hero or another living actor.

The live bootstrap trace exposed five actual collisions in the previous
counter implementation: slots 28 through 32, still owned by EIDs 3561 through
3565, were overwritten by jungle EIDs 100000 through 100004. Counting the
26 static tape records was not equivalent to reading their assigned slots.
The session now seeds the allocator from each record's actual EID and slot.

## Jungle creation and objectives

`server/entity_spawn.py` loads external 126-byte actor templates instead of
embedding unknown serializer bytes. `HALCYON_SPAWN_CORPUS` accepts directories
containing the operator's VGR chunks, separated by the OS path separator.
Default local inputs are under `$TEMP/vg_phaseB/vgr_live`,
`$TEMP/vg_max/vgr5/vgr5` and `$TEMP/vg_max/vgr/vgrtmp`.

The decoded registry and corpus agree on these archetypes:

| Archetype | Actor |
|---|---|
| 357 | Treant |
| 358 | Elder Treant |
| 359 | Big Bear |
| 360 | Small Bear |
| 361 | Crystal Miner |
| 362 | Gold Miner |
| 363 | Neutral Kraken |
| 364 | Captured Kraken, registry-proved only |

The measured jungle class is `4dd5b7d0`; +0 is the archetype and +8 is the
actual actor EID. Unresolved bytes +92 through +95 vary between captures and
remain in the external template. Known identity, position, facing and actor
slot fields are patched explicitly. Jungle EIDs start at 100000 to avoid
collision with lane allocation, which starts at 4610.

Gold Miner appears at 240 seconds at `(0, 23.6)`, accumulates up to 300 gold,
pays the capturing team and remains as its guardian. Kraken appears at 900
seconds, replaces Gold Miner, and uses the requested 5000 HP, 400 armor and
100 shield. Capturing it changes authoritative ownership and sends it via
the lane to vulnerable enemy structures.

Neutral Kraken creation is directly measured in match
`a683aa80-9811-47c3-bb64-0731a802e889`, chunk 72, row 1062 under
`$TEMP/vg_phaseB/vgr_live`. An 830-file VGR scan found no archetype-364
creation. Faction-changing actor replacement is therefore an explicit
own-client adapter behind `HALCYON_EXPERIMENTAL_CAPTURE`, with bounded
team-1 Gold/Kraken live acceptance recorded in the jungle leaf. It does not
claim complete native capture-protocol recovery. The adapter emits death for the defeated actor,
retains its corpse/slot, and creates a fresh owned actor with an explicit
current/max-HP snapshot. Lethal damage still addresses the old EID before
those messages. The old assumption that +120 means `team - 1` was falsified;
that actor-specific byte is preserved. See
[jungle wire lifecycle and client QA](solo-sandbox-jungle-wire.md) for the
22 native death chains, capture adapter, faction evidence and remaining gates.

The attachment leaves several coefficients unspecified. Current sandbox
policy is gold fill 1 per second, buffs for 90 seconds, Weapon Buff slow 15%
for 2 seconds and 10 true damage per second for 3 seconds, Crystal Buff +30
CP and +5 energy regeneration. These are explicit implementation choices.

## Waves and formation

The measured wave cadence is 25 seconds; the first wave begins at 22.974
seconds. The requested sandbox composition is three melee and two ranged
units per side, with one extra siege unit every third wave. Melee range is
2 units and ranged range is 6.5. Registry 367 is siege; 368 is captain.
`corpus_profile=True` preserves the previous measured wave composition for
comparisons instead of conflating it with the attachment's desired profile.

Current policy increases HP 10% and damage 5% per elapsed spawn minute and
uses 0.75-unit ally spacing. Survivors pursue targets and then vulnerable
structures. In a standalone lane without structures they close the next
enemy formation instead of parking just outside aggro range and blocking
all subsequent waves. Paused movement time is not accumulated into a later
teleport.

The early spawn grammar is verified: `1010`, slot-addressed `1016`, current
`1070`, then measured visibility-field messages `1067`. Visibility messages
are not movement or animation state selectors. Fifty early `vgfull` lane
spawns match the current builder byte for byte. Fifty later spawns vary
bytes +88 and +119. Their exact growth/stage meaning remains open, so the
server's stat-growth rule does not establish matching native growth display.

### Lane death, corpse retention and reconnect

The full `vgfull.pcap` contains 83 lane-minion removals. Every one has a
preceding `1072 [victim EID][killer EID][six zeros]`. Death precedes `1073`
by 3.759–3.861 seconds of TCP receive time; `1073` and `1035` themselves
share the same receive timestamp in all 83 cases. The implementation uses
a fixed 3.8-second corpse period. This is a measured approximation of the
native timing, not evidence for an arbitrary delay between destroy and removal.

For EID 4315, the lethal `1054` is frame 3753 at 73.905560 seconds from the
capture origin; death `1072` is frame 3761 at 74.005112; destroy `1073` is
frame 4375 at 77.788933; removal `1035` is frame 4391 at that same instant.
Its slot 34 is subsequently reused by EID 4579 at frame 4583. This corrects
the old immediate `1073`/`1035` minion-death path, which omitted `1072`.
It has not yet established that this omission caused the live client crash.

`Director.on_minion_death(victim, killer_eid, now)` sets HP to zero,
prevents further movement and attacks, emits `1072`, and retains the compact
slot. `pump` emits the due `1073`/`1035` pair and releases the slot before
allocating any new wave actors. Repeated damage/death calls do not duplicate
the lifecycle. Reconnect includes retained corpses through creation,
zero-HP snapshot and `get_death_frames()`; removed actors are excluded.

### Native static creation and current actor state

`NativeActorCatalog` reads external records with the actual nonhero identity
layout: archetype at +0, class at +4, EID at +8, position at +12/+20, compact
slot at +116 and team at +121. A 126-byte creation has no HP fields. The
122-byte VGR snapshot carries current/max HP at +36/+40 and retains the slot
at +116; it does **not** shift that slot four bytes earlier. Unknown fields
remain in the external template. No proprietary payload fixture is added.

The static class is `0xc10b41da`: archetypes 371/370/369 are outer/middle/base
turrets, 372 is a Vain turret, and 292/293 are the two Vain crystals. All
twelve authored placements are retained so shared archetypes keep their
individual height and facing. Across eight audited matches, Vain turret
snapshots have maximum HP 3000; the old 5000 premise was wrong and the four
server Vain turrets now use 3000. Other turret and crystal HP tiers are
unchanged. The test validates all 24 retained structure creation/snapshot
templates byte for byte against the external source.

`StructureManager.get_spawn_1010_frames()` now builds actual 126-byte
creations, including persistent destroyed structures. Its separate
`get_state_1010_frames()` reads current HP. Lane reconnect helpers likewise
retain current EIDs, slots, positions and HP without scheduling a new wave.
The 122-byte form is proved in VGR state snapshots; its live reconnect use
is an explicit client integration experiment and remains to be validated.

## Hero energy, recall, death and resurrection

`1053` uses resource type 0 for HP, 2 for energy, and 6 for gold. Damage event
`1054` is victim first, attacker second. Ordinary damage is sent once via
`1054`; a duplicate negative-HP `1053` would apply the same loss again.
Energy spending and positive regeneration use their corresponding `1053`.

Recall channels for 4 seconds, cancels on movement/damage/control, and
teleports to the friendly spawn with `1070`. Friendly fountain regeneration
adds 15% max HP and energy each second. The enemy fountain deals the
requested 1000 true damage per second. Dynamic respawn uses the requested
`6 + level * 2.5` seconds plus the explicit policy of one second per completed
match minute.

`server/lifecycle_wire.py` implements the actual hero lifecycle:

| Event | Opcode and fields |
|---|---|
| Death | `1072`: victim EID, killer EID, six zero bytes |
| Countdown | `1075`: EID, float seconds, six zero bytes |
| Corpse hiding | `1073`: EID and two zero bytes, approximately 1.8 seconds after death; no `1035` actor removal |
| Pre-return | `1033`: EID, x, measured spawn height, y, flag 1 and five zero bytes; hero remains dead |
| Position confirmation | `1070`: EID, x, y, zero tail |
| Completed revival | `1074`: EID, x, the same height and y, six zero bytes; approximately 0.3 seconds after pre-return |

All six deaths, six countdowns and five resurrections in `vgfull` match the
builders byte for byte. The original two-frame resurrection check omitted
the preceding `1073`; the local Baron client subsequently remained in its
death pose after the server sent `1033`/`1070`. The complete five native
intervals and seven local-player VGR intervals all include corpse hiding
before resurrection. Adding corpse hiding alone did not resolve the client
failure; the final native `1074` was also missing. All 129 expanded-corpus
flag1 returns precede `1074`, and native snapshots between the two actions
still have zero HP. The server now sends `1033`/`1070` 0.3 seconds before
the deadline while keeping the hero dead, then `1074` at the deadline to
complete revival. It retains the actor slot throughout. Slots 1500 and 1515 use measured height 1.3;
1517, 1518 and 1519 use 1.5. The full correction, exact origins and the
successful fresh Gwen client acceptance are in
[solo-sandbox-hero-respawn.md](solo-sandbox-hero-respawn.md).

No full-HP/full-energy delta accompanies the final native `1074`; a local
snapshot after it shows full HP/energy. The earlier claim that `1033`
restores pools was false: it only starts the return transition. The old `1162` tag
`b855d752` is an initialization record, not a death countdown: it occurs
exactly once for each of the six heroes before play. Its float starts at
+12, not +10.

## Basic attack presentation and unresolved cycle timing

`server/attack_wire.py` emits `1045` followed immediately by `1070` for the
attacker's **current** position at each windup start. `1045` is source EID,
target EID, one observed variant byte and five zero bytes. It repeats for
each attack against the same target; a one-time target-acquire message does
not reproduce the observed stream.

Adagio uses variants 7 and 8 in 127 ordinary attacks; Baptiste uses 7, 8, 10
and 11 in 108 attacks. Every one of these 235 actions has the immediate
source-position message. Variant semantics remain unresolved. Selecting
among observed variants deterministically is presentation policy, not a
claim to recover the native selector. No independent Adagio basic-projectile
builder is established by this audit; live attack/projectile animation is
still an acceptance check.

A second bounded audit joins `1006` hero IDs to `1045` and matching negative
`1054` class-5 damage in 591,070 frames across 11 canonical VGR matches.
`attack_wire.MEASURED_BASIC_VARIANTS` supplies ordinary candidate variants for
28 recorded kits; uncovered kits return `None`, without borrowing another
hero's action. Special or empowered variants are excluded from this default
selection. In particular, Baptiste 10/11 corresponds to initial damage 78,
while the 7/8 examples deal 105.3, consistent with an empowered attack.

| Hero ID | Registry identity | Ordinary candidate variants |
|---|---|---|
| 242 | Catherine | 9, 10 |
| 244 | Adagio | 7, 8 |
| 245 | Koshka | 9, 10 |
| 253 | Joule | 7, 8 |
| 254 | Hero009 | 7, 8 |
| 256 | Sayoc | 11, 12 |
| 258 | Vox | 10, 11 |
| 260 | Hero016 | 10, 11 |
| 265 | Skye | 13, 14 |
| 266 | Reim | 7, 8 |
| 267 | Kestrel | 7, 8 |
| 268 | Alpha | 9, 10 |
| 274 | Ozo | 14, 15 |
| 275 | Lance | 8, 9 |
| 279 | Phinn | 7, 8 |
| 393 | Flicker | 7, 8 |
| 396 | Grumpjaw | 10, 11 |
| 397 | Tony | 10, 11 |
| 399 | Baptiste | 10, 11 |
| 408 | Churnwalker | 8, 9 |
| 409 | Lorelai | 7, 8 |
| 418 | Magnus | 7, 8, 9 |
| 432 | Silvernail | 9, 10 |
| 439 | Yates | 8, 10, 12 |
| 913 | Leo | 8, 9 |
| 915 | Caine | 8, 9 |
| 924 | Viola | 11, 12 |
| 925 | Amael | 8, 9 |

Amael's direct examples are match `0e7de8af-96d9-4e3a-b3c2-609ed5e71120`,
chunk 15 rows 1057→1096 (variant 8) and chunk 29 rows 252→285 (variant 9),
under `$TEMP/vg_phaseB/vgr_live`. Koshka's example is match
`591146df-33f2-4f12-9a04-8d800d239821`, chunk 5 rows 815→870, under
`$TEMP/vg_max/vgr2`. Phinn's examples are match
`045f86d4-7ef2-4125-a835-e70a96288c88`, chunk 4 rows 344→361 and 1067→1082,
under `$TEMP/vg_max/vgr5b`. These full payload pairs are checked from external
files, alongside Catherine's recorded variants.

The initialization timer tagged `d60c580b` is not sufficient evidence for a
hero's complete basic-attack cycle. Its native symbol is unresolved. In
`vgfull`, Baptiste has timer 0.7 seconds, but starts attacks at receive times
70.378530, 71.387102 and 72.394655 seconds, with impacts approximately 0.20
seconds after each action. Adagio has the same timer, first measured start
spacing 1.012785 seconds and approximately 0.60-second action-to-impact delay,
which includes flight. Receive timing and bot scheduling do not identify
the exact native windup/recovery formula. Do not replace an explicit cycle
policy with this timer while claiming a measured full cycle.

Reproduce the independent attack, slot and wave audit:

```powershell
python Tools/Teardown/inspect_attack_sequence.py --pcap "$env:TEMP/vg_max/vgfull.pcap" --match b9f511e0-11cd-4cfa-ad62-dc8612b8d270 --source-eid 1516 --limit 3
python Tools/Teardown/inspect_attack_sequence.py --vgr "$env:TEMP/vg_phaseB/vgr_live" --match 0e7de8af-96d9-4e3a-b3c2-609ed5e71120 --variant-census
```

The inspector reads captures only and prints scalar findings. Pcap times
are completion times from the first observed TCP bytes; VGR times use the
record's float timestamp. Neither is silently treated as an engine tick.

## Checks

The latest focused static/reconnect, minion-lifecycle, actor-slot, structure
and wave set passes 60 tests, including the 83 native minion removal chains
and full external structure payload comparisons. The earlier owned
navigation/lifecycle, jungle, wave, actor-slot and attack-wire set passed
132 tests, including external-corpus golden comparisons. A separate
1,000-second lane simulation completes without slot collisions. The slot
regression covers 600 successive minion creations and removal-based reuse.
The production benchmark is tracked separately by `Tools/verify_sandbox.py`.
No commits were made. Live client gameplay and the unresolved capture,
growth-field, variant-selection and exact attack-cycle meanings remain
separate acceptance gates.

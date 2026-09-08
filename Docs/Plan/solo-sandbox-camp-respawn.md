# Native camp respawn reconciliation

2026-09-08. `JungleManager` now respawns Treant camps **A/C after 60 seconds**
and bear camps **B/D after 50 seconds**, measured from the last living
member's death. The original brief does not override camp-return timers.
Its explicit Gold Miner **4:00** and Kraken **15:00** schedules are unchanged.

The former A=85 and B/C/D=71 values came from coarse chunk-index estimates.
They are contradicted by exact timestamps in the same original match-2
files, as well as an independent match with both replay and TCP capture.

## Identity and interval evidence

The read-only `inspect_jungle_lifecycle.py --camp-respawns` groups actual
126-byte `1010` creations by native class `0x4dd5b7d0`, archetype and map
placement. Each adjacent camp generation must contain all expected actors,
keep the same archetypes and exact float creation coordinates, use fresh
EIDs, and have each old actor's ordered `1072` then `1035` before new
creation. Incomplete or ambiguous groups are reported and excluded.

Camp names come from the measured map anchors, never from presumed actor
ID ranges. Bear offsets are within two units of their authored camp anchor.
The native A/C actors are archetype **357**; B contains two **359** actors,
and D contains two **360** actors. Each bear pair's timer starts at the
**later** death. Timing each sibling from its own death incorrectly creates
apparent periods longer than 50 seconds.

Two complete native series provide **26 camp intervals**, covering every
left and right A/B/C/D camp, with no incomplete or unclassified generations:

| Source | A | B | C | D |
|---|---|---|---|---|
| `b9f511e0…`, 13 intervals | 4: 60.029095–60.097252 | 4: 50.023705–50.055702 | 2: 60.028305–60.080078 | 3: 50.023788–50.089542 |
| `591146df…`, original match 2, 13 intervals | 4: 59.996834–60.080978 | 3: 50.011421–50.061230 | 3: 60.080273–60.080994 | 3: 50.012878–50.095108 |

Each table cell is `interval count: minimum–maximum seconds`. The small
fractional spread is retained as observed event timing, rather than rounded
away in the inspector. The simulation uses the nominal 60/50-second timers.

Original match-2 examples, all in the external directory
`$TEMP/vg_max/vgr2`, with filename prefix
`ea4c7fda-4b61-481d-abb7-1c757d24ae58-591146df-33f2-4f12-9a04-8d800d239821`:

| Camp and type | Prior → new EIDs | Last death, chunk:row | New creation, chunk:row | Timestamp interval |
|---|---|---|---|---|
| Left A, 357 at `(-40.915,20.251)` | 4685→6724 | `4:792` | `10:748` | 44.946995→105.011223 = **60.064228 s** |
| Left B, two 359 | 4683/4684→6597/6598 | `5:301` | `10:276/277` | 50.632389→100.693619 = **50.061230 s** |
| Left C, 357 at `(-21.95,24)` | 4682→7226 | `5:1177` | `11:1335` | 58.551327→118.631599 = **60.080273 s** |
| Left D, two 360 | 4680/4681→7298/7299 | `7:388` | `12:342/343` | 70.919754→121.014862 = **50.095108 s** |

Rows are zero-based inside each decoded chunk. B's unchanged creation
positions are `(-45.529999,32.229999)` and `(-43.419998,31.110001)`.
D's positions are `(-14.400001,37.669998)` and `(-12.510000,37.669998)`.
The EIDs in this table are observations identifying these records, not the
mechanism used to infer camp identity.

## Why the older estimate and clock caveat do not apply here

The original match-2 files contain explicit float timestamps. Chunk 0 spans
0→9.922937, chunk 1 spans 10.006063→19.974731, and chunk 2 spans
20.007982→29.861410. All 21 chunk-start timestamps are within 0.1 seconds
of `chunk_index * 10`. The former examples 56.5, 70.6, 84.7, 98.8 and
141.2 are instead reproduced by multiplying chunk indices by approximately
14.12. That coarse conversion must not override the actual record times.
It also put the Treant in C into the wrong 71-second bucket.

For match `b9f511e0-11cd-4cfa-ad62-dc8612b8d270`, each of the **13** complete
camp intervals has the same full native death and creation bytes in
`$TEMP/vg_max/vgfull.pcap` and `$TEMP/vg_max/vgr/vgrtmp/*.vgr`. The elapsed
times agree within **0.014807463 seconds**. Thus this is not merely a new
estimate made from replay chunk indices or a comparison between unrelated
matches. The TCP timestamp reconstruction accounts for all 32,640 frames.

This correction does not establish one clock model for every historical
practice-mode session. Mechanics §19.3's separately observed accelerated
hero UI clocks still have their original limits. Native `1075` countdown
durations also need their own client-presentation checks: in `vgfull`, five
countdown-to-revival receive intervals are about 0.216–0.267 seconds shorter
than their declared duration. They are not used to derive the camp timers.

## Implementation and checks

The production change is confined to `_get_respawn_duration`: A/C=60,
B/D=50. Corpse retention, last-member clear detection, rewards, fresh EIDs,
actor-slot release and objective schedules retain their existing behavior.
Existing tests that asserted the old premise now use the native deadlines
and preserve their death/removal/reward assertions.

Five new tests add:

- All 26 exact native intervals, camp types, stable creation bytes/positions
  and fresh identities, including the original four match-2 examples.
- A byte-exact cross-recording comparison for all 13 `vgfull` camp intervals.
- Rejection of an incomplete bear generation instead of substituting its
  earlier sibling's death as the full-clear time.
- All eight simulated camp deadlines: no early respawn, no timer reset on
  repeated corpse damage, complete fresh-EID return at the deadline.

```powershell
python -B Tools/Teardown/inspect_jungle_lifecycle.py --vgr "$env:TEMP/vg_max/vgr2" --match 591146df-33f2-4f12-9a04-8d800d239821 --camp-respawns --limit 4
python -B Tools/Teardown/inspect_jungle_lifecycle.py --pcap "$env:TEMP/vg_max/vgfull.pcap" --match b9f511e0-11cd-4cfa-ad62-dc8612b8d270 --camp-respawns --limit 4
python -B -m unittest server.test.test_camp_respawn_native server.test.test_jungle server.test.test_jungle_lifecycle server.test.test_jungle_session server.test.test_jungle_objectives -q
```

The 48 focused checks pass. A client process must load the corrected server
source before its live camp-return observation can validate these timers.
The visible spawn/death/return sequence remains a separate acceptance check.

The native B composition of two archetype-359 bears differs from the current
server's BigBear+SmallBear policy. This narrow timer correction records that
separate composition gap and does not silently change it.

## Proposed QA diagnostic fields

`SandboxQA.snapshot` currently tries `actor.kind.value`; jungle actors instead
have the string `actor.config.monster_type`, so their reported `kind` is null.
The following read-only additions were proposed to the agent owning that file
and are **not implemented by this timer pass**:

- Per jungle actor: class, kind, camp ID, current projected anchor, target,
  leash state, corpse-removal deadline, camp-return deadline and whether its
  EID still owns a published actor slot.
- All eight camp records outside the capped nearby list: authored anchor,
  current living EIDs and pending return deadline.

`pending_removals[eid]` stores `(remove_at, monster, killer_eid, archetype)`;
`camp_respawns[camp_id]` stores an absolute simulation deadline. Reading
these dictionaries needs no identity allocation, frame draining, economy
creation or simulation mutation. Projected monster anchors should be exposed
separately from authored map anchors because leash distance uses the former.

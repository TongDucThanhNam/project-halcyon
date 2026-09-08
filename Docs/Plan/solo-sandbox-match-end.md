# Natural structure destruction and match result

Observed on 2026-09-07 by reading existing captures of the operator's own
client. No remote probing, executable analysis, or new remote capture was
performed. All recordings remain outside the repository.

## Source and reproduction

Natural ending: match `a683aa80-9811-47c3-bb64-0731a802e889`, 75 VGR chunks,
114,825 decoded records. The files are under
`$env:TEMP/vg_phaseB/vgr_live/`, named
`ea4c7fda-4b61-481d-abb7-1c757d24ae58-<match-id>.<chunk>.vgr`.
The existing decode cache is
`$env:TEMP/vg_max/match6.halcyon_spawn_audit.pkl`.
Indices below are zero based. VGR tokens, interpreted as big-endian f32,
give the recorded game time.

```powershell
python Tools/Teardown/inspect_match_end.py --vgr-directory "$env:TEMP/vg_phaseB/vgr_live" --match-id a683aa80-9811-47c3-bb64-0731a802e889 --entities 3761 3762 3763 3764 3765 3766
python -m unittest server.test.test_match_end -v
```

The inspector prints positions, HP, event counts, source indices, and
decoded scalar fields. It does not export captured payloads.

## Corrected structure-death premise

The earlier `3563` sequence in the protocol leaf describes a 5,000-HP
objective locator during teardown. It does **not** establish turret or
Vain Crystal death behavior. Applying its synthetic self-hit of −10,000,
1068 state toggles, 1073 destruction, and 1035 despawn to all structures
was an incorrect premise.

In the natural ending, right-side structures have ids 3761–3766. They
match the placement anchors and HP tiers: outer 2500, middle 3000, base
3500, both Vain turrets 3000, crystal 10000. Structure ids differ between
matches; position and HP joins establish identity.

| Structure | Entity | Final hit index | 1072 index | Killer |
|---|---:|---:|---:|---:|
| Right outer turret | 3761 | 51805 | 51816 | 14098 |
| Right middle turret | 3762 | 78232 | 78237 | 21647 |
| Right base turret | 3763 | 82987 | 82993 | 1515 |
| Right Vain turret at 75.48,11.96 | 3764 | 109580 | 109584 | 1515 |
| Right Vain turret at 68.59,19.97 | 3765 | 87534 | 87539 | 23565 |
| Right Vain Crystal at 76.12,19.90 | 3766 | 114025 | 114043 | 1515 |

For every row, 1072 is `[u32 victim][u32 killer][6 zero bytes]`. The
same entity gets a self-targeted 1086 with tag `0x003d`; the crystal also
gets tag `0x0011`. Those 1086 messages contain generated event ids and
their remaining semantics are open.

There are **zero** 1068, 1073, or 1035 records for these six structures
across the complete match. There is no self-targeted −10,000 combat delta.
Subsequent 1010 snapshots retain all five destroyed turrets with HP zero.
After each turret's 1072, visibility updates 1067 appear for side indices
0,1,3,4,5,6,7 with bytes `01 01` after the side index. These are visibility
updates, not a demonstrated death animation command. The crystal has no
corresponding visibility batch in its death window.

The implemented death builder therefore preserves the lethal combat
delta and kill attribution. It does not remove the dead structure from
the client's world.

## Crystal and winner sequence

The last right-crystal snapshot at merged index 113463 has HP 787.41394
and maxHP 10000. Subsequent damage exhausts that HP. Team-one hero 1515
delivers the last two deltas, −242 and −181.81750. The left crystal remains
at full HP throughout. This independently anchors winner value `1`.

| Event | Merged index | Chunk 74 row | Game seconds |
|---|---:|---:|---:|
| Final crystal damage, 1054 | 114025 | 693 | 742.203247 |
| Crystal ending notification, 1106 | 114029 | 697 | 742.203247 |
| Crystal death with killer, 1072 | 114043 | 711 | 742.203247 |
| End statistics, 1165 | 114823 | 1491 | 748.199707 |
| Match result, 1009 | 114824 | 1492 | 748.216187 |

1106 is six zero bytes and arrives in the lethal-hit tick. The result
arrives about six seconds later, after the destruction interval. Combat
messages continue during that interval in the source recording.

1009 is exactly `[u32 winning_team][u8 reason][u8 zero]`:

- Natural crystal ending: winning team 1, reason 0.
- Known AFK surrender in `vgfull.pcap`: winning team 2, reason 2,
  merged index 32625. Its VGR equivalent has the same fields at 31264.
- The second surrender recording has the same fields at `m2frames.pkl`
  index 27587. No natural team-two crystal ending has been observed;
  mirroring the measured winning-team field to team two is an inference
  from team numbering and the surrender result.

`server/match_end.py` builds 1072, 1106, and 1009 from scalar fields.
The tests compare its output with the external records and assert that
the source does not contain the former fabricated death chain.

## Remaining client-facing evidence

Every complete ending inspected has a 1,614-byte 1165 statistics message
immediately before 1009. Its first 64 bytes contain sixteen u32 hero ids;
six occupied slots match the roster, with `0xffffffff` for unused slots.
The next sixteen bytes match the teams. Other regions hold combat totals,
inventory ids, and currently unmapped statistics. A complete statistics
builder has not been justified by this pass.

Passive ordering alone could not show whether 1165 was required to display
the result overlay. The subsequent local Gwen match sent immediate 1106
and measured 1072, then 1009 approximately six seconds later, and visibly
displayed Victory at 19:13. That bounded result check passes without a
fabricated statistics message; exact lines and the inspected screenshot
are in [live acceptance](solo-sandbox-live-acceptance.md#2026-09-08-natural-kraken-capture-siege-and-victory).
Complete post-match statistics and return-menu behavior are separate from
the brief's demonstrated crystal-destruction/match-end requirement.

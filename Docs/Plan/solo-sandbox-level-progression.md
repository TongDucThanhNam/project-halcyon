# Native level, experience and ability-point progression

The sandbox formerly accumulated XP and raised authoritative hero stats while
never emitting the native `1076` level action. This explains the local Adagio
HUD staying at level 1: one 1,925-second local trace contained 1,540 XP worth
of `1053` type-8 updates and six synthetic HP-growth deltas, but zero `1076`
actions. Its thresholds were also an unverified progression curve.

`server/level_wire.py` and `server/economy.py` now use the measured progression.
Passive XP and both bounty entry points deliver the XP causing a transition,
then emit one `1076` and a requirement setter per new level. Pending passive
XP is flushed before an intervening level action, including a bounty that
crosses the threshold. Each action grants the native level's base-stat growth
and ability point; authoritative stats are updated once without sending a
second additive HP-growth delta. Actual combat, item and regeneration deltas
remain separate resource changes.

## Packet and snapshot contracts

All offsets below start at the payload, excluding the two-byte opcode.

| Action/field | Native shape |
|---|---|
| `1076` entity level increment | 14 bytes: `[u32 eid][u32 1][6 zero bytes]` |
| `1052` next-level requirement | 22 bytes: `[u32 eid][u32 FFFFFFFF][f32 requirement][27 00 01][7 zero bytes]` |
| `1011` hero level | f32 integer at payload `294` |
| `1011` unspent ability points | f32 integer at payload `314` |
| `1011` XP within this level | f32 at payload `318` |
| `1011` next-level requirement | f32 at payload `322` |
| `1011` raw maximum HP | f32 at payload `46`: hero base plus level growth, excluding item modifiers |
| `1078` skill-point request and echo | 6 bytes: `[u8 slot 0/1/2][5 zero bytes]` |
| `1082` accepted rank increment | 14 bytes: `[u32 eid][u32 native action ordinal][6 zero bytes]` |

The `1052` suffix is a setter for attribute 39 (`0x27`); the additive item
attribute builder has different flags and must not construct this packet.
Snapshot offsets are identical in the 746-byte replay semantic record and
the 750-byte padded network record. A skill rank increment spends one point;
it does not increment hero level. `1096` is an item-instance use and has no
role in hero or skill progression.

The native requirement at level `L` is `68 + 16*(L-1)`. Cumulative XP to reach
that level is `(L-1)*(52+8*L)`:

| Level | Total XP to reach it | XP requirement stored for that level |
|---:|---:|---:|
| 1 | 0 | 68 |
| 2 | 68 | 84 |
| 3 | 152 | 100 |
| 4 | 252 | 116 |
| 5 | 368 | 132 |
| 6 | 500 | 148 |
| 7 | 648 | 164 |
| 8 | 812 | 180 |
| 9 | 992 | 196 |
| 10 | 1188 | 212 |
| 11 | 1400 | 228 |
| 12 | 1628 | 244 |

The level cap is 12; native level-12 snapshots still store requirement 244.
`PlayerEconomy.xp` is cumulative. `level_wire.within_level_xp(total, level)`
converts it for the native snapshot. New heroes require level 1, one point,
zero within-level XP and requirement 68; a donor snapshot's historical
progression must not leak into bootstrap. Reconnect must preserve current
level and points without replaying historical level actions, and must account
for ability-rank restore actions that consume points.

## Evidence and reproduction

The operator-owned replay caches under `$TEMP/vg_max/` contain **852 hero
snapshots** whose explicit level matches their native base-HP ladder. Every
snapshot has the requirement above. The four sources are `m2frames.pkl`,
`m3frames.pkl`, `m4frames.pkl` and `vgr5frames.pkl`; no payload is stored in this
repository.

The native `vg5_final.pcap` contains **95 level increments**, 47 targeting the
six hero actors and 48 other entities. All have increment one and rebuild
byte-for-byte. All **47 hero requirement setters** rebuild exactly with the
native setter suffix. Its seven local `1078` requests each receive the exact
six-byte echo followed by `1082` for the same hero and selected ability's
native action ordinal. Those ordinals happen to match UI slots for the Phinn
capture; Catherine's A/B/C are native actions 1/2/3 and her Recall is 5.

Two complete replay intervals independently establish XP and points:

- `vgr5frames.pkl` rows 21137 through 22576: hero 1500 changes from level 4,
  zero points, XP 111.699989 and requirement 116 to level 5, one point, XP
  4.699989 and requirement 132. The interval contains nine XP, one `1076`
  and no skill allocation: `111.699989 + 9 - 116 = 4.699989`.
- Rows 110665 through 112171: the same actor in another replay segment
  changes from level 2, zero points, XP 75 and requirement 84 to level 3,
  one point, XP 1 and requirement 100. Ten XP and one level action explain
  the rollover exactly. Rows 22576 through 24235 independently show an
  `1082` spending the point while hero level remains 5.

These are complete selected intervals, not a claim that every inter-snapshot
gap is an uninterrupted match segment. The bounded inspector reports decoded
structure and timing only and sends no network traffic:

```powershell
python -B Tools/Teardown/inspect_level_progression.py "$env:TEMP/vg_max/vg5_final.pcap" `
  --match 045f86d4-7ef2-4125-a835-e70a96288c88 --port 7034 --eid 1500
python -B Tools/Teardown/inspect_level_progression.py "<local-wire-trace.jsonl>" --local-trace --eid 1500
python -B -m unittest server.test.test_level_wire server.test.test_level_progression_corpus server.test.test_economy -q
```

The 30 focused tests cover native snapshots and byte-exact actions, every
level boundary, XP delivery before rollover, awards spanning multiple levels,
single application of HP growth, and level changes while dead. Match bootstrap,
reconnect resource credits, and visible on-client level/point acceptance remain
integration checks separate from these verified codecs and economy transitions.

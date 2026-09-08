# Recall presentation and return evidence

2026-09-07. This pass audits only our existing external capture corpus and
native metadata. `server/recall_wire.py` contains original builders and a
presentation lifecycle; the match session owns recall success/cancellation,
coordinates, HP and energy.

## Native contract

Native KindredBuffs first/last revision pointers independently identify
25 as `Buff_Withdraw` and 26 as `Buff_Withdraw_Ping`. Source:
`D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/55/551BCB541D80053BACD0A897B7993A77`.
The first revision vector is `PTCH[0]=4` with four-byte entries; the last is
`PTCH[0]=8` with eight-byte entries. Each entry's first pointer names the buff.

| Stage | Measured sequence |
| --- | --- |
| Start | Hero-specific Recall action 1045, then two 1086 self buffs, kinds 25 and 26, duration four seconds |
| Early cancellation | 1093 for the same instance of 25 and for the same instance of 26; movement may occur between them |
| Successful return | 1094 targeting instance 25, then Recall effect 1049, relocation 1033 with flag zero, positive self-health 1054 and energy 1053 |

The Recall action follows the hero's native action vector, so it is not
universally slot 3: Catherine=5, Ringo/Gwen/Amael=4, Adagio/Phinn=3. Cast inputs
1041/1042/1102 use these native action ordinals too. Only the 1078 upgrade
request uses UI slots 0/1/2; its accepted 1082 rank increment uses the native
action ordinal. See `server/ability_wire.py`.

1094 has target u32, buff instance u32 and six zero bytes. It also occurs for
other buff kinds; this pass calls it a **trigger**, without claiming that
every 1094 means generic buff completion. All 11 Recall instances associated
with a successful return in the bounded 344-chunk/eight-match `vg_phaseB`
audit use it. The one observed early-cancellation pair uses 1093 instead.

Recall-specific 1049 has tag `0x48d95353`, entity u32, x/height/y f32 and ten
zero bytes (30 bytes). The ten-byte tail is specific to this measured effect,
not a proposed schema for all 1049 messages. Recall 1033 is entity u32,
x/height/y f32 and six zero bytes (22 bytes); resurrection uses a different
flag value. The observed return bursts do not include 1070. A session may
retain its regular position echo after the native presentation.

## Exact own-corpus anchors

All rows below are zero-based. Except the explicit Phinn path, files are under
`$env:TEMP/vg_phaseB/vgr_live/`, with prefix
`ea4c7fda-4b61-481d-abb7-1c757d24ae58-`.

- Catherine, match `1574e27a-e851-492b-8d91-94fc4bd66985.18.vgr`: row 754
  action 5 at 184.010757 seconds; rows 755/756 start instances 9780/9781,
  kinds 25/26, four seconds. Rows 1181/1182/1183 at 188.104568 are
  1094 instance 9780, 1049 and 1033. Rows 1184/1185 restore HP/energy.
- Flicker, match `f58e0359-8d83-4994-a33c-217cf863144b.27.vgr`: rows 300/301
  start instances 11799/11800 at 270.425659. At 270.626160, row 312 cancels
  instance 11799, row 313 moves compact actor 2, and row 314 cancels 11800.
  Incoming damage also occurs on that tick; the exact input/AI reason for
  cancellation is not established by this server-to-client recording.
- Phinn, `$env:TEMP/vg_max/vgr5b/ea4c7fda-4b61-481d-abb7-1c757d24ae58-045f86d4-7ef2-4125-a835-e70a96288c88.47.vgr`:
  row 378 starts instance 15826 at 472.286560, duration four seconds.
  Rows 618–622 at 476.237579 contain 1094, 1049, 1033, HP and energy.
  Same match `.9.vgr` row 986 to `.10.vgr` row 343 repeats the return chain.
  Token-time differences are approximately 3.90–4.09 seconds across samples;
  the explicit buff duration is four seconds.

Mid-recall snapshots use 1087 with the same instance, remaining half-float
duration, state count 1 and four zero u32 words. Examples in
`$env:TEMP/vg_max/vgr5frames.pkl`: 2787/2788 (instances 6118/6119,
remaining 2.099609 seconds) and 18147/18148 (9045/9046, 2.798828 seconds).
No additional opaque parameters are required for these two buffs.

Two independent returns prove an immediate **25% of maximum HP and energy**
refill before ordinary fountain regeneration:

- Match `0e7de8af-96d9-4e3a-b3c2-609ed5e71120.17.vgr`, row 1025, entity 1517:
  prior 1011 maximum HP/energy 1115/428, followed by +278.75/+107.
- Match `f58e0359-8d83-4994-a33c-217cf863144b.22.vgr`, row 1159, entity 1517:
  prior maxima 1265/351, followed by +316.25/+87.75.

Catherine's return adds 366.662506 HP and 68 energy: one quarter of base
maximum HP 1316.65 plus equipment HP 150, and maximum energy 272.
Apply actual missing-resource caps and ordinary healing modifiers in the
authoritative simulation; captured deltas are not fixed healing constants.

## Integration

Create `RecallPresentation(status_manager)` once per match. After an accepted
Recall start, call `start(eid, now)`; paired adds are queued on the shared
status manager and use its match-wide native instance allocator. Repeated
calls for the same start are idempotent. Call `cancel(eid, now)` when movement,
damage, death or control effects actually cancel the authoritative recall.
The shared manager handles native cancellations and reconnect remaining time.

For a confirmed successful return, `complete(eid, now)` returns its 1094 once,
even if natural buff expiry has already been cleaned by the shared manager.
Providing all of `x`, `y`, `effect_height`, `relocation_height` appends the
measured 1049/1033 pair. Heights are explicit because they differ across map
sides and between effect and relocation; the helper does not guess them from
the two-dimensional simulation. The caller still performs teleport and
resource refill and emits actual resource deltas.

```powershell
python -m unittest server.test.test_recall_wire -q
```

Seven tests cover native adds/snapshots, idempotence, early cancellation,
completion after expiry, validation without consuming state, Catherine and
Phinn byte-exact return builders, the movement-cancellation pair, and both
quarter-resource goldens. The local client subsequently displayed the native
channel, completed return and movement cancellation; screenshots and session
provenance are in [live acceptance](solo-sandbox-live-acceptance.md#2026-09-07-evening-shop-levels-recall-and-visibility).

## Authoritative refill and measured heights follow-up

`HeroMovement.tick_lifecycle()` now applies the immediate quarter-resource
refill when the four-second return actually succeeds. Its
`last_recall_completed_at` starts as `None` and records that successful tick;
movement, damage, death and control cancellations do not update it. The
session can distinguish completion from cancellation without inferring the
reason from a cleared timer.

Teleport retains the existing 1070 position output. Instant HP recovery uses
one positive self-1054 and does not also emit an HP-1053 for that amount.
Instant energy recovery uses one 1053 with the actual recovered amount.
Resource caps and wound apply normally. Ordinary fountain regeneration still
runs afterward and publishes its own, separate deltas.

The height census prevents a false universal constant for the left side:

| Return location | 1049 effect height | 1033 relocation height |
| --- | --- | --- |
| Right side, all three observed slots | `3fc00000` = 1.5 | `3fdf9ffa` = 1.7470695972442627 |
| Left slots 1500/1515 | `3fa66666` = 1.2999999523162842 | `3fa22f56` = 1.2670695781707764 |
| Left slot 1516 | `3fa66666` | `3fa0733c` = 1.253516674041748 on ordinary returns, also `3fa66666` on repeated returns already at base |

`RETURN_HEIGHTS` consequently contains the unambiguous right-team pair only.
`RETURN_HEIGHTS_BY_EID` separately supplies the stable observed left slots
1500 and 1515. Ambiguous slot 1516 is omitted. These are measured A001 spawn
locations, not a height policy for an arbitrary map or changed spawn point.

`test_recall_session_lifecycle.py` adds five checks through the actual session
and lifecycle: exactly four seconds, one immediate refill then ordinary
regeneration, wound and resource caps, no success marker after cancellation,
and exact return-height builders for all three right slots and both supported
left slots. The combined Recall/navigation/sandbox command passed 62 tests:

```powershell
python -m unittest server.test.test_recall_session_lifecycle server.test.test_recall_wire server.test.test_navigation_lifecycle server.test.test_sandbox_simulation -q
```

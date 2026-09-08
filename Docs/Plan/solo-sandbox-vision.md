# Actor visibility for the solo sandbox

2026-09-07. The client needs current visibility as well as actor positions.
`server/vision.py` now supplies a minimal deterministic team-vision baseline
using native 1067 setters. Its 12-unit radius is explicit sandbox policy;
retail brush, wall occlusion, stealth and true-sight behavior remain open.

## The local blocker

In the operator-owned trace
`$TEMP/halcyon_stack/wire-1788796968592819300.jsonl`, local Catherine 1500
was at `(0.000253, 40.240666)` and enemy Baptiste 1517 at
`(2.917888, 39.818711)`. Both were alive in the authoritative QA snapshot,
about 2.95 units apart. The client rendered only Catherine.

At the audit checkpoint, the trace contained 50,171 server frames. Each of
these heroes had one 1011 creation and one QA 1070 position correction, but
**no 1067 visibility update**. Baptiste's original visibility for viewer 1
was `(1, 0, 0)` and stayed there. Its team-2 bank was `(1, 15, 0)`. Moving
the actor did not update the client's hidden bank for the opposing team.

This isolates a missing protocol update; visible rendering after the repair
still requires the local client check. It does not establish that every
rendering issue is a visibility issue.

## Measured native contract

The existing PC analysis in
`Docs/Teardown/vainglory-pc-client-internals.md` §7.6 identifies opcode 1067
as `ActionModifyVisibility`. It serializes a full EID and four bytes. The
setter uses the first byte as an index and stores the other three in three
arrays within a visibility component. Its branch logic references
`onEnterBrush`/`onExitBrush`; the exact names and meanings of all three
stored fields are not established.

The 14-byte mobile payload is:

```text
u32 BE EID | u8 viewer index | u8 field A | u8 field B | u8 field C | 6 zero bytes
```

All 5,330 records in the external `vgfull.pcap` reproduce byte for byte
through `VisibilityUpdate.encode()`. Viewer indices range from 0 through 7.
In both audited normal 3v3 bootstraps, indices 1 and 2 correspond to the
playing teams; other indices are not assigned new meanings here.

The native 750-byte hero 1011 contains three eight-byte banks at offsets
713, 721 and 729. Initially, bank A contains eight ones, bank B contains
15 only at the actor's own team index and zero elsewhere, and bank C is
zero. This matches the current local bootstrap exactly. The server updates
both playing-team banks through 1067 after actor creation.

Ordinary captured values used by this implementation are:

| Relationship/state | A/B/C |
|---|---|
| Native owner-team bootstrap | `1 / 15 / 0` |
| Ordinary visible/revealed actor | `1 / 1 / 0` |
| Ordinary hidden actor | `1 / 0 / 0` |

The visible interpretation has independent client-input evidence. In
`$TEMP/vg_max/vg5_final.pcap`, match
`045f86d4-7ef2-4125-a835-e70a96288c88`, port 7034, all 22 captured client
1060 target clicks have a preceding viewer-1 update with B equal to 1, 3
or 7 and A/C equal to 1/0. Six creature clicks follow the ordinary B=1
form. All 12 enemy-hero clicks follow B=3 or B=7. These richer values are
recorded evidence, not a recovered model of their additional bits.

For example, the native click at 290.573265 seconds targets EID 1517 after
server frame 34942 at 285.433527 seconds sets `1 / 7 / 0`. In this capture
EID 1517 is **Vox, hero 258**; EIDs are match-local and must not be used as
permanent hero identities. In the current local match and `vgfull.pcap`,
EID 1517 is Baptiste, hero 399.

The living Baptiste in `vgfull.pcap` provides a direct ordinary sequence:

| Zero-based server frame | Viewer index | A/B/C |
|---:|---:|---|
| 3342 | 1 | `1 / 1 / 0` |
| 9335 | 1 | `1 / 0 / 0` |
| 9959 | 1 | `1 / 1 / 0` |

All three transitions precede that actor's first death at frame 16703.
No 1033 resurrection occurs in this sequence. The separate native 1033
death/respawn contract is not evidence for adding resurrection to normal
teleports. These ordinary reveals also do not require a fresh actor spawn,
1055 player tag or 1087 buff allocation at each transition.

Corpses are not automatically invisible: all six native hero deaths have
a subsequent viewer-1 update with B/C equal to 1/0. Five use A=1; one uses
A=3, retaining the distinct brush-related field. This baseline preserves
ordinary corpse-target visibility while treating dead actors as inactive
observers. It does not reinterpret 1067 as a death or animation command.

## Deterministic baseline and integration

```python
self.vision = vision.Vision(actor_slots=self.actor_slots)
# After authoritative actor creation/lifecycle and movement for this tick:
self._emit_frames(self.vision.update(now, self._entities()))
# On reconnect, after all current actors have been created:
for opcode, payload in self.vision.snapshot_frames():
    send(opcode, payload)
```

`VisionRules(radius=12.0)` is the default. The existing mechanics leaf §18
and §19.4 records the unsuccessful radius extraction and absence of measured
fog-edge/brush distances; no native coefficient is claimed. This policy
uses inclusive squared distance in the same integer millionth-unit lattice
as movement. An integer spatial grid narrows candidate observers to nine
cells, then performs that exact distance check. It has no random input or
wall-clock timing.

Living allied heroes, lane minions and non-crystal turrets share sight.
Each target receives own-team B=15, opposing-team B=1 while within the
chosen radius of any living observer, and B=0 otherwise. Neutral actors
can be revealed independently to either playing team. Dead targets retain
the same nearby/own-team treatment; dead actors do not provide sight.

Updates are sorted by entity ID and viewer team and are emitted only when
the stored triplet changes. The first update establishes both playing-team
banks. `snapshot_frames()` returns those current banks without recomputing,
allocating or mutating the simulation. It should follow an ordinary update
and all actor creation messages on reconnect.

The shared `ActorSlots` binding is required in production: `_entities()`
contains scheduled lane minions and older dead minions whose actors were
already removed. The visibility component excludes unallocated IDs and
future `spawn_at` values, prunes missing/removed IDs from its cache, and
emits no packet for an actor after its removal. Without an allocator, the
caller must supply only current client-created actors. Retained corpses
keep their slot and remain eligible as visibility targets until 1035.

This baseline does not implement terrain/brush occlusion, stealth, true
sight, observer-specific retail radii, ward sight, spectator banks, enemy
position suppression or authoritative target rejection based on sight.
Those remain separate fidelity gaps. Forced vision setup alone is not
proof of the requested basic-attack or hero-aggro client scenarios.

The pre-existing standalone `VisionManager` API and all seven of its tests
remain available. That earlier 10/6/9-radius, rectangular-brush and turret
true-sight policy is not connected to the live publisher and does not supply
native evidence for those behaviors. The production match uses `Vision`.

## Reproduction and checks

```powershell
python -B Tools/Teardown/inspect_visibility.py --wire "$env:TEMP/halcyon_stack/wire-1788796968592819300.jsonl" --viewer 1 --eid 1517 --limit 3
python -B Tools/Teardown/inspect_visibility.py --pcap "$env:TEMP/vg_max/vg5_final.pcap" --match 045f86d4-7ef2-4125-a835-e70a96288c88 --viewer 1 --limit 22
python -B -m unittest server.test.test_vision server.test.test_vision_wire
```

The inspector reports numeric bank states, counts and native target/input
correlations. It does not send packets or export corpus payloads. When a
live trace contains multiple connections, select `--connection` explicitly
to avoid combining separate clients' streams.

The 13 new wire/publication tests pass alongside all seven existing policy
tests. New coverage includes the complete 5,330 native setters, living
reveal/hide/reveal, six native corpse sequences, all 22 native target clicks,
inclusive fixed-point radius boundary, shared minion/turret observers,
dead observer behavior, actor creation/removal filtering, deterministic
ordering and pure reconnect snapshots. The client check remains: reveal
the nearby enemy, verify its model and targetability, drive basic attacks
through the real UI, then separate the teams and check hiding/revealing.

An independent exhaustive-distance comparison matches the grid's outputs
for 48 observers across negative coordinates and cell/radius boundaries.
A bounded 242-actor standalone check dropped from mean 8.07/max 10.52 ms
for the simple scan to mean 2.608/max 4.172 ms for the grid across 21 updates.
These timings concern this component in a local diagnostic workload, not
complete fixed-tick performance acceptance.

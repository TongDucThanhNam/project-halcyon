# Vainglory character movement — why it feels smooth (mechanism anatomy)

Spun out of the map leaf as its own leaf on 2026-09-03. Section number
**§13 is inherited** from `vainglory-3v3-map-structure.md` (monolith era) so
existing cross-references stay valid.

Evidence classes: heap strings (4,861 verified VAs), named path objects
decoded in the heap (route in `vainglory-runtime-reconstruction.md` §4),
navmesh format (map leaf §4), runtime placement table (map leaf §11).
Labels per claim; measured traffic context lives in
`vainglory-netcode-backend.md`.

## §13.1 Authored routes are sparse named waypoint objects (Observed)

Six path objects live in the heap: `lKrakenPathTop/Bot`, `rKrakenPathBot/Top`,
`Team1/2__CrystalMiner_Path`. Layout: `{char* namePtr → inline name,
char* ptr2 → inline name}` followed by a vector of pointers (8 B stride) to
16 B waypoint slots `[tag=2.0, A, 0.0, B]` — 21 sparse waypoints per kraken
route, four-way mirror symmetric (x ±8.2…±73.4, z ±6.6…±61.1).

- The tag `2.0` equals the structure collision radius — plausibly a waypoint
  reach radius [Inferred].
- The recovered kraken coordinates do not fit the current 3v3 bounds in z —
  the objects likely survive from a larger/older authoring space [Inferred].
- Design meaning: scripted walkers (kraken, courier) follow hand-authored
  sparse polylines; free movers do not. Minion lane polylines were probed for
  and are **not** stored as flat arrays (runtime leaf §7.2).

## §13.2 Free movement is navmesh pathfinding with runtime adjacency (Observed → Inferred)

The navmesh payload ends exactly after the index buffer (19,166 +
2,496 ÷ 3 × 6 = 24,158 = payload length): no adjacency, portal or waypoint
graph is stored. The engine rebuilds triangle adjacency from shared edges at
load and paths over the mesh at runtime — a triangle-mesh + corridor setup,
the classic input to path smoothing.

## §13.3 Rotation is a first-class state, not an instant snap (Observed)

`Ability__Turret__RotateTowardsTarget` and
`Ability__Turret__StopRotatingToTarget` exist as named ability nodes — even
turrets turn via explicit rotate/stop states, implying turn-rate-limited
rotation across actors.

## §13.4 Locomotion has dedicated start/stop clips (Observed)

Creep art ships `*.idle.anim`, `*.idle_combat.anim`, `*.run.anim` and
**`*.run_start.anim`** (Blackclaw) — motion start is its own blended clip, a
major contributor to perceived smoothness.

## §13.5 Order model (transferred)

Move intents resolve deterministically with no hidden retarget (landed in
goal 009); ability events give presentation one channel (map leaf §5).

## Transferable smoothness checklist for Veilbound

Delta against what goals 009/010 already landed:

1. turn-rate-limited rotation;
2. path-following with corner cutting inside the corridor;
3. arrival stop-radius (no oscillation);
4. `run_start` clip in the locomotion blend tree;
5. fixed-tick deterministic sim with presentation observing events (already
   the project architecture);
6. input shipped as tiny intents over a low-latency channel, events back —
   the network half is `vainglory-netcode-backend.md` §4.

## §13.6 The Locomotion Protocol Duality: Predictive Local Hero vs Server-Driven Puppet (Observed 2026-09-07)

Comparative wire analysis of Match 1 (`vgfull.pcap`, hero 925 Amael / EID 1500) vs bot heroes (EIDs 1515–1519) established two fundamentally distinct movement contracts in the Vainglory client:

1. **Contract A: Local Player Hero (EID 1500 — Client-Predictive)**
   - **Local Authority**: The client evaluates navmesh pathfinding locally upon touch input (`c2s 1012`) and directly drives the locomotion blend tree (`idle` → `run_start` → `run`).
   - **Wire Silence**: Over an entire 353-second match, EID 1500 receives only **37 frames of `1070 POSITION`** (averaging 2–5 frames per move order as initial current-position anchor, ~1.55u checkpoints at 5 Hz, and duplicate arrival confirmation).
   - **Zero Puppet Opcodes**: Receives **0 frames of `1018 ENTITY_POSE_3D`** and **0 frames of `1067 ENTITY_STATE`** during pure locomotion. If server position stream ceases, the hero continues walking to its destination autonomously.

2. **Contract B: Replicated Entities / Bots (EIDs 1515–1519 — Server-Driven Puppet)**
   - **Zero Local Simulation**: The client performs no local pathing or prediction for remote/bot entities.
   - **Dense Wire Guidance**: Each bot receives **350–606 frames of `1070 POSITION`** and continuous **`1018 ENTITY_POSE_3D`** (12–66 frames) for 3D orientation.
   - **Explicit Animation Triggers**: Locomotion animation is explicitly commanded by the server via `1067 ENTITY_STATE`:
     - Move start: `1067 [eid][team][03|01][0x0F]` (`0x0F = ENTITY_STATE_MOVING`).
     - Move stop / arrival: `1067 [eid][other_team][01|03][0x00]` (`0x00 = ENTITY_STATE_IDLE`).

**Root cause of "Hero Gliding" on custom servers:**
Custom servers that advance hero coordinates server-side and stream `1070` position frames without activating Contract A's local prediction or Contract B's explicit `1067` animation state trigger force the client into a pure coordinate-displacement mode: the 3D model transforms across the navmesh while remaining locked in its default `idle` animation clip.

## Claims left open (movement-specific)

- The `2.0` waypoint slot tag interpretation (reach radius vs layer id).
- Hero spawn points (not in the placement table; map leaf open-claims).
- Exact blend-tree graph topology — clip names and explicit state triggers (`0x0F` / `0x00`) are Observed; internal transition curves remain Inferred.
- Local character controller activation handshake: which early bootstrap packet (e.g. the 6× `1087` allocations at `+0.194s`) authorizes the client to predictively walk EID 1500.


## Follow-up qualification (2026-09-07; skill UI fixed, locomotion still open)

Section 13.6's packet-count observations do not independently establish the
client's exact internal blend graph, predictor flag, or a conditional that
ignores 1067 for the local actor. Those causal interpretations require runtime
or instruction evidence; the PC leaf records unresolved flag/address conflicts.
The operator withdrew the earlier claimed Amael walking-animation acceptance.

A fresh local experiment repaired the missing skill acknowledgement/state
sequence and visibly cleared the tutorial. Ground taps reached the server as
1012 both before and after this repair. With the prompt cleared, pausing the
isolated server briefly still stopped hero progress after queued updates had
settled, while the client clock/ambient effects continued. All server messages
were paused, so this does not identify an individual missing opcode. It rules
out assuming that the UI repair alone establishes autonomous locomotion.

See vainglory-mobile-local-stack.md, "Live outcome of the skill-state repair",
for evidence paths, capture frame rates, and limitations. The 1087 bootstrap was
present in that test (1458-frame world tape); a missing entire bootstrap batch
is not an adequate explanation for that session. Which ownership/navigation
state or event sequence remains incorrect is still open. No walking-animation
acceptance or sparse-1070 fix is claimed.
> **Latest locomotion correction (2026-09-07):** the operator now confirms
> visible walking/leg animation in LDPlayer, still choppy. Earlier "100% fixed"
> and subsequent "still open" status blocks refer to older experiments.
> `1016` is movement intent; `1067` is visibility, not run/idle. Section 13.6's
> speculative animation/ownership contract must not be treated as established.
> See [the consolidated handoff](vainglory-locomotion-handoff.md) for the active
> six-cancellation bootstrap candidate, evidence limits, and unfinished work.

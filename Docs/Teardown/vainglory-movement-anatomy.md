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

## Claims left open (movement-specific)

- The `2.0` waypoint slot tag interpretation (reach radius vs layer id).
- Hero spawn points (not in the placement table; map leaf open-claims).
- Exact blend-tree shape — only clip names are Observed, not the graph.

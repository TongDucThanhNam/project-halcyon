# Veilbound Multiplayer Design — Research Document

> **Purpose:** Design the multiplayer architecture for Veilbound's deterministic
> gameplay slice when that goal is activated. This document is research-only:
> no code, no implementation, no commitment. It synthesises structural lessons
> from the Vainglory reverse-engineering programme and maps them against
> Veilbound's deterministic core.
>
> **Companion documents.**
> - [veilbound-multiplayer-spike-report.md](veilbound-multiplayer-spike-report.md) —
>   live Python spike that validated the `DeterministicRuleEngine` contract
>   (§10 step 2). Outcome in §7 below carries the spike's "yes/but" verdict.
> - `spikes/determinism/` — spike source (`engine.py`, `run_process.py`, `verify.py`).
>
> **IP boundary:** Only structural principles transfer. Blueprint class names,
> map naming, texture art and protocol details from Vainglory are never
> inputs. Veilbound's vocabulary — `Instability`, `Discipline`, `Revelation`,
> zone names, entity names — is the only permitted namespace.

---

## 1. What the Vainglory RE Programme Taught About Multiplayer

The RE work produced findings in three layers relevant to server design.

### 1a. Map / world architecture — one environment, many modes

Vainglory's 3v3 map (`A001`) is built in five independent authoring layers:

1. **Zone-chunked terrain** — 13 named zones (decorative rock clusters, crystal
   mine, gold mine, out-of-bounds painted as `PitchBlack`). Each zone is a
   discrete authored chunk with per-zone material identity.
2. **Grid-named ground tiles** — `GroundAA`…`GroundCD` on a row/column grid.
3. **Blueprint catalogue** — typed actor classes placed via a named placement
   table. The placement record carries full transform context (position +
   rotation matrix + parameter blocks).
4. **Navigation baked per mode variant** — one environment carries several
   `navMesh_*` records sharing the same world origin but with different
   triangle subsets (full 3v3, trimmed ARAM, tutorial subset). Bounds are
   stored as `min/max` pairs and proven symmetric across variants.
5. **Live-rendered minimap** — a per-actor-type icon layer over match state,
   not a baked screenshot. 21 icon types, five semantic pings, side/size
   settings.

**Transferable to Veilbound:** The zone-chunk pattern means the environment
is authored once; a mode variant is expressed as a different placement table
+ nav subset, not a new scene. This maps directly onto Veilbound's existing
`ZoneAuthoringData` + `ActorPlacementData` structure.

### 1b. Typed actor placement table — the critical data model

The 30-record placement table recovered from runtime memory (`§11,
vainglory-3v3-map-structure.md`) revealed the canonical shape:

```
{ namePtr → inline NUL name,
  ptr2,                        -- companion record or next
  f32 x, y, z,                -- world position, ground-snapped
  d = 0,                      -- likely flags/dimension
  yaw°,                        -- euler rotation
  f = 0 }                     -- likely parameter-block offset
```

Each anchor is grid-quantised to a 3-unit lattice sharing the navmesh origin
fractions. Companion triples store health-bar / icon heights above the anchor.
The table is the **authored blueprint**; runtime instances are ground-snapped
copies (`y = 0` vs `y = 0.0071`).

**Transferable to Veilbound:** Veilbound already uses `ScriptableObject`
placement data. The key insight is that the placement table must be a
first-class runtime serialisable type — position + rotation + typed parameters
— because the server needs to reconstruct world state from it.

### 1c. Client-authoritative model — the CE lesson

SEMC's "Vainglory: Community Edition" announcement described the transition
as *"client-authoritative."* No reference server implementation was published.
Community projects (VGReborn, HackedGlory) work by intercepting or mocking the
client-side traffic, not by running an authoritative server SEMC wrote.

**Transferable to Veilbound:** The lesson is negative but valuable: a
client-authoritative model requires the client to be trusted, which requires
anti-cheat. An authoritative server that owns all game state and validates
every action is the correct default for Veilbound — it is both simpler to
reason about for determinism and more robust against manipulation.

---

## 2. Core Architectural Choice: Lockstep vs State-Sync

Veilbound's deterministic gameplay core makes this choice more constrained
than for a typical MOBA.

### 2a. What "deterministic" means here

`AGENTS.md`: *"Determinism is the product. No randomness in combat rules. Every
outcome must be predictable from visible state."*

`GOAL.md` §2 gate: *"Intent truth — the command committed is the last valid
intent shown."*

This means Veilbound's combat resolution is a pure function:

```
(new_state, events) = ApplyRules(current_state, action)
```

Given the same `(current_state, action)` tuple on any machine, the result is
bit-identical. This is the hardest property to maintain in multiplayer and
the most valuable one to preserve.

### 2b. Option A — Deterministic Lockstep (GGPO-style)

**Mechanism:** All clients simulate the same frame. One peer is the
"host" (not authoritative on rules — only on tie-breaking and disconnect).
Every input is logged and broadcast. Execution is speculative locally and
corrected by rollback when a discrepancy arrives.

**Pros:**
- Determinism is preserved end-to-end. The committed state is identical on
  every machine because they all run the same deterministic tick.
- No floating-point divergence: if the rule engine uses fixed-point or
  integer math, every tick is bit-exact across all participants.
- Lower bandwidth: only inputs need to be transmitted, not full state.
- The intent-commit gate maps naturally: the committed intent *is* the input.

**Cons:**
- Latency budget is tight at 60 Hz: one frame = 16.7 ms. Players beyond
  ~60 ms RTT feel the correction judder. Acceptable for LAN / regional
  (HCM → HCM < 10 ms, HCM → Singapore ~80 ms — usable but not ideal).
- Rollback state must be preserved: every active tick holds a diff of
  the pre-rollback state. Memory grows with player count and tick rate.
- Reconnect requires replaying from the last confirmed tick — which must be
  stored server-side as a replay log.
- One desync = one abort. Requires a deterministic checksum per tick to
  detect.

**Verdict for Veilbound:** Viable if the game stays regional and the
player pool tolerates the latency sensitivity. The deterministic core makes
this *simpler* than in a non-deterministic game — there is no
"which random seed" ambiguity on rollback.

### 2c. Option B — Authoritative Server + State Sync

**Mechanism:** A trusted server runs the full rule engine tick-by-tick.
Clients send intent (not raw actions). The server resolves intent into
committed state and broadcasts a state delta to all clients each tick.
Clients render the latest server state and predict locally for responsiveness.

**Pros:**
- The server is the single source of truth. Anti-cheat is straightforward:
  the server validates every action against the current state before applying.
  No client can lie about what happened.
- Disconnect / reconnect: the client fetches the current state snapshot and
  resumes rendering. No replay log needed.
- Latency tolerance is higher: the client can render a predicted state and
  correct when the server delta arrives. 80 ms RTT is tolerable if prediction
  is correct.
- Floating-point divergence between server and client is acceptable because
  the server state wins.

**Cons:**
- Determinism is broken across the network boundary. The server's
  floating-point result must match the client's predicted result or the
  client will visually jerk. Unity's floating-point is
  non-deterministic across platforms/CLRs.
- Bandwidth is higher: state deltas must be sent every tick, not just inputs.
  With 60 Hz tick, 10 units per team, abilities and particle state — delta
  compression is non-trivial.
- The intent-commit gate must be redesigned: the server must be able to
  distinguish "player intent shown" from "player intent committed". The
  current single-frame gate may need a 2–3 tick grace to account for
  round-trip.

**Verdict for Veilbound:** More robust for a public deployment with unknown
client hardware. Requires resolving floating-point determinism (see §4).

### 2d. Recommended Hybrid: Authoritative Server with Deterministic Core

**Architecture:**

```
[Client]          [Server]
  |                   |
  |--- intent ------->|  (client shows intent locally, sends to server)
  |                   |--- validate + apply rules --> authoritative state
  |<-- state delta ---|  (server broadcasts committed state every tick)
  |                   |
  |<-- ack/rollback --|  (server reports if intent was invalid)
  |                   |
  v                   v
renders             stores
predicted           authoritative
state               state
```

The server runs the *exact same rule engine* as the client (shared library,
not a replica). Floating-point non-determinism is addressed by running the
rule engine in a controlled environment (see §4).

Intent is shown locally at 60 fps client-side and committed when the server
acks. If the server rejects (invalid target, ability on cooldown, target
died), the client rolls back one tick and replays without that action.

This preserves the intent-commit gate, keeps anti-cheat server-side, and
tolerates real-world latency.

---

## 3. Server Data Model

### 3a. World state snapshot

The server owns and serialises per tick:

```
GameState {
  tick: uint64
  teams: Team[2]
  units: Unit[id][]          -- indexed by persistent id
  zones: ZoneState[]
  activeAbilities: ActiveAbility[]
  pendingIntents: Intent[]   -- per player, last N ticks for rollback
  gas: GasState | null
}
```

The placement table drives initial world construction. The server reconstructs
the world from the same `ActorPlacementData` + `ZoneAuthoringData` the client
uses for rendering, ensuring geometry is identical.

### 3b. Typed placement table (per map variant)

```
PlacementRecord {
  id: uint16
  type: ActorType          -- e.g. Turret, MinionCamp, Objective, Shop
  position: Vector3        -- world space
  rotation: Quaternion     -- yaw only for most entities
  parameters: ParamBlock   -- health, aggroRadius, abilityIds, etc.
  team: TeamId | Neutral
}
```

The placement table is the **authored blueprint** for a given map + mode
variant. The server holds it as an asset (same `ScriptableObject` the editor
uses). No dynamic placement during play — only pre-authored placements load
at match start.

This maps directly from the Vainglory finding: one environment, one typed
catalogue, mode expressed as navMesh + placement subset.

### 3c. Intent log for rollback

Every tick, for every player:

```
IntentLogEntry {
  tick: uint64
  playerId: uint8
  action: Action           -- move / attack / ability
  targetId: uint16 | null
  targetPosition: Vector3  -- for move
  timestamp: uint64         -- client-side clock for ordering
  intentShownTick: uint64  -- the tick when client showed this intent
}
```

The server keeps the last 8–16 ticks per player to handle rewind on invalid
action. The client keeps a local mirror for speculative execution.

---

## 4. Floating-Point Determinism — the Critical Engineering Problem

This is the single hardest problem to solve correctly. Unity's `Mathf`,
`Vector3`, `Quaternion` use platform-specific floating-point, and JIT
behaviour can vary across .NET implementations.

### 4a. Known divergence points

| Source | Non-deterministic behaviour |
|---|---|
| `Mathf.Approximately(a, b)` | Tolerance varies by platform |
| `Quaternion.Euler(x,y,z).eulerAngles` | Order-of-operations dependent |
| `Vector3.Angle`, `Vector3.Distance` | Trig implementation varies |
| Division by zero / NaN propagation | Compiler / platform differs |
| `Mathf.Lerp` with `Time.deltaTime` | Frame time varies |

### 4b. Required mitigations

**Controlled rule engine:** The rule engine (all `ApplyRules` calls) must run
in a deterministic environment. Options in ascending order of correctness:

1. **Fixed-point math library** — represent all world-space positions,
   angles and lerp factors as integers (e.g. `long` with a fixed scale
   factor). No floating-point in the rule engine. Rendering interpolates on
   the client. This is the approach used by most lockstep RTS engines.
   *Cost:* significant rewrite of position/rotation/targeting code.
   *Benefit:* provably deterministic.

2. **StrictFP in Java** (not applicable here) or a self-contained
   deterministic math lib — implement `DetMath.cs` with the specific
   floating-point quirks of .NET/IL2CPP locked down. Requires validating
   against the target platform (Android ARM64 + IL2CPP).
   *Cost:* medium. Implement only the functions actually used in rules.
   *Benefit:* less invasive than full fixed-point.

3. **Server-side validation only** — accept that client and server float
   slightly diverge, but use server state as authoritative. The client predicts
   but the server corrects. This is the state-sync approach (Option B/C above).
   *Cost:* visual micro-corrections on high-divergence operations.
   *Benefit:* no rule engine rewrite.

**Decision needed from the user before implementation begins.** Option 1 is
the only one that fully preserves the "determinism is the product" gate.
Option 3 is pragmatic and already used by many shipped mobile MOBAs.

---

## 5. Connection and Reconnection Model

### 5a. Connection flow

```
Client connects --> Auth (token / anonymous)
  --> Matchmaking queue
    --> Match found: receive placement table hash + server address
      --> TCP/UDP socket established
        --> Server sends initial state snapshot (tick 0)
          --> Client begins rendering and sending intents
```

The placement table hash is critical: if the client's placement table version
does not match the server's, geometry differs and the session is aborted
before play begins.

### 5b. Reconnection during a match

The server stores the last **60 seconds** of `IntentLogEntry` records per
player. On reconnect:

1. Client receives the current `GameState` snapshot.
2. Client replays all intents it sent in the last 60 s from its local log.
3. If any intent was rejected (server already processed it differently),
   the server sends a rollback delta.
4. Client corrects and continues.

Players who disconnect for > 60 s are marked AFK. The server continues
running the match. If a player reconnects, they resume from wherever the
match is. If AFK for > match duration, they are replaced by a bot slot
(bot policy is a design decision — see §7).

### 5c. Replay storage

Every match generates a replay file:

```
Replay {
  header: { version, mapId, timestamp, duration }
  placementTable: PlacementRecord[]
  intentLog: IntentLogEntry[]   -- compressed, all players, all ticks
  finalState: GameState
}
```

The replay file is deterministic: replaying the intent log from tick 0 with
the same rule engine produces the same final state. This is both a player
feature ("watch replay") and a developer feature (reproduce any desync).

---

## 6. Regional Deployment Model

### 6a. Singapore lag problem — stated motivation

Ping from HCM to SG server: ~80–150 ms (measured). At 60 Hz tick, 150 ms =
9 ticks of delay. With client-side prediction this is tolerable; with
lockstep it is not. The authoritative-server-with-prediction model (Option C
above) handles this naturally: the client predicts 5–10 ticks ahead,
corrects on server ack.

A HCM-hosted server reduces HCM → HCM ping to ~10–30 ms. SEA region
deployment (Singapore, Bangkok, Jakarta or HCM as hub) covers the target
player base within the 80 ms window where prediction corrections are
imperceptible.

### 6b. Server components needed

| Component | Role | Hosting |
|---|---|---|
| **Game server** | Authoritative tick engine, rule validation, state broadcast | 1 × per active match, ephemeral |
| **Matchmaking service** | Groups players into matches, assigns game server | Persistent, scales with queue |
| **Auth service** | Player identity (anonymous or account) | Persistent |
| **Replay storage** | Stores replay files, serves download | Object storage (S3-compatible) |
| **cdn** | Serves placement table assets + client binary | Static CDN |

For a prototype with HCM-only initial scope, all persistent services can
run on a single VPS (e.g. AWS ap-southeast-1, DigitalOcean SGP, or a HCM
colocation). The game server is ephemeral — one process per match, started
by the matchmaking service, terminated when match ends.

### 6c. Bandwidth budget (per match, per player)

Estimate for a 3v3 Veilbound slice:

| Data | Size per tick | At 60 Hz |
|---|---|---|
| State delta (compressed) | ~200–500 B | ~12–30 KB/s upstream |
| Intent uplink | ~50–100 B | ~3–6 KB/s downstream per other player |
| Server ack / rollback | ~30 B | ~1.8 KB/s |

Total per player: ~20–40 KB/s upstream, ~15–25 KB/s downstream.
Mobile-comfortable on 4G (5 Mbps+).

---

## 7. Open Design Questions

These are decisions the user must make before implementation, not solved
problems in this document.

1. **Fixed-point or float-determinism?** (§4) — determines the entire rule
   engine implementation path. Fixed-point is correct; float-with-server-auth
   is pragmatic.

2. **3v3 or staying with the current lane?** The active goal (goal 013) is
   rebuilding the battlefield as a 3v3. Multiplayer design here assumes 3v3.

3. **Bot policy for AFK / early disconnect.** Options: (a) server runs a
   minimally-capable bot for the slot, (b) match continues as-is, (c) match
   is aborted and remaining players returned to queue.

4. **Anti-cheat scope.** Minimal: server validates all ability targets and
   cooldown states. No client trust for: position (server runs navmesh query
   and corrects teleports), damage numbers (server calculates), line-of-sight
   (server traces). A separate class of cheat ( Intent flooding, chat spam,
   account farming) requires a separate mitigation layer.

5. **Matchmaking algorithm.** Elo / Glicko-2 for ranked; casual queue for
   unranked. Party matching (2-stack, 3-stack) introduces skill variance
   handling.

6. **Region expansion.** If Singapore players connect to a HCM server and
   experience > 80 ms, do they get a different regional shard, or is one
   Singapore-hosted server enough for SEA?

7. **Reconnection replay window.** 60 s is a starting estimate. Mobile
   connections are less stable than PC; a shorter window means more
   forgiveness for brief disconnects but more server memory pressure.

8. **Intent grace period.** When a player issues a move command, the server
   should confirm it within N ticks. If the player's connection has 3 ticks
   of jitter, the grace period must be ≥ 3. Too short = frequent "intent
   rejected" micro-corrections. Too long = responsiveness suffers.

---

## 8. Vainglory RE Findings That Transfer, and Those That Do Not

### Transfers (principle, not implementation)

| Finding | Veilbound application |
|---|---|
| One environment, many navMesh variants | Zone-chunked authoring → same zone data, different placement table per mode |
| Typed placement table with transform + parameters | `ActorPlacementData` as the canonical match-initialisation artefact |
| Client-authoritative model is a design choice, not a necessity | Choosing server-authoritative with prediction gives us anti-cheat for free |
| 30-record placement table cross-validated from runtime memory | The server owns the authoritative placement table; clients receive a hash to verify they have the same version |
| Minimap as live icon layer | Minimap already renders from match state; no additional protocol needed |
| Fog of war baked as visMesh | Out-of-bounds / fog zones are authored as geometry; server marks them inaccessible, no separate system |

### Does NOT transfer

- `HF_*` blueprint naming — Veilbound uses its own entity vocabulary.
- BC1 / texture format pipeline — Unity handles asset loading; no custom
  header format needed.
- Blowfish + MD5(salt + match_id) key derivation — this is a Vainglory
  protocol detail that is both (a) SEMC IP and (b) irrelevant to Veilbound's
  own protocol design.
- Runtime memory dump technique for placement recovery — used for research
  only; Veilbound's placements are authored directly in the Unity editor.
- Community Edition MITM proxy architecture — appropriate for community
  reverse-engineering, not for a server-authored game where anti-cheat matters.

---

## 9. Relationship to the Current Veilbound Architecture

The current codebase already has structures that map to this design:

| Existing asset | Maps to |
|---|---|
| `ZoneAuthoringData` (ScriptableObject) | Zone chunk definition, shared between editor and server build |
| `ActorPlacementData` (ScriptableObject) | Typed placement record (§3b) |
| `AbilityDefinition` (ScriptableObject) | Action parameters serialised in intent log |
| `InstabilityTracker` | Deterministic state — this is the core rule engine |
| `IntentCommitFrame` | Client-side intent gate, maps to the intent log entry |
| `MatchState` | Subset of `GameState` (§3a) |
| Existing HUD event channel | The same events the minimap renderer consumes can be serialised for server broadcast |

The primary new components needed (when the goal is activated):

1. **Shared deterministic rule engine library** — a DLL / Unity assembly that
   runs identically on server and client, exposing `ApplyRules`.
2. **Veilbound.Network** assembly — intent serialisation, state delta codec,
   connection management, rollback logic.
3. **Game server process** — headless Unity server build, hosts the rule
   engine + network assembly.
4. **Matchmaking service** — separate process, simple REST gRPC API.

---

## 10. Next Steps (for when the goal is activated)

1. **User decision: fixed-point vs float-determinism** (§4). This is the
   single highest-impact architectural decision.
2. **Author the `DeterministicRuleEngine` interface** — define the exact
   `ApplyRules(state, intent) → (newState, events)` contract. Write the
   fuzzing harness that validates bit-exactness across two local processes.

   **Status [Observed]:** Reference Python implementation already
   written under `spikes/determinism/engine.py` (~110 LOC). Two-process
   positive + negative test pass.
   See [spike report](veilbound-multiplayer-spike-report.md) §3–§5.
   Spike does not substitute for a Unity-ground-truth test (§5a
   caveat, "Unity adds several non-determinism sources Python does
   not"); the C# port under Unity IL2CPP remains a prerequisite for
   committing to the float path.
3. **Prototype intent codec** — encode a move intent and an attack intent,
   decode them, validate round-trip. Measure bandwidth at 60 Hz.
4. **Write the placement table versioning scheme** — hash algorithm,
   version negotiation on connect.
5. **Stand up a minimal game server** — no matchmaking, two hardcoded
   clients, one deterministic tick loop. Validate that both clients reach
   identical tick N after 30 s of play.
6. **Performance test** — how many concurrent game server processes on one
   VPS at the target tick rate before CPU budget is exceeded?

Steps 2–5 are implementation tasks. Step 1 is the prerequisite decision.
Steps 2–5 require a new goal file (`veilbound-multiplayer-impl-goal-014.md`)
with its own scope and acceptance gates.

---

*Document status: research-only. No implementation. Awaiting user decision
on §4 (fixed-point) and activation of the multiplayer goal.*

*Companion: [spike report](veilbound-multiplayer-spike-report.md) — answers
the §10 step 2 sub-question with a positive+negative test outcome.*

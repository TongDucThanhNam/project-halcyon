# Next steps — close T1, open the T3 thin slice

Research brief produced 2026-09-05 (advisor pass + main-thread selective
verification). Role of this file: the **active hand-off plan** between
Phase 0 (closed — `phase0.md`) and the T1→T3 build work. It is a decision
record + router: measurement detail stays in the Teardown leaves cited
inline; this file holds status, decisions, and open gaps only.

## 0. Where we actually are (2026-09-05)

- **T2 closed.** `server/wire.py` + `gateway.py` + `match_server.py`;
  24/24 unit tests; corpus-validated decode (vgfull.pcap + 25 `.vgr`
  chunks = 31,266 frames, zero walk failures).
- **T1 broken through (menu tier).** `server/platform/local_stack.py`
  (hosts redirect, HTTP :80 + TLS :443, hot-reloaded `answers.json`)
  brought the unmodified PC client through guest auth into the menu:
  18-min stable run, 26 platform-RPC methods answered, all three big
  manifests (skin/season/buff) resolved. Mobile CE client also reaches
  the local menu (`vainglory-mobile-local-stack.md`).
- **Remaining T1 blockers.** (a) **Matchmaking/queue RPC schema unknown**
  — the exchange after `joinLobby` is unmapped (client sent `exitLobby`
  ×28, `joinLobby` ×1 over the day; no queue-family call captured);
  (b) manifest methods still retry-loop (~17k attempts each per day —
  answers not fully satisfying the client parser); (c) first Android
  direct-TLS attempt failed `UNKNOWN_CA` (device does not trust our
  self-signed cert yet).
- **T3: zero sim code.** Inputs are recovered and unusually complete —
  see §4 for the asset→use map and the ledger rows it cites.

## 1. Close T1 — matchmaking schema discovery (priority 1)

Ranked approaches:

| # | Approach | Speed | Confidence | Main failure mode |
|---|---|---|---|---|
| 1 | Audit **HackedGlory's published schema sheet** (see §5), cross-check against our `rpc.jsonl` captures, then verify live via `answers.json` hot-reload | Hours | High (it targets our exact build) | Their schemas are *inferred*, not authoritative — every field must be confirmed against our client |
| 2 | Patch the PC client (loader already armed, handler `0x4f1320`) to push past PLAY → MITM loopback + hot-reload answers | Hours–days | High | Anti-tamper silent exit; ACK schema incomplete → client hangs |
| 3 | Static strings grep (Ghidra) for queue/party method names near the known RPC patterns | Hours–days | Medium | Obfuscated/concatenated literals; stale RPC names |
| 4 | Brute-force `answers.json` until PLAY unlocks | Days–weeks | Low | **Rejected** — no feedback signal (client swallows wrong RPC silently) |

**Plan:** run 1 and 2 in parallel; 3 as fallback. Do NOT probe any live
remote backend (boundary rule 1) — discovery happens entirely against our
own client + local stack.

## 2. Open T3 — thin-slice build order (priority 2, starts in parallel)

**The gate: the entity-spawn opcode is unknown.** 1010 is a
position-update for a known entity; nothing in the 167-case dispatch
(`vainglory-protocol-wire.md` §15.8) is yet identified as "make entity X
appear". If the client will not render a hero, nothing downstream
matters — so spawn-opcode discovery starts **now**, in parallel with T1
(capture the wire at the moment a real match loads; probe the 1100–1110
join-sequence neighborhood).

Build order (each stage gated on the previous):

1. **Movement-only.** Spawn 1 hero at placement TeamA
   (`vainglory-3v3-map-structure.md`), tick loop echoes 1010 + 1011 for
   client 1012 inputs. Goal: hero visible and controllable. *(Estimate:
   movement + basic attack reachable in 1–2 weeks **if** the spawn
   opcode is found — estimate, not a commitment.)*
2. **Basic attack.** Dummy target, server validates range, emits
   1054/1053. Goal: damage popup + HP bar move.
3. **Minion waves.** 60 s spawner, ~12–14 entities, anchor-chained lane
   path. Goal: lanes alive.
4. **Turret aggro.** Simplest state machine (closest enemy in range),
   measured HP tiers. Goal: lanes fight.
5. **Death/respawn.** HP ≤ 0 → despawn → timer → fountain. Goal: the
   death loop closes.

Known per-stage unknowns (decode backlog — run alongside, not after):
entity-spawn opcode; full 1011 field map (only eid/team/HP/maxHP mapped
of the 124 B record); target-acquisition rule for basic attacks;
buy-item opcode (1134/1133 are open/close only); hero-select flow
(likely JSON-RPC, not wire); 1086 gold-award payload; 6/28 B of 1054
unmapped; per-level respawn curve (only 4 anchors). Full detail per gap
in the Teardown leaves; the complete 12-gap list lives in §4.

## 3. Determinism decisions (binding for T3)

1. **Checksums ride the existing 1011 snapshot** (subset hash: hero
   eid/team/HP/maxHP + x/z), plus per-event checks on 1054/1053 — never
   hash the whole world per tick (~513 ticks/s is infeasible).
2. **The client does not predict.** Evidence: no dedicated rollback
   opcode; corrections are re-issued 1010/1019 (ledger row 7). Client
   interpolates between 1010s — so the server owns the feel of the game.
   Tick budget ≈ 2 ms; Python is acceptable for the thin slice only;
   plan the C++/Rust port before hero count grows.
3. **Fixed-point integers for position (1e3) and yaw (1e4) from day
   one.** Python float is fine for same-platform dev; porting
   float-based state to C++/ARM64 diverges in `sin/cos/atan2/sqrt`.
   Presentation floats stay client-side.
4. **Late join = full-state dump** (candidate opcode 1114, the 2590 B
   snapshot our stub already emits) + input replay from the dumped tick.
   Replaying from tick 0 is not viable (18 min of input > connect
   timeout).
5. **Replay harness is a CI gate:** N-run byte-identical fuzz on the
   input-stream model (extend `Docs/Research/spikes/determinism/`),
   pre-allocated entity tables (GC pauses break tick budget), and after
   any port: Python-reference vs C++ cross-check per tick.

## 4. RE asset → server use map

| RE asset (source leaf) | Becomes, in the server | Transfer |
|---|---|---|
| Kit numbers, 97.5 % of 1,761 vars × 55 heroes (`vainglory-mechanics-matrix.md` §17–18) | Kit data tables loaded at boot; combat reads them directly | Direct |
| Combat formula `D=W/(1+A/100)`, `C/(1+S/100)`, crit ×1.5, ≈25 % pierce [Inferred] (matrix §19.2) | `apply_damage(attacker, victim, kind)` | Direct |
| 167-case dispatch + payload maps 1001–1168 (`vainglory-protocol-wire.md` §15.8) | The T3 event encoder + dispatcher | Direct |
| Movement anatomy: 28 B entity stride, ground-snap 0.007, anim clock (`vainglory-movement-anatomy.md`) | Server entity layout + locomotion FSM skeleton | Direct (layout) / partial (feel) |
| Navmesh + placement table + visMesh (`vainglory-3v3-map-structure.md`) | `world.json` init, A* pathfinder, (later) vision queries | Direct |
| Store/cipher tooling INST/PTCH (`vainglory-store-format.md`, `Tools/Teardown/`) | One-shot offline extractor → JSON dumps for the server | Direct (toolchain, not runtime) |
| Netcode topology (`vainglory-netcode-backend.md` §1) | Already embodied in T2 (`server/gateway.py`, `server/match_server.py`) | Direct — done |
| `.vgr` corpus + oracle bot matches (matrix §19) | **Verification oracle** — replay rule changes against ground-truth event streams | Direct, irreplaceable |
| Wave 60 s / HP tiers / jungle timers / start gold 600 (ledger row 8) | Scheduler + constants tables | Direct |

**Does not transfer** (client-side presentation/assets; out of server
scope): texture/BC1 codec work, VFX shadergraph containers, audio,
localization, talents (Blitz-only), SEMC `HF_*` blueprint naming (IP
rule — we use our own vocabulary).

**The 12 gaps T3 will feel** (discovery backlog; each is
capture-derivable, none is a dead end): entity-spawn opcode; target
acquisition / auto-attack rule; minion AI + lane polyline; turret aggro
state machine; ability targeting/AoE resolution rules; bot AI (only if
solo-practice bots are wanted); vision/FoW runtime rules (numeric radii
are a documented ceiling — thin slice runs no-fog); passive gold/XP
tick; hero-select flow; ping opcode family; buy-item opcode; XP
level-up thresholds. 

## 5. External leads register

| Lead | What it is | Status |
|---|---|---|
| **`a1cnore/HackedGlory`** (github.com/a1cnore/HackedGlory, MIT) | RE archive for **our exact build** (GameKindred 4.13.4 / 147219, iOS + Android): `method_schema_sheet.md` + `rpc_schemas.json` covering auth/social/party/guild/ranked/inventory/**matchmaking** JSON-RPC (inferred from static strings + Ghidra + captures — *not authoritative*), a mock JSON-RPC server, CE-gate map (`FUN_100131560`), `vg_unlock` client hooks, decrypted CFF0 balance JSON | **Verified 2026-09-05** (repo + README read). Contents not yet audited against our client — that audit is action item A1 |
| `VGReborn/VGReborn` | Community MITM/overlay stack (VPN architecture, Supabase state) — observability, **not** an authoritative server | [Unverified — advisor research] |
| XDA: Vainglory Community Edition (2020) | SEMC moved accounts/matchmaking client-local to cut costs; matches the operator's "simplified community stack" context | [Unverified — advisor research] |
| Reddit r/vainglorygame "Vainglory v2" | Claims a full binary-to-server revival | [Unverified — not read] |

## 6. Decision log (2026-09-05)

- **D1** — Matchmaking discovery = audit HackedGlory's schema sheet
  first, confirm each method/field against our client via `answers.json`
  hot-reload; patch+MITM in parallel. Brute-force rejected.
- **D2** — T3 opens with movement-only thin slice; entity-spawn-opcode
  discovery starts immediately in parallel (it gates everything).
- **D3** — Determinism decisions in §3 are binding for all T3 code
  (checksum-in-1011, no client prediction assumption, fixed-point
  position/yaw, 1114-based late join, replay harness as CI gate).

## 7. Update 2026-09-06 — T1 queue tier CLOSED; T3 handshake is the new gate

**T1 (a) resolved.** The joinLobby→match exchange is mapped and verified
on the mobile CE client (full evidence chain + reply shapes:
`vainglory-mobile-local-stack.md` §"Match-entry exchange verified"):
`joinLobby` acks `state:"pending_auto"`; the `update` long-poll drives the
FSM (`menus→pending_auto→matched_partners→match_pending→playing`; the
state `matched_partners` + `numQueuedEntries` is what triggers
`queryPendingMatch` — not `match_pending`, not notify categories);
`queryPendingMatch` reply shape decoded (`isValid/matchId/ttl/code/
responses[]`); with a self-accept roster the client auto-fires
`acceptMatch` (solo bots), and `update.state="playing"` with host/port
makes it open the match TCP socket and send the §15.1 route request —
verified end-to-end into our gateway.

**New gate (replaces T1-a): the post-route handshake.** The real client
sends nothing after the route request — the phase-0 assumption "client
sends 1000 first" is wrong. Key-derivation RE: key =
`MD5(SALT‖<session-singleton>+0xa8>)` (setter `0x00be262c`, salt
0x1ac8e97, globals 0x304b220/238). Open questions: which write fills
session+0xa8, and what s2c opener burst unlocks the client's c2s 1000
(candidates: §15.5's 104/752/1,616 B handshake frames from the real
capture). Next bounded step: find the session+0xa8 writer; decode and
replay the s2c handshake from the existing corpus. T3 movement slice
starts only after this gate — the client must reach its join sequence
(1000 → 1112/1131/1118/1123) before any spawn logic can be tested.

## 8. Update 2026-09-06 (later) — handshake gate CLOSED

Both §7 open questions are answered and verified live on the mobile CE
client (evidence + implementation notes:
`vainglory-mobile-local-stack.md` §"Post-route handshake closed";
protocol facts added to `vainglory-protocol-wire.md` §15.1):

- The gate was the **gateway route-ack** `[u16 3][00 06 00]` — one
  5 B plaintext frame ~0.2 s after the route request; the client's c2s
  1000 follows ~1 ms later. Client-first ordering was right all along
  once that frame exists.
- The **key input is the `playing` update's `matchId` field**
  (proven by A/B: absent → `MD5(SALT‖"")`, present →
  `MD5(SALT‖matchId)` = the vgfull.pcap key). The match server
  auto-detects the client's key on its first frame either way.
- Live result: c2s 1000 → opener burst (1001/1108/1107×275/1113) →
  **c2s 1112 + 1131** → the client renders the match screen with the
  countdown interpolating from our 1113 snapshot. The earlier "~30 s
  EOF + retries" was our own read timeout (now 300 s).
- **New gate: join completion = player roster.** The client renders no
  hero select, sends no 1118/1123/keepalives, and the team panels are
  empty — it has no slot/team/hero binding. Next bounded step: serve
  the local player in 1006 PLAYER_INFO + the 1113 snapshot player
  table (roster shapes exist in the corpus), then resume §2's build
  order (spawn opcode discovery → movement-only slice).

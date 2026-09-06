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
3. **Minion waves.** ~~60 s spawner, ~12–14 entities~~ *(corrected
   2026-09-06 by the wave-1 decode: 25.0 s interval, 10 lane minions = 5
   mirrored pairs, first wave at +22.974 s — §15, wire leaf §15.8)*,
   anchor-chained lane path. Goal: lanes alive.
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
| Wave timer **corrected: 25.0 s**, 10 minions/wave; HP tiers / jungle timers / start gold 600 (ledger row 8) | Scheduler + constants tables | Direct |

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

## 9. Update 2026-09-06 (later still) — roster exchange decoded and served

**Historical interpretation, superseded by §11:** the values called
player IDs/tokens below are hero selections; the claimed echo direction,
snapshot base and need for a stream to render the picker were incorrect.

The §8 gate is **decoded to the field level** from vgfull.pcap + c2s.bin
(match 1) and **implemented** in `server/roster.py` + `match_server.py`;
protocol facts recorded in `vainglory-protocol-wire.md` §15.8 (roster
block):

- **Binding mechanism:** s2c 1118 `[u32 player_id][u32 token][6B 0]` —
  the client echoes it byte-for-byte (c2s 1118). The same pid recurs in
  1006 (+164), 1011 (+0) and the 1113 record (+1); the roster uuid in
  1006 (+64) / 1113 (+89) is the **session uuid the client presented in
  c2s 1000**. Teams are 1-based (1113 rec[0]: 1|2), slots 1-based
  (rec[154]); the 1113 record base is **+16**, not +8 as earlier pinned.
- **Pick phase lives on the snapshot stream:** after 1113[0] (flags 0000)
  the server streams 1113 at ~2.5 Hz, flags 0101, countdown 7.0→0 — a
  silent server = dead pick UI (the earlier 30 s/300 s read-timeout
  symptom). The match read side now runs without an idle timeout; the
  SnapshotStream thread owns s2c and reaps dead peers via send errors.
- **Server sequence implemented:** opener burst → 1118 → 1113 stream →
  roster dump (1006×6 → 1135 → 1006×6 → (1011 + 1162×7)×6 reverse).
  1006 = 222 B; 1011 = 750 B with pid/token/eid/team header (stat run
  placeholder zeros); 1162 = 22 B zero timers. pids/tokens derived
  deterministically from the match id (§3 discipline).
- **Repo hygiene:** the verbatim 1001/1108 captured-payload hex left the
  repo — rebuilt as field builders (`roster.build_game_setup/_game_mode`)
  from the decode. No captured payload bytes remain in `server/`.
- **Tests:** 41/41 green incl. `-W error::ResourceWarning` (gateway pump
  now catches reset-mid-burst; `vgdecode.parse_pcap` uses a with-block).
  New coverage: `test_roster.py` (encoder shapes), corpus roster check in
  `test_corpus.py` (encoder output vs captured bytes), e2e extended to
  the full roster exchange with identity binding asserted.

**Next bounded step (unchanged direction, now unblocked): run the mobile
CE client against the local stack and validate live** — populated team
panels, hero select, c2s 1118 echo + 1123/1137 arriving — then start §2's
spawn-opcode discovery → movement-only slice. Open sub-gaps: 1011 stat
run content (zeros may starve the ability UI), 1162 timer values, and
what the client does when the countdown hits 0.

## 10. Update 2026-09-06 — roster live validation FAILED

The current implementation passed 41/41 tests with
`python -B -W error::ResourceWarning -m unittest discover -s server/test -t .`,
but **does not yet pass the mobile client gate**. Two local joins at host
10:59:50 and 11:00:01 reached c2s 1000 / 1112 / 1131 and then EOF about
one second later. No c2s 1118, 1123 or 1137 arrived; no roster-dump log
was reached. Android recorded GL-thread SIGSEGV / null dereference at
address 0x10. Guest and host timestamps differ; do not merge them directly.

An identity discrepancy is now observed: the local platform flow supplies
a JWT prefix in c2s 1000, whereas the corpus has a UUID. The current roster
builders truncate the supplied identity to 36 bytes. Therefore §9's claim
of exact local identity binding is not established for this platform flow.
This discrepancy is a candidate cause, **not a diagnosed crash cause**.

Next bounded step: isolate the reconstructed opener, token announcement,
and early populated snapshots using controlled local runs; establish the
client's actual identity-field contract before changing it. The 1011 stat
zeros were not reached in these attempts. Hero select, countdown completion,
and movement remain unverified. Evidence and operating state are in
`vainglory-mobile-local-stack.md` §"Roster live validation failed".

## 11. Update 2026-09-06 — roster crash fixed; hero selection verified live

Controlled local comparisons isolated the crash to **invented hero IDs**
in the initial 1113 snapshot. With the same rebuilt opener and identity:
the old snapshot survives; the new snapshot alone crashes; replacing only
the supposed player IDs with the corpus's `ffff` unpicked sentinel restores
the hero picker; replacing only the supposed tokens does not.

**1118 is client-initiated hero selection**, not a server-issued credential.
Without any s2c 1118, the client sent `(925, 2fd7245d)` for Amael. Clicking
Adagio sent `(244, f9fd7554)`. Echoing that pair and publishing the chosen
hero in 1113 renders Guest's portrait. Clicking Lock In sends 1123.
The corrected normal stack reproduced this flow at host 11:24–11:25 and
stayed connected after lock. The current client then waits on a dark
overlay; no 1119/1137 or gameplay has been verified.

The slot layout is also corrected: `8 B countdown + 16*161 B slots +
6 B padding`. The former +16 base omitted an 8-byte per-slot prefix and
mistook the next slot's prefix for the previous slot's tail. Slots are
zero-based, hero ID is +9 in each slot, identity occupies a 64-byte region.
See the wire leaf §15.8 for all offsets. The initial generated snapshot
now matches **every corpus byte** (using corpus display names/countdown).

Implemented: unpicked initial roster, per-connection selection state owned
by one writer, 1118 acknowledgement, local 1123 lock, corrected empty-slot
prefixes, and identity preservation through 64 bytes. Removed invented
per-match hero values, unsolicited 1118 and the timed placeholder gameplay
dump. The old tests' automatic-dump/credential premise was wrong and has
been replaced with corpus equality and client-initiated selection checks.
44/44 tests pass with ResourceWarning treated as errors; no test was relaxed
to conceal the live failure.

**Next bounded step:** establish what completes the post-lock UI and opens
gameplay: bot hero choices, 1119 semantics, and valid 1006/1011 initialization.
Do not resume the unconditional zero-stat dump. Complete the hero/skin
ID/hash mapping for semantic selection validation (currently only message
shape/range is checked), then revisit spawn discovery and movement.
Evidence and the A/B matrix are in the mobile leaf's "Hero-selection crash
isolated and fixed" section. No client payload files were changed.

## 12. Update 2026-09-06 (evening) — post-lock exchange decoded and served

The §11 three questions are answered from the corpus with an **ACK-precise
trace** (the TCP ACK of each c2s frame names exactly how many s2c bytes the
client had received — causality, not timestamps; tooling:
`$TEMP/vg_max/trace_after_lock.py` + `detail_after_lock.py`, outside the
repo). Protocol facts now live in the wire leaf §15.8 "Post-lock
world-init exchange closed". Highlights:

- **1119 = the lock commit**: c2s `[u32 committed hash][00 00]` in the same
  TCP segment as 1123; the server echoes it and the committed hash replaces
  the clicked 1118 hash everywhere (1113/1006 +168/1011 +4).
- **Bots lock with the countdown restart**: 8× identical 1113 at (7.0, 7.0)
  with every slot 0101 + hero; bot (hero, hash) pairs are measured client
  constants (`roster.BOT_HERO_CHOICES`). Countdown ticks ~10 Hz to 0.
- **Finalization at 0**: 1006×6 (final) + 1132 → ~23 s client map load →
  c2s 1134+1137 → world dump (1135, 1006×6, 1105, 1011+1162×7 reverse,
  1087×39, 1055×6, echoes, 1116 ~1 Hz). The gameplay firehose starts after
  c2s 1133.
- **1006 +168 corrected** to the committed selection hash u32 (the "XP
  f32" reading was a misread). **1011 tail pinned** (ff ff ff ff @741,
  slot u8 @745). **1087 is the strongest spawn-opcode lead** for §2 — its
  payload allocates sequential new entity ids with type codes.

Implemented in `match_server.py` (state machine PICK → LOCKED → FINAL →
WORLD; echo discipline: 1112/1131/1123/1119/1134/1137) and `roster.py`
(`commit_lock`, `BOT_HERO_CHOICES`, corrected 1006/1011, builders for
1132/1105/1055/1116/echoes). Deliberately NOT emitted: the 1087 spawn batch,
the 1053/1086/1087 steady stream, and real 1011 stat runs — invented
content crashes this client (§11); the acceptance run decides whether
zeros starve the UI. Two robustness fallbacks exist where the corpus is
silent: lock proceeds without 1119 after 1 s (keeping the clicked hash),
and the world dump fires on a 40 s timer if the client never sends
1134/1137 (a client past the tutorial may not).

Tests: 56/56 green with `-W error::ResourceWarning` (was 44). New: corpus
byte-equality for the all-locked final 1113, the final 1006 group (bot
guid field excepted — shared corpus constant, derivation open), 1011
headers + dump order, and the e2e now drives 1123 → 1119 → countdown →
1006×6+1132 → 1134/1137 → world dump. `decode.walk_stream` now decrypts
small 8-aligned frames, so 1119/1123/1132/1116-class messages appear as
named opcodes in decodes.

**Next bounded step (acceptance run):** take the mobile CE client through
the stack — expect: lock → locked countdown → loading screen → map render
→ client 1134/1137 on the local match log. If the map does not render, the
first suspects are, in order: the missing 1087 spawn batch, zero 1011 stat
runs, the derived 1055 tags. After the map renders, open the movement
slice (§2 stage 1) with 1010 ENTITY_FULL_UPDATE + 1070 POSITION, using the
1087 lead for the spawn path.

## 13. Update 2026-09-06 (night) — T3 movement slice LIVE: map renders, hero moves

The §12 acceptance run completed end-to-end against the mobile CE client.
The blocker from §12's suspect list was real and is fixed: the client
aborted world sync when the entity layer was invented/absent. The fix is
**architecture, not more invented bytes**: the WORLD phase now replays a
*real-time tape* of the corpus s2c stream (0..12.5 s after the 1137 echo —
1087 allocations, the delta stream, 1010 full updates, echoes at measured
positions; `server/world_tape.py`, tape file outside the repo per the
payload rule), preceded by the live-built dump with **measured** per-hero
1011 stat runs + 1162 timer sets (`roster.HERO_INIT_DATA`, 6 heroes).

Live-measured (wire leaf §15.8 has the protocol detail):

- Map renders fully (HUD, spawn-circle heroes with nameplates/HP, camera
  follow). Client stays in the match; re-queue eliminated.
- c2s 1133 accompanies the "Choose a Build" overlay; dismissed via Android
  BACK (no c2s). New c2s op-0 6-byte variant = f32 uptime ticker (~2 s
  cadence); strict 2-B keepalive parsing killed the match socket — now
  consumed (`match_server._dispatch`).
- **Movement slice closed**: tap → c2s 1012 (x,y) → server moves hero eid
  1500 and streams 1070 at 0.2 s (spawn −78.18/0.88 → −70.25/3.01 verified
  on screen). Spawn floats equal 1011 stat-run +18 — behavior-confirmed.

Tests: 65/65 green (`-W error::ResourceWarning`). New since §12: tape
loader unit tests, corpus-pinned 1070/1012 layout tests, e2e movement
leg (1012 → ordered 1070 stream for eid 1500). The stale-elevated-stack
situation is handled by a second stack on gateway ports 7102/2114 sharing
the same hot-reloaded `answers.json`; `local_stack.py` now tolerates the
:80/:443 bind conflict.

**Next bounded step (T3 begins):** replace tape segments with real
simulation, one op family at a time, keeping the client in-session as the
oracle — order: 1010 full-update generation for the local hero (from the
movement state we already own), then 1087 spawn of one minion wave, then
1053/1086 stat deltas. The determinism decisions in §3 bind from here.

## 14. Update 2026-09-06 (late night) — họng 1010: hero full-update sim thay tape im lặng

Measure → build → test → live per the t3-slice protocol. **Measure**: all
173 corpus 1010s of wire match 1 decoded with `$TEMP/vg_max/measure_1010{,b,c}.py`,
plus a second pass over the `.vgr` match-5 corpus (all 6,472 1010s of
169,963 parsed frames). Findings (full offset table with evidence in wire
leaf §15.8 "1010 measured on the wire"): **two payload variants** — 126 B
(no HP; all of match 1, 821 of match 5) and 122 B (**HP@+36, maxHP@+40**;
5,651 of match 5 — turret tiers 5000/3000, minion 450-class). Common head:
`+0` u32 eid; `+4` u32 entity-class id (match 1: 4 values, 1:1 eid
groups, [Open]); `+8` u32 global entity-write tick (+1/frame in bursts,
advances with the rest of the entity stream between bursts — not a
fixed-rate clock); `+12/+16/+20` x / z(0.00707 ground) / y; `+24/+32`
facing (cos, sin) — every pair a unit vector, idle default (0, 1).
Combined census: **0 / 6,645 hero-1010s** — the real server never sends a
1010 for a hero; hero state rides 1011 + 1070 + 1053/1086. Minions and
statics DO get 1010s, with HP in the 122-B variant.

**Build**: `roster.build_entity_full_update` (pure; caller owns the shared
`world_tick` u32 and per-1010 `seq` u8 — both +1 per emission, 1086's u16
counter will join the same family later; `hp=None` → 126-B,
`hp=(cur,max)` → 122-B) + `roster.facing_toward`.
**Wiring** (`match_server._run_world`): first hero 1010 5 s after the live
layer starts (`roster.HERO_1010_PERIOD` — corpus per-entity refresh ≈5–6 s),
then every 5 s, position read at send time so it is always consistent with
the 1070 stream; `_step_hero` now tracks facing from the motion vector.
`HALCYON_NO_TAPE=1` skips the corpus tape entirely (pure-sim world without
deleting the operator's tape file).

Tests: 76/76 green (`-W error::ResourceWarning`). New: 1010 proven-field
layout vs corpus frame-1 fragments (no full raw frame pinned — payload
rule), [Open]-template defaults, tick/seq monotonic + u8 wrap, x/y f32
re-pack equality with 1070; 122-B HP-variant layout vs the match-5 sample;
e2e no-tape world (join → lock → dump → no tape → 1010 at spawn with
tick/seq 1 → 1012 walk with mid-walk 1010s in-segment → post-arrival 1010
exactly at target); HALCYON_NO_TAPE + HALCYON_HERO_1010 flag unit tests.

**Live (two runs, and the premise was falsified by the first)**:

- *Hero-1010 ON (14:58)*: the server emitted the first measured-shape hero
  1010 for eid 1500 right after the tape completed; the client EOF'd the
  match socket **1 s later** (14:58:18 first frame → 14:58:19 EOF) and
  re-queued at 14:58:28. The corpus silence about hero-1010 is real server
  behavior, not a capture gap. Fix by architecture, not by weakening the
  finding: hero-1010 is **default-OFF** behind `HALCYON_HERO_1010=1`.
- *Default path (15:35–15:40)*: join → lock (1 s 1119-fallback) → world
  dump → tape complete 15:38:21 (log: "hero 1010 OFF, 1116 pings,
  1012→1070 movement") → client stayed in match well past the 60 s gate
  (51 op-0 uptime keepalives consumed post-tape, zero EOF/reset, zero
  `am_crash` in the window) → tap → c2s 1012 → move target (−71.62, 0.09)
  → 1070 stream, camera followed on screen. Acceptance met.
- *Live-ops notes*: (1) the `matched_partners` accept-screen transition
  segfaulted 3/3 tonight (libhoudini class — every crash happened before
  any match connection existed); the known-good route is to skip the
  accept screen and flip `update` → `playing` directly after `joinLobby`.
  (2) An emulator reboot wipes the hosts bind-mount, iptables redirects
  and CA overlay (mobile leaf's roll-forward list) — the client then
  resolves real SEMC IPs and shows "Unable to connect"; re-apply the
  mounts + rules + `adb reverse` before relaunching.

**Next bounded step (họng kế):** hero-1010 is dead as a hero throat — the
122-B HP variant builder is the template for **1087 spawn của 1 minion
wave** (minions receive 1010s with HP in the corpus) từ allocation layout
đã đo (blob 40 B, new eid tuần tự từ 0x7d6) → sau đó 1053/1086 stat
deltas theo damage giả lập trên dummy. Mỗi họng giữ nguyên trình tự
measure → build → test → live.

## 15. Update 2026-09-06 (late night II) — T3 slice 2 LIVE: lane-minion wave spawn

Slice 2 của `Docs/Plan/t3-slice-2-prompt.md`, đo → build → test → live.
**Premise của prompt bị chính phép đo falsify** (đúng luật của slice
protocol): minion wave **không** đi qua 1087 và **không** dùng 1010
122-B HP — wave-1 spawn thật là **1010 126-B + 1016 + 1070 + 1067**.
Toàn bộ layout + bằng chứng đã vào wire leaf §15.8 (block "Lane-minion
wave spawn measured on the wire"); những con số định mệnh:

- Wave 1 tại **+22.974 s** sau 1137-ack, interval **25.0 s chính xác**
  (6 mốc pinned) — **sửa claim "60 s, 12–14 entities"** mà §3 Build
  order và bảng HackedGlory đang mang; mỗi wave = **10 lane minion**
  (5 cặp mirror phải/trái, offset 0/0.92/1.94/2.86/3.88 s).
- Eid cấp tuần tự từ 4610, chẵn=phải/lẻ=trái; spawner eid của cặp dùng
  chung (366,366,367,365,365) — trùng group 365..368 của bảng §15.6.
- Walk 4.5 u/s theo polyline lane team (đầy đủ trong
  `server/roster.py::LANE_PATH_*`), 1070 heartbeat 1.33 s, **vẫn heartbeat
  khi đứng nghỉ cuối lane**; 1067 `[eid][side][01][state][7×0]`
  (side 01 trái/02 phải, state 00 spawn/0f di chuyển), 1016
  `[seq][x][y][5×0]` là target đầu tiên của walker.

**Build**: `server/roster.py` thêm builder thuần `build_minion_spawn_1010`
(id-map 126-B đúng measure), `build_entity_state`, `build_move_intent` +
constants lane; `server/wave.py` (mới) — `Director` deterministic: mọi
giờ suất sinh từ (t0, tick), không random, không wall-clock vào state;
`server/match_server.py` — director armed tại tape_base (anchor 1137-ack),
`seq_1010` kế thừa đếm 1010 của tape; kill switch **`HALCYON_NO_WAVE=1`**
từ ngày đầu. Hero mặc định **không bao giờ** nhận 1010
(`HALCYON_HERO_1010` vẫn OFF — §14 đã chứng minh live làm client EOF).

Tests: **90/90** xanh (`python -B -W error::ResourceWarning -m unittest
discover -s server/test -t .`; baseline 76 + 12 unit `test_wave.py` + 2
e2e). Unit pin từng byte-shape (hex điểm lane `428e8f5c`/`414ee148`,
tail theo bên, seq wrap) và lịch determinism (wave 2 = eid 4620..4629,
walk monotone tới (1.500, 5.500)); e2e no-tape: join → lock → dump →
burst đúng thứ tự corpus `[1010,1016,1070,1010,1016,1070,1070,1070,1067,
1067]` → 10 eid 4610..4619 → 20 1067 (mỗi eid `00` rồi `0f`) → 1070
stream tới cuối lane; `HALCYON_NO_WAVE=1` im lặng hoàn toàn. Hai test
đã bắt được 1 bug suite-thật: `TestNoTapeFlag` để lại
`HALCYON_HERO_1010=1` trong env khi `old is None` — đã sửa hygiene
(pop vô điều kiện trong finally), không có test nào bị giảm độ khắt khe.

**Việc 0 — `server/platform/guest_setup.py`** (1 lệnh
`python -m server.platform.guest_setup`): re-apply toàn bộ routing sau
reboot — bind hosts/cacerts overlays, 4 firewall rule tagged
`halcyon-*`, 4 `adb reverse`, kết thúc bằng verify guest
`ping rpc.kindred-live.net → 127.0.0.1`. Idempotent theo **hiệu lực nội
dung**, không theo mechanism: trên LDPlayer này `/system/etc/hosts` và
`.../cacerts` là mount point của block device riêng (`/dev/block/sdb2`)
nên bind cũ không còn trong `/proc/mounts` sau snapshot — script kiểm
tra nội dung (tên platform trong hosts, CA `41e9eb4e.0`) và skip khi đã
có hiệu lực. Firewall check theo marker (`-S OUTPUT` là normalized,
comment + `--to-ports` làm dấu hiệu riêng từng rule — 2 rule nat dùng
chung comment nên phải phân theo port). Chạy thử thật: 2 lần liên tiếp
→ lần 2 toàn "ok (already)", rule count ổn định 1/1/2, verify pass.
Hai bẫy đã ghi vào script docstring: `adb shell su -c` phải bọc **một
chuỗi được quote** (không thì su chỉ nhận token đầu), và khôi phục
adb-server khi shell treo (transport `device` không đảm bảo shell sống).

**Simplification ghi rõ**: mọi cặp trong sim đi hết polyline team tới
(±1.5, 5.5); corpus cho thấy cặp 2–5 dừng sớm hơn (x ±9.5..10.5) — vị
trí dừng theo cặp là [Open], chưa đo riêng.

**Next bounded step**: turret aggro (§3 Build order mục 4) trên nền
wave đã sống — state machine gần nhất-trong-range, HP tier đã đo, damage
qua 1054/1053 khi hai lane giao nhau; hoặc basic-attack dummy nếu aggro
cần thêm dữ kiện target-acquisition.

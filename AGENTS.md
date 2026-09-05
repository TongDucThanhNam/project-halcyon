# AGENTS.md — Project Halcyon

Entry point for this repository. This project is a
separate effort with a different mission and its own guardrails. Read both
sections below before doing anything; then open only the leaf that matches the
task (progressive disclosure — do not scan `Docs/` or preload logs).

## Mission (the north star)

Build a **faithful, self-hosted, PvP Vainglory private server** for a small
friend-group (Hồ Chí Minh), reproducing **100 % of Vainglory gameplay** from
our own reverse-engineering results. The client (Vainglory 4.13.4, build
147219) is kept **as-is unless we deliberately repack it** — we control it, so
repacking is allowed when it removes a blocker (e.g. bypassing the TLS-443
menu RPC).

The plan, in one line: **test against a local server first, then stand up the
real authoritative simulation server** from the decoded wire protocol + the
recovered rule layer.

This is the **"Làm" (doing)** project. The RE knowledge base under
`Docs/Teardown/` is the **"Hiểu" (understanding)** input. The binding framing
carried over from the research: *understanding is not implementation* — the
knowledge tells us **how Vainglory communicates**, not **what its server
computes**. Rebuilding the server means reimplementing the authoritative game
simulation server-side. That is the actual work.

## What this repository holds

| Path | What it is |
|---|---|
| `Docs/Teardown/README.md` | **Router** for the whole Vainglory RE knowledge base (use when the task index below is insufficient) |
| `Docs/Teardown/*.md` | Every RE leaf: protocol wire, netcode backend, mechanics matrix, rule layer, store/cipher, runtime method, dead-ends, knowledge ledger |
| `Tools/Teardown/` | Read-only inspectors + reproduction scripts (content store, BC1, navmesh, codec probe, memory scan, placement) |
| `Docs/Research/` | Reference design + working determinism spike (input-stream model, delta replay) — the seed for the server-authoritative sim |

Artifacts that are **never** in this repository (by IP rule, see below):
`.pcap`, `.vgr`, decrypted payloads, extracted textures/models, the deobfuscated
binary — all such collection lives outside the repo (see `TEMP` paths below).

---

## Binding boundaries

These are inherited from the research campaign and remain binding. They are a
mix of legal discipline and technical safety.

1. **Read-only towards anything we did NOT stand up.** All capture was passive
   observation of our own rooted emulator / own device. We do **not** probe,
   scan, or inject packets into a live remote Vainglory/community backend, and
   we do **not** intercept TLS on someone else's connection. Reimplementing the
   protocol for **our own server** is in-scope; attacking a live one is not.

2. **No proprietary payloads/assets in the repo.** No Vainglory texture, model,
   shader implementation, executable, decrypted store payload or `.vgr`/`.pcap`
   enters the repository. We keep structure, constants and reproducible
   commands. (The 64-byte obfuscation salt is a constant, not payload content.)

3. **Private, non-commercial operation.** This is a friend-group server. Do not
   redistribute SEMC assets or republish the game payloads. Know that
   reproducing Vainglory's protocol and gameplay is legally sensitive; run it
   quietly and privately.

4. **Determinism is the product.** The authoritative sim must be deterministic
   and fixed-tick. Every outcome must be reproducible from input intents — that
   is exactly the transport the wire protocol uses (input-stream model,
   client-streams-input). No randomness in combat rules.

5. **Never weaken a test/check to make it pass.** Decide honestly whether the
   code or the premise is wrong, and say which.

6. **Do not commit unless asked.** Keep the worktree honest; report diffs, do
   not auto-commit.

---

## Progressive-disclosure task index

Choose the smallest matching leaf below. Use `Docs/Teardown/README.md` only
when broader routing is needed. Keep commands, evidence, and capture paths
in the leaf; this entry point holds routes and brief status only.

| Task | Open first | Reveal next only when needed |
|---|---|---|
| Overall protocol, transport, crypto, join sequence | `Docs/Teardown/vainglory-protocol-wire.md` (§15) | `vainglory-netcode-backend.md` (§14) for topology |
| Backend / gateway / relay architecture | `Docs/Teardown/vainglory-netcode-backend.md` (§14) | `vainglory-protocol-wire.md` §15.1–15.2 for the gateway route-request + heartbeat |
| Mobile CE local-server startup, LDPlayer routing/TLS, or lobby entry | `Docs/Teardown/vainglory-mobile-local-stack.md` | `vainglory-runtime-reconstruction.md` only for additional emulator capture methods |
| Legacy PC menu replies, watchdog errors, or date workaround | `Docs/Teardown/vainglory-pc-client-internals.md` | The mobile leaf above when validating the target CE client |
| What is known vs. what is the ceiling (which layer is "Hiểu" and which is not) | `Docs/Teardown/vainglory-knowledge-ledger.md` | The `## Ceiling` row 10 (server sim interior) |
| Gameplay rule layer: combat math, wave/jungle timers, HP tiers, economy | `Docs/Teardown/vainglory-mechanics-matrix.md` (§8/§14/§19, `## Offline combat-math pass`) | `vainglory-3v3-map-structure.md` for placement/anchors |
| Hero / item / ability **numbers** (kit data) | `vainglory-mechanics-matrix.md` §17–18 | the store leaf for the `INST`/`CFF0` cipher if re-extraction is needed |
| What was already tried and stopped (do not re-attempt binary RE / codec cracking) | `Docs/Teardown/vainglory-dead-ends.md` | `vainglory-runtime-reconstruction.md` for the sanctioned runtime route |
| Store format / container / cipher | `Docs/Teardown/vainglory-store-format.md` | `Tools/Teardown/` scripts |
| How to capture / reproduce evidence on the emulator | `Docs/Teardown/vainglory-runtime-reconstruction.md` | `vainglory-artifact-reproduction.md` for exact counts + corrections |
| Building the deterministic server-authoritative sim | `Docs/Research/veilbound-multiplayer-design.md` (input-stream model) | the determinism spike under `Docs/Research/spikes/determinism/` |

When no row matches, stay with this file and the source. Do not load docs "just
in case."

---

## The build blueprint (what a self-hosted server actually needs)

The client is a thin renderer over a deterministic sim; the **server is
authoritative**. To self-host we must build three tiers:

| Tier | What it is | RE status | Difficulty |
|---|---|---|---|
| **T1 Front door** | preauth bootstrap + platform RPC (TLS JSON-RPC menu/auth/matchmaking) | **Partial** — mobile CE local menu verified; lobby/matchmaking schema remains open (see mobile leaf above). | Open |
| **T2 Gateway + match server** | frame grammar `[u16 BE len][body]`, Blowfish ECB per-match key, route-request greeting, join handshake, heartbeat | **Closed** (`mock_gcp.py` round-trip proved encode/decode) | Easy |
| **T3 Authoritative simulation** | run the actual game logic: movement, ability effects, minion/jungle AI, turret aggro, vision/FoW, XP/gold, death/respawn, win/lose — and emit the event stream | **The ceiling** — not recovered; must be reimplemented | Hard |

**T3 is the real work.** T2 is the provable warm-up. The rule-layer *numbers*
(kit 97.5 %, combat `D = W/(1+A/100)`, wave 60 s, HP tiers 2500/3000/3500/5000/
10000/448, economy) are recovered, but the *engine mechanics* — how a skill
resolves, how bots decide, how targeting/pathing works, aggro state machines —
are not, and must be derived or rebuilt.

---

## Tooling

- The shipped RE inspectors are Python 3.11+ in `Tools/Teardown/` (read-only).
  `lz4`/`zstandard` only for the bounded codec probe.
- The determinism reference implementation is pure Python under
  `Docs/Research/spikes/determinism/` (`engine.py` / `run_process.py` /
  `verify.py`) — a working input-stream sim skeleton we can evolve into T3.
- Corpus / TEMP locations are **outside** the repo and are up to the operator:
  `D:/Downloads/vg/` (client / store / PC build), `$TEMP/vg_max/` (decrypted
  + extracted outputs), an emulator capture tag. Never copy payloads in.

## Current phase

Phase 0 (T2 wire layer, corpus-validated) — plan in `Docs/Plan/phase0.md`.
Server source lives in `server/` (`wire.py`/`decode.py`/`gateway.py`/
`match_server.py`); `server/mock_gcp.py` + `server/vgdecode.py`
are the reference round-trip proof and reusable decoder brought in from the
corpus.

Latest client checkpoint: mobile CE 4.13.4 (147219) reaches the local menu;
`joinLobby` is the next blocker. Open the mobile leaf above for evidence and
reproduction. Match entry and T3 gameplay remain unverified.

## Report discipline

- Run `git status` and read the relevant `Docs/` leaf before modifying anything.
- After each round: report affected paths, tests/checks, and unresolved
  warnings; `git diff --stat`; never commit with red checks.

> Initialize or reinitialize git only when the operator asks.

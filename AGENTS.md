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

Artifacts that are **never tracked in Git** (by IP rule, see below):
`.pcap`, `.vgr`, decrypted payloads, extracted textures/models, the deobfuscated
binary. Per the operator's 2026-09-13 relocation request, owned inputs may
live physically under the project's Git-ignored `Local/` directory. New QA
evidence stays outside the checkout. See `Docs/Setup/windows-local-development.md`.

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
   enters Git or a distributed source archive. Operator-owned copies may live
   under ignored `Local/`; do not force-add or redistribute that directory.
   We keep structure, constants and reproducible
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
| New developer setup, downloads, LDPlayer/root, local files or migration | `Docs/Setup/windows-local-development.md` | `vainglory-mobile-local-stack.md` for historical routing evidence |
| Overall protocol, transport, crypto, join sequence | `Docs/Teardown/vainglory-protocol-wire.md` (§15) | `vainglory-netcode-backend.md` (§14) for topology |
| Backend / gateway / relay architecture | `Docs/Teardown/vainglory-netcode-backend.md` (§14) | `vainglory-protocol-wire.md` §15.1–15.2 for the gateway route-request + heartbeat |
| Mobile CE local-server startup, LDPlayer routing/TLS, or lobby entry | `Docs/Teardown/vainglory-mobile-local-stack.md` | `vainglory-runtime-reconstruction.md` only for additional emulator capture methods |
| Evaluate external matchmaking/T3 advice or community-source leads | `Docs/Teardown/vainglory-implementation-brief-review.md` | Follow only the source or mechanics leaf needed for the claim under review |
| Community ecosystem tricks & leads (VGNA, HackedGlory, VGReborn, Real Data strategy) | `Docs/Teardown/vainglory-community-ecosystem-tricks.md` | `vainglory-implementation-brief-review.md` for historical lead audit |
| Legacy PC menu replies, watchdog errors, or date workaround | `Docs/Teardown/vainglory-pc-client-internals.md` | The mobile leaf above when validating the target CE client |
| What is known vs. what is the ceiling (which layer is "Hiểu" and which is not) | `Docs/Teardown/vainglory-knowledge-ledger.md` | The `## Ceiling` row 10 (server sim interior) |
| Gameplay rule layer: combat math, wave/jungle timers, HP tiers, economy | `Docs/Teardown/vainglory-mechanics-matrix.md` (§8/§14/§19, `## Offline combat-math pass`) | `vainglory-3v3-map-structure.md` for placement/anchors |
| Hero / item / ability **numbers** (kit data) | `vainglory-mechanics-matrix.md` §17–18 | the store leaf for the `INST`/`CFF0` cipher if re-extraction is needed |
| What was already tried and stopped (do not re-attempt binary RE / codec cracking) | `Docs/Teardown/vainglory-dead-ends.md` | `vainglory-runtime-reconstruction.md` for the sanctioned runtime route |
| Store format / container / cipher | `Docs/Teardown/vainglory-store-format.md` | `Tools/Teardown/` scripts |
| How to capture / reproduce evidence on the emulator | `Docs/Teardown/vainglory-runtime-reconstruction.md` | `vainglory-artifact-reproduction.md` for exact counts + corrections |
| Building the deterministic server-authoritative sim | `Docs/Research/veilbound-multiplayer-design.md` (input-stream model) | the determinism spike under `Docs/Research/spikes/determinism/` |
| Current Tier 1 solo sandbox implementation and acceptance | `Docs/Plan/solo-sandbox.md` | `solo-sandbox-acceptance-status.md` and the subsystem leaf linked for the scenario |
| Repeatable Skye/minion scenario verification and reference comparisons | `Docs/Plan/solo-sandbox-scenarios.md` (shipped pilot: `Tools/run_scenarios.py` headless scenarios, two-process exact repeatability, client driver, reference interface) | `solo-sandbox-acceptance-status.md` for active gate status and the relevant subsystem leaf for the scenario under test |
| After Phase 0: closing T1 (matchmaking schema) and opening the T3 thin slice; RE-asset→server mapping, determinism decisions, open gaps | `Docs/Plan/next-steps.md` | the Teardown leaves it cites per row |

When no row matches, stay with this file and the source. Do not load docs "just
in case."

---

## The build blueprint (what a self-hosted server actually needs)

The client is a thin renderer over a deterministic sim; the **server is
authoritative**. To self-host we must build three tiers:

| Tier | What it is | RE status | Difficulty |
|---|---|---|---|
| **T1 Front door** | preauth bootstrap + platform RPC (TLS JSON-RPC menu/auth/matchmaking) | **Local CE flow verified** — menu, draft and match entry support the solo sandbox; broader platform/PvP completeness remains separate | Open |
| **T2 Gateway + match server** | frame grammar `[u16 BE len][body]`, Blowfish ECB per-match key, route-request greeting, join handshake, heartbeat | **Closed** (`mock_gcp.py` round-trip proved encode/decode) | Easy |
| **T3 Authoritative simulation** | run the actual game logic: movement, ability effects, minion/jungle AI, turret aggro, vision/FoW, XP/gold, death/respawn, win/lose — and emit the event stream | **Solo acceptance reopened** — `Docs/Plan/solo-sandbox.md`; September 8 operator defects reopened acceptance; individual Skye/projectile behaviors and minion movement have since been observed locally, but repeatable acceptance and official fidelity remain open | Hard |

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
- Owned client/store inputs live in ignored `Local/vainglory/`, research inputs
  in `Local/research/`, and platform configuration in `Local/runtime/halcyon_stack/`.
  `server/paths.py` supports explicit overrides and legacy locations. Historical
  `D:/Downloads/vg/` and `$TEMP/vg_max/` references remain evidence provenance.
  Keep new QA output outside the checkout; never track payloads in Git.

## Verification strategy

**Scope:** The full faithful self-hosted PvP / 100 % gameplay target is unchanged.
The current pilot scenario (repeatable Skye/minion verification) is a workflow
qualification, not a scope reduction or an overall-completion claim.

**Evidence-driven verification before expanding.** Every defect gets a named scenario
with: exact source/client version, reproducible initial state, input sequence, observed
versus expected outcome, and external evidence artifacts. Establish repeatable results
before adding new gameplay implementation. Reuse `Tools/verify_sandbox.py`,
`Tools/sandbox_qa.py`, and production `SnapshotStream.advance_simulation`; extend
these rather than inventing a parallel toy engine.

**Scripts own time-sensitive client execution.** Check HP/energy/ranks/available
points/cooldowns/target validity and required target lock, perform the bounded UI
sequence, retain timestamps, input/response trace and video as needed. No model/tool
reasoning round trips between a basic hit and the dependent short-lived cast.
Automation must report distinct observed stages: missing input; rejected/ignored input
(explicit rejection only when actually observed — otherwise unacknowledged with unknown
reason); accepted operation; and authoritative outcome plus visible presentation.
Unknown presentation is unverified, not automatically missing. Setup failure must not
be called a gameplay regression. QA preparation is allowed only within acceptance-leaf
scope; QA damage/forced casts cannot prove real UI behavior.

**Headless for simulation; rendered client for acceptance.** Use short headless scenarios
through actual production integration for simulation diagnosis and regression, with
necessary nav, structures/turrets and lifecycle enabled. Use the rendered CE client to
establish native presentation. Keep real-duration soak/long-timer tests when those are
the claim; do not replace acceptance with artificially sped-up time or isolated
subsystems.

**Independent gameplay fidelity.** Reuse owned captures first, then ordinary-client
passive observation for missing cases, preserving rank/items/HP/positions/time and
relevant inputs. Local Halcyon recordings prove Halcyon behavior only. Recorded server
outputs alone (`.vgr`) are not a complete computation oracle. Compare semantic outcomes
after explicit identity/time normalization and measured justified tolerances; never claim
raw packet equality guarantees official fidelity. Determinism within our same
implementation stays exact.

**Community tooling scope.** VGNA replay/spectator is an evaluation lead for repeated
visual reference; HackedGlory is capture/decoder research; VGReborn is matchmaking
integration. None is evidence of a complete replacement simulation. The original Trick 8
zero-noise/AFK swarm assertions are superseded by the opening review in
`Docs/Teardown/vainglory-community-ecosystem-tricks.md`. Headless clients only against
our own server under existing boundaries. Do not restart binary/codec dead ends without
genuinely new evidence routed through existing leaves.

**Delegation discipline.** Delegate bounded scenario/tool or subsystem changes with
explicit outputs and checks; one owner per emulator/runtime and per overlapping file set.
Agent summarizes measured results with artifact paths; parent reviews. Don't spend cycles
on repeated ad-hoc screenshot probing or re-discovering known trace layouts. Stop a
failed experiment with preserved evidence and a classified unknown instead of blind
repeated retries; continue independent work. Do not add permission gates.

**Pilot implementation and evidence (reviewed 2026-09-13).** The repeatable
command for current Skye and minion/turret cases is
`python Tools/run_scenarios.py --mode headless --scenario all`: production headless
scenarios run in two seeded independent processes over one pinned source snapshot and
are accepted by exact event/state byte comparison, with machine-readable failure
stages and preserved external evidence. `--mode client --scenario ...` drives the
implemented rendered-client path (`Tools/scenario_client.py`), which is mock-tested;
the reviewed September 12 records contain two accepted A attempts in one match
and two B and two C attempts on separate fresh matches for each ability. Those
records did not run the compare-pair contract and their presentation remains
unreviewed. Three bounded minion observation windows establish approach/combat
but not survivor resumption or structure interaction. The corpus
`world_tape.bin` was rebuilt byte-faithfully by `Tools/build_world_tape.py`
(loader-digest-proven). An idle ~30-minute client crash remains open — see
`Docs/Plan/current-status.md` and `Docs/Plan/solo-sandbox-scenarios.md`;
independent reference fixtures are an interface only — without one the reference
status is `UNAVAILABLE`. See
`Docs/Plan/solo-sandbox-scenarios.md` for commands, schema and the demonstrated
status. Do not invent another executable path for these scenarios.

**Measurement hierarchy.** Distinguish: harness repeatability, internal determinism,
visible client acceptance, and independently measured gameplay fidelity. A passing test
count alone never closes faithful-gameplay acceptance.

**Artifacts.** Keep all QA output outside the repo; never delete old journals/captures
to prepare a new run; allocate unique output directories. The existing boundary on no
assets/payloads in the repo remains unchanged.

## Current phase

Phase 0 is **closed** (2026-09-05; `Docs/Plan/phase0.md`). The current
concise progress report is **`Docs/Plan/current-status.md`**; the detailed
gameplay acceptance record is **`Docs/Plan/solo-sandbox.md`**.
**Acceptance is reopened:** September 8 operator defects reopened acceptance;
local fixes and individual Skye/projectile behaviors and minion movement have
since been observed, but repeatable acceptance and official fidelity remain open.
Consult the linked leaf for active gates, evidence, and current defect status.
The operator's "Tier 1" names solo gameplay
acceptance, distinct from the platform T1 tier in the architecture above.

`Docs/Plan/next-steps.md` retains the historical Phase 0 hand-off and design
decisions; its zero-simulation and unknown-match-entry statements are
superseded by the current implementation record.

## Report discipline

- Run `git status` and read the relevant `Docs/` leaf before modifying anything.
- After each round: report affected paths, tests/checks, and unresolved
  warnings; `git diff --stat`; never commit with red checks.

> Initialize or reinitialize git only when the operator asks.

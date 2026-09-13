# Project Halcyon

> **Authoritative, Deterministic, Self-Hosted Game Server for Vainglory (4.13.4, build 147219)**  
> Built from pure reverse-engineering research and clean-room protocol reimplementation.

🌐 **Languages**: [English](README.md) | [Tiếng Việt](README.vi.md)

**Status reviewed September 13, 2026:** an experimental server with recorded
single-client gameplay and automated simulation coverage. Overall gameplay
acceptance remains **OPEN**. Start with the
[current status and limitations](Docs/Plan/current-status.md); the
[scenario evidence](Docs/Plan/solo-sandbox-scenarios.md) distinguishes live
observations, test fixtures, and remaining validation work.

---

## 1. Mission & Engineering Philosophy

**Project Halcyon** aims to reproduce 3v3 Vainglory gameplay on a self-hosted private server for friend-group matches. The current solo sandbox has been tested against the unmodified Android Community Edition client (CE 4.13.4, build 147219); broader PvP and complete native hero fidelity remain separate work.

* **Core Philosophy**: *"Understanding is not implementation."* Protocol teardown reveals how the Vainglory client communicates over the wire, but provides zero server computation logic. The authoritative simulation engine must be designed, modeled, and engineered entirely from scratch.
* **Operational Criteria**: Fixed-tick determinism, pure input-stream replication, and low-latency response (<30 ms on local networks).

---

## 2. System Architecture

The server adopts a decoupled 3-tier architecture:

```
                        [ Vainglory Client (CE 4.13.4) ]
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
   HTTPS/TLS (8443)             TCP Gateway (7100+)            UDP Relay (2112)
        │                              │                              │
        ▼                              ▼                              ▼
┌──────────────────┐          ┌──────────────────┐          ┌──────────────────┐
│   T1: PLATFORM   │          │   T2: GATEWAY    │          │    HEARTBEAT     │
│  Preauth & Auth  │          │ Blowfish Encrypt │          │ Keepalive Ping   │
│  JSON-RPC / WS   │          │ Multi-Client RT  │          │ Packet Relay     │
└─────────┬────────┘          └────────┬─────────┘          └──────────────────┘
          │ (FSM: joinLobby)           │ (TCP Wire stream)
          └────────────────────────────┼──────────────────────────────┘
                                       ▼
                          ┌──────────────────────────┐
                          │       T3: GAME SIM       │
                          │   Authoritative Server   │
                          │  ──────────────────────  │
                          │  • Locomotion & Navmesh  │
                          │  • Combat & Abilities    │
                          │  • Minion & Turret AI    │
                          │  • Jungle & Objectives   │
                          │  • Economy & Items       │
                          └──────────────────────────┘
```

### T1: Platform RPC (Pre-auth, Authentication & Catalog)
- **Transport**: HTTP/1.1 over TLS 1.2/1.3 on port 8443, WebSocket notification stream on 8080/notify.
- **Key Mechanisms**:
  - Issues deterministic player JWTs mapped to Hardware IDs (or unique Device Listener Tags to support multiple cloned emulator instances).
  - Exposes hero and skin selection through `canUseAllHeroes` and `getSkinManifest`. Catalog availability does not establish implemented hero kits: ten heroes have explicit kit factories, with incomplete mechanics documented per kit.
  - Implements lobby session state machine: `menus` $\rightarrow$ `joinLobby` $\rightarrow$ provision match IP/Port $\rightarrow$ `playing` $\rightarrow$ `exitLobby`.

### T2: Gateway & Match Transport (Routing & Cryptography)
- **Transport**: TCP stream with 2-byte Big-Endian length framing: `[u16 BE Length][Payload]`.
- **Encryption**: Blowfish ECB cipher utilizing a per-match dynamic key derived from match credentials.
- **Key Mechanisms**: Handles Route-Request handshake (`00 06 00`), coordinates heartbeat keepalives, demultiplexes multi-client connections into designated match sessions, and purges orphaned match instances on client departure.

### T3: Authoritative Simulation (Deterministic Game Engine)
- **Locomotion**: Dual-contract movement model combining client-side local pathfinding (`c2s 1012`) with server-side validation and periodic correction (`s2c 1070`), backed by FSM-driven animation state sync (`1067 MOVING 0x0F` / `IDLE 0x00`).
- **Combat & Structures**: Damage mitigation $D = \frac{W}{1 + A/100}$, turret targeting with defensive ramps, and Vain Crystal destruction logic. Native gameplay fidelity remains subject to independent comparison.
- **Wave Director**: Fixed 25-second minion wave intervals with waypoint tracking, target acquisition, and siege prioritization.
- **Economy**: Passive gold trickle, last-hit bounty distributions, hero kill rewards, and interactive in-game shop transactions (`1081`/`1082`).

---

## 3. Development Roadmap & Milestones

Progress is tracked by implemented behavior and measured acceptance, without
an overall completion percentage. The gameplay tiers below are separate from
the architecture's T1/T2/T3 layers.

### Tier 1: Solo Sandbox / Practice Mode
> *Objective: Single player enters the match and experiences a complete, fully functional game loop.*

**Acceptance remains OPEN.** Earlier bounded client observations cover movement,
basic attacks, selected ability shapes, shopping, jungle objectives, Recall,
death/respawn and reaching Victory. Some use declared QA preparation; they do
not establish a fully accepted ordinary match. See the
[seven-gate acceptance record](Docs/Plan/solo-sandbox-acceptance-status.md).

The latest recorded progress through September 12 is:

| Area | Evidence and remaining boundary |
|---|---|
| Skye basic attacks | Projectile visuals were reviewed live following the September 8 defect report; other hero profiles retain fidelity gaps. |
| Skye A/B/C | The declared-fixture driver recorded two accepted attempts per ability: A twice in one match, B and C each across two fresh matches. The compare-pair contract was not run and those presentations remain unreviewed. |
| Skye C corrections | Owned-record inspection supports activation before damage and a strict two-unit cluster-selection threshold. Focused tests and the production headless scenario pass; fresh rendered acceptance of these corrections remains pending. |
| Minions and turrets | Live approach and opposing combat are observed. Three bounded windows did not establish survivor resumption or structure damage. The headless push fixture deliberately eliminates one wave after contact; its PASS does not establish natural live pushing. |
| Scenario tooling | Six production-integrated headless scenarios passed exact event/state comparison across two seeded processes on a recorded source pin. This is internal repeatability, not independently measured official gameplay fidelity. |

### Tier 2: PvE / Bot Match
> *Objective: Playable against autonomous, competent AI bots.*

- Implemented foundations: bot draft selection, slot filling, lane navigation, target selection and basic attacks.
- Open: competent tactical play, ability combinations, dodging, retreats and coordinated jungle behavior. A complete bot match is not accepted.

### Tier 3: PvP Online / Multiplayer
> *Objective: Smooth local LAN or online matches with friends.*

- Implemented and exercised by automated tests: shared match routing, draft synchronization and reconnect/session handling.
- Open acceptance milestone: a reproducible combat session with **two actual game clients**, with consistent attacks and health changes on both screens.
- Open: complete fog of war/brush concealment, kit and reconnect fidelity, and sustained service reliability. A roughly 30-minute idle client crash remains under investigation.

---

## 4. Local Setup and Verification

### Prerequisites

- **Recorded live workflow**: Windows, LDPlayer 9 with root access, ADB, and the owned Android CE 4.13.4 client (build 147219). The `live_up` helper uses Windows process tools; this is not a verified Linux or PC-client quick start.
- **Python**: 3.11+ and PyCryptodome for the wire/certificate tooling; Pillow for the rendered-client driver and its tests. The optional native-contract inspector also needs Capstone.
- **External owned data**: the A001 navigation record, jungle/Skye spawn corpora and a production-valid `world_tape.bin`. Captured payloads and client assets are intentionally absent from Git. A fresh clone alone cannot reproduce the complete test/live environment.
- **Local platform setup**: certificate/key, answers configuration, emulator routing and CA trust. The [mobile setup record](Docs/Teardown/vainglory-mobile-local-stack.md) describes the routing and trust procedure; its September 5 menu-only result is historical.

Run commands from the repository root. Select your own external paths in
PowerShell before running the tests or starting the server:

```powershell
$env:HALCYON_NAVMESH = '<absolute path to owned A001 navigation record>'
$env:HALCYON_SPAWN_CORPUS = '<absolute directory containing owned spawn records, including Kraken>'
$env:HALCYON_SKYE_VOLLEY_CORPUS = '<absolute directory containing owned Skye volley chunks 32 and 36>'
```

The live stack reads configuration, certificates and the world tape from
`$env:TEMP/halcyon_stack`. Keep them outside the checkout. The
[scenario record](Docs/Plan/solo-sandbox-scenarios.md) documents the required
corpora and [world-tape builder](Tools/build_world_tape.py); missing corpus
data is a setup failure, not evidence that a gameplay rule regressed.

### 1. Run the Test Suite

Ensure all regression checks and integration tests pass:
```powershell
python -B -W error::ResourceWarning -m unittest discover -s server/test -t .
```
Historical test counts apply only to their recorded source and environment;
see the [current status](Docs/Plan/current-status.md). Require a clean exit on
the source being reviewed. Run the bounded repeatability scenarios separately:

```powershell
python Tools/run_scenarios.py --mode headless --scenario all
```

Outputs go outside Git. Without an independent reference fixture the reference
verdict is `UNAVAILABLE`, even when local repeatability passes.

### 2. Launch the Host Server

With the external setup complete and the emulator available, start the local
platform, gateway and relay, and apply guest routing. This helper stops prior
local stack processes and restarts the stack:
```powershell
python -m server.platform.live_up
```

To advertise a LAN address, with each device's routing and certificate trust
configured separately:
```powershell
python -m server.platform.live_up --match-host <YOUR_LAN_IP>
```

### 3. Connect via Client

1. Launch Vainglory on an emulator or physical device configured with DNS/hosts pointing to the server.
2. Follow the recorded solo route: **PLAY → SOLO BOTS → 3V3 → VERY EASY**.
3. Select a hero with an implemented kit, such as Skye, lock in, and choose **Manual Build**. Selectability alone does not imply kit support.

---

## 5. Repository Layout

```
project-halcyon/
├── Docs/                      # Research documentation, teardown notes, and specifications
│   ├── Teardown/              # RE knowledge base (wire protocol, navmesh, codecs, map layout)
│   ├── Plan/                  # Milestone roadmaps and acceptance deliverables
│   └── Research/              # Deterministic simulation research and architecture designs
├── server/                    # Authoritative server implementation
│   ├── platform/              # T1: TLS HTTPS RPC, guest JWT auth, answers JSON, lobby FSM
│   ├── gateway.py             # T2: TCP gateway routing, dynamic match key derivation, relay
│   ├── match_server.py        # T2/T3: Match lifecycle coordinator, draft & world session
│   ├── hero_movement.py       # T3: Locomotion engine, navmesh routing, animation state machine
│   ├── abilities.py           # T3: Ability framework, skill point leveling, cooldowns
│   ├── wave.py                # T3: Minion wave spawning, waypoint pathing, lane director
│   ├── structures.py          # T3: Defensive turrets, target acquisition, Vain Crystal
│   ├── economy.py             # T3: Item shop, passive gold trickle, kill/bounty rewards
│   ├── jungle.py              # T3: Neutral creep camps, leash boundaries, buff states
│   ├── bot_ai.py              # T3: Headless bot decision making and combat behavior
│   └── test/                  # Automated unit, regression, and end-to-end test suite
├── Tools/                     # RE inspectors, scenario drivers and reproduction tools
├── GOAL.md                    # Detailed milestone tracking per vertical slice
├── README.md                  # English primary documentation
├── README.vi.md               # Vietnamese documentation
└── AGENTS.md                  # Operational directives and engineering constraints for AI agents
```

---

## 6. Binding Guardrails

1. **Clean-Room Reimplementation**: Strictly zero proprietary game assets in the repository. No textures, 3D models, audio, `.vgr` replay tapes, raw `.pcap` network captures, or decrypted store payloads may be committed.
2. **Private & Non-Commercial**: This software is intended exclusively for private, self-hosted educational and recreational use among friends.
3. **Passive & Read-Only**: We do not probe, scan, inject, or intercept traffic against any public or third-party servers.
4. **Determinism as the North Star**: The simulation engine must remain strictly deterministic. Wall-clock randomness, unseeded generators, and asynchronous timing variations are prohibited within the simulation tick.

# Project Halcyon

> **Authoritative, Deterministic, Self-Hosted Game Server for Vainglory (4.13.4, build 147219)**  
> Built from pure reverse-engineering research and clean-room protocol reimplementation.

🌐 **Languages**: [English](README.md) | [Tiếng Việt](README.vi.md)

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
  - Unlocks the entire roster of **50+ heroes** (`canUseAllHeroes: true`) and all **290 skins** (`getSkinManifest`).
  - Implements lobby session state machine: `menus` $\rightarrow$ `joinLobby` $\rightarrow$ provision match IP/Port $\rightarrow$ `playing` $\rightarrow$ `exitLobby`.

### T2: Gateway & Match Transport (Routing & Cryptography)
- **Transport**: TCP stream with 2-byte Big-Endian length framing: `[u16 BE Length][Payload]`.
- **Encryption**: Blowfish ECB cipher utilizing a per-match dynamic key derived from match credentials.
- **Key Mechanisms**: Handles Route-Request handshake (`00 06 00`), coordinates heartbeat keepalives, demultiplexes multi-client connections into designated match sessions, and purges orphaned match instances on client departure.

### T3: Authoritative Simulation (Deterministic Game Engine)
- **Locomotion**: Dual-contract movement model combining client-side local pathfinding (`c2s 1012`) with server-side validation and periodic correction (`s2c 1070`), backed by FSM-driven animation state sync (`1067 MOVING 0x0F` / `IDLE 0x00`).
- **Combat & Structures**: Faithful damage resolution $D = \frac{W}{1 + A/100}$, turret multi-target aggro rules with defensive ramps, and Vain Crystal core destruction logic.
- **Wave Director**: Fixed 25-second minion wave intervals with waypoint tracking, target acquisition, and siege prioritization.
- **Economy**: Passive gold trickle, last-hit bounty distributions, hero kill rewards, and interactive in-game shop transactions (`1081`/`1082`).

---

## 3. Development Roadmap & Milestones

Progress is evaluated across a 3-tier vertical slice model:

### Tier 1: Solo Sandbox / Practice Mode
> *Objective: Single player enters the match and experiences a complete, fully functional game loop.*

**Acceptance reopened:** the operator's Skye test exposes unavailable skill
upgrades, missing visible projectiles and defective minion movement. The
758-test baseline and replay results do not establish completed gameplay.
Current defects and historical evidence are in the
[acceptance record](Docs/Plan/solo-sandbox.md).

- [x] Navmesh routing, wall collision, dynamic speed and crowd-control stops.
- [ ] Attack windup/release/recovery, ranged projectiles and stutter-stepping — visible projectile defect reopened.
- [ ] Four ability shapes, energy/HUD updates and channel interruption — selectable Skye has no ability kit.
- [x] Shop restrictions, required active items and combat passives.
- [ ] Melee/ranged/siege waves, protective turret targeting, damage ramp and Victory — normal minion movement requires repair.
- [x] Jungle buffs, Gold Miner team payout and captured Kraken siege.
- [x] Four-second Recall, base healing and dynamic death/respawn lifecycle.

### Tier 2: PvE / Bot Match (~40%)
> *Objective: Playable against autonomous, competent AI bots.*

- [x] Bot draft roster selection and slot filling.
- [x] Autonomous lane pathfinding, enemy targeting, and auto-attacking.
- [ ] Tactical AI behaviors: ability combos (A/B/Ult), skillshot dodging, low-health retreats, and jungle ganking.

### Tier 3: PvP Online / Multiplayer (~70%)
> *Objective: Smooth local LAN or online matches with friends.*

- [x] Multi-client routing into a unified game instance.
- [x] Synchronized real-time draft picks and skin selections across participants.
- [x] Resilient session handling and mid-game reconnection support.
- [ ] **Fog of War & Brush Concealment**: Coordinate culling when players enter stealth or unrevealed brush.

---

## 4. Quick Start

### Prerequisites
- **Operating System**: Windows 10/11 or Linux.
- **Python**: 3.11+ (standard library only; clean pure-Python implementation).
- **Client**: Vainglory CE 4.13.4 (Build 147219) on PC or Android Emulator (LDPlayer 9).

### 1. Run the Test Suite
Ensure all regression checks and integration tests pass:
```powershell
python -B -W error::ResourceWarning -m unittest discover -s server/test -t .
```
*(All 220+ unit and integration tests must exit cleanly with code 0).*

### 2. Launch the Host Server
Execute a single command to terminate orphaned listeners, bind the HTTPS platform RPC, boot the Gateway and Heartbeat Relay, and configure host redirects:
```powershell
python -m server.platform.live_up
```

To expose the match gateway across your local LAN for physical mobile devices:
```powershell
python -m server.platform.live_up --match-host <YOUR_LAN_IP>
```

### 3. Connect via Client
1. Launch Vainglory on an emulator or physical device configured with DNS/hosts pointing to the server.
2. In the main menu, navigate to: **PLAY $\rightarrow$ SOLO BOTS $\rightarrow$ 3V3 $\rightarrow$ EASY** (or create a Custom Lobby).
3. Lock in your hero, select a skin, and step onto the Halcyon Fold!

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
├── Tools/                     # Read-only RE inspection and measurement scripts
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

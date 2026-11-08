# Project Halcyon

**Local storage (2026-10-11):** checkout at `D:\project-halcyon`; private inputs,
runtime files and QA output stay inside ignored `Local/` (new runs:
`Local/evidence/`). See the [relocation guide](Docs/Setup/windows-local-development.md).

> **Authoritative, Deterministic, Self-Hosted Game Server for Vainglory (4.13.4, build 147219)**  
> Built from pure reverse-engineering research and clean-room protocol reimplementation.

🌐 **Languages**: [English](README.md) | [Tiếng Việt](README.vi.md)

**Status reviewed October 23, 2026 (archived November 8, 2026):** an experimental
authoritative server with verified 6-participant wire sessions, natural match
completion to Vain Crystal destruction, byte-exact deterministic input-journal
replay, 1 real CE client + 5 protocol participants (`M5 step C`), and unmodified
physical Android transport over WireGuard + public TLS. Overall full-game PvP
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
   HTTPS/TLS (8443)             TCP Gateway (7100+)            TCP Heartbeat (2112)
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

- **Implemented & Verified Milestones (through October 23, 2026)**:
  - **Milestone 2 (`M2`)**: Six wire-only participants (Skye/Catherine/Adagio vs Ringo/Gwen/Amael) pass draft/readiness and execute learn, native cast, move, attack, shop purchase, Recall, and same-identity reconnect.
  - **Milestone 3 (`M3`)**: Natural 6-participant match to Vain Crystal destruction (`1106 → 1072 → 1009`), replayed byte-identically across independent seeds (6,813 records, 328 checkpoints, 145,052 events).
  - **Milestone 4 (`M4`)**: Application-order `server/input_journal.py` and exact two-process production replay (`Tools/run_scenarios.py --mode replay --journal <path>`).
  - **Milestone 5 Step C (`4ac`)**: One real Android CE client plus five protocol participants pass all 8 live conditions (reciprocal combat before and after reconnect).
  - **Milestone 7 Preparation (`M7 prep`)**: Dead wave minions and removed-EID histories bounded; separate-process host (`Tools/protocol_host.py`); 30-minute 6-participant soak replayed byte-identically (38,391 operations, 1,027,103 events).
  - **Unmodified Physical Android VPN Ingress**: Unrooted Redmi Note 11 running original CE 4.13.4 over official WireGuard + owned-domain Let's Encrypt TLS (`server/platform/phone_vpn.py`); 538-second live session recorded and replayed byte-identically across seeds.
- **Open Priorities When Resuming Development**:
  1. **Physical Android cold-process reconnect readiness**: Cold relaunch reattaches to the match within 7.8s and receives catchup, but disconnects before emitting client opcodes/readiness (diagnose load/ready handshake before catchup dump).
  2. **Two real rendered CE clients (`M5` full gate)**: Dual-client live combat session with consistent attacks and health changes on both screens.
  3. **M7 soak residuals & kit completeness**: Attribute remaining +0.069 ms/min checkpoint growth and +0.17 MiB/min RSS growth; expand remaining hero kits and fog of war/brush concealment.

---

## 4. Cold-Start Restore & Local Setup (Resuming After Archival)

The working project consists of two parts:
1. **Git repository (GitHub)**: All server code (`server/`), RE/verification tools (`Tools/`), documentation (`Docs/`), and SHA-256 input manifests (`Config/local-inputs.json`).
2. **Single Distilled Google Drive Archive (`halcyon-local-backup.zip`, ~1.56 GB)**: Private, Git-ignored assets and state distilled from ~41 GB down to **one single `.zip` file** containing:
   - Unmodified Android APK (`vg-4.13.4-147219-base.apk`) & OBB (`main.147219...obb`), plus `vainglory/lib/arm64-v8a/libGameKindred.so` (for the native ARM64 health oracle).
   - All 944 required PC 4.13 `Data/` store files (navmeshes + all 942 `INST`/`CFF0` manifests — 16.4 MB instead of 3.45 GB of unused PC textures/audio).
   - Complete `runtime/` state (`world_tape.bin`, `answers.json`, local TLS CA, WireGuard `phone-vpn/` keys, and Let's Encrypt `phone-acme/` certificates for `rpc.halcyon.tongducthanhnam.id.vn`).
   - Complete `research/runtime-corpus/` (`.32`, `.36`, `.72` `.vgr` anchors) and distilled `research/vg_max/` corpus (`.pcap`, `.vgr`, `.pkl`, `.tsv`, `inst_dump/`).
   - Irreplaceable live-session input journals (`journal.jsonl`, `inputs-*.jsonl`) and milestone reports under `evidence/` (`M3`, `M4`, `M5 4ac`, `M7 soak`, `phone-vpn`) for deterministic replay.

### Step-by-Step Restoration on a Fresh / Wiped Machine

1. **Clone the repository into `D:\project-halcyon`** (using `D:\project-halcyon` preserves exact path pins in historical replay journals):
   ```powershell
   git clone https://github.com/TongDucThanhNam/project-halcyon.git D:\project-halcyon
   Set-Location D:\project-halcyon
   ```

2. **Download `halcyon-local-backup.zip` from Google Drive** and extract it directly into `D:\project-halcyon\Local`:
   ```powershell
   New-Item -ItemType Directory -Path .\Local -Force | Out-Null
   Expand-Archive -LiteralPath "C:\path\to\halcyon-local-backup.zip" -DestinationPath .\Local -Force
   ```

3. **Create the Python virtual environment and install dependencies** (Python 3.11+, tested on 3.14 x64):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   # Optional packages for RE inspectors, native ARM64 oracle, and phone WireGuard ingress:
   .\.venv\Scripts\python.exe -m pip install -r requirements-research.txt -r requirements-native.txt -r requirements-phone-vpn.txt
   ```

4. **Verify all local inputs, certificates, and simulation loaders**:
   ```powershell
   .\.venv\Scripts\python.exe -B Tools/setup_local.py --check --profile headless
   .\.venv\Scripts\python.exe -B Tools/setup_local.py --check --profile client
   ```
   Both commands must print `RESULT: PASS (0 prerequisite failures)`.

5. **Run the verification suites (no emulator required)**:
   ```powershell
   # Fast smoke test lane (~11s):
   .\.venv\Scripts\python.exe -B Tools/run_checks.py --suite smoke
   # Full 7-scenario two-process deterministic headless check:
   .\.venv\Scripts\python.exe -B Tools/run_scenarios.py --mode headless --scenario all
   # Replay the recorded physical Android live session deterministically:
   .\.venv\Scripts\python.exe -B Tools/run_scenarios.py --mode replay --journal .\Local\evidence\phone-vpn-journal-1792731479464021600\replay\journal.jsonl
   ```

6. **Run with a live game client (LDPlayer 9 or Unmodified Physical Android)**:
   - See the **[complete Windows & client setup guide](Docs/Setup/windows-local-development.md)** for LDPlayer 9 ADB/root setup (§5–§9) and unmodified physical Android WireGuard + public TLS setup (§6.1).
   - Quick start for LDPlayer (`emulator-5554`):
     ```powershell
     .\.venv\Scripts\python.exe -B -m server.platform.live_up --serial emulator-5554 --bind-host 127.0.0.1 --match-host 127.0.0.1
     ```

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

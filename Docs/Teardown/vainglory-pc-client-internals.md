# Vainglory PC client internals — menu replies and the endSession error counter

Updated 2026-09-07: corrected movement/visibility action identities in section 7;
the controlled platform-reply repair below was verified on 2026-09-05.
This leaf concerns the **PC 4.13 client, revision 102405, PE32**, not the
Android build. Addresses below are static VAs unless explicitly marked RVA.
Runtime address = image base from PEB32 + (static VA − 0x400000).

**Correction to the earlier version of this leaf:** the watchdog bypass kept
the process alive while hiding a malformed `friendListAll` reply. It was not
the required boot fix. The supposed `getSkinManifest` parser was also the
wrong RPC operation. Correcting four server replies removes both the manifest
retry storm and the recurring watchdog error, with the watchdog **original**.
Loader state 5 / pending 0 still occur in that run; they do not establish that
the visible client is stuck at a loading screen.

Only the operator's local client copies and hosts-redirected local stack were
used. Payloads, binaries, screenshots and raw journals remain outside the repo.

## 1. friendListAll caused the watchdog errors

**[Observed, static + runtime]** The PC friend-list consumer at `0x4bbc80`
parses the complete RPC response text and accesses `returnValue`. At
`0x4bbf9b` and `0x4bbfaf` it requires keys `pending` and `confirmed`.
Missing either takes this path:

```text
0x4bc285: push -6
0x4bc287: call 0x9b8620
0x9b8626: mov [0x1ab9f18], eax   ; EAX = -6
```

A breakpoint at the setter captured `EAX=0xfffffffa`, with return address
`0x4bc28c`. A separate breakpoint at `0x4f13aa` captured the same global
status immediately before the loader counter increment. This is a parser
error from the friend-list consumer, not an inference from RPC timing.

The local empty-list reply is:

```json
{"code":0,"returnValue":{"pending":[],"confirmed":[],"numOffline":0}}
```

The earlier `{"code":0,"returnValue":{"friends":[]}}` lacks both required
keys. A brief array-only diagnostic was also replaced with the object above.

**[Observed]** The waiting handler is **`0x4f1320`**, not `0x4e1320`:

- It reads global RPC status through `0x99c3d0` and returns immediately when
  status is `1` (`0x4f1328` → `0x4f1457`). The value `1` is also written by
  the status reset helper `0x994350`; calling it simply “RPC success” was too
  imprecise for interpreting this state machine.
- Other status values enter a switch. Its default path at `0x4f13aa`
  increments `[loader+0x154]` when `[loader+0x14a]` is armed. If the counter
  exceeds 5, `0x4f13c9` calls the `endSession` wrapper `0x9bb250`.
- The handler resets the shared status to `1` before returning from that path.
  Therefore **this is not an unconditional five-render-frame timeout**.
  Repeated error results explain counter growth; corrected replies leave it zero.
- The queue/transition branch in tick `0x4f2bb0` is real, but `pending=0`
  does not by itself indicate an unfinished boot. The corrected run retains
  state 5, pending 0, armed true, counter 0 and frontend state 1 (`menus`).

The previously observed endSession caller was real; attributing it to an
absent pending transition was the incorrect causal step.

## 2. Manifest RPCs contain JSON inside a JSON string

**[Observed, static + live hot-reload]** These PC callbacks accept a string
`returnValue`, then parse its contents as another JSON document:

| RPC | Request type ID | RPC parser entry | Frontend request offset |
|---|---:|---:|---:|
| `getSkinManifest` | `0x1e` | `0x99dd1c` | `+0x1b5c` |
| `getBuffManifest` | `0x29` | `0x99e463` | `+0x1b04` |
| `getSeasonRewardsManifest` | `0x32` | `0x9abd90` | `+0x2124` |

For skin, the frontend constructor installs vtable `0x12186ac`, whose type-ID
method `0x5091f0` returns `0x1e`. The router at `0x99d720` dispatches by that
ID (jump table `0x99ebb4`, index = ID − 1). Case `0x1e` requires the string
type flag and copies it to request `+0x18`. The frontend consumer at
`0x50ba63` passes that string to skin-catalogue parser `0x7e8550`.

**The earlier `0x9a92f0` parser is case `0x3a`, a different operation.** Its
`skins` object / `blueprintsOwned` / `owned` fields are not evidence for the
`getSkinManifest` catalogue shape. Observing that parser execute during the
same boot burst did not establish which request it belonged to.

Changing only the three `returnValue` types in a live client stopped buff
and season retries immediately. Skin continued because its contents also
used the wrong schema:

- The skin catalogue consumes `themes` and `skins` **arrays**.
- At `0x7e9346` and `0x7e9350` it requires populated theme and skin counts
  before setting the cache flag at catalogue `+0x30` (`0x7e9365`).
- The sender's polling condition at `0x50a674` checks this cache flag and
  its timestamp. Empty or wrongly typed catalogue collections do not satisfy it.
- One synthetic theme and linked skin, with the skin hidden and unobtainable,
  stopped the remaining retry loop. This is a **diagnostic catalogue**, not
  recovered skin data or a faithful implementation of the store.

The exact diagnostic skin metadata is generated in
`Tools/client/repair_pc_menu_answers.py`. Wire example for the tested season
fixture (optional version fields are retained from the existing local config):

```json
{"code":0,"returnValue":"{\"season\":1,\"rewards\":[],\"version\":\"1\"}","version":"1"}
```

This finding does not mean every RPC uses a string. `getPlayerInfo` and
`friendListAll` still use object values. Adding a `version` field to an
object reply had not addressed the outer type mismatch.

## 3. Controlled validation and reproduction

External evidence directory: `$env:TEMP/halcyon_stack/`.

- `manifest_experiment.json` records the first client's PID, wall-clock
  boundaries and byte offsets into the RPC journal. `answers.before-manifest-string.json`
  preserves its original configuration. No debugger was used for the reply
  type/cache experiment.
- Before the changes: at 22.3 seconds, skin/buff/season had already sent
  **131 / 133 / 134** requests respectively.
- With string replies: over the next measured 20.6-second window, buff and
  season sent **one** request each; skin sent **155**.
- With the nonempty diagnostic skin catalogue: over the next measured
  24.4-second window, skin sent **one** request and the other two sent none.
- After the friend-list correction, the existing client's error counter
  stopped growing. A fresh **date-only** client copy was then launched with
  the original watchdog instruction, no debugger, silent WebSocket, and
  the same empty `update` reply as before.
- At 138 seconds in that fresh run: **zero endSession**, counter **0**,
  skin **1**, season **1**, buff **2** total requests (no continuing burst),
  plus 15 update polls and 7 friend-list polls. All three manifest requests
  were idle with flags `3`. `no_watchdog_experiment.json` records the run
  boundary; the raw journal remains external.
- Final check at **1080.2 seconds (18 minutes)**: still **zero endSession**,
  counter **0**, original watchdog, frontend state 1. Manifest totals remained
  skin **1**, season **1**, buff **2**; no manifest request occurred after the
  initial 30 seconds. There were 109 update polls and 54 friend-list polls.
  `verified_menu_summary.json` preserves counts and the bounded runtime
  snapshot. The test client was stopped after verification; corrected replies
  and the existing local stack remain available.

Reproduce the configuration correction, preserving unrelated session fields:

```powershell
python Tools/client/repair_pc_menu_answers.py "$env:TEMP/halcyon_stack/answers.json" --diagnostic-skins
python Tools/client/repair_pc_menu_answers.py "$env:TEMP/halcyon_stack/answers.json" --diagnostic-skins --apply
python Tools/client/repack_ftol_edx.py
python Tools/client/inspect_pc_runtime.py <local-client-pid>
python -m unittest discover -s Tools/client -p 'test_*.py' -v
```

The answer repair defaults to a dry run, prints RPC names rather than token
values, backs up exact original bytes before applying, and uses an atomic
replacement so the server does not read partial JSON. Without
`--diagnostic-skins`, it preserves supplied catalogue metadata and refuses an
empty/wrongly typed skin catalogue. The live corrected answers are left in
place; the repair command reports no changes when run against them.

The runtime inspector opens the supplied process for **read/query only**,
reads the WoW64 PEB to relocate every address, and checks known instruction
sites before reading the bounded status fields. It does not attach a debugger
or change the process. Snapshot fields are observations, not UI assertions.

## 4. Client copies and the remaining date workaround

Original client SHA256:
`659f9eed557a426db57554d2a768efe34ba9fe02ba1085d77db64390b0d92642`.

The current reproducible copy is **`VaingloryLocal.exe`**, beside the original
in `D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/`. SHA256:
`e625620fe3b3a9ffa56e62509b632b9f6c79e11d205533227b5ef05d7dd8db4d`.
Only **14 bytes differ** from the original, within two date-formatter calls
and their padding cave. The watchdog is original.

`Tools/client/repack_ftol_edx.py` now checks the complete source hash and the
expected code-site bytes, refuses to overwrite a different existing file,
and refuses binary output inside the repository. A repeated invocation verifies
an identical copy. Its default filename avoids the observed installer-detection
problem with names containing “patch”. Existing experimental copies are retained.

The retained date workaround concerns the previously captured menu analytics
failure: invalid `time_t` high bits reached `_localtime64_s`, then `strftime`
received a null `tm` and the CRT failed fast. `getPlayerInfo.targeting.cohort`
must also carry a valid epoch (the local fixture uses `1704067200`). The helper
patch zeroes EDX after conversion; it is a bounded workaround for the tested
nonnegative epochs, not a general replacement for the CRT conversion routine.

Date patch **RVAs**: calls `0x56e68d` and `0x56e701`; cave `0x56e746`; original
helper target `0xdb8c3f`. These are RVAs, so add the runtime image base directly.

The historical watchdog bypass changed static VA `0x4f13c3`, file offset
`0xf07c3`, from `0f 8e 88 00 00 00` to `e9 89 00 00 00 90` in
`VaingloryHalcyon.exe`. **It is superseded, and is not applied to the verified
date-only copy.** Keeping a process alive with that bypass did not prove the
platform replies were correct.

## 5. Update/notify mapping and limits

The preserved mapping is useful independently of the fixed friend-list issue:

- HTTP `update` sender: `0x99f1e0`, with request construction at `0x99f32e`.
  The local run polls about every 10 seconds; `{"code":0,"returnValue":{}}`
  remains configured. No transition push was needed for the validation above.
- Ingest `0x509390` clears category flags and walks **two** maps: integer
  sequence values from the input object's `+8` map, and string values parsed
  as 64-bit integers from its `+0` map. Describing it as one integer map was
  incomplete.
- Categorizer `0x509630`: `party`→5, `partyInvitation`→6, `friends`→7,
  `matchResponse`→8, `transition`→4; other keys→0.
- The registered callback `0x4bf590` calls consumer `0x50a2e0`. After ingest,
  the transition flag invokes `0x9bcf30`, which requests an earlier update
  poll through session flag `+0x2628`. This is not proof that a transition
  notification must populate the loader's pending state.
- Registration stores the callback at global `0x1ef336c`. Tick consumers
  `0x4f30ce` and `0x4f3155` invoke it for event records marked `0x80000`.
  Exact notify framing and the producer of those maps remain unverified.
- `_ws_push` and `_ws_push_payload` in the existing stack are sampled at
  **connection time**, despite the old “hot-reloadable payload” comment.
  The verified run has `_ws_push=false` throughout.

Operational pitfalls from the earlier investigation:

- For this PE `.text`, file offset = **RVA − 0xc00**, or static VA −
  `0x400c00`. For `.rdata`, use its section table (`RVA − 0xe00` in the
  examined region). Do not subtract an RVA delta directly from a static VA.
- Android decompile addresses/layouts are not PC addresses/layouts. Use the
  appropriate ELF/PE mappings and actual PC instruction boundaries.
- Relocate globals as well as breakpoints. Earlier probes read unrelocated
  globals and at times mistook stack data for return addresses. Scan candidates
  are not a proven call stack; the status-setter experiment above identifies
  the actual immediate return address.
- The old TEMP `failcatch32.py` has accumulated experimental instrumentation.
  Prefer the bounded read-only inspector for routine status checks. The focused
  `pc_onebp.py` / `pc_statusbp.py` experiments remain external for audit.

**Still open:** visual confirmation of the rendered menu (the computer-use
capture helper was unavailable during this pass), a faithful catalogue and
the rest of T1/matchmaking, and the actual T1→T2 handoff. Process survival,
idle manifest requests and frontend state 1 are not a verified playable match.

## 6. PC Client as High-Speed Dissection Lab for Server Emulation (Observed, 2026-09-07)

### 6.1 Role in the Dual-Wield Engineering Strategy
The PC client (`Vainglory.exe` / `VaingloryLocal.exe`, PE32 x86) serves as a **high-speed dissection laboratory** rather than the primary production target (which remains Android/LDPlayer for friend-group play):
- **10–20x Iteration Speed**: Zero ADB latency, no guest-OS virtualization, no ARM64 translation layers (Houdini/NDK). Process launches, restarts, and crash recoveries execute instantly on native Windows.
- **`__thiscall` Convention Root Anchors**: Under MSVC x86 32-bit calling conventions, the `ECX` register deterministically holds the `this` pointer for member function invocations. Hooking event/RPC dispatchers immediately exposes object roots (`Actor*`, `BuffManager*`, `HeroObject*`).
- **Memory Address Space**: Flat 32-bit addresses (`0x00400000 - 0x7FFFFFFF`) with 4-byte pointer strides drastically simplify pointer-chain walks compared to 64-bit sparse address spaces.
- **Direct Windows Tooling**: Support for x32dbg hardware breakpoints, Cheat Engine memory freeze/search, and zero-latency C++ DLL injection (MinHook / Detours) directly into the process.
- **TLS/Certificate Pinning Bypass**: Bypasses Android's `UNKNOWN_CA` self-signed cert blocker directly via the Windows Certificate Store (Local Machine Trusted Root) or standard Win32 API hooks.

### 6.2 Asymmetry Matrix: PC vs Android Client
| Property | Windows Client (`VaingloryLocal.exe`) | Mobile Client (`libGameKindred.so` on LDPlayer) | Engineering Handling |
|---|---|---|---|
| **Architecture** | PE32 (x86 32-bit WoW64) | ELF64 (ARM64-v8a) | Address offsets and struct padding are architecture-specific; never assume PC RVA = Android RVA. |
| **Build Revision** | Revision 102405 | Revision 147219 (v4.13.4) | Build divergence means sub-opcode extensions or enum layouts must be validated against mobile before final release. |
| **Input / Presentation** | Mouse click / drag | Multi-touch taps & gestures | Touch gesture prediction differs from mouse orientation updates; verify orientation on mobile. |
| **Runtime Date Stability**| Requires 14-byte `_localtime64_s` CRT patch (`repack_ftol_edx.py`) | Stable (no CRT date crash) | Keep `VaingloryLocal.exe` as the reproducible testing binary. |

## 7. In-Memory C++ Engine Architecture & Actor Layout (partial, 2026-09-07)

Reverse-engineered directly from `VaingloryLocal.exe` (PE32 x86 WoW64, base `0x00400000`) using MSVC RTTI extraction, binary disassembly (Capstone), and live memory verification.

Evidence is scoped to individual observations, not a complete validated layout.
Some original field names were interpretations; disputed flag meanings remain
unverified. Section 7.6 records the bounded static action audit that supersedes
the earlier movement/animation labels.

### 7.1 EVIL Engine RTTI Architecture & Class Hierarchy
The binary retains 2,425 complete MSVC RTTI Complete Object Locator records:
- **Actor Class**: `Nuo::Kindred::CKinActor` (vtable `0x127B448`). Single concrete actor class instantiated for all units (heroes, minions, turrets, monsters).
- **Secondary Interface**: `Nuo::Game::Referenceable<CKinActor>` (vtable `0x127B458` at `Actor + 0x14`).
- **Component Linked List**: Head stored at `[Actor + 0x0C]`. Node layout: `+0x04 = Component*`, `+0x10 = NextNode*`.
- **Component Subsystems**:
  - `CKinActorAttributes` (vtable `0x127B478`, pointed to by `Actor + 0x20`).
  - `CKinActorNav` (vtable `0x1282970`, size `0x7DC` = 2,012 bytes, pointed to by `Actor + 0x24` and retrieved by `Actor->GetComponent<CKinActorNav>()` at `0x813000`).
  - `CKinActorRep` (vtable `0x121C520`, size `0x58` bytes, pointed to by `Actor + 0x28`, holds 3D mesh and `ComponentAnimation`).
  - `CKinActorGameplayFlags` (vtable `0x127B418`, size `0x20` bytes).

### 7.2 Recovered Struct Layouts & Offsets

#### `CKinActor` (Base Actor Instance, VTable `0x127B448`)
| Offset | Type | Field Name | Disassembly Anchor / Proof | Description |
|---|---|---|---|---|
| `+0x00` | `void*` | `vtable_primary` | `0x81DE9C: mov [edi], 0x127B448` | Primary `CKinActor` virtual table |
| `+0x0C` | `void*` | `component_list_head` | `0x813000: mov eax, [ecx + 0x0C]` | Head of attached component linked list |
| `+0x14` | `void*` | `vtable_referenceable` | `0x81DEA2: mov [esi], 0x127B458` | `Referenceable<CKinActor>` interface |
| `+0x20` | `CKinActorAttributes*` | `attributes` | `0x94AF77: mov eax, [edi + 0x20]` | Pointer to combat stats & health |
| `+0x24` | `CKinActorNav*` | `navigation` | `0x95DE5E: mov eax, [esi + 0x24]` | Pointer to navigation & pathfinder |
| `+0x28` | `CKinActorRep*` | `representation` | `0x534386: mov [esi + 0x28], 1` | Pointer to visual model & animation |
| `+0x48` | `uint32_t` | `component_slot_mask` | `0x81DEEE: or eax, 0x3FF` | Bitmask of active component slots |
| `+0x50` | `uint8_t[0x180]`| `component_slots` | `0x94B96F: cmp [eax + esi + 0x50], 3` | Array of 32-byte component slots |
| `+0x130`| `CKinActor*` | `self_ptr` | `0x81DEE4: mov [edi + 0x130], edi` | Backpointer to self |
| `+0x168`| `float` | `position.x` | `0x95DD85: movss xmm1, [esi + 0x168]` | World position X (matches wire 1070.x) |
| `+0x16C`| `float` | `position.y` | `0x95DD95: addss xmm0, [esi + 0x16C]` | World position Y / elevation |
| `+0x170`| `float` | `position.z` | `0x95DD8D: movss xmm2, [esi + 0x170]` | World position Z (ground plane, matches wire -1070.y) |
| `+0x178`| `uint32_t` | `entity_id` | `0x8579B7: cmp [eax + 0x178], esi` | Entity ID (`u32 eid`, e.g. 1500, 1515, etc.) |
| `+0x17C`| `uint8_t` | `team_tag` | `0x81DF3E: mov [edi + 0x17C], 0xFF` | Team identifier (0x01 Team 1, 0x02 Team 2) |
| `+0x1D8`| `float` | `elevation_offset` | `0x93D1FD: movss xmm0, [esi + 0x1D8]` | Vertical model offset added to position.y |
| `+0x1E0`| `uint32_t` | `entity_flags` | `0x94EA2C: test byte ptr [edi + 0x1E0], 1` | Bit tests exist; Player/Moving/Targetable/Bot and predictor/alive labels are unverified |
| `+0x1E4`| byte access observed; total width unverified | `state_flags` | `0x95DF28: test byte ptr [ecx + 0x1E4], 0x81` | Movement code tests these bits; active/stationary names are not established |
| `+0x1F0`| `uint8_t` | `compact_entity_id` | `0x84C082: mov bl, byte ptr [esi + 0x1F0]` | ID copied into ActionMoveTo; distinct from the full EID at +0x178 |
| `+0x1F8`| `uint8_t` | `status_byte` | `0x94AF6E: test byte ptr [edi + 0x1F8], 0x10` | Bit 4 (`0x10`) = invulnerable |

#### `CKinActorAttributes` (Combat & Health, VTable `0x127B478`)
| Offset | Type | Field Name | Disassembly Anchor / Proof | Description |
|---|---|---|---|---|
| `+0x00` | `void*` | `vtable` | `0x95775E: mov [edi], 0x127B478` | Attributes virtual table |
| `+0x20` | `float` | `base_max_health` | `0x53CFA4: addss xmm3, [eax + 0x20]` | Base maximum health |
| `+0xD4` | `float` | `max_health_mod` | `0x53CF9C: mulss xmm3, [eax + 0xD4]` | Multiplier on max health |
| `+0x168`| `float[45]` | `attribute_base` | `0x81C660: mov [eax - 0x168], 0` | Array of 45 base stats |
| `+0x2F0`| `float` | **`current_health`** | `0x94AF82: movss xmm1, [eax + 0x2F0]` | **Current Health (HP)** — verified by `ActionImpactHealth` and sprintf `"%d/%d"` at `0x5F1FF6` |
| `+0x2F4`| `float` | **`current_shield`** | `0x94EA03: movss xmm0, [eax + 0x2F4]` | **Current Barrier / Shield** |

#### `CKinActorNav` (Navigation & Orientation, VTable `0x1282970`)
| Offset | Type | Field Name | Disassembly Anchor / Proof | Description |
|---|---|---|---|---|
| `+0x00` | `void*` | `vtable` | `0x957833: mov [esi], 0x1282970` | Nav virtual table (size `0x7DC`) |
| `+0x08` | `CKinActor*`| `owning_actor` | `0x95DEF0: mov ecx, [esi + 0x08]` | Backpointer to owning Actor |
| `+0x774`| `Vector3` | `destination` | `0x95DEF3: movq xmm0, [edx]; movq [edi], xmm0` | Destination coordinate (x, y, z floats) |
| `+0x780`| `Vector3` | `current_waypoint` | `0x95DFC7: movq [esi + 0x780], xmm0` | Next navmesh waypoint (x, y, z floats) |
| `+0x7A8`| reference pointer plus companion value at +0x7AC | `target_reference` | `0x94B9D9: lea eax, [edi + 0x14]`; `0x94B9DC: mov [ecx + 0x7A8], eax` | Reference to target interface, not a raw CKinActor pointer |
| `+0x7B0`| `float` | **`facing_x`** | `0x95D710: movss [ecx + 0x7B0], xmm0` | Normalized facing vector X (cos yaw) |
| `+0x7B4`| `float` | **`facing_y`** | `0x95D723: movss [ecx + 0x7B4], xmm0` | Normalized facing vector Y (pitch) |
| `+0x7B8`| `float` | **`facing_z`** | `0x95D72B: movss [ecx + 0x7B8], xmm1` | Normalized facing vector Z (sin yaw) |
| `+0x7D0`| `uint8_t` | `path_flags` | `0x95DFB0: or byte ptr [esi + 0x7D0], 1` | Bit 0 = active nav path |
| `+0x7D4`| `uint32_t` | `nav_status_bits` | `0x94B9D0: or eax, 3; mov [ecx + 0x7D4], eax` | Low bits set when assigning another target and cleared on the self-target branch; prior 1/2/3 move/target/idle enum is unsupported |
| `+0x7D8`| `uint8_t` | `override_flags`| `0x95D643: test byte ptr [ecx + 0x7D8], 1` | Bit 0 = orientation override active |

*Yaw Calculation*: `yaw_radians = atan2(facing_z, facing_x)`. This exactly mirrors wire opcode 1010 facing cos/sin at `+24/+32`.

### 7.3 Global Anchor Pointers & Calling Conventions
Under MSVC 32-bit `__thiscall`, `ECX` holds the `this` pointer across all engine methods.
- **Global App Singleton**: `0x1E6EE1C` (`Nuo::Kindred::KindredClientMain*`).
- **Global Entity Registry**: `0x1E6EE20` (`Nuo::Game::NonAuthorativeObjectRegistry<unsigned char, CKinActor, 200>*`).
- **Global Entity Table**: `0x20E7404` (pointer to array of `0xB8`-byte records).
- **Global Entity Count**: `0x20E7408` (active entity count, `0 <= count <= 200`).
- **Global Local Player Entry**: `0x20E7424` (pointer into the entity table entry for the local player).
- **`GetLocalPlayerEid()` Helper at `0x939790`**: Reads `[0x20E7424] + 4` to return local player EID (`1500`).
- **`FindEntityById(u32 eid)` at `0x857970`**: Walks the entity registry, compares `[actor + 0x178] == eid`, and returns `CKinActor*` in `EAX`.
- **Movement request at `0x93D180`**: `__thiscall` on `CKinActor*` (`ECX`), delegates to `0x95DD70`, which invokes navigation through `0x95DED0`. This sets a destination and computes a path, not a direct write to actor position. The earlier `SetPosition` label was incorrect; see section 7.6.
- **`SetFacingDirection(Vector3 const& dir)` at `0x95D640`**: `__thiscall` on `CKinActorNav*` (`ECX`), normalizes direction and stores to `+0x7B0/+0x7B4/+0x7B8`.
- **Local movement/input routine at `0x52A420`**: Looks up the local EID, checks actor restrictions, calls movement request `0x93D180`, then branches to outgoing float serializers. This is not a verified 1067 handler or blend-tree transition routine. Opcode 1067 belongs to `ActionModifyVisibility`, established in section 7.6.

### 7.4 Delivered PC Tooling
1. **`Tools/client/scan_pc_actors.py`**: Non-invasive ctypes memory scanner. Connects via `OpenProcess` / `ReadProcessMemory`, reads WoW64 PEB, relocates static VAs, verifies code sites, traverses the global entity table and scans heap memory to print all active actors with EID, 3D coordinates, current HP/shield, facing yaw, and locomotion flags.
2. **`Tools/client/halcyon_tracer.cpp` / `halcyon_tracer32.dll`**: 32-bit native DLL compiled via MSVC `cl.exe /LD /O2`. Implements `DissectActor` and `DumpAllActors` to trace actor structs with 0 latency.
3. **`Tools/client/test_pc_actor_layout.py`**: Automated unit test suite verifying PE section alignment, bytecode signatures at code sites, and struct offset formulas against `VaingloryLocal.exe`.


### 7.5 Dual-Wield completion report: evidence scope and discrepancies (2026-09-07)

An operator-supplied completion report reiterates the 2,425 RTTI records,
CKinActor vtable 0x127B448, component pointers, position/identity fields, and
scanner/tracer tooling described above. Its claimed successful Amael
locomotion QA was subsequently withdrawn after gliding was observed again;
see vainglory-mobile-local-stack.md for the mobile evidence and follow-up.

The following table preserves historical conflicting claims, not current
facts. The action addresses and destination width are reconciled by section
7.6; flag meanings and total state-field width remain unverified:

| Detail | Supplied report | Existing section 7 claim |
|---|---|---|
| ActionStateChange_Client address | 0x94B810 | Execute at 0x52A420 |
| Moving/idle animation branches | 0x4D6490 / 0x4D6540 | Branch addresses not recorded |
| Actor +0x1E0, bit 0x01 | LOCAL_PREDICTOR_FLAG | Player |
| Actor +0x1E0, bit 0x10 | IS_ALIVE | Targetable |
| Actor +0x1E4 state_flags | uint32 | uint16 |
| Nav +0x774 destination | Two floats (x, z) | Vector3 (x, y, z) |

The estimated actor size of approximately 0x220 bytes remains unverified.
The claimed 1067 run/idle interpretation is disproved by the action RTTI and
visibility implementation below. Do not use the disputed predictor bit as a
patch target or treat PC offsets as validated mobile offsets.

### 7.6 DUAL-WIELD static correction: 1016 MoveTo and 1067 visibility (2026-09-07)

**[Observed, bounded PC disassembly and RTTI]** The local executable from
section 4 was inspected read-only using Capstone in x86 32-bit mode. PE
section headers were used to map each static VA to file bytes. These findings
apply to **PC revision 102405**; Android revision **147219** needs its own
wire/runtime validation. This audit does not establish mobile walking-animation
acceptance, exact animation blend curves, or complete engine reconstruction.

| Action | RTTI name | Vtable | Outgoing method | Apply method |
|---|---|---|---|---|
| 1016 | `.?AVActionMoveTo@Kindred@Nuo@@` | `0x127CA68` | `0x94B870` | `0x94F930` |
| 1067 | `.?AVActionModifyVisibility@Kindred@Nuo@@` | `0x127CA54` | `0x94B810` | `0x94F760` |

Reproduce the identities by following the Complete Object Locator pointer at
`vtable - 4`, its type-descriptor pointer at `COL + 12`, and the ASCII name at
`type_descriptor + 8`. Disassemble the outgoing/apply methods above and their
callees below; this requires no process attachment or binary modification.

**1016 payload and identity.** Constructor `0x81BC80` stores a byte ID at
action `+0x10` and a Vec3 at `+0x14`. The outgoing method serializes the ID and
Vec3 X/Z as two big-endian floats. Emitter `0x815AC0` explicitly writes opcode
`0x3F8` and copies **9 payload bytes**, `[u8 compact_id][f32be x][f32be z]`.
Transport/cipher padding is not part of these fields. At `0x84C082`, an action
producer reads the ID from **actor +0x1F0**, distinct from the full EID at
`+0x178`. Lookup `0x4A8F30` checks `id < 200`, uses registry pointer
`0x1E6EBC0`, validates a reference generation, and resolves the actor. Hero
IDs 0-5 observed in the corpus are entries in this general compact registry,
not proof that this opcode is restricted to heroes or minions.

**1016 navigation activation.** The apply method resolves the compact actor
and rejects actor component-state values 3/4 before requesting movement:

```text
0x94F930 ActionMoveTo apply
  -> 0x4A8F30 compact-ID lookup
  -> 0x93D180 actor movement request
  -> 0x95DD70 checks movement restrictions and actor+0x24 navigation
  -> 0x95DED0 navigation destination/path update
     0x95DEF7 / 0x95DEFE: copy target Vec3 to nav+0x774
     0x95DF9D: call 0x9F5BF0 with current position and destination
     0x95DFB0: on success, set nav+0x7D0 bit 0
     0x95DFC7 / 0x95DFD2: copy next waypoint to nav+0x780
```

The destination has three floats; the wire carries two ground-plane floats.
The path routine also checks a navigation configuration byte through
`[nav+0x14]+0x1C` and branches on actor state flags. A received action alone
therefore does not guarantee a valid active path. These instructions disprove
the previous claim that `0x93D180` merely overwrites actor world coordinates.
They establish a navigation request; animation success still requires mobile
observation. No local-predictor flag interpretation is needed for this finding.

**1067 visibility, not run/idle.** Outgoing method `0x94B810` serializes the
full EID and four bytes through emitter `0x8176C0`, which writes opcode 1067.
Apply method `0x94F760` resolves the full EID and a visibility component using
type global `0x2091598`, then passes the four bytes to `0x945DD0`. The setter
uses the first byte as an index and writes the other three into arrays at
component-relative `+0x14`, `+0x1C`, and `+0x24` within the selected bank.
Its branch logic hashes event identifiers `onEnterBrush` and `onExitBrush`
(strings at `0x121C618` and `0x121C628`). Exact names for all four wire fields
remain open, but interpreting `0x0F`/`0x00` as run/idle enums is unsupported.
Guessed 1067 animation emissions can change visibility and must not be used
as locomotion triggers.

Finally, the `0x52A420` branches to `0x4D6490` / `0x4D6540` are outgoing
float serialization paths, not observed run/idle animation clips. The earlier
report assigned both the wrong action identity and the wrong behavior to
these addresses. Mobile captures and server movement changes belong in the
movement/mobile leaves, independently of this PC evidence.
> **Locomotion follow-up (2026-09-07):** additional PC findings establish
> `1070 ActionMoveToCorrection` and `1093 ActionCancelBuff`; the consolidated
> record also includes navigation guards and the speed expression. The operator
> now reports visible but choppy mobile walking after an external bootstrap
> extension. PC semantics do not prove buff type 255 blocks movement, and PC
> offsets are not Android offsets. See
> [the consolidated handoff](vainglory-locomotion-handoff.md).

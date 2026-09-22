# Vainglory runtime reconstruction — method, tooling, and operational traps

Created 2026-09-03 as part of the docs normalisation. This leaf answers
"how was the running game observed, and how do I repeat or extend it". The
*results* live in their topical leaves: placement table and cross-validation
in the map leaf §11, waypoint path objects in
`vainglory-movement-anatomy.md`, traffic windows in
`vainglory-netcode-backend.md`.

Boundary (binding): passive observation of the user's own devices and
static analysis of released files only. No decryption, no DRM bypass, no
crafted packets, no active probing of their infrastructure. The runtime
route works *because* the process decodes its own data — we read, never
patch.

## 1. Environment (Observed)

| Component | Value |
|---|---|
| Emulator | LDPlayer 9, rooted, Android 9, x86_64 kernel + arm64 translation |
| Why this one | AOSP AVD images API 29/30/34 all fail earlier (see goal 012 decision log); LDPlayer's legacy-EGL stack runs the game |
| Guest resolution | 1600×900 (`adb shell wm size`) — all tap coordinates are guest-space |
| App identity | `com.superevilmegacorp.game`, versionCode 147219 (4.13.4) + matching OBB |
| Native lib | `libGameKindred.so`, arm64-v8a, 45,062,040 B, stripped |

## 2. Driving the guest UI — adb only (Observed, binding rule)

The Windows-click route against the player window fails repeatedly (window
identity mismatch, stale frames, self-minimizing) and is **dropped
entirely** — `AGENTS.md` guardrail 6. The only route:

```bash
adb shell wm size                      # read guest resolution first
adb shell input tap <x> <y>            # guest coordinates
adb shell input swipe x1 y1 x2 y2 ms   # drag/pan gestures
adb exec-out screencap -p > scr.png    # pixels for verification
```

Menu flow that reliably reaches a solo-bot 3v3 match (guest 1600×900,
tap → sleep ≈ 1 s between screens): PLAY (1308, 790) → SOLO BOT (1435, 635)
→ 3V3 (1188, 490) → VERY EASY (1188, 310) → LOCK IN (800, 820).

## 3. Memory dump pipeline (Observed)

1. Get the pid: `adb shell su -c "ps -A | grep -i kindred"`.
2. Enumerate readable regions: `/proc/<pid>/maps`; dump region contents via
   `/proc/<pid>/mem`.
3. **Trap**: Android 9 `toybox dd` and `busybox dd` mishandle 64-bit
   `skip=` into `/proc/pid/mem`; `toybox xxd -s <off> -l <len>` seeks
   correctly. Use `xxd -r -p` (or plain `xxd` output) to land bytes in a
   file.
4. **Trap**: `mksh` arithmetic is 32-bit and silently truncates hex
   addresses — do all offset math on the host (Python), not in `adb shell`.
5. Captures used for goal 012: two passes ~3 min apart inside one match,
   plus one pass from a second match (region bins kept outside the repo,
   e.g. `ba2/bb2/ba1*.bin`), with a host-side string table of **4,861
   verified string VAs** (`strings.json`) and region base VA
   `0x763866000000`.

## 4. Static-intersect scan (Observed)

`Tools/Teardown/scan_memory_dump.py` intersects 4-aligned `(x,y,z)` f32
triples inside the known map bounds across passes: actors move, statics do
not. 8.19 M static triples in one pass → 758 K surviving the cross-match.
The survivor set is what exposed the 3-unit placement lattice and the named
placement chain.

Anchor trick: printable strings found in a dump give verified virtual
addresses; heap pointers that land inside a known string are `char*`s, and
`pointer − base_va` converts to file offsets in the region bin. This is how
the placement chain and the path objects were walked (pointer chasing with
validation by `HF_` prefix / printable-name round-trip).

## 5. Tool inventory (`Tools/Teardown/`, all reproducible)

| Tool | Input → output | What it established |
|---|---|---|
| `extract_vainglory_paths.py` | store dir → 1,250 self-declared paths | store tree, zone names, blueprint taxonomy |
| `render_vainglory_bc1.py` | store dir → decoded top-mip thumbnails | 28-byte texture header codec (store leaf §6) |
| `render_vainglory_navmesh.py` | nav record → SVG/PNG mesh | full navmesh container format, 100 % of payload (map leaf §4) |
| `scan_memory_dump.py` | ≥2 region dumps → static triples | placement lattice, runtime instance coords |
| `parse_vainglory_placement.py` | region.bin + base_va + strings.json + chain_start → 30-record JSON | named placement table (map leaf §11.4) |
| `build_map_layout.py` | nav record + placement JSON → `Assets/_Game/Map/map-layout.json` (+ PNG) | walkable outline (62 pts), 16 holes, renamed objectives, anchor-chained routes; 30/30 containment check |

Parser details worth keeping (map leaf §11.4 and movement leaf §1 are the
evidence; this is the how): placement records are `{namePtr → inline name
@+0x38, ptr2, f32 x,y,z, 0, yaw°, 0}` with `next` at **+0x50 or +0x58**
(probe both) targeting the next record's *inline name* — the walker computes
`record = next − base_va − 0x38` and validates the name round-trip.

## 6. Network measurement — passive counters only (Observed)

No packet capture, no MITM: `/proc/net/tcp` (hex-decode little-endian
IP:port) to enumerate connections, and `/proc/net/dev` `wlan0` counters
sampled at 0.35–0.5 s from the host to build rate series. Menu baseline,
in-match idle and in-match driven windows are reported in
`vainglory-netcode-backend.md` §2. Endpoint identification is DNS-only:
resolve known hostnames and reverse-DNS observed IPs — never connect to
them.

## 7. Negative results that shaped the route (Observed negatives)

1. **Navmesh vertices are not stored verbatim in memory** — 0 exact-bit hits
   for all 793 triples; the engine converts the store payload at load. The
   file bytes cannot anchor a memory search.
2. **Minion lane waypoint polylines are not flat f32 arrays in the heap** —
   scan over 4.26 M ground triples produced one candidate (a 1-unit-step
   top-jungle strip); closed as negative, superseded by anchor-chained
   geodesics (goal 013, [Inferred]).
3. **The OBB adds no placement data** — a float-bounds sweep over every
   plain store file needed three passes to answer honestly (padding zeros
   → unit-cube parameters → layout discriminator) and ended at 25
   candidates, all animation/curve blobs (map leaf §10). Method note for
   any future scan: a discriminator (values outside parameter-cube + distinct
   `(x,z)` multiplicity) is what separates signal from shader noise, not
   raw in-bounds counts.

## 8. Runtime observation and differential comparison — corrected 2026-09-12

### September22 ordinary input and native lifecycle readiness

`Tools/android_input_health.py` parses the owned PID's existing NUO lifecycle
log (`logcat -d -v epoch -t2000 -s NUO:D`). A new completed `Resume - Post`,
with no later resume/suspend transition, is a conservative readiness gate;
foreground Android activity alone is insufficient. Do not compare guest log
wall time directly with host gesture wall time: their measured offset in05
was about16.6s, and ResumePost already preceded a failed PLAY by about2.3s.
The source anchor is owned `NuoActivityGame.processTouch` → `NuoView`/
`Renderer.isInitialized` and `executeState`'s JNI resume completion. The
initialized predicate itself only excludes uninitialized state, so do not
claim that it alone explains the lost input. Successful control/wire response
is still required. Missing logs or stale/wrong-PID events remain unknown.
This reads lifecycle state, not images, frame pacing or FPS.

An external bounded06probe additionally qualified the JNI touch pipeline:
ELF`7f638c` checks app`2b08f98` and callback`2b08f30`; callback`18843c8`
uses owner`3114448`, vtable`2aaec70`, then`1884460` writes32slots at
owner+28, stride40. One ordinary PLAY yielded17active queue reads and16UI
captures, then the native mode chooser. This qualifies read-only delivery
observation, not the site dropping earlier touches. Lifecycle/button flags
alone are not successful-input evidence. See checkpoint19 in the run leaf.

The subsequent08trial attached a bounded Java observer before the first PLAY
(`Activity.dispatchTouchEvent`, owned`onTouchEvent` and`processTouch`), calling
each original unchanged and detaching afterward. No dispatch or native queue
event appeared. The owned view reported`hasWindowFocus=false` despite Android
global focus naming the game. A later stable true view-focus observation
preceded successful delivery and mode transition. This narrows that failed
input upstream of Activity dispatch; it is not a universal root-cause claim.
The read-only activity lookup follows`ActivityThread.mActivities` (bound8),
not a heap scan. External Frida17Java bridge bundle/version/digest and event
receipts are preserved under the run's`java-input-observer/` and08directories.
The observer itself adds overhead; its measurements are delivery/state, not
timing acceptance. See checkpoint20.

09then qualified a minimized/backgrounded owned LDPlayer host window as
one readiness failure. `activate_owned_ldplayer` validates the executable
path and unique window, restores/activates it, and releases temporary input
thread attachments; guest view focus must still qualify.12demonstrated why:
host activation succeeded but the view remained unfocused. Android input
state identified a second, dialog-sized window owned by the game. A bounded
accessibility XML read identified the sign-in-failure message and one enabled
OK control (`android:id/button3`, bounds `[244,275][308,323]`). One ordinary
tap at its center removed the dialog; stable Java focus and the subsequent
PLAY/mode transition qualified entry. These coordinates are historical
evidence, not a reusable blind tap. XML lives outside Git under12;
no image/video was produced. See checkpoints21–23 in the run leaf.

The optional source-pinned persistent ordinary Android input wrapper is
documented in [the scenario leaf](../Plan/solo-sandbox-scenarios.md#current-nonvisual-paths--september-22-2026).
It calls the same device input class as `/system/bin/input`, retaining native
UI and wire gates while avoiding a new VM per gesture. Source/dex/remote
digests and sequential timing receipts are external. Transport completion
does not prove native command consumption; no game function or packet is
injected.

### September 22 ten-hour run: model and baked navigation qualification

Active camera projection is also now qualified through `81ef94 -> 8bbfb0 ->
8bd5c8 -> 8b891c`, viewport `e00238/e034d4`. Owned manager global302ede8,
active camera+2b0, view+18c, projection+20c, vtable26c2288; dirty bit2 is
rejected rather than calling the native lazy updater. `camera_view()` and
`project_position()` feed optional `world_points` in the existing movement
scenario, with retained matrix/input provenance and central-playfield bounds.
Three live world-point inputs pass; ground picking on a slope can differ from
the supplied world point, so projection is not claimed to invert navigation.

The read-only native observer now supports `model_transform=True` with
owner/type/vtable/generation/resource checks. `c58004` forwards position via
the entity presentation interface to `8ad524`; `d7cce0` updates the model
translation, `d7ccd0` returns its column-major matrix, and `8a9d6c/8b2364`
bind its mesh/animation component. This is root model world state, **not bone
pose, view projection, frame pacing or display-time acceptance**. No image or
video path was used. Offline inspection uses `--client-position model` and
rejects missing/unqualified model samples rather than falling back to logical.

A separate bounded owner-query chain (`c60ff4`, `df09b4/df09f8`, manager
`3110ca8`) recovered the baked Detour geometry. All870 tiles' immutable geometry
matches the owned `4D562D63B9D0796F7FCC5EC61ADB111B` asset. This proves that the
old server A001 authoring mesh was the wrong geometry for at least one measured
corner. See [navigation finding, code changes and evidence](../Plan/solo-sandbox-navigation.md#september-22-native-baked-navigation-replaces-authoring-geometry).
Keep the native path and root-model qualification distinct from complete
rendered/gameplay acceptance and from simulation determinism.

### 2026-09-22: external CE passive reference workflow

The owned client has now completed two nonvisual movement batteries against
the external CE service: **14 inputs / 10,030 logical client samples**.
See [reference measurements](../Plan/solo-sandbox-navigation.md#external-ce-movement-reference--2026-09-22).
This is independent semantic evidence, not a full computation oracle or
general movement-smoothness acceptance.

`Tools/Teardown/observe_reference_wire.py` adapts an **already running owned
client packet trace** to the existing scenario JSONL contract. It starts no
capture, contacts no backend and sends no game packets. It incrementally
reassembles the selected ordinary TCP match flow and uses the production
codec, validates route/ack framing, rejects conflicting retransmissions,
records incomplete tails/gaps, and excludes opcode 1000 login data from JSONL.
Evidence/output must be external; existing output directories are rejected.

```powershell
python -B Tools/Teardown/observe_reference_wire.py --adb D:/LDPlayer/LDPlayer9/adb.exe --serial 127.0.0.1:5555 --remote-pcap /sdcard/<owned-existing-trace>.pcap --match-id <verified-match-uuid> --server-port <observed-port> --duration 125 --output <new-external-directory>
python -B Tools/run_scenarios.py --mode client --scenario movement-walk --adb-serial 127.0.0.1:5555 --wire-trace <adapter-output>/wire.jsonl --connection <observed-client-port> --client-profile <nonvisual-profile> --output <new-external-run>
python -B Tools/Teardown/inspect_movement_trace.py trace <adapter-output>/wire.jsonl --connection <observed-client-port> --timing --eid <verified-owner> --slot <verified-slot>
```

Before driving: verify stock external routing, preserve/isolate local-issued
profile credentials, use ordinary native-label-guarded entry, establish fresh
match identity from **manifest contents**, and wait for native gameplay state.
Wire-ready can precede native owner creation. The retained label/layout entry
helper is qualified on this pinned build, not a general UI navigator.
Restore the local profile/routing afterward and stop only owned observers.
No image fallback, broad memory scan or remote packet injection is permitted.

The adapter retains packet capture time and measured host/guest brackets.
`inspect_movement_trace.py` labels these **client-interface** intervals;
mixed/unknown timestamp sources and local-server tick correlation of this
external trace are rejected. Do not call them server input-to-ack measurements.
One polling batch is an observation/export window, not a simulation tick.

**Replay qualification correction:** this paired run has zero `1070` in
15,041 native replay frames despite 45 owner corrections on wire. Fourteen
ordinary owner `1016` payloads/order match exactly, plus one extra shorter
native record. Preserve packet + native state + replay together; `.vgr` alone
omits the very correction traffic relevant to the walking defect.

### 2026-09-22: anchored client data reads qualified on LDPlayer

**The position-accessor blocker is superseded, not the ARM-hook closure.**
The September 21 same-session check found ARM64 `libGameKindred.so` in
`/proc/<pid>/maps` while native Frida enumeration omitted it: a namespace
visibility split. Following the identified `1070` consumer now yields a
read-only entity registry → EID → position/navigation-component chain.
Frida's native realm can read those mapped addresses despite not enumerating
the guest library. No translated ARM function call/hook or broad heap scan is
needed. The owned library digest and mapped anchor bytes are checked first.

The durable observer is `Tools/Teardown/observe_client_movement.py` with
`client_movement_observer.js`, integrated into the existing movement scenario.
Owner 1500 was qualified stationary; moving bot 1515 produced 779 samples,
193 distinct positions and 17 correction-timer resets. Host/guest monotonic
clock brackets and per-read duration are retained. These are non-atomic
logical entity reads, **not model/render transforms or owned-hero smoothness
acceptance**. The subsequent native UI tree/text anchor identified a blocking
Choose a Build panel. A title-guarded Back restored input, then the walking
owner produced 4,194 samples. A short-walk A/B/A measured backward logical
motion on 8/12 baseline legs versus 0/6 with periodic owner corrections
suppressed; a scoped walking-publication fix follows from this evidence.
See the [owner correction experiment](../Plan/solo-sandbox-navigation.md#measured-owner-correction-reversal-and-walking-fix--2026-09-22)
for the native UTF-16 anchors, measurement boundaries and current fix status.

Exact ELF anchors, build hash, tests, evidence and outstanding guards:
[nonvisual client accessor](../Plan/solo-sandbox-navigation.md#nonvisual-client-position-and-correction-accessor--2026-09-22).
AGENTS.md now forbids image/video dependencies, including entry guards;
older capture procedures are historical, not fallbacks.

### Historical qualification and comparison boundaries

The 2026-09-07 version of this section described proposed opcode, JSON-RPC
and allocator hooks as an active, working instrumentation stack. That claim
was not supported by the later qualification run and is withdrawn.

In corr32 (`run-1789191266817-b1abe751`), Frida 17.11.0 started and native and
emulated sessions attached, loaded a no-op observer, enumerated modules and
detached. Neither enumeration exposed the target `libGameKindred`: the native
realm reported 196 modules and the emulated realm seven. This is **target not
observed**, not a working game-state observer, proof of a private loader, or
proof that every instrumentation route is impossible. At that point the
LDPlayer route was parked pending the new anchor/environment result above.
Preserved evidence:
`%LOCALAPPDATA%/halcyon-evidence/halcyon-corr32-observer-final-20260912/`.

A 2026-09-18 method note
([vainglory-instrumentation-transfer.md](vainglory-instrumentation-transfer.md)
§1) reports the identical enumeration signature for any translated arm64 app
on this LDPlayer + Houdini stack and names the specific environment test the
route was parked on: compare `/proc/<pid>/maps` against the native realm's
enumeration in one session. [Inferred]

The older “static analysis is blocked by stripped symbols” wording was also
too broad. Symbols are absent, but identified dispatch handlers and CFF
action/relocation tables provide bounded entry points. Follow the
[structural investigation loop](vainglory-community-ecosystem-tricks.md#research-direction-correction--2026-09-12)
before commissioning another capture or loader experiment.

There are two distinct comparisons:

- **Client contract:** feed a dependency-preserving recorded stream through
  our local stack to the owned client, then inspect identified state changes
  or presentation. This investigates how the client consumes server output.
- **Authoritative behavior:** replay compatible C2S intents through production
  `SnapshotStream.advance_simulation`, with a known initial state and relevant
  rules, then compare semantic outcomes against independent observations.
  Missing input, rank/item state, bot actions or timing makes a comparison
  incomplete, not automatically a formula defect. S2C-only VGR is insufficient
  to recreate those missing causes.

The former promise of “zero mathematical drift” from packet comparison is
withdrawn. Raw packet equality does not establish universal gameplay parity;
identity mapping, publication order, sampling and clock alignment matter.
Reference comparisons require measured, justified tolerances and explicit
unknowns. Determinism of our own implementation remains an exact comparison.
Use current measured opcode semantics (including `1078` skill upgrades), not
the old illustrative `1157` upgrade or `1067` animation assumptions.

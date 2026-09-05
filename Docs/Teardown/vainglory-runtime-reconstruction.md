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

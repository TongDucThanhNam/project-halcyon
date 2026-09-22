# Instrumentation route selection — transfers from an external RE case

> **Local qualification update, 2026-09-22:** the map/enumeration split below
> was confirmed on the owned Vainglory client. More importantly, native-realm
> **read-only access to code-anchored mapped data works**: the `1070` consumer
> led to EID-attributed client position and correction state, demonstrated on
> a moving entity and subsequently the walking owner. A code-derived native
> UI text guard removed the setup blocker. Owner correction A/B/A now
> measures a specific backward-motion defect and supports a scoped
> publication repair. A later code-anchored owner-bound **root model matrix**
> accessor is now qualified too; bone/camera/display-time acceptance is not.
> This is not an ARM Interceptor success. See [runtime §8](vainglory-runtime-reconstruction.md#8-runtime-observation-and-differential-comparison--corrected-2026-09-12)
> and its linked exact evidence. The September 18 method claims below retain
> their original dates; do not repeat the already-settled namespace test.

> **Status: method note, 2026-09-18.** No Vainglory target was touched to
> write this leaf. It transfers techniques proven in an unrelated
> reverse-engineering case — the ByteDance Doubao Android (arm64) client on
> the same LDPlayer 9 + Houdini translation stack, Frida 17.18 host +
> rooted `frida-server` — and assesses them against Halcyon's recorded
> evidence. Labels follow the README; every Vainglory-side claim not yet
> locally reproduced is [Inferred] or [Unverified] and names its
> falsification step.
>
> Full case study (operator vault, outside this repo):
> `C:\Users\terasumi\Documents\StudyWithTerasumi\30_Resources\Software_Engineering_Mental_Models\60_Case_Studies\Case Study - Doubao Mobile Feed Reverse Engineering via Cookie Replay.md`

## Qualified scalar and UI accessors — September 22 ten-hour run

The same pinned, read-only observer now provides reusable nonvisual controls
and resources in `Tools/Teardown/observe_client_movement.py` and its JS agent.
All offsets below are **ELF virtual addresses** (the owned Ghidra listing uses
ELF + `0x100000`), checked against the mapped pinned ARM64 image before reading.
No translated ARM calls, Interceptor, heap search, images or memory writes.

| Native consumer/binding | Qualified measurement |
|---|---|
| `c58004 -> 8ad524 -> d7cce0/d7ccd0`, `8a9d6c/8b2364` | Owner-bound root model world matrix, loaded mesh resource, component/type/generation qualification; not bone pose or camera/display time |
| `81ef94 -> 8bbfb0 -> 8bd5c8 -> 8b891c`, `e00238/e034d4` | Active view/projection matrices and viewport; ordinary projected ground inputs qualified, dirty/changed state rejected; no pixels |
| `c60ff4 -> df09b4/df09f8`, `3110ca8`, `df16c4` | Owner navigation query, bounded native path and baked Detour tiles; all870 match owned asset geometry |
| `df09f8 -> df0f78`, `c60208` | Double-read query array/destination/cursor, at most128points; flag bit0 qualifies active movement.38of39active paths match offline pinned Detour exactly, one height differs by one ULP; inactive retained arrays are not current route evidence |
| `ca1284`, `c5b404` | Target-radius inclusion and scaled definition radius; ten turret radii2.15 and two crystal radii2.5 |
| `c04408`, `c01624`, `caa5a0` | Entity resource component: current HP/EP/barrier/fortified/gold/XP and native maximum-attribute formula/clamps |
| `c9ee8c`, `c772c8` | Movement-speed attribute18 layers plus bounded type-qualified modifier descendants; demonstrated native3.7 versus server5.7, then native3.7+2 after temporary bonus publication |
| `957c98` | HUD kills/deaths from attributes 41/42; assists/farm from resources 11/14 |
| `9153f0`, `885090 -> 8850b8 -> 826ba0` | Ordinary target selection/deduplication and1060 sender; owner+2b0/+2b8 target weak handle, bounded typed-registry and generation checks |
| `829fac -> c041e4 -> c042f0 -> c5b68c -> c5f478` |1052 absolute base-attribute setter; maximum-HP write clamps current pool but does not fill an increase |
| `9300f8`, `9305c8` | Default-item owner/instance binding, exact callback and clipped touch rectangle |
| `8f1f64`, `9114dc`, `93b354 -> 9170cc` | Saved camera-lock preference, owning hero and ordinary HUD toggle |
| `923dd8`, `924160`, `927d68 -> 9287e4` | Ability cast/upgrade owner lifetime, UI slot, native action and touch rectangle |
| `96eb98`, `96ff1c`, `8c7a54` | Utilities Recall item0 and Shop item2, verified owner and clipped control |
| `c03188 -> c5c5c4 -> c72a18`, `c70fc4`, `c7175c/c71764` | Native inventory slots, item/instance IDs and quantity; includes default items |
| `960b70`, `96307c`, `965914`, `95c4a8`, `95c7b0`, `95a9f4` | Catalog item/owner binding, selection, BUY owner lifetime and purchase mode |
| `e0061c`, `e02710`, `e0d3a4`, `810394` | Active bounded UI tree and native UTF-16 labels; not OCR |
| `7f638c`, `188437c/18843c8 -> 1884460` | External read-only qualification of JNI app/callback and typed touch owner,32bounded slots; one ordinary PLAY correlated native queue, UI capture and mode transition. Earlier intermittent missing-touch site remains unknown |

Input readiness also requires the actual owned Java view's window focus,
not merely Android's focused activity name. Exact existing Java methods can
be observed with originals called unchanged.09qualified restoration of the
path-identified LDPlayer host window;12isolated a different cause: an owned
Java sign-in-failure dialog covering the game. Its accessibility XML supplied
the exact message, package and clickable OK bounds. One ordinary dismissal
restored focus and delivered PLAY. No pixels, OCR or game-memory writes;
do not treat host activation as a universal fix or repeatedly retry input.

Live Flask use plus disclosed incoming-hit diagnostics measured barrier
150→50→0 and exactly agreeing final native/server HP 579.5. Natural wounded
level 3→4 exposed, then verified the repair of, a server/client HP-growth
mismatch (post-fix HP error below `0.000001`). Ordinary attack and diagnostic
death/farm trials verified native counters and natural respawn retention.
Camera lock was genuinely off in a failed targeting trial; one code-identified
ordinary toggle made it on. Ability control bindings are live-qualified;
ordinary A/B/C and Recall completion/cancellation now pass native resource and
logical-position gates in disclosed prepared trials. Weapon Blade ordinary
purchase created native item458/instance2002 and +10 bonus. Native weapon-power
layers exposed a client-only10% modifier imported from the archived tape; the
fresh repaired bootstrap reads zero multiplier. The observer also pins entity
generation to reject same-EID/pointer reuse across native lifetimes.

Evidence and exact trial directories: [ten-hour run](../Plan/classic-ten-hour-run.md).
Resource/counter agreement does not prove model animation, model-transform
smoothness or independent CE rule/timing parity. A native logical position is
still not a model transform. Free-camera reference fields are not a qualified
view matrix, especially while the camera is locked.

## 1. The corr32 "target not observed" signature is expected under translation

[Observed, external case] On LDPlayer 9 with Houdini ARM translation, Frida's
native realm enumerated the x86-side module list only; every guest arm64
library of the translated target app was absent from
`Process.enumerateModules()` while the app demonstrably ran. Java-realm
tooling (class enumeration, `Java.use`) behaved normally in the same
sessions, and the x86 native realm remained fully scriptable: the case
dumped a 57 KB SQLite file from the app's private storage by calling
`fopen`/`fread`/`send` as `NativeFunction`s from the injected script.

[Inferred → corr32] The 2026-09-12 corr32 qualification (runtime leaf §8:
196 native + 7 emulated modules, no `libGameKindred`) matches that
signature. Leading explanation: Houdini maps and links guest ARM objects
through its own ARM linker namespace, which x86-side enumeration does not
surface — "module not enumerated" under translation is the expected
observation, not evidence of a failed attach or an unobservable target.

Falsification (minutes, own emulator, read-only) — distinguishes the
namespace-split hypothesis from "never mapped" (which would reopen the
private-loader hypothesis):

1. Resolve the CE client PID (`pidof`), attach the same no-op observer.
2. From a root shell, `cat /proc/<pid>/maps`; look for file-backed
   `libGameKindred` regions.
3. Compare with `Process.enumerateModules()` in the same session.
   Mapped in `/proc` but absent from enumeration confirms the split;
   absent from both falsifies the diagnosis.

Consequences:

- `Interceptor`-style hooks **inside translated ARM code** stay closed
  without a native ARM execution environment. Sanctioned routes are
  unchanged: a rooted physical arm64 device (where guest libraries are real
  modules), the PC lab, and the HackedGlory loader-shim lead
  (ecosystem leaf).
- Java-realm hooks work under translation, but the client's Java surface
  is minimal; do not budget time there for game logic.
- Anything reachable as an x86-side export stays callable from the injected
  script — which is exactly the PC lab's operating mode, transferred to the
  emulator if a bridged export ever matters.
- **Qualified September 22:** data reads do not require the guest library to
  appear in native module enumeration. Derive ASLR base from rooted process
  maps, verify pinned mapped code bytes, and follow only an identified
  consumer's bounded registry/field chain. This opens client-state telemetry,
  not blind translated-code interception or speculative heap scans.

## 2. PC-lab technique transfers (highest local value)

### 2.1 Hook the decrypt boundary for oracle evidence collection

The oracle compares semantic outcomes under measured, justified tolerances
(AGENTS.md; raw packet equality was withdrawn as a fidelity proof). What
timed, labeled streams add is cheap, complete evidence *collection*: hooking
the client's receive/dispatch and Blowfish-decrypt call sites on
`VaingloryLocal.exe` dumps every frame in plaintext, in arrival order, with
host-clock timestamps — no offline key reconstruction, no capture-decode
drift. Method matches the ecosystem leaf's anchor-first loop: hook the x86
`recv`/`send` exports (real modules on PC), backtrace to the identified
dispatcher, then instrument the decrypt routine it calls. [Unverified
locally — the call site has not been located on this build; the ecosystem
leaf's HackedGlory transport writeup is the anchor lead.]

### 2.2 Dump post-conversion structures, not raw bytes

Runtime leaf §7 closed the raw heap scans: navmesh triples are not verbatim,
waypoint polylines are not flat `f32` arrays, the OBB sweep produced only
animation/curve candidates — the engine converts store payloads at load.
The external case hit the same wall one layer shallower; the fix transfers:
**set the dump point at the conversion output or the consuming accessor,
not at the stored bytes.** Concretely: follow an identified handler into
the state-write it performs (the structural loop the ecosystem leaf already
prescribes) and dump the converted structure there. A named consumer anchor
beats any in-bounds byte count as a discriminator.

### 2.3 Binary dump primitive: native calls + host script

For any of the above, move buffers out with native `fopen`/`fread`/`fwrite`
via `NativeFunction` and stream them with `send(payload, ArrayBuffer)` to a
small host-side Python process. The external case found Frida's Java
`byte[]` bridge unreliable for binary and this path reliable for multi-MB
dumps. Keep dumps under `%LOCALAPPDATA%/halcyon-evidence/...` per the
artifact rule; nothing here changes what may enter Git.

## 3. Ops micro-tricks (marginal; recorded to avoid re-derivation)

- **Attach by explicit PID.** Attach-by-name landed in an isolated
  subprocess (different uid) in the external case; every "permission denied
  on the app's own file" symptom was that, not SELinux. Use `pidof` + `-p`.
- **DROP vs REJECT semantics.** `iptables REJECT` on udp/443 made the
  external target fail fast with no protocol fallback; `DROP` (silent
  timeout) made it fall back to TCP. If `guest_setup`'s leak rejection ever
  needs a client to give up a route quietly instead of retry-storming,
  that is the knob. [Observed, external case]
- **Idempotent post-reboot re-inject.** tmpfs-mounted state (CA store,
  root hiding, rules) disappears at reboot by design; the fix is a single
  re-run script. `guest_setup` already implements this discipline; no
  change proposed.

## 4. What does not transfer

- **Session/cookie replay against a live backend** — excluded by binding
  boundary 1 (read-only towards anything we did not stand up), and the
  match protocol is stateful binary, not replayable REST. The owned analog
  already exists: `server/replay.py` input-stream replay against our own
  server.
- **WebView cookie-store extraction** — the client has no webview auth
  surface; T1 issues our own guest JWTs.
- **TLS-interception plumbing** — already owned (`guest_setup` overlay);
  the external case adds nothing to it.

## 5. Leaf relationships

- `vainglory-dead-ends.md` — new entry recording the translated-LDPlayer
  native-hook closure and this diagnosis.
- `vainglory-runtime-reconstruction.md` §8 — the corr32 record; the
  falsification test above is the concrete "anchor/environment result" the
  route was parked on.
- `vainglory-community-ecosystem-tricks.md` — the loader-shim lead and the
  anchor-first structural loop this note extends.

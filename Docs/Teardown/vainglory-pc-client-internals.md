# Vainglory PC client internals — menu replies and the endSession error counter

Updated 2026-09-05 after a controlled repair of the local platform replies.
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

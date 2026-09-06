# Implementation brief review — 2026-09-05

Review of the operator-supplied matchmaking/T3 research brief. Its useful
contribution is a set of source leads and a proposed sequence of small gameplay
milestones. Its implementation recipes mix hypotheses, obsolete PC findings,
and superseded wire interpretations. Do not treat the brief as a protocol spec.

## Verified external leads

Only public source text was inspected. No external proxy was run, no live game
backend was contacted, and no proprietary payload or third-party source was
copied into this repository.

| Source | What the inspected source establishes | Confidence limit |
|---|---|---|
| [VGReborn monitor](https://github.com/VaingloryReborn/VGReborn/blob/main/mitm-monitor/src/handlers/actionDispatcher.ts) | Its `queryPendingMatch` handler reads `returnValue.isValid` and `returnValue.responses`; its `update` handler recognizes `returnValue.state` values `menus` and `playing`. Its `joinLobby` handler parses the JSON string at request `params[1]`, including `lobby` and `playerHandle`, consistent with our captured request shape. | **Observed in third-party source**, not validated against our mobile client's response consumer. It provides no complete join reply, assignment sequence, or match connection configuration. Monitor state labels are not necessarily client state-machine semantics. |
| [HackedGlory schema sheet](https://github.com/a1cnore/HackedGlory/blob/main/reports/method_schema_sheet.md) and [mock contract](https://github.com/a1cnore/HackedGlory/blob/main/reports/generated/mock_contract.json) | Lists `joinLobby`, `acceptMatch`, `rejectMatch`, and `queryPendingMatch` among session/lobby methods. | The contract explicitly describes static-string inference and approximate field ownership. These are search leads, not captured accepted replies. |
| [VGReborn README](https://github.com/VaingloryReborn/VGReborn) | Describes VPN/MITM monitoring with web and Supabase components around CE. | This does not establish a replacement authoritative simulation server, or prove that its proposed features are complete. |

The brief's GitHub URLs omitted the actual owners. The repositories inspected
were `VaingloryReborn/VGReborn` and `a1cnore/HackedGlory`. Our wire leaf already
credits HackedGlory for specific prior findings; it is not an entirely new
discovery or blanket independent corroboration of our RE.

Downloaded review copies are external under `$TEMP/halcyon_review_20260905/`.
Content fingerprints for reproducibility:

- VGReborn `actionDispatcher.ts`: SHA-256
  `f5ba421ac0993d1fc36511f63da76b8e044b72f05aff6a14dfb86853d633a9c1`.
- HackedGlory `method_schema_sheet.md`: SHA-256
  `0d1524b453fc8082d789aa88b526be733136d148f9f099bbadbdd466ddfd9050`.
- HackedGlory `mock_contract.json`: SHA-256
  `b653ccb2b9ee49f55c2c76e0d09de1a960f5477128af09c742e37c6ac27b9e62`.

## T1 claims to correct before acting

| Brief claim | Review |
|---|---|
| Patch PC `0x4f1320` to enter matchmaking | The verified PC function handles RPC status/error waiting. The watchdog/manifest failures were repaired by correcting replies, with the watchdog original. No queue-entry patch is established at this address. See `vainglory-pc-client-internals.md` §1. |
| Manifest retry storm still blocks PLAY | Obsolete. The PC 18-minute run had no manifest requests after its initial phase. The separate mobile run visibly reached PLAY. Keep those two experiments distinct. |
| Try ten guessed service-style method names in `answers.json` | Unsupported discovery method. `local_stack.py` selects replies for methods the client has already requested; adding unused keys cannot induce new client calls. Use captured method names and source-backed leads. |
| Reply with an `error/code/result` success object | This differs from the locally observed `code`/`returnValue` envelope. No evidence establishes that proposed envelope for this operation. |
| Use the 167-case match dispatch as a menu-RPC catalogue | That catalogue covers the binary match protocol. Mapping a JSON-RPC consumer requires its own evidence; similar strings or nearby addresses are insufficient. |
| Wireshark loopback exposes TCP before Blowfish encryption | Socket traffic is already encrypted when application-layer encryption happens before the send. Plaintext instrumentation must be at an identified encode/decode boundary. Our own platform server already terminates its TLS requests. |
| CE account data on-device implies local matchmaking logic | The [SEMC roadmap](https://www.vainglorygame.com/news/vainglory-community-edition/?p=27342) discusses locally stored handle/matchmaking information. It does not define where opponents are selected or disclose the assignment algorithm. |

No remote MITM or candidate request injection is part of the local-only plan.
Current boot and certificate setup is in `vainglory-mobile-local-stack.md`.

## T3 and determinism claims to correct

| Brief claim | Review |
|---|---|
| Keepalive counter rises about 513/s, so simulation runs at 513 Hz | The measured quantity is a wire counter rate (`vainglory-protocol-wire.md` §15.8). Simulation scheduling frequency and a mandatory 2 ms budget have not been established. The claim that Python necessarily fails at a particular entity count has no benchmark. |
| No dedicated rollback opcode proves no prediction/extrapolation | Wire vocabulary alone cannot establish the client's execution or presentation algorithm. Correction handling and prediction require runtime evidence. |
| `1011` consists of six uniform 124-byte hero records | Superseded by `vainglory-mechanics-matrix.md` §19.1: later blocks are heterogeneous; the documented eid/team/position/HP mapping applies to the first record only. The earlier combat-pass section and ledger had retained the old interpretation. |
| `1010` is merely two floats / a movement acknowledgement | The local s2c field map documents a larger entity update with position and state (`vainglory-protocol-wire.md` §15.8). Do not conflate it with the short c2s `1012` coordinate order. |
| Emit `1053` type 6 as hero HP damage | The mechanics leaf's offline combat pass retires that reading and classifies it as a pool-related stream [Inferred]. Combat attribution uses corrected `1054` evidence. |
| Add a checksum field to stock `1011` packets | There is no verified checksum extension or stock-client comparison path. Put deterministic replay hashes in our own harness first. Changing a wire schema requires corresponding client support. |
| Every-tick state hashing is inherently infeasible | No measured state size/cost supports this. Choose checksum cadence from a benchmark and an explicit verification purpose. |
| `np.seterr(all='ignore')` prevents NaN/infinity | It suppresses handling of floating-point errors; see [NumPy's API contract](https://numpy.org/doc/stable/reference/generated/numpy.seterr.html). Use appropriate error reporting and explicit finite-value checks. Neither setting proves cross-platform determinism. |
| Fixed-point coordinates automatically preserve Vainglory behavior | Fixed point is an implementation choice whose precision and rounding still require validation against the stock client. A heap layout or placement grid is not a simulation precision contract. |
| Allow one fixed-point ULP in determinism CI | Approximation tests can specify tolerance separately. The deterministic replay check for the same rules and inputs must remain exact; do not weaken it to accept divergent states. |
| `.vgr` is a complete input-to-output simulation oracle | It supplies recorded server outputs and useful measurement fixtures. Re-simulation also needs the matching initial state, inputs, timing, and relevant rules. Feeding expected outputs back into a sim does not validate their computation. |
| Scoreboard-shaped `1113`/`1114` proves full-world catch-up | The documented scoreboard and the placeholder stub do not establish a complete world checkpoint. The brief also mixes `1014` and `1114`; late-join behavior remains an independent unknown. |
| Entity spawn must be a separate undiscovered opcode | Initialization is an unresolved sequence. It could involve setup, entity updates, templates, or several messages. Do not assume a dedicated spawn opcode or try neighboring opcode numbers without evidence. |
| Hero/skin selection certainly lives in JSON-RPC | The layer and ordering are unproven. Existing match-side ready/loadout observations also need to be accounted for. |
| Texture/VFX presentation will use our Unity client | Halcyon retains the Vainglory client. This language comes from the separate Veilbound design and does not describe the current project. |
| Copy the client's entity-memory stride into the server | Memory observations can identify fields but do not dictate our server's internal representation. Define authoritative state according to rules and required wire encoding. |
| Decoded kit/map data transfers directly into complete mechanics | Numbers and geometry are useful inputs. They do not establish ability resolution, path selection, aggro, or vision rules. A maxHP ladder does not establish an HP-regeneration curve, and the inferred pierce result must retain its measured attacker/context. |
| `HF_*` identifiers categorically violate this repository's IP rule | The root rules retain structure/constants, and the research router permits minimal identifiers for reproducibility. Veilbound's original-art naming discipline does not define Halcyon's protocol identifier requirements. Proprietary payloads/assets still stay outside the repo. |

The spike correctly provides a small deterministic Python reference exercise.
Its old docstring overstates equivalence with C#/IL2CPP; that claim should not
be used as evidence. Cross-process Python agreement cannot establish agreement
with another language, precision, compiler, or CPU.

## What to retain and the next bounded test

Retain the milestone order: establish match initialization, then one controllable
hero, one attack against a stationary target, followed by waves, structures, and
death/respawn. Each stage needs an accepted wire exchange and a deterministic
server rule. A no-fog or nearest-target experiment must be labeled approximate;
it cannot satisfy the project's faithful-gameplay gate. The proposed 1–2 week
estimate is unsupported while initialization remains unknown.

The immediate T1 lead is now narrower: determine whether our mobile `update`
consumer can transition from the captured `joinLobby` into pending-match handling.
The current local answers return an empty `returnValue` for `update`, with no
configured `joinLobby`, `queryPendingMatch`, `acceptMatch`, or `rejectMatch`
reply. This confirms missing scripted behavior, but does not establish which
state value or notification would make the client advance.
Inspect how it reaches `queryPendingMatch`/`acceptMatch`, if those paths remain
active. Use the third-party `isValid`/`responses` reads as hypotheses to validate,
not a complete response to paste into `answers.json`. Record the first accepted
transition or the specific missing evidence before constructing further state.

No client patch, server behavior change, or match experiment was performed in
this review. Public source inspection improved the next investigation; the
accepted mobile matchmaking exchange is still open.

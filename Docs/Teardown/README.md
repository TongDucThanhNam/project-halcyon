# Vainglory research — evidence from a shipped mobile MOBA

Vainglory 4.13.4 (build 147219) is a primary research subject: the first shipped
60 FPS mobile MOBA that simultaneously solved sub-30ms touch response, coherent
visual hierarchy and four-corner HUD zoning. The goal is to understand *how*
it was built, then apply those principles to Veilbound's own design.

This README is the router. Open exactly one leaf for the task at hand; a leaf
cross-links to siblings instead of duplicating them.

## IP boundary — read before using anything here

`PLAN.md` section `## Vấn đề IP` is binding. What transfers is **structure and
technique**: how many indicator states a shipped MOBA needs, how it groups
foliage into atlases, where it puts HUD clusters, how pretarget resolves finger
occlusion. What does **not** transfer is its art, shapes, colour choices, naming
or any asset.

Veilbound has its own visual language and its own discipline shape vocabulary
(`PLAN.md` -> `### Visual vocabulary`). Studying Vainglory extracts principles,
not parity or copied assets.

No Vainglory payload, texture, model, shader implementation or executable is
stored in this repository. Minimal identifiers and path fragments are retained
only where they make a structural claim falsifiable; they are never art or
generation-prompt inputs.

## Evidence labels (used by every leaf)

- **[Observed]** — read directly from a named artifact or a preserved
  measurement; the leaf names the tool or command that reproduces it.
- **[Rendered]** — decoded locally for identification only; no payload enters
  the repository.
- **[Inferred]** — design conclusion from observed evidence.
- **[Unverified]** — plausible, not established.

Negative results are recorded with the same discipline: a closed negative
names what was swept and how.

## Routes

### Product / UX principles

| Need | Open |
|---|---|
| Touch behavior, target arbitration, HUD/composition, visual hierarchy and claim limits | `vainglory-independent-audit.md` — start here for product/UX principles |
| Indicator/telegraph states, HUD cluster placement, foliage atlas and LOD strategy, asset tree naming | `vainglory-applicable.md` — structural decisions after the principles are understood |
| 3v3 game-screen anatomy — frame-pixel zoning with implementation mapping | `vainglory-3v3-ui-spec.md` — the mapping column is design decision, not evidence |

### The 3v3 map and how it runs

| Need | Open |
|---|---|
| Map identity, zones, blueprint taxonomy, navmesh format, **30-anchor placement table**, pipeline synthesis, rebuild playbook, key numbers, stuck-map | `vainglory-3v3-map-structure.md` — the map reference book |
| Container/chunk grammar, INST encryption wall, texture header codec | `vainglory-store-format.md` |
| How the runtime evidence was obtained; repeating or extending it; tool inventory and traps | `vainglory-runtime-reconstruction.md` |
| Why movement feels smooth: waypoint objects, pathfinding, locomotion clips | `vainglory-movement-anatomy.md` (§13) |
| Backend topology, live traffic windows, transport strings, smoothness synthesis | `vainglory-netcode-backend.md` (§14) |
| **Wire protocol** — the match connection itself: endpoint topology, frame grammar, obfuscation, traffic shape, capture playbook | `vainglory-protocol-wire.md` (§15) |
| **PC client internals** — PC menu reply shapes, friendListAll watchdog errors, date workaround, update/notify mapping | `vainglory-pc-client-internals.md` |
| **Mobile CE local-server test** — LDPlayer routing/TLS, verified menu, missing match-entry exchange after `joinLobby`, bounded investigation | `vainglory-mobile-local-stack.md` |
| **Implementation brief review** — VGReborn/HackedGlory source leads, rejected T1/T3 assumptions, and next evidence gate | `vainglory-implementation-brief-review.md` |
| **Mesh/skeleton rigging architecture** — how hero models were packed and rigged, and which techniques transfer to our own models | `vainglory-mesh-skeleton-structure.md` (§16) |
| **Mechanics matrix / 3v3 build bar** — what each gameplay domain still needs before an original 3v3 build can start; measured jungle timers; the remaining search plan | `vainglory-mechanics-matrix.md` |

### Artifacts and history

| Need | Open |
|---|---|
| APK/native/smali/container/path/public-infrastructure evidence, exact counts, commands and corrections | `vainglory-artifact-reproduction.md` |
| What was already attempted and why those avenues were stopped | `vainglory-dead-ends.md` — read before re-attempting binary RE or asset extraction |
| **Coverage audit**: how well each layer is understood (Measured / Shipped-complete / ceiling), and what remains open | `vainglory-knowledge-ledger.md` — the ledger owned by goal 014; carries the binding **Hiểu ≠ Làm** framing |

**Section numbers §13/§14/§15/§16 are inherited** from the era when movement and
netcode were sections of the map leaf; goals and research docs reference them
by that number, so the leaves keep it.

## Applied so far

| Finding | Where it landed | Record |
|---|---|---|
| HUD belongs in four corners with the centre kept clear | Corner assignment for all six clusters | `Assets/_Game/Tests/EditMode/HudLayoutTests.cs` |
| Ground indicators are shaders, not flat placeholder materials | `Assets/_Game/Art/Shaders/IndicatorRing.shadergraph` and `Assets/_Game/Materials/Indicators/` | `## phase3-ground-indicators` rounds 1-2 in `../workbench.md` |
| Measured map skeleton (bounds, outline, holes, 30 anchors) | `Assets/_Game/Map/map-layout.json` generated by `Tools/Teardown/build_map_layout.py` | goal 012 (closed) → goal 013 (active) |
| Determinism-first netcode shape (input-stream model; payload-measured ≈21 kbps down, ~6 B/s up, one 8–16 B frame per touch) | Reference input for the deferred multiplayer slice | `vainglory-netcode-backend.md` §2, §4; `vainglory-protocol-wire.md` §15.5; `../Research/veilbound-multiplayer-design.md` |

Open gaps: pretarget/selection has separate ally/enemy states; Veilbound still
has one selection state. The research is recorded in `vainglory-applicable.md` §2.

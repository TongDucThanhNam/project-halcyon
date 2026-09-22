# Ten-hour Classic 3v3 implementation run — 2026-09-22

User-requested work window: **11:55:53–21:55:53 Asia/Ho_Chi_Minh**
(`04:55:53–14:55:53 UTC`). Goal is a complete playable Classic 3v3 match,
with measured client behavior and regression checks. Zero bugs or official
parity is not promised. No images/video/FPS, no delegation, no commits;
unrelated pre-existing work is preserved. The bounded work window ends at the
deadline above; **complete official-like match acceptance was not achieved**.

Final handoff: repaired candidate15launches from immutable
`source-pin/scenario-source-gxn14mxg`, launcher23756/server24800, local
listeners7100/9443. Fresh Classic world/Skye265owner1500/native HUD entry is
qualified; no automated gameplay driver remains and server stderr is empty.
One late identified Google SignInActivity caused a retained setup failure;
bounded dismissal/readiness qualification recovered entry. No long-run native
validation of the final starvation/QA-overhead repairs was completed.
The owned crash watcher19928was stopped. Worktree/check evidence and concise
machine-readable outcome are in D:root`final-{diff_check,diff_stat,status}.log`
and`ten-hour-result.json`. No commits, images/video/FPS work or delegation.

Evidence and original dirty-source backups:
`C:/Users/terasumi/AppData/Local/halcyon-evidence/classic-ten-hour-4ebad0fde26d4fb7bc14998c35df550e/`.
The exact deadline, baseline processes and scope are in `run-state.json`.

**Evidence continuation:** after C: filled during archiving, new artifacts use
`D:/HalcyonEvidence/classic-ten-hour-4ebad0fde26d4fb7bc14998c35df550e/`.
The closed `classic-live-02` directory was moved intact (563 files,
423102791 bytes), with a junction preserving its old path. Nothing was
discarded. `classic-live-03-gateway-final.log` is on D:. The empty C:-side
`classic-live-04` is the interrupted allocation; the actual run is on D:.

## Checkpoint 1 — navigation geometry

- Reproduced the owned return-leg detour: **19.36597 units**, versus a
  **17.02884-unit** path in the same triangle corridor. An independent
  synthetic square-hole case also took 9.61693 instead of the analytic
  shortest 8.32456 units.
- Replaced midpoint/center visibility smoothing with deterministic integer
  portal string-pulling. A* corridor selection and exact collision checks
  remain; no fixed-tick change or copied mesh data.
- The existing traversal regression exposed an underlying diagonal-edge
  quantization stall. A separate single-triangle reproduction stalls even
  without funnel routing. Shared ordinary walk-step correction now chooses
  only a safe neighbour within two microunits and the existing movement
  budget. Hero and minion walkers use it; forced displacement still stops
  at the first wall without this adjustment.
- **62 focused tests pass**; all six existing production headless scenarios
  pass byte-identical comparisons in two independent processes. A further
  49 deterministic map traversals completed without wall entry or stalls.
  These are simulation checks, not client-smoothness acceptance.
- Patched local stack restarted. Fresh native-label entry identified a Google
  sign-in interception and a build/shop overlay; bounded native-state actions
  resolved both. Failed setup attempts remain retained, not gameplay failures.
- Both existing no-recorder movement runs completed: **14 inputs, 7,850 native
  samples**, owner verified as Amael 925/EID 1500/slot 0. Six declared short
  straight legs show **zero backward steps**. Five completed broader legs
  finish within 0.0000014 units of their accepted targets; two retarget windows
  are intentionally superseded. This samples logical entity position, not the
  model transform or general smoothness.
- All **40** owner position publications match adjacent authoritative ticks;
  no missing ticks, unmatched positions or zero steps while moving. Maximum
  lateness/work/start gap in these windows: **47.44/82.29/84.21 ms** with bots
  enabled. Logging cost remains excluded from work_ms and included indirectly
  in subsequent lateness; the peak warrants targeted production profiling.
- Fixed a trace-reader failure on Windows locale-encoded non-telemetry prose.
  JSON records remain strictly decoded; malformed records still fail.
  **21** timing/client-report tests pass. Evidence: `navigation-live/`, including
  failed analyses and final `*-analysis-v3.json` and `movement-ticks.log`.

## Checkpoint 2 — resource contract and implementation

- Strict offline decoding of the retained CE Flask PCAP completes in ~2 s,
  with zero incomplete frames/TCP gaps. Independent 1011/1076 state establishes
  levels 5 and 7, initial energy 270 and 25-per-level growth. Observed barriers
  255/325 agree with `115 + 35*(level-1)`; energy pulses agree with
  `max_energy * 0.30 * 0.3 / 5`.
- Following the identified 1053/1054 consumers qualifies read-only native
  HP, energy, barrier, fortified health, gold and XP access. Local level-8
  Amael reads HP/maxHP 1894 and energy/maxEnergy 450, agreeing with independently
  known growth; native gold 5802 agrees with active HUD text. The same accessor
  identifies how negative 1054 consumes barrier before HP. This is a concrete
  new anchor for resource validation, not an ARM hook or broad heap scan.
- Existing native Flask effect registration exposes the 0.3-second interval,
  metadata-indexed formulas and full terminal pulse. Production default-item
  ownership now routes through ItemManager: five-second barrier, 17 heal and
  energy pulses, 120-second cooldown, capped/wounded healing and lifecycle.
  Initial pulse phase relative to CE arrival timestamps is not yet qualified.
- Native negative 1054 consumes barrier, then fortified health, then HP. Fixed
  shared status-pool grants/refresh/expiry/reconnect and publication of the
  pre-pool damage amount, including fully absorbed hits. Structure protection
  now precedes pool absorption. No duplicate pool-depletion event accompanies
  a native damage event. Six resource-wire regressions cover these contracts.
- **100 focused tests pass**. All **seven** production headless scenarios,
  including new `healing-flask`, pass exact two-process comparison. A registry
  assertion still listed the original six scenarios; updated the exact expected
  set, then **24 runner tests pass**. No checks were weakened.
- Integrated read-only resource accessor independently matched level-9 native
  maxima and HUD gold. One bot match reached native Defeat at 19:24 and returned
  through FINISH to PLAY. Human only walked: not full human-match acceptance.
  All player K/D/A remained zero despite team kills; this is a new investigation.
- Resource/Flask-patched local stack restarted with the existing QA mailbox.
  Entry revealed a cached preview hero with no fresh 1118 selection; locks were
  correctly rejected. Explicit native-label Skye selection produced 1118 and
  allowed lock/loading. Failed setup actions are retained, not gameplay failures.
  Fresh Skye client trial `flask-live/trial-01/` passed **115 native resource
  reads**: ordinary 1096, 17 heal/energy pulses, 255 barrier then zero at expiry,
  HP 805.99994 vs server 806.0, energy inside the final measurement bracket.
  This accepts the measured resource behavior, not model animation or CE timing.

## Checkpoint 3 — wounded level-up desynchronization

- `flask-live/trial-02-hits/` correctly **FAILS** final client agreement. The
  shield consumed controlled 100/200 true-damage hits correctly (290→190→0),
  but client HP was already **42.54465 below the server before item input**.
  Original failed evidence remains; no PASS rewrite.
- Exact diagnosis: level 5 Skye HP 806/max 1214.2 becomes native 890.00535
  at max 1340.75, while Halcyon granted flat growth to 932.55. Native 1076
  consumer `c03f24 -> c56aa4` independently confirms percentage-scaled HP
  **and energy** growth. This is not inferred solely from the Flask test.
- `EconomyManager._level_frames` now requests native resource-ratio growth;
  item purchases retain their separate attribute/resource policy. Two new
  reproductions fail before the fix and pass after, including an item-boosted
  maximum. The prior multi-level test incorrectly assumed a constant missing-HP
  amount; its exact assertion now checks the native fraction instead.
- **42** level/corpus/economy/resource tests, **106** related combat/item/
  reconnect tests and all **seven** production headless scenarios pass.
  **24** nonvisual movement/Flask gate tests pass; a stale native resource
  baseline now stops before item input instead of contaminating the trial.
- Fixed QA damage receipts to distinguish actual HP loss from pre-pool wire
  damage; a fully absorbed hit must report zero HP loss. **35** QA/level-
  reconnect tests pass.
- Fresh patched stack `level-live/`: ordinary Flask plus disclosed 100/200
  diagnostic hits **PASS** in `trial-03-hits/`. Native barrier 150→50→0,
  actual HP losses 0/150, final native/server HP both 579.5. Earlier setup
  failures (omitted connection argument and overconservative fixed heal margin)
  are retained; neither submitted an item input. The fixture now reserves the
  exact level-dependent healing total; **26** nonvisual gate tests pass.
- `level-live/level-watch-1790057948527694600/` directly observes natural
  wounded level **3→4**, native/server HP error **7.3867e-7**, matching maxHP
  and energy within the native measurement bracket. The resource-ratio fix
  therefore has actual client evidence, not merely a deterministic-server PASS.

## Checkpoint 4 — native HUD counters and targeting qualification

- Native HUD ELF `957c98` reads kills/deaths from base attributes 41/42,
  assists from current resource 11 and farm from resource 14. Independent CE
  caches contain **30 kill + 30 death deltas** and **466 farm increments**;
  every inspected builder output matches those full scalar payloads exactly.
  All 466 farm increments join preceding last-hit deaths and spawned entity
  identities; observed classes include lane actors 365–368 and jungle 357–360.
- `1165` is not the KDA channel: its small integer fields include farm and
  net worth at five minutes, counter-jungle farm, turret deaths and scout uses.
  No fabricated 1165 has been added.
- Added authoritative kill/death/farm counters and delta publication to actual
  damage/death resolution, with reconnect restoration. Assist eligibility is
  explicitly unimplemented; not guessed. Read-only native score accessor is
  anchored to the same HUD consumer. QA exposes measured counters and the gap.
- The related suite reports **79 tests, OK with 8 skips** across scoreboard/
  corpus, QA, reconnect, lifecycle and resource gates. Skips are unavailable
  `vg_phaseB` lifecycle/objective fixtures, not failing checks. All seven
  production headless comparisons also pass (`scoreboard-headless/`).
- `scoreboard-live/native-score-1790059165280040700/` **PASS**: one ordinary
  1060 basic-attack input kills a disclosed stunned/1-HP target; native kills
  increment to 1. Diagnostic incoming damage increments native deaths to 1;
  natural respawn restores full HP with counters retained. A diagnostic lane
  last hit increments native farm to 1. This proves the measured counters and
  lifecycle, not an unprepared human-match win or assist correctness.
- The first targeted-input experiment failed correctly: camera lock was off,
  so after QA teleport the body tap produced 1012 into the old camera area.
  Pinned native preference getter `8f1f64/8f1f88`, owner accessor `9114dc`, and
  HUD callback `93b354 -> 9170cc` establish the saved preference and exact
  camera button. An ordinary owner-bound tap changed locked 0→1, enabling the
  successful attack trial. This is a setup fix, not a server movement repair.
  Shipped observer now reads that qualified toggle; no pixels, ARM calls or
  memory writes. Camera target/model transform measurements remain separate.
- Code review then exposed an omitted environmental death path: fountain
  damage originates in hero lifecycle, not `_deal_damage`. Added a failing-
  before/passing-after test and counted its death exactly once, without a
  fabricated hero kill. **43 scoreboard/QA/reconnect tests pass**.

## Targeted server-work profile

`profile-world-1790058473467551100/` uses the actual production Classic world,
five bots, navigation, waves, structures and jungle for 6,000 fixed ticks
(300 simulated seconds). With cProfile overhead included: 21.35 wall seconds,
29,871 frames, maximum profiled tick 12.49 ms. This is an accelerated CPU
diagnostic, not soak or smoothness evidence. Separately, 11,741 live ticks
in `level-live/movement-current.jsonl` peak at 21.33 ms. Earlier 82+ ms live
spikes remain unreproduced by this CPU workload; transport/logging/scheduling
effects are not ruled out. No speculative performance patch was made.

## Checkpoint 5 — ordinary abilities uncover a fixture-position defect

- Added pinned native cast/upgrade control accessors and a one-toggle camera
  guard. Existing `--mode client --scenario skye-a/b/c` now routes to the
  no-image/no-recorder path. It requires ordinary point-spending/cast inputs,
  attributed damage, native resources and same-process/match diagnostics.
  It explicitly does not claim a controlled compare-pair or model animation.
- `ability-live/skye-a-01/` passed ordinary rank-one A input/resource gates:
  30 ability hits, total published damage 566.000004, 59 native resource pairs.
  **Spatial acceptance is subsequently withdrawn:** the enemy's native
  logical position was not yet gated and differed from the prepared position.
- `ability-live/skye-b-01/` stopped on missing Target Lock; no B cast was
  attempted. A tap generated a movement order instead. Read-only native data
  explains why: server target `(4,38)`, native target `(15.323611,29.273438)`.
  QA teleport sent only 1070, whose collision-constrained correction need not
  reach a distant endpoint across geometry. This is not evidence of B failing.
- Native 1033 dispatcher `8283c4`, constructor `c07ad0` and consumer `c07b80`
  establish flag-zero relocation, distinct from correction and resurrection.
  QA now emits that relocation plus 1070, using barycentric surface height
  from the owned navmesh. Two-dimensional pathfinding remains unchanged;
  surface height is not asserted to be a model/feet offset. Ordinary gameplay
  dash/recall policies were not changed by this fixture repair.
- Both actor native X/Z positions are now mandatory before any combat input.
  The missing-relocation regression failed before the fix. **53** QA/native
  ability/height/recall checks passed (3 unavailable historical corpus skips),
  and **75** related navigation/movement/Flask checks passed. Fresh live
  relocation and A/B/C validation follows; no server-only acceptance claim.

## Checkpoint 6 — live A/B/C and Recall resource/position gates

Patched runtime `relocation-live/`, wire `wire-1790060910020700200.jsonl`,
connection `2269223528016`, Skye 265/owner 1500/slot 0:

- Native target placement now agrees: `(4,37.999992)` against `(4,38)`.
  `skye-a-01` stopped before casting because the bot moved 0.195 units between
  teleport and stun. Stun-before-placement removes that race.
- `skye-a-02` **PASS**, 30 ability hits and 59 paired native resource reads.
- `skye-b-01` obtained Target Lock/cast/three hits but failed an incorrect
  absolute-HP harness premise: enemy level 8→9 increased maxHP 1747→1891,
  while actual damage lowered its HP fraction. Final native HP1754.494141
  already agreed with server1754.494833. The gate now checks fraction reduction
  plus final scalar agreement; tests reject level growth without damage.
- `skye-b-02` **PASS**, 3 hits, 35 native resource pairs, lock-to-input533ms.
- `skye-c-01` **PASS**, ordinary native upgrade at naturally reached level6,
  20 pulses, 64 resource pairs, lock-to-input539ms. No forced levels/cast.
- Pinned native utility-item0 binding identifies Recall: callback `96eb98`,
  select handler `8c7a54`, command `919ed0 -> 91704c`, owner controller checked.
  Ordinary button center `(715,506)` emits `1041 ffffffff0500` for Skye.
- `recall-01` **PASS**: action, paired buffs, return after3.956s, native spawn
  arrival and HP/EP agreement, 98 resource samples. `recall-cancel-01` **PASS**:
  ordinary ground input cancels both buffs; no return, 91 resource samples.
- **36** movement/Flask/ability gate tests and **29** Recall/runner checks pass.
  UI utility-item2 opens the native shop through ordinary input; purchase and
  native inventory qualification are next, not yet acceptance evidence.

These are disclosed stationary/partial-resource diagnostic fixtures, not an
unprepared complete human match, controlled compare-pairs, model animation or
independent official timing fidelity. The earlier pre-relocation A resource
record remains spatially unaccepted.

## Checkpoint 7 — native inventory exposes stale bootstrap state

- Native `1085 -> c03188 -> c5c5c4 -> c72a18` identifies the owner's
  inventory component/slots; `c70fc4` and `c7175c/c71764` identify item and
  instance IDs. Ordinary Weapon Blade purchase in `relocation-live/` created
  native item458/instance2002 and +10 weapon bonus. No native memory writes.
- The same read exposed an extra 10% weapon multiplier, absent from the
  simulation. Source: three archived1052 records at tape8.517s for team1.
  `world_tape.authoritative_corpus_bootstrap` now omits only these exact
  records from the fingerprint-qualified live bootstrap. The archival file,
  allocations/cancellations, unknown tapes and ordinary live1052 are unchanged.
  This establishes local consistency, not official bot-handicap semantics.
- `shop-live/inventory-179006289639*` confirms fresh native base72, bonus0,
  multiplier0. **64** tape/level/QA checks pass, including byte-faithful rebuild.
- New ordinary `shop-purchase` client scenario checks input, exact debit,
  instance/component consumption, native inventory, bonus, total weapon power
  and gold. No QA preparation; item458 base purchase or item505 upgrade only.
  Native BUY binding `95c4a8`, detail owner `95c7b0`, selection/mode `95a9f4`.
  **54** shop/ability/Flask/Recall/runner checks pass; live shop trial follows.

## Checkpoint 8 — spawn axis/ownership defect

- Fresh native Skye at `(-77.03,-1.94)` disagreed with server
  `(-78.18,.88)` by about3.05 units. Its1011 reused the donor hero's position.
- Five bot spawn constants also incorrectly treated vertical Y (`1011+22`)
  as planar depth instead of Z (`+26`). Correct planar coordinates now use
  each canonical slot's measured X/Z, with height stored separately.
  `build_hero_block` publishes slot-specific XYZ for every selection, including
  donors/mirrors. Before the fix, mirrored team2 heroes could start on team1's
  side in the native client. This is an initial-state mismatch; general model
  smoothness is still not established.
- Regression failed before the fix in all five bot slots plus mirrored spawn
  publication. **91** spawn/roster/reconnect/QA/movement checks pass afterward.
  The old donor-prefix test's premise was corrected: slot XYZ must replace
  donor XYZ; all remaining measured prefix bytes are still checked.
- All seven production headless scenarios pass exact independent-process
  comparisons in `spawn-headless/`. This is not client acceptance.
- Fresh runtime `spawn-live/` includes both repairs and read-only QA combat
  attributes. Native live spawn/first-move/shop validation is next. An Android
  force-stop/task-removal race left a resumed activity without a process on the
  first launch; classified setup failure, not gameplay regression.

## Checkpoint 9 — fresh native spawn and ordinary shop pass

`spawn-live/`, ownerSkye265/EID1500/slot0, clientPID25181, connection2248951813456,
wire`wire-1790063582586161100.jsonl`:

- Before any walking, native XYZ is `(-78.180000305,1.267069578,.879999995)`;
  authoritative planar position `(-78.18,.88)` agrees. Native weapon base72,
  bonus0, multiplier0. The prior donor displacement and archived multiplier
  are absent on this fresh client.
- `shop-blade-01` **PASS**: ordinary controls,300gold debit, native458/2002,
  +10bonus and native/server total82. No QA preparation or forced gold.
- `shop-steel-01` **PASS**: natural earned gold,850upgrade debit, removal2002,
  native505/2003, total item bonus45, native/server weapon120.63 at level2.
- Concrete new presentation anchor: entity position setter `c58004` dispatches
  to entity+50 interface/vtable slot168. Observed setter`8ad524` leads through
  interface+20 to matrix object`27208a0`; translation setter`d7cce0` writes
  XYZ at+a0. The bounded read follows explicit pointers and agrees at rest.
  Its render consumption/model semantics still require qualification; do not
  relabel this initial binding as proven model smoothness.

General movement acceptance, resources/items, the full match lifecycle and
stability verification remain pending. Update this record with measured outcomes;
do not relabel partial tests as a complete playable match.

## Checkpoint 10 — baked-mesh mismatch and structure reach repaired

- Root model matrix accessor is now qualified through owned component/resource
  bindings, distinct from bone/camera/display state. `spawn-live/model-short-01`
  has2691 paired native samples over six ordinary inputs. One straight reversal
  (0.007954units) and corner arrival overshoot (0.434068units) remain measured.
- Owner path query and nav manager lead to870 native Detour-v7 tiles. All
  immutable geometry matches the owned4D562D63B9D0796F7FCC5EC61ADB111B asset.
  The prior server corner is inside its obstacle. Default production/scenario
  navigation now loads this baked mesh through a strict bounded parser.
- Correct geometry exposed minion center-range deadlock at a turret boundary.
  Qualified native target-radius formula/values now inform structure reach in
  hero/minion pursuit and basic attacks. Other point-target policies and
  ability radii are unchanged; official combat parity is not asserted.
- **118 focused checks PASS**, plus seven byte-identical headless comparisons
  in`detour-range-headless-01/`. Legacy raw-mesh route regression now explicitly
  loads its historical raw input; its exact assertions were not relaxed.
- Fresh runtime`detour-live/`, launcher26852/child21688, listeners7100/9443;
  stderr empty. Entry paused on an observed Google SignInActivity, dismissed
  with Back before resuming from the native-qualified mode panel. No blind
  retry, screenshots or video. Fresh walking measurements follow.

## Checkpoint 11 — fresh root-model movement and projection evidence

- `detour-live/model-short-01`:2692 samples, one0.007335 backward step,
  corner final error0.178484. Baked geometry alone did not fix corrections.
- Scoped normal-walk owner start/retarget/arrival1070 suppression now ships,
  with explicit arrival classification;78 related checks pass. Stops, forced
  displacement, pursuit, reconnect and other subscribers are unchanged.
- `anchor-policy-live/model-short-01` and`model-full-01`: **13 ordinary inputs,
  6855 native logical/root-model samples**, zero reversals on seven straight
  legs; all11 completed endpoints equal accepted targets, two deliberate
  retargets. No QA movement/resource preparation.
- Native camera binding/matrix projection recovered and integrated into the
  **same** movement scenario (`world_points`). Scalar-only controls, dirty/
  changed camera and off-screen/UI-region rejection;72 focused checks pass.
  One projected probe and three further world-point inputs succeed. Ground
  picker differs0.2766units on one slope; do not claim exact inverse mapping.
- A stale route was refused before input because the idle hero had died and
  naturally respawned. Native resources and death counter corroborate it.
- Clock-bracketed position comparison still measures up to0.4642units while
  moving around the short corner, and0.3664 on a retarget. Endpoints being
  correct does not close route/steering/latency fidelity. Timing artifacts also
  preserve an early68.3ms input acknowledgement and catch-up ticks.
- Current runtime launcher20172/child16896, client32696, ownerSkye265/1500/0,
  connection2506693987664, wire`wire-1790067585959317700.jsonl`. Native input
  failed after Google sign-in dismissal; normal HOME/task resume restored it.
  These bounded failures are setup evidence, not gameplay regressions.

Next work remains full ordinary gameplay/lifecycle and the measured moving
position mismatch. No general smoothness, official parity or zero-bug claim.

## Checkpoint 12 — native route oracle and archived turret barrier defect

- Public RecastNavigation v1.6.0 Detour, built only in the external
  `detour-oracle/` directory, reproduces the retained native five-point corner
  path to float32 precision and a second four-point path byte-exactly. Native
  `df09f8` uses one-unit surface-following steps and0.01 steering slop;
  `df0f78` advances along **3D** segments. Production still uses the fixed-point
  planar funnel. This is a concrete algorithm anchor, not a shipped route fix.
- The ordinary client reached native **Defeat /22:33 /FINISH**, with all six
  scoreboard rows, during a mostly-idle match with walking trials. This is
  natural lifecycle evidence, not a complete actively played human match.
- Explicit bounded `actor_states(eids)` observation now reads native entity
  positions, selection capsules and resource pools, with registry/lifetime
  checks. Turret maxHP agrees with the server, but dead outer turrets retained
  about600 native HP. Complete wire accounting found exactly2500 damage and
  six archived100-point barrier grants; an untouched middle turret reads
  HP3000/barrier600. The native-only pool explains the discrepancy.
- Fingerprint-qualified bootstrap now omits these exact60 archived grants,
  preserving the original tape, creations/cancellations, unknown tapes and
  live barrier mechanics. **21 tape/resource/Flask tests pass.** Fresh native
  verification follows; official turret-barrier rules remain separate.
- Evidence: `anchor-policy-live/structure-wire-audit-*`,
  `structure-resource-read.json`, native end-label record, and
  `detour-oracle/native-comparison-*`. Backups: `before-turret-barrier/`.

## Checkpoint 13 — ordinary combat exposes target and minion-health disagreements

- `classic-live-01/match-01`: fresh native readings confirm all ten turrets
  have expected maximum/current HP and zero barrier; both crystals have10000
  HP and zero barrier. This closes the specific archived-pool repair's live
  verification, not official turret rules.
- `classic-match` now runs through the existing client scenario entry point,
  with ordinary native-bound upgrades, purchases, movement, target selection,
  Barrage and Flask. QA is read-only; no forced gold, levels, damage or casts.
  Fresh-start gating distinguishes a full-match trial from explicitly labeled
  diagnostic continuations. All failed inputs/setup attempts remain external.
- `continuation-05` performed13 moves, two target selections, one Barrage,
  seven purchases and three upgrades, before a missing target-input gate.
  It is **not** a full-match pass. Native target weak-handle observation
  proves selection persisted across Barrage while server target becameNone.
  Selecting that same target can be deduplicated by native `9153f0`.
- Barrage now restores the retained target on completion/cancellation only
  if no newer order, Recall, explicit stop or death supersedes it. No new
  input/version is synthesized. A production regression failed before the
  fix;67 relevant checks pass. B's separate clearing behavior remains open.
- Native ranged minion4894 had475/475HP while server had735/735HP; a bounded
  typed census confirms native archetype365 base475 and366 base575. Server
  wave growth was never published. Spawn now emits an explicit base maximum
  setter followed by clamped health fill, without assuming native baseline.
  Reconnect retains its injury snapshot rather than refilling. The server's
  sandbox HP profiles are not asserted to be official gameplay values.
-90 relevant minion/spawn checks pass (three skips). All seven production
  scenarios pass byte-identical independent-seed comparisons in
  `combat-agreement-headless-01/`. This is not native or smoothness acceptance.
- Fresh `classic-live-02/` is being started with both repairs; qualification
  and full ordinary-match acceptance remain pending. Evidence/backups:
  `classic-live-01/minion-native-*`, `before-barrage-target/`,
  `before-minion-health/`, retained continuation journals and wire traces.

## Checkpoint 14 — live combat agreement and ordinary-input latency

- Fresh runtime `classic-live-02/` verifies native/server minion maximum/current
  health agreement, including720/412 melee and525/525,560/560 ranged actors.
  Native siege max1500 and current755.879883 agree with server1500/755.88.
  Barrage's prior hero target1517 is restored at3.186s after the ordinary
  cast, matching native selection without another1060. Later target death
  remains separate from restoration. General combat parity is not established.
- `match-01` from the opening minute failed its first enemy pick: ADB input
  arrived about300ms after projection while the camera/hero were moving, and
  the client sent1012 instead of1060. This was input timing, not a server
  target-ack defect. The failure is retained, not converted to a pass.
- New source-only `Tools/android/HalcyonInput.java` wraps the device's existing
  ordinary `com.android.commands.input.Input` class in a bounded persistent
  process. No game hooks, pixels, memory writes or protocol injection. Its
  source/dex/remote digest, sequential receipts and host/guest timings are
  preserved. `Tools/build_input_bridge.py` pins public D8/R8 8.3.37; all build
  outputs remain external. Optional `classic_match.input_bridge_dex` selects
  it within the existing scenario path; unknown receipt/timeout never retries.
- `continuation-02`: five selections, two A casts, one Flask,13 moves, four
  purchases and six upgrades.39 transport receipts below200ms have median
  27.17ms (including one no-input ping). Subsequent failure selected a different
  valid enemy in an overlapping cluster; ordinary lane policy now records any
  explicitly eligible native/server enemy, while exact-target tests stay strict.
- `continuation-03` hit an incomplete native UI traversal during fast shop
  close/reopen. Bounded read-only settling now requires two complete stable HUD
  trees, retains unknown reads and sends no repeated Back. No traversal limit
  was enlarged. `continuation-04` completed two further purchases afterward.
- A later low-HP minion selection raced its death: damage at1790073047.580948,
  input at.581189, death publication at.581526. No1045 followed. The lane policy
  can classify this narrowly observed wire/native death race as unacknowledged,
  never increment accepted-target coverage. Unknown/later deaths still fail.
- QA's64-row nearby window contained61 dead creatures at800.55s, masking live
  targets. Diagnostic ordering now prioritizes living actors, retains the bound
  and exposes total/alive counts. A failing regression precedes the fix;
  **49 QA/nonvisual Classic/input checks pass**. Runtime restart is needed for
  this QA-only change; no simulation/combat rules are changed by it.
- Input failures and all continuations remain diagnostic, not full-match
  acceptance. `classic-live-02/continuation-05` is pursuing the natural result
  screen; a new fresh full-lifecycle attempt will follow harness qualification.

## Checkpoint 15 — lifecycle/readiness races and longer ordinary combat

- Retained input correlation (`classic-live-02/input-transport-comparison.json`)
  measures host gesture submission → server-observed ordinary tap inputs:
  median221.72ms before the persistent wrapper,46.43ms and39.19ms in its next
  two trials. These are neither network RTT nor client-consumption latency.
- The last02 continuation selected living enemy4996, which the corpse-filled
  QA snapshot omitted from its eligible set. The living-first diagnostic fix is
  now active in fresh `classic-live-03/` (launcher9020/child12844, client14223).
- A fresh PLAY attempt at1790073388.516 had no native touch capture. Native
  resume completion was logged later at1790073401.472, then a further complete
  pause/resume ended3403.280. Foreground activity alone preceded native readiness.
  `Tools/android_input_health.py` now reads bounded, PID-specific existing
  lifecycle logs, rejecting unfinished/suspended/missing/stale resume states.
  A qualified later attempt entered successfully. This is an input-lifecycle
  guard, not proof that a touch reached a control or a frame-rate investigation.
  The Java initialized predicate is only a not-uninitialized check; the exact
  site dropping the earlier touch has not been independently observed.
- Native HUD appeared before first WORLD QA state publication; initial file
  creation now has a bounded read-only wait. Existing freshness, two progressing
  snapshots and process/session linkage checks remain unchanged.
- An occasional dirty camera matrix and the Level Up panel preceding its enabled
  upgrade control exposed further read/readiness races. The driver retries only
  those bounded read operations, keeps every unknown, refreshes actor positions,
  and still refuses wrong owners, invalid matrices or persistent absence. No
  input, native updater call, traversal-limit increase or fake success is used.
- **37 targeted setup/linkage/input/Classic checks pass.** An old linkage-only
  fixture was updated to supply the newer WORLD-qualification prerequisite; its
  exact bad-process/bad-match assertions remain. The initial missing mock import
  and old-fixture failures were corrected, not suppressed.
- `classic-live-03/continuation-04` has passed9minutes of current-world time and
  continues ordinary combat/respawn/upgrades/purchases. This remains explicitly
  a continuation following retained failed early trials, not fresh full-match
  acceptance. At531.1s owner K/D/farm is1/4/15; native HP agrees within float
  precision through death. Final lifecycle and structure-health gates are pending.
- Remaining movement finding: the retained native corner path is3.822384 units,
  while production's shortest triangle-funnel path is3.535199. Native one-unit
  surface steering, not only3D speed, remains a concrete differential target.
  The public Detour oracle reproduces the native path; no new production route
  algorithm has been shipped in this checkpoint.

**Clock correction (checkpoint19):** the earlier PLAY host wall timestamp and
NUO guest wall timestamp above cannot be directly ordered. Host-observed lifecycle
records from05 show ResumePost already preceded its failed PLAY by about2.3s;
the guest clock was offset by about16.6s. Foreground/resume is only a readiness
guard, not an established explanation of missing native input.

## Checkpoint 16 — sustained ordinary combat and receipt transport repair

- `classic-live-03/continuation-04` reached14 ordinary A casts,27 accepted
  selections,105 moves, eight purchases, eight upgrades and two Flasks before
  a Windows PermissionError opening an already-published QA snapshot receipt.
  `Tools/sandbox_qa.py` now retries **only that same receipt read** within the
  original deadline; no command is reissued. Transient errors are retained;
  permanent denial remains pending/unknown.57 related checks pass.
- `continuation-05` added13 casts,32 selections,40 moves, three purchases and
  two Flasks. It stopped when selection ack at1790074656.889481 was followed
  by owner death at.891374, clearing native selection. The lane exercise now
  separately records narrowly wire/native-confirmed acknowledged selections
  interrupted by death; they do not count as presented-target coverage.
  Unknown selection disagreement still fails.52 QA/Classic checks pass.
- `continuation-06` is running with these transport/classification repairs.
  These are still explicitly diagnostic continuations, not a fresh full-match
  PASS or a zero-bug claim. No game input is automatically retried.
- An external in-process public Detour oracle reproduces both retained native
  routes byte-exactly at float32.500 diagnostic random routes took median
  0.179ms among496 successful queries; four failed strict getPolyHeight checks
  and43 reached the native128-point cap. Native `df09f8` ignores that height
  call's status and initializes height to zero; live qualification of these
  edge cases remains open. The diagnostic DLL is **not** a production dependency
  or shipped navigation replacement. See`detour-oracle/library-qualification-*`.

## Checkpoint 17 — natural result, fresh trial and target-observation correction

- `classic-live-03/continuation-06` added38 moves,17 selections, nine casts and
  two Flasks before the natural22:29 Defeat transition. A transient native UI
  traversal failed there; a later stable tree has625 nodes and both Defeat and
  FINISH. All12 native structure HP values agree with final authoritative
  values within0.00127HP, and owner K/D/farm is4/11/61 in both. This is retained
  diagnostic end-state evidence, **not a retroactive full-match PASS**.
- `ClassicMatchExercise.fresh_ui_state` now retains and retries only bounded
  transition reads, without changing the1024-node bound or sending input.
  Persistent/unrelated failures still fail. The result wait has its own clock.
- Fresh D:`classic-live-04/match-01` reached670s with163 moves,58 selections,
  33A casts,11 purchases,12 upgrades and four Flasks. It stopped on a mistaken
  verifier premise: **1045 is attack start, not an immediate1060 selection ACK**.
  The selected enemy4878 died0.219s after the input, while the owner approached.
  Production `_apply_event` accepts pursuit without emitting1045; a regression
  proves that distinction. Ordinary policy now checks read-only authoritative
  target intent plus native selection, not an attack-start deadline. An intent
  that expires before this agreement remains unknown and does not count as
  accepted coverage. Exact prepared attack trials retain their strict1045 gate.
 27 related tests pass; the old failure and wire window remain preserved.
- Fresh baseline `classic-live-05` is running with this verifier repair. Its
  Android failed-to-attach launch and post-Google-sign-in missing PLAY touch
  were separately retained/recovered using qualified lifecycle/focus state;
  neither is labeled a gameplay regression. Native ResumePost alone is not
  proof of input delivery; the failed PLAY produced no native touch capture.

## Checkpoint 18 — scalable route comparison and isolated3D steering

- Added reproducible authored `build_detour_oracle.py`, `detour_route_oracle.py`
  and C++ query source under `Tools/Teardown/`. Public RecastNavigation1.6.0
  source digest and owned mesh digest are pinned; builds/assets remain external.
  No translated native function calls, hooks, packets, images or game writes.
- `native_path()` reads the code-anchored bounded query array twice. A120s
  passive window during ordinary gameplay retained585 reads, zero unknowns,
  median4.264ms/max19.653ms host RPC time. This overhead is disclosed.
- Initial44 unique array/destination pairs included four inactive retained
  arrays whose destination had changed on stop/respawn. Native `c60208` only
  advances paths with flag bit0; those are not valid current query pairs.
  Among39 active routes,38 reproduce exactly at float32; one differs only by
  `2.9802322387695312e-8` in one height coordinate. Original comparisons remain.
  Evidence: D:`passive-native-paths-1790075619316172100/`.
- A500-query diagnostic sweep reproduces native zero-initialized height fallback
  without errors;45 routes reach the128-point cap. These edge cases are **not**
  adopted as server policies. Optional `HALCYON_NATIVE_STEERING_LIBRARY` uses
  `server/native_steering.py` and fixed-point3D `HeroMovement` integration only
  when explicitly configured. Capped/partial/height-failure cases retain the
  existing planar policy with explicit counters. Default steering is unchanged.
- All39 retained active routes traverse through the production hero integrator
  to completion.76 initial focused checks pass. A sloped pursuit-budget defect
  in the experiment was then reproduced/fixed;12 related checks pass. Seven
  production scenarios compare byte-identically with the opt-in backend, and
  all seven also pass on the default backend. The first opt-in attempt failed
  because source pinning omitted the authored C++ input; that dependency and
  native observer/driver sources are now pinned, not bypassed. Canonical state
  includes surface waypoint heights and cursor height, excluding only native
  scratch pointers and diagnostics.21 pinning/timing/surface checks pass.
- Broader production traversal found an existing rounding defect: a valid
  partial step could leave an invalid remaining segment to its waypoint.
  A synthetic L-corner regression fails before the repair. `clamp_walk_step`
  now qualifies both segments before accepting a rounded point;59 focused
  checks pass. The ongoing500-route sweep checks actual within-tick waypoint
  segments, not an invalid straight chord across a consumed corner. Both
  diagnostic-premise and genuine-defect reproductions remain external.
- **Still open:** native live validation of opt-in steering, broad movement
  smoothness, full fresh ordinary-match acceptance, assists, six-client PvP
  and independent official fidelity. No test count closes these gates.

## Checkpoint 19 — complete traversal sweep, Suri selection and pinned live runtime

- D:`production-steering-500-1790077294261994900/`: all500seed227 routes
  reach their accepted endpoints through the production hero integrator.
  453use qualified3D surface paths;45explicitly fall back on partial/capped
  queries, two on height failure. The22.14s pass checks actual consumed
  waypoint segments, walkable rounded endpoints and the applicable movement
  budget;977micro-rounding bridges were needed. This is not client smoothness.
- Fresh05`match-01` retained237.15s of ordinary play:71moves,21selections,
  11A casts, three purchases, ten upgrades, two Flasks, K/D/farm4/2/10.
  Its failure was a valid enemy1518picked through an overlapping capsule,
  outside the policy's aim-search radius. Actual-pick qualification now uses
  all bounded known living enemies, while the smaller radius still chooses
  an aim. Exact wire identity plus native/authoritative selection is required;
  friendlies/unknown picks and missing inputs still fail.
- Prepared05`b-selection-01` observed native selection1517and targetHP1958.79187
  after B, while authoritative target wasNone before deliberate disengage.
  The B lifecycle now restores pursuit only if owner/target remain alive,
  recall has not started, no new target is set and order version is unchanged.
  Regression fails before the repair; superseding move/target/stop/Recall/death
  remains authoritative.76focused ability/steering/pinning/observer checks and
  seven opt-in production headless comparisons pass.05source changed during
  this diagnostic; it is not a clean acceptance pair.
- Source pinning now includes platform/runtime drivers and the authored C++
  query.06server and driver use the same immutable external snapshot; private
  assets resolve via`HALCYON_LOCAL_ROOT`. Diagnostics retain runtime root,
  navigation metadata, experimental switches and steering fallback counters.
  Workspace edits no longer silently change live provenance.59related checks
  pass.06ordinary fresh trial is underway with experimental steering enabled.
-06again lost its first PLAY despite a newly observed nativeResumePost. Button
  flags match successful runs; focus/channel/queues were healthy. A newly
  anchored read-only touch pipeline (`7f638c`, `188437c/18843c8`, `1884460`)
  qualifies app/callback/owner type and32bounded slots. One instrumented PLAY
  retained269reads,17active native queue reads and16UI-capture reads, then
  reached the mode chooser. Entry continued from that observed state, without
  repeating PLAY. Exact earlier loss site remains unknown. Evidence:
  D:`classic-live-06/touch-pipeline-1790078609289903800.json`.
- Open gates remain live steering comparison, post-fix B native selection,
  full fresh ordinary-match acceptance, assists, multi-client PvP and official
  fidelity. No image/video work or game-memory writes were used.

## Checkpoint 20 — measured pursuit publication gap and invalid-target repair

- Frozen06 ordinary `match-01` retained423.8s,117moves,36selections,
  22Acasts, seven purchases,12upgrades and three Flasks. It failed when the
  owner died106ms into a278ms ability swipe, before release; this was not an
  accepted cast. The verifier now classifies only wire/native-proven deaths
  overlapping the actual gesture as interrupted, never as successful casts.
  Prepared06`b-postfix-01` separately verifies native/server target1517 after
  Suri Strike. Runtime source provenance remained unchanged throughout06.
-06 native logical/root-model sampling retained8466samples, zero observer
  errors. Offline normal-walk pairing has2193moving unselected zero-correction
  samples across117orders: median gap0.05752,p95.16491,max1.56427units.
  Clock envelope1.28ms; nearest native sample at most25.2ms. The largest gap
  begins when server pursuit resumes after A but native navigation flags
  remain0: the native client moves only through periodic1070corrections.
  The next ground order inherits this disagreement. Tick lateness below1ms
  and work below11ms exclude a large scheduler stall for that transition.
  The other116order windows have maximum0.32343; this is diagnostic pairing,
  not a controlled before/after comparison or general smoothness acceptance.
- Default-off`HALCYON_PUBLISH_PURSUIT_INTENT=1` publishes accepted human
  pursuit routes through1016, plus stops at range/target invalidation; it
  does not manufacture simulation orders. Other clients retain corrections.
  The first07prepared probe lost its target to a pending projectile and is
  **not a qualified pursuit comparison**. It exposed a separate simulation
  defect: dead-target invalidation retained obsolete waypoints. That route
  now stops; its regression failed before the fix. Ground retargeting is
  covered against accidental overwrite by an experimental stop.
- The corrected07`a-pursuit-03` keeps the target alive and preserves its EID:
  24paired reads, nine moving server rows, **zero active native-navigation
  rows**, maximum2.28697-unit gap. Both actors and authoritative target intent
  remain valid. This is the clean publication-OFF diagnostic baseline; its
  harness and older server source snapshots are explicitly separate.
- A harness defect had silently replaced the chosen living enemy with the
  first enemy corpse during refresh; EID now remains pinned.28focused
  ability/setup checks pass. An overbroad scenario-client unittest run was
  interrupted, not counted as passing.39movement/publication/burst/Skye
  checks pass after invalid-target repair; all seven exact production
  headless scenarios pass with experimental steering/publication enabled
  (`pursuit-invalid-target-headless-02`). These are not client acceptance.
-08 first PLAY is now observed at Java dispatch as well as the native touch
  queue: neither receives the gesture; the owned Java view reports no window
  focus even though Android's global focused-window name matches the game.
  A subsequent bounded stable-view-focus qualification precedes a delivered
  gesture and native mode transition. This narrows entry loss upstream of
  Activity dispatch; it does not establish a universal cause or fix.
  Exact methods call their originals unchanged; no game-state writes.
- Ordinary Classic policy now covers A/B/C and completed Recall, with
  time-bounded target-lock and interruption checks. Fresh live qualification
  of that expanded policy remains pending.08 is the source-pinned publication
  ON comparison, not an ordinary full-match run. Assists, six-client PvP,
  full fresh-match acceptance and independent official fidelity remain open.

Evidence: D:`classic-live-06/normal-walk-correlation-1790079456391426200.json`,
`movement-divergence-01-{pairs,wire}.json`, `missing-cast-window.json`;
D:`classic-live-07/a-pursuit-01`, `a-pursuit-02`, `a-pursuit-03` and
`pursuit-harness-03/pin.json`; D:`classic-live-08/java-input-*.json`,
`touch-pipeline-*.json`. All paths use the D: root named above; old artifacts
are preserved. No images/video/FPS investigation was used.

## Checkpoint 21 — native movement command and speed are separate contracts

-08`a-pursuit-01` activates native navigation but fails the0.75-unit
  diagnostic bound (2.00467maximum) and clears native selection. Do not
  promote that1016experiment. The native consumer calls the selected-target
  clearing callback; this is a command-semantic defect, not timing noise.
- Native927c40→d05d08 identifies1017`[u8 actor,f32 X,Y,Z,u8 flag]`.
  Callbacka124e0 only clears the selected weak handle when the flag is zero;
  ARM instruction inspection confirms that branch. All2441017records in
  owned match6set the flag to one. The revised experimental pursuit publisher
  uses accepted3D destinations with that flag.09`a-pursuit-01` preserves
  selected target1517on all22paired reads and activates native navigation,
  but still fails with2.23282maximum moving gap. This is partial diagnosis,
  not movement acceptance.
- The new bounded speed observer follows nativec9ee8c/c772c8: attribute18
  plus typed descendants (type30in this process), with owner/parent/cycle
  bounds and no native game-function invocation.09has no speed-modifier
  component and native base3.70000005, while the server reports5.7throughout
  the probe. This independently explains a growing speed disagreement.
  Skye's2/.2directional bonuses remain simulation calibration policies.
- The owned corpus initializes persistent perk-control600(count1/four zero
  words); local08never published600. Default-off`HALCYON_NATIVE_SKYE_CONTROL`
  adds a separately measurable initialization experiment, with once-per-live
  lifetime and reconnect snapshot handling.10is testing it; no mechanical
  effect is presumed from the buff name.23focused Skye/publication checks
  pass; the preceding59checks cover the1017encoder, stronger native-selection
  gate, bounded diagnostics and setup contracts.
-09also isolated a host readiness condition: LDPlayer was minimized and its
  Java view lacked window focus. HOME/resume and a native-rectangle-qualified
  neutral touch did not restore delivery. Restoring and activating the exact
  owned host window changed view focus to true and delivered one PLAY.
  `Tools/android_input_health.activate_owned_ldplayer` now qualifies the
  executable path and unique window, restores/focuses it, then releases all
  temporary input-thread attachments. Its caller still waits for stable
  guest view focus before input.10reproduces the focus recovery. This is no
  image/video/FPS work and is not a claim about gameplay speed.
- A separate Android launch-state failure logged process removal/attach
  timeout. Force-stop→HOME→bounded explicit launcher start recovered it;
  no gameplay command was attempted in the failed setup. Source pins,
  failed Java guards and host-focus receipts are retained, not overwritten.

Evidence D:`classic-live-08/a-pursuit-01`, D:`classic-live-09/a-pursuit-01`,
`owned-corpus-movement-semantics.json` (its first1052interpretation is
superseded by`owned-corpus-movement-attributes-corrected.json`),
`java-input-1790082607297460500.json`, `host-focus-*.json`;
D:`classic-live-10/java-input-1790083075340714100.json`.
General smoothness, complete ordinary ABC/Recall match, assists, multi-client
PvP and independent official parity remain open.

## Checkpoint 22 — prepared pursuit native gate passes; fresh match begins

-10persistent600initialization leaves native speed at3.7 with no typed
  movement modifier; max gap2.11065. This hypothesis did not repair speed.
 11adds only authoritative Skye strafe bonus publication, using the identified
  native movement attribute18. Backward reduction, expiry and reconnect use
  the same bonus delta; equipment is separate. Equipment move-speed1052was
  also missing and now uses18.51focused checks and all seven exact headless
  comparisons pass with the experimental switches enabled.
-11`a-pursuit-01` has native base3.7+bonus2, retained target and max logical/
  root-model gap0.30195, but its full result remainsFAIL because the final
  cooldown check ran after the added pursuit diagnostic had outlasted it.
  The retained post-ability state already showed cooldown2.75and spent
  energy351.4725. The verifier now uses that pre-diagnostic state for
  expenditure, without bypassing native energy/damage/final resource gates.
  A new regression covers subsequent cooldown expiry/energy regeneration;
  another rejects logical agreement with divergent root-model state.
 17focused nonvisual ability checks pass.
-11`a-pursuit-02` **PASS**:23paired samples, nine moving server rows and
  nine active native-navigation rows; target1517retained; maximum logical
  and root-model gap0.25612. The living-target07baseline was2.28697 with
  no native navigation. Each runtime/harness snapshot is preserved. This
  qualifies the prepared post-A transition only, not general smoothness.
-12starts a fresh ordinary Classic exercise with the same qualified
  experimental navigation/publication/speed settings and all A/B/C plus
  Recall required. It uses ordinary Android input and read-only QA, no
  prepared gameplay state. A completed match has not yet been accepted.

Evidence D:`classic-live-10/a-pursuit-01`, D:`classic-live-11/a-pursuit-01`,
`a-pursuit-01-model-audit.json`, `a-pursuit-02`, `pursuit-harness-02/pin.json`,
`pursuit-speed-headless-03/summary.json`, and D:`classic-live-12/`.


## Checkpoint 23 — ordinary movement evidence and target-death input race

- Fresh12 ordinary gameplay produced83moves,20target selections, nine upgrades,
  five purchases, two Flasks and10accepted casts (A6/B3/C1), with natural kills,
  deaths and respawns. It stopped at roughly270sim seconds: a C target4706
  died121ms into a268ms swipe; the exact602lock was cancelled before release.
  No1042cast followed. Preserve the originalFAIL; this is not an accepted cast.
- A strict driver interruption classification now requires B/C, the exact
  owned602lock, matching1072death and1093cancellation during the gesture, plus
  native HP0 or native absence accompanied by wire1073destruction. Later death,
  unrelated cancellation, living native target or unqualified absence cannot
  excuse missing input. No retry, cast count or successful-ability claim follows.
 37nonvisual Classic checks pass. The next policy also deliberately performs
  one ordinary Recall at its first safe non-base opportunity; all completion
  gates remain, with no prepared state or artificial gameplay outcome.
-12retained5377native logical/root-model samples. All83walk windows contribute
 1531qualified pairs: median gap0.06347,p95.17997,max0.24957units. Envelope1.69ms,
  nearest sample26.49ms. This is a retained failed-run diagnostic, not general
  smoothness, official parity or a controlled cross-run comparison.
- The reconnect/level/multiplayer/same-hero21check run exposed two obsolete
  multiplayer premises requiring recurring owner1070updates. They now verify
  the accepted1016intent and the remote subscriber's position stream in both
  directions; combat/reconnect checks remain. All eight multiplayer checks
  pass, plus the bounded join follow-up and a new six-connection roster/motion
  check. The latter verifies six attributed intents and five remote position
  streams at every subscriber; it is not six rendered-client acceptance.
-12entry established a second focus cause: an owned Java sign-in-error dialog
  covered the game, while global activity focus still named it. Accessibility
  XML identified its exact text/package/OK bounds; one ordinary dismissal
  restored Java focus and PLAY delivery.13uses the same strict text/identity
  guard, not historical coordinates. Host activation alone is insufficient.
-13uses a new immutable runtime/driver pin for a fresh ABC/Recall exercise.
  No image/video/FPS work, delegation, commits or discarded failed evidence.

Evidence D:`classic-live-12/match-01`, `missing-c-gesture-window.json`,
`normal-walk-correlation-1790085008603428200.json`, `sign-in-failure-dialog.xml`,
`gateway-segment-final.log`; root `multiclient-contract-02.log`,
`multiclient-contract-bounded-03.log`, `six-client-movement-02.log`;
D:`classic-live-13/pinned-runtime.json` and its source-pin directory.


## Checkpoint 24 — bounded HUD reads and an unresolved native-position hold

-13completed two ordinary Recalls,38moves,10targets, six upgrades, two purchases
  and six casts(A4/B2). At115.7sim seconds the verifier's HUD guard performed
  a second direct UI traversal, bypassing its already-qualified bounded reader.
  That read failed with cycle/node-limit unknown; the FAIL remains preserved.
  Four subsequent input-free native reads returned complete594/604-node trees.
  All Classic HUD guards now use the bounded reader, without increasing1024
  nodes, accepting an empty/unknown tree, or repeating input.59relevant checks
  pass.14is the fresh source-pinned run of this harness repair.
-13walking:38orders,2101native samples,705qualified pairs, median gap0.06888,
  p95.15587,max0.48321. The largest interval contains a100.96ms exact native
  logical/root-model hold with navigation active and correction time zero,
  followed by about0.672planar units advance. Nearby server ticks remain timely and
  no owner1070appears. First-wave minion publication coincides; causation is
  unknown, so no speculative publication/asset change was made.
- Reusing the independent CE native corpus offline finds one111.82ms exact
  active/zero-correction logical hold in its short run and none in the broad
  run. Different hero/latency/scene/sample period and missing reference model
  data prevent equivalence or smoothness acceptance. This is actor-state
  measurement, not a frame-rate or image/video investigation.
- For14, ordinary HOME preceded force-stop; absence of both owned PID and
  activity records was verified before stopping/restarting the server. The
  first subsequent launch entered successfully. This one reproduction is a
  better startup ordering, not proof of a universal Android task-removal fix.

Evidence D:`classic-live-13/match-01`, `post-failure-ui-state.json`,
`post-failure-ui-observer{.jsonl,.metadata.json}`, `post-recall-walk-gap.json`,
`normal-walk-correlation-1790085812892660400.json`, `orderly-client-stop-*.json`;
root `reference-active-position-holds-1790086111306192600.json`;
D:`classic-live-14/pinned-runtime.json`, `process-launch.json`, entry receipts.

## Checkpoint 25 — thirty-minute ordinary trial and long-run diagnostics

-14fresh ordinary trial reaches its30-minute cap without a client crash or
  server stderr, but no native result screen: **FAIL remains**.416moves,
  94targets,12upgrades,12purchases,10Flask inputs,51accepted casts(A19/B16/C16),
  20completed Recalls and seven interrupted/uncredited casts are retained.
  Same server source digest at startup/current; no prepared gameplay state.
-2,506QA/native resource pairs have zero K/D/farm mismatches; maximum max-HP
  error0.00009766 and max-energy error0. Current HP/energy reads are not atomic.
  Two earlier largest HP discrepancies are bracketed by matching wire damage,
  not evidence of persistent HP drift. Assists remain unimplemented.
-35,653native logical/root-model samples,416walk windows and7,768qualified
  moving pairs: median0.08155,p95.22013,max0.88924units. Root-model p95.22048.
  The peak coincides with113.48ms tick work and catch-up; native samples keep
  advancing, correction time is zero and no owner1070is present. Do not call
  this a native hold or extrapolate general smoothness.
-36,015instrumented ticks have median work14.05ms,p95.38.03ms,max182.38ms;
  lateness median.875ms,p99.28.03ms,max288.01ms. Median start interval49.996ms.
  No untraced baseline exists. Read-only request-glob benchmarking finds
  5.59ms median over2,767QA entries versus.35ms over180entries. This is one
  overhead contributor, not complete attribution. New opt-in per-phase timing
  separates QA,wave,bots,heroes/effects,economy;33relevant checks pass and a
  controlled clock proves attribution without changing authoritative state.
  It is not retroactively present in14's immutable running source.
-16of21observed Recall starts returned with full HP/energy and six Heavy
  Steels, only because surplus gold exceeded the policy threshold. The driver
  now shares its affordable supported-purchase decision with Recall; first
  coverage/resource recovery remain. No live memory or runtime source change.
-Late`continuation-01`uses that corrected policy but cannot claim fresh-match
  acceptance.50more moves,fiveABCcasts,oneRecall,then missing1096Flask input:
  authoritative owner death precedes its tap33ms. Native consumption at that
  instant was not separately measured. The subsequent driver checks native
  liveness after reading the control and skips an already-dead owner without
  counting/retrying input.41Classic tests pass. OriginalFAIL preserved;
  `continuation-02`is another explicitly late diagnostic, not acceptance.

Evidence D:`classic-live-14/match-01/client-result-1790087635.json`,
`gateway-segment-through-match-01.log`,
`normal-walk-correlation-1790087736608494100.json`,
`largest-walk-gap-window-1790087941612787700.json`,
`final-tick-timing-1790087735738738400.json`,
`final-resource-counter-audit-1790088080386996000.json`,
`recall-policy-audit-1790087624832030400.json`,
`qa-directory-enumeration-1790087800057579600.json`,
`continuation-01/flask-death-window.json`, and continuation driver pins.

### Measured diagnostic scalability repair

The Windows QA request enumerator now asks the filesystem for only
`command*.json`, using the documented
[FindFirstFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findfirstfilew)
and [FindNextFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findnextfilew)
contract. It rechecks long-name matching to exclude DOS/short-name artifacts,
closes enumeration handles, distinguishes no matches from I/O errors, and
retains sorted execution, eight-command capacity, durable consumed markers,
at-most-once behavior and regular-file/schema validation. Other platforms
retain the existing glob implementation. No receipts are deleted or moved.

An interleaved100-sample read-only benchmark on14's3,304-entry live mailbox:
old median5.4177ms/p95.7.6625ms, production replacement median.2314ms/
p95.4356ms. The earlier cached-prototype figure.0791ms is not the integrated
result.47QA/timing checks pass, including matching candidates, malformed
files/directories, batch limits, replay prevention and I/O-failure behavior.
This is a measured operation-level overhead repair, not whole-tick speedup
or client-smoothness acceptance. The immutable running14source is unchanged.
Evidence:`classic-live-14/qa-request-enumeration-qualified-1790088322229834700.json`.

### Qualified candidate settings (not plain-default acceptance)

The native-qualified14runtime uses the pinned public Detour library plus
three explicit experimental switches. A plain launch without these switches
does **not** reproduce this candidate. Keep evidence/QA outside the checkout:

```powershell
$env:HALCYON_LOCAL_ROOT = 'D:\Games\project-halcyon\Local'
$env:HALCYON_NATIVE_STEERING_LIBRARY = 'D:\HalcyonEvidence\classic-ten-hour-4ebad0fde26d4fb7bc14998c35df550e\detour-oracle-reproduction-01\detour_route_oracle.dll'
$env:HALCYON_PUBLISH_PURSUIT_INTENT = '1'
$env:HALCYON_PUBLISH_SKYE_SPEED = '1'
$env:HALCYON_NATIVE_SKYE_CONTROL = '1'
.venv\Scripts\python.exe -B -u -m server.platform.local_stack --bind-host 127.0.0.1 --match-host 127.0.0.1
```

Do not start a second stack on the occupied ports.14's immutable source pin
and process receipts identify the actual long-run build; the checkout also
contains later driver/timing changes.600control's speed hypothesis failed;
it remains enabled here solely to reproduce the qualified configuration.
General smoothness, complete fresh-match acceptance, six native clients,
assists and independent official parity remain open.

## Checkpoint 26 — sustained overload starves received input

-Second late continuation reaches42.6sim minutes, then fails waiting for1016.
  Unlike the preceding Flask case, its1012**was received** at1790088399.236147.
  Owner was alive at spawn, with no CC. The same destination's owner1016later
  appears at1790088408.113425, **8.877278seconds** after server receipt. This
  is server-observed publication delay, not RTT or client-consumption timing.
-Retained tick rows show20.4seconds of scheduler lateness,61–116ms work and
  rapidly growing native-steering fallback counts. The production loop's
  unbounded catch-up batch postpones `_pump`until it reaches the stale outer
  deadline, allowing queued input to wait seconds under sustained overload.
  DriverFAIL is retained; its51moves,sevenABCcasts and oneRecall are diagnostic
  continuation coverage, not full-match acceptance.
-The loop now services queued input after at most four catch-up ticks. Every
  authoritative tick remains50ms; no drops, variable-dt or speedup. Controlled
  120ms-per-tick production-loop reproduction fails with the cap removed:
  input queued at tick10is applied ten ticks later. The repaired loop meets
  the four-tick bound;34timing/publication/burst checks pass. This is not a
  wall-time guarantee under arbitrary tick work or a fix for overload itself.
-14client was ordinarily sent HOME, force-stopped and verified absent before
  stopping its owned stack. Final gateway evidence is archived.15launches
  from a new immutable source pin containing the batch cap, phase timing,
  QA enumeration and latest driver fixes. Entry uses the same bounded native/
  accessibility guards, no screenshots or gameplay-state preparation. This
  handoff restart is not a replacement for a long native regression trial.

Evidence14:`continuation-02/{missing-move-ack-window,delayed-owner-move-ack}.json`,
`gateway-segment-through-continuation-02.log`, `gateway-segment-final.log`,
`orderly-stop-*.json`; root`catchup-starvation-pre-fix-1790088575608077700.log`;
15:`pinned-runtime.json`, `source-pin/scenario-source-gxn14mxg`, entry receipts.

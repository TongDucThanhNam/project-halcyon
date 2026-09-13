# Solo sandbox acceptance record

## Current reading order — 2026-09-13

Start with [current status](current-status.md) for the latest implementation,
dependency and acceptance summary. The September 8 missing-Skye-kit and
projectile findings below are historical defects: repairs and bounded live
observations followed. The [scenario record](solo-sandbox-scenarios.md) carries
the stricter September 12 fixture-gated A/B/C results and the finite negative
minion-to-structure observations. Those results do not close all seven gates,
establish two-client game acceptance, or prove independent gameplay fidelity.
The 758-test baseline below belongs to its recorded September 8 source; it is
not a test result for later revisions.

## September 9 implementation and observation record

Updated 2026-09-09. This tracks the operator's seven-subsystem **Tier 1 solo
sandbox** definition. It is distinct from the architecture's T1 platform RPC
tier. The target is one controllable hero in Halcyon Fold, with the complete
specified gameplay loop, all seven client acceptance scenarios, and at least
250 passing tests. **Historical defect repair & live verification status:**
The operator's 2026-09-08 Skye test disproved an overly broad completion claim:
Skye initially had no registered ability kit (ten 1078 requests received zero acks),
ordinary basic attack projectiles lacked visual bullets (emitted only 1045
without native 1037 projectile releases), and lane minions moved only once
upon spawn without subsequent 1016 path updates.
On 2026-09-09, defect repair and live verification proceeded on our unchanged
owned Android CE client against the local authoritative server:
Basic attack projectile visuals are repaired and verified live: native 1037
targeted projectile creation emits alternating LeftGun/RightGun sockets and kind
108, with visible bullets and impact flashes documented via resampled illustrations
(frames 49, 50, 57, 79 from original 11.7fps 30s `skye-basic-attacks.mp4`); perfect
native fidelity for all hero profiles is not claimed. Gate 2 is closed.
For Skye's kit (Gate 3), original upgrade allocation is repaired: client 1078
requests for A, B, and C receive 1082 acks in trace `wire-1788942557949012000.jsonl`
(A at `1788942770.4508677` / `1082.452012`, B at `1788942803.1498234` / `1082.151304`,
C at `1788943185.216853` / `1082.226975`). In the subsequent trace
`wire-1788947055923739400.jsonl` (connection `2607844752976`): A Forward Barrage
`c2s 1042` action 0 at `1788948535.097593`, outgoing `1054` victim `1517` /
attacker `1500` −25.82 at ~22 min; B Suri Strike `c2s 1042` action 2 at
`1788947918.1802444`, `1054` −232.686 and −46.537; C Death from Above `c2s 1042`
action 4 at `1788947922.5289133`, repeated `1054` −21.153. All casts via real ADB UI;
QA prepared positions only. Bounded A/B/C operations and authoritative damage are
verified. Repeatable gameplay acceptance, native B trajectory/smoothness, C reconnect
actor recreation, and independent official fidelity remain OPEN. Gate 3 OPEN/PARTIAL.
For lane waves (Gate 5), continuous 1016 movement order re-issuance was verified
(16-22 orders/actor across first 25s in `wire-1788894917131102000.jsonl`;
2557 order snapshot in `wire-1788942557949012000.jsonl`). Short operator recordings
illustrate directed locomotion: fresh 30s `skye-basic-attacks.mp4` and 45s
`skye-combat-verify.mp4`; `halcyon_gate5_wave.mp4` is an older >2-minute recording.
Late-match wave accumulation was observed in botless runs; whether it represents
an abnormal defect versus expected backlog requires reference-backed evaluation.
The `wave.py` targeting-guard modification was **reverted** by its own worker; a
new 17-line regression in `server/test/test_wave_sandbox.py` protects the guard
(76 focused wave/structure tests pass in 1.906s, `wave.py` is at clean HEAD). The
earlier wave-only 110→87 comparison omitted production nav and turret steps and is
not a production buildup fix. Gate 5 remains OPEN/PARTIAL.


Broader kit fidelity (Skye C reconnect actor recreation, strafe policies),
unsupported roster kits (10 implemented heroes), and full PvP/brush FoW remain
explicit boundaries.
The [seven-gate checklist](solo-sandbox-acceptance-status.md)
links each manual observation; broader native timing and kit fidelity limits
remain explicit in the subsystem leaves.

## Scope and evidence

| Subsystem | Implemented behavior | Requested client acceptance evidence |
|---|---|---|
| Navigation | External A001 mesh, integer A* and collision clipping, thin-wall dash query, dynamic speed, CC movement interruption | Catherine routes around the wall; moving Gwen stops under STUN. |
| Basic attacks | Windup cancellation, committed release, recovery movement, 22 u/s ranged projectiles, attack-speed scaling, native attack groups | Two Celeste minion sequences show attack-to-retreat motion and retained damage after changed positions. |
| Abilities | Four geometric queries, energy costs and regeneration, delayed effects, channel interruption, named rank curves | Gwen line/cone, Celeste delayed area and Taka vector-through; energy spending/empty-energy blocking; Ringo completed channel versus STUN interruption. |
| Shop and items | Native registry IDs, location checks, recipes, required actives/passives, immunity/wound/fortified health | Bounded matrix scenario met: native purchase/activation, 5.9 versus 3.9 u/s, blocked stun and Aftershock hit |
| Lane and structures | Three melee/two ranged waves, periodic siege, growth, ally protection, heat ramp, backdoor protection, full chain unlock, shared compact actor slots | Isolated ranged minion visibly fires from behind melee; turret switches from a living minion to the attacking hero and ramps damage; crystal destruction reaches Victory. |
| Jungle | Neutral camps, leash, weapon/crystal buffs, timed Gold Miner/capture reward and Kraken siege simulation | Natural Treant kill grants three subsequent attack-burn ticks; full Gold Miner pays 300 to each ally; naturally timed Kraken captures, marches and destroys structures. |
| Lifecycle | Four-second Recall/refill, base healing, enemy fountain damage, dynamic respawn and full native death/return sequence | Bounded matrix scenario met: visible standing hero, full pools and actual post-revival movement |

Subsystem details and remaining rule calibration are recorded in
[abilities](solo-sandbox-abilities.md), [items](solo-sandbox-items.md), and
[match ending](solo-sandbox-match-end.md). Navigation and performance evidence
are in [navigation](solo-sandbox-navigation.md) and
[production verification](solo-sandbox-performance.md); current reconnect
behavior and limitations are in [reconnect](solo-sandbox-reconnect.md).
Further measured corrections cover [attack actions](solo-sandbox-attack-actions.md),
[camp respawns](solo-sandbox-camp-respawn.md), and
[hero revival](solo-sandbox-hero-respawn.md).
Geometry and spawn inspectors read
the operator's external client store/corpus. No mesh, captured packet payload,
texture, model or executable is added to the repository.

## Authoritative integration

`SnapshotStream.advance_simulation` owns 50 ms ticks. Wall-clock scheduling
selects when to execute a tick, not its duration. Movement, projectiles,
abilities, items, ecology, structures and economy share match time and one
damage-resolution path. Hero ability queries include lane and jungle creatures.
Released shots remain committed after a move order or attacker death.

`server/test/test_sandbox_simulation.py` exercises the production session:
mitigation and one client HP change per hit, ranged commitment after movement,
shop gating plus active speed, neutral-target abilities, Aftershock consumption,
recall completion/cancellation, channel interruption, and repeated byte-identical
wire streams. These are integration checks, not substitutes for device acceptance.

Positions use integer millionths of a world unit. This refines the older
millimetre design to keep narrow mesh portals stable under quantization.
Same-runtime repeatability is tested; a cross-language/architecture equivalence
claim still requires the planned port comparison. Unspecified balance values
remain explicit policies in the subsystem rule definitions.

## Corrections to the previous scaffold

The current work uses independent captured exchanges and native registry
structure to correct several premises:

- `1054` begins with **victim, attacker**, then signed damage. Emitting another
  `1053` HP subtraction for the same hit would damage the client twice.
- `1053` resource discriminators are HP `0`, energy `2`, gold `6`, XP `8`.
  The former type-6 "HP" updates were gold. The economy emits the measured
  resource channels; it does not duplicate the old keepalive gold/XP pair.
- `1078 [slot][5 zero bytes]` upgrades UI slot 0/1/2. Accepted `1082` and
  actual casts `1041`/`1042`/`1102` use native action ordinals. Catherine's
  A/B/C/Recall are 1/2/3/5; Ringo's are 0/1/2/4. The former universal slot-3
  Recall and UI-index cast assumption selected the wrong Catherine actions.
- Hero and equipment numbers are manifest-registry IDs. Ringo is `243`,
  Adagio `244`, Koshka `245`, Amael `925`; `924` is Viola. An unsupported
  hero is not assigned an unrelated kit.
- `1010` starts with an archetype ID, class, and new actor EID. Its byte
  at `+116` is a compact actor slot, also used by `1016`; it is not a
  freely wrapping event counter. Heroes, static actors, lane and jungle
  creatures share one allocator; slots are released after actor removal.
- Hero death is `1072` victim/killer attribution plus `1075` countdown, then
  `1073` corpse hiding while retaining the actor/slot. `1033`/`1070` relocate
  the still-dead hero shortly before the deadline; `1074` completes revival.
  The old `1162` death timer was an initial hero timer, and the old corpse
  "state" was visibility data.
- Lane minions also emit `1072` on death. All 83 measured removal chains
  retain the corpse for approximately 3.8 seconds before `1073`/`1035`.
  The shared actor slot stays occupied throughout that interval.
- Targetless item activation is `1096` with an owned item-instance ID;
  ground item input is `1098`. Buff add `1086` contains a half-precision
  duration, instance and native kind; it is not an attribute keepalive.
- Natural turret deaths retain zero-HP actors. The former generic despawn
  chain belonged to an objective locator, not a turret. Crystal destruction
  emits `1106`, with `1009` winner/reason about six seconds later.

## Local verification

```powershell
python -B -m unittest discover -s server/test
python -B -m unittest server.test.test_sandbox_simulation
python Tools/run_scenarios.py --mode headless --scenario all
$env:HALCYON_NO_BOTS = '1'
$env:HALCYON_TRACE_WIRE = '1'
$env:HALCYON_EXPERIMENTAL_CAPTURE = '1'
python -B -m server.platform.live_up
```

`Tools/run_scenarios.py` is the repeatable verification pilot: the named Skye
and minion/turret scenarios run through the production simulation in two
seeded independent processes and are accepted by exact event/state byte
comparison; `--mode client` drives the implemented rendered-client path
(mock-tested, live execution pending). Commands, result schema, failure-stage
interpretation and the demonstrated status are in
[the scenarios leaf](solo-sandbox-scenarios.md). The sixteen-minute
`Tools/verify_sandbox.py` coverage/deadline gate is unchanged and separate.

Start LDPlayer before running `live_up`. The command starts the server in the
background and restores guest loopback routing, TLS trust and ADB reverse
ports. Emulator restarts clear that routing, so the normal startup command
must include guest setup. Close and reopen Vainglory after it reports ready.
Enter **PLAY → SOLO BOTS → 3V3 → VERY EASY**, select a supported hero, lock in,
and choose **Manual Build**. Bot AI is disabled by the setting above; lane and
jungle creatures still run. The capture setting enables the verified local
Gold Miner/Kraken ownership presentation. Follow the mobile-local-stack leaf
for first setup details.
Traces and screenshots are written outside the repository under
`$TEMP/halcyon_stack/`. `wire-*.jsonl` captures local gameplay packets for
client failure diagnosis; session-token frames are excluded.

The recorded full suite passed **885 tests in 132.465 seconds (2 skipped, exit 0)**
on 2026-09-11, after the wave-guard revert, its regression, the scenario pilot
and the live client validation landed; the complete output is external at
`%TEMP%/halcyon-scenario-pilot-20260911/full-suite-20260911.log`, and
`git diff --check` exits 0 on the same worktree. This count is evidence, not a
definition of faithful gameplay.
The earlier two-process 960-second pair reproduces identical
wire, canonical state and all 960 checkpoints. Both workers pass every 50 ms
deadline, with maxima of **14.6694 and 15.5164 ms**, and complete all coverage
requirements, including two Recalls per run. Historical 758-test / 960-second
replay pins represent an earlier source baseline prior to operator Skye defect
testing, not current-source verification. See the performance record for exact
source pins, failed attempts, repairs, coverage and measurement limits.

The first integrated Adagio device run crashed after build selection. A later
trace exposed a server exception from attaching Arcane Fire state to a slotted
lane minion. That defect is fixed and regression-tested. The next device run
rendered the HUD and moved Adagio to the shop, then crashed alongside an immediate
minion removal. The server continued running. The native corpse-lifetime repair
and reconnect corrections passed their tests afterward. A subsequent natural
25:57 match reached the visible Victory screen on one continuous connection
after the turret-removal correction. Later client checks demonstrated buying
and activating Sprint Boots, visible native Recall channel/return effects,
hero level progression and nearby enemy visibility/targeting. The later Gwen
run closed the bounded navigation, item and lifecycle matrix scenarios and
reached visible 19:13 Victory after natural Gold/Kraken schedules and prepared
low-HP captures. Celeste subsequently demonstrated delayed ground damage.
The final Celeste, Gwen, Taka and Ringo sessions close line/dash/channel,
minion stutter, turret retaliation, ranged formation and Treant-burn checks.
Range-boundary, Celeste basic-damage and NPC attack presentation repairs are
included in the recorded 758-test run. Final performance results are tracked
separately above and in the performance leaf.

The earlier failing trace is external at
`$env:TEMP/halcyon_stack/wire-1788784234892652800.jsonl`. The read-only
`Tools/Teardown/inspect_live_actor_order.py` reports zero creation/slot/reference
errors on its original connection and twelve position-before-creation errors on
the old reconnect path. These checks narrow the failure; they do not establish
the cause of a native crash. The guest clock was approximately 100 seconds ahead
of the host during this run. Current device evidence and exact artifacts are
tracked in [live acceptance](solo-sandbox-live-acceptance.md).

# Solo sandbox acceptance record

Updated 2026-09-08. This tracks the operator's seven-subsystem **Tier 1 solo
sandbox** definition. It is distinct from the architecture's T1 platform RPC
tier. The target is one controllable hero in Halcyon Fold, with the complete
specified gameplay loop, all seven client acceptance scenarios, and at least
250 passing tests. **Acceptance is reopened after the operator's Skye test.**
Skye is selectable but has no implemented ability kit, so actual upgrade
requests receive no acknowledgement. The operator also reports missing basic
projectile visuals and broken minion movement. These remain unresolved client
defects. The previous completion claim was too broad: the 758-test baseline
and deterministic replay results do not prove these user-visible behaviors.
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
$env:HALCYON_NO_BOTS = '1'
$env:HALCYON_TRACE_WIRE = '1'
$env:HALCYON_EXPERIMENTAL_CAPTURE = '1'
python -B -m server.platform.live_up
```

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

The current suite passed **758 tests in 61.721 seconds** on 2026-09-08,
with exit code 0. The complete output is external at
`$TEMP/halcyon-sandbox-full-suite-20260908-postaudit.txt`. Its adjacent JSON
records unchanged source and test manifests plus the output digest. This includes shared
hero/jungle range-boundary repairs, Celeste's crystal basic attacks, delayed
lane contacts, Fountain minion HP deltas and lethal-hit passive bookkeeping,
alongside native actions, lifecycle, shop and visibility coverage. The final
audit adds transient attack-CC cancellation and exact navigation-clipping
regressions. Two older
instant-contact test premises were corrected to require an attack start,
no early damage, and the same expected contact at its actual deadline.
The final two-process 960-second pair reproduces identical wire, canonical
state and all 960 checkpoints. Both workers pass every 50 ms deadline, with
maxima of **14.6694 and 15.5164 ms**, and complete all coverage requirements,
including two Recalls per run. The source pin matches this full-suite run
and the final worktree. The 2 ms aspiration is exceeded on many ticks.
See the performance record for exact source pins, failed attempts, repairs,
coverage and measurement limits.

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

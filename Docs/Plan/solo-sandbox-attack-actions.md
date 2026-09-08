# Ordinary attack actions from native metadata

## Operator correction: missing projectile creation, 2026-09-08

**Basic-attack client acceptance is reopened.** The operator's Skye session
shows that the previous animation/damage checks missed the absence of visible
bullets. `1045` begins the attack animation; native ordinary ranged attacks
also send **`1037` at release**. The previous inference from the absence of
`1038` was wrong: `1037` is the targeted projectile command.

Independent owned records demonstrate the omitted middle stage:

| Source | Attack | Projectile creation | Damage |
|---|---:|---:|---:|
| `vgfull.pcap`, Adagio 1516 to minion 4478 | 4675 | 4717 | 4756 |
| Same, next Adagio attack | 4807 | 4846 | 4913 |
| `a683aa80-9811-47c3-bb64-0731a802e889.3.vgr`, Skye 1517 to minion 4540 | 252 | 263 | 272 |
| Same, Skye alternate attack | 316 | 321 | 325 |
| Same, ranged minion 4562 to Skye 1517 | 334 | 380 | 440 |

Indices are zero-based decoded frames. The VGR lives in external
`$TEMP/vg_phaseB/vgr_live/` with session prefix
`ea4c7fda-4b61-481d-abb7-1c757d24ae58-`. The 22-byte layout is
`[u32 instance][u32 socket hash][f32 argument][u16 kind]`
`[u8 source slot][u8 owner slot][u8 target slot][5 zero bytes]`.
Sockets are independently joined to FNV-1a hashes of authored attachment names:
Skye `LeftGun`/`RightGun`, Adagio `DefaultAttack_Projectile`, and minion
`GunMuzzle`. Kind IDs remain corpus mappings; the complete float semantics
and unrecorded hero projectile profiles are still open.

The correction emits `1037` only on committed release, using the shared
compact actor map and effect-instance allocator. Cancelled hero windups emit
no projectile. Ranged minions now distinguish release from later contact;
shots already released survive source movement/death. Native records and
production-session boundaries are checked in `test_projectile_wire.py`.
These source changes still require a fresh client session and visible
projectile verification before this gate can be closed again.

2026-09-08. Ringo, Gwen and Celeste previously had no entry in the server's
ordinary-attack presentation table. Their simulation could apply projectile
damage without emitting a corresponding native attack action. The new
`SOURCE_BASIC_VARIANTS` rows supply Ringo/Gwen 8/9 and Celeste 7/8.

The external 4.13 hero CFF contains two relevant pointer vectors:

- Header `PTCH[100]`: hero-specific actions, already used for cast/Recall indices.
- Header `PTCH[108]`: attack groups. A group's `+40` pointer lists ordinary
  attack definitions; `+44` lists critical definitions. Each definition's first
  pointer names its `Ability__...` symbol.

The ordinal join places four shared actions after the hero vector, then
flattens each group's ordinary entries followed by its critical entries.
This is an inference corroborated by the recorded-variant table for 28 heroes
and the independent raw-corpus attack tests. Conditional groups matter:
Baptiste's empowered group occupies 7/8/9 before ordinary 10/11/12; Skye has
right/left groups before her combined attacks; Yates has three named groups.
A simple universal `kit length + 4/+5` shortcut would select incorrect
actions for those heroes.

Ringo, Gwen and Celeste each have exactly one group containing named
DefaultAttack/AltAttack/CritAttack. The new rows select only the two ordinary
entries. Native conditional-group selection, critical-hit rules and ordinary
animation alternation remain separate mechanics; deterministic alternation
of these two valid actions is an explicit presentation policy.

The audit also corrects Magnus: the old table treated 7/8/9 as ordinary
variants, but metadata names 7 as PerkProcAttack and 8 as its critical entry.
The recorded ordinary action 9 is now selected.

Sources remain under
`D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/`:

| Hero | Source | Ordinary | Critical |
|---|---|---|---|
| Ringo | `E2/E2E212FBCFCE9E9E2A7D85CA951B5389` | 8/9 | 10 |
| Gwen | `F6/F6C308E95E8AA8EB10E012C37100D8D9` | 8/9 | 10 |
| Celeste | `DD/DD70F13AABF2B1B43E95B27FE45A2676` | 7/8 | 9 |

```powershell
python -B Tools/Teardown/inspect_attack_actions.py 'D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/F6/F6C308E95E8AA8EB10E012C37100D8D9'
python -B -m unittest server.test.test_attack_action_metadata server.test.test_attack_wire server.test.test_attack_fsm -q
```

The 18 focused tests pass. A separate read-only review parsed all 65 native
hero files and confirmed that all 304 traversed vectors terminate at actual
zero words. Names/indices/offsets are the only inspector outputs; no decoded
payload is stored in the repository. Live ranged-attack acceptance remains
separate from this structural and wire evidence.

## Owned live Gwen attack/movement observations, 2026-09-08

The current owned client trace is
`$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`, connection
`1788669376464`, Gwen hero 395/source EID 1500, Baptiste target EID 1517.
Line numbers below are one-based JSONL lines; times are logged Unix seconds,
not simulation ticks or rendered animation frames. No production code changed
during this read-only audit.

The first sequence includes an actual client movement request, a native
movement response and a changed source position before the matching damage:

| Line | Logged time | Observation |
|---:|---:|---|
| 31759 | 1788804899.7798185 | c2s 1060 targets EID 1517 |
| 31760 | 1788804899.7825541 | s2c 1045, source 1500/target 1517, ordinary action 9 |
| 31765 | 1788804900.0149493 | c2s 1012 requests `(-2.6743311882, 10.6534061432)` |
| 31766 | 1788804900.016631 | s2c 1016, source actor slot 0, confirms that destination |
| 31768 | 1788804900.074861 | s2c 1070 changes source position to `(-0.1903640032, 11.2063503265)` |
| 31780 | 1788804900.2525048 | s2c 1054, victim 1517/source 1500, HP delta `-64.625`, class 5/type 0 |

The move arrives 232.395 ms after the attack action; the hit arrives
237.556 ms after the move and 469.951 ms after the attack action. The immediate
source 1070 at line 31761 gives the initial position
`(-0.000023, 11.2487201691)`. Therefore this trace directly observes sampled
server movement before matching ordinary-damage output. The target's last
1070 at line 30825 is `(5.5000238419, 11.2488555908)`, already 19.733 seconds
old at attack start; it is a position sample, not proof of continuous geometry.

The inspected external screenshot `$TEMP/gwen3-stutter-single-shell.png`
shows Gwen, Baptiste and the rounded damage number 65 after the sequence.
This single image does not establish movement order or an animation release
frame. Minion movement-before-hit and video acceptance remain separate work.

A second request gives a shorter attack-to-move interval and no matching hit
inside the bounded observation window:

| Line | Logged time | Observation |
|---:|---:|---|
| 38230 | 1788805035.649632 | c2s 1060 targets EID 1517 |
| 38231 | 1788805035.6584995 | s2c 1045 ordinary action 9 |
| 38238 | 1788805035.835542 | c2s 1012 requests `(-2.6742606163, 10.6534061432)` |
| 38239 | 1788805035.8366475 | s2c 1016 confirms movement |
| 38242 | 1788805035.838843 | source 1070 has changed to `(-0.1903630048, 11.2063493729)` |

This move arrives 177.042 ms after the attack action. No negative 1054 for
victim 1517/source 1500 occurs through the selected three-second deadline
1788805038.6584995, which is 2.822958 seconds after the move. This is a
**windup-cancellation candidate**, not direct proof of the internal release
decision. An earlier sequence at lines 24586/24590 likewise moves 92.426 ms
after action 9 and has no matching hit in its bounded window. The intervening
attempt at lines 27944/27994/27997 moves 60.218 ms after its damage, so it
supports recovery movement only.

`inspect_live_attack.py` selects one connection, joins real 1060 inputs to
1045 actions and matching victim/source negative 1054 records, distinguishes
ordinary class-5/type-0 damage candidates from type-4 proc/spell records, and
reports sampled 1070 positions with their age. A no-hit window ends at the
next player intent, next source action, chosen time limit or complete trace
end. It never infers projectile release, native commitment semantics or full
deterministic state from these logs. Seven focused inspector tests cover
actor ordering, proc separation, observation boundaries, stale positions,
movement after impact and incomplete trace tails.

```powershell
python -B Tools/Teardown/inspect_live_attack.py "$env:TEMP/halcyon_stack/wire-1788804074149933400.jsonl" --source-eid 1500 --hero-id 395 --from-line 31759 --to-line 38231 --limit 8
python -B -m unittest server.test.test_live_attack_inspector -q
```
## Oblique range-boundary repair, 2026-09-08

The subsequent Celeste run exposed a movement/attack disagreement. In external
`wire-1788805712141535000.jsonl`, actual target input at
1788806537.5591629 selected Baptiste at (52.094387,2.952555). Celeste approached
from (44.5,2.92), then repeatedly published the same position near
(46.794434,2.929829), with no attack-start action. The movement reproduction
stalled 0.000000724 units outside the 5.3-unit range. Separately, rounding the
oblique relative vector to millimetres made the attack check reject some
positions already inside the movement range.

Both admission checks now use the movement grid of millionths of a unit.
The final pursuit step aims two grid quanta inside the radius to accommodate
the movement integrator's per-axis truncation. It neither expands the attack
radius nor admits a target just outside it. `test_attack_range_boundary.py`
reproduces the exact approach and requires repeated releases/impacts, and
checks inclusive boundaries plus formerly false positive/negative cases.
The combined movement/attack command passed 66 tests. A subsequent 35-test
combat/session pass also covers release-time damage/type commitment for
Celeste's native crystal attacks. These repairs require a fresh client process;
the original stalled trace remains failed evidence.

## Celeste minion stutter acceptance, 2026-09-08

**The bounded basic-attack scenario is met.** Two real minion-target inputs
produce an ordinary attack, a real movement input, changed server positions
before the retained hit, and visible attack-to-retreat transitions with damage
numbers while Celeste keeps moving. This combines the live recordings with
the tested release-commitment contract. It does not identify an exact native
projectile-release frame or establish a 60-fps rendering measurement.

Source: external `$TEMP/halcyon_stack/wire-1788808981133504900.jsonl`,
connection `1920953706832`, Celeste EID `1500`. Both victims are naturally
spawned enemy ranged minions, not heroes or QA-created targets:

| Trial | Victim | Native 1010 line/time | Archetype / class / team / compact slot |
|---|---:|---|---|
| 2 | 4850 | 34340 / 1788809621.9828935 | 365 / 3946434133 / 2 / 60 |
| 4 | 4958 | 52550 / 1788809873.0529842 | 365 / 3946434133 / 2 / 71 |

The creation records have the measured right-side tail `000001 / 010102`.
The source is team 1. The following chains were read independently from the
complete trace; times are logged wall times, not invented simulation ticks.

| Event | Trial 2 line / time | Trial 4 line / time |
|---|---|---|
| c2s 1060 minion selection | 40671 / 1788809714.0443351 | 64676 / 1788810020.0270817 |
| s2c 1045 ordinary action | 40753 / 1788809715.2260962, action 7 | 64793 / 1788810020.904631, action 8 |
| c2s 1012 movement | 40764 / 1788809715.517216 | 64845 / 1788810021.246409 |
| s2c 1016 movement acknowledgement | 40765 / 1788809715.518496 | 64846 / 1788810021.2477975 |
| First changed source 1070 | 40768 / 1788809715.525271 | 64849 / 1788810021.2546291 |
| Matching source/victim 1054 | 40775 / 1788809715.6946084, −115.909088 | 64855 / 1788810021.3775651, −120.454544 |

Movement starts 291.120/341.778 ms after the attack action. The matching hits
follow movement input by 177.392/131.156 ms and the first changed position by
169.338/122.936 ms. Both damage records carry class 5/type 0, the basic-hit
presentation; that type byte does not turn Celeste's crystal damage into
weapon damage. Initial inventory contains only items 457/526, and 1076 level
records plus the displayed levels give level 10/11. Julia's Light therefore
accounts for the two raw damage amounts without an item proc or CP purchase.

Trial 2 moves from `(8.799000,4.062156)` through
`(8.613419,4.102891)` to `(3.570609,5.209805)` at line 40849.
Trial 4 moves from `(10.180514,4.985013)` through
`(9.996890,5.033820)` to `(5.302303,6.281653)` at line 64985.
Each has six intervening changing 1070 samples before arrival. There is no
second client intent or source attack within either attack-to-arrival window.

The QA journal at `$TEMP/halcyon_qa_celeste2_20260908/journal.jsonl` confirms
no fixture mutation inside either sequence. Trial 2 lies between the earlier
534.85-second QA teleport (wire line 31574) and the later 882.25-second QA
teleport (line 57032). Trial 4 follows the last accepted QA command, the
882.5-second B learn echoed at line 57047. The only earlier QA minion damage
targets are 4698/4700/4702/4704; neither victim above was modified by QA.

The independently decoded and viewed recordings remain outside the repo:

- `$TEMP/halcyon_stack/celeste2-minion-stutter2.mp4`: 253 frames, 480×270,
  14.97 seconds, average 16.91 fps. Native decoded frames 23–27 show the
  attack transition; the movement marker appears at frame 28 (1.653011 s),
  and the rounded **116** is visible by frame 32 (1.885856 s). Celeste
  continues retreating through the subsequent frames.
- `$TEMP/halcyon_stack/celeste2-minion-stutter4.mp4`: 116 frames, 640×360,
  11.92 seconds, average 9.73 fps. Frames 12–13 (1.171400–1.271500 s)
  show the attack motion, frames 14–15 the turn and retreat, and frame 16
  (1.572144 s) shows rounded **120** on the selected minion while Celeste is
  moving away. The following frames continue the retreat to the destination.

These are recorded-frame observations. Crowded actors and compression prevent
confident isolation of the airborne projectile itself or its precise release
frame. The moving hero, terrain/camera progression and damage readout remain
visible. Video PTS gives time within each recording; container creation times
are not synchronized to the server trace and were not used as an epoch join.
The recording rates are also not the application's rendering frame rate.

```powershell
python -B Tools/Teardown/inspect_live_attack.py "$env:TEMP/halcyon_stack/wire-1788808981133504900.jsonl" --connection 1920953706832 --source-eid 1500 --hero-id 285 --from-line 40671 --to-line 40753 --limit 2
python -B Tools/Teardown/inspect_live_attack.py "$env:TEMP/halcyon_stack/wire-1788808981133504900.jsonl" --connection 1920953706832 --source-eid 1500 --hero-id 285 --from-line 64676 --to-line 64793 --limit 2
```

Frame numbers above come from ffmpeg 7.1 decoding with `-vf showinfo
-fps_mode passthrough`; no fps conversion or interpolated frames were used.
This round changed documentation only; it did not alter production or tests.

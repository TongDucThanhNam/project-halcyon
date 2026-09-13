# Lane formation, attack presentation and turret heat

Current gate-5 status is **reopened** after the user's live Skye test exposed
broken minion movement. The earlier Celeste2 turret sequence and
[Taka fresh-wave firing check](#2026-09-08-taka-fresh-wave-ranged-fire-from-behind-passes)
covered bounded stationary situations; they did not validate continuous
lane travel, turns, stops or resumed pursuit. The current investigation is
recorded at the end of this leaf. Client acceptance remains open.

This 2026-09-08 audit reads the operator's local Celeste 285 match, PID 15676,
trace `$TEMP/halcyon_stack/wire-1788805712141535000.jsonl`, connection
1410964560464. QA provenance is in
`$TEMP/halcyon_qa_celeste_20260908/journal.jsonl`. Line numbers are one based.
The observations below predate the subsequent attack-range and lane-action
repairs; they cannot validate those changes in the client.

## Third-turret heat and retreat

QA placed Baptiste 1517 at requested (52.2,2.92), projected by the real mesh
to (52.094387,2.952555), at simulation 706.35. Request
`ca33641643034226b736f8c3ffe6abb0` completed normally. At 706.55,
request `3f9ba3d9d71d4c6bb5fe7a0a81adaea3` placed Celeste 1500 at
(44.5,2.92). No QA damage, movement or resource mutation intervened in the
following attack/retreat interval.

Actual client `1060` at line 31729 / epoch 1788806537.5591629 targeted
Baptiste. Celeste approached the target and entered turret 3541's radius.
The turret sent acquire action 1 at line 31742 / 1788806537.8377273 and
its first attack action 0 at line 31743 / 1788806537.8380685.

| Shot | Damage line | Wall timestamp | Raw heat damage | Observed HP damage |
|---|---:|---:|---:|---:|
|1|31744|1788806537.8383825|160|96.435501|
|2|31787|1788806538.8246660|259.2|156.225510|
|3|31831|1788806539.8646913|352.512|212.466705|
|4|31875|1788806540.8403880|423.0144|254.960037|
|5|31914|1788806541.8340385|423.0144|254.960037|

Each `1054` names victim 1500 and source 3541. Nine preceding native
`1076` increments establish level 10 from level 1; the last is line 29111.
The loaded Celeste constants give armor `25 + 9×4.546 = 65.914` and max HP
`649 + 9×125.37 = 1777.33`. Every observed damage value equals the f32
serialization of `raw / (1 + 65.914/100)`. Shots 4 and 5 show the heat cap.
This validates the implemented heat progression and mitigation, not an
independent recovery of its policy coefficients from native recordings.

Celeste's own basic attack never starts in this interval. `1070` repeats
(46.794434,2.929829), just outside the old combat predicate despite movement
considering her in range. There is no Celeste `1045` and no Celeste-to-Baptiste
`1054`. The turret acquired an enemy in range; this is not evidence of the
ally-protection rule switching aggro from a minion after a hero attack.

Actual retreat `1012` is line 31932 / 1788806542.3540046, targeting
(−0.119455,6.364209). The turret sends self-targeted release action 2 and idle
action 3 at lines 31959/31960 / 1788806542.6946301/.6950180. The preceding
published hero position is 8.153411 units from the turret; the next is
8.912009 units away, bracketing its 8.5-unit boundary. No further
3541-to-1500 damage appears through the read-only checkpoint at epoch
1788807077.546835. The retreat reaches its requested endpoint at lines
32462/32463. A later re-entry would be needed to show the heat reset.

Inspected `$TEMP/celeste-third-turret-hits.png` shows level-10 Celeste with
reduced HP, Baptiste, and the turret's red warning/attack presentation at
client 11:58. The packet trace supplies the exact damage numbers. This is
a bounded heat/cap/retreat-release pass. Hero-protection aggro remains open.

## Ranged minion stops behind a living melee minion

Creation, death, removal and position records were joined before comparing
actors. Ranged 4779 is archetype 365/team 1 (creation line 18983). Its nearest
living friendly melee during this sample is 4775, archetype 366/team 1
(creation line 18880).

Ranged 4779 repeats (−13.702757,5.520302) at lines 19553,19591,19632,19684,
19735 and 19784. Melee 4775 repeats (−12.174995,5.479901) at lines
19557,19598,19648,19688 and 19740. From epochs 1788806245.819434 through
1788806251.2519236 both remain alive and stationary, separated by 1.528296
units, with the melee 1.527761 units ahead along team 1's direction of travel.
Ordinary ranged contacts continue, for example `1054` line 19599 against
enemy 4772 for 65 damage. Neither actor is moved or damaged by a QA fixture
during this interval. This establishes one server-position formation sample.

Later contacts by ranged 4787 and 4789 occur after nearby melee actors have
died; their nearest living melee belongs to an incoming wave far behind.
Those contacts do not establish the same formation. All three ranged actors
have zero `1045` in this loaded match. The position/damage sample therefore
does not validate shooting animation or projectile presentation.

## Grounded lane attack action repair

`wave.Director._combat` previously applied damage without an attack action.
It now emits exactly one `1045` when starting each attack, after checking
life, spawn time, target/range, attack permission and cadence. Melee 366 cycles
0/1/2; ranged 365, siege 367 and captain 368 cycle 0/1. New minions start at
ordinal 0. These use the existing measured constants in `attack_wire.py`.
No extra `1070` is appended. The subsequent contact scheduling repair below
changes when damage resolves. Damage amounts, movement and attack cooldowns
remain unchanged.

The NPC direct PTCH+100 vector, with each Ability__ symbol at entry+4,
independently identifies all selected actions. External first-revision CFFs,
relative to `D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data`:

| Archetype | External path | Named entries |
|---|---|---|
|365 ranged|74/74C3647809896C485179091260963244|DefaultRangedAttack_01, _02|
|366 melee|8D/8D300EEC712D921FE908FC39FD554FAB|DefaultMeleeAttack_01, _02, _03|
|367 siege|AD/ADC34CE1748BA32E0A631949404BB60D|LeadMinion DefaultAttack, AltAttack|
|368 captain|1E/1E7A3B02E8305164AAA32F953749D112|DefaultRangedAttack_01, _02|

The canonical native recording census contains 15,682 lane actions:
365 has 8,358; 366 has 3,331; 367 has 2,788; 368 has 1,205. All are immediately
followed by `1086`, rather than the heroes' current-position pair. The test
compares nine complete recorded action payloads and subsequent negative
class-5 damage payloads, covering every selected variant and all four types.
Actions come from match `591146df-33f2-4f12-9a04-8d800d239821`, chunks
3,10,11 under `$TEMP/vg_max/vgr2`; exact rows are in
`server/test/test_wave_attack_presentation.py`.

Two native ranged examples have action-to-impact delays of 1.400261 and
1.383820 seconds (chunk 3, rows 451→542 and 560→886). Neither window has
`1038`; unrelated/undecoded `1037` effects interleave. These observations
do not establish which effect, if any, creates the ordinary projectile or
separate windup from flight. Deterministic variation selection is policy.

Initial presentation validation: 60 tests passed across lane action evidence/cadence, wave behavior,
native minion death, turret rules and jungle action evidence. Four new tests
cover all four external CFFs, nine full native action/damage pairs, repeated
melee/ranged/siege cadence, and no action while stunned, out of range, dead
or not spawned. Initial failures were test setup mistakes (the wrong status
API and exact comparison of differently associated float additions), corrected
without changing the production behavior under test. No proprietary payloads
were copied into the repository.

## Delayed lane contacts: empirical fixed-tick policy

This section records the initial delay repair. Its conservative source-death
rule was superseded by the later native `1037` release evidence and staged
projectile lifecycle described at the end of this leaf.

A stricter native timing audit selected the first recorded `1045` for each
source, then its first matching negative class-5 `1054`, requiring the hit
to precede the next action from that source. No source/target death or
removal may intervene. All 15 examples below were independently re-decoded
from the original match chunks 0 through 11, with zero failed assertions.
They establish that immediate HP damage at attack start is the wrong premise
for these native lane attacks. Chunk and row coordinates are zero based.

| Type | Source → target | Start → hit → next action | Start-to-hit seconds |
|---|---|---|---:|
|365 ranged|4476 → 4444|3:451 → 3:542 → 3:553|1.400261|
|365 ranged|4477 → 4443|3:458 → 3:552 → 3:560|1.399754|
|365 ranged|4489 → 4443|3:537 → 3:861 → 3:873|1.401009|
|365 ranged|4972 → 4883|6:524 → 6:637 → 6:649|1.301151|
|365 ranged|6382 → 6357|11:503 → 11:645 → 11:669|1.400688|
|366 melee|4443 → 4444|3:326 → 3:358 → 3:437|0.499817|
|366 melee|4444 → 4443|3:330 → 3:361 → 3:443|0.500282|
|366 melee|4455 → 4443|3:371 → 3:424 → 3:481|0.484402|
|366 melee|4454 → 4444|3:379 → 3:428 → 3:490|0.483276|
|366 melee|4843 → 4465|5:1051 → 5:1099 → 5:1247|0.498585|
|367 siege|4465 → 4444|3:377 → 3:485 → 3:506|1.384041|
|367 siege|4466 → 4443|3:392 → 3:493 → 3:510|1.383965|
|367 siege|4910 → 4465|5:1172 → 5:1356 → 6:250|1.333130|
|367 siege|4909 → 4883|6:257 → 6:437 → 6:483|1.316872|
|367 siege|5661 → 4972|8:419 → 8:567 → 8:606|1.333641|

Across the broader canonical cache there were 6,013 paired ranged contacts,
2,820 melee and 2,180 siege contacts within three seconds. None had both
source and target current-position `1070` samples within 0.25 seconds of
the action. Compact `1016` destinations are not current actor positions.
Consequently this audit cannot fit a release time plus distance/projectile
speed model from those records.

A bounded source audit inspected both first and last CFF revisions for
365,366,367 using the already established INST keys. Their action vectors
identify the ordinary attack names, but the containers have only DEF0,
INST,PTCH,SYMB chunks and no TIMR data. Unnamed float fields in action and
animation records do not identify release time or projectile speed.
Animation references point to `minion.RangeAttack01/02.anim`,
`minion.MeleeAttack01/02/03.anim` and `leadMinion.attack/attack_alt.anim`.
The existing asset index does not resolve those clip paths. No separate
named minion projectile asset or supported timing-field semantics emerged.
This does not recover a native windup or projectile-speed constant.

The implementation therefore adopts an explicit empirical approximation:
melee 366 contacts after **10 ticks (0.50 s)**; ranged 365, siege 367 and
captain 368 after **27 ticks (1.35 s)**, on the existing 20 Hz clock.
Captain uses the shared ranged policy without a separate timing sample.
These are sandbox timing choices informed by the measurements above, not
exact native engine constants. An off-tick action rounds forward to the
next simulation tick before adding its delay.

Each pending contact retains its own deadline, insertion order, damage
amount, and original source/target objects and EIDs. Repeated attacks can
overlap; starting another action does not reset an earlier deadline. Due
contacts resolve before new attacks for that tick. Source death cancels
both melee and ranged contacts: this is a conservative policy while the
native projectile release boundary remains unknown. Target death, removal
or replacement drops the contact; EID reuse cannot redirect it. Once a
tick observes a dead or removed actor, later revival cannot restore that
contact. Current session registries validate hero and structure identities.

Validation: **68 focused tests pass**, including eight new contact-timing
tests covering exact 10/27-tick boundaries and no earlier hit, independent
overlapping deadlines, source/target death, removal/reused EIDs, off-tick
rounding and snapshotted damage. Existing damage/death tests now assert no
damage at attack start and preserve their damage, death-order and corpse
assertions at the delayed contact. They formerly assumed the immediate
contact premise contradicted by the native records.

At this initial repair, fresh client attack animation and visual impact
alignment were unobserved; the later Taka check establishes visible ranged
firing. The original Celeste trace predates both lane repairs. Exact native release,
projectile flight and post-release source-death behavior are still unknown;
this policy does not claim full native synchronization.

## 2026-09-08: Celeste2 protective target switch, heat and retreat

The fresh Celeste 285 match uses
`$TEMP/halcyon_stack/wire-1788808981133504900.jsonl`, connection
1920953706832. Unlike the preceding Celeste match, this source includes
the hero range correction and delayed lane contacts. QA learning and
positioning at simulation 184.9–186.05 prepared level-8 Celeste 1500 at
(7.5,1.93) and Baptiste 1517 at projected (15.368114,1.929846).
Those fixtures are explicit in `$TEMP/halcyon_qa_celeste2_20260908/journal.jsonl`;
they do not apply damage. The later action/heat/retreat interval has no QA
mutation. The wire's preceding level increments establish Celeste level 8
and Baptiste level 4 by this interval.

First turret 3539 acquires living friendly melee minion 4685 at line 14999 /
epoch 1788809302.235276. Its attacks at lines 15000/15001 and 15058/15059
each deal 100 to that minion. Actual hero input `1060` at line 15013 /
1788809302.600891 targets Baptiste. Celeste approaches and starts `1045`
at line 15060 / 1788809303.2890558. Her contact at line 15080 /
1788809303.8175786 deals 81.5960312 crystal damage to Baptiste.
The immediately following action at line 15081 / 1788809303.8182065 is
turret acquire 1, now targeting Celeste 1500. Minion 4685 is still alive.
This proves the protective switch after an enemy hero damages the turret's
ally, rather than ordinary acquisition after the previous victim dies.

| Hero shot | `1045` / `1054` lines | Damage wall timestamp | Raw heat | HP damage |
|---|---|---:|---:|---:|
|1|15113 / 15114|1788809304.2622697|160|102.026505|
|2|15168 / 15169|1788809305.2347987|259.2|165.282928|
|3|15237 / 15238|1788809306.2358866|352.512|224.784790|
|4|15294 / 15295|1788809307.2335527|423.0144|269.741760|

Every damage packet names victim 1500 and source 3539. Celeste's level-8
armor is `25 + 7×4.546 = 56.822`; all four values equal f32 serialization
of the raw damage divided by `1.56822`. Shots 2 and 3 visibly and numerically
increase. This validates the implemented heat/mitigation policy in the live
client, not an independent recovery of the coefficients.

Actual movement input at line 15269 / 1788809307.0994272 retreats toward
(−0.119455,6.364209). The fourth turret hit still occurs while Celeste is
inside range. Release 2 and idle 3 at lines 15312/15313 /
1788809307.5271766/.5277748 follow her departure, then acquire 1 at line
15314 / 1788809307.5283291 returns to minion 4685. The next attack at
15359/15360 damages that minion by 100. It dies only at line 15361.
No further turret-to-Celeste damage occurs through the bounded checkpoint
at line 15700. The minion's survival across both target switches rules out
death as the explanation for the first switch.

Viewed `$TEMP/halcyon_stack/celeste2-protect-heat.png` shows the red 225
damage over level-8 Celeste, 82 over Baptiste and the turret's red warning
at client 4:28. The clip `$TEMP/halcyon_stack/celeste2-turret.mp4` also shows
the attack and retreat. It contains 78 frames over 19.89 seconds, averaging
3.92 fps; this is useful for visible states, not smoothness or precise
animation/impact timing. The bounded protective-switch, escalating-heat
and return-to-minion sequence passes.

## 2026-09-08: delayed ranged fire behind a living front minion

In the same clip interval, ranged 4681 is archetype 365/team 1, created at
line 10534. Melee 4685 is archetype 366/team 1, created at line 11650.
The ranged actor repeats (10.6110725,2.7432389) at lines 15033,15118,15195,
15272, approximately 6.5 units from turret 3539. The front melee repeats
(17.0359707,4.1821060) at lines 15209 and 15304. Thus both are stationary
around epochs 1788809306.099444–1788809307.1594467, with the melee 6.424898
units ahead along team 1's travel direction and 6.584045 units away. Both
are alive; melee death is later at line 15361. This is a living front-line
comparison. The closest living melee overall, 4687, is in the incoming
formation behind the ranged actor and is not misidentified as that front.

Ranged 4681 emits alternating `1045` ordinals 0/1 toward turret 3539.
Its delayed weapon contacts deal 55 each to that same turret. Examples:

| Action line | Contact line | Action wall time | Contact wall time |
|---:|---:|---:|---:|
|15031|15115|1788809302.9441960|1788809304.3160317|
|15072|15143|1788809303.6414770|1788809304.8941088|
|15106|15181|1788809304.2024480|1788809305.5298595|
|15140|15218|1788809304.7832193|1788809306.1655006|
|15178|15261|1788809305.4666490|1788809306.8019218|
|15208|15303|1788809306.0438280|1788809307.4052548|

These are ordered contacts from overlapping attacks under the implemented
27-tick queue, rather than the first later hit being assigned to each new
action. Wall gaps vary with serialization/batching and do not replace the
fixed-tick deadline tests. There is no QA actor movement or damage during
this sample.

Read-only extraction placed the clip's original frames outside the repo at
`$TEMP/halcyon_stack/celeste2-turret-frames/frame-001.png` through
`frame-078.png`. Frames 7–15 and 24 show a rear formation and a front minion
beside the turret, with changing rear-minion poses. However, the crowded
actors and Celeste overlap do not isolate an identifiable projectile from
4681 in those sparse frames. The stationary formation, ordinary action and
delayed damage checks pass. **Visible ranged fire from behind remains
unconfirmed**, so gate 5 is not marked complete from this clip alone.

## 2026-09-08: follow-up ranged visual audit

Two later clips from the same connection improve sampling:

| External clip under `$TEMP/halcyon_stack/` | Size | Original frames | Duration | Average frame rate |
|---|---|---:|---:|---:|
|`celeste2-minion-stutter2.mp4`|480×270|253|14.97 s|16.91 fps|
|`celeste2-minion-stutter4.mp4`|640×360|116|11.92 s|9.73 fps|

The second clip is not 16.91 fps. Original frames were extracted to sibling
directories with the `-frames` suffix, outside the repository. The audit
inspected sampled frames across each clip and the closer sequence of
stutter4 frames 36–58. Celeste retreats, the front melee actors visibly
change attack poses, and the ranged actors stay in the dense rear formation.
At these actor sizes and compression, rear ranged firing cannot be identified
confidently. This is an inconclusive observation, not proof that it is absent.

The wire supplies a separate clean formation/action/contact check in
stutter4. Ranged 4969 (archetype 365/team 1, creation line 54483) repeats
(8.4464073,3.4152479) at line 65127 / epoch 1788810024.0300996 and line
65260 / 1788810025.337452. Living friendly melee 4973 is ahead at
(12.7938633,4.6337762), recorded at lines 65003/65157; it dies only at
line 65275 / 1788810025.590403. Ranged action 1 at line 65151 /
1788810024.2283845 targets enemy 4956. Its queued contact at line 65272 /
1788810025.577531 names that victim and source 4969, dealing 85 damage.
The 1.349147-second wall gap is consistent with the existing 27-tick policy.

Gate 5 retains only the brief's visible ranged-fire-from-behind observation.
Exact projectile timing, a particular projectile effect, and a separate
isolated-actor scenario are not additional acceptance conditions. These
read-only clip checks do not justify marking the remaining observation met.
No simulation source changed during this audit.

## 2026-09-08: Gwen4 isolated ranged attempt

The next recording is `$TEMP/halcyon_stack/gwen4-ranged-isolated.mp4`,
640×360, 187 original frames over 19.98 seconds, averaging 9.36 fps.
Trace `$TEMP/halcyon_stack/wire-1788810206949588100.jsonl`, connection
2598410757328, supplies the actor identities. At simulation 419.75 QA
positions primary Gwen at (5,−3). Between 419.8 and 420.95, 18 other living
lane actors are explicitly killed through opposite-team non-primary
sources. The retained ranged 4765, melee 4771 and enemy siege 4768 receive
no direct QA damage, movement or status fixture. The complete commands are
in `$TEMP/halcyon_qa_gwen4_20260908/journal.jsonl`.

This selection does not form the requested ordering. Ranged 4765 is
archetype 365/team 1, creation line 21480; melee 4771 is archetype 366/team 1,
creation line 22707. While firing, the ranged actor repeats
(11.4787045,3.7581429) at lines 24202/24261, epochs
1788810694.566848/1788810695.9171598. The melee remains at
(10.6854343,3.2421989), lines 24163/24220/24267. The ranged actor is ahead
of that melee along the positive-x direction of travel.

Ranged action 1 at line 24144 / 1788810693.3509307 targets enemy siege 4768;
its contact at line 24204 / 1788810694.6741467 deals 65 damage. Another
action/contact pair is 24196→24226. Turret and siege damage kill the ranged
actor at line 24273 / 1788810696.3481243. Only afterward does melee 4771
advance to (15.4490948,4.5758839), first published at line 24352.

Viewed `gwen4-ranged-isolated.png` and clip frames 18–36 show the two
retained friendly actors more clearly, but their positions are the reverse
of the required formation. This attempt therefore does not establish
ranged fire from behind a living melee minion. It does not change the
earlier formation/action/contact passes or add any new acceptance condition.
No source changed during this read-only audit.

## 2026-09-08: Taka fresh-wave ranged fire from behind passes

The final bounded setup keeps actors from one fresh wave: friendly melee
4749, friendly ranged 4755 and opposing melee 4748. Trace
`$TEMP/halcyon_stack/wire-1788811044288843600.jsonl`, connection
2207670451280, identifies them as 366/team 1, 365/team 1 and 366/team 2
respectively. Creation lines are 19690,19858,19687. They have no direct
QA damage, movement or status preparation.

The journal at `$TEMP/halcyon_qa_taka_20260908/journal.jsonl` records
**20** other lane actors cleared through opposite-team non-primary
sources between simulation 353.55 and 354.85. The twenty-first command
positions the player at (−8,5), simulation 354.95, request
`03afb7c3580e4dbdb9e8dcfc49a9b568`. Thus the kept actors still walk into
combat under their ordinary movement and attack rules. No player movement,
attack, cast, purchase or item-use input intervenes during the clip.

Viewed `$TEMP/halcyon_stack/taka-isolated-wave2.mp4` shows the melee pair
meeting first, followed by the ranged actor arriving and stopping behind
its friendly melee. The rear actor is now separate from the hero and other
minions. Its repeated firing poses are visible while the melee pair swings
at close range, including frames 82–93 of the original extraction.
`taka-isolated-wave2.png` independently shows the rear blue ranged actor
near (546,250), friendly melee near (666,288), and opposing melee near
(742,295) in the 960×540 screenshot. The clip has 153 original 640×360
frames over 19.97 seconds, averaging 7.66 fps. This is sufficient to
observe the requested behavior; no exact projectile-time or smoothness
claim follows from it.

Repeated positions prove the same formation in the authoritative stream:

| Actor | Stationary position | Example position lines |
|---|---|---|
|4755 ranged, team 1|(−5.5536861,5.1116462)|20551,20609,20653,20699|
|4749 melee, team 1|(−1.0552530,5.2636299)|20522,20576,20628,20666|
|4748 melee, team 2|(0.9447300,5.2551632)|20518,20567,20622,20665|

The friendly melee is 4.498433 units ahead along team 1's direction of
travel and 4.501000 units from the ranged actor. The ranged actor is
approximately 6.5 units from the enemy, with the melee pair approximately
2 units apart. All three remain alive during the firing sample.

The ranged actor's first ordinary `1045`, action 0, is line 20519 /
epoch 1788811599.9748816, targeting 4748. Its first matching negative
class-5 damage is line 20575 / 1788811601.3539755, victim 4748/source 4755,
for 62.5 damage. Action 1 at 20543 / 1788811600.572452 is followed by the
next contact at 20588 / 1788811601.9483857. These are the first two ordered
contacts, separated from their starts by the implemented delay. Subsequent
0/1 actions and 62.5-damage contacts continue while the ranged actor holds
its rear position. Its final contact at 20700 / 1788811605.0532992 kills
4748; native death at 20701 / 1788811605.0539467 names killer 4755.
The friendly melee survives and advances afterward.

The visible firing cycle, intact front melee and source/target-resolved
position/action/damage sequence together pass **ranged fire from behind**.
This closes the remaining bounded gate-5 observation alongside Celeste2's
protective turret switch and escalating shots, and the earlier crystal
destruction/Victory. Exact native NPC release/flight timing and overall
client smoothness retain their separate limits. No source changed for
this acceptance check.

## 2026-09-08: user Skye test reopens continuous minion movement

The user reported broken movement in the active Skye 265 match, server PID
27792, connection 2586935884240, with QA disabled. The finite audit through
line 24511 of `$TEMP/halcyon_stack/wire-1788834431219807100.jsonl` found
170 lane actors and exactly **one** compact `1016` order per actor. Every
order still named the first spawn waypoint, `(±65.62,11.101)`. Lane turns,
pursuit changes, range stops and ally obstruction only changed server
positions; the client's travel goal remained the original waypoint.

For example, melee 4759 received its sole `1016` at line 21989, epoch
1788834858.419989. Position line 22513 / 1788834866.592370 is
`(-35.817730,4.767786)`; line 22580 / 1788834867.927021 is
`(-29.743864,4.884944)`, a 6.074996-unit change after 1.334651 seconds.
The server's positions advance along the lane while its only client order
still points toward the spawn. This accounts for walking back toward that
old goal between forward position corrections.

Read-only Android capture `$TEMP/halcyon-wave-skye-live.mp4` records the
user's unchanged session at client clock approximately 4:51–5:10. It has
19.61 seconds of 960×540 video averaging 4.23 fps. The incoming allied
actors visibly hold, drift and then advance in large corrections. The low
frame rate limits animation and smoothness conclusions; the wire census
independently proves the missing orders. No tap, teleport, QA command,
restart or other gameplay input was sent for this audit.

Native match `591146df-33f2-4f12-9a04-8d800d239821`, chunks 0–3 under
`$TEMP/vg_max/vgr2`, instead contains 13–18 `1016` orders for each of its
ten first-wave actors. Source 4443 owns compact slot 33. Its successive
orders at rows 1:639, 1:683, 2:210 and 2:262 progress through lane goals
`(64.13,10.62)`, `(57.27,7.08)`, `(49.54,6.04)` and `(41.85,5.04)`.
Later row 3:315 changes its combat destination to `(0.5,4.5)` before
its ordinary action at row 3:326. These are distinct goal updates, not
full-EID position corrections. Those VGR chunks contain no `1070`.

`wave.Director` now tracks the last published goal on the position lattice.
It emits a new compact `1016` when a lane turn or pursuit changes the next
waypoint, a current-position goal when range/CC/ally obstruction stops the
actor, and the resumed waypoint when movement resumes. Each goal change
also publishes one matching current `1070`. Unchanged goals are suppressed:
stationary attacks do not reissue stop orders at launch or damage contact.
Reconnect creation restores the last actual goal, including an obstruction
stop. Dead actors receive no movement order. The existing position heartbeat
remains unchanged. Navigation geometry, movement budgets, attack ranges and
attack cooldowns are unchanged by this presentation repair.

## 2026-09-08: ranged attacks require a separate projectile release

The same review exposed a second missing command: `1045` starts an attack
animation, while native ranged attacks separately create their projectile
with `1037`. The earlier Taka firing-pose observation did not prove a visible
projectile. The native source below makes that omission concrete.

External file:
`$TEMP/vg_phaseB/vgr_live/ea4c7fda-4b61-481d-abb7-1c757d24ae58-a683aa80-9811-47c3-bb64-0731a802e889.3.vgr`.
Rows are zero based; all decode checks pass.

| Source/target | `1045` row | `1037` row | `1054` row | Start → release | Release → contact |
|---|---:|---:|---:|---:|---:|
|4562 siege → Skye 1517|334|380|440|0.532322 s|0.816837 s|
|4561 siege → minion 4551|421|463|527|0.515842 s|0.866310 s|
|4572 ranged → minion 4540|490|528|—|0.716549 s|—|
|4572 ranged → minion 4551|921|1003|—|0.499836 s|—|
|4573 ranged → minion 4539|1001|1051|—|0.499344 s|—|

The ranged/siege projectile profile has launch-socket hash `0x005DD10C`
and kind 79. The authored float is 15 when targeting a hero and 50 in the
minion-target examples; its semantics remain unresolved and it is not used
as projectile speed. Source, owner and target fields use their real compact
actor slots. The session allocates a fresh effect identity from the shared
allocator and builds the native payload through `projectile_wire.py`.

The explicit 20 Hz approximation now releases at 10 ticks (0.50 s) and
retains contact at 27 ticks (1.35 s). The recorded spread above is preserved
as evidence; these fixed values do not claim exact native windup or flight
physics. `on_projectile_release(source,target,variant)` supplies the visible
creation at release. Melee has no projectile callback and still contacts at
10 ticks.

Before release, source death, removal, replacement or an attack interruption
cancels the windup. Interruption serials retain even a short stun that ends
between simulation ticks. After release, source death/removal, movement,
retargeting or later CC cannot retract the projectile. Target death or
replacement drops its contact; reused source identities do not inherit it.
Shared deadline and attack-start serial ordering resolves a same-tick melee
kill versus ranged release deterministically. Damage is still emitted once
at the original contact deadline against the original target.

The final focused selection passes **78 tests**, covering native goal and
release evidence, lane turns, blocked/CC stop and resume, pursuit retargeting,
reconnect, stationary attack order suppression, exact release/contact
boundaries, short pre-release CC, committed post-release death/CC, reused
identities, simultaneous release/lethal-contact ordering, and production
session compact-slot projectile creation with one mitigated hit after source
death. The active user match still runs the preceding loaded source. These
changes have not yet received post-reload live client acceptance, and the
wave gate remains open.

## 2026-09-09 live minion locomotion and ongoing wave buildup defect (gate 5: OPEN/PARTIAL)

Live Skye sessions on the local server. The original defect where spawned minions received only a single `1016` move order and subsequently halted or drifted has been repaired by continuous waypoint and turn re-issuance.

In the earlier movement trace `$TEMP/halcyon_stack/wire-1788894917131102000.jsonl` (connection `1986324652112`), the first lane wave spawned at +121.6..125.5 s from connection start as actor slots 45..54 (EIDs `4610`..`4619`, melee/ranged mixed, both sides).

Census of `1016` move intents addressed to each wave-1 actor during its first ~25 s on the lane (window +118..+148 s):

| Slot | 45 | 46 | 47 | 48 | 49 | 50 | 51 | 52 | 53 | 54 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1016 orders | 22 | 22 | 20 | 19 | 19 | 18 | 17 | 17 | 16 | 16 |

Every lane actor received **16-22 orders in 25 s** (native reference observation is roughly 13-18; same order, same cadence). Per-actor lifetimes ran +121.7 to +143.9..165.1 s (20-40 s on the lane) with continuous re-pathing throughout. In the current session snapshot (`wire-1788942557949012000.jsonl`), **2557** total `1016` orders were logged across the match. Short operator recordings illustrate directed locomotion without hold-in-place, drift, or rubberbanding: fresh 30s `skye-basic-attacks.mp4` and 45s `skye-combat-verify.mp4`. The older `halcyon_gate5_wave.mp4` is a >2-minute recording with separate provenance and is not the fresh 30s reference.

### Confirmed open defect: late-match minion buildup at lane center

While individual minion locomotion is repaired, the actual long-match wave buildup remains confirmed and open. Minions clumping at the gold miner circle / lane center fail to reliably advance, eventually creating a large accumulation that degrades client performance. Cause of client input degradation in those conditions is unknown; minion accumulation alone does not establish the mechanism.

The `wave.py` targeting-guard change (removing the `structures is None` precondition on the fallback foe acquisition) was **reverted** by its own worker because it could select a distant enemy wave instead of advancing on a nearby vulnerable turret. A new 17-line regression in `server/test/test_wave_sandbox.py` protects this behavior (76 focused wave/structure tests pass in 1.906s; `wave.py` is at clean HEAD). The earlier wave-only 110→87 comparison omitted production nav and turret steps and is not a production buildup fix. A preliminary full-SnapshotStream 20-min comparison (old guard 89 live vs. removed guard 91 live, central |x|≤5: 21 vs 12) was confounded by baseline/copy/brush predicate differences; no definitive improvement or fidelity claim follows from it. Continuous `1016` repair is already in HEAD. Gate 5 remains **OPEN/PARTIAL** pending reference-backed repeatable acceptance.

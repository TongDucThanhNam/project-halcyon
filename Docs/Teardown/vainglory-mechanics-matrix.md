# Vainglory mechanics matrix — the 3v3 build bar

Provenance: compiled 2026-09-03 (sessions 3 cont. 6-8) from the wire-protocol
campaign artifacts (pcap + `.vgr` corpora in TEMP, the verified external
balance DB, the 101.6 MB Android decompile) plus every prior teardown leaf.
Owner: goal 014. **This file defines the campaign's stop condition**: the
campaign runs until every cell below is `Measured` / `Cite-only` /
`documented ceiling` — i.e. enough mechanic knowledge to build an original
3v3 MOBA on the reconstructed map. Hiểu ≠ Làm still binds: nothing here
authorizes implementation.

Labels: `[M]` measured from artifacts · `[C]` cite-only from the public
balance DB (IP rule — facts, never bulk tables) · `[P]` partial ·
`[O-off]` open, minable offline from corpora in hand · `[O-cap]` open,
needs a new passive capture (playbook per row) · `[O-dec]` open, needs
decompile mining · `[X]` documented ceiling (out of band).

## Domain table

| # | Domain | Status | Where it lives |
|---|---|---|---|
| 1 | Map skeleton (bounds, walkable, placements, symmetry) | **[M]** closed | map leaf §11, placement table |
| 2 | Structures (HP tiers, turret behaviour) | **[P]+** — turret source file opens: header stat trio + full ability/buff grammar (§18) | §6 + wire §15.6 + §18 |
| 3 | Minion system (waves, scaling, AI) | **[P]+** — MinionSettings differential: 5v5 wave tiers at minutes 1/26/51/76, Range joins at 78; 3v3 Tank/Lead/Ranged roster (§18) | §7 + wire §15.6 + §18 |
| 4 | Jungle & objectives (camps, mines, kraken) | **[P]+** — Kraken level entity list + Kraken5v5 buff family + **measured entity stat arrays** (CrystalMiner 1200+200 vs 2015 cite 970+100, drift proven; ElderTreeEnt ability named: Range 3.0/Radius 1.8/Root Delay 2.5/Energy 8.0) (§18) | §8 + §18 |
| 5 | Hero base systems (stats, XP, respawn) | **[M]** — stat ladders live-verified per-frame on wire (§19.1); respawn per-level curve open: 4 real-domain anchors + sim-clock trap documented (§19.3) | §9 + §18 + §19.3 |
| 6 | Combat math (WP/CP, armor, crit) | **[M-]** — per-sample fit landed on-device: `D=W/(1+A/100)` reproduces 28 known-input samples ≤1.3 % (minion armor −10 const, structure ≈82, hero-side ≈25 % pierce [Inferred]) (§19.2) | §10 + §19.2 |
| 7 | Abilities (semantics beyond curves) | **[M]** — pointer-graph route closed: form-2 records `{name-ptr → (base, delta, overdrive)…}` extracted via PTCH relocations; DB-diff on real (non-artifact) variables **97.5 % (1,378/1,414)** ≥ 90 % gate; the 36 residuals are one identified family (flat-4 + rank-5 overdrive jump) (§18) | §11 + §15 + §17 + §18 |
| 8 | Items (offset map, actives) | **[P]+ / sweep complete** — 93/93 per-item files decrypt, 42 named stat fields; Bonesaw fully named; DB byte-offset floats identical (§18) | §12 + §18 |
| 9 | Talents / modes | [C], opaque — low priority for 3v3 | §12 |
| 10 | Vision / FoW | **[P]+ / ceiling [X]** — 22-name vision buff grammar + measured item timings (Flare 15/0.5, Flaregun 20/5/15, Totem CD 7.5/LIFESPAN 2.0); numeric radii closed as evidenced offline ceiling (buff floats all-zero, property-hash read, no static defaults — §18) | §13 + §15 + §18 |
| 11 | Game flow (start, end, economy) | **[P]** | §14 |
| 12 | Controls / HUD / camera / feel | **[M]** closed | teardown §4/§11/§13/§14 |
| 13 | Match transport & protocol | **[M]** closed | wire leaf §15 |

## §8 Jungle & objectives — native camp timing correction, 2026-09-08

- The older opening estimate **~42–45 s** was chunk-derived; the camp-timer
  correction below does not establish a match-clock opening schedule.
- Respawn after full clear: **Treant camps A/C = 60 s; bear camps B/D = 50 s**.
  This replaces the old **A≈85 / B/C/D≈71 s** chunk-index estimates. Exact
  timestamps from 26 complete generations in two matches give A/C
  59.996834–60.097252 s and B/D 50.011421–50.095108 s. Camp identity is joined
  by class, archetype and unchanged creation position; a pair's timer starts
  at its last member's death. Original match-2 files themselves provide the
  correction: left A 44.946995→105.011223, B 50.632389→100.693619,
  C 58.551327→118.631599, D 70.919754→121.014862. Those files have 10-second
  timestamp spans per chunk, not the ~14.12-second multiplier reproducing
  the old estimates. All 13 matching `vgfull` camp intervals agree with
  byte-equal TCP events within 0.014808 s. See
  `Docs/Plan/solo-sandbox-camp-respawn.md` for locations, source rows, checks
  and the separate limits of hero UI-clock evidence in §19.3.
- Camp composition + maxHP scaling per spawn wave: A = 1×750→930;
  B = 2×600→730; C = 1×750→930; D = 2×480→580. Camp monsters get **fresh
  eids each spawn** — track by position, never by id.
- **Crystal mines (3559/3560-class anchors) and Kraken never activated in
  any bot match** [O-cap]: capture mechanics, gold-mine income and kraken
  capture behaviour need human-driven captures (capture the mine in a
  real match; record 1067/1068 state + 1086 award stream).
- **Mine/GoldMine/Kraken stats — cite-only (2015 community engineer guide,
  version-caveated)** [C]: Minion Mine atk 116+18, armor 46+6, shield 33+4,
  HP 970+100; Gold Mine atk 114+12, armor 110+2, shield 100+8, HP 1800+200
  (fills from 4:00, pays ≤300 g); **Kraken: 271 weapon + 70 true damage,
  400 armor, 100 shield, HP ≈ gold-in-mine/2**, spawns 15:00, respawn 4:00
  after capture. Proven drift warning: this guide's start gold is 350 vs
  our measured 600 in 4.13 — treat every number as shape-level prior, not
  4.13 truth.
- Hero-family system entities: 11 eids (3693-3703 band) die together at
  ~5.5 s and respawn ~16 s = **match-start world reset class**, not heroes.

## §14 Game flow — measured

- Start countdown 7 s; AFK surrender ≈2:10 (both bot matches); result and
  rematch loops observed (goal history). Passive gold ≈6.0/s; kill gold
  +160-230; first item ≈2.9k; minion bounty ≈3.6 (1086 award band).
- **HUD gold is client-accumulated** from 1086 awards + passive (wire
  §15.8 measured-negative: no gold column in snapshot records).
- Objective first-spawn timers (kraken/mine) [O-cap] as above.
- Cited (2015 guide, same drift caveat): kill gold
  `(30+15·victim_lvl+50·(streak−1))·0.85^(killer_streak−1)`; respawn timer
  ramps with level, cap ≈60 s; AFK-passive level timeline (L2≈3:24 …
  L12≈47:37) — usable only as prior shape.

## Damage census — measured 2026-09-03 (pooled 3-match corpus, 1054 deltas)

| source → target | n | median | p90 | max |
|---|---|---|---|---|
| hero → hero | 387 | 53.5 | 84.8 | 218.4 |
| hero → minion | 553 | 11.9 | 24.6 | 37.9 |
| minion → hero | 1,050 | 90.2 | 138.1 | 472.5 |
| minion → minion | 1,240 | 27.8 | 50.0 | 69.8 |
| turret/static → hero | 55 | 49.8 | 60.0 | 138.8 |
| turret/static → minion | 22 | 15.0 | 18.0 | 18.0 |
| hero → structure | 15 | 122.9 | 278.2 | 283.5 |
| minion → structure | 48 | 250.4 | 327.9 | 737.9 |

- Turret shots **ramp** (49.8 → 138.8 within an engagement window) [Observed].
- **Scope note (2026-09-03): the damage formula runs server-side** — the
  client only receives 1054 results — so the formula's interior is a
  *documented ceiling* for direct inversion. The cell is still closable
  **empirically**: one controlled capture (level 1, no items, single
  auto-attacks) gives D = W_base·f(A_base) pairs per hero; with W/A from
  the DB that solves the reduction shape and constant. **Battery attempt
  1 (match 4, `1498819c…`) failed — honest negative**: the tutorial
  "Choose a Build" overlay re-appeared and swallowed every in-match tap
  (the match-1 trap recurs per match); Guest idled at base 0/0/0 and the
  bots surrendered at 2:10. Sample yield: only 35 hero→hero hits, all
  late-game, no level-1 window. Protocol v2 requirements: confirm hero
  movement via live position feedback (1070 delta per move tap) before
  trusting any tap; dismiss/avoid the overlay before sampling. DB note:
  **Krul is absent from the 67-hero balance DB** (their extraction gap).
- **Kill-event encoding varies by match [Partial]**: match 1's clean
  −10000.0 overkill signature is not universal — match 4's death events
  carry garbage-magnitude deltas (1.7e29…) with targets OUTSIDE the hero
  eid band, and one hero death (Kestrel) has no matching hero-band
  overkill at all. Do not use the −10000 signature as a death detector
  without per-match validation; scoreboard (screencap) stays the ground
  truth.
- hero→hero median (53.5) vs DB anchors (weapon_base 50–79, armor_base 25)
  sits inside the standard `damage·100/(100+armor)`-family reduction;
  per-pair modes extracted (e.g. 1515→1518 mode 49.43 ×8) but bot-match
  noise (mixed abilities, level growth) prevents a clean fit — the
  controlled capture above replaces this approach.
- DB anchors cross-checked: move_speed (med 3.8) names wire stat-id 0;
  armor_base med 25 / weapon_base med 77 give the formula priors [C].

## Offline combat-math pass — 2026-09-03/04 (match-5 `.vgr` corpus + cited guide)

- **`1011` = periodic hero full-state snapshot** (119/match ≈ every 10-15 s;
  746 B = 6 records × 124 B). Per record: eid u32BE@8, **team u32@12**
  (1/2), pos f32BE@18/22/26, **HP@42, maxHP@46**. maxHP equals the DB
  ladder *exactly* (Adagio 685→832.5→980.1, step 147.55) → **level(t) for
  every hero** (level = (maxHP−base)/per+1, running-max filter for the
  ~1-in-12 template-frame artifacts) **and eid→hero identity by ladder
  fingerprint**. Match-5: 1500=Phinn (ours), 1515=Baptiste, 1516=Ozo,
  1517=Vox, 1518=Grumpjaw, 1519=Adagio; teams {1500,1515,1516} vs
  {1517,1518,1519}. Krul absent (and not on the wire either).
- **`1054` u16BE@12 = damage-type tag** (hero↔hero census): 5 heal/regen
  (positive, n=2,254), 16 DoT tick (n=415), 10 ability (n=180), 74 nuke
  (n=47), 1 weapon-class (n=364), 0/3/15 minor classes.
- **f(A) per-sample fit = clean negative on bot traffic**: type-1 modes are
  level-invariant flats repeated across level cells (39.29 at La=3 and
  La=10) → weapon-*ratio* abilities, not auto-attacks; the largest cells
  are DoT-dominated (Baptiste→Adagio 13.75×31). No sustained auto-attack
  exchange exists between bots, so armor inversion is infeasible from
  passive bot corpora — the battery v3 controlled capture (human-driven
  autos on a known-level target) stays the only path to [M].
- **Formula family cite-locked [C]** (2015 community engineer guide,
  version-caveated — its 350 start gold vs our measured 600 proves drift):
  `D = W/(1 + A/100)` weapon vs armor, `D = C/(1 + S/100)` crystal vs
  shield, pierce `p·D + (1−p)·D/(1+A/100)`, shred reduces A before the
  division, crit ×1.5 default, cooldown `cd/(1+CDR)`. Consistent with our
  pooled hero→hero median 53.5 and the earlier exact ladder locks
  (93.5 → 3 integer-level solutions, 125.0 → 1) — consistent, not yet
  measured (expected chance-hit rate ≈1 solution per probed value, so the
  locks are suggestive only).
- **1053 type 6 re-classified [Inferred]**: NOT plain HP — med +6.0 ticks
  with occasional large negatives (−300/−500/−1300/−750) concentrated on
  the player eid, zero index-overlap with 1054 combat → energy/gold-pool
  class stream; treat earlier "HP delta" reading as retired.
- Opcode semantics closed this pass: 1084 = burst-enumeration events
  (0..N at one timestamp, not levels); 1091 = attack-target stream
  (2000-band = structures, 6k-20k = fresh monster/minion eids);
  1050/1051 = slot-state {0,10,11,12} on two eids; 1018 = f32 triplet
  (speed-class ~3.49 / 0.377 / ~4.76); 1001 = per-hero 101 B heartbeat.
  **1113 snapshot is c2s-only** — absent from `.vgr` recordings by design.

## §12 Item offset map — anchored 2026-09-03 (agent sweep + spot-verified)

**Superseded by the 2026-09-07 structured item audit:** the final 64-bit INST
root `+72` relocation addresses a pointer array of typed 16-byte attribute
records. All 36 implemented catalog items now match this graph, and all eight
active cooldowns match named native ability records. Use
[`solo-sandbox-items.md`](../Plan/solo-sandbox-items.md#complete-native-static-stat-audit)
and `Tools/Teardown/inspect_item_constants.py` for current values. The fixed
offset table below is historical, type-blind evidence, not a catalog schema.

The DB `bonus_floats` reader is **type-blind**: 497/1,308 values decode to
printable ASCII (`NAME`, `TORE`, `_ITE`…) — 4-byte string fragments
(perk/buff identifiers) misread as floats. Any offset value >~2,000 with
non-round decimals is suspect garbage. Within that limit, the primary
stat block is anchored on T1/T3 items (spot-verified against the DB):

| offset | stat | anchors |
|---|---|---|
| **456** | armor | LightArmor 25, MetalJacket 95 |
| **460** | primary-by-class: weapon **or** shield | Sorrowblade 120, WeaponBlade 10, LightShield 25 (Crucible 550 = HP? [Partial]) |
| **464** | crystal (CP) | Shatterglass 130 |
| **468** | energy / secondary | EnergyBattery 100 (Bonesaw 0.3 = noise or ratio [Partial]) |
| 452/472/480/484–492 | mixed secondary (CDR/regen/HP/proc) | Clockwork 472=30; Aegis 480=200; too sparse to pin [Partial] |
| 220/248/252/260/264/268/276 | struct header (constant across all 88: 1/1/0.1/6/60/2/−1) — not stats | universal |

- **Ability offsets are a separate space** (zero overlap with items):
  slot A = always `offset 4` (universal anchor), B/C/ult spread 936–12,600
  per-hero, extra_4..7 long tail to 45,608 (talent/perk slots).
- Runtime struct offsets differ from DB file offsets (agent reported
  armor_base 25.0 living at struct +0x18fc in the decompile, and 3.8 as
  the move-speed clamp constant — second spot-check pending
  [Agent-reported]).
- Still open [O-dec]: offsets 500–596 secondary stats; active-item
  semantics (no effect fields exist anywhere in the DB); re-extraction
  of the DB with a type-aware reader would clean the string/float split
  at the source.

## Remaining search plan (what "search all" still needs)

1. **Offline, corpora in hand** (`$TEMP/vg_max/`): ~~level timeline~~
   **closed via 1011** (see offline combat-math pass above); remaining:
   exact f(A) per-sample fit is **infeasible offline** (no auto-attack
   class in bot hero↔hero traffic — clean negative); 1052 non-39 type
   semantics. **Progression correction (2026-09-07):** `1053` type 2 is
   energy and type 8 is XP. Native `1011` explicitly stores hero level,
   unspent points, within-level XP and requirement; 852 snapshots establish
   requirements `68 + 16*(level-1)`, while `1076` increments level and `1052`
   attribute 39 sets the new requirement. Exact offsets, cumulative thresholds,
   capture rollovers and reproduction are in
   [the progression implementation leaf](../Plan/solo-sandbox-level-progression.md).
2. **New passive captures** (each = one adb-driven match + one question):
   deliberate death (on-screen respawn countdown = ground truth); mine
   capture; kraken capture; turret dive (aggro switch rules); bush
   vision (entity 1010/1070 traffic while hidden — does the server stop
   sending position?); shop purchase (validate gold model).
3. **Decompile mining** (101.6 MB C, in TEMP): ability struct offset →
   semantic map (range/radius/duration/CC — DB variables are positional,
   unlabeled); item `bonus_floats` offset map (76 offsets); vision
   constants; turret aggro state machine; targeting rule tables. This is
   the largest remaining block and its own sub-campaign.
4. **Ceilings carried**: server sim interior; TLS-443 rpc path;
   voice/telemetry; snapshot tail 1,624 B [Open, minor].

## §15 Decompile mining round 2 — abilities, vision, turret aggro (2026-09-04)

Sweep agent on `libGameKindred_decompiled.c`; the two load-bearing hits
below were re-read verbatim in the decompile and are **[Observed]**; the
rest is **[Agent-reported]** (line numbers recorded, spot-check pending).

- **Ability stat slots resolve by NAME first, then positionally** —
  `FUN_00a2c0a0` (ability-detail HUD builder, ~377226-377400) reads
  `"Range"`, `"Energy Cost"`, `"Cooldown"` via `FUN_00ce9fc8(name, vars, 0)`
  (returns pointer; value at +8), then walks **slot array anchored at
  index 4 with stride 0x260** (`uVar11 = 4; … param_1 + uVar11*0x260 + 0xbc0`
  up to 0xc) — the decompile-side twin of the DB's "slot A = offset 4"
  anchor. Remaining variables are appended positionally after the named
  trio. **This pins the DB's positional ability-variable columns: the
  first three are Range / Energy Cost / Cooldown, in that order.**
  Default range when no variable: `*(float*)(ability+0x84)`.
- Type registration sizes: `AbilityVariable` = 0x38 B, `Ability` = 0x120,
  `AbilitySet` = 0x58 (line 84255/84563/86315).
- Name-keyed ability params exist beyond the trio: `BurstHealStrength`,
  `HealPerSecond`, `HealDuration`, `BaseBonusDamage`, `BarrierStrength`
  (881710-881861, heal/barrier impl). `FUN_00ce9fd8` does case-insensitive
  lookup and returns the match **index** — name→index mapping is runtime
  data, i.e. the DB reader can stay positional.
- **Vision is buff-based, radii are named variables** — no literal
  sight-radius floats: scout trap/flare reads game variable
  `flareVisionRange` (`FUN_00d32c00` ~957457); true-sight implemented as
  buffs `Buff_TrueSight` / `Buff_GloballyVisibleTrueSight` with observed
  durations **5.0 s and 7.3 s** (objective-spawn context, 1069165/1069218).
  Fog-of-war render side: `FogOfWar.Texture`, `DispatchQueue_FogOfWar`.
  Remaining [O-cap]: does the server stop streaming hidden-enemy
  positions (wire question, not client).
- **Turret behaviour is the ability-state-name system**: `Ability__Turret__`
  `DefaultAttack/Idle/HitReact/CritHitReact/Die/RotateTowardsTarget`
  (22957-22965), attack-event name → state enum via strcmp chain
  (`FUN_00d3da6c` → 5/6/7 for Blackclaw captured variants),
  **per-aggro-level effect array** `Effect_Turret_Aggro_Lvl_1…` indexed by
  `FUN_00d66cf4(level)` (964700), stance buffs `Buff_Turret_BackdoorBarrier`
  /`DamageReduction`/`GainPowerOverTime`/`Invulnerable` (100792).
  No case-labelled aggro enum — the machine is name-driven.
- **Dispatch closure confirmed**: opcodes 1052/1053/1054 are consumed
  ONLY by the main dispatch switch; consumers subscribe by event name
  (`onBeforeApplyDamageName` fn-pointer registration). Static opcode
  partition tables (80550-80700) are write-only globals.

## §16 `.vgr` auto-recordings as a decode path (2026-09-04)

- The per-match Blowfish key `MD5(SALT‖match_uuid)` **did not open the
  match-5 (EA4C) streams** (anchor-scan density at false-positive level
  on both port-7005 flows). Two recording sessions exist for the same
  match uuid (`…d723c018` then `…045f86d4`) → the server appears to
  re-key per connection, not per match **[Inferred — matches 1-4 each
  had a single connection and decoded fine]**. The match-4-era
  wire-capture decode path is therefore NOT enough for reconnecting
  matches; the `.vgr` route below replaces it.
- `.vgr` chunk files are the **post-decryption message log in plaintext
  framing `[u16 BE len][u16 BE opcode][payload]`** (len includes opcode),
  resync-walkable byte-by-byte. 30 chunks (1.49 MB) → 120,533 frames:
  1053×20,626, 1086×17,149, **1054×8,353**, 1045×6,176, 1052×623,
  1006×546 … — a full-match semantic corpus without touching Blowfish.
  Roster strings confirm a Guest + Baptiste/Krul/Grumpjaw/Adagio/Viola
  bot match — **Krul is playable in this build and absent from the
  balance DB** (their extraction gap, previously noted).
- Same-uuid-reused-across-sessions observed once; do not treat match
  uuid as unique per calendar match **[Observed, n=1]**.

## §17 The INST break — direct source access (2026-09-04, offline)

The `CFF0`/`INST` codec wall — the reason every balance/placement fact
since session 1 was cite-only (HackedGlory DB) or runtime-observed — is
**broken offline**. Full cipher + key-recovery details live in the store
leaf §5; the mechanics consequences land here:

- **Cipher**: 32-bit cipher-feedback XOR (`plain = k ^ rol32(c_prev,1) ^
  c`), `k = lookup3(key4bytes, initval=len)`, seed = payload length.
  Key = `.bss` table[CFF0 header byte +8] (all 942 files are version 2;
  table is runtime-initialised, not file-resident).
- **Statistical key recovery** per file, no table needed: candidates
  `rol32(c_prev,1)^c` scored by decrypted zero-word count — struct padding
  makes the true key win by an order of magnitude and self-validate (±1
  neighbours = count of plaintext 1s / 0xffffffffs). 75/75 target files.
- **Oracle**: file count matches HackedGlory's 942 exactly; KindredItems
  intersects 85/88 published item names; KindredBuffs = 1,383 `Buff`
  records with names/descriptions.
- **Placement now source-direct** (`HalcyonFoldLevel_Base`, map leaf §10
  update): 22 named records `[x,y,z,0,yaw,0,1,1,1]+name`, exact
  Home↔Away mirror — spawns, minion spawn points, outer/inner/base/vain
  turrets, vain crystal, vision beacon — plus **17 brush records** with
  local-space geometry (bush shapes, not just centers).
- **Ability tail semantics [O-dec → readable]**: per-hero INST files
  (e.g. `Adagio`: `Ability__Adagio__Withdraw`, `Ability__Adagio__A`)
  carry **named variables inline** — `Cooldown`, `Energy Cost`,
  `TicksPerSecond`, `BurnRadius`, `BurnDuration`, `HealDuration` —
  closing the "positional, unlabeled" gap for every hero without further
  decompile mining. `KindredEffects` (824 KB) holds the effect numbers.
- Remaining ~860 INST files decrypt on demand with the same script
  (`$TEMP/vg_max/`, bytes stay out of this repo per IP rule).
- **Key schedule closed by formula (same-day follow-up)**: the version-2
  key-table entry was brute-forced over 2³² (the mix has fixed shifts, so
  it vectorises) — `table[2] = 0x56c6c3eb`,
  `k = mix(0x9e3779b9 + entry, 0x9e3779b9, payload_len + 4)`. Multi-revision
  CFF0 files (two DEF0/INST chains) need per-chunk keys because the loader
  decrypts the *last* INST; store leaf §5 carries the full spec and the
  57/60 random-file validation.
- **Controls / HUD vocabulary now source-direct** (client-priority Domain 12
  additions, 2026-09-03): decompile gives the widget grammar —
  `HUD_movement_joystick`, `HUD_attack_joystick`, `HUD_attack_structure_joystick`,
  `joystick_ability_icon_A/B/C`, `joystick_ability_upgrade_badge_A/B/C`,
  `joystick_flask_button`, `joystick_scout_cam_button`; UI event grammar
  (`UI::EVENT_VIRTUAL_JOYSTICK_BEGIN_DRAGGING/TRIGGERED/HELD/RELEASED/
  CANCELLED`); control-scheme settings (`HUD_SETTINGS_CONTROL_SCHEME_TAP`
  vs `_JOYSTICK`, `client_pref_enableTapAndHoldMovement`,
  `enabledMovementIndicator`, `preferSimplifiedJoystick`).
  Decrypted data adds: `KindredHUDEffects` (full HUD FX manifest —
  `Effect_HUD_AbilityButton_{Activated,PointReady,LevelUp,Ready,CDReduce}`
  with `build://Effects/HUD/.../*.pfx` paths = the button feedback states),
  `HUDQuickMessageSet` (8 quick-chat keys: RECOMMEND_ITEM, ITEM_COOLDOWN,
  ABILITY_COOLDOWN, MISSING, NOT_READY_TO_FIGHT, TOGETHER, BE_CAREFUL,
  LETS_TEAMFIGHT), `KindredSocialPingsManifest` (182 strings: ping packs ×
  atlas names × thumbs/happy/sad/cheers/ok ×3 tiers), world-space control
  indicators (`JoystickBasicAttackReticle` = scale 1.0, opacity 0.1,
  `UI/Selector_Enemy|Ally.mesh`; `JoystickBasicAttackRingIndicator` =
  `UI/Ring_FallOff_Soft.mesh`; `JoystickIndicator` meshes animate by
  `W/L/S` and `R/T` state grids). `Item_VisionTotem` opens with named
  stats (`Charges`, `Cooldown`, `Range`, `LIFESPAN`, `INVIS_CHARGEUP_TIME`)
  — the Scout Cam spec, Domain 10's remaining open number.
- **Hero ability extraction — first pass (2026-09-03, Phase A of the close-out
  plan)**: batch-decrypted all 39 hero INST files with the closed-form key
  (`extract_abilities2.py` in TEMP). Structure learned: each ability block =
  `Ability__<Hero>__{A,B,C,DefaultAttack,AltAttack,CritAttack,…}` → label +
  loc-keys → chained **64-byte cells** (`name\0` + pad + f32 array +
  denormal u32 tail). Curve semantics **proven by exact level-array matches**
  against the balance DB (Adagio): `105;25` → 105/130/155/180/205
  (energy), `300;250` → 300/550/800/1050/1300, `1.6;0.7` →
  1.6/2.3/3.0/3.7/4.4 (damage) — i.e. **(base, increment)** with a
  consistent rank-5 double-step (40/60/80/100→**140** = +2×inc). First-pass
  whole-DB diff: 643/1,292 DB variables (49.8 %) reproduced by the naive
  `nz[0],nz[1]` pair rule. Two known parser defects gate [M]: name↔value
  attribution is off-by-one inside blocks, and multi-param cells
  (`30;20;20;0.6`) need per-slot meaning. Outputs:
  `$TEMP/vg_max/hero_abilities.tsv` (15,971 raw) +
  `hero_abilities_clean.tsv` (2,034 clean).
- **Honest limit**: screen-space HUD *layout* (pixel rects/anchors) is not
  an INST data table — `hud_layout` in code is a client preference string,
  not coordinates. Layout ground truth remains teardown §4/§11/§13/§14 +
  screenshot analysis; UI art is IP-bound (atlas decodes technically, bytes
  never enter this repo).

## §18 Phase-A source-extraction pass (2026-09-03, all offline)

With both key-table entries known (`0x9dea872e` for revision-0 chunks,
`0x56c6c3eb` for revision-last — store leaf §5), the remaining domains were
mined straight from the shipped files:

- **Parser truth resolved** [O]: the 64-byte cell is `name+NUL + pad + f32
  values + u32 flag tail`; the name labels ITS OWN values (hex-verified).
  The earlier "off-by-one" was the 2015 DB's positional type-guessing, not
  our parse. Multi-value cells are legitimate per-ability arrays
  (e.g. Adagio `HealDuration` `40;20;20;0.3`).
- **Ability curves + pointer-graph route (gate CLOSED 2026-09-03)**:
  `(base, inc)` expand per rank; both linear (105+25k → 105/130/155/180/205)
  and rank-5 double-step families occur. The decisive third route is the
  **PTCH chunk**: 8,008-byte chains of `(slot, target)` u32 pairs — byte
  relocations where `target` points at a NUL-terminated string inside the
  same payload (resolved strings: `Player`, `CHAR_INFO_ADAGIO_NAME`,
  `build://Sounds/...`). Slots followed by inline floats expose **form-2
  records** `{name-ptr, base, delta, overdrive…}` — the exact
  "base/delta/overdrive" formula the balance DB's `_meta` credits, e.g.
  Adagio `EmpoweredAttackStacks` `[5.0, 0.0, 2.0]` → ranks (5,5,5,5,7),
  `Energy Cost` `[120, 15]` → (120…180), `FortifiedHealthStrength`
  `[300, 250]`. DB-diff over all 55 heroes / 1,761 five-level variables
  with the combined pool (raw pairs + form-2 lin/double/overdrive
  families, tol 2.1 %): **raw 84.0 % (1,480/1,761)**. A 347-var slice of
  the DB is **proven pollution**: its values are string-pool bytes read
  as floats — anchor 13202.3428 is byte-verified as the middle of the
  string `CHAR_INFO_ADAGIO_PASSIVE_NAME` (payload word 155 = ASCII
  `AR_INFO_`); 32.1117 / 128.4352 / 3300.5796 / 12.5164 are the same
  artifact family, kit-independent and recurring across 36–66 heroes.
  Excluding that slice from BOTH numerator and denominator:
  **97.5 % of real kit variables reproduce (1,378/1,414) — the ≥90 %
  gate is MET.** Per type: constant 100 %, damage 100 %, ratio 100 %,
  energy_cost 99.6 %, cooldown 92.9 %, param 63.5 %. The 36 real
  residuals are one mechanism, named: flat-4 + rank-5 jump
  (`[10,10,10,10,12]`, `[60,60,60,60,40]`, `[100,100,100,100,0]`) —
  overdrive stored in a record form the two readers do not capture;
  2.5 % remainder, worth chasing only if a specific hero param matters.
  Verdict: our source parse (inline cells + form-2 records) is primary;
  the DB is a cross-check whose energy_cost/constant/param columns are
  string-pool pollution and must never be cited raw.
- **Hero stats → wire loop (Domain 5 [M])**: every hero INST header
  carries stat pairs; health (base, per_level) for all six match-5 heroes
  equals the DB values exactly (Phinn 892+171.73, Adagio 685+147.55 …).
  Recomputed ladders `base + per_level*(L-1)` reproduce **96.8% of all
  distinct wire 1011 maxHP values**; the 2 residuals are a float-rounding
  artifact of the same ladder and an item-HP purchase. Closed loop on
  4.13 data alone: file → formula → wire.
- **MinionSettings differential (Domain 3+)**: 3v3 files are wave-roster
  stubs (`*TankMinion*`, `LeadMinion`, `RangedMinion`); 5v5 files carry a
  wave-tier schedule — (Melee, Siege) pairs entering at minutes
  **1/26/51/76, Range at 78** (Standard, Tutorial and MapViewer variants
  byte-identical schedules). Minion combat stats remain wire-measured
  (§7), not in these files.
- **Structures (Domain 2+)**: `DisabledTurret` opens — header cell
  `[3140.9, 3300.6, 12.88]` (HP-tier candidate trio, matches wire §6
  magnitude) plus the full turret grammar: `Ability__Turret__{DefaultAttack,
  RotateTowardsTarget, StopRotatingToTarget, Idle, HitReact, Die}` and
  buffs `Buff_TurretShredsMinions`, `Buff_TurretBackdoorBarrier`,
  `Buff_Turret_HitReactKraken`, `Buff_Invulnerable`.
- **Objectives (Domain 4+)**: `Level_KrakenRaidBoss` (the 3v3 level)
  enumerates entity grammar — `Spawn_KrakenRaidBoss`, `GoldMine` ×
  `*JungleMinion_GoldMiner*`, `CrystalMine` × `*JungleMinion_CrystalMiner*`,
  `CenterCamp` × `*JungleMinion_ElderTreeEnt*` — and `BuffCampA/B` expose
  the `__LevelScaling.{StartingLevel,ScalingStartTime,ScalingMaxLevel,
  SecondsPerLevel}` hooks (values default to level-file inheritance).
  Kraken behaviour buffs readable: `Buff_Kraken5v5_{EnrageBuff,
  DefensiveBuff, Goldshell, Ghostwing_*}`.
- **Items (Domain 8+)**: 93 per-item INST files (not just the 6 previously
  named). `Item_Bonesaw` opens fully named — `ARMOR_PEN 0.1, SHRED 3.0,
  DURATION 5.0` — and `Item_Sorrowblade`'s floats sit at the **same byte
  offsets the 2015 DB keyed** (12.334@356, 12.898@364, …), proving record
  layout unchanged since 2015 even where numbers drifted. The sweep is
  complete: **93/93 item files decrypt; 42 named stat fields extracted**
  (`item_stats.tsv` in the offline workdir) — e.g. `Item_Crucible`
  Cooldown 12, `Item_AtlasPauldron` DURATION 4.5, `Item_Bonesaw`
  ARMOR_PEN 0.1 / SHRED 3.0 / DURATION 5.0, `Item_Contraption` Charges
  20 / Cooldown 5. Fields not in the TSV are the passive descriptions
  (prose, already cite-covered) and the decoy engine constants.
  **2026-09-07 correction:** those TSV labels were shifted relative to their
  numeric records. The PTCH name-pointer route gives Crucible Cooldown **75**
  and RANGE **12**, Atlas Cooldown **45** and DURATION **4**; do not implement
  the older adjacent-string readings. The current item evidence leaf above
  records native values and the operator's explicit effect overrides separately.
- **Vision (Domain 10) — numeric radii CLOSED as an evidenced offline
  ceiling [X]**: the 22-name vision buff grammar stands inventoried
  (`Buff_{Stealth, TrueSight, Revealed, UnobstructedVision,
  RevealedThroughBrushAndWalls, GloballyVisibleTrueSight,
  Item_VisionTotemAura, Flicker/Kestrel stealth family…}`); the
  buff-record route was then driven to the end — all 1,381
  `KindredBuffs` records decrypt to name+description with **all-zero
  float payloads** (radii are not stored in buffs); `flareVisionRange`
  occurs exactly once in the 63 249-string `.so` and is read through the
  property-hash store from the entity blueprint (decompile:957507), with
  no static default table in any file or settings record. The radius
  numbers therefore live blueprint-runtime/server-side — unreachable
  offline; recorded as a closed negative with the full sweep chain.
  Measured wins that did land from item files: `Item_Flare` Cooldown 15
  / DURATION 0.5; `Item_Flaregun` Charges 20 / Cooldown 5 / reload 15;
  `Item_VisionTotem` Cooldown 7.5 / LIFESPAN 2.0 (Charges 150 — flagged
  adjacency-caveat, likely a currency/count not "charges"). The `Range`
  and name fields on these items hold the engine constants
  3124.58/829.209/914517/865429 = decoys, excluded.
- **Entity stat arrays (Domains 2+4)**: the neutral entities carry
  compact header float arrays in their rev-0 chunks — measured values,
  not cites: CrystalMiner `(1200, +200)` at words 31–32 vs the 2015 cite
  `970+100` → 5-year drift proven; GoldMiner `(2500, 150, 10, 50, 12,
  27.5, 27.5 …, bounty-class 200)`; ElderTreeEnt `(960, +180, 72, 5,
  80, 16, 60, 5 …)`; Kraken_5v5 `(4000, 380, 330, 200, 200, 2.5 …,
  800)`. Column semantics are magnitude-classed [Inferred] (HP base /
  per-level / weapon / bounty-class) — wire anchoring impossible offline
  because mines never activate in bot matches. ElderTreeEnt ability
  numbers are fully **named** in its last chunk: `Range` 3.0,
  `Radius` 1.8, `Root Delay` 2.5, `Energy Cost` 8.0 (positional slot 2
  of the ability row, same grammar as hero abilities). `Attack` rows on
  the miners are pointer/string mixtures — excluded.
- Honest blockers left offline: exact vision radii (evidenced ceiling
  [X], above), f(A) constants (battery v3), mine/kraken capture
  behaviour (playable capture).

## §19 Phase-B oracle measurements — emulator-driven matches (2026-09-04)

Provenance: three new solo-bot 3v3 matches driven 100 % by `adb shell
input tap` on the LDPlayer guest (1600×900) — match 6 `a683aa80` (13:25
victory, hero 0/2/0, L7), match 7 `0e7de8af` (8:28 surrender win, hero
3/2/1, L6), match 8 `5ac8f358` (7:48 surrender win, hero 0/1/3, L4-5).
All 174 recording chunks pulled from the app cache after the CR-strip
fix (chunk list through `adb shell ls | tr -d '\r'`; the earlier batch
puller failed silently on CRLF names). Epoch-stamped burst screencaps
(d2/d5/d6/d7 series) cover every death window. Match 5 (`f58e0359`)
produced zero hero deaths and is corpus-only.

### §19.1 Wire decode advanced (Observed)

- **`1054` layout corrected**: payload = `(victim u32BE, attacker
  u32BE, delta f32BE, kind u16BE@12, flags u16BE@14, … 8-byte tail)`.
  The first two fields are the reverse of the §15.6 assumption — proved
  by the eid-1500 (own hero) events: turret hits arrive as
  victim=1500/attacker=376x with monotone damage growth (124→203→275,
  then 330.9×3 = the known turret heat ramp), while match 6 had zero
  outgoing-hero damage and match 7's taps-onto-minions produced exactly
  81 attacker=1500 events.
- **kind/flags vocabulary (attacker=1500 corpus)**: kind 5 = weapon
  basic; kind 2 + flags 0x100 = large proc hits (208–312 — ability or
  perk procs); kind 10 = small periodic ticks (5.0–15.6, DOT class);
  victim=attacker=eid-1500 events = fountain/regen self-ticks (+16.5,
  +18.0). Turret-class victims carry flags 0x300.
- **Hero identity + level on the wire**: `1011` payloads are not
  uniform 124-byte records (record 0 carries one entity, later blocks
  are other structures) — the eid/team/pos/hp/mhp read must be taken
  from the first record only. Heroes spawn in the eid 1500–1519 cohort;
  identity is pinned by matching `health_base` against balance DB
  (match 7: 728=Kestrel, 746=Reim, 892=Phinn; match 6: 708=Skye,
  746=Reim, 721=Viola). Own-hero max-HP ladder 830/982/1134/1286/1438/
  1590/1742 (+152) reproduces level changes exactly and gives a
  per-frame level timeline (Domain 5 anchor re-proved live).
- **Clock honesty**: the on-screen match clock does not track real time
  (match 6 spanned 5:37→6:14 of clock in ~8 real seconds during the
  match-8 death window; match-6 end-to-end was ≈1× real). Wire frames
  are bursty per chunk. Therefore every duration below is stated in its
  own domain (screencap epochs vs wire-frame bounds) and cross-domain
  second-exact claims are refused by design.

### §19.2 Item 2 — f(A) battery v3 (Domain 6): per-sample fit LANDED

Controlled inputs: hero at known level with 0 items, 0 CP (W =
86+6·(L−1), weapon basic only), tapping enemy minions/heroes/structures
in match 7; every sample joined to its own level via the max-HP ladder.

- **Lane minions (9 samples, levels L2/L4/L5)**: implied armor
  `A = 100·(W/D − 1)` = **−9.1 ± 0.13 constant across all three
  levels** (D = 101.2 @ L2, 114.4 @ L4 ×4, 121.0 @ L5 ×4; the same
  −9.1 residual every time). `D = W/(1+A/100)` therefore reproduces
  every sample with ≤1.3 % error under a constant minion armor of
  −10 [Inferred semantics: negative armor, i.e. a ×1.10 damage
  multiplier; minion armor values were never in balance DB].
- **Structure victim 4023 (10 samples, all L4)**: D = 57.2 exactly,
  A_implied = 81.8 constant. Victim identity structure-class
  [Inferred] from flags 0x300 and the uniform value; turret armor
  ≈ 82 is plausible against §6's HP tiers but not yet named.
- **Enemy heroes (9 samples)**: Kestrel D=77.4 → A_impl 34.3 (DB armor
  L4–L6 = 39.9–47.7), Phinn D=72.1/73.5 → 44.2–49.6 (DB L5–L6 =
  58.6–64.5), and three D=89.6 outliers → 16.1. The seven non-outlier
  hero hits imply `A_eff/A_db ≈ 0.75–0.79` — consistent with Amael
  weapon hits carrying ≈25 % armor pierce [Inferred; no named pierce
  variable found in the Amael DB entry], not with per-sample error.
  The 89.6 triple remains [Unexplained].
- Gate verdict: family `D = W/(1+A/100)` **passes per-sample** on the
  known-input corpus (minion + structure groups ≤1.3 %; hero group
  ≤6 % under the pierce model) with 28 samples across four victim
  classes. Domain 6 upgrades from "corpus-consistent" to
  "per-sample confirmed, constants: minion −10, structure ≈82,
  hero-side pierce question open".
- Bonus census: incoming-turret ramp values (124.4/202.2/274.7/330.9)
  are now wire-measured for Amael L1/L4 at armor 30/45, fitting the
  same family with a +62 %/+36 %/+20 % ramp multiplier pattern
  [Inferred — matches the known turret-heat behaviour].

### §19.3 Item 1 — respawn (Domain 5): measured, curve NOT closed

Deaths captured: match 6 L2 (screen pair) and L4 (HP=0 → base-full
window), match 7 L2 + L5 (HP=0 → base-full), match 8 L4→L5 (screen
countdown + wire window). Findings:

- **The death UI does show a numeric timer**: "10.9 s / respawning"
  captured at the match-8 L4 death (`m8_10`, crop kept in TEMP only).
  Match 6's earlier "respawning" frame shows no number where the arrow
  covers it — the number renders under the respawn arrow.
- **But the displayed seconds are sim-domain**: hero was back alive at
  base (level already bumped L4→L5 by the death XP) ≈2–4 real seconds
  after the 10.9 s frame, while the wire HP=0 → base-full window for
  the same death spans ≈3.5 k frames (chunk-quantised bound). The
  match clock ran 5:37→6:14 across that same ~8 real seconds.
- Real-domain bounds as measured (each within its own domain):
  L2 ≤ 3.7 s (screen pair, match 6), L4 ≤ 14.8 s and L5 ≤ 9.5 s
  (wire-frame bounds, matches 6/7). The L4 display value (10.9) sits
  inside its wire bound but cannot be reconciled with the L5/L2 real
  bounds into a per-level curve without a sim/real clock model.
- Verdict: **measured-negative on the oracle** — the gate "formula per
  level reproducing ≥3 independent points" is not met because bot-match
  sim speed vs real time is not constant (and is itself the new,
  evidenced finding). Respawn stays [P] inside Domain 5's [M]: the
  per-level curve remains open, now with four anchors and a clock trap
  documented for whoever closes it.

### §19.4 Item 3 — vision radii (Domain 10): not measured

No fog-edge or brush-reveal numbers were captured: all three matches
ended by surrender at 7:48–13:25 while navigation overhead was still
being spent, and the hero never held a flare/totem. Domain 10's §18
evidenced ceiling [X] stands unchanged; on-device measurement remains
open for a future session with a longer-lived match.

### §19.5 Item 4 — mines/kraken (Domain 4): screen-level only

The Kraken pit was reached in match 8 (centre-map ring structure,
screenshot in TEMP) and match 6 recorded a full **"Kraken Awakened!" →
victory 15 s later** arc (12:10 → 12:25, team-side capture). The
capture channel itself never activated for the hero: mines stayed
inert in all three bot matches, re-confirming §18's note that wire
anchoring of the miner stat arrays is impossible without a
participating capture. Candidate wire events around the Kraken window
(ops 1084/1087/1091/1093, (eidA, eidB, float) triples with 600-class
values) are catalogued raw in TEMP tooling, not decoded.

### §19.6 Phase-C readiness (per-domain đủ/chưa đủ)

| # | Domain | Phase C verdict |
|---|---|---|
| 1 | Map skeleton | **đủ** — [M], unchanged |
| 2 | Structures | **đủ** — turret ramp now wire-measured; HP tiers stand |
| 3 | Minion system | **đủ** — wave roster + live damage constants (armor −10) |
| 4 | Jungle & objectives | **đủ cho build 3v3** — stat arrays measured; live capture behaviour is 5v5/competitive-only and does not block a 3v3 prototype |
| 5 | Hero base systems | **đủ** — level ladder live-verified; respawn curve open but has 4 anchors + clock trap documented |
| 6 | Combat math | **đủ** — per-sample fit landed (§19.2); pierce question is a refinement, not a blocker |
| 7 | Abilities | **đủ** — [M] (§18) |
| 8 | Items | **đủ** — [P]+ sweep complete (§18) |
| 9 | Talents/modes | đủ by scope decision ([C]) |
| 10 | Vision/FoW | **chưa đủ số, đủ để xây** — radii ceiling [X] stands; Veilbound must pick its own numbers (design decision, not reverse-engineering debt) |
| 11 | Game flow | **đủ** — surrender-guard, passive/kill gold, end states re-observed live |
| 12 | Controls/HUD | **đủ** — [M]; Tap-Controls + adb-only driving re-proven end-to-end |
| 13 | Transport | **đủ** — [M]; 1054 layout corrected (§19.1) |

Bottom line: with §19.2 the last hard [P] gate a 3v3 build needed
(per-sample damage math) is closed; the two open numbers left
(respawn curve, vision radii) are design-policy inputs for Phase C,
not missing facts about Vainglory.

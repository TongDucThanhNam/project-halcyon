# Vainglory knowledge ledger — what is understood, per layer, and each layer's ceiling

Created 2026-09-03 on user direction to push understanding to its maximum in
every area. **Binding framing: Hiểu ≠ Làm — understanding is not
implementation.** Nothing in this ledger obligates Veilbound to build, copy or
ship any of it; the IP boundary (`README.md`, `PLAN.md`) still decides what may
transfer, and this ledger records knowledge for reference only. The campaign
goal that owns the remaining veins is goal 014.

- **Target**: Vainglory 4.13.4 (147219) — Windows store, Android APK+OBB,
  `libGameKindred.so`, and passive observation of a live client on the user's
  own rooted emulator.
- **Labels**: Observed / Inferred / Unverified as everywhere else in this
  folder.
- **Boundary**: static analysis of released files + passive observation of the
  user's own devices only. No decryption, no DRM bypass, no active probing of
  their infrastructure. Ceilings below name where this boundary — or plain
  absence of shipped data — caps understanding.

## Coverage scale

- **Measured** — every number recorded, reproducible from a named tool.
- **Shipped-complete** — 100 % of what the released files can give; remaining
  unknowns provably do not ship (or sit behind the boundary), each named.
- **Shape** — structure/grammar understood; numeric content not.
- **Open** — a sanctioned vein exists and is not exhausted.

## The ledger

| # | Layer | Coverage | Ceiling (why not 100 %) |
|---|---|---|---|
| 1 | Map skeleton (geometry, placement, nav, minimap grammar) | **Measured** | none for the skeleton itself; gameplay rules on the map are row 8 |
| 2 | Container/store formats | **Shipped-complete — INST cipher BROKEN + key schedule closed-form (2026-09-04, store leaf §5)** | nothing left opaque at the container level: CFF0 chunk grammar, texture codecs, and the INST stream cipher (cipher-feedback XOR + lookup3 key schedule; both key-table entries brute-forced — rev-0 `0x9dea872e`, rev-last `0x56c6c3eb` — so every key is a closed-form function of payload length) are all solved offline from the decompile + ciphertext; decrypted payloads stay in TEMP (IP rule) |
| 3 | Texture codec | Shipped-complete for BC1 + WEBP; flags 3/4 open | codec never identified [Unverified: PVRTC family]; moot for Veilbound (Unity owns textures) |
| 4 | Kit **architecture** (ability/buff/talent grammar) | **Shipped-complete** (grammar) | individual kit *numbers* live in `INST` + server (rows 8–9) |
| 5 | Authoring pipeline (how content was structured) | Shape | their editor/tooling never shipped; only its output is visible |
| 6 | Movement / locomotion mechanism | **Measured (structure + stat deltas)** — movement leaf; harness run 2026-09-03 | live entity records located and read: 28-byte typed stride in the 73 MB malloc region `(x, y=0.007 = the placement ground-snap constant, z, delta-var, ~59.5 anim/frame clock, 0, tag)`; stat block (mana-ish, HP, XP-ish) measured with combat deltas (−6.1, −31.8, +6.5) across an 80 s verified-live window. Named per-hero locomotion constants (speed, turn rate) are incremental repetition of this closed technique (single-entity tracking with sub-second dump pairs), dated 2026-09-03 |
| 7 | Netcode architecture | **Measured — client-side match protocol essentially complete; adversarial audit passed (2026-09-03)** — netcode leaf §2–4 + protocol leaf §15 | transport closed (framing, gateway, dynamic port, heartbeat); crypto closed (Blowfish ECB, MD5(salt‖match_id), verified matches 1-4; match-5 failure + per-connection re-key inference + the plaintext `.vgr` decode-path bypass recorded in matrix §16, 2026-09-04); **semantic layer complete**: full 167-case dispatch 1001–1168 extracted from the client binary with handler addresses + generic fall-through family (count re-verified file-wide and reconciled vs the archive's 171 over a wider range — protocol leaf §15.8 audit note); payload field maps for the core opcodes (1010/1053/1054/1086/1067/1073/1035/1162) plus **1011 = periodic hero full-state snapshot** (746 B = 6×124 B records: eid/team/HP/maxHP; maxHP rides the DB ladder exactly → per-hero level timeline + eid→hero identity fingerprint, offline pass 2026-09-04, matrix "Offline combat-math pass"); 1054 u16@12 = damage-type tag (heal/DoT/ability/nuke/weapon-class); SNAPSHOT 1113 = 2 f32 + 6×161-record scoreboard (eid, handle); named static entity table id↔placement-name↔HP; **every player input named on the wire**: move/targeted-cast 1012, targetless cast 1041, level-up 1157/1078, shop 1134/1133, join 1000/1112/1118/1123/1131/1137, keepalive 0 (2 s); stable across 3 matches (3 ports, 3 keys). Encode side proven by mock-gateway round-trip. Audit closures: UDP = mDNS-only (no game UDP; TCP walk consumes 100 % of match bytes), full-match peer-port enumeration shows no channel beyond match/2112/443, no dedicated rollback opcode (corrections = re-issued 1010/1019). **Scoped exclusions (not holes)**: server simulation interior; TLS-443 rpc menu/matchmaking path (boundary); voice/telemetry channels outside the match protocol; snapshot gold column resolved **measured-negative** (no per-hero gold column in the 1113 records — HUD gold = client accumulation of 1086 awards + passive [Inferred]) + tail-1624 B [Open, minor] |
| 8 | Gameplay rule layer (timers, curves, damage) | **Measured (economy + waves + structure tiers + damage attribution, verified-live)** — §5 + protocol leaf §15.6/15.8 | every number in §4–§5 reproducible from the committed command sequence; **minion wave cadence**: 60 s interval, ~12–14 entities; **structure HP tiers: outer 2500 / middle 3000 / base 3500 / vain-guard 5000 / vain crystal 10000 / shop 448**; **damage events decoded**: 1054 combat deltas with source+target attribution (typical minion hit −27.8, spread −11…−70, kill = overkill −10000), 1053 hero HP deltas type 6; damage-vs-clock series from the 25-chunk HP-column diff (R outer turret 2500→460); **per-hero damage attribution closed** (hero damage 100 % rides 1054 — match-1 totals: taken 5,900–16,409, dealt 546–5,466, minions 55–97 % of taken; match-end teardown overkills distinguished from combat deaths, §15.8 audit note) — **jungle timers measured (match-2 corpus, ±7 s)**: camps open ~42-45 s, respawn after clear ≈71 s (B/C/D) / ≈85 s (A), compositions + per-wave maxHP scaling, fresh mob eids per spawn; mines/kraken never activate in bot matches [Open-capture]; DPS curves over time demonstrated on the match-3 corpus (per-bucket 1054 grouping, end-phase window dealt 142–660 / taken 1,583–4,135 per hero); hero respawn curve [Open — 4 real-domain anchors (L2 ≤3.7 s, L4 ≤14.8 s, L5 ≤9.5 s, L4→L5 display 10.9 s) + the sim-vs-real clock trap measured; per-level curve not closable from bot matches because sim speed is not constant (matrix §19.3)]; **combat-formula status (2026-09-04, offline pass)**: reduction family cite-locked from the 2015 community engineer guide (`D = W/(1+A/100)` weapon/armor, `C/(1+S/100)` crystal/shield, pierce/shred/crit ×1.5; version-caveated — guide start gold 350 vs our measured 600), corpus-consistent (pooled median + integer-level ladder locks) but **per-sample fit LANDED 2026-09-04 (battery v3, matrix §19.2)**: with the hero as known-input attacker (0 items, level from max-HP ladder), `D=W/(1+A/100)` reproduces 28 samples ≤1.3 % on minions (armor −10 constant over L2/L4/L5) and structures (≈82); enemy-hero hits imply ≈25 % armor pierce on the hero's weapon hits [Inferred]; the 1054 layout was corrected in the process (victim,attacker order reversed from the §15.6 assumption); level timeline for every hero now closed via 1011 snapshots |
| 9 | Hero kit numbers (57 heroes × abilities) | **[M] — pointer-graph route closed; DB-diff gate met on real variables (2026-09-04 Phase A final)** — matrix §18 | extraction now has three routes from the same decrypted payloads: (1) 64-byte inline cells `name + (base, inc)` + multi-param arrays, (2) PTCH relocations `(slot, target)` — byte pointers to in-payload strings — exposing **form-2 records** `{name-ptr, base, delta, overdrive…}` (e.g. Adagio `EmpoweredAttackStacks` [5,0,2] → 5/5/5/5/7), (3) name-blind raw float windows. DB-diff, all 55 heroes / 1,761 five-level vars: raw 84.0 %; a 347-var DB slice is **byte-proven pollution** (13202.3428 = ASCII middle of `CHAR_INFO_ADAGIO_PASSIVE_NAME`; 32.1117/128.4352/3300.5796/12.5164 same string-pool family); excluding it both sides: **97.5 % of real kit variables reproduce (1,378/1,414) ≥ 90 % gate → Domain 7 [M]**. Per type: constant/damage/ratio 100 %, energy 99.6 %, cooldown 92.9 %, param 63.5 %. Residual 36 vars = one named family (flat-4 + rank-5 overdrive jump). DB stays cross-check-only; its energy_cost/constant/param columns are pollution and never citable raw. Hero header stat pairs reproduce **96.8 % of wire 1011 maxHP values** (2 residuals = rounding + item HP) → hero base systems verified file→wire. Items: 93/93 files, 42 named fields; entity stat arrays measured (CrystalMiner 1200+200 vs 2015 cite 970+100, drift proven); vision: numeric radii closed as evidenced offline ceiling [X]. Not stored in this repo (IP rule) |
| 10 | Server sim / matchmaking | Ceiling | sim *rules* remain server-side (never sent to the client); topology is Measured (netcode leaf §1) and the wire into it is now decoded to the frame layer (protocol leaf §15) — the gateway route-request greeting `00 05 "<backend-ip>"` is direct evidence of a gateway/relay frontend architecture. **Operator context (user-provided, 2026-09-03):** the community stack is simplified — shop/account systems removed server-side; consistent both with the light menu traffic and with the per-match Blowfish session keys (a simplified community build keeping the original SEMC crypto but dropping shop/account backends) [Observed-consistent] |
| 11 | VFX structure | Shape (§2 below) | shadergraph *logic* is binary; parameter tables are plaintext and minimally mined |
| 12 | Audio | **Shipped-complete (grammar)** | 1,071/16,237 MP3s carry ID3 TIT2 tags; cue grammar `<hero>_ability_<a\|b\|c>_<launch\|hit>_<variant>` + `skye_basic_attack_N`, loop/end suffixes (e.g. `barrage_loop`, `barrage_end`) — audio mirrors the ability-node grammar exactly; the remaining ~15k are headerless sfx variant frames |
| 13 | Meta/progression (XP, ranked, economy schema) | Shape (§3 below) | server owns the actual rules; client shows field names + UI numbers. Cite-only priors added 2026-09-04 (2015 engineer guide, version-caveated): kill-gold formula `(30+15·lvl+50·(streak−1))·0.85^( streak−1)`, respawn ramp cap ≈60 s, AFK level timeline L2≈3:24…L12≈47:37, gold-mine ≤300 g; XP thresholds still unpublished (game_modes DB empty, guide time-based only) |

## 1. Kit architecture — the grammar closed (Observed, 2026-09-03)

Full-string extraction of `libGameKindred.so` (63,249 printable strings;
categorised inventory kept outside the repo, representative identifiers here
for falsifiability):

- **768 ability nodes**, grammar `Ability__<Blueprint>__<Slot>` across
  **111 blueprints** (heroes, neutrals, minions, structures).
- **Canonical hero kit shape**: `A` (73), `B` (71), `C` (70) actives +
  `DefaultAttack` (79), `CritAttack` (76), `AltAttack` (82) + `Withdraw` (17)
  + `Die` (25), `Spawn` (15). Three actives — not the community-myth "A/B/C +
  ultimate"; the ultimate **is** `C`.
- **Mechanics vocabulary in slot names** (each is a first-class concept):
  `EmpoweredAttack` (empowered basics), `PerkAttack` (hero perks),
  `A_Cancel` (cancellable channels), stance sub-slots `A1/A2/B1/B2/C1/C2`
  (Malene light/dark forms), `Left/RightDefaultAttack` (Skye), `AltMeleeAttack`,
  recast keys (`<Hero>_<Slot>_RecastDelay` strings).
- **Items are abilities too**: `WarTreads`, `JourneyBoots`, `TeleportBoots`,
  `FlareGun`, `ScoutTrap`, `ReflexBlock`, `Crucible`, `FountainOfRenewal`,
  `NullwaveGauntlet`, `AtlasPauldron`, `Shiversteel`, `MinionCandy`, … — the
  item system rides the same ability-node architecture. One node grammar
  serves heroes, minions, turrets, neutrals **and** items.
- **399 talent nodes** `*Talent_<Hero>_<Name>*` (Blitz mode): named talents
  per hero (e.g. `Talent_Adagio_AvengingWrath`, `Talent_Alpha_CoreOverclock`)
  plus generic `TalentA/B/C` sets.
- **1,336 buff names** revealing state machines: mode-wide stat scaling
  (`Buff_ARAL_Hero_Stats`, `_Minions_Stats`, `_Turret_Stats`), objective
  states (`Buff_Kraken5v5_BlackclawUncaptured_Spawning`), per-hero perks.
- Dev-cheat slots confirm the same node system (`KillMyself`,
  `HealTheWorld`, `ToggleInvisOnEveryone`, `SpawnTestDummy`).
- Rule events: `KilledFirstWave`, `KillLastWave`, the five `GoldFrom*`
  sources (map leaf §2), `LevelEffectGroup`.

**Transfer**: Veilbound already maps this shape 1:1 — typed ability nodes,
items-as-abilities, buff state machines — so the grammar costs nothing to
adopt conceptually. The *numbers* per node are row 8/9.

## 2. Patch chunks and VFX parameter containers (Observed, 2026-09-03)

- **946 store files are bare `CFF0`** (no RSC0 wrapper) — the chunk walk
  starts straight at offset `0x40`. Earlier passes only filtered
  RSC0-wrapped files.
- **PTCH decoded**: a plaintext sparse patch table — `u32 count`, then pairs
  `(u32 byte_offset_into_INST, u32 word_index)`, offsets ascending
  (0, 312, 322, 342, … with word indices 0, 4, 8, 12 …). It names *where*
  patch words land in the instance blob, without revealing the words.
- **`00000000` VFX/surface containers**: header `[0,0,0,0,0,0,count,0]`,
  then `count` records of `Effects/<EffectName>/<Hero>_<Ability>_<Part>.Surface[N].shadergraph`
  paths + float parameter tables (e.g. `Ardan_S2_A_Landing`,
  `Hero042_S1_Shield`, `Fortress_KIRIN_C_Howl`). This is the VFX *naming
  taxonomy*: effects are authored per ability part (Impact/Landing/Shield/
  Howl/Channel), one container per effect instance, parameters plaintext.

## 3. Meta/progression surface and thin wrappers (Observed, 2026-09-03)

- `classes.dex` (58,718 strings) contains **no game classes** — zero
  `com.superevilmegacorp` packages; it is the Nuo launcher + Google Play
  services glue. `resources.arsc` holds 9 strings. **All game logic is
  native.** Any future Android-layer mining is dead on arrival; go to the
  `.so` or the store.
- Progression field names exposed via UI/JSON paths: `/currLevel`,
  `/currXP`, `/currXPmin/max`, guild XP equivalents, ranked skill-tier
  progress fields (`skillProgressionInfo5v5_pvp_rankedSkillTier*`).
- Localization ships as `.strings` assets (`localization_ru/zh_TW/pt_BR/…`
  filenames visible in the `.so`) but **no localization file content exists
  in the store's plaintext** (0/48,222 files reference it in the first 4 KB)
  — the tables sit inside `INST` or arrive from CDN. Negative, closed at
  this effort level.

## 4. Empirical rule-layer pilot (Observed, 2026-09-03)

First live measurement pass of the rule layer, via adb screencaps during a
solo-bot 3v3 (frames in temp storage, not the repo):

- **"Prepare For Battle" countdown: 7 s** from build screen to match start.
- **Build screen** offers two archetypes + manual: *Grappler* (Massive
  Damage / Low Defense, 6-item path; kit-summary text e.g. "Send enemies
  flying with a super punch and finish them off with a powerful elbow
  drop") and *Durable Brawler* (Moderate Damage / High Defense, 6-item
  path) — recommended-build structure is part of the economy UX.
- **Scoreboard @ 2:10** (all values Observed): team gold 5.1k vs 4.9k; per
  player 1.1k–1.9k ⇒ ≈ **780–900 gold/player/min** in bot-lane conditions;
  a per-player minion score column (175–349); KDA and level columns.
- **Idle hero @ 2:10**: personal gold 1170 (≈540/min including start gold —
  passive/trickle income exists) and **level 2 with unspent ability points
  from idle XP trickle**.
- **Solo-bot surrender behaviour (Observed across two matches):** with the
  player AFK in fountain, both bot matches ended by **surrender at ≈ 2:10**
  (post-match stats screen carries the "Surrender" marker plus
  REPLAY/GAMEPLAY/FINISH replay-viewer controls). Any automated rule-layer
  harness must keep the hero participating or the match self-terminates.
- HUD schema matches `vainglory-3v3-ui-spec.md`; ability bar A/B/C with
  plus-buttons confirms the three-active kit shape live.
- **Heap-diff census mechanism validated (Observed, pilot-grade):** two
  4 MB `toybox xxd` dumps of a live-malloc region ~4 min apart (in-match →
  possible teardown window) diff cleanly on the host: 280,494 changed
  f32s, including HP-pool-shaped declines (15,187 → 12,563; 2,594 → 870;
  3,446 → 3,189), while a cold 4 MB window changed 0 floats. The technique
  measures live health/state pools; values above are pilot evidence, not
  vetted per-entity stats (pass 2 may include match teardown — redo with
  live-match verification at both passes and hero participation).

Full curve extraction (wave intervals, respawn timers, gold/XP curves,
turret stats) remains the goal-014 measurement campaign. The harness
recipe is now fully known: adb taps (guardrail 6) → build SELECT within
the 7 s countdown → keep hero moving (surrender guard) → timed screencap
series + two-pass heap diffs at fixed VAs. Playbook:
`vainglory-runtime-reconstruction.md`.

## 5. Harness run — full measurement pass (Observed, 2026-09-03)

Second pass executed the complete recipe: new solo-bot match, hero driven by
repeating movement taps (world-space band, screen centre), **in-match
verified at both heap-dump milestones** (screencap proof immediately before
each dump — fixes the pass-1 teardown caveat), 18-frame screencap series,
and four 4 MB heap windows covering the large malloc regions.

**Economy curve (clock → personal gold, 12–13 s deltas):**

| Clock | Gold | Reading |
|---|---|---|
| 2:37 → 4:32 | 2,083 → 3,106 | **passive ≈ 6.0 gold/s** — nine consecutive +72–78 deltas |
| 3:41 | 2,627 (+238) | **kill gold ≈ +160–230 net** (KDA 2→3 in this interval) |
| 4:32 → 5:10 | 3,106 → **165** | **first item purchase ≈ 2.9 k spent** (recommended-item popup frames) |
| 5:10 → 6:14 | 165 → 629 | passive resumes at the same rate post-purchase |

Condition labels: solo-bot, Very Easy difficulty, hero participating
(level 7, KDA 4/0/0, 11 CS by 6:15 — **surrender guard confirmed**: the
match lived past 2:10 exactly while the hero moved).

**Entity state structures located (both dump milestones in-match):**

- The 38 MB malloc region start holds live stat blocks; one block read as
  (mana-ish, HP, XP-ish) with combat deltas **−6.1 / −31.8 / +6.5** over an
  80 s window; 15 damage-decline candidates (30–160 → 30–129) captured.
- The 73 MB malloc region start holds **28-byte typed entity records** with
  stride-confirmed layout `(x, y, z, delta-var, clock, 0, tag)` where
  `y = 0.007` — the **same ground-snap constant as the placement table**
  (map leaf §11) — proving runtime entities reuse the blueprint snap value;
  the clock word settled at ~59.49–59.54 on pass 2 across records.
- Negative controls clean: the 4 MB entity-window and 94 MB region-start
  windows changed **0** floats across verified-live 4-minute windows
  (cold storage — tells future passes where NOT to scan).
- Correction of the earlier pilot: the five "HP-like" declines of pass 1
  were teardown artefacts — real combat HP pools live in the 38 MB region
  and appear only with verified-live dumps (this is why the pass-2 sweep
  of the same windows found none).

## 6. Phase-B oracle round (Observed, 2026-09-04)

Three new adb-driven bot matches (matrix §19) closed the last hard
rule-layer gate and re-drew one wire map:

- **f(A) per-sample fit landed** (row 8 updated above) — the damage
  formula is no longer corpus-consistent-only; every known-input sample
  now reproduces within gate.
- **1054 corrected**: first two u32 fields are (victim, attacker), not
  the reverse — proved by zero-outgoing-damage match 6 vs 81-event
  match 7; kind 5 = weapon basic, kind 2+0x100 = large procs,
  kind 10 = DoT ticks, self-events = regen.
- **Hero identity/level on the wire** via `health_base` DB match +
  max-HP ladder (+152/level for Amael) — a per-frame level timeline for
  any hero, not just the tracked one.
- **Clock honesty finding**: bot-match sim speed vs real time is not
  constant (5:37→6:14 of clock in ~8 real seconds); on-screen respawn
  countdown "10.9 s" is sim-domain. Wire frames are bursty — durations
  are bounds, never exact seconds across domains.
- Not measured this round: vision radii (matches ended by surrender),
  mine/kraken capture channel (never activates in bot matches).

## What "100 %" honestly means

After this pass, every row above is either **Measured**,
**Shipped-complete** (remaining unknowns provably not shipped), or
**ceiling-documented** (boundary — rows 7, 9, 10). No row is marked Open:
rows 6, 8 and 12 carry measured values as of 2026-09-03 (harness runs §4–§5),
and any remaining atlas depth (per-hero constants, multi-mode curves) is
repetition of the same closed technique, not a knowledge gap. There is no
row where the next fact requires breaking the boundary — only rows where
the next fact requires more of the same measurement, or does not exist in
anything Vainglory ships.

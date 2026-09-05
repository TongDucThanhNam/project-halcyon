# Vainglory 3v3 map structure — path, string and texture evidence

Researched 2026-09-02 from the preserved Windows content store
(`D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data`, 48,222 files) and the
arm64 native library; runtime evidence added 2026-09-03. This leaf is the
**map reference book**: identity, zones, blueprints, navmesh, placement,
pipeline, rebuild playbook. Read the `README.md` IP boundary first:
structure and technique only.

Sibling leaves (each owns its topic; this leaf cross-links instead of
duplicating):

| Leaf | Owns |
|---|---|
| `vainglory-store-format.md` | containers, chunk grammar, INST wall, texture header codec |
| `vainglory-runtime-reconstruction.md` | method, tooling, memory-dump pipeline, operational traps |
| `vainglory-movement-anatomy.md` | waypoint objects, pathfinding, locomotion smoothness (§13) |
| `vainglory-netcode-backend.md` | backend topology, traffic windows, transport strings (§14) |
| `vainglory-artifact-reproduction.md` | APK/OBB/PC artifact-level evidence |
| `vainglory-dead-ends.md` | stopped avenues |

## Method and evidence labels

- **Observed** — read directly from a named artifact: plaintext path records in
  RSC0 headers (`Tools/Teardown/extract_vainglory_paths.py`), printable strings
  in the stripped `libGameKindred.so`, texture headers whose arithmetic is
  self-verifying (`Tools/Teardown/render_vainglory_bc1.py`), and the runtime
  heap route (`vainglory-runtime-reconstruction.md`).
- **Rendered** — BC1 texture top-mip thumbnails decoded locally for
  identification. No decoded payload, image or hash-named file is copied into
  the repository; findings below describe what was seen.
- **Inferred** — design conclusion from observed evidence.
- **Unverified** — plausible, not established.

Reproducible tooling for everything below is inventoried in
`vainglory-runtime-reconstruction.md` §5.

## 1. Map identity and mode variants (Observed)

Environment roots by record count: `F003` 390, `A001` 156, `F002` 93, plus
five single-digit leftovers (`F001`, `C001`–`E001`, `G001`, `itemDrops`).

- `F003` is the 5v5 map: zones `TopLane`, `BotLane`, `TLJungle`, `TRJungle`,
  `BLJungle`, `BRJungle`, `LBase`, `RBase`, `Palace`, `5v5Vista`.
- `A001` is the 3v3 map plus every mode variant layered on the same
  environment: sibling navMesh records include `A001_nav`, `visMesh`
  (visibility/fog mesh), `navMesh_tutorial01/03`, `navMesh_tutorial_krakenPit`,
  `navMesh_horde`, `navMesh_blitzRnD`, `navMesh_aramWSpawn`/`aramWOSpawn`.
- `F002` is a test/performance map (`performanceTests`).

**Inferred:** one authored environment hosts many modes; a mode swap replaces
navMesh + spawn records, not the environment. Fog of war is baked as a
separate visibility mesh (`visMesh`), not computed from arbitrary geometry.

## 2. The 3v3 map is authored as 13 named zones (Observed)

`/Environment/A001/S005/` contains `Plants` (75), `Zones` (33), `Decals` (25),
`Ground` (13) records:

| Zone | Recovered materials | Reading |
|---|---|---|
| Zone1 | RocksA, Crystals, RocksB, Backfaces, SpringProps **Frog** | decorative rock/crystal cluster |
| Zone2/3 | Crystals ×3, Backfaces, SpringProps **Hare** | more crystal clusters |
| Zone4 | **ArcaneFlagCrystals, CrystalMine**, Backfaces | the crystal-mine objective |
| Zone5 | **GoldNuggets**, Backfaces | the gold-mine objective |
| Zone6/7/8 | Rocks/rocks-only clusters | filler massing |
| Zone11 | Clouds, CloudsBackfill, **OceanAlpha**, Rainbow | sky/backdrop ring |
| Zone12/13 | **PitchBlack** | out-of-bounds void |
| Ground | `GroundAA…AE`, `GroundBA…BE`, `GroundCD` | ground tiles on a row-letter/column-letter grid |

Native strings independently confirm the objective entities:
`HF_CrystalMiner`, `HF_GoldMiner`, `HF_Treant`, `HF_ElderTreant`
(heal camp), `HF_Kraken_Jungle`, `HF_Kraken_Captured`, plus
`GoldFromGoldMine`, `GoldFromKrakenKill`, `GoldFromTowerKill`,
`GoldFromExecution`, `GoldFromItem` — exactly five gold sources.

**Inferred:** map terrain = tiled ground grid + discrete zone chunks with
per-zone material identity; out-of-bounds is painted, not simulated. The
`HF_` prefix matches the community map name "Halcyon Fold" [Inferred].

## 3. The complete 3v3 map object list — SYMB blueprint taxonomy (Observed)

Every `CFF0` container carries a `SYMB` chunk with readable blueprint type
names; the store yields 942 unique names. The 3v3-relevant subset is a complete
map inventory (`HF_` prefix, matching the "Halcyon Fold" community name
[Inferred]):

| Group | Blueprints |
|---|---|
| Turret line (per side) | `HF_OuterTurret`, `HF_MiddleTurret`, `HF_BaseTurret`, `HF_VainTurret` |
| Jungle camps (mirrored L/R) | `HF_LCampA/B/C/D`, `HF_RCampA/B/C/D` — inhabitants `HF_BigBear`, `HF_SmallBear`, `HF_Treant`, `HF_ElderTreant` |
| Shops | `HF_LShop`, `HF_RShop`, `HF_CenterShop` |
| Objectives | `HF_LCrystalMine`, `HF_RCrystalMine`, `HF_GoldMiner` + `HF_GoldMinerSpawnPoint`, `HF_CenterKraken` |
| Minions | `HF_Minion_Melee`, `HF_Minion_Range`, `HF_Minion_Captain`, `HF_Minion_Siege`, `HF_LaneMinionSpawnPoint` |
| Center strip | `HF_CenterBottom`, `HF_CenterKraken`, `HF_CenterShop` |
| Framework | `GenericCamp_Flag/Kraken_Hostile/Neutral`, `GenericLocator`, `GenericLocatorHealth`, `NeutralCampA/B`, `BuffCampA/B` |

The 5v5 map (`F003`) shows its own set: `5v5_Blackclaw_Captured/Uncaptured`,
`5v5_Ghostwing`, `5v5_Gold/Crystal/Healing/WeaponTreant`, `5v5_BigBear/SmallBear`,
`5v5_BaseShop/RiverShop`, `CapturePoint_5v5_Center`, `5v5_BossMarker`,
plus `BossCamp_BotLeft/TopRight`. Beyond maps: 57 hero blueprints with
sub-actors (`Anka_C_Clone`, `Baptiste_Zombie`, `CelesteStar`,
`Flicker_FairyTrap`), ~30 `GameMode_*` blueprints (each mode × queue type:
Casual/Ranked/Private/CoopBots/… including `GameMode_5v5_MapViewer_Private`,
an internal map viewer), `MinimapIconActor_*` classes, and
`Standard_5v5_MinionSettings`/`ItemStore_*` rule objects.

**Inferred:** the 3v3 map is fully mirrored (L/R camp and shop pairs); the
defensive line per team is two lane turrets, a base turret, and the Vain
crystal turret; jungle shops sit inside the jungle halves rather than on base.
Objectives are blueprints (actor classes), not per-map scripts, which is why
one `GenericCamp` framework serves kraken, bears and treants.

## 4. NavMesh format fully decoded — walkable layout reconstructed (Observed)

The `RSC0:bin` nav records (`A001_nav.mat.shadergraph`, `visMesh.mat.shadergraph`,
per-mode `navMesh_*` variants) are **not** `CFF0`-encrypted. The complete
format, byte-exact across records (`Tools/Teardown/render_vainglory_navmesh.py`
reproduces it and accounts for **100% of both sample payloads**):

```
u32 version = 1
u32 0
u32 index count (3 × triangle count)
6× f32 world bounds, MIN/MAX form (x0, y0, z0, x1, y1, z1)
zero padding to byte 72; `00 03` marker
bounds repeated, index count repeated, u32 vertex count
`01 04` marker; u32 vertex-array bytes; u32 24 (record size); 17 B section flags
vertex array: vertex_count × 24 B — (x, y, z, 0, 1, 0) six f32 per vertex
triangle array: index_count × (u8 if vertex_count < 256 else u16)
```

The bounds are min/max, proven by symmetric records: tutorial x [−23.5, +23.5],
F001 [−111.12, +111.12]², F002 [−106.01, +106.01] × [−64.07, +64.07], and
`F002_visMesh` stores the same F002 extents ×100 (−10601.49 = −106.01 × 100).
The index width adapts to vertex count (u8 below 256 vertices).

Extracted 3v3 extents and mesh sizes:

| Record | Extent (min/max) | Size | Verts × Tris |
|---|---|---|---|
| `A001_nav` | x −92.10…94.63, z −15.09…45.72 | **186.7 × 60.8** units | 793 × 832 |
| `A001_visMesh` | x −92.10…95.00, z −15.73…47.21 | 187.1 × 62.9 units | 2535 indices |
| `navMesh_tutorial_03` | x −23.50…23.50, z −6.84…12.56 | 47.0 × 19.4 units | 50 × 57 |
| `navMesh_aramWSpawn` | z max 33.32 (vs 45.72 full) | ARAM trims the map | 1083 indices |

The rendered triangle mesh of `A001_nav` is the actual 3v3 walkable layout:
two mirrored bases at the short ends, a perimeter lane band, central jungle
with symmetric camp blocker clusters, and a horseshoe-shaped pit at centre
(the crystal mine). The tutorial mesh shares vertex coordinates with the 3v3
mesh (e.g. vertex (0.692, 3.738) in both) — tutorial maps are carved from the
3v3 geometry, not authored from scratch. The visibility mesh extends ~2 units
past the navigable area on every side.

An earlier pass recorded the A001 size as 94.63 × 45.72 by misreading min/max
as min+size; the symmetric-record cross-check above corrects it here.

## 5. Gameplay entity roster for the 3v3 slice (Observed)

From `/Characters/` paths and strings: `Kraken` + `krakenAlly` +
`krakenEnemy` (a capturable neutral that switches faction), `JungleBlackclaw`,
`JungleHeal` (treeant), `JungleMinion` in `ally/enemy/neutral/wraith`
variants, `Minion`/`LeadMinion` (`HF_Minion_Captain`, `HF_Minion_Siege`),
`Turret` + `turret_ally/enemy/neutral`, `VainHome`/`VainAway` nexus crystals,
`VainNodeHome`, `ScoutTrap` (structure), `Petal`'s summons, `wartoad`.
Turret behaviour is entity-native: `Ability__Turret__DefaultAttack`,
`StopRotatingToTarget`, `Die`, `Aggro_Lvl_2`, and separate `_5v5` variants.

**Inferred:** objectives are actors with ability/buff components (capturable
Kraken = buff-state machine), not scripted map props. Structures expose
ability events like heroes do, so presentation can observe one event channel.

## 6. Minimap: icon taxonomy and settings (Observed)

21 `hud_minimap_*` strings: `armory`, `store_neutral`, `blackclaw`,
`buff_camp`, `crystalminer`, `ghostwing`, `kraken_neutral`, `minion_neutral`,
`nexus_neutral`, `turret_neutral`, `herohalo_neutral`, `vision_eye`,
`timer_circle(_empty)`, `timer_coin_black/white`, and five ping icons
`ping/alert/avoid/mia/onmyway` with dedicated UI sounds
(`sfx__minimap_mia.mp3` …). Settings keys: `MinimapIconScales`,
`MinimapSettings`, `HUD_SETTINGS_MINIMAP_SIZE`, `MINIMAP_INSTANT_PAN`,
`HUD_SETTINGS_3V3_MINIMAP_ON_RIGHT` (the 3v3 minimap can live on the right),
`preferPulseOnDamage`, `draft_minimap3V3`/`draft_minimap5V5`.

**Inferred:** the minimap is a live-rendered actor layer with per-actor-type
icons (not a baked screenshot) plus a small timer/coin overlay grammar. Even
the draft screen renders a map image per mode.

## 7. Texture format — moved (numbering kept for stable cross-references)

The 28-byte texture header codec (BC1 solved and renderable; flags 3/4 open;
WEBP `0x12` variant) now lives in `vainglory-store-format.md` §6. The
map-relevant conclusion stays: the in-game minimap was **not** found among
BC1 textures — consistent with live rendering [Inferred] (§6 above).

## 8. What transfers to Veilbound

1. **One environment, many modes:** author zones once; express a mode as
   navMesh + spawn-set + rule-table differences (Veilbound's five-minute slice
   can grow a Blitz-like variant without a second map).
2. **Zone-chunked terrain with a ground tile grid:** named zone chunks with
   per-zone material identity, painted out-of-bounds, grid-named ground tiles.
3. **Objectives as actors with buff/ability components:** capturable neutrals
   are buff state machines; structures emit ability events on the same
   channel heroes use — matches Veilbound's presentation-observes-events rule.
4. **Minimap as a live icon layer** with per-type icons, five ping semantics,
   size/side settings — Veilbound's minimap should stay a renderer over match
   state, never a bitmap.
5. **Block-compressed textures with tiny self-describing headers:** Veilbound
   ships through Unity (formats handled by the engine), but the lesson holds:
   predictable asset headers make a pipeline debuggable.

## 9. How the 3v3 map was built — pipeline synthesis

Combining every evidence class above, the authoring pipeline separates into
five independent layers that a build step composes:

1. **Terrain authored in zone chunks** (Observed): `A001/S005` splits the map
   into Zones 1–13 with per-zone material identities (crystal clusters, rocks,
   spring props), a row/column ground-tile grid (`GroundAA`…`CD`), per-zone
   plant atlases (BUSHES/FLOWERS/Maple, each with `_animated` near LOD and a
   shared `_low` far LOD), and dynamic decals (caustics, god rays). Zone
   12/13 `PitchBlack` paints the out-of-bounds instead of simulating it.
2. **Gameplay populated from a blueprint catalogue** (Observed via SYMB):
   designers place instances of named actor classes — `HF_OuterTurret`,
   `HF_LCampA`, `HF_CenterKraken`, shops, spawn points — against one
   `GenericCamp`/`GenericLocator` framework. The instance-placement file is
   not among the self-declared store paths [left open]; only the class
   catalogue ships readable.
3. **Navigation baked per variant** (Observed): the build produces a compact
   nav record per mode — min/max bounds, 24-byte vertex records, triangle
   indices with adaptive width — plus a separate `visMesh` for fog of war.
   One environment carries several nav variants (`A001_nav`,
   `navMesh_blitzRnD`, `navMesh_aram*`, `navMesh_tutorial*`); the ARAM record
   reuses the full 3v3 bounds but trims z to 33.32, i.e. modes cut holes into
   one navigable mesh rather than authoring new maps.
4. **Tutorial maps carved from the 3v3 mesh** (Observed): shared vertex
   coordinates between `navMesh_tutorial_03` and `A001_nav` show the tutorial
   environment is a subset of the 3v3 geometry, not new authoring.
5. **Textures block-compressed at build** (Observed): all surface art ships as
   28-byte-header block-compressed textures with pre-baked mip chains;
   indicator/ring art is parameterised shadergraphs, and the minimap is a
   live actor-icon layer (§6), so no baked map screenshot is needed.

**Inferred:** SEMC's map pipeline is "author terrain once, bake navigation per
mode, instantiate gameplay from a typed blueprint catalogue". Veilbound can
transfer that shape directly: keep its deterministic world as data (zones +
placed actor instances + baked walkable grid), and express any future mode as
nav/spawn subsets instead of new scenes.

## 10. Android OBB cross-check: one platform-agnostic content store (Observed)

The Android expansion file `main.147219.com.superevilmegacorp.game.obb`
(user-supplied, 2026-09-02) was fingerprinted and diffed against the Windows
store byte-for-byte.

- **Identity**: plain ZIP (`50 4b 03 04` — not encrypted), 1,394,159,471 B,
  SHA-256 `bcbe9aff2f161e59eb7f75ab57a124e35ee46ae708b5c933d74e912cba0478fb`,
  48,187 entries totalling 2,337,980,882 B uncompressed.
- **Store identity**: 48,185 of 48,187 files are byte-identical to the Windows
  store by SHA-256. Android and Windows ship the *same* content store — the
  mobile build already receives BC1 block-compressed textures and the same
  hash-addressed layout. Platform differences are confined to 11 WEBP/RIFF
  textures (2 Android-only, 9 Windows-only) that were re-encoded per platform.
- **WEBP header variant**: those textures use a distinct 28-byte header
  `u32 payload_size, u32 version(11 or 12), 1, 0x12, width, height, 0`
  followed directly by a `RIFF…WEBP` (VP8L) payload — same arithmetic rules
  as §7 with format `0x12` replacing the BC1 fields.
- **Level file unchanged**: `HalcyonFoldLevel_Base` from the OBB parses as the
  same standalone `CFF0` (two revision groups of DEF0/INST/PTCH/SYMB); its
  `INST` chunks remain opaque (entropy 7.978). Placement data is equally
  closed in the mobile build — the OBB opens no new door on the open
  placement-coordinate claim below.
- **`00000000` family identified** (3,257 files whose magic is four zero
  bytes): header `[0,0,0,0,0,0,count,0]` then records carrying readable
  `Effects/…/*.Surface[N].shadergraph` paths plus float parameter tables.
  These are VFX/surface parameter containers, not placement data — they do
  not contradict the open placement-coordinate claim below.
- **Float-bounds sweep — definitive negative (SUPERSEDED 2026-09-04)**:
  the sweep concluded no plain file carries a placement table and the data
  lives only behind the `CFF0`/`INST` codec. That conclusion stood until
  the INST cipher was broken (store leaf §5): decrypting
  `HalcyonFoldLevel_Base`'s INST yields the **definitive placement table
  straight from source** — 22 records, layout `[x,y,z,0,yaw,0,1,1,1]+name`,
  exactly mirror-symmetric Home↔Away (`x→−x`, `yaw→−yaw`):
  spawns TeamA (−78.18, 1.3, 0.88 / −81.81, 1.3, 1.97 / −77.03, 1.3,
  −1.94), TeamB mirrored at ≈+80; minion spawn points (∓71.28, 0, 12.93);
  turrets Home (−17.06, 1.93, yaw 90), (−35.78, 1.17, 90), (−54.0, 2.92,
  75), vain turrets (−75.48, 11.96, 130) / (−68.59, 19.97, 130); vain
  crystal (−76.12, 19.9); away side exact mirror. Plus **17 brush
  (bush) records** with local-space vertex/center data — the bush geometry
  the wire route could only bound. The earlier heap-read placement table
  remains the runtime cross-check; source and observation now agree on
  provenance.

**Observed conclusion:** the Android artifact adds *portability* evidence
(one store, BC1 on mobile, same container formats) but no new map-structure
information beyond what the Windows store already yielded.

## 11. Runtime memory capture — objective placement recovered (Observed)

The opaque `CFF0`/`INST` codec was never broken; instead the running game was
observed. Vainglory 4.13.4 was installed on a rooted Android 9 emulator
(LDPlayer 9: x86_64 kernel, arm64 translation, legacy-EGL-compatible stack —
the AOSP AVD images of API 29/30/34 all fail earlier, see goal 012 log), a
solo-bot 3v3 match was played, and `/proc/<pid>/mem` was dumped as root:
two passes ~3 min apart in one match plus one pass from a second match.
`Tools/Teardown/scan_memory_dump.py` intersects 4-aligned `(x,y,z)` f32
triples inside the known map bounds across passes (actors/minions move,
statics do not): 8.19 M static triples → 758 K across matches. Practical
notes for the pipeline: Android 9 `toybox dd` and `busybox dd` mishandle
64-bit `skip=` into `/proc/pid/mem` (`toybox xxd -s/-l` seeks correctly);
`mksh` arithmetic is 32-bit and silently truncates hex addresses.

Findings:

1. **Navmesh vertices are not stored verbatim in memory** (0 exact-bit hits
   for all 793 triples): the engine converts the store payload at load. The
   memory route cannot be anchored on file bytes.
2. **Placement data exists in the heap as plain f32 world triples.** The
   static-intersect subset organises into a **3-unit lattice** sharing the
   navmesh origin fractions (`x` frac `.0978` = navmesh `x0 −92.0978`, `z`
   fracs `.9134/.0866`), with entities ground-snapped at `y = 0.0071`.
   This is the decoded `INST` blueprint: SEMC's world origin is shared
   between navigation and placement, and anchors are grid-quantised.
3. **Placement records carry full transform context**: rotation matrices
   (cos/sin pairs, e.g. 0.891/0.454 ≈ 27°) adjacent to positions, plus
   parameter blocks (`1, 10000, 1, 360, 360, 1` — health/radius-scale
   class values) — typed actor records, not bare coordinate lists.
4. **The named placement table is present verbatim in the heap (Observed).**
   A linked list of 30 records, `{char* namePtr → inline NUL name @+0x38,
   char* ptr2, f32 x, y, z, d=0, yaw°, f=0}` with variable stride
   (0x50/0x58 — the `next` pointer lives at +0x50 or +0x58 and targets the
   following record's inline name), exists in **two byte-identical copies**
   in the libc_malloc region (bin 29 @ VA 0x763866000000, chain starts
   0x54d6a0 and 0x5c5048). Reproduce with
   `Tools/Teardown/parse_vainglory_placement.py`:

| Name | x | y | z | yaw° | | Name | x | y | z | yaw° |
|---|---|---|---|---|---|---|---|---|---|---|
| HF_CenterKraken | 0 | 0 | 23.60 | 0 | | HF_LTurret_Outer | −17.06 | 0 | 1.93 | 90 |
| HF_CenterMid | 0 | 0 | 23.60 | 0 | | HF_LTurret_Middle | −35.78 | 0 | 1.17 | 90 |
| HF_CenterBottom | 0.20 | 0 | 39.50 | 0 | | HF_LTurret_Base | −54.00 | 0 | 2.92 | 75 |
| HF_CenterShop | 0.20 | 0 | 42.00 | 0 | | HF_LTurret_Vain1 | −75.48 | 0 | 11.96 | 130 |
| HF_LCrystalMine | −35.19 | 0 | 36.034 | 0 | | HF_LTurret_Vain2 | −68.59 | 0 | 19.97 | 130 |
| HF_RCrystalMine | 35.19 | 0 | 35.73 | 0 | | HF_RTurret_Outer | 17.06 | 0 | 1.93 | −90 |
| HF_LCampA | −40.915 | 0 | 20.251 | 0 | | HF_RTurret_Middle | 35.78 | 0 | 1.17 | −90 |
| HF_LCampB | −44.42 | 0 | 31.91 | 0 | | HF_RTurret_Base | 54.00 | 0 | 2.92 | −75 |
| HF_LCampC | −21.95 | 0 | 24.00 | 0 | | HF_RTurret_Vain1 | 75.48 | 0 | 11.96 | −130 |
| HF_LCampD | −13.47 | 0 | 37.67 | 0 | | HF_RTurret_Vain2 | 68.59 | 0 | 19.97 | −130 |
| HF_RCampA | 40.59 | 0 | 20.75 | 0 | | HF_LVainCrystal | −76.12 | 0 | 19.90 | 0 |
| HF_RCampB | 44.60 | 0 | 31.60 | 0 | | HF_RVainCrystal | 76.12 | 0.10 | 19.90 | 6 |
| HF_RCampC | 22.50 | 0 | 23.50 | 0 | | HF_LLaneSpawn | −71.28 | 0 | 12.93 | 0 |
| HF_RCampD | 13.635 | 0 | 37.46 | 0 | | HF_RLaneSpawn | 71.28 | 0 | 12.93 | 0 |
| HF_LShop | −88.50 | 0.89 | 2.00 | 0 | | HF_RShop | 88.565 | 1.80 | 0.51 | 0 |

5. **Cross-validation of the table (Observed):** 26/30 `(x,z)` pairs
   bit-match the runtime static-intersect set — the table is the blueprint
   (`y = 0`) and the runtime copies are the ground-snapped instances
   (`y = 0.0071`). Each anchor also has companion triples above it
   (turret +0.90, vain +1.00 — health-bar/icon heights). Mirror symmetry is
   bit-exact on `x` for all 7 turret/lane/mine pairs; the **only layout
   asymmetries** are RCrystalMine `z` 35.73 vs 36.034 (−0.304) and
   RVainCrystal `yaw 6°, y 0.10` vs L `0°, 0.00`. The 4 non-matching rows
   are the Kraken/CenterMid (0, 23.6), CenterShop and RLaneSpawn markers —
   their runtime entities were not static across passes (Kraken is
   summoned, minions flow from lane spawns). This **supersedes the earlier
   guess** that the (±21.95, 24) anchors were the crystal mines: those are
   LCampC/RCampC; the mines sit at (±35.19, ~35.9). Per-turret tier mapping
   is now named by the table itself (Outer/Middle/Base/Vain1/Vain2). The
   (±46, 1, 1) n≈400 anchors are still not in the table — role open.

6. **Structure collision radius corroborated by the navmesh (Observed,
   2026-09-03):** rasterizing the decoded walkable mesh and testing all 30
   table anchors shows the 13 structures (towers/cores/shops) sit uniformly
   **1.7–2.1 u from walkable cells** — their footprints are carved out of
   the navmesh as holes, giving an effective structure collision radius of
   ≈ 2.0 u, while all 17 soft objectives (camps/mines/spawns/anchors) sit
   directly on walkable ground.

**Transferable:** Vainglory's runtime level is a typed, grid-quantised
placement table with full transforms and per-class parameter blocks — the
same shape Veilbound already uses (zones + placed actors + baked nav).
Decompressing a competitor's opaque container was unnecessary: the running
process exposes the decoded blueprint directly.

## 12. Rebuild playbook — fidelity verdict, key numbers, stuck-map

Answer to "can we rebuild it exactly?" — per layer, honestly:

| Layer | Exact-rebuild possible? | Basis |
|---|---|---|
| Walkable geometry (footprint, walls, holes) | **Yes — measured, ±1 u** | navmesh fully decoded (§4) → `map-layout.json` outline 62 pts + 16 holes |
| Objective placement (30 anchors, yaw) | **Yes — measured, ±0.01 u** | runtime placement table (§11, [Observed]), mirror symmetry bit-exact |
| Movement flow (lane/jungle routes) | Structurally — derived, not verbatim | waypoint arrays not stored (§11 open-claims); anchor-chained geodesics [Inferred] |
| Minimap proportions & icon grammar | Yes — measured | icon inversion + settings keys (§6) |
| Visual identity (terrain art, props, materials, lighting, VFX) | **No — by rule, and partly by codec** | payload in opaque CFF0/INST; textures technically decodable (`vainglory-store-format.md` §6) but source assets are banned in this project. Re-author original art to the measured massing (hole/bound silhouettes) |
| Gameplay rules ON the map (wave timing, turret aggro ranges, jungle respawns, capture rules) | Not yet extracted | entity/ability layer (§5) and heap param blocks (`10000, 360, 360`) are the leads; dig heap/defs when this becomes the blocker |

So: the map's *skeleton* is 100 % understood in the sense that matters for
rebuilding — every number below is measured, not guessed. The *skin* is
deliberately not copied. The *rule layer* is the one remaining unmined
chapter; its location is known.

Key numbers to flip to (all [Observed] unless noted):

| Quantity | Value |
|---|---|
| World bounds | x −92.10 … 94.63, z −15.09 … 45.72 (186.7 × 60.8 u, aspect 3.07:1) |
| Walkable mesh | 793 verts / 832 tris; 1 outer contour (62 pts @ eps 1.5) + 16 significant holes |
| Placement grid | 3 u lattice; x-frac .0978 / z-fracs .9134/.0866 shared with navmesh origin |
| Ground snap | runtime y = 0.0071 |
| Structure collision radius | ≈ 2.0 u (navmesh holes around all 13 structures: 1.7–2.1 u) |
| Lane span (spawn→spawn via towers) | 242.3 u route; anchors at x ±17.06 / ±35.78 / ±54.0 / ±68.59 / ±71.28 / ±75.48 |
| Turret yaw set | ±90° (outer/middle), ±75° (base), ±130° (vain guards) |
| Vain crystals | (±76.12, 19.90); right one yaw 6°, y +0.10 — the only asymmetries with RCrystalMine z −0.304 |
| Jungle camps | L: (−40.9, 20.3) (−44.4, 31.9) (−21.95, 24.0) (−13.5, 37.7); R mirrored (±0.2–0.5 z jitter) |
| Crystal mines | (±35.19, ~35.9) |
| Kraken pit anchor | (0, 23.6); pit walls = the large central hole cluster |
| Shops | base (±88.5, ~0.5–2.0, y 0.89/1.8), neutral (0.2, 42.0) |
| Nav variants | ARAM trims z to 33.32; tutorial maps reuse 3v3 vertices (§9.3–9.4) |

Stuck-map — when X blocks you, open:

| You are stuck on… | Open |
|---|---|
| Wall/brush/walkable shape, cliff silhouettes | §4, `map-layout.json`, §11 finding 6 |
| Where objectives go, tier names, symmetry rules | §11 table, §5 roster |
| Lane/jungle route shape | §12 routes note; goal-013 `paths` block [Inferred] |
| Minimap icon set, ping grammar, settings | §6 |
| Texture formats, mip chains, render pipeline | `vainglory-store-format.md` §6 (stub §7 above) |
| Movement smoothness, locomotion, waypoint routes | `vainglory-movement-anatomy.md`; net/latency half: `vainglory-netcode-backend.md` §4 |
| Zone/material identity per area, plant atlases | §2, §9.1 |
| Mode variants without new maps | §9.3–9.4 |
| Entity/ability architecture of structures | §5 |
| What is intentionally NOT copied and why | GOAL.md IP gate; goal 013 non-goals |

Reconstruction status lives in goal 013
(`Goals/veilbound-3v3-layout-reconstruction-goal-013.md`); this leaf stays
the reference book, not the build log.

## 13. Character movement — moved (numbering kept for stable cross-references)

The full movement anatomy (sparse named waypoint objects, runtime-adjacency
navmesh pathfinding, turn-rate-limited rotation, `run_start` locomotion
clips, order model, transferable smoothness checklist) now lives in
`vainglory-movement-anatomy.md` (§13 numbering inherited from here).

## 14. Netcode and backend — moved (numbering kept for stable cross-references)

Backend topology, live traffic windows, transport strings and the
smoothness synthesis now live in `vainglory-netcode-backend.md`
(§14 numbering inherited from here; merged with the backend-liveness
report that used to sit outside the repository).

## Claims deliberately left open

- ~~Exact objective coordinates~~ — **recovered as a named 30-record
  placement table, cross-validated against runtime instances** (§11,
  [Observed]). Minion lane waypoint polylines: **closed as negative** —
  not stored as flat f32 arrays in the captured heap regions (runs scan
  over 4.26 M ground triples: one candidate only, a 1-unit-step top-jungle
  strip); goal 013 derives lane routes structurally instead (anchor-chained
  geodesics through the navmesh, flagged [Inferred]). Still open: hero
  spawn points and the (±46,1,1) n≈400 anchor role.
- The exact codec for texture format flags 3/4 (`vainglory-store-format.md` §6).
- Whether the live minimap composites any baked artwork underneath.

# Vainglory store format — containers, codecs, and where they stop

Promoted into the repository on 2026-09-03 from the working notes
(`D:/Downloads/vg/FORMAT.md`) plus the texture-format section of the map leaf
(inherited §7). This leaf answers "what file formats is this engine's content
store built from". Read `README.md` (IP boundary) first: formats are
knowledge, not assets.

- **Target artifact**: Windows store `D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/`
  (48,222 files, 257 content-addressed directories `00`–`FF` plus `Video/`);
  byte-identical to the Android OBB for 48,185/48,187 files (map leaf §10).
- **Labels**: Observed / Inferred / Unverified, same discipline as the other
  leaves. Nothing here is Veilbound code or content.

## 1. Store layout and hash addressing (Observed)

Files are named by a 32-hex-digit ID. The ID is **not** the MD5 of the file
content, nor of the payload after the header, nor of the embedded logical
path under any of 9 normalisations tested (raw / lowercased / slash-stripped
/ `build://`-prefixed / extension-stripped × MD5 and SHA-1). The mapping
lives in a manifest, not in the name.

**Inferred:** content-addressing by internal GUID; a shipped manifest binds
`id -> logical path`. Practical consequence: recovering paths requires the
1,228 files that self-declare their path (below) or runtime observation.

## 2. Type distribution (Observed)

| Kind | Count |
|---|---|
| `RSC0` wrapping `CFF0` | 16,985 |
| MP3 / ID3 audio | 16,237 |
| unclassified | 13,821 |
| `RSC0` binary (shadergraph) | 1,151 |
| MP4 video | 28 |

Only 1,228 files (~2.5 %) embed a readable logical path. Recovered top-level
trees: `Environment` (746), `Characters` (453), `UI` (28), `Effects` (1).
Examples:

```
/Characters/Skye/Art/skye.mech_mat.shadergraph
/Characters/Hero065/Art/hero065.guob_mat.shadergraph
/Environment/A001/S005/Plants/Zone3TreesD.TreeAtlas_mat1.shadergraph
/UI/Ring_Opposite/Ring_Opposite.glow.shadergraph
```

Heroes appear both by name (`Skye`, `Adagio`) and numeric ID (`Hero012`,
`Hero023`, `Hero065`) — the numbered set is the later roster.

`asset_index.tsv` (kept next to the extracted store, outside this repo) lists
all 48,222 files: id, size, container kind, recovered path.

## 3. RSC0 container — 32-byte header (Observed)

```
+00  char[4]  "RSC0"
+04  uint32   payload_size      // == filesize - 32, held for 166/166 sampled
+08  uint32   payload_size      // repeated; an uncompressed/compressed pair
+12  uint32   0
+16  uint32   0
+20  byte[12] 0
+32  payload
```

Two payload variants observed:

- payload begins `"CFF0"` — the chunked container (§4);
- payload begins with a bare `uint32` equal to the **whole file size**, then
  `uint16 0x0003`, then an ASCII logical path — the shadergraph variant, and
  the source of the 1,228 recovered paths.

## 4. CFF0 container — chunked, with one trap (Observed)

```
+00  char[4]  "CFF0"
+04  uint32   total file size
+08  uint32   2          // version
+12  uint32   0x0201     // flags
+16  uint32   0
+20  uint32   0x40       // offset of first chunk
+24  uint32   size
+28..0x3F     zero padding
```

Chunks form a flat chain from `0x40`. **The chunk size field includes the
8-byte chunk header** — advance by `size`, not `8 + size`. Getting this wrong
desyncs the chain at the second chunk and looks like a corrupt file.

```
+00  char[4]  tag
+04  uint32   size        // including these 8 bytes
+08  byte[]   body
```

Observed tags, walking a `HeroManifest` end to end (entropy over payload
bytes only):

| Offset | Tag | Size | Entropy | Meaning |
|---|---|---|---|---|
| 0x0040 | `DEF0` | 16 | 2.75 | type definition: `uint32 id`, `uint32 typehash` (`4d96daf4`) |
| 0x0050 | `INST` | 19184 | 7.96 | instance data — opaque |
| 0x4B40 | `PTCH` | 6480 | 4.31 | patch / offset table, plaintext, starts with count (`0x327` = 807) |
| 0x6490 | `SYMB` | 32 | 3.77 | `uint64 0`, `uint32 hash` (`478194f3`), then `*HeroManifest*` |
| 0x64B0 | `DEF0` | 16 | | second revision begins |
| 0x64C0 | `INST` | 23408 | 7.93 | |
| 0xC030 | `PTCH` | 6480 | 4.28 | |
| 0xD980 | `SYMB` | 32 | | `*HeroManifest*` again |

The `*Name*` form in `SYMB` matches type strings visible in the Android
`libGameKindred.so`: `*KindredManifest*`, `*HeroManifest*`,
`*KindredSkinManifest*`, `*KindredCardManifest*`, … A file carries multiple
revisions of the same type — base plus patch — consistent with the `PTCH`
chunk between them. Ten files in the store contain manifest symbols; the
largest is 55,712 bytes.

## 5. The INST wall — BROKEN (cipher + key recovery solved 2026-09-04)

`INST` bodies do not decompress (45 codec combinations fail; entropy 7.96,
no framing magic). The wall was encryption — and it is now **fully broken,
offline, from the decompile + ciphertext alone**:

**Cipher** (from `FUN_019a1194` in the 101.6 MB Ghidra decompile of
`libGameKindred.so`; loader path `FUN_019896a8`): a 32-bit-word
**cipher-feedback XOR** over the INST payload —

```
k = lookup3_variant(key_u32_LE_bytes, initval = payload_len)
state = payload_len                     // seed
for each LE u32 word c[i]:
    plain[i] = k ^ rol32(state, 1) ^ c[i]
    state = c[i]                        // feedback from ciphertext
```

`lookup3_variant` (`FUN_0091ed5c`) is Jenkins lookup3 with a non-standard
init: `a = b = 0x9e3779b9` (not `0xdeadbeef+len+init`), `c = initval`,
`c += length` before the big-endian byte tail, standard mix; used all over
the binary for name hashes (`FUN_0091ed5c("hud_plaque_hero_hp_me", …,
0x12345678)`).

**Key schedule**: the loader selects `key = table[version]` from a 16-slot
u32 table at `.bss` `0x2bf27e8` (runtime-initialised — not file-resident,
so not statically extractable), indexed by the **CFF0 header byte at +8**
(all 942 INST files in 4.13.4 are version 2). Because `k`'s initval is the
per-file payload length, `k` differs per file even with one table key.

**Key recovery without the table** (the practical break): INST payloads are
padding-heavy struct arrays (~30–50 % zero words), and the cipher is
cipher-feedback — so for every word, `rol32(c[i-1],1) ^ c[i]` is a *candidate*
for `k` (the value that would make that word decrypt to zero). Score every
candidate by zero-count over the first 4,096 words; the true `k` wins by
orders of magnitude (KindredBuffs: 1,981 zeros vs 142 for the runner-up) and
**self-validates**: the ±1 neighbours of the winner score exactly the count
of plaintext words equal to `1` / `0xffffffff`. Verified on 75 target files,
zero failures.

**Key schedule CLOSED (2026-09-03 follow-up pass)**: the statistical attack
fails on small struct payloads — no zero padding, no signal. Fixed by
brute-forcing the *single* version-2 table entry over the full 2³² space:
the variant's mix uses **fixed shifts** (no data-dependent rotations, unlike
standard lookup3), so the search vectorises (numpy, ~290 s). Exactly one
entry satisfies 8 independently verified `(payload_len → k)` pairs:

```
table[2] = 0x56c6c3eb
k = mix(a = 0x9e3779b9 + 0x56c6c3eb, b = 0x9e3779b9, c = payload_len + 4)
```

Every INST key is now a **closed-form function of payload length** — no
statistical attack is ever needed again. Two structural facts found on the
way: CFF0 files carry **1–2 revision groups** (two DEF0/INST/PTCH/SYMB
chains in one file), and the loader (`FUN_019896a8`) decrypts the **last**
INST chunk — whose payload length, and therefore key, differs from the
first. Single-key-per-file decryption garbles revision-2 reads; per-chunk
`k = f(len)` fixes it. Validated on 60 random files of the 942: 57 open to
real string content, the other 3 are legitimately string-less numeric
structs.

**Oracle verification**: the 942 INST files match HackedGlory's
`files_scanned: 942` exactly; decrypted `KindredItems` intersects 85/88 of
their published item names; `KindredBuffs` decrypts to 1,383 clean `Buff`
records (`Buff_Talent_BonusMovementSpeed`, …); `HalcyonFoldLevel_Base`
yields the definitive 22-record placement table (map leaf §10 update).

Decrypted payloads stay in TEMP (IP rule — no foreign bytes in this repo).

**PTCH chunk (solved 2026-09-03)**: follows each `INST`; an array of
`(u32 slot, u32 target)` pairs — byte relocations into the decrypted
payload where `target` is the offset of a NUL-terminated string in the
payload's own string pool (`Player`, `CHAR_INFO_ADAGIO_NAME`,
`build://Sounds/...`, `Damage_To_Energy_Ratio`). Slots whose neighbours
are inline floats expose the **form-2 record** layout
`{name-ptr, base, delta, overdrive, …}` used for ability variables
(mechanics leaf §18); slots inside string runs are display/localization
name pointers. `SYMB` = 32-byte block: u32 0, u32 hash, `*FileName*`.

**Consequence**: everything previously reached only via runtime observation
or the HackedGlory cite-only DB is now **directly readable offline**:
`KindredEffects` (824 KB), `KindredBuffs`, `KindredItems`,
`KindredCardManifest`, per-hero files (`Adagio` = abilities with *named*
variables: `Cooldown`, `Energy Cost`, `TicksPerSecond`, `BurnRadius`,
`BurnDuration`, `HealDuration`), `HalcyonFoldLevel_Base`,
`Experiment_HalcyonFold5v5_Level`, `KindredSoundBalance`,
`KindredAnnouncements`, talent files, and the remaining ~860 INST files.

Historical note (superseded): before the break, the sanctioned pattern was
runtime observation of decoded blueprints in the process heap
(`vainglory-runtime-reconstruction.md`), and the dead-ends leaf ruled static
recovery impractical (stripped `.text`) — the Ghidra decompile + the
zero-word statistical attack together overturned that ruling.

## 6. Texture header — 28 bytes, arithmetically self-verifying (inherited §7)

18k+ standalone textures share a 28-byte header
(`u32 size, u32 mip_count, 1, u32 format, u32 width, u32 height, u32 flags`),
solved arithmetically: `size` equals the file length and `size - 28` equals
the exact BC1 mip chain for format 2 — 256px/9 mips + 28 = 43,732 and
1024px/11 mips + 28 = 699,092 match byte-exact across thousands of files.

| Format flag | Meaning | Status |
|---|---|---|
| 2 | BC1 (0.5 B/px), pre-baked mip chains | **Solved and renderable** — 983 textures decode cleanly (VFX glows, atlases, normal-map variants) |
| 3, 4 | other block sizes, PVRTC-family suspected | codec open [Unverified] |
| `0x12` | WEBP variant: 28-byte header then `RIFF…WEBP` (VP8L) payload | Solved (OBB cross-check, map leaf §10) |

Rendered identifications (thumbnails only; no payload enters this repo): the
3v3 lane ground is dark teal cracked stone (2048²), base/crystal language is
silver frames with saturated blue facets, turret parts blue-teal gunmetal
with a circular lens, UI rings/masks ship as atlas sheets. The in-game
minimap was **not** found among BC1 textures — consistent with live
rendering [Inferred] (map leaf §6).

Tooling: `Tools/Teardown/render_vainglory_bc1.py` locates and renders
28-byte-header BC1 textures locally.

## 7. Navmesh container — the one plaintext binary family (cross-link)

`RSC0` binary payloads whose logical path ends `.mat.shadergraph` include the
navigation records. Their payload format is fully decoded in the map leaf
§4 (`vainglory-3v3-map-structure.md`): version/bounds/count header, 24-byte
float-six vertex records, adaptive-width triangle indices, payload ending
exactly after the index buffer. It is reproduced byte-exact by
`Tools/Teardown/render_vainglory_navmesh.py` and accounts for 100 % of both
sample payloads.

## 8. What transfers to Veilbound

1. **Self-describing headers** (RSC0 size words, texture size == file length)
   make a content pipeline debuggable with zero tooling — worth copying in
   any custom asset format.
2. **Inclusive chunk-size fields are a trap worth a comment in the spec** —
   one sentence in a format doc saves a desync debugging session.
3. **Per-chunk selective encryption** protects only the semantic payload
   (`INST`), leaving structure (`DEF0/PTCH/SYMB`) plaintext — good for their
   threat model, and the reason the blueprint *types* were recoverable while
   *instances* were not.
4. The decisive lesson is operational: an opaque codec is a dead end worth
   45 probe combinations, no more — the runtime always holds the decoded
   form, and observing it is cheaper and sanctioned.

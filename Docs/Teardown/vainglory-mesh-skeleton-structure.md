# §16 Vainglory mesh & skeleton architecture — how the heroes were rigged

Provenance: facts read from the public `a1cnore/HackedGlory` RE archive
(`reports/3d_mesh_extraction.md`, `reports/hero_assets_inventory.md`,
2026) — the same client build we decompile (4.13.4 / 147219), so the
structures apply verbatim to our binary. Read 2026-09-03. The archive
carries no license: **facts are cited here, never bulk text and never
payload bytes.** We have not independently executed their extraction —
labels carry that caveat: **[Observed]** marks facts they verified two
independent ways (native call site + byte-variance + silhouette render),
**[Unverified]** marks their single-source claims.

Why this leaf exists: the standing question was *"không được copy, nhưng
cần hiểu nó được rigging như nào, xử lý như nào, để sau này tự tạo model
+ rigging vào game."* One-paragraph answer: classic 2012-era mobile
skinned-mesh pipeline — separate mesh and skeleton resources, one 64-byte
vertex packing everything the GPU needs, per-submesh bone-index lists,
triangle-strip indices for bandwidth — and, surprisingly, **no GPU
skinning in the shader they decoded** (deformation baked/CPU-side).
Everything there is a technique Veilbound can reproduce with standard
Unity parts; nothing there is worth copying byte-wise.

## Asset landscape (their inventory, [Observed] counts)

- **18,136 RSC0 containers** hold all art including meshes, shaders,
  textures; **942 CFF0** definition files (cross-checks: the balance
  DB's `_meta.files_scanned = 942` — same inventory, two sources).
- Hero art is addressed by `build://` paths compiled into RSC0:
  `HUDPartsHero_%s.png`, `Splash_%s.png`, `MenuCharPortraitsHD2.atlas`,
  `HUDItemsAndBuffs.atlas` — sprite-atlas discipline, same shape as our
  atlas route.
- Mesh/shader internal paths use numeric hero ids + tier suffixes:
  `/Characters/Hero009/Art/hero009_rock_t3.shadergraph`.

## Mesh file structure (RSC0 `Mesh` resource)

- Container header: version flag, submesh count (u16 LE), vertex count,
  bbox (6 × f32 LE).
- **Attribute table**: 8-byte entries — stream index, data type
  (1 = ubyte, 2 = short, 4 = float, 5 = half), component count, byte
  offset, semantic (`0x01` POSITION, `0x02` NORMAL, `0x05` TANGENT,
  `0x09/0x0A` TEXCOORD0/1, `0x17` BLENDWEIGHT). Stride **64 B** for the
  typical 6-attribute hero mesh.
- **Typical 64-byte vertex** [Observed — positions confirmed by native
  `glVertexAttribPointer` call site + byte variance + recognizable
  silhouette]: 2-byte prefix (bone/submesh index), **big-endian float3
  position @+2**, float3 normal, float4 tangent, half2 UV0, float3 UV1,
  sparse bone data, 1-byte tail.
- **Index buffer sits after the vertex block, uint16 big-endian**;
  topology is triangle-strip-like with repeated-index restarts — but
  their strip→list conversion still yields long edges, and the exact
  restart convention is **their #1 unsolved problem**. Closed negative
  for us: we do **not** pick this problem up — Veilbound renders with
  Unity's own mesh pipeline; strip decoding has zero value here.
- Per-submesh bone-index lists bind each submesh to a bone subset;
  `.mesh` and `.skeleton` are **separate resources referenced
  externally** (skeleton not embedded in the mesh); CFF0 `Mesh` files
  act as scene-graph nodes above them.

## Rigging / animation finding — the instructive surprise

Their decoded vertex shader (GLSL extracted from `libGameKindred.so`)
does `_ModelViewProjectionMatrix * _Vertex` and nothing else bone-wise;
the `_Bones` uniform feeds **UV atlas transforms, not skinning**
[Unverified: single shader path — the shipped build may carry other
variants]. Interpretation: hero deformation in the analyzed path is
baked or CPU-side — consistent with a 2012 mobile budget (very old GPUs
had no reliable skinning throughput), and with the 3-bytes-only
blendweights.

## What transfers to Veilbound's own model + rig path (technique, not assets)

- **Split mesh / skeleton / animation as separate assets with external
  references** — Unity does this on FBX import; keep that separation in
  `SourceArt/` naming and in the authoring checklist.
- **Bandwidth discipline of the vertex format**: half-float UVs,
  ubyte weights, 16-bit indices, 64 B stride. Unity equivalents:
  16-bit index buffers (default), mesh compression / quantized normals,
  one UV set for mobile heroes.
- **Bone budget**: 3 weights/vertex and sparse bone lists imply small
  hierarchies — target ≤4 weights and a few dozen bones per MOBA hero;
  per-submesh bone-index lists map to Unity submeshes per material part.
- **Do not reproduce** the no-GPU-skinning trick or triangle strips:
  Unity's `SkinnedMeshRenderer` GPU path is the right answer on 2026
  mobile; the finding is valuable as a budget hint (they spent GPU on
  shaders, not on skinning).
- Atlas-first texture addressing (`HUDItemsAndBuffs.atlas` etc.)
  matches our HUD atlas route; keep hero portraits/ability icons as
  atlas pages, not loose PNGs.

## Negatives (recorded with the same discipline as positives)

- We executed **no** mesh extraction ourselves; no `Payload/` byte
  enters the repo — this leaf is structure + counts only.
- Their open problems (strip restart convention, normal non-unit
  length, texture codec of `7c55`/`a055` files) are **explicitly out of
  scope**: closed here as not-needed-for-Veilbound, so a future session
  does not re-attempt them.

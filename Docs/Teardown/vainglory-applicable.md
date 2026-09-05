# Vainglory research — what transfers

Source: Vainglory 4.13.4 (versionCode 147219) Android APK, plus the Windows build
of the same version. Findings are structural. See `README.md` for the IP boundary
before acting on any of this.

Evidence base: 48,222 files in the Windows build's content-addressed `Data/`
store. Structural parsing finds 1,250 unique self-declared paths: 1,151 RSC0
binary path records and 99 surface records. The older 1,228 count is the subset
left after selecting only Environment, Characters, UI and Effects. Exact
reproduction and corrections are in `vainglory-artifact-reproduction.md`.

---

## 1. Every recovered ground-indicator record is a Shader Graph

This was the finding with the highest return. The 28 recovered `/UI/` records
are not one homogeneous set: 21 RSC0 records are ring, selector or pretarget
`.shadergraph` paths, while seven are unrelated menu surface records. All 21
recovered ground-indicator records are shadergraphs, not sprites or flat decals.
Representative members are:

```
/UI/Ring/Ring.glow.shadergraph
/UI/Ring/Ring01.glow.shadergraph
/UI/Ring_Directional/Ring_Directional.glow.shadergraph
/UI/Ring_Double/Ring_Double.glow.shadergraph
/UI/Ring_DoubleSize/Ring_DoubleSize.glow.shadergraph
/UI/Ring_FallOff/Ring_FallOff.glow.shadergraph
/UI/Ring_FallOff_Soft/Ring_FallOff_Soft.glow.shadergraph
/UI/Ring_Global/Ring_Global.glow.shadergraph
/UI/Ring_Opposite/Ring_Opposite.glow.shadergraph
/UI/Ring_Sniper/Ring_Sniper.glow.shadergraph
/UI/Ring_r7/Ring_r7.glow.shadergraph
/UI/RingTemplate/RingTemplate.lambert2.shadergraph
```

Two things matter more than the list:

- There is a `RingTemplate` the variants derive from. One authored base, many tuned
  instances — not eleven unrelated assets.
- The variants are named by *ability shape*, not by hero: directional, global, sniper,
  double, soft falloff. The taxonomy is driven by what the ability does.

Veilbound applied the template idea in `IndicatorRing.shadergraph`: one parameterised
URP Unlit graph exposing radius, softness, intensity and pulse, with the differences
living in materials. That decision paid off immediately — the round 2 critique of
marker size and colour was fixed entirely in material properties without reopening the
graph.

## 2. Selection has more states than "selected"

```
/UI/Selector_Ally/Selector_Ally.select_tex.shadergraph
/UI/Selector_Ally_Lg/Selector_Ally_Lg.select_tex.shadergraph
/UI/Selector_Enemy/Selector_Enemy.select_tex.shadergraph
/UI/Selector_Enemy_Sm/Selector_Enemy_Sm.select_tex.shadergraph
/UI/Joule_PreTarget_Ally/Joule_PreTarget_Ally.lambert2.shadergraph
/UI/Joule_PreTarget_Enemy/Joule_PreTarget_Enemy.lambert2.shadergraph
```

Three axes: faction (ally/enemy), footprint size (`_Lg`, `_Sm`), and a distinct
**pre-target** state separate from the selected state.

Evidence boundary: these paths prove distinct authored assets/states, not their
exact pointer-event timing. First-party Update 2.5 independently confirms that a
pretargeted ability can show a selection indicator without an existing target.
Using that state before release to counter finger occlusion is Veilbound's design
inference and contract, documented in `vainglory-independent-audit.md`.

Veilbound currently has **one** selection state (`SelectionRing.cs`: on/off, follows
target). No faction distinction, no size variant, no pre-target. This is an open gap,
not a completed transfer.

Per-hero signature rings also exist (`Hero018_Ring`, `Joule_Ring`), i.e. abilities
with unique footprints get bespoke indicators rather than reusing a generic ring.

## 3. Foliage is atlased by category, with an LOD collapse

```
BLJ_FoliageA.smallPlantsAtlas_animated_BUSHES_mat.shadergraph
BLL_FoliageA.smallPlantsAtlas_animated_FLOWERS_mat.shadergraph
BLL_FoliageB.treeAtlas_animated_MapleA_mat.shadergraph
BLJ_FoliageA_low.TreesAtlas_mat.shadergraph
```

The recipe:

- Atlas by *category* (BUSHES, FLOWERS, Maple), not per prop.
- Near LOD gets an `_animated` material — vertex wind, paid for only where visible.
- Far LOD (`_low`) collapses onto one shared `TreesAtlas_mat`, dropping both the
  animation and the atlas variety.

This is how visual density is achieved on mobile without the draw-call cost. It is
relevant to the queued battlefield-cohesion goal, but does not authorize a larger
map or new gameplay area.

## 4. Asset tree naming

```
/Characters/<HeroName>/Art/<hero>.<variant>_mat.shadergraph
/Characters/Hero0NN/Art/hero0NN_<skin>.<skin>_mat.shadergraph
/Environment/<MapId>/<Zone>/<Piece>.<atlas>_mat.shadergraph
/UI/<Widget>/<Widget>.<effect>.shadergraph
```

Every skin is its own shadergraph under the hero it belongs to. Heroes appear both by
name (`Skye`, `Adagio`) and by numeric id (`Hero012` … `Hero065`); the numbered set is
the later roster, suggesting names were assigned after the art pipeline slot existed.

## 5. HUD occupies four corners and leaves the centre empty

Read from the gameplay frame at `../QualityBar/vainglory-gameplay.jpg`:

| Zone | Contents |
|---|---|
| top-left | team cluster, item slots on the far edge |
| top-centre | clock flanked by both teams' portraits and health |
| top-right | resource counters, then settings at the extreme corner |
| bottom-centre | ability and item tray |
| bottom-right | utility buttons |
| centre | nothing |

The rule worth keeping: the middle of the screen must stay readable while controls
remain reachable from a real phone grip. First-party Update 1.22 explicitly describes
placing item controls beneath the player's thumb. Veilbound's HUD follows the centre-
clear rule and the current corner assignment is locked by `HudLayoutTests.cs`.

Note the tradeoff taken: abilities at bottom-centre are a slightly longer thumb reach
than bottom-right, spent to keep the corner free for utilities.

## 6. Manifest taxonomy — mostly out of scope, recorded for completeness

Type symbols found in both the Windows `Data/` store and the Android binary:

```
*KindredManifest*  *HeroManifest*  *KindredSkinManifest*  *KindredCardManifest*
*KindredCharmsManifest*  *KindredHeroMasteryManifest*  *KindredPlayerTitlesManifest*
*KindredSocialPingsManifest*  *KindredAnnouncerVOPacksManifest*  *KindredHatManifest*
*KindredAttachableEquipmentManifest*  *KindredPlayerAvatarsManifest*
```

This is a content-system roadmap for a mature live MOBA. Almost all of it —
progression, cosmetics, cards, mastery, titles — remains deferred by `GOAL.md`
and `CLAUDE.md`. Recorded so nobody mistakes its absence for an oversight.
`SocialPings` is the only entry that plausibly serves an offline slice.

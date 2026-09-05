# Vainglory independent audit — touch and visual product behavior

Audited 2026-07-31. This is a separate evidence pass from the earlier static
binary/content-store teardown. It exists to prevent a later agent from repeating
someone else's reverse-engineering conclusions as its own observations.

## Method and evidence labels

No Vainglory binary or playable client was present in the workspace during this
pass. A recursive search found only the supplied gameplay reference and the
existing teardown documents. Therefore this pass is a **visual/product behavior
audit**, not a new binary analysis.

The following were inspected directly:

- `../QualityBar/vainglory-gameplay.jpg`, 1280x576, at original resolution;
- [Vainglory Basic Game Overview](https://www.youtube.com/watch?v=hLTeeAIM4lw)
  from the official Vainglory channel, sampled through its 320x180 first-party
  storyboard at two-second intervals across the 139-second video;
- first-party product and patch pages listed below.

No sampled/extracted video frame was added to the repository. Use these labels:

- **Observed** — directly visible in the supplied frame or official footage.
- **Confirmed** — stated by Super Evil Megacorp on a first-party page.
- **Inferred** — a design conclusion drawn from observed/confirmed evidence.
- **Unverified** — plausible, but this pass did not establish it.

## Primary source table

| Source | Establishes | Limitation |
|---|---|---|
| [Official game page](https://en.vainglorygame.com/game/) | The product marketed 60 FPS, sub-30ms control response, 1.3M map polygons and precision controls together | Historical marketing claims; this pass did not instrument the original client or establish what the polygon figure counts |
| [Official 2014 overview](https://www.youtube.com/watch?v=hLTeeAIM4lw) | Real early gameplay composition, map teaching, HUD zoning, target/range graphics and combat VFX | Storyboard sampling shows states, not exact frame timing or input-to-photon latency |
| [Update 1.22](https://www.vainglorygame.com/vainglorylive/update-1-22-baron-opals-autumn-season-fun/) | Phone-grip-aware item placement, hold-to-follow movement, full multi-touch and simultaneous minimap/ability interaction | Describes the 1.22 behavior, not launch behavior |
| [Update 2.5](https://www.vainglorygame.com/vainglorylive/update-2-5-notes-introducing-talents-collectable-hero-upgrades-exclusive-to-brawl-modes/) | Pretargeted abilities show selection indicators even when invoked without a target; turret ranges and status visuals were made more explicit | Does not specify the internal event/state machine |
| [Update 2.9](https://www.vainglorygame.com/vainglorylive/update-2-9-churnwalker-notes-new-items-crystal-rework/) | Heroes receive priority over nearby minions for taps; visibility/reveal rules were changed to prevent invisible damage cases | Target priority is a product rule, not proof of a particular collider/query implementation |
| [GDC 2015 session record](https://www.gdcvault.com/play/1021909/Designing-a-Multiplayer-Battle-Online) | A company co-founder presented high-skill MOBA design and touch-platform tradeoffs as deliberate design work | The accessible record is an abstract, not the full talk transcript |

## Touch findings

### 1. Precision is a pipeline, not “tap-to-move”

**Confirmed:** the reviewed versions include all of these independent layers:

1. a spatial command surface (tap/hold on the world);
2. an explicit priority rule when candidate targets overlap;
3. pretargeted-ability selection indicators;
4. hold-to-follow movement;
5. multi-touch so world/camera/ability input can coexist;
6. camera shift through the minimap without changing vision rules.

**Inferred:** the product feel comes from keeping those layers consistent. A
tap gesture alone cannot feel exact if target arbitration is unstable, if an
ability resolves to an unseen candidate, or if a second finger steals the first
pointer's state.

### 2. “Pretarget” is real; its exact timing is not proven here

**Confirmed:** Update 2.5 explicitly says a pretargeted ability can bring up a
selection indicator without an existing target. The prior static teardown also
contains distinct pretarget-named assets, but that is separate evidence.

**Unverified:** neither the storyboard nor patch text proves the exact internal
sequence `pointer-down -> render marker -> pointer-up -> commit`, or that every
hero uses the same sequence.

**Veilbound decision:** adopt that sequence as our own measurable contract. It
solves finger occlusion and makes “the committed command equals the last visible
intent” testable without pretending it is recovered Vainglory source behavior.

### 3. Target arbitration is part of UX

**Confirmed:** Update 2.9 gives heroes priority over nearby minions when tapped.
That means target selection is not simply “first collider returned.”

**Inferred:** Veilbound needs a documented semantic order and stable tie-break,
plus overlap tests that are independent of physics enumeration order. The exact
order must fit Veilbound's current units/structures; only the principle transfers.

### 4. Concurrency matters

**Confirmed:** Update 1.22 describes holding world movement while another touch
operates the minimap or an ability. The HUD layout change is also described in
terms of where a phone player's thumb actually rests.

**Inferred:** pointer ownership and UI capture are gameplay-feel requirements,
not merely input-system cleanup. Multi-touch can be staged after the core intent
contract, but it must have its own acceptance proof.

## Visual findings

### 1. The combat centre is reserved for dynamic information

**Observed:** in the supplied 1280x576 frame, fixed UI is concentrated in a top
band and the lower edge. Roughly the middle two-thirds of the frame contains no
persistent panel; only world-anchored health, targeting and combat effects enter
it. The official 2014 footage repeats this composition during ordinary play.

**Inferred:** “centre clear” does not mean visually empty. It means fixed UI does
not compete with dynamic threats, characters or telegraphs.

### 2. Detail is distributed, not uniform

**Observed:** the traversable stone lane uses broad, mid-value shapes. Dense
high-frequency foliage, rocks, flowers and architecture cluster around its
edges. Characters and health bars receive sharper contours and stronger local
contrast than the ground beneath them.

**Inferred:** the expensive-looking result depends on controlled hierarchy more
than uniformly dense meshes or textures. Veilbound should spend detail at
silhouette boundaries and scene edges while keeping the fighting plane calm.

### 3. Readability uses redundant channels

**Observed:** faction/health information combines hue, placement and dark
outlines. Ground-aligned circles combine a translucent interior with a brighter
boundary. Major ability effects use the brightest cyan/white or red accents,
while most environment colour remains lower in value/saturation.

**Inferred:** every important Veilbound state should survive at least two of
shape, value, animation, position and colour. Colour-only team or validity cues
are insufficient.

### 4. VFX are layered around actors

**Observed:** across the official storyboard, warnings/range disks remain on the
ground plane, projectiles and shields read around character height, and impacts
briefly rise above the actors. Large effects are translucent enough to retain
health bars and silhouettes.

**Inferred:** Veilbound needs a semantic render/timing stack rather than a pile
of independent particles: warning below, action at actor height, impact above,
then a short decay that yields to the next decision.

### 5. Graphics and response were one product promise

**Confirmed:** the official game page presents 60 FPS, sub-30ms response and map
polygon count side by side. The custom E.V.I.L. engine is also confirmed there.

**Unverified:** this pass did not establish that the engine was built primarily
for input latency, nor independently measure either performance claim.

**Veilbound decision:** touch and visuals stay co-equal, but our acceptance uses
our own phone, our own timestamps and our own frame—not historical marketing
numbers or engine mythology.

## What transfers and what does not

| Transfer to Veilbound | Do not transfer |
|---|---|
| Preview -> update -> release/cancel intent contract | External art, palette, map shapes, characters, icons or terminology |
| Explicit semantic target arbitration | An assumed copy of an unknown internal implementation |
| Pointer ownership and multi-touch tests | Features such as camera shift without a Veilbound visibility problem |
| Calm fighting plane, dense edge massing, strong silhouette/value hierarchy | A polygon-count race or raw generator detail |
| Ground/actor/impact VFX layers with redundant state cues | Exact ring shapes, colours or hero-specific effects |
| Real-device response and frame-time evidence | Self-reported historical metrics as our acceptance proof |

## Claims deliberately left open

- Exact launch-day input event timing and full selection state machine.
- Exact renderer, shader or asset-format behavior beyond the separate static
  teardown evidence.
- The motive for building the custom engine.
- A single-cause explanation for Vainglory's commercial decline.
- Any claim that Veilbound can match its content volume or years of polish.

Those questions are not needed to implement the next goal honestly.

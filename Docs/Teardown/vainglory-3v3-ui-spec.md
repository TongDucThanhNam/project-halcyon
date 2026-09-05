# Vainglory 3v3 game-screen anatomy — structural spec

Research extracted 2026-09-02 from the primary gameplay frame. Read the `README.md`
IP boundary first: this leaf records **structure and technique only**. No Vainglory
art, glyph, colour value or name transfers; Veilbound renders every cluster in
its own visual language.

## Method and evidence labels

Single primary artifact: `../QualityBar/vainglory-gameplay.jpg` (1280x576),
inspected directly at original resolution. Coordinates below are approximate
frame pixels from that inspection, recorded so each claim is falsifiable by
re-reading the same file. Secondary support: the official-footage storyboard
findings already recorded in `vainglory-independent-audit.md`.

- **Observed** — visible in the frame at the cited coordinates.
- **Inferred** — design conclusion drawn from observed evidence.
- **Unverified** — plausible, not established by this pass.

## Screen zoning (Observed)

| Zone (frame px) | Contents |
|---|---|
| top-left (0,0)-(260,95) | Organic, semi-transparent minimap with teammate/foe markers and one circular portrait badge at its lower edge |
| below minimap, far-left edge (15,95)-(70,135) | Two small square item/inventory slots |
| top-centre (430,0)-(850,60) | Three ally portraits, each with a green health bar beneath, then a round clock plate reading 0:24, then three enemy portraits with health bars; small triangular pips float above the portraits |
| top-right (1000,0)-(1280,120) | Round icon row (crystal, warning, silhouette, chat bubble), beneath it the resource row (gold "50" with a gem glyph, crossed-swords "0/0/0", a creature-kill counter "0"), and the large round settings gear at the extreme corner (~1245,100) |
| bottom-centre (445,505)-(840,576) | Ability tray: flask/potion roundel, one square ability slot, a large centre plate carrying the hero level numeral with tick marks, two small figure chips, one portrait chip |
| bottom-right (970,505)-(1280,580) | Four evenly spaced round utility buttons (~80px pitch): a concentric-ring ping wheel, a "?" help disc, a stats bar-chart disc, a rounded-square shop cart |
| centre (roughly x 260-970, y 95-505) | **No persistent UI.** Only world-anchored bars above units (each with a level chip), a turret bar, and ground VFX |

## Structural rules worth keeping (Observed → Inferred)

1. **Two horizontal chrome bands, clear middle.** All fixed UI lives in the
   top band (roughly the upper 12% of frame height) and the bottom band
   (lower 13%). The middle two-thirds is world-only. Matches the
   independent audit's "combat centre" finding; it is the same rule
   `HudLayoutTests.PersistentHudLeavesCentralCombatFieldClear` already locks.
2. **The clock is the centre of the top band.** Team identity flanks it:
   allies left, enemies right, one portrait-plus-health-bar per hero
   (Observed). Team sides, not colour alone, carry ownership — redundant
   channels (Inferred).
3. **Kill/resource counters are top-right, not in the team cluster**
   (Observed: gold, crossed-swords K/D, creature counter all sit top-right;
   the portraits carry only health). Duplicating counters inside the
   portrait cluster would break the observed information hierarchy.
4. **Utilities are bottom-right discs** with the top-right extreme corner
   reserved for settings (Observed). Update 1.22 first-party text already
   ties this zoning to phone-thumb reach (Confirmed in the audit's source
   table).
5. **The hero's own numbers live in the bottom tray** — level numeral in the
   centre plate, potion at its left (Observed). No persistent attack button
   and **no virtual joystick anywhere**: movement is tap-to-move/tap-to-target
   (Observed; consistent with the audit's touch findings). Veilbound's
   existing tap-intent control scheme is therefore structurally correct for
   this screen.
6. **Health bars are green for both factions at unit level; faction reads
   from position/portrait context** (Observed). Veilbound keeps its own
   stronger rule — hue plus position redundancy — which satisfies the same
   principle without copying the paint.

## Unverified / out of reach

- Exact pixel dimensions at native resolution (the frame is 1280x576
  footage, not a native capture), font identities, and the exact semantics
  of the tray's figure/portrait chips.
- Whether the minimap's portrait badge is the camera indicator or a hero
  beacon — one frame cannot disambiguate.
- Any claim about the 5v5 or Blitz screens; this spec covers the 3v3 frame
  only.

## Mapping into Veilbound (decisions, not evidence)

| Observed structure | Veilbound implementation (goal 011) |
|---|---|
| Minimap top-left | Already built (`Minimap` cluster) — unchanged |
| Portraits + health flanking the clock | `PlayerBand`/`EnemyBand` inside `ScoreboardFrame` gain roundel + health fill (`TeamFrameView`), bound to the heroes `MatchScore` already observes |
| Counters top-right | `ResourceCluster` with hero-kill and minion-score plates (`ResourceClusterView` on `MatchScore.Changed`); scoreboard bands drop the duplicated K/M text |
| Settings gear top-right corner | Inert settings roundel at the cluster's far edge (no settings feature exists; accepts no input) |
| Utility discs bottom-right | `UtilityCluster`: four visible, inert, non-raycast discs; features stay deferred |
| Bottom tray with potion/level | Ability tray already built; potion/level remain deferred reserved slots (no fake numerals — visual truth gate) |
| Clear centre | Already locked by `HudLayoutTests` |

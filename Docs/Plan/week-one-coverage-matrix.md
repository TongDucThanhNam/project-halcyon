# Week-one declared coverage matrix — 2026-10-09

**Declared candidate, not qualified:** Skye, Ringo, Catherine, Gwen, Adagio,
Amael (one of each across two teams of three). This selects the six factories
with A/B/C slots, not six complete kits or a release-qualified composition.
No six-actual-client match, ordinary complete match/menu return, real-duration
soak, or complete independent gameplay-fidelity gate is closed by this matrix.
The full faithful PvP mission is unchanged.

Evidence levels below describe a **bounded surface**, not entire-kit acceptance:
**headless** = authored rules/tests; **native** = owned native metadata/kernel or
wire anchors (scope stated); **client** = retained local nonvisual client effect;
**none** = no implemented/qualified effect. Mocks are headless evidence, not
actual-client evidence. Native constants do not establish resolution mechanics.

Baseline: discovery `run-1791562480510-fac7cde6`, source `bda39c2`,
`C:/Users/terasumi/AppData/Local/halcyon-evidence/discovery-run-1791562480510-fac7cde6-all/result.json`
(1,470 tests, 28 reviewed skips) and sibling `-headless/summary.json` (seven
exact pairs). New execution results are recorded in the
[acceleration checkpoint](one-week-acceleration.md#execution-checkpoint--2026-10-09).

## Every kit factory

Production dispatch is [`create_hero_kit`](../../server/abilities.py#L1469);
unsupported heroes receive no substitute abilities. A/B/C means registered
slots, not completed perks, overdrives, geometry or timing.

| Factory / slots | Evidence and code | Explicit fidelity backlog |
|---|---|---|
| Skye A/B/C | **client, partial**; [`create_skye_kit`](../../server/abilities.py#L1309), [`SkyeKit`](../../server/abilities.py#L852), [scenario evidence](solo-sandbox-scenarios.md) | Barrage width/flight, C dimensions/selection bounds, directional perk-speed calibration, native pursuit/model divergence; repeatable pair and independent fidelity remain open |
| Ringo A/B/C | **headless**; [`create_ringo_kit`](../../server/abilities.py#L1329), [`TestRingoKit`](../../server/test/test_abilities.py#L65), [`HellfireLifecycleTests`](../../server/test/test_spell_lifecycles.py#L33) | Double Down, damage overdrives, projectile-speed and channel timing calibration |
| Catherine A/B/C | **headless**; [`create_catherine_kit`](../../server/abilities.py#L1349), [`TestCatherineKit`](../../server/test/test_abilities.py#L318), [`StormguardLifecycleTests`](../../server/test/test_spell_lifecycles.py#L74) | Captain of the Guard; burn scaling, reflect target cap/travel and cone calibration |
| Gwen A/B/C | **headless** mechanics; [`create_gwen_kit`](../../server/abilities.py#L1365), [`TestGeometryAbilities`](../../server/test/test_abilities.py#L206) | Boomstick, passive speed, Buckshot slow/reveal, Aces High travel and geometry; historical item observations do not qualify the kit |
| Adagio A/B/C | **headless**; [`create_adagio_kit`](../../server/abilities.py#L1418), [`TestAdagioKit`](../../server/test/test_abilities.py#L362) | Arcane Renewal; Arcane Fire coefficient and burst-heal ratio ownership |
| Amael A/B/C | **headless**; [`create_amael_kit`](../../server/abilities.py#L1447), [`TestAmaelKit`](../../server/test/test_abilities.py#L503) | Pump It Up; charge/reactivation, dash width/interpolation, splash radius/knockup timing |
| Celeste A/B | **headless**; [`create_celeste_kit`](../../server/abilities.py#L1383), [`TestGeometryAbilities`](../../server/test/test_abilities.py#L206), [`test_celeste_item_session`](../../server/test/test_celeste_item_session.py) | C Solar Storm, Julia's Light reveal/star visibility, intermediate-level basic scaling and B range |
| Lance A | **headless**; [`create_lance_kit`](../../server/abilities.py#L1399), [`test_lance_line_pierces_multiple_enemies`](../../server/test/test_abilities.py#L277) | B/C, stamina; A displacement/width/range |
| Taka A | **headless**; [`create_taka_kit`](../../server/abilities.py#L1409), [`test_vector_dash_lands_behind_enemy_and_hits`](../../server/test/test_abilities.py#L288) | B/C/perk, Kaiten invulnerability, timing and behind distance |
| Koshka A/B | **headless**, factory/dispatch/rank surface only; [`create_koshka_kit`](../../server/abilities.py#L1435), [`TestAbilityRanks`](../../server/test/test_abilities.py#L445) | C Yummy Catnip Frenzy, Bloodrush, pounce travel and damage overdrives; no dedicated native/client kit qualification |

Celeste/Lance/Taka/Koshka and every hero without a factory are excluded from the
week-one candidate and remain fidelity backlog. Every missing mechanic in the
six candidate rows is also backlog, not waived by selection.

## Every catalog item and default item

All 36 catalog items have **native metadata** stat/ID evidence plus headless
purchase/stat tests, not automatic live-effect qualification:
[`TestNativeItemConstants`](../../server/test/test_item_native_constants.py#L57)
checks exact catalog membership, all stat fields including zeros, and active
cooldowns; [`TestShopLocations`](../../server/test/test_items_sandbox.py#L272)
checks purchase gates/recipes. Recipes are
[`economy._RECIPES`](../../server/economy.py#L133). “Stat-only” below explicitly
does not claim any unimplemented passive implied by the official item name.

| Item (native ID) | Implementation citation / surface | Evidence and remaining gap |
|---|---|---|
| Weapon Blade (458) | [`economy.ITEMS`](../../server/economy.py#L60), weapon stat | **client**, ordinary purchase/native bonus; [shop evidence](solo-sandbox-items.md#native-shop-instrumentation-and-bootstrap-stat-repair) |
| Heavy Steel (505) | [`economy.ITEMS`](../../server/economy.py#L61), weapon stat/component upgrade | **client**, ordinary upgrade/native bonus; same bounded shop evidence |
| Sorrowblade (464) | [`economy.ITEMS`](../../server/economy.py#L62), weapon stat | **native** metadata / headless; actual-client purchase/effect not qualified |
| Light Armor (469) | [`economy.ITEMS`](../../server/economy.py#L65), armor stat | **native** metadata / headless; live qualification open |
| Metal Jacket (471) | [`economy.ITEMS`](../../server/economy.py#L66), armor stat | **native** metadata / headless; live qualification open |
| Oakheart (467) | [`economy.ITEMS`](../../server/economy.py#L67), max HP | **native** metadata / headless; live qualification open |
| Aegis (503) | [`economy.ITEMS`](../../server/economy.py#L68), [`ItemManager.activate`](../../server/items.py#L166) reflex | **native** metadata / headless effect; multi-effect native ordering open |
| Shatterglass (465) | [`economy.ITEMS`](../../server/economy.py#L72), crystal stat | **native** metadata / headless; live qualification open |
| Clockwork (476) | [`economy.ITEMS`](../../server/economy.py#L73), stat-only | **native** metadata / headless; full official passive semantics not qualified |
| Sprint Boots (477) | [`ITEMS_BY_KEY`](../../server/economy.py#L84), [`activate`](../../server/items.py#L151) sprint | **native** constants / headless; historical UI observations not complete nonvisual acceptance |
| Halcyon Chargers (490) | [`ITEMS_BY_KEY`](../../server/economy.py#L86), same sprint family | **native** constants / headless; travel/passive parity and live qualification open |
| Fountain of Renewal (487) | [`ITEMS_BY_KEY`](../../server/economy.py#L90), [`activate`](../../server/items.py#L157)/[`_heal`](../../server/items.py#L294) | **native** constants / headless periodic ally healing; ordinary client effect open |
| Reflex Block (485) | [`ITEMS_BY_KEY`](../../server/economy.py#L93), [`activate`](../../server/items.py#L166) barrier/immunity | **native** constants / headless; native individual-pool ordering open |
| Crucible (488) | [`ITEMS_BY_KEY`](../../server/economy.py#L95), allied reflex family | **native** constants / headless; complete multi-client ally effect open |
| Atlas Pauldron (498) | [`ITEMS_BY_KEY`](../../server/economy.py#L97), [`step`](../../server/items.py#L307) delayed attack-speed slow | **native** constants / headless; live timing/radius acceptance open |
| Aftershock (492) | [`ITEMS_BY_KEY`](../../server/economy.py#L99), [`on_basic_attack`](../../server/items.py#L238) | **native** constants / headless proc; ordinary client/reference proc acceptance open |
| Spellfire (522) | [`ITEMS_BY_KEY`](../../server/economy.py#L101), [`on_crystal_damage`](../../server/items.py#L260)/`step` | **native** constants / headless wound/DoT; native scheduling parity open |
| Alternating Current (509) | [`ITEMS_BY_KEY`](../../server/economy.py#L102), [`on_basic_attack`](../../server/items.py#L238) | **native** constants / headless second-hit proc; ordinary client/reference acceptance open |
| Slumbering Husk (525) | [`ITEMS_BY_KEY`](../../server/economy.py#L105), [`before_damage`](../../server/items.py#L275) fortified pool | **native** constants / headless trigger; native multi-effect ordering open |
| Crystal Bit (459) | [`_COMPONENT_ITEMS`](../../server/economy.py#L114), crystal stat | **native** metadata / headless; live qualification open |
| Swift Shooter (460) | [`_COMPONENT_ITEMS`](../../server/economy.py#L115), attack-speed stat | **native** metadata / headless; live qualification open |
| Six Sins (461) | [`_COMPONENT_ITEMS`](../../server/economy.py#L116), weapon stat | **native** metadata / headless; live qualification open |
| Eclipse Prism (462) | [`_COMPONENT_ITEMS`](../../server/economy.py#L117), crystal stat | **native** metadata / headless; live qualification open |
| Blazing Salvo (463) | [`_COMPONENT_ITEMS`](../../server/economy.py#L118), attack-speed stat | **native** metadata / headless; live qualification open |
| Dragonheart (468) | [`_COMPONENT_ITEMS`](../../server/economy.py#L119), HP stat | **native** metadata / headless; live qualification open |
| Coat of Plates (470) | [`_COMPONENT_ITEMS`](../../server/economy.py#L120), armor stat | **native** metadata / headless; live qualification open |
| Energy Battery (472) | [`_COMPONENT_ITEMS`](../../server/economy.py#L121), energy/regen | **native** metadata / headless; live qualification open |
| Hourglass (473) | [`_COMPONENT_ITEMS`](../../server/economy.py#L122), cooldown/regen | **native** metadata / headless; live qualification open |
| Void Battery (474) | [`_COMPONENT_ITEMS`](../../server/economy.py#L123), energy/regen | **native** metadata / headless; live qualification open |
| Chronograph (475) | [`_COMPONENT_ITEMS`](../../server/economy.py#L124), cooldown/regen | **native** metadata / headless; live qualification open |
| Travel Boots (478) | [`_COMPONENT_ITEMS`](../../server/economy.py#L125), sprint/static speed | **native** constants / headless; separate travel-speed behavior unqualified |
| Light Shield (501) | [`_COMPONENT_ITEMS`](../../server/economy.py#L126), shield resistance | **native** metadata / headless; live qualification open |
| Kinetic Shield (502) | [`_COMPONENT_ITEMS`](../../server/economy.py#L127), shield resistance | **native** metadata / headless; live qualification open |
| Lifespring (504) | [`_COMPONENT_ITEMS`](../../server/economy.py#L128), HP/stat-only | **native** metadata / headless; passive regeneration not implemented here |
| Heavy Prism (512) | [`_COMPONENT_ITEMS`](../../server/economy.py#L129), crystal stat | **native** metadata / headless; live qualification open |
| Warmail (538) | [`_COMPONENT_ITEMS`](../../server/economy.py#L130), armor/shield | **native** metadata / headless; live qualification open |
| Healing Flask (457, default instance 2000) | [`activate_default`](../../server/items.py#L187), [`DefaultItemState`](../../server/economy.py#L221) | **client**, partial barrier/17-pulse HP/EP observation; [Flask evidence](solo-sandbox-items.md#flask). Global rounding and independent scheduling parity open |
| Vision Totem (526, default instance 2001) | [`PlayerEconomy`](../../server/economy.py#L255), [`activate_default`](../../server/items.py#L195) explicitly refuses non-Flask | **none** for gameplay; native identity/capacity metadata only; placement/vision effect absent |

Candidate shop surface is these 36 items plus Flask; this is a declaration,
not approval to claim their passives/actives qualified. Totem gameplay and all
items absent from the catalog are excluded and remain fidelity backlog.

## Shared mechanics and release boundaries

| Mechanic | Code / bounded evidence level | Explicit gap |
|---|---|---|
| Fixed tick, authoritative input, exact replay | [`SnapshotStream.advance_simulation`](../../server/match_server.py), [`verify_sandbox`](../../Tools/verify_sandbox.py); **headless** two-process exact | No inference of official computation or client smoothness; historical deadline outlier needs attribution |
| Navigation/pursuit, target/owner identity | [`HeroMovement.step`](../../server/hero_movement.py), [`_publish_pursuit_route`](../../server/match_server.py), [`test_movement_publication`](../../server/test/test_movement_publication.py); **native/client**, partial retained scalar paths | Native hold/missing owner acknowledgments and post-cast divergence open; experiments default-off |
| Basic attacks/projectiles, resistance, pools/statuses | [`combat`](../../server/combat.py), [`status_effects`](../../server/status_effects.py), [`_deal_damage`](../../server/match_server.py), [`test_resource_pool_wire`](../../server/test/test_resource_pool_wire.py); **native** aggregate health helper, **headless** resolution | Multi-effect native ordering, comprehensive hit/target timing and non-dyadic policy unqualified |
| Waves/minion AI, turrets/structures | [`wave`](../../server/wave.py), [`structures`](../../server/structures.py), [`run_scenarios`](../../Tools/run_scenarios.py); **headless** exact; limited client approach/combat | Full survivor resumption, structure interaction and official AI parity open |
| Jungle/objectives/respawns | [`jungle`](../../server/jungle.py), [`test_jungle_lifecycle`](../../server/test/test_jungle_lifecycle.py); **headless**, native spawn/lifecycle anchors | Full independent objective/AI/economy acceptance open |
| Shop, XP/gold, levels, skill learning | [`EconomyManager`](../../server/economy.py#L443), [`test_economy`](../../server/test/test_economy.py); **client**, partial shop/level observations | Shop radii/bounties include sandbox policies; full official economy not qualified |
| Kills/deaths/farm HUD | [`Scoreboard`](../../server/scoreboard.py#L29), [`test_scoreboard`](../../server/test/test_scoreboard.py); **native** counter channels / headless | Full ordinary multi-client match acceptance open |
| Assists | [`PlayerScore`](../../server/scoreboard.py#L18); **none** | Eligibility/reward rules absent; not inferred from HUD fields |
| Vision/FoW | Live [`Vision`](../../server/vision.py#L61), [`test_vision_wire`](../../server/test/test_vision_wire.py); **native** wire banks / headless policy | Radius 12 is policy; brush, occlusion, stealth, true sight and Totem absent. Legacy `VisionManager` is not the live implementation |
| Recall, death/respawn, reconnect and late join | [`hero_movement`](../../server/hero_movement.py), [`lifecycle_wire`](../../server/lifecycle_wire.py), [`test_recall_session_lifecycle`](../../server/test/test_recall_session_lifecycle.py), [`test_multiclient`](../../server/test/test_multiclient.py); **client**, partial Recall; **headless** sessions | Two actual clients and native endpoint continuity across reconnect/late join unqualified |
| Crystal end/result | [`match_end`](../../server/match_end.py), [`test_match_end`](../../server/test/test_match_end.py); **native** wire ordering / headless | Complete ordinary declared-composition match remains open |
| Front door/matchmaking; menu return | [`_fsm_update_state`](../../server/platform/local_stack.py#L289), [`test_exit_lobby_returns_to_menus`](../../server/test/test_platform_fsm.py#L57); **headless** FSM, historical client solo entry | `exitLobby -> menus` is not complete native menu-return acceptance; actual two-client admission needs qualification |

Everything not qualified above remains backlog, including all other hero kits,
all missing candidate perks/overdrives, independent reference fixtures, ordinary
six-client lifecycle and stability. Six actual clients are an operator/machine
capacity prerequisite (this host has two 6-GB LDPlayer instances), not satisfied
by six socket sessions.

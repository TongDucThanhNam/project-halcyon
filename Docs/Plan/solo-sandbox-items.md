# Solo sandbox: item rules, shop protocol, and evidence

Updated 2026-09-08. This is subsystem 4 of the operator's solo-sandbox brief.
It records implemented behavior and remaining fidelity work separately.

## Implemented

`server/economy.py` accepts purchases only for a living hero at its own fountain
or native base shop (8-unit radii), or the jungle shop `(0.2, 42.0)` (6-unit
radius). These radii are explicit sandbox choices; the jungle position comes
from the brief. Native `1010` shop-kind `315` actors are left `3565` at
`(-88.5, 2.0)` and right `3564` at `(88.56500244, 0.50999999)`. A fountain-only
gate incorrectly rejected the left shop, which is over ten units away.
Native item IDs, component consumption, recursive component discounts, full
inventory upgrades, and instance allocation are implemented. An unsuccessful
purchase leaves gold, items, and instances unchanged. Cooldowns survive selling,
repurchasing, and upgrading items in the same active family.

`server/items.py` implements Sprint Boots/Chargers, Fountain healing over time,
Reflex/Aegis/Crucible barrier plus CC immunity, delayed Atlas attack-speed slow,
Aftershock, Spellfire wound/DoT, Alternating Current, and Slumbering Husk.
`ItemRules` keeps all unspecified calibration values visible. The acceptance
brief's requested effect magnitudes and durations take precedence over older
balance references. Immunity prevents new debuffs; it does not erase a stun
already applied. Fortified health absorbs half post-barrier damage until its
pool expires or is depleted.

Native presentation now follows the same authoritative lifetime for Boots,
Fountain, Reflex/Aegis/Crucible and Atlas. `StatusManager` allocates one native
instance per presented effect and queues `1086` creation / `1093` cancellation.
The two Reflex mechanics share one presentation: depleting its barrier retains
the immunity visual until immunity ends. Fountain has a status marker, so
cleansing its buff also stops subsequent healing ticks. Dead targets have their
statuses and presentation cleared. Timed effects expire naturally from their
wire duration; a refresh explicitly cancels the previous instance and adds a
new one. A cooldown-ready `1162` is emitted once when each active finishes.

The live integration supplies `StatusManager(instance_allocator=callback)` from
one monotonic match allocator, drains `status_manager.drain_frames()` after
events/ticks, and uses `snapshot_frames(now)` for reconnect. The standalone
allocator starts at `2,000,000`; buffs do not consume compact actor slots.
`clear_target(eid, now=now)` handles death/despawn. Optional `StatusEffect`
fields `native_buff_kind` and `native_buff_key` bind mechanical status lifetimes;
`apply_presentation(...)` / `remove_presentation(...)` cover effects whose
mechanics live in another subsystem. `ItemManager.cooldown_frames(eid, now)`
supplies active item timers without replaying old activations.
`shorten_presentation(target, key, expires_at, now)` retains the native instance
when an existing effect loses duration (Catherine Stormguard's deflections).
Reconnect sees the shorter remaining time; the original client receives one
`1093` at the earlier deadline, without another add for every duration change.

Passives use the match's ordinary damage callback so kills, defenses, rewards,
recall interruption, and turret aggression use one authoritative path. Husk
triggers after resistance calculation and before barrier absorption. Attack
procs run once at impact; Spellfire ticks cannot recursively create more ticks.

## Native registry IDs: recovered, not guessed

Read-only reconstruction uses the **already decrypted** 32-bit
`KindredManifest.inst.bin` and the original manifest's first `PTCH` group.
No executable analysis or new cipher cracking is involved.

- Original CFF0: `D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/03/03A640B504C2B4D7C8CBF3A04E189223`.
- Decrypted first INST: `$TEMP/vg_max/inst_dump/KindredManifest.inst.bin`, 85,608 bytes.
- First PTCH starts at file offset 85,696; its body has an 8-byte header,
  2,797 `(u32 slot, u32 target)` relocations, then zero alignment padding.
- Root relocation `0 -> 4` addresses an array of 32-bit record pointers.
  For each array slot, `ID = (slot - 4) / 4`; follow its record pointer,
  then the record's first pointer to the NUL-terminated symbol.
- Independent wire anchors: Healing Flask `457` and Vision Totem `526` are
  created as initial item instances `2000` and `2001` for every hero; recorded
  Book of Eulogies `499` agrees with the same registry origin.

Reproduce a bounded selection without exporting payloads:

```powershell
python Tools/Teardown/inspect_kindred_registry.py `
  --manifest 'D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/03/03A640B504C2B4D7C8CBF3A04E189223' `
  --inst "$env:TEMP/vg_max/inst_dump/KindredManifest.inst.bin" `
  --name Item_SprintBoots --name Item_FountainOfRenewal --name Item_Aftershock
```

| Item | Native ID |
|---|---:|
| Sprint Boots | 477 |
| Halcyon Chargers | 490 |
| Fountain of Renewal | 487 |
| Reflex Block | 485 |
| Crucible | 488 |
| Aegis | 503 |
| Atlas Pauldron | 498 |
| Aftershock | 492 |
| Spellfire | 522 |
| Alternating Current | 509 |
| Slumbering Husk | 525 |

The former nine-item catalog assigned unrelated native IDs to several names.
For example, `467` is Oakheart, `487` is Fountain, and `504` is Lifespring;
Weapon Blade is `458`, Sorrowblade is `464`, and Heavy Steel is `505`.
Tests now check actual registry identity and measured attribute changes.

## Measured purchase/resource stream

The existing external `vg5_final.pcap`, match
`045f86d4-7ef2-4125-a835-e70a96288c88`, gives the complete upgrade chain.
Read-only audit scripts remain outside the repository in
`$TEMP/vg_max/audit_item_actions.py`, `audit_item_stats.py`, and
`audit_recall_items.py`; packet payloads remain outside the repository.

| Opcode | Observed shape or relationship |
|---|---|
| c2s/s2c 1081 | 14-byte purchase payload: hero EID, native item ID, six zero bytes; server echoes successful intent |
| 1053 | 14-byte resource delta: EID, f32 amount, u8 type, five-byte tail; HP `0`, energy `2`, gold `6`, XP `8` |
| 1085 | 14 bytes: EID, item ID, item instance ID, u16 zero |
| 1099 | 14 bytes: EID, consumed item instance ID, six-byte state suffix `00 01 00 00 00 00` |
| 1052 | 20 semantic bytes: EID, null target `FFFFFFFF`, f32 additive amount, attribute ID, mode `1`, six zero bytes |

The previously assumed `1082` inventory-slot reply was wrong: its observed
values are ability-slot numbers, and it does not carry an equipment identity.
The former `1086` gold/XP interpretation is also superseded by paired `1053`
gold `+6` / XP `+1` updates. Gold uses tail `00 00 00 00 00`; ordinary HP,
energy, and XP changes use `00 01 00 00 00`.

At capture-relative 148.929 s, Lifespring `504` removes Oakheart instance
`2002`, deducts 500 gold, and creates instance `2004`. At 312.766 s, Fountain
`487` removes that Lifespring, deducts 1,300 gold, and creates instance `2005`.
This proves owned components reduce the upgrade price and are removed from
the client's inventory rather than simply occupying another slot.

Adjacent `1085 -> 1052` signatures independently recover many static stats:
Weapon Blade +10 WP; Sorrowblade +120 WP; Heavy Steel +45 WP; Oakheart +150 HP;
Lifespring +200 HP; Fountain +400 HP/+40 armor/+40 shield; Husk +55 armor/+55
shield. Attribute indices observed here are max HP `0`, max energy `2`, energy
regen `3`, WP `4`, CP `5`, armor `7`, shield `8`, fractional attack speed `15`,
and fractional cooldown reduction `25`. Component IDs and recipe references
also come from the recovered metadata. Recipe totals use combine fees plus
components; the older DB's `2 * sell_value` estimate is not reliable for every
item (Spellfire's estimate is 3,000, while its recovered recipe sums to 2,700).

## Complete native static-stat audit

`Tools/Teardown/inspect_item_constants.py` resolves the actual item attribute
array instead of interpreting fixed file offsets as floats. In the final
64-bit INST revision, root relocation `+72` points to a null-terminated array
of eight-byte record pointers. Each target is a 16-byte record:
`[u32 attribute][f32 amount][u32 zero][u32 metadata mode]`. Attribute IDs agree
with the purchase-stream `1052` IDs above. AS is stored as a fraction and
converted to the simulation's percentage convention. The metadata mode is
retained for inspection and is not assumed to equal the wire delta mode.

All **36 catalog items** now match every native static field, including zero
fields. The requested item values are:

| Item | HP | Energy | CP | AS | Armor / shield | Energy regen | CDR | Passive MOVE |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| Sprint Boots | 0 | 0 | 0 | 0 | 0 / 0 | 0 | 0 | 0.3 |
| Travel Boots | 100 | 0 | 0 | 0 | 0 / 0 | 0 | 0 | 0.3 |
| Halcyon Chargers | 150 | 250 | 0 | 0 | 0 / 0 | 3.5 | 10% | 0.5 |
| Fountain | 400 | 0 | 0 | 0 | 40 / 40 | 0 | 0 | 0 |
| Reflex Block | 150 | 0 | 0 | 0 | 0 / 0 | 0 | 0 | 0 |
| Crucible | 550 | 0 | 0 | 0 | 0 / 0 | 0 | 0 | 0 |
| Aegis | 200 | 0 | 0 | 0 | 45 / 45 | 0 | 0 | 0 |
| Atlas Pauldron | 0 | 0 | 0 | 0 | 65 / 0 | 0 | 0 | 0 |
| Aftershock | 0 | 0 | 30 | 0 | 0 / 0 | 1 | 15% | 0 |
| Spellfire | 0 | 0 | 80 | 0 | 0 / 0 | 0 | 0 | 0 |
| Alternating Current | 0 | 0 | 45 | 40% | 0 / 0 | 0 | 0 | 0 |
| Slumbering Husk | 0 | 0 | 0 | 0 | 55 / 55 | 0 | 0 | 0 |
| Clockwork | 0 | 400 | 30 | 0 | 0 / 0 | 5 | 20% | 0 |

These rows have no static WP or HP-regeneration attribute. Boots' passive MOVE
comes from its named variable, rather than the static attribute array. Travel
Boots and Chargers also contain a separate `TRAVEL=0.5`; its activation rule
has not been measured, so it is not counted as a permanent bonus. Additional
stale catalog values corrected in this pass: Shatterglass `130 CP`, Metal
Jacket `95 armor`, Hourglass `7.5% CDR + 0.25 energy regen`. Clockwork's `30 CP`
is correct and independently agrees with its recorded purchase deltas.

Named-variable records follow their eight-byte name pointer with the f32 base
value. This avoids the old shifted TSV readings (for example, Crucible's
cooldown is 75, while 12 belongs to RANGE). All eight catalog actives now
match native Cooldown records. Aegis and Reflex refer to separate ability CFFs;
their records resolve to `45 s` and `90 s` respectively. Chargers is `45 s`;
Atlas is `45 s`, correcting the prior 15-second calibration.

Reproduce one complete item without extracting a payload:

```powershell
python Tools/Teardown/inspect_item_constants.py `
  'D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/6D/6D88622FFB87BF474FADF47E0BE08A8E'
```

The native-file references for every catalog item and the two separate Reflex
abilities are recorded in `server/test/test_item_native_constants.py`. The
tests compare all fields, all active cooldowns and the MOVE variables with the
external originals. Unspecified rule values now use native Aftershock
`COOLDOWN=1`, Husk `Burst_Window=1`, `Fortified_Health_Duration=3`,
`Lockout_Duration=30`, Fountain/Crucible `RANGE=12`, and Spellfire's two ticks per
second over three seconds. Spellfire's calibrated DPS is divided across those
half-second ticks while its damage formula remains open. The operator's explicit
effect requirements still override differing native values: sprint +2 for
three seconds, Alternating 70% CP, Husk trigger above 20% max HP, and the listed
Fountain/Atlas effects remain the acceptance brief's values.

## Measured cooldown snapshots and native ability tags

`server/cooldown_wire.py` implements the measured 22-byte `1162` layout:

| Offset | Field |
|---|---|
| 0 | hero EID, u32 BE |
| 4 | native ability tag, u32 BE |
| 8 | remaining cooldown, f32 BE |
| 12 | full cooldown duration, f32 BE |
| 16 | six-byte state |

The former `[u16 zero][f32 value][8-byte tail]` split placed the value at offset
10 and lost half the duration float. Periodic replay snapshots establish the
correct interpretation: remaining time decreases while the full duration stays
fixed. Ordinary item state is `01 01 02 00 00 00` when ready, `00 01 02 00 00 00`
while cooling. The second byte is `02` for recorded Vision Totems; its precise
charge/capacity meaning remains open. Ordinary learned A/B abilities use
`01 01 01 00 01 00` when ready; ultimates have fourth byte `01`. Unlearned
abilities have first and second bytes zero. The parser preserves all six bytes,
including exceptions such as Joule and Caine.

Tags are **32-bit FNV-1a of the exact native `Ability__` symbol**, without
surrounding asterisks. Structured metadata gives both direct declarations and
`*symbol*` references. Recovered hero triplets independently agree with the
recorded values. Shared `Ability__Withdraw` hashes to `022982b5`, Dance to
`1e275dc1`, and Taunt to `b855d752`; that last tag is not a respawn timer.

| Active | Native symbol suffix after `Ability__Item__` | Tag | Duration evidence |
|---|---|---|---:|
| Sprint Boots | `SprintBoots` | `8c2eef5b` | 150 s |
| Travel Boots | `TravelBoots` | `592b3a5f` | 90 s |
| Fountain | `FountainOfRenewal` | `6f056481` | 75 s |
| Reflex Block | `ReflexBlock` | `b92e6a9d` | 90 s |
| Crucible | `Crucible` | `7926962b` | 75 s |
| Halcyon Chargers | `HalcyonChargers` | `1b024529` | 45 s, native INST |
| Aegis | `UpgradedReflexBlock` | `7df46cad` | 45 s, native INST |
| Atlas Pauldron | `AtlasPauldron` | `87077498` | 45 s, native INST |
| Healing Flask | `HealingFlask` | `1b184adf` | 120 s |
| Vision Totem | `VisionTotem` | `6b3ebf4f` | 150 s |

The external decoded caches `m2frames.pkl`, `m3frames.pkl`, `m4frames.pkl`, and
`vgr5frames.pkl` contain 8,650 timer records. Tests rebuild all **8,649 valid
records byte-for-byte**. The remaining `m4frames.pkl` row `401` is explicitly
identified as damaged evidence: EID `1516`, corrupted tag `d60c0797`, negative
duration around `1e26`, and a random state suffix. The strict parser rejects
it. Tests also verify every selected native item symbol against its external
`Item_*.last.inst.bin` and every measured item duration against all matching
snapshots. No captured payload is stored in the repository.

`build_initial_timers` also rebuilds all complete first timer bursts for the
16 heroes represented in those caches. Adagio, Koshka, Joule, Amael, and Caine
have eight timers; Alpha has nine; the other ten have seven. The default-attack
tag `d60c580b` has duration `0.7` for most of these heroes, `0.6` for hero `254`
and Lyra, and `0.95` for Phinn. Its exact native symbol remains open. Koshka's
extra Fakeout timer is `20.0`; Caine's NoAmmo timer is `1.0`. Unrecorded heroes
receive A/B/C identities only when the exact native symbol triplet is verified;
37 such hero names are independently checked against their own INST records.

## Native item input and timed buff evidence

`server/item_input.py` now resolves item use by **owned inventory instance**.
The old `1096` ability-upgrade name was incorrect; ability points use `1078`.
`1096` is a six-byte `[u32 item instance][u16 zero]` targetless use, while
`1098` is 22 bytes: `[f32 x][f32 height][f32 y][u32 item instance][6B zero]`.
The captured server echoes these payloads unchanged. An echo alone is not
proof that an active succeeded: repeated Fountain clicks can be acknowledged
without applying another buff. Instance lookup must use the authenticated
hero's current inventory, since instance numbers repeat between heroes.

The existing `vg5_final.pcap` contains eight `1096` requests: two Healing Flask
uses of instance `2000` and six Fountain uses of instance `2005`. Seven of the
nine total item requests have exact echoes, including the single `1098` Vision
Totem instance `2001` request. At capture-relative `281.153880` s, Flask is
acknowledged at `281.368732`, followed by buff `259` at `281.431129` for five
seconds. Fountain at `427.281952` is acknowledged at `427.499949`, followed by
buff `270` at `427.537269` for three seconds. The repeated click at `427.481874`
gets a separate echo and no additional buff. The ground Totem request at
`173.070877` is echoed, then creates native archetype `392`, EID `7071`, at the
requested x/y position and attaches indefinite aura `287` from hero `1500`.

`server/buff_wire.py` implements the newly measured grammar:

| Opcode | Fields |
|---|---|
| 1086 | target u32, source u32, duration **f16** at offset 8, buff instance u32 at offset 10, kind u16 at offset 14, six zero bytes |
| 1087 | same first 16 bytes, u16 state/count at offset 16, four opaque u32 words at offsets 18/22/26/30, four zero padding bytes |
| 1093 | target u32, buff instance u32, six zero bytes |

The previous f32-duration interpretation accidentally consumed two bytes of
the buff instance. The old `roster.build_entity_prop` and `build_xp_trickle`
helpers have been retired: these packets describe buffs, while XP uses `1053`.
All **12,810 adds and 157 cancellations** in this capture rebuild byte-for-byte.
Of those cancellations, 124 match an earlier `1086` with the same target and
instance. The remaining 33 are now proven to address earlier `1087` records:
all **1,646 parameterized states** rebuild exactly and all 157 cancellations
resolve to their original target/instance. `1087` has 34 semantic bytes in
replay snapshots and 38 bytes after wire padding. Its four words are not
universally floats: measured kinds contain float bits, small integer state,
and entity references. The codec preserves these words without inventing
per-kind meanings. Ordinary Fountain `270`, Travel sprint `279`, and Mortal
Wound `29` replay states use count `1` with four zero words, retaining the
original instance and decreasing f16 remaining duration. Timed buffs can expire naturally;
their lifetime does not require an explicit cancellation. Callers allocate a
separate buff identity from the match's global actor/buff pool, never reuse an
inventory instance as a buff instance.

KindredBuffs final 64-bit registry file is
`D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/55/551BCB541D80053BACD0A897B7993A77`.
Root pointer `0 -> 8` starts an eight-byte record-pointer array, so
`kind = (array slot - 8) / 8`. Following each record's first pointer yields
`Buff_Item_HealingFlask=259`, `ReflexBlock=268`, `FountainOfRenewal=270`,
`SprintBootsSprint=278`, `TravelBootsSprint=279`, `HalcyonChargersSprint=281`, and
`VisionTotemAura=287`, and `AtlasPauldronSlow=295`. Tests independently verify
these native identities. Atlas/Boots variants absent from this activation
capture are bound through their exact native registry names; their live visual
acceptance is still distinct from registry identity and byte-shape validation.
Measured item-buff durations are Flask 5 s, Reflex 1.5 s, Fountain 3 s, Travel
sprint 2 s and Totem -1 (indefinite). Explicit brief durations still control
the sandbox effects where they differ.

Reproduce the input-to-echo/buff associations without exporting payloads:

```powershell
python Tools/Teardown/inspect_item_input.py "$env:TEMP/vg_max/vg5_final.pcap" `
  --match 045f86d4-7ef2-4125-a835-e70a96288c88 --port 7034 --eid 1500
```

Each `PlayerEconomy` now owns Flask instance `2000` (native item `457`) and
Totem instance `2001` (item `526`) in `default_items`, separately from all six
equipment slots. `item_input.resolve_owned_item(player, instance)` resolves
these identities and current equipment without accepting sold or consumed
instances. `default_item_frames(now)` supplies native inventory and current
timer state for bootstrap/reconnect. Default timers use the measured 120/150 s
cooldowns and state counts 1/2 respectively; Totem's count stays two both before
and after its captured use, so it is not modeled as a guessed remaining-charge
counter. Default ownership does not itself implement Flask restoration or
Totem actor creation.

Native default metadata paths are `AF/AFE27DA418272F58FF795339B0DE791F` (Flask)
and `74/74B1975A1D1590FA748ADD33740A56B4` (Totem), under the same external Data
directory. Flask has duration 5, barrier coefficients `(115,35,0,0)`, healing
coefficients `(200,25,0,0)`, and energy fraction 0.30. Both captured uses emit
five-second buff259 and energy deltas on approximately 0.3-second intervals.
Totem has Charges2, Range7.5, lifespan150 and invisibility delay2. The coefficient
level convention, health/barrier application timing, and full Totem state
lifecycle still need validation before these effects can be enabled.

## Remaining fidelity observations

`1041` is `[u32 target][u8 action slot][u8 flags]`, not an unconditional B cast.
In the Phinn capture, slot `1` casts B and slot `3` recalls. The two slot-3
orders produce a `1045` slot-3 acknowledgement followed by a `1070` return to
base after 3.897 s and 3.965 s respectively, confirming a four-second recall.
No item-active slot above `3` was present in the five bounded captures
examined (`vgfull`, `vgc2s`, `vg3`, `vg4`, `vg5_final`); no new `1162` timer appears around
those recalls. Initial hero bursts contain seven to nine timers; truncating
them to seven drops extra hero abilities or the default-attack timer.

Item-button routing is now measured from native requests; the local HUD results
below cover Sprint Boots and Reflex Block. Other actives have no recorded
local HUD observation here. Item activation emits a correctly aligned
`1162` using its native ability tag. Required active-item status lifecycles now
emit native buffs and cancellation, and the `1087` codec is corpus-verified.
Passives still run authoritative effects without claiming their full native
presentation: the registry identifies Aftershock readiness272, Husk fortified
health315 and Spellfire damage324, but their per-kind parameter/update contracts
are not present in this bounded activation corpus. Default Flask/Totem effect
execution also remains open beyond the now-authoritative ownership/timer state.
Barrier size and Spellfire's damage calculation remain explicit calibration
values. Spellfire's native records contain `DAMAGE_BASE=7`, `DAMAGE_MAX=40`,
`DAMAGE_RATIO=0.5`, `DAMAGE_DURATION=3`, and `TICKS_PER_SECOND=2`; the formula
joining those values is still unverified. The separate travel-speed trigger
also remains open. These fidelity limits are separate from the brief's
[completed item/shop manual scenario](solo-sandbox-acceptance-status.md).

Validation: `python -m unittest server.test.test_item_input server.test.test_buff_wire
server.test.test_item_presentation
server.test.test_item_native_constants server.test.test_cooldown_wire
server.test.test_items_sandbox server.test.test_status_effects server.test.test_economy -q`.
The focused tests include the actual native registry pointer graph when the external
manifest is available, component upgrade wire events, rollback on insufficient
gold, temporal effects, passive damage, immunity, wound, and fortified health.

## 2026-09-08 local Gwen item acceptance

This bounded audit uses the operator's running Gwen match, PID `6488`, trace
`$TEMP/halcyon_stack/wire-1788804074149933400.jsonl`, and QA directory
`$TEMP/halcyon_qa_gwen3_20260908/`. Gwen is hero `395`, EID `1500`; Baptiste is
hero `399`, EID `1517`. The operator drove the native shop and item buttons.
The audit only read the trace, receipts and state; its only repository change
is this documentation. Epoch timestamps below identify the exact records.

Setup was explicit: QA granted 12,000 gold at tick `4350`, teleported the hero,
and later prepared ability ranks. These grants and placements are diagnostic
setup. The subsequent native purchase/use requests are the interaction evidence.

| Native purchase request time | Item / hero level | Accepted result |
|---|---|---|
| `1788804594.1654587` | Sprint Boots `477`, level 4 | 1081 echo, gold `-300`, 1085 creates instance `2002` |
| `1788804609.679164` | Reflex Block `485`, level 4 | 1081 echo, gold `-700`, instance `2003`; 1052 max-HP attribute `0` adds `150`, followed by 1053 HP `+150` |
| `1788804667.5679927` | Aftershock `492`, level 5 | 1081 echo, gold `-2600`, instance `2004`; 1052 adds energy-regen attribute `3`: `1`, CP attribute `5`: `30`, and CDR attribute `25`: `0.15` |

The three explicit purchase debits sum to 3,600 gold; passive income makes a
later balance comparison unsuitable for isolating their cost. The retained
snapshot at tick `11657`, time `582.85`, confirms slots 0/1/2 contain exactly
`(477,2002)`, `(485,2003)`, `(492,2004)`.

The outside-shop preparation at tick `4342` requested `(0,20)` and projected
to `(0.00458,21.005057)`. During epoch `1788804482..1788804528`, the operator
reported the shop proximity message and no available Buy button; the trace
contains no 1081 purchase request or 1085 inventory creation. This establishes
the observed client UI gate. It does not establish rejection of a submitted
off-site request. A later successful QA teleport to the native base shop
`(-88.5,2)` is recorded at tick `5845`, before the purchases above.

Sprint activation at `1788804702.6004438` is c2s 1096 for owned instance `2002`.
The server echoes it, sends 1162 tag `8c2eef5b` with remaining/total `150/150`,
then creates buff instance `2004943`, kind `278`, duration `3`. This confirms
the live button-to-instance, cooldown and native buff path. The subsequent
[movement audit](solo-sandbox-acceptance-status.md#boots-speed-from-the-completed-gwen-trace)
measures sprint at approximately `5.9` versus ordinary equipped speed `3.9`
units/s from the production publication cadence.

The Aftershock trial begins with actual Gwen B input, c2s 1041 native action
`2`, at `1788804748.71468`. The server deducts 60 EP and publishes B timer
`364220ee`, duration `16.5217399597` seconds, matching `19 / 1.15` after CDR.
The following c2s 1060 targets Baptiste at `1788804749.021391`; Gwen's native
ordinary attack variant `8` begins at `1788804749.077834`. At impact the two
1054 records both name victim `1517`, source `1500`:

| Impact time | Observed HP delta | Calculation before float32 serialization |
|---|---:|---|
| `1788804749.4980066` | `-62.9032249451` | Weapon: `97.5 / (1 + 55/100)` |
| `1788804749.4986324` | `-158.3746490479` | Aftershock crystal: `(1459 * 0.15) / (1 + 38.185/100)` |

Both heroes were level 6 at this impact, proven by five native 1076 grants
each before the event. Gwen's WP was `68 + 5*5.9 = 97.5`; Baptiste's max HP,
armor and shield were `1459`, `55`, `38.185`. Both calculated amounts round
exactly to the observed float32 deltas, totalling about `221.277874` damage.
The later level-7 snapshot must not be substituted into this calculation.
B does no direct spell damage, so this sequence isolates the weapon impact
and armed passive proc. The next attack windup, variant `9`, was followed by
movement input at `1788804749.8277206` and no second impact in this trial.
The trial therefore does not establish a second unarmed hit, rearm timing,
or native Aftershock readiness presentation.

Reflex activation at `1788804838.976312` is c2s 1096 instance `2003`, followed
by its echo, 1162 tag `b92e6a9d` with `90/90` seconds and one kind-`268` buff,
instance `2006042`, duration `1`. QA request
`6c2835076ad24c1f81c7ab3c5e0c536f` then tries STUN at tick `11477`, time
`573.85`, and records `applied:false`; there is no false kind-`22` add in the
activation window. This verifies immunity against a diagnostic status request
following actual item activation. No incoming damage in that window measures
the barrier's absorption; this fixture does not observe an enemy ability's
CC collision. The permitted incoming-status fixture satisfies this part of
the manual scenario.

Checks for this round were read-only event decoding, native level-grant counts,
exact purchase/stat associations, float32 damage comparisons, and QA journal/
inventory correlation. That evidence round changed no production code or
tests. Together with the subsequent speed audit, these live results meet
the original brief's item/shop manual scenario.

## 2026-09-08 integrated item edge corrections

A production-session audit found that Fountain changed a lane minion's HP
from `50` to `57.42525` over its three pulses but emitted no live HP update.
The nonhero healing branch now emits one capped, wound-adjusted `1053` HP
delta per positive pulse through the existing item frame publisher. It uses
the same measured entity-resource layout as hero healing. The bounded owned
VGR scan and `vg5_final.pcap` scan contained no lane-actor `1053` examples;
native lane healing display is therefore not claimed as an observed result.
The production regression uses actual `wave.Minion` objects and native
Fountain purchase/use. It checks all three pulses, wound expiry, the HP cap,
and exclusion of dead, enemy and distant minions, with no duplicate `1054`.

A lethal ordinary basic previously returned from item processing before
consuming Aftershock readiness or counting Alternating Current. Landed hits
now update that bookkeeping even when their ordinary component kills the
target; extra damage still requires a living victim. A production Celeste
cast/basic regression kills its first victim, verifies one damage event and
consumed readiness, then targets a lane minion and verifies the second-hit
Alternating Current proc without carried Aftershock. The hero-kill bounty's
level increase is retained in that next basic's expected crystal damage.

Validation: `python -B -m unittest server.test.test_fountain_item_session
server.test.test_celeste_item_session server.test.test_items_sandbox
server.test.test_item_presentation server.test.test_idle_effect_work` passed
**67 tests in 0.070 seconds**. The full source suite subsequently passed
**758 tests in 61.721 seconds**, including these fixes. Source pins and timing
evidence are recorded separately in [production verification](solo-sandbox-performance.md).

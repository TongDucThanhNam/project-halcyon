# Client purchase permission — native evidence

The local client rejected purchases with “Must be near a shop” before
sending `1081`. The server's purchase gate was not reached. This is a
missing live permission refresh, not evidence that the range gate should
be broadened or disabled.

## Local failure

In `$TEMP/halcyon_stack/wire-1788788674860733600.jsonl`, hero1500 reaches
`(-87.101143, 1.655892)` at trace time1788788831.498013, about1.44 units from
the native left base shop at `(-88.5, 2.0)`. Its last shop permission was
sent at1788788769.253546 with a1.5-second lifetime: the bootstrap record
expired about61 seconds before the player arrived. The trace has no
client1081 request and no continuing shop permission stream.

## Measured contract

The native KindredBuffs registry identifies:

| Kind | Name |
|---:|---|
| 173 | `Buff_Shop_CanShopIcon` |
| 174 | `Buff_Shop_AllowStorePurchase` |
| 175 | `Buff_Shop_GrantStoreAccess` |
| 176 | `Buff_Shop_GrantStoreAccess_LevelDefaultStore` |
| 177 | `Buff_Shop_GrantStoreAccess_5v5Base` |

These symbols come from the decoded CFF0/PTCH registry at
`D:/Downloads/vg/pc/Vainglory 4.13/Vainglory/Data/55/551BCB541D80053BACD0A897B7993A77`.
The separate KindredManifest registry resolves452 to
`ItemStore_Standard_3v3`;451 is the5v5 store. The manifest inputs and
reproduction command are recorded in `solo-sandbox-items.md`.

In `$TEMP/vg_max/vg5_final.pcap`, match
`045f86d4-7ef2-4125-a835-e70a96288c88`, port7034, local hero1500 receives
409 permission records. All use **1087**, not1086:

```python
buff_wire.build_buff_state(
    target_eid=eid,
    source_eid=eid,
    duration=1.5,
    instance_id=fresh_shared_buff_instance,
    kind=174,
    state_count=1,
    words=(0, 0, 452, 0),
)
```

All409 complete payloads reproduce byte for byte through the existing
builder. All409 instances are distinct.408 lifetimes are1.5 seconds; the
first bootstrap state contains the remaining1.2958984375 seconds. All
records have state_count1 and identical words `(0, 0, 452, 0)`. The word452
is a registry identifier, not floating-point data. The median interval
within an active permission run is0.515488 seconds. No explicit1093
cancellation of any of these409 permission instances occurs in the capture;
their short duration expires naturally when refresh stops.

Five of the six successful client1081 requests occur while alive; all five
have a permission refresh0.24–0.40 seconds before the request. Independent
examples, with zero-based server-frame indices from
`Tools/Teardown/inspect_item_input.py::read_capture`:

| Permission frame/time | Client1081 time | Server1081 echo frame/time |
|---|---|---|
| 1991 /51.234721 |51.633768 |2046 /51.849951 |
| 2045 /51.748114 |51.984464 |2092 /52.193595 |
| 14031 /148.422900 |148.713091 |14105 /148.906987 |
| 40138 /317.352227 |317.697906 |40230 /317.914843 |
| 49765 /389.002459 |389.303492 |49881 /389.505342 |

The remaining purchase at312.529773 occurs while dead: death1072 is at
305.260334, successful echo1081 at312.734059, and resurrection1033 at
313.687496. Native dead purchasing is a separate behavior; this evidence
does not authorize weakening the sandbox's living-hero gate.

Kind173 is a separate shop icon. New proximity runs use1086 with duration−1,
source=self, target=self, then1093 for that exact icon instance on exit.
Examples: icon instance6214 added at146.361211 and canceled at153.056383;
instance10914 added at313.982512 and canceled at321.993026; instance12806
added at388.879828 and canceled at394.154723. These cancels occur about1.55
seconds after the last174 refresh. Initial bootstrap instead contains an
1087 snapshot of an already-existing173 icon with zero state words.

## Implemented presentation contract

`server/shop_wire.py::ShopPresentation` publishes 174 immediately when the
existing authoritative `economy.can_shop` predicate becomes true, then every
0.5 seconds while it remains true. Each refresh uses a fresh shared buff
instance and the native 1087 shape above. When the gate becomes false,
refresh stops and the last permission expires after its remaining lifetime.
The independent server validation of each 1081 purchase still applies.

The emitter queues indefinite 173 through `StatusManager.apply_presentation`
on entry, then queues its 1093 cancellation when the final permission expires.
A brief exit/reentry refreshes 174 immediately and preserves the existing
icon. Death clears the icon through the normal status lifecycle; respawn in
an authorized shop zone restores it. The 1086 icon cannot replace 174: its
store registry word is carried by the 1087 state form. No native range
coefficient was inferred from this pass, and the server's existing geometry
remains authoritative.
The verified store permission can express eligibility at either authorized
shop type; this sample does not independently prove a human jungle-shop
purchase or the exact native shop radius.

Integration uses the same allocator supplied to `StatusManager`:

```python
shop = ShopPresentation(status_manager, allocate_buff_instance)
# After hero lifecycle/movement, once per authoritative simulation tick:
frames += shop.step(now, heroes)
# Icon frames remain queued alongside other item/ability effects:
frames += status_manager.drain_frames()
```

For reconnect, create all actors before `shop.snapshot_frames(now)` and the
normal `status_manager.snapshot_frames(now)`. The permission snapshot carries
the latest still-active instance with its remaining lifetime; older equivalent
refreshes confer no extra access. It neither allocates an identity nor mutates
simulation state, pending frames or the next refresh time. It also preserves
the remaining exit grace if the hero just left a zone. Run the initial normal
`step` before requesting an initial permission snapshot; an emitter that has
never stepped has no permission to replay.

The fixed 0.5-second refresh and 1.5-second icon removal boundary are simulation
policy approximations of the captured receive cadence. The capture proves
the packet shape and permission duration, not the native shop distance or an
exact engine scheduling tick.

## Validation and local acceptance

`python -m unittest server.test.test_shop_wire` passes 10 tests. These include
all 409 external native permission payloads, the exact permission preceding a
successful purchase, three native icon add/cancel pairs, own/enemy base and
jungle boundary checks, dead/nonfinite rejection, shared identities, no
cross-hero access, refresh/expiry, reentry, and reconnect without state changes.
The external corpus remains outside the repository. `git diff --check` passes;
Git reports existing LF/CRLF conversion notices in the shared worktree.

The emitter still needs the local client check: enter an authorized shop zone,
observe fresh 174, attempt a purchase, and verify client 1081 followed by its
successful echo and inventory update. Also leave the zone, wait more than
1.5 seconds, and verify that permission refresh and the icon stop. The module
and tests do not change the authoritative purchase gate or the client.

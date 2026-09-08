"""Measured native item-use intents, addressed by owned inventory instance ID.

1096 is targetless use; 1098 carries a ground position. The server echoes the
same payload, but an echo alone does not prove activation succeeded. Never
interpret the instance ID as an ability slot or accept another hero's inventory.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from .economy import PlayerEconomy

ITEM_USE = 1096
GROUND_ITEM_USE = 1098


@dataclass(frozen=True)
class ItemInput:
    instance_id: int
    target_position: tuple[float, float] | None = None
    height: float = 0.0


@dataclass(frozen=True)
class OwnedItemInstance:
    instance_id: int
    item_id: int
    equipment_slot: int | None = None


def resolve_owned_item(player: "PlayerEconomy", instance_id: int) -> OwnedItemInstance | None:
    """Resolve equipment or a native default HUD item for this player only."""
    _check_instance(instance_id)
    slot = resolve_inventory_slot(player.inventory_instances, instance_id)
    default = player.default_items.get(instance_id)
    if default is not None:
        if slot is not None:
            raise ValueError("default item identity collides with an equipment instance")
        return OwnedItemInstance(instance_id, default.item_id)
    if slot is None or player.inventory[slot] is None:
        return None
    return OwnedItemInstance(instance_id, player.inventory[slot].id, slot)


def _check_instance(instance_id: int) -> None:
    if isinstance(instance_id, bool) or not isinstance(instance_id, int) or not 0 < instance_id <= 0xFFFFFFFF:
        raise ValueError("item instance ID must be a positive u32")


def build_item_use(instance_id: int) -> bytes:
    """1096 request/echo: u32 instance ID, u16 zero."""
    _check_instance(instance_id)
    return struct.pack(">IH", instance_id, 0)


def build_ground_item_use(instance_id: int, x: float, y: float, *, height: float = 0.0) -> bytes:
    """1098 request/echo: f32 x/height/y, u32 instance ID, six zero bytes."""
    _check_instance(instance_id)
    if not all(math.isfinite(value) for value in (x, y, height)):
        raise ValueError("item target position must be finite")
    return struct.pack(">fffI", x, height, y, instance_id) + bytes(6)


def parse_item_input(opcode: int, payload: bytes) -> ItemInput:
    if opcode == ITEM_USE:
        if len(payload) != 6 or payload[4:] != bytes(2):
            raise ValueError("1096 requires an item instance ID and two zero bytes")
        instance_id = struct.unpack_from(">I", payload)[0]
        _check_instance(instance_id)
        return ItemInput(instance_id)
    if opcode == GROUND_ITEM_USE:
        if len(payload) != 22 or payload[16:] != bytes(6):
            raise ValueError("1098 requires position, item instance ID and six zero bytes")
        x, height, y, instance_id = struct.unpack_from(">fffI", payload)
        build_ground_item_use(instance_id, x, y, height=height)
        return ItemInput(instance_id, (x, y), height)
    raise ValueError("unmeasured item-use opcode")


def resolve_inventory_slot(instances: Sequence[int | None], instance_id: int) -> int | None:
    """Resolve only within the authenticated hero's current inventory.

    IDs are allocated per hero; a global instance lookup would cross inventory
    ownership boundaries. Sold/consumed instances do not match their old slots.
    Reserved Flask/Totem instances require their own authoritative item state.
    """
    _check_instance(instance_id)
    matches = [slot for slot, owned_instance in enumerate(instances) if owned_instance == instance_id]
    if len(matches) > 1:
        raise ValueError("ambiguous inventory instance identity")
    return matches[0] if matches else None

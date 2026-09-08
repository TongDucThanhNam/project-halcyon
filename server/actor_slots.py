"""Deterministic compact actor slots shared by every actor in one match.

1010's byte +116 is an actor slot, reused after 1035 removes its previous
owner. 1016 addresses that slot. It is not a wrapping packet counter: vgfull
contains 116 slot reuses, all after the previous owner's destruction/removal.
"""
from __future__ import annotations

import struct


class ActorSlots:
    def __init__(self, *, reserved_slots=range(6), capacity=256):
        if not 1 <= capacity <= 256:
            raise ValueError("actor slot capacity must fit one wire byte")
        self.capacity = capacity
        self.by_eid: dict[int, int] = {}
        self.by_slot: dict[int, int | None] = {}
        for slot in reserved_slots:
            self.reserve_slot(slot)

    def _validate_slot(self, slot):
        if not isinstance(slot, int) or not 0 <= slot < self.capacity:
            raise ValueError(f"actor slot {slot!r} is outside the wire range")

    def reserve_slot(self, slot):
        """Reserve an externally initialized slot whose owner is not known yet."""
        self._validate_slot(slot)
        self.by_slot.setdefault(slot, None)

    def register(self, eid, slot):
        """Register a measured hero/static/spawn mapping, refusing live overlap."""
        self._validate_slot(slot)
        previous = self.by_eid.get(eid)
        if previous is not None and previous != slot:
            raise ValueError(f"actor {eid} already owns slot {previous}, not {slot}")
        owner = self.by_slot.get(slot)
        if owner is not None and owner != eid:
            raise ValueError(f"actor slot {slot} belongs to live actor {owner}, not {eid}")
        self.by_slot[slot] = eid
        self.by_eid[eid] = slot
        return slot

    def allocate(self, eid):
        """Keep an existing mapping or allocate the lowest unoccupied slot."""
        if eid in self.by_eid:
            return self.by_eid[eid]
        for slot in range(self.capacity):
            if slot not in self.by_slot:
                return self.register(eid, slot)
        raise RuntimeError("all compact actor slots are occupied; refusing a live actor collision")

    def release(self, eid):
        """Release only after the caller emits the actor's 1035 removal."""
        slot = self.by_eid.pop(eid, None)
        if slot is not None:
            del self.by_slot[slot]
        return slot

    def observe(self, opcode, payload):
        """Register a real 126-byte spawn or observe a real actor removal."""
        if opcode == 1010 and len(payload) == 126:
            return self.register(struct.unpack_from('>I', payload, 8)[0], payload[116])
        if opcode == 1035 and len(payload) >= 4:
            return self.release(struct.unpack_from('>I', payload)[0])
        return None

    @classmethod
    def from_legacy_tail(cls, last_slot):
        """Compatibility for callers that only know the initial contiguous tail.

        Sessions should register measured mappings and share one allocator.
        """
        return cls(reserved_slots=range(max(5, last_slot) + 1))

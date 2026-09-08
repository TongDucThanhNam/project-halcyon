"""Measured 3v3 shop permission and icon presentation.

Native 174 is a short 1087 state refresh carrying the store registry ID.
It expires naturally when refresh stops; the independent 173 icon uses the
shared status lifecycle. Purchase authorization remains economy.can_shop.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import math

from . import buff_wire, economy
from .hero_movement import HeroMovement
from .status_effects import StatusManager


SHOP_ICON_KIND = 173
SHOP_PERMISSION_KIND = 174
STANDARD_3V3_STORE = 452
PERMISSION_DURATION = 1.5
REFRESH_INTERVAL = 0.5
SHOP_ICON_KEY = "shop:can-shop"


@dataclass(frozen=True)
class ShopPermission:
    target_eid: int
    instance_id: int
    applied_at: float

    @property
    def expires_at(self) -> float:
        return self.applied_at + PERMISSION_DURATION

    def payload(self, now: float) -> bytes:
        return buff_wire.build_buff_state(
            self.target_eid, self.target_eid, max(0.0, self.expires_at - now),
            self.instance_id, SHOP_PERMISSION_KIND, 1, (0, 0, STANDARD_3V3_STORE, 0))


class ShopPresentation:
    """Publish living-shop eligibility from the authoritative fixed-tick world.

    ``step`` returns permission 1087 frames. Icon add/cancel frames are queued
    in the supplied StatusManager for its ordinary drain, preserving other
    item/ability presentation. Both use the same match-wide instance allocator.
    ``snapshot_frames`` returns only still-active permission states and never
    allocates, emits queued status frames, or changes the next refresh time.
    The caller also includes StatusManager.snapshot_frames for the icons.
    """

    def __init__(self, status_manager: StatusManager, instance_allocator: Callable[[], int]):
        if not callable(instance_allocator):
            raise TypeError("shop buff instance allocator must be callable")
        self.status_manager = status_manager
        self._allocate = instance_allocator
        self._allocated: set[int] = set()
        self.latest: dict[int, ShopPermission] = {}
        self._eligible: set[int] = set()
        self._last_step_at = -math.inf

    def step(self, now: float,
             heroes: Mapping[int, HeroMovement] | Iterable[HeroMovement]) -> list[tuple[int, bytes]]:
        if not math.isfinite(now) or now < self._last_step_at:
            raise ValueError("shop presentation time must be finite and monotonic")
        actors = heroes.values() if isinstance(heroes, Mapping) else heroes
        eligible = {hero.eid for hero in actors if economy.can_shop(hero)}
        frames = []
        for eid in sorted(eligible):
            previous = self.latest.get(eid)
            if (eid not in self._eligible or previous is None
                    or now + 1e-9 >= previous.applied_at + REFRESH_INTERVAL):
                instance = self._allocate()
                permission = ShopPermission(eid, instance, now)
                payload = permission.payload(now)  # Validate before recording an instance.
                if instance == 0 or instance in self._allocated:
                    raise ValueError("shop allocator returned a zero or reused buff identity")
                self._allocated.add(instance)
                self.latest[eid] = permission
                frames.append((buff_wire.BUFF_STATE, payload))
            if (eid, SHOP_ICON_KEY) not in self.status_manager.presentation.active:
                self.status_manager.apply_presentation(
                    SHOP_ICON_KEY, eid, eid, SHOP_ICON_KIND, now, -1.0)

        # A proximity exit stops refreshing. Match the measured icon cancel
        # near the final permission's expiry, not at the instant of crossing.
        for eid, permission in sorted(list(self.latest.items())):
            if eid not in eligible and now >= permission.expires_at:
                self.status_manager.remove_presentation(eid, SHOP_ICON_KEY, now=now)
                del self.latest[eid]
        self._eligible = eligible
        self._last_step_at = now
        return frames

    def snapshot_frames(self, now: float) -> list[tuple[int, bytes]]:
        if not math.isfinite(now):
            raise ValueError("shop snapshot time must be finite")
        # The native bootstrap contains the current permission's remaining
        # lifetime. Identical older refreshes do not confer additional access.
        return [(buff_wire.BUFF_STATE, permission.payload(now))
                for _, permission in sorted(self.latest.items())
                if permission.applied_at <= now < permission.expires_at]

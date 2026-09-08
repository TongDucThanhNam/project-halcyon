"""Native targeted projectile creation, emitted at committed attack release.

1037 is separate from the 1045 attack animation. Its two source bytes and
target byte address compact actor slots, not the low bytes of actor EIDs.
The launch socket is a FNV-1a hash of the authored attachment name. The
projectile kind indexes the native projectile registry. The float is an
authored launch argument; its complete semantics are not yet established.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct


OP_TARGET_PROJECTILE = 1037
_TARGET = struct.Struct('>IIfHBBB5x')


@dataclass(frozen=True)
class ProjectilePresentation:
    socket_hash: int
    kind: int
    argument: float = 0.0


# Native 1045 -> 1037 joins, corroborated by authored socket names. These
# represent ordinary attacks only; special shots require their own profile.
# Reproduction and external frame references live in the attack-action leaf.
_HERO_PROFILES = {
    (244, 7): ProjectilePresentation(0x855A7534, 0),
    (244, 8): ProjectilePresentation(0x855A7534, 0),
    (258, 10): ProjectilePresentation(0x17F2CF05, 115),
    (258, 11): ProjectilePresentation(0x17F2CF05, 115),
    (265, 9): ProjectilePresentation(0x77B4B72A, 108),
    (265, 13): ProjectilePresentation(0x77B4B72A, 108),
    (265, 14): ProjectilePresentation(0xB1AB2985, 108),
    (267, 7): ProjectilePresentation(0xE3A0D5BA, 50),
    (267, 8): ProjectilePresentation(0xBF31A0F8, 50),
    (409, 7): ProjectilePresentation(0x3E3270A0, 127),
    (409, 8): ProjectilePresentation(0x3E3270A0, 128),
    (418, 9): ProjectilePresentation(0x84E975E6, 136),
    (432, 9): ProjectilePresentation(0x713F51BA, 178),
    (432, 10): ProjectilePresentation(0x713F51BA, 178),
    (915, 8): ProjectilePresentation(0x95982642, 193),
    (915, 9): ProjectilePresentation(0x95982642, 193),
    (924, 11): ProjectilePresentation(0x95982642, 207),
    (924, 12): ProjectilePresentation(0x95982642, 207),
}


def hero_projectile(hero_id, variant):
    return _HERO_PROFILES.get((hero_id, variant))


def minion_projectile(target_is_hero=False):
    return ProjectilePresentation(0x005DD10C, 79, 15.0 if target_is_hero else 50.0)


def build_target_projectile(instance_eid, profile, source_slot, target_slot, *, owner_slot=None):
    if owner_slot is None:
        owner_slot = source_slot
    if type(instance_eid) is not int or not 1 <= instance_eid <= 0xFFFFFFFF:
        raise ValueError('projectile instance must be a nonzero u32 identity')
    for slot in (source_slot, owner_slot, target_slot):
        if type(slot) is not int or not 0 <= slot <= 255:
            raise ValueError('projectile actors must have valid compact slots')
    if not 0 <= profile.socket_hash <= 0xFFFFFFFF or not 0 <= profile.kind <= 65535:
        raise ValueError('invalid native projectile profile')
    if not math.isfinite(profile.argument):
        raise ValueError('projectile argument must be finite')
    return _TARGET.pack(instance_eid, profile.socket_hash, profile.argument, profile.kind,
                        source_slot, owner_slot, target_slot)

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


OP_DASH_TRANSLATION = 1027
OP_TARGET_PROJECTILE = 1037
OP_CURVED_PROJECTILE = 1038
OP_BARRAGE_PROJECTILE = 1039

# Captured ground elevation word shared by native 1027/1039 frames
# (chunk36: 0x3BE7A8F8 on every dash and barrage projectile).
from .skye_wire import GROUND_ELEVATION_BITS  # noqa: E402
GROUND_ELEVATION = struct.unpack_from('>f', struct.pack('>I', GROUND_ELEVATION_BITS))[0]

_DASH = struct.Struct('>IffffH')
_TARGET = struct.Struct('>IIfHBBB5x')
_CURVED = struct.Struct('>IIffffB3BH')
_BARRAGE = struct.Struct('>IIfffffff5sBBBH')


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


def build_dash_translation(eid: int, speed: float,
                           destination: tuple[float, float] | tuple[float, float, float],
                           *, elevation: float | None = None) -> bytes:
    """1027 payload: directional translation with speed and (x, z, y) destination."""
    if type(eid) is not int or not 1 <= eid <= 0xFFFFFFFF:
        raise ValueError('dash actor must be a nonzero u32 identity')
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError('dash speed must be a positive finite float')
    if elevation is None:
        elevation = GROUND_ELEVATION
    if len(destination) == 2:
        dx, dy = destination
        dz = elevation
    elif len(destination) == 3:
        dx, dz, dy = destination
    else:
        raise ValueError('destination must be a 2D or 3D coordinate tuple')
    for val in (dx, dz, dy):
        if not math.isfinite(val):
            raise ValueError('destination coordinates must be finite')
    return _DASH.pack(eid, speed, dx, dz, dy, 0)


def parse_dash_translation(payload: bytes) -> tuple[int, float, float, float, float]:
    if len(payload) != 22 or struct.unpack_from('>H', payload, 20)[0] != 0:
        raise ValueError('invalid 1027 dash translation payload')
    eid, speed, dx, dz, dy, _ = _DASH.unpack(payload)
    return eid, speed, dx, dz, dy


def build_curved_projectile(instance_eid: int, socket_hash: int,
                            target_pos: tuple[float, float] | tuple[float, float, float],
                            curve: float, source_slot: int, *, owner_slot: int | None = None,
                            kind: int = 111, elevation: float = 0.0) -> bytes:
    """1038 payload: curved projectile (e.g. Skye Suri Strike missiles)."""
    if owner_slot is None:
        owner_slot = source_slot
    if type(instance_eid) is not int or not 1 <= instance_eid <= 0xFFFFFFFF:
        raise ValueError('projectile instance must be a nonzero u32 identity')
    if type(socket_hash) is not int or not 0 <= socket_hash <= 0xFFFFFFFF:
        raise ValueError('socket hash must be a valid u32')
    if len(target_pos) == 2:
        px, py = target_pos
        pz = elevation
    elif len(target_pos) == 3:
        px, pz, py = target_pos
    else:
        raise ValueError('target position must be a 2D or 3D coordinate tuple')
    for val in (px, pz, py, curve):
        if not math.isfinite(val):
            raise ValueError('projectile target position and curve must be finite')
    for slot in (source_slot, owner_slot):
        if type(slot) is not int or not 0 <= slot <= 255:
            raise ValueError('projectile actors must have valid compact slots')
    if type(kind) is not int or not 0 <= kind <= 255:
        raise ValueError('projectile kind must fit u8')
    return _CURVED.pack(instance_eid, socket_hash, px, pz, py, curve, 0, kind, source_slot, owner_slot, 0)


def parse_curved_projectile(payload: bytes) -> tuple[int, int, float, float, float, float, int, int, int]:
    if len(payload) != 30 or payload[24] != 0 or struct.unpack_from('>H', payload, 28)[0] != 0:
        raise ValueError('invalid 1038 curved projectile payload')
    inst, sock, px, pz, py, curve, _, kind, src, own, _ = _CURVED.unpack(payload)
    return inst, sock, px, pz, py, curve, kind, src, own


def build_barrage_projectile(instance_eid: int,
                             origin: tuple[float, float] | tuple[float, float, float],
                             direction: tuple[float, float],
                             source_slot: int, *, owner_slot: int | None = None,
                             socket_hash: int = 0x259FD523, kind: int = 110,
                             elevation: float | None = None) -> bytes:
    """1039 payload: directional barrage stream (e.g. Skye Forward Barrage)."""
    if owner_slot is None:
        owner_slot = source_slot
    if elevation is None:
        elevation = GROUND_ELEVATION
    if type(instance_eid) is not int or not 1 <= instance_eid <= 0xFFFFFFFF:
        raise ValueError('projectile instance must be a nonzero u32 identity')
    if type(socket_hash) is not int or not 0 <= socket_hash <= 0xFFFFFFFF:
        raise ValueError('socket hash must be a valid u32')
    if len(origin) == 2:
        px, py = origin
        pz = elevation
    elif len(origin) == 3:
        px, pz, py = origin
    else:
        raise ValueError('origin must be a 2D or 3D coordinate tuple')
    if len(direction) != 2:
        raise ValueError('direction must be a 2D direction tuple')
    dir_x, dir_y = direction
    for val in (px, pz, py, dir_x, dir_y):
        if not math.isfinite(val):
            raise ValueError('projectile coordinates and direction must be finite')
    for slot in (source_slot, owner_slot):
        if type(slot) is not int or not 0 <= slot <= 255:
            raise ValueError('projectile actors must have valid compact slots')
    if type(kind) is not int or not 0 <= kind <= 255:
        raise ValueError('projectile kind must fit u8')
    return _BARRAGE.pack(instance_eid, socket_hash, px, pz, py, dir_x, dir_y, dir_x, dir_y,
                         bytes(5), kind, source_slot, owner_slot, 0)


def parse_barrage_projectile(payload: bytes) -> tuple[int, int, float, float, float, float, float, int, int, int]:
    if len(payload) != 46 or payload[36:41] != bytes(5) or struct.unpack_from('>H', payload, 44)[0] != 0:
        raise ValueError('invalid 1039 barrage projectile payload')
    inst, sock, px, pz, py, d1, d2, d3, d4, _, kind, src, own, _ = _BARRAGE.unpack(payload)
    return inst, sock, px, pz, py, d1, d2, kind, src, own

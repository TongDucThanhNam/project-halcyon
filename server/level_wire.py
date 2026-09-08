"""Native entity level increments and hero experience progression.

The 4.13 captures contain 1076 single-level increments followed by a 1052
attribute-39 requirement setter. Requirements are 68 + 16 * (level - 1),
independently checked against 852 hero snapshots in the decoded corpus.
"""
from __future__ import annotations

import math
import struct


OP_LEVEL_INCREMENT = 1076
OP_XP_REQUIREMENT = 1052
MAX_HERO_LEVEL = 12
XP_LEVEL_THRESHOLDS = tuple((level - 1) * (52 + 8 * level)
                            for level in range(1, MAX_HERO_LEVEL + 1))


def next_level_requirement(level: int) -> float:
    """Native requirement stored even at the maximum hero level."""
    if type(level) is not int or not 1 <= level <= MAX_HERO_LEVEL:
        raise ValueError("hero level must be an integer from 1 to 12")
    return float(68 + 16 * (level - 1))


def within_level_xp(total_xp: float, level: int) -> float:
    """Convert authoritative cumulative XP to the native 1011 XP field."""
    next_level_requirement(level)
    if not math.isfinite(total_xp) or total_xp < 0:
        raise ValueError("total XP must be finite and nonnegative")
    return max(0.0, total_xp - XP_LEVEL_THRESHOLDS[level - 1])


def build_level_increment(eid: int) -> bytes:
    """1076: one native level, including its base growth and ability point."""
    return struct.pack(">II", eid, 1) + bytes(6)


def parse_level_increment(payload: bytes) -> tuple[int, int]:
    if len(payload) != 14 or payload[8:] != bytes(6):
        raise ValueError("1076 requires two u32 values and six zero bytes")
    eid, increment = struct.unpack_from(">II", payload)
    if increment != 1:
        raise ValueError("only native single-level increments are measured")
    return eid, increment


def build_xp_requirement(eid: int, requirement: float) -> bytes:
    """1052: set next-level XP; its flags differ from additive item stats."""
    if not math.isfinite(requirement) or requirement <= 0:
        raise ValueError("next-level XP requirement must be finite and positive")
    return struct.pack(">IIf", eid, 0xFFFFFFFF, requirement) + bytes((39, 0, 1)) + bytes(7)


def parse_xp_requirement(payload: bytes) -> tuple[int, float]:
    if (len(payload) != 22 or payload[4:8] != bytes.fromhex("ffffffff")
            or payload[12:] != bytes((39, 0, 1)) + bytes(7)):
        raise ValueError("unexpected next-level XP attribute setter")
    eid, requirement = struct.unpack_from(">I", payload)[0], struct.unpack_from(">f", payload, 8)[0]
    if not math.isfinite(requirement) or requirement <= 0:
        raise ValueError("next-level XP requirement must be finite and positive")
    return eid, requirement

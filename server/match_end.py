"""Measured structure-death and match-result messages.

The natural match-six ending preserves destroyed turrets as HP-zero world
entities.  It sends 1072 with the victim and killer, followed at match end by
1009 with the winning team.  The generic 1073/1035 despawn chain observed on
an objective locator is not a turret or crystal death sequence.

Evidence and remaining UI verification: Docs/Plan/solo-sandbox-match-end.md.
"""
from __future__ import annotations

import struct
from enum import IntEnum


OP_MATCH_RESULT = 1009
OP_STRUCTURE_DEATH = 1072
OP_CRYSTAL_DESTROYED = 1106
DESTRUCTION_DELAY_SECONDS = 6.0


class MatchEndReason(IntEnum):
    CRYSTAL_DESTROYED = 0
    SURRENDER = 2


def _entity_id(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"{name} must be an unsigned 32-bit entity id")
    return value


def build_structure_death(victim_eid: int, killer_eid: int) -> bytes:
    """1072: retain the dead structure, with kill attribution, after final damage."""
    return struct.pack(">II6x", _entity_id(victim_eid, "victim_eid"),
                       _entity_id(killer_eid, "killer_eid"))


def build_crystal_destroyed() -> bytes:
    """1106: six zero bytes, observed immediately after a crystal's lethal hit."""
    return bytes(6)


def build_match_result(winning_team: int,
                       reason: MatchEndReason = MatchEndReason.CRYSTAL_DESTROYED) -> bytes:
    """1009: [u32 winning team][u8 ending reason][u8 zero padding]."""
    if type(winning_team) is not int or winning_team not in (1, 2):
        raise ValueError("winning_team must be team 1 or team 2")
    if isinstance(reason, bool):
        raise ValueError("unsupported match-end reason")
    try:
        reason = MatchEndReason(reason)
    except (TypeError, ValueError) as exc:
        raise ValueError("unsupported match-end reason") from exc
    return struct.pack(">IBx", winning_team, reason)

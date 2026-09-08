"""Measured hero death, corpse hiding and two-stage resurrection actions.

1073 hides the corpse without 1035 actor removal. Flag1 1033 returns a
still-dead hero to base; 1074 completes revival about 0.3 seconds later.
"""
import struct

OP_HERO_DEATH = 1072
OP_RESPAWN_COUNTDOWN = 1075
OP_HERO_RESPAWN = 1033
OP_HERO_RESPAWN_COMPLETE = 1074
OP_HERO_CORPSE_HIDE = 1073

# Five complete vgfull chains hide after 1.7966..1.8407 seconds. Seven
# local-player VGR chains independently measure 1.7470..1.8678 seconds.
HERO_CORPSE_SECONDS = 1.8
# All 129 native VGR flag1 returns precede 1074. Five TCP examples measure
# 0.2979..0.3091 seconds; native snapshots between them still have zero HP.
HERO_RESPAWN_TRANSITION_SECONDS = 0.3
RESPAWN_HEIGHTS = {1500: 1.3, 1515: 1.3, 1517: 1.5, 1518: 1.5, 1519: 1.5}


def build_hero_death(eid, killer_eid):
    return struct.pack('>II', eid, killer_eid) + bytes(6)


def build_respawn_countdown(eid, seconds):
    return struct.pack('>If', eid, seconds) + bytes(6)


def build_hero_corpse_hide(eid):
    """1073 retains the hero's actor ID and compact slot for resurrection."""
    return struct.pack('>IH', eid, 0)


def build_hero_respawn(eid, x, y, height=None):
    """1033 pre-return relocation; the actor remains dead until 1074."""
    if height is None:
        # 1516 has no captured flag1 resurrection; retain the prior height
        # policy for unmeasured slots instead of generalizing a team value.
        height = RESPAWN_HEIGHTS.get(eid, 1.5)
    return struct.pack('>IfffB', eid, x, height, y, 1) + bytes(5)


def build_hero_respawn_complete(eid, x, y, height=None):
    """1074 revival uses the same coordinates as 1033 and six zero bytes."""
    if height is None:
        height = RESPAWN_HEIGHTS.get(eid, 1.5)
    return struct.pack('>Ifff6x', eid, x, height, y)

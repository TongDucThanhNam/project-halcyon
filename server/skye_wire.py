"""Skye's native C volley actors, using operator-held creation records.

The 126-byte serializer has opaque fields. Its templates stay outside the
repository; only known identity, position, facing, owner and team fields are
patched. Gameplay damage belongs to SkyeKit, not this presentation lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
import os
from pathlib import Path
import struct

from . import buff_wire, decode, entity_spawn, lifecycle_wire
from .paths import runtime_corpus_dir
from .vision import VisibilityUpdate


VOLLEY_CLASS = 0xF59CDB08
CLUSTER_ARCHETYPE = 384
LINE_ARCHETYPE = 385
_MATCH = 'ea4c7fda-4b61-481d-abb7-1c757d24ae58-a683aa80-9811-47c3-bb64-0731a802e889'


@lru_cache(maxsize=1)
def native_volley_templates():
    base = Path(os.environ.get('HALCYON_SKYE_VOLLEY_CORPUS',
                str(runtime_corpus_dir())))
    result = {}
    for archetype, chunk, row in ((LINE_ARCHETYPE, 32, 1136), (CLUSTER_ARCHETYPE, 36, 326)):
        frames, stats = decode.walk_vgr(base / f'{_MATCH}.{chunk}.vgr')
        if stats['failures']:
            raise ValueError('native Skye volley corpus has decode failures')
        _, opcode, payload = frames[row]
        if (opcode != 1010 or len(payload) != 126
                or struct.unpack_from('>II', payload) != (archetype, VOLLEY_CLASS)):
            raise ValueError('native Skye volley creation record does not match its source anchor')
        result[archetype] = payload
    return result


def build_volley(template, eid, source_eid, slot, team, center, facing):
    if (len(template) != 126 or struct.unpack_from('>I', template, 4)[0] != VOLLEY_CLASS
            or struct.unpack_from('>I', template)[0] not in (CLUSTER_ARCHETYPE, LINE_ARCHETYPE)):
        raise ValueError('not a measured Skye volley template')
    if any(type(value) is not int or not 0 < value <= 0xFFFFFFFF for value in (eid, source_eid)):
        raise ValueError('volley and owner identities must be nonzero u32 values')
    if type(slot) is not int or not 0 <= slot <= 255 or team not in (1, 2):
        raise ValueError('volley requires a valid actor slot and playing team')
    if len(center) != 2 or len(facing) != 2 or not all(math.isfinite(value) for value in (*center, *facing)):
        raise ValueError('volley geometry must be finite')
    body = bytearray(template)
    for offset, value in ((8, eid), (112, source_eid)):
        struct.pack_into('>I', body, offset, value)
    for offset, value in ((12, center[0]), (20, center[1]), (24, facing[0]), (32, facing[1])):
        struct.pack_into('>f', body, offset, value)
    body[116] = slot
    entity_spawn._patch_team_state(body, team)
    return bytes(body)


@dataclass
class Volley:
    eid: int
    source_eid: int
    team: int
    archetype: int
    center: tuple[float, float]
    facing: tuple[float, float]
    activation_at: float
    expires_at: float
    played: bool = False
    activated: bool = False
    dead: bool = False


class VolleyPresentation:
    def __init__(self, actor_slots, allocate_instance):
        self.actor_slots = actor_slots
        self.allocate_instance = allocate_instance
        self.active: dict[int, Volley] = {}

    def _buff(self, volley, kind, duration, *, self_source=False):
        return (buff_wire.BUFF_ADD, buff_wire.build_buff_add(
            volley.eid, volley.eid if self_source else volley.source_eid,
            duration, self.allocate_instance(), kind))

    def start(self, hero, center, line_direction, now, *, activation_at, duration):
        if (not all(math.isfinite(value) for value in (now, activation_at, duration))
                or activation_at < now + .2 or duration <= 0):
            raise ValueError('invalid volley presentation timeline')
        archetype = LINE_ARCHETYPE if line_direction is not None else CLUSTER_ARCHETYPE
        template = native_volley_templates()[archetype]
        facing = tuple(line_direction) if line_direction is not None else (1.0, 0.0)
        if (len(center) != 2 or len(facing) != 2
                or not all(math.isfinite(value) for value in (*center, *facing))
                or hero.team not in (1, 2)):
            raise ValueError('invalid volley geometry or faction')
        eid = self.allocate_instance()
        slot = self.actor_slots.allocate(eid)
        volley = Volley(eid, hero.eid, hero.team, archetype, tuple(center), facing,
                        activation_at, activation_at + duration)
        self.active[eid] = volley
        frames = [(1010, build_volley(template, eid, hero.eid, slot, hero.team, center, facing))]
        frames.extend(self._buff(volley, kind, -1.0) for kind in
                      (61, 614 if line_direction is not None else 612, 616))
        # Native C fields reveal their warning area to both teams. The owner
        # bank uses15, the opposing bank3; other native banks carry2.
        frames.extend((1067, VisibilityUpdate(eid, viewer,
                      (1, 15 if viewer == hero.team else 3 if viewer in (1, 2) else 2, 0)).encode())
                      for viewer in range(8))
        return frames

    def step(self, now):
        frames = []
        for eid, volley in sorted(tuple(self.active.items())):
            if not volley.played and now + 1e-9 >= volley.activation_at - .2:
                frames.append(self._buff(volley, 617, volley.expires_at - volley.activation_at + .2))
                volley.played = True
            if not volley.activated and now + 1e-9 >= volley.activation_at:
                frames.append(self._buff(volley, 615 if volley.archetype == LINE_ARCHETYPE else 613,
                                         volley.expires_at - volley.activation_at))
                volley.activated = True
            if not volley.dead and now + 1e-9 >= volley.expires_at:
                frames.append((1072, lifecycle_wire.build_hero_death(eid, 0xFFFFFFFF)))
                frames.append(self._buff(volley, 61, 2.2, self_source=True))
                volley.dead = True
            if volley.dead and now + 1e-9 >= volley.expires_at + 3.8:
                frames.extend(((1073, struct.pack('>IH', eid, 0)),
                               (1035, struct.pack('>IH', eid, 0))))
                self.actor_slots.release(eid)
                del self.active[eid]
        return frames

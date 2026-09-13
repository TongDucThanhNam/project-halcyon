"""Nonhero actor creation from measured, externally held spawn templates.

Registry ids 357..364 name jungle archetypes; the corresponding 1010 actor
class is 0x4dd5b7d0. Unmapped serializer fields (including +92..95) remain in
the user's external corpus. This module never ships captured payload bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
import math
from pathlib import Path
import struct

from . import decode, roster
from .paths import research_dir, runtime_corpus_dir

JUNGLE_CLASS = 0x4DD5B7D0
JUNGLE_ARCHETYPES = frozenset(range(357, 365))
REQUIRED_NEUTRAL_ARCHETYPES = frozenset((357, 359, 360, 362, 363))
STRUCTURE_CLASS = 0xC10B41DA
STRUCTURE_ARCHETYPES = frozenset((292, 293, 369, 370, 371, 372))
LANE_CLASS = 0xEB39CE55
LANE_ARCHETYPES = frozenset((365, 366, 367, 368))


def _patch_team_state(body, team, *, actor_index=None):
    """Measured team column/state; +120 is actor-specific, not team minus one.

    126-byte creations initialize the selected team column to 1. The
    corresponding 122-byte snapshots use 15. Other columns can contain
    runtime visibility/state bits, which are not valid for a fresh capture.
    Same-class owned Crystal Miners use +120=4/5; shops use 255. Preserve
    that opaque field unless the own-client experiment explicitly overrides it.
    """
    state = 15 if len(body) == 122 else 1
    body[96:99] = bytes(state if side == team else 0 for side in range(3))
    body[121] = team
    if actor_index is not None:
        if type(actor_index) is not int or not 0 <= actor_index <= 255:
            raise ValueError('opaque actor index must fit one byte')
        body[120] = actor_index


@dataclass(frozen=True)
class NativeActorTemplate:
    """One measured creation (126 B) or replay snapshot (122 B) record."""
    payload: bytes
    source: str = ''

    def __post_init__(self):
        if len(self.payload) not in (122, 126):
            raise ValueError('unsupported native actor record shape')
        archetype, entity_class = struct.unpack_from('>II', self.payload)
        expected = (STRUCTURE_CLASS if archetype in STRUCTURE_ARCHETYPES else
                    LANE_CLASS if archetype in LANE_ARCHETYPES else
                    JUNGLE_CLASS if archetype in JUNGLE_ARCHETYPES else None)
        if entity_class != expected:
            raise ValueError('unsupported actor archetype/class combination')

    @property
    def archetype(self):
        return struct.unpack_from('>I', self.payload)[0]

    @property
    def team(self):
        return self.payload[121]

    @property
    def position(self):
        return (struct.unpack_from('>f', self.payload, 12)[0],
                struct.unpack_from('>f', self.payload, 20)[0])

    @property
    def health(self):
        return struct.unpack_from('>ff', self.payload, 36) if len(self.payload) == 122 else None


class NativeActorCatalog:
    """External same-archetype/team records; unknown serializer bytes stay external.

    The 122-byte form is proved in the client's VGR state snapshots. Its use
    for a live reconnect is an explicit client integration experiment.
    """
    def __init__(self, templates=()):
        self.templates = {}
        for template in templates:
            key = template.archetype, template.team, len(template.payload)
            # Static Vain turrets share a blueprint but have distinct authored
            # heights/facing. Retain each placement; other actors need one form.
            placement = tuple(round(v, 3) for v in template.position) if template.archetype in STRUCTURE_ARCHETYPES else None
            self.templates.setdefault(key, {}).setdefault(placement, template)

    @classmethod
    def from_frames(cls, frames, source=''):
        templates = []
        for opcode, payload in frames:
            if opcode != 1010 or len(payload) not in (122, 126):
                continue
            archetype, entity_class = struct.unpack_from('>II', payload)
            if ((archetype in STRUCTURE_ARCHETYPES and entity_class == STRUCTURE_CLASS)
                    or (archetype in LANE_ARCHETYPES and entity_class == LANE_CLASS)
                    or (archetype in JUNGLE_ARCHETYPES and entity_class == JUNGLE_CLASS)):
                templates.append(NativeActorTemplate(payload, source))
        return cls(templates)

    def template_for(self, archetype, team, x, y, *, snapshot=False):
        candidates = self.templates.get((archetype, team, 122 if snapshot else 126), {})
        if not candidates:
            shape = 'snapshot' if snapshot else 'creation'
            raise ValueError(f'no external {shape} record for actor archetype {archetype}, team {team}')
        return min(candidates.values(), key=lambda t: ((t.position[0] - x) ** 2 + (t.position[1] - y) ** 2, t.position))

    def build(self, archetype, eid, x, y, slot, *, team, snapshot=False,
              hp=None, facing=None, height=None, experimental_capture=False,
              actor_index=None):
        if eid in roster.HERO_SPAWNS:
            raise ValueError('native nonhero record cannot create a hero')
        if not isinstance(slot, int) or not 0 <= slot <= 255:
            raise ValueError('actor slot must fit one byte')
        if not all(math.isfinite(value) for value in (x, y)):
            raise ValueError('actor position must be finite')
        if team not in (0, 1, 2):
            raise ValueError('invalid actor team')
        if actor_index is not None and not experimental_capture:
            raise ValueError('opaque actor-index mutation requires experimental_capture=True')
        if hp is not None and not snapshot:
            raise ValueError('126-byte creation has no HP fields; request the measured snapshot form')
        try:
            template = self.template_for(archetype, team, x, y, snapshot=snapshot)
        except ValueError:
            if not experimental_capture or archetype not in (362, 364) or team not in (1, 2):
                raise
            # Registry-proved sibling class, measured neutral serializer form.
            # No captured Gold/364 form exists in the current external corpus.
            template = self.template_for(363 if archetype == 364 else 362, 0, x, y, snapshot=snapshot)
        body = bytearray(template.payload)
        struct.pack_into('>I', body, 0, archetype)
        struct.pack_into('>I', body, 8, eid)
        struct.pack_into('>f', body, 12, x)
        struct.pack_into('>f', body, 20, y)
        body[116] = slot  # Same offset in BOTH measured forms, not shifted.
        if team != template.team or actor_index is not None:
            _patch_team_state(body, team, actor_index=actor_index)
        if facing is not None:
            struct.pack_into('>f', body, 24, facing[0])
            struct.pack_into('>f', body, 32, facing[1])
        if height is not None:
            struct.pack_into('>f', body, 16, height)
        if hp is not None:
            current, maximum = hp
            if not all(math.isfinite(value) for value in hp) or not 0 <= current <= maximum or maximum <= 0:
                raise ValueError('snapshot HP must satisfy 0 <= current <= positive maximum')
            struct.pack_into('>ff', body, 36, current, maximum)
        return bytes(body)


@dataclass(frozen=True)
class SpawnTemplate:
    archetype: int
    payload: bytes
    source: str = ''

    def __post_init__(self):
        if len(self.payload) != 126 or struct.unpack_from('>II', self.payload) != (self.archetype, JUNGLE_CLASS):
            raise ValueError('not a measured jungle actor creation record')
        if self.archetype not in JUNGLE_ARCHETYPES:
            raise ValueError('unsupported jungle archetype')


class SpawnCatalog:
    def __init__(self, templates):
        self.templates = dict(templates)

    @classmethod
    def from_frames(cls, frames, source=''):
        templates = {}
        for opcode, payload in frames:
            if opcode != 1010 or len(payload) != 126:
                continue
            archetype, entity_class = struct.unpack_from('>II', payload)
            if archetype in JUNGLE_ARCHETYPES and entity_class == JUNGLE_CLASS:
                templates.setdefault(archetype, SpawnTemplate(archetype, payload, source))
        return cls(templates)

    def build(self, archetype, eid, x, y, seq, *, team=0, facing=None,
              owner_index=None, opaque_word=None, experimental_capture=False,
              actor_index=None):
        if archetype not in JUNGLE_ARCHETYPES or eid in roster.HERO_SPAWNS:
            raise ValueError('jungle creation cannot create a hero or unknown archetype')
        if team not in (0, 1, 2):
            raise ValueError('invalid actor team')
        if not isinstance(seq, int) or not 0 <= seq <= 255:
            raise ValueError('actor slot must fit one wire byte; wrapping would alias a live actor')
        if not all(math.isfinite(value) for value in (x, y)):
            raise ValueError('actor position must be finite')
        if owner_index is not None:
            if actor_index is not None:
                raise ValueError('specify only actor_index; owner_index is its legacy spelling')
            actor_index = owner_index
        if actor_index is not None and not experimental_capture:
            raise ValueError('opaque actor-index mutation requires experimental_capture=True')
        template = self.templates.get(archetype)
        if template is None and archetype == 364 and experimental_capture:
            # Registry-proved captured archetype; mutation of its neutral
            # sibling's serializer template is explicitly an own-client test.
            template = self.templates.get(363)
        if template is None:
            raise ValueError(f'no external 126-byte spawn evidence for archetype {archetype}')
        original_team = template.payload[121]
        if team != original_team and not experimental_capture:
            raise ValueError('faction mutation requires experimental_capture=True until capture evidence exists')
        body = bytearray(template.payload)
        struct.pack_into('>III', body, 0, archetype, JUNGLE_CLASS, eid)
        struct.pack_into('>f', body, 12, x)
        struct.pack_into('>f', body, 20, y)
        if facing is not None:
            struct.pack_into('>f', body, 24, facing[0])
            struct.pack_into('>f', body, 32, facing[1])
        body[116] = seq
        if team != original_team or actor_index is not None:
            _patch_team_state(body, team, actor_index=actor_index)
        if opaque_word is not None:
            if len(opaque_word) != 4:
                raise ValueError('opaque serializer field must be four bytes')
            body[92:96] = opaque_word
        return bytes(body)


@lru_cache(maxsize=4)
def _load_catalog(paths):
    templates = {}
    for entry in paths:
        root = Path(entry)
        candidates = [root] if root.is_file() else sorted(root.glob('*.vgr')) if root.is_dir() else []
        for path in candidates:
            if path.suffix.lower() != '.vgr':
                continue
            frames, stats = decode.walk_vgr(str(path))
            if stats['failures']:
                raise ValueError(f'cannot use malformed external spawn corpus: {path}')
            catalog = SpawnCatalog.from_frames(((op, payload) for _, op, payload in frames), str(path))
            for archetype, template in catalog.templates.items():
                templates.setdefault(archetype, template)
    missing = REQUIRED_NEUTRAL_ARCHETYPES - templates.keys()
    if missing:
        raise FileNotFoundError('external jungle spawn records missing for ' + ','.join(map(str, sorted(missing)))
            + '; set HALCYON_SPAWN_CORPUS to directories containing your own .vgr captures (including match 6 Kraken spawn)')
    return SpawnCatalog(templates)


def _source_paths(path=None):
    if path is not None:
        paths = (str(path),)
    elif os.environ.get('HALCYON_SPAWN_CORPUS'):
        paths = tuple(os.environ['HALCYON_SPAWN_CORPUS'].split(os.pathsep))
    else:
        paths = (str(runtime_corpus_dir()),
                 str(research_dir('vg_max') / 'vgr5' / 'vgr5'),
                 str(research_dir('vg_max') / 'vgr' / 'vgrtmp'))
    return paths


def load_spawn_catalog(path=None):
    return _load_catalog(_source_paths(path))


@lru_cache(maxsize=4)
def _load_native_catalog(paths):
    templates = []
    for entry in paths:
        root = Path(entry)
        candidates = [root] if root.is_file() else sorted(root.glob('*.vgr')) if root.is_dir() else []
        for path in candidates:
            if path.suffix.lower() != '.vgr':
                continue
            frames, stats = decode.walk_vgr(str(path))
            if stats['failures'] or stats.get('trailing'):
                raise ValueError(f'cannot use malformed external actor corpus: {path}')
            catalog = NativeActorCatalog.from_frames(((op, body) for _, op, body in frames), str(path))
            templates.extend(template for group in catalog.templates.values() for template in group.values())
    catalog = NativeActorCatalog(templates)
    required = {(archetype, team, 126) for archetype in (369, 370, 371, 372) for team in (1, 2)}
    required.update(((292, 1, 126), (293, 2, 126)))
    missing = required - catalog.templates.keys()
    if missing:
        raise FileNotFoundError('external native structure creation records missing: ' + str(sorted(missing))
            + '; set HALCYON_SPAWN_CORPUS to your own VGR directories including match bootstrap chunks')
    return catalog


def load_native_actor_catalog(path=None):
    return _load_native_catalog(_source_paths(path))

"""Jungle ordinary action ordinals, joined to native CFF and recorded 1045.

357–360 have independent native recordings for both 0 and 1. The same
direct NPC action vector identifies ordinary 0/1 for 361–364; critical,
root, spawn and victory entries are excluded. Alternation is deterministic
presentation policy. NPC attack/contact timing is not inferred here.
"""
from .attack_wire import build_attack_start


MEASURED_BASIC_VARIANTS = {357: (0, 1), 358: (0, 1), 359: (0, 1), 360: (0, 1)}
SOURCE_BASIC_VARIANTS = {361: (0, 1), 362: (0, 1), 363: (0, 1), 364: (0, 1)}


def basic_variant_for(archetype: int, ordinal: int = 0) -> int | None:
    variants = MEASURED_BASIC_VARIANTS.get(archetype) or SOURCE_BASIC_VARIANTS.get(archetype)
    return variants[ordinal % len(variants)] if variants else None


def build_basic_attack(source_eid: int, target_eid: int, archetype: int,
                       ordinal: int = 0) -> tuple[int, bytes]:
    variant = basic_variant_for(archetype, ordinal)
    if variant is None:
        raise ValueError(f'no grounded jungle ordinary action for archetype {archetype}')
    return 1045, build_attack_start(source_eid, target_eid, variant)

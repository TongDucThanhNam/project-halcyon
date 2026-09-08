"""Measured basic-attack presentation commands.

Each ordinary attack starts with 1045 and an immediate current-position 1070.
In vgfull this pairing holds for 127/127 Adagio attacks (variant 7 or 8) and
108/108 Baptiste attacks (7, 8, 10 or 11). The variant byte's detailed meaning
is unresolved; callers must choose a variant measured for the actor's kit.
Ordinary ranged projectile creation is a separate 1037 release command;
see projectile_wire. The older inference that 1045 alone creates the bullet
was disproved by the operator's Skye test and independent native records.
"""
from __future__ import annotations

import struct

from . import roster

OP_ATTACK_START = 1045
ADAGIO_BASIC_VARIANTS = (7, 8)
BAPTISTE_BASIC_VARIANTS = (7, 8, 10, 11)
MELEE_MINION_BASIC_VARIANTS = (0, 1, 2)
RANGED_MINION_BASIC_VARIANTS = (0, 1)

# Joined 1006 hero IDs -> 1045 -> negative 1054 class-5 hits from the external
# VGR corpus. These are ordinary observed variants; special/empowered variants
# are intentionally not selected here (e.g. Baptiste 7/8, Koshka 3, Vox 12).
# Variant selection itself is not decoded. Alternating this measured set is
# explicit deterministic presentation policy, not recovered native logic.
MEASURED_BASIC_VARIANTS = {
    242: (9, 10),       # Catherine
    244: (7, 8),        # Adagio
    245: (9, 10),       # Koshka
    253: (7, 8),        # Joule
    254: (7, 8),        # Registry Hero009
    256: (11, 12),      # Registry Sayoc
    258: (10, 11),      # Vox
    260: (10, 11),      # Registry Hero016
    265: (13, 14),      # Skye
    266: (7, 8),        # Reim
    267: (7, 8),        # Kestrel
    268: (9, 10),       # Alpha
    274: (14, 15),      # Ozo
    275: (8, 9),        # Lance
    279: (7, 8),        # Phinn
    393: (7, 8),        # Flicker
    396: (10, 11),      # Grumpjaw
    397: (10, 11),      # Tony
    399: (10, 11),      # Baptiste, before empowered attacks
    408: (8, 9),        # Churnwalker
    409: (7, 8),        # Lorelai
    418: (9,),          # Magnus; metadata identifies 7/8 as perk/critical actions
    432: (9, 10),       # Silvernail (0 is the reduced-damage extra shot)
    439: (8, 10, 12),   # Yates
    913: (8, 9),        # Leo
    915: (8, 9),        # Caine
    924: (11, 12),      # Viola
    925: (8, 9),        # Amael
}

# Native header PTCH[108] lists attack groups. Flatten their ordinary then
# critical action vectors after the kit entries and four shared actions.
# The join agrees with recorded actions for 28 heroes, including multiple
# conditional groups on Skye/Baptiste/Yates. These three kits lack recorded
# attack samples; their named DefaultAttack/AltAttack entries supply the rows.
# Reproduce with Tools/Teardown/inspect_attack_actions.py.
SOURCE_BASIC_VARIANTS = {243: (8, 9), 285: (7, 8), 395: (8, 9)}


def basic_variant_for(hero_id, ordinal=0):
    """Cycle recorded or native-metadata ordinary actions; unknown stays None."""
    variants = MEASURED_BASIC_VARIANTS.get(hero_id) or SOURCE_BASIC_VARIANTS.get(hero_id)
    return variants[ordinal % len(variants)] if variants else None


def build_attack_start(source_eid, target_eid, variant):
    """The full measured 14-byte command; this begins presentation, not damage."""
    if not 0 <= variant <= 255:
        raise ValueError('attack presentation variant must fit one byte')
    if target_eid == 0xffffffff:
        raise ValueError('an attack start must name a real target actor')
    return struct.pack('>IIB', source_eid, target_eid, variant) + bytes(5)


def build_attack_start_frames(source_eid, target_eid, variant, x, y):
    """Emit once at windup start, using the attacker's current position."""
    return [(OP_ATTACK_START, build_attack_start(source_eid, target_eid, variant)),
            (1070, roster.build_position(source_eid, x, y))]

"""Native cast action indices, joined to 4.13 hero INST pointer vectors.

1045 is a targeted action start; 1046 is a ground-aimed action start. Their
u8 action is the native action-vector ordinal, NOT necessarily a UI slot.
All payload fields below are supported by own-corpus structural joins.

The common recall action follows the hero's own entries: directly measured
for Catherine (5), Adagio (3), and Phinn (3); other rows apply that shared
rule to the recovered vector length. Unknown heroes/actions return None.
"""
from __future__ import annotations

import math
import struct

from .hero_balance import HERO_NAMES

# selection ID: (A, B, C, hero-specific entry count / common recall ordinal).
# None means no exact A/B/C symbol exists, usually because the kit has forms.
# Reproduce with Tools/Teardown/inspect_ability_actions.py against the source
# joined by $TEMP/vg_max/inst_names.tsv. No client assets are retained here.
HERO_ACTIONS = {
    242: (1, 2, 3, 5), 243: (0, 1, 2, 4), 244: (0, 1, 2, 3),
    245: (0, 1, 2, 5), 246: (0, 1, 2, 3), 249: (0, 2, 3, 5),
    250: (1, 2, 3, 5), 253: (0, 1, 2, 3), 254: (0, 1, 2, 3),
    255: (0, 1, 2, 5), 256: (0, 1, 2, 7), 257: (0, 1, 2, 3),
    258: (0, 1, 2, 6), 259: (0, 1, 2, 3), 260: (0, 1, 2, 6),
    261: (1, 2, 3, 4), 265: (0, 2, 4, 5), 266: (0, 1, 2, 3),
    267: (0, 1, 2, 3), 268: (0, 1, 2, 5), 269: (0, 2, 3, 4),
    273: (0, 3, 4, 6), 274: (None, 3, 8, 10), 275: (0, 1, 2, 4),
    276: (1, 3, 4, 5), 279: (0, 1, 2, 3), 280: (0, 1, 2, 3),
    281: (None, None, None, 6), 285: (0, 1, 2, 3),
    393: (0, 1, 2, 3), 395: (1, 2, 3, 4), 396: (1, 2, 3, 6),
    397: (0, 4, 5, 6), 399: (0, 1, 2, 3), 403: (0, 1, 2, 4),
    406: (0, 1, 2, 3), 408: (0, 1, 2, 4), 409: (0, 1, 2, 3),
    412: (0, 1, 2, 3), 413: (0, 4, 8, 9), 418: (0, 1, 2, 3),
    420: (0, 1, 2, 3), 421: (0, 1, 2, 3), 423: (0, 1, 2, 3),
    424: (0, 1, 2, 3), 425: (0, 1, 2, 3), 429: (0, 2, 3, 4),
    432: (2, 3, 4, 5), 435: (0, 1, 3, 4), 436: (0, 2, 3, 5),
    439: (0, 2, 3, 4), 440: (0, 1, 2, 5), 445: (0, 1, 4, 5),
    446: (0, 1, 2, 3), 447: (0, 1, 2, 9), 913: (0, 1, 2, 4),
    915: (0, 1, 2, 4), 916: (0, 1, 2, 7), 919: (0, 1, 2, 5),
    922: (0, 1, 2, 3), 924: (0, 1, 3, 7), 925: (0, 1, 2, 4),
    926: (0, 1, 2, 4), 927: (0, 1, 2, 7), 929: (0, 1, 2, 4),
}

_NAME_IDS = {name: hero_id for hero_id, name in HERO_NAMES.items()}
_NAME_IDS.update(Taka=256, Krul=254, Skaarf=255, Rona=260)


def hero_action_variant(hero_id: int | str, action: str) -> int | None:
    if isinstance(hero_id, str):
        hero_id = _NAME_IDS.get(hero_id)
    row = HERO_ACTIONS.get(hero_id)
    column = {'A': 0, 'B': 1, 'C': 2, 'recall': 3}.get(action)
    return row[column] if row is not None and column is not None else None


def hero_slot_for_action(hero_id: int | str, action: int) -> int | None:
    """Cast intents carry native action indices; skill-upgrade intents use UI slots."""
    if type(action) is not int:
        return None
    for slot, name in enumerate("ABC"):
        if hero_action_variant(hero_id, name) == action:
            return slot
    return None


def build_target_cast(source: int, target: int | None, action: int) -> bytes:
    return struct.pack('>IIB5x', source, 0xffffffff if target is None else target, action)


def build_ground_cast(source: int, x: float, y: float, action: int, *, z: float = 0.0) -> bytes:
    if not all(math.isfinite(value) for value in (x, y, z)):
        raise ValueError('ground-cast coordinates must be finite')
    return struct.pack('>IfffB5x', source, x, z, y, action)

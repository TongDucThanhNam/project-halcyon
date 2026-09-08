"""Measured 1162 cooldown snapshots and native ability-name tags.

The two floats are remaining cooldown and full duration. The six state bytes
are retained losslessly; constructors use the combinations observed for ordinary
hero abilities and equipped item actives. See solo-sandbox-items.md for evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

PAYLOAD_SIZE = 22
_LAYOUT = struct.Struct(">IIff6s")


def native_ability_tag(symbol: str) -> int:
    """FNV-1a of an exact native Ability__ symbol, without surrounding stars."""
    if not symbol.startswith("Ability__") or not symbol.isascii() or "*" in symbol:
        raise ValueError("expected an unadorned native Ability__ symbol")
    value = 2166136261
    for octet in symbol.encode("ascii"):
        value = ((value ^ octet) * 16777619) & 0xFFFFFFFF
    return value


RECALL_TAG = native_ability_tag("Ability__Withdraw")
DANCE_TAG = native_ability_tag("Ability__Emote_Dance")
TAUNT_TAG = native_ability_tag("Ability__Emote_Taunt")
DEFAULT_ATTACK_TAG = 0xD60C580B  # repeated corpus identity; native symbol is open

# Symbols are read from the corresponding native item's structured metadata.
# Aegis uses UpgradedReflexBlock; synthesizing a tag from its display name fails.
ITEM_ABILITY_SYMBOLS = {
    "sprint_boots": "Ability__Item__SprintBoots",
    "travel_boots": "Ability__Item__TravelBoots",
    "halcyon_chargers": "Ability__Item__HalcyonChargers",
    "fountain_of_renewal": "Ability__Item__FountainOfRenewal",
    "reflex_block": "Ability__Item__ReflexBlock",
    "crucible": "Ability__Item__Crucible",
    "aegis": "Ability__Item__UpgradedReflexBlock",
    "atlas_pauldron": "Ability__Item__AtlasPauldron",
    "healing_flask": "Ability__Item__HealingFlask",
    "vision_totem": "Ability__Item__VisionTotem",
}
ITEM_TAGS = {key: native_ability_tag(symbol) for key, symbol in ITEM_ABILITY_SYMBOLS.items()}

# Full-duration floats in the external replay snapshots.
MEASURED_ITEM_COOLDOWNS = {
    "sprint_boots": 150.0,
    "travel_boots": 90.0,
    "fountain_of_renewal": 75.0,
    "reflex_block": 90.0,
    "crucible": 75.0,
    "healing_flask": 120.0,
    "vision_totem": 150.0,
}

# Exact named Cooldown records in native item/ability INST metadata. The three
# additional actives are absent from this bounded replay corpus but their
# durations are available directly from the client rule data.
NATIVE_ITEM_COOLDOWNS = {
    **MEASURED_ITEM_COOLDOWNS,
    "halcyon_chargers": 45.0,
    "aegis": 45.0,
    "atlas_pauldron": 45.0,
}

# These exact A/B/C symbols occur in each corresponding native hero INST.
# Ozo/Malene use multipart names and are intentionally absent from this generic
# fallback; a display name alone is insufficient to bind a hero's ability tags.
VERIFIED_HERO_ABILITY_NAMES = {
    242: "Catherine", 243: "Ringo", 244: "Adagio", 245: "Koshka", 246: "Petal",
    249: "Glaive", 250: "SAW", 253: "Joule", 257: "Ardan", 258: "Vox",
    259: "Fortress", 261: "Baron", 265: "Skye", 266: "Reim", 267: "Kestrel",
    269: "Lyra", 273: "Idris", 275: "Lance", 276: "Samuel", 279: "Phinn",
    280: "Blackfeather", 285: "Celeste", 393: "Flicker", 395: "Gwen", 397: "Tony",
    403: "Reza", 406: "Grace", 408: "Churnwalker", 409: "Lorelai", 412: "Kensei",
    413: "Varya", 429: "Anka", 432: "Silvernail", 436: "Ylva", 913: "Leo",
    915: "Caine", 916: "Warhawk",
}

_READY_ABILITY = bytes((1, 1, 1, 0, 1, 0))
_UNLEARNED_AB = bytes((0, 0, 1, 0, 1, 0))
_UNLEARNED_C = bytes((0, 0, 1, 1, 1, 0))
_READY_ATTACK = bytes((1, 1, 0, 0, 0, 1))


@dataclass(frozen=True)
class InitialTimer:
    tag: int
    duration: float
    state: bytes


def _unlearned_abc(a: int, b: int, c: int) -> tuple[InitialTimer, ...]:
    # Native initial bursts use C, B, A order.
    return (InitialTimer(c, 0.0, _UNLEARNED_C), InitialTimer(b, 0.0, _UNLEARNED_AB),
            InitialTimer(a, 0.0, _UNLEARNED_AB))


def _initial(abilities: tuple[InitialTimer, ...], *, recall: int = RECALL_TAG,
             attack_duration: float | None = 0.7) -> tuple[InitialTimer, ...]:
    result = (InitialTimer(TAUNT_TAG, 5.0, _READY_ABILITY),
              InitialTimer(DANCE_TAG, 0.5, _READY_ABILITY),
              InitialTimer(recall, 0.5, _READY_ABILITY)) + abilities
    if attack_duration is not None:
        result += (InitialTimer(DEFAULT_ATTACK_TAG, attack_duration, _READY_ATTACK),)
    return result


# Complete first 1011 -> 1162 bursts from the external m2/m3/m4/vgr5 caches.
# Scalar tags, durations and interpreted flag combinations only. The original
# roster's fixed-seven lists silently omitted extra native ability/attack rows.
MEASURED_INITIAL_TIMERS = {
    244: _initial((InitialTimer(0xDF768139, 0.0, _UNLEARNED_C),
                   InitialTimer(0x4454D39B, 0.0, bytes((1, 1, 1, 0, 0, 0))),
                   InitialTimer(0xDE767FA6, 0.0, _UNLEARNED_AB),
                   InitialTimer(0xDD767E13, 0.0, _UNLEARNED_AB)), recall=0xBE0716FA),
    245: _initial((InitialTimer(0x36C7A4F7, 20.0, _READY_ABILITY),)
                  + _unlearned_abc(0x68862E1F, 0x69862FB2, 0x6A863145)),
    253: _initial((InitialTimer(0x65BBCC86, 0.0, bytes((1, 1, 1, 1, 0, 0))),
                   InitialTimer(0x0C76237B, 0.0, _UNLEARNED_C),
                   InitialTimer(0x0B7621E8, 0.0, bytes((0, 0, 1, 0, 1, 1))),
                   InitialTimer(0x0E7626A1, 0.0, _UNLEARNED_AB)), recall=0xB87E7670),
    254: _initial(_unlearned_abc(0xEC35BB90, 0xEF35C049, 0xEE35BEB6),
                  recall=0x553FCD73, attack_duration=0.6),
    257: _initial(_unlearned_abc(0xD575F970, 0xD875FE29, 0xD775FC96)),
    258: _initial(_unlearned_abc(0x19616CF9, 0x16616840, 0x176169D3)),
    267: _initial((InitialTimer(0x668CCB9E, 0.0, _UNLEARNED_C),
                   InitialTimer(0x678CCD31, 0.0, _UNLEARNED_AB),
                   InitialTimer(0x648CC878, 0.0, bytes((0, 0, 1, 0, 0, 0)))), recall=0x58D0428B),
    268: _initial((InitialTimer(0x49D725BB, 0.0, _UNLEARNED_C),
                   InitialTimer(0xCD8619D8, 0.0, bytes((1, 1, 1, 1, 0, 0))))
                  + _unlearned_abc(0xB5DC2AEA, 0xB4DC2957, 0xB3DC27C4), recall=0x26312D75),
    269: _initial(_unlearned_abc(0x589C2E36, 0x579C2CA3, 0x569C2B10), attack_duration=0.6),
    279: _initial(_unlearned_abc(0x4D70217F, 0x4E702312, 0x4F7024A5), attack_duration=0.95),
    396: _initial(_unlearned_abc(0x0E5F6713, 0x0F5F68A6, 0x105F6A39)),
    399: _initial(_unlearned_abc(0x7511F55E, 0x7411F3CB, 0x7311F238)),
    429: _initial(_unlearned_abc(0x232A20B9, 0x202A1C00, 0x212A1D93)),
    915: _initial((InitialTimer(0xBA121030, 1.0, bytes((1, 1, 1, 0, 1, 1))),)
                  + _unlearned_abc(0x332DE7E0, 0x362DEC99, 0x352DEB06)),
    924: _initial(_unlearned_abc(0x16FA5609, 0x13FA5150, 0x916E3893)),
    925: _initial((InitialTimer(0xE7FC3F5D, 0.0, _UNLEARNED_AB),)
                  + _unlearned_abc(0x60482B06, 0x5F482973, 0x5E4827E0)),
}


@dataclass(frozen=True)
class TimerTick:
    eid: int
    tag: int
    remaining: float
    duration: float
    state: bytes

    def encode(self) -> bytes:
        for name, value in (("eid", self.eid), ("tag", self.tag)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFFFFFF:
                raise ValueError(f"{name} must fit u32")
        for value in (self.remaining, self.duration):
            if not math.isfinite(value) or value < 0:
                raise ValueError("cooldown values must be finite and nonnegative")
        if not isinstance(self.state, bytes) or len(self.state) != 6:
            raise ValueError("1162 state must be six bytes")
        return _LAYOUT.pack(self.eid, self.tag, self.remaining, self.duration, self.state)


def parse_timer_tick(payload: bytes) -> TimerTick:
    if len(payload) != PAYLOAD_SIZE:
        raise ValueError("1162 payload must be 22 bytes")
    tick = TimerTick(*_LAYOUT.unpack(payload))
    tick.encode()  # same finite/range checks as outgoing authoritative state
    return tick


def build_item_timer(eid: int, tag: int, remaining: float, duration: float,
                     *, state_count: int = 1) -> bytes:
    """Second byte is 1 for ordinary items, 2 for the recorded Vision Totem.

    Its exact charge/capacity interpretation remains open.
    """
    if isinstance(state_count, bool) or not isinstance(state_count, int) or not 0 <= state_count <= 255:
        raise ValueError("item state count must fit u8")
    state = bytes((int(remaining <= 0 and state_count > 0), state_count, 2, 0, 0, 0))
    return TimerTick(eid, tag, remaining, duration, state).encode()


def build_ability_timer(eid: int, tag: int, remaining: float, duration: float,
                        *, ultimate: bool = False, learned: bool = True) -> bytes:
    """Ordinary A/B or ultimate state; unusual native abilities may differ."""
    state = bytes((int(learned and remaining <= 0), int(learned), 1, int(ultimate), 1, 0))
    return TimerTick(eid, tag, remaining, duration, state).encode()


def build_initial_timers(eid: int, hero_id: int, *, ability_symbols: tuple[str, ...] = (),
                          attack_duration: float | None = None) -> list[bytes]:
    """Full measured burst, or shared timers plus verified native A/B/C symbols.

    Returns encoded 1162 payloads. For heroes outside the corpus, callers may
    supply the exact verified A/B/C symbols and a known attack duration. A
    generic donor hero's identities are never substituted for another hero.
    """
    specs = MEASURED_INITIAL_TIMERS.get(hero_id)
    if specs is None:
        if not ability_symbols and hero_id in VERIFIED_HERO_ABILITY_NAMES:
            name = VERIFIED_HERO_ABILITY_NAMES[hero_id]
            ability_symbols = tuple(f"Ability__{name}__{slot}" for slot in "ABC")
        if ability_symbols and len(ability_symbols) != 3:
            raise ValueError("fallback ability symbols must be a verified A/B/C triplet")
        abilities = _unlearned_abc(*(native_ability_tag(s) for s in ability_symbols)) if ability_symbols else ()
        specs = _initial(abilities, attack_duration=attack_duration)
    return [TimerTick(eid, spec.tag, 0.0, spec.duration, spec.state).encode() for spec in specs]

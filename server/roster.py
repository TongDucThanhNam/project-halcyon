"""Field-built roster + post-lock world-init messages; no captured payloads.

Live corrections, 2026-09-06:
- 1118 is a CLIENT hero selection, echoed by the server. Its (hero_id,
  selection_hash) pair is not a player credential. Unpicked slots use 0xffff.
- 1119 carries the COMMITTED selection hash: c2s [u32 hash][00 00] right
  after the lock, and the server echoes it. The committed hash replaces the
  clicked hash everywhere (1113 slots, 1006 +168, 1011 +4) — measured on
  match 1: clicked 2fd7245d, committed 4260123e.
- 1006 +168 is that committed hash as u32 (the earlier "XP f32" reading was
  the same bytes misread as a float).

1113 consists of an 8-byte countdown, sixteen 161-byte slot records, and
six trailing zero bytes. Bots are assigned heroes + locked exactly when the
7.0 s lock countdown starts (corpus match 1, measured).
"""
from __future__ import annotations

import hashlib
import math
import os
import struct

BOT_UUID_SENTINEL = "__Kindred_Player_Bot__"

# -- 1113 SNAPSHOT (the §15.8 trio's join variant) --------------------------
SNAPSHOT_PAYLOAD_SIZE = 2590      # 8 B countdown + 16×161 B slots + 6 B padding
SNAPSHOT_RECORD_BASE = 8
SNAPSHOT_RECORD_STRIDE = 161
SNAPSHOT_SLOT_COUNT = 16          # 1116/1137 handlers use a 16-slot player table
SNAPSHOT_ROSTER_SIZE = 6          # solo-bots: 3v3
SNAPSHOT_EMPTY_TOKEN = 0x10C2BAD9  # selection-hash init value of empty/bot slots
UNPICKED_HERO_ID = 0xFFFF

# Pick/lock flags published in 1113 slots (+2) and 1116 slot entries.
PICK_FLAG_SELECTED = 0x0100       # hero chosen, not locked (after c2s 1118)
PICK_FLAG_LOCKED = 0x0101         # locked (after c2s 1123+1119)

# Bot hero choices: (hero_id, selection_hash) pairs the real server assigns.
# Measured constants of this client build (match 1 countdown + 1011 blocks);
# the 244 pair is byte-identical to what a live client click on that hero
# produces, so the hash is a hero/skin property, not per-match state.
BOT_HERO_CHOICES = (
    (396, 0xBC155DEF),            # Alpha Bot
    (244, 0xF9FD7554),            # Beta Bot
    (399, 0x4A490296),            # Gamma Bot
    (254, 0x9D1AD5D3),            # Delta Bot
    (924, 0xE25ACB56),            # Epsilon Bot
)

# -- 1006 PLAYER_INFO -------------------------------------------------------
PLAYER_INFO_PAYLOAD_SIZE = 222
FNVL_EMPTY = 0x811C9DC5           # FNV-1a offset basis = hash of "" (ability slot)
BOT_CFG_CONST = 0xF1DEDAE3        # bot tail u32 at +200 (constant in corpus)

# -- 1108 / 1135 mode name, 1001 setup --------------------------------------
GAME_MODE_PAYLOAD_SIZE = 70       # [u32 0]["*mode*" padded]
MODE_NAME_PAYLOAD_SIZE = 70       # ["*mode*" padded] — no u32 prefix
GAME_SETUP_PAYLOAD_SIZE = 102

# -- 1011 hero block / 1162 timer -------------------------------------------
HERO_BLOCK_PAYLOAD_SIZE = 750
TIMER_TICK_PAYLOAD_SIZE = 22
TIMERS_PER_HERO = 7               # corpus: 7-8 1162 frames after each 1011

# -- small post-lock frames --------------------------------------------------
ACK_ZEROS_PAYLOAD_SIZE = 6        # s2c echoes of 1112/1123/1131/1132/1105/1134
COMMIT_ACK_PAYLOAD_SIZE = 6       # s2c 1119: [u32 committed hash][00 00]
HERO_READY_ACK_PAYLOAD_SIZE = 6   # s2c 1137: [u16 0][u16 eid][u16 0100]
PLAYER_TAG_PAYLOAD_SIZE = 14      # 1055: [u32 derived][10 B zeros]
SLOT_FLAGS_PAYLOAD_SIZE = 102     # 1116: 16 × [u32 eid][u16 flags] + 6 B pad

MODE_SOLO_BOTS = "GameMode_HF_SoloBots"   # bare name; builders add the stars


class Player:
    """One player slot, including its current hero selection."""

    __slots__ = ("handle", "team", "eid", "hero_id", "selection_hash", "uuid",
                 "is_bot", "pick_flags", "slot")

    def __init__(self, handle: str, team: int, eid: int, hero_id: int,
                 selection_hash: int, uuid: str, is_bot: bool):
        self.handle = handle
        self.team = team                 # 1 | 2 (corpus values)
        self.eid = eid                   # hero entity id: 1500 / 1515–1519
        self.hero_id = hero_id           # client hero selection, NOT a player id
        self.selection_hash = selection_hash
        self.uuid = uuid                 # account session uuid; bot sentinel
        self.is_bot = is_bot
        self.pick_flags = 0
        self.slot = 0                    # zero-based; set by the roster builder


def default_solo_bots(session_uuid: str, match_id: str):
    """Roster order = slot order = corpus order: local player first."""
    handles = ["Guest", "Alpha Bot", "Beta Bot", "Gamma Bot", "Delta Bot",
               "Epsilon Bot"]
    eids = (1500, 1515, 1516, 1517, 1518, 1519)
    players = [Player(handles[k], 1 if k < 3 else 2, eids[k], UNPICKED_HERO_ID,
                      0 if k == 0 else SNAPSHOT_EMPTY_TOKEN,
                      session_uuid if k == 0 else BOT_UUID_SENTINEL, k != 0)
               for k in range(SNAPSHOT_ROSTER_SIZE)]
    for k, p in enumerate(players):
        p.slot = k
    return players


def commit_lock(players, committed_hash: int | None = None):
    """Lock the whole roster: human players commit their (hero, hash) pair,
    bots take the measured hero choices — corpus: all slots 0101 with heroes
    the moment the 7.0 s lock countdown starts."""
    if committed_hash is not None and len(players) > 0 and not players[0].is_bot:
        players[0].selection_hash = committed_hash
        players[0].pick_flags = PICK_FLAG_LOCKED
    bot_choices_iter = iter(BOT_HERO_CHOICES)
    for p in players:
        if p.is_bot:
            try:
                hero_id, selection_hash = next(bot_choices_iter)
                p.hero_id = hero_id
                p.selection_hash = selection_hash
            except StopIteration:
                pass
            p.pick_flags = PICK_FLAG_LOCKED
        else:
            p.pick_flags = PICK_FLAG_LOCKED


# --------------------------------------------------------------------------
# 1113 SNAPSHOT — 8 B countdown + stride-161 player slots + 6 B padding
# --------------------------------------------------------------------------
# record: +0 occupied u8 · +1 slot u8 (zero-based) · +2 pick flags u16
#         +4 ff ff ff 00 · +8 team u8 · +9 hero id u16 · +11 eid u16
#         +13 selection hash u32 · +17 handle region 80 B · +97 identity 64 B
# String-region capacities follow field boundaries; corpus identities are UUIDs.

def build_snapshot(players, countdown=(300.0, 300.0), pick_flags: int | None = None) -> bytes:
    if len(players) != SNAPSHOT_ROSTER_SIZE:
        raise ValueError(f"roster must hold {SNAPSHOT_ROSTER_SIZE} players")
    payload = bytearray(struct.pack(">ff", *countdown))
    for k in range(SNAPSHOT_SLOT_COUNT):
        rec = bytearray(SNAPSHOT_RECORD_STRIDE)
        rec[1] = k
        rec[4:8] = b"\xff\xff\xff\x00"
        if k < len(players):
            p = players[k]
            rec[0] = 1
            struct.pack_into(">H", rec, 2, p.pick_flags if pick_flags is None else pick_flags)
            rec[8] = p.team
            struct.pack_into(">HHI", rec, 9, p.hero_id, p.eid, p.selection_hash)
            name = p.handle.encode("ascii")[:80]
            rec[17:17 + len(name)] = name
            ident = p.uuid.encode("ascii")[:64]
            rec[97:97 + len(ident)] = ident
        else:
            struct.pack_into(">HHI", rec, 9, UNPICKED_HERO_ID, 0xFFFF, SNAPSHOT_EMPTY_TOKEN)
        payload += rec
    payload += bytes(6)
    assert len(payload) == SNAPSHOT_PAYLOAD_SIZE
    return bytes(payload)


# --------------------------------------------------------------------------
# 1006 PLAYER_INFO — 222 B, one frame per player, roster order
# --------------------------------------------------------------------------
# +0 handle 64 B · +64 uuid 36 B · +160 hero eid u32 · +164 hero id u32
# +168 committed selection hash u32 · +172 const 0x9241F10E
# +176..221 loadout/tail union — shape verified, semantics [Open, minor]:
#   local: 7×FNV("") (ability slots) | ff ff 00 ff | 00 02 01 00 | 00 00 00 01
#   bot:   0 | instance-guid 16 B (derived; corpus value is a shared constant,
#          derivation unknown) | 0 | f1dedae3 | ff ff ff ff
#          | 00 02 0<team> 00 | 01 00 00 00

PLAYER_INFO_CONST = 0x9241F10E

def build_player_info(p: Player, match_id: str) -> bytes:
    body = bytearray(PLAYER_INFO_PAYLOAD_SIZE)
    name = p.handle.encode("ascii")[:64]
    body[0:len(name)] = name
    ident = p.uuid.encode("ascii")[:36]
    body[64:64 + len(ident)] = ident
    struct.pack_into(">I", body, 160, p.eid)
    struct.pack_into(">I", body, 164, p.hero_id)
    struct.pack_into(">I", body, 168, p.selection_hash)
    struct.pack_into(">I", body, 172, PLAYER_INFO_CONST)
    if p.is_bot:
        g = hashlib.md5(f"{match_id}|botguid".encode("ascii")).digest()
        body[180:196] = g                        # instance guid (derived [Open])
        struct.pack_into(">I", body, 200, BOT_CFG_CONST)
        body[204:208] = b"\xff\xff\xff\xff"
        struct.pack_into(">H", body, 208, 0x0002)
        body[210] = p.team
        body[212] = 0x01
    else:
        for k in range(7):                       # ability slots unpicked
            struct.pack_into(">I", body, 176 + 4 * k, FNVL_EMPTY)
        body[204:208] = b"\xff\xff\x00\xff"
        body[208:212] = b"\x00\x02\x01\x00"
        body[212:216] = b"\x00\x00\x00\x01"
    return bytes(body)


# --------------------------------------------------------------------------
# 1118 hero selection (c2s); s2c acknowledges the client-selected pair
# --------------------------------------------------------------------------

def build_hero_selection(p: Player) -> bytes:
    return struct.pack(">II", p.hero_id, p.selection_hash) + b"\x00" * 6


def parse_hero_selection(payload: bytes) -> tuple[int, int]:
    """Validate the measured shape; full catalog ID/hash validation is open."""
    if len(payload) != 14 or payload[8:] != bytes(6):
        raise ValueError("invalid 1118 hero-selection payload")
    hero_id, selection_hash = struct.unpack_from(">II", payload)
    if not 0 < hero_id < UNPICKED_HERO_ID:
        raise ValueError("hero selection outside populated u16 range")
    return hero_id, selection_hash


# --------------------------------------------------------------------------
# 1119 lock commit — c2s [u32 committed hash][00 00]; s2c echoes it
# --------------------------------------------------------------------------

def parse_commit_hash(payload: bytes) -> int:
    if len(payload) != COMMIT_ACK_PAYLOAD_SIZE or payload[4:] != bytes(2):
        raise ValueError("invalid 1119 commit payload")
    return struct.unpack_from(">I", payload)[0]


def build_commit_ack(selection_hash: int) -> bytes:
    return struct.pack(">I", selection_hash) + bytes(2)


# --------------------------------------------------------------------------
# small post-lock frames — 6 B zero acks (1123/1131/1132/1105/1134 echoes)
# --------------------------------------------------------------------------

def build_zero_ack() -> bytes:
    return bytes(ACK_ZEROS_PAYLOAD_SIZE)


def build_hero_ready_ack(eid: int) -> bytes:
    """s2c 1137: [u16 0][u16 eid][u16 0100] (corpus 00 00 05 dc 01 00)."""
    return struct.pack(">HHH", 0, eid, 0x0100)


def build_player_tag(p: Player, match_id: str) -> bytes:
    """1055, one per player at world init: [u32][10 B zeros]. The corpus u32
    did not match FNV/MD5 of handle or uuid — derivation [Open]; we use a
    deterministic per-match value so repeats are stable."""
    tag = hashlib.md5(f"{match_id}|1055|{p.eid}".encode("ascii")).digest()[:4]
    return tag + bytes(PLAYER_TAG_PAYLOAD_SIZE - 4)


def build_slot_flags(players) -> bytes:
    """1116, ~1 Hz after world init: 16 × [u32 eid][u16 flags] + 6 B pad.
    Corpus flags: local/humans 0100, bots 0101."""
    body = bytearray(SLOT_FLAGS_PAYLOAD_SIZE)
    for k in range(SNAPSHOT_SLOT_COUNT):
        off = k * 6
        if k < len(players):
            p = players[k]
            flags = PICK_FLAG_SELECTED if not p.is_bot else PICK_FLAG_LOCKED
            struct.pack_into(">IH", body, off, p.eid, flags)
    return bytes(body)


# --------------------------------------------------------------------------
# 1011 hero block — 750 B; header + stat run patched from HERO_INIT_DATA
# --------------------------------------------------------------------------
# +0 hero id u32 · +4 selection hash u32 · +8 eid u32 · +12 team u32
# +16 ff ff · +18.. stat run (see HERO_INIT_DATA: spawn/facing/scale/HP/
# speed prefix measured; deeper semantics [Open])
# tail: ff ff ff ff @+741 · slot-class u8 @+745 (corpus: slot 5 → 0x05)

def build_hero_block(p: Player) -> bytes:
    body = bytearray(HERO_BLOCK_PAYLOAD_SIZE)
    struct.pack_into(">I", body, 0, p.hero_id)
    struct.pack_into(">I", body, 4, p.selection_hash)
    struct.pack_into(">I", body, 8, p.eid)
    struct.pack_into(">I", body, 12, p.team)
    body[16:18] = b"\xff\xff"
    hero_data, donated = hero_init_for(p.hero_id)
    if hero_data is not None:
        for off, hexbytes in hero_data["runs"].items():
            raw = bytes.fromhex(hexbytes)
            body[off:off + len(raw)] = raw
    if donated:
        # These fields are independently decoded in the captured 1011 runs.
        # An unrecorded selection must receive its own numeric stats even while
        # the remaining presentation fields still use the bootstrap template.
        from .hero_balance import HERO_NAMES, STATS
        stats = STATS.get(HERO_NAMES.get(p.hero_id))
        if stats is not None:
            values = {42: stats.health_base, 46: stats.health_base,
                      74: stats.move_speed, 122: stats.energy_base, 126: stats.energy_base,
                      190: stats.armor_base, 202: stats.shield_base, 214: stats.weapon_base}
            for offset, value in values.items():
                struct.pack_into(">f", body, offset, value)
    # A hero outside the measured corpus roster reuses the donor's measured
    # stat run (see hero_init_for) — measured bytes, no invented values.
    for offset, value in ((294, 1.0), (314, 1.0), (318, 0.0), (322, 68.0)):
        struct.pack_into(">f", body, offset, value)
    body[741:745] = b"\xff\xff\xff\xff"
    body[745] = p.slot                          # corpus: slot 5 → 05
    return bytes(body)


# Live evidence 2026-09-07: a hero served with a zeroed stat run renders but
# GLIDES. Donor run restores rendering and level display, but walk-on-move
# animation requires locomotion state activation (see Docs/Teardown/vainglory-movement-anatomy.md §13.6).
# Unmeasured heroes reuse a measured DONOR run for valid stats and rendering.
HERO_INIT_DONOR_ID = 244

def hero_init_for(hero_id: int):
    """(init data or None, donated?) for a hero id."""
    data = HERO_INIT_DATA.get(hero_id)
    if data is not None:
        return data, False
    return HERO_INIT_DATA.get(HERO_INIT_DONOR_ID), True


# --------------------------------------------------------------------------
# 1135 mode name / 1108 game mode / 1001 game setup
# --------------------------------------------------------------------------

def _mode_star(mode: str) -> bytes:
    return f"*{mode}*".encode("ascii")

def build_mode_name(mode: str = MODE_SOLO_BOTS) -> bytes:
    s = _mode_star(mode)
    if len(s) > MODE_NAME_PAYLOAD_SIZE:
        raise ValueError("mode name too long")
    return s + bytes(MODE_NAME_PAYLOAD_SIZE - len(s))

def build_game_mode(mode: str = MODE_SOLO_BOTS) -> bytes:
    s = _mode_star(mode)
    if len(s) > GAME_MODE_PAYLOAD_SIZE - 4:
        raise ValueError("mode name too long")
    return struct.pack(">I", 0) + s + bytes(GAME_MODE_PAYLOAD_SIZE - 4 - len(s))

def build_game_setup(mode: str = MODE_SOLO_BOTS, hero_eid: int = 1500) -> bytes:
    """[u32 hero_eid][u32 1][0000][ffff][u32 0][03 03][14B 0][*mode*@+32]
    [zeros to +96][f32 1.0][u16 0100] — 102 B, corpus-shaped."""
    s = _mode_star(mode)
    body = bytearray(GAME_SETUP_PAYLOAD_SIZE)
    struct.pack_into(">I", body, 0, hero_eid)
    struct.pack_into(">I", body, 4, 1)
    body[10:12] = b"\xff\xff"
    body[16:18] = b"\x03\x03"
    body[32:32 + len(s)] = s
    struct.pack_into(">f", body, 96, 1.0)
    body[100:102] = b"\x01\x00"
    return bytes(body)


# Hero world-init constants: 1011 stat-run byte patches (offset -> hex
# bytes) and the 7 1162 timer (tag, tail) pairs per hero. The first six
# heroes were measured on the vgfull.pcap match-1 world init; the rest come
# from the same capture corpus re-walked (vg3/vgc2s/vg5_final, session keys
# recovered from the recorded uuids) — see the sweep note inside. The
# stat-run interior is otherwise unmapped (semantics [Open], bytes measured);
# offset 601 is a per-hero content GUID, stable across matches.
HERO_INIT_DATA = {
    924: {
        'eid': 1519,
        'runs': {
            18: '42a670a43fdf9ffa3f3851ec3f80',
            34: '80',
            42: '443440',
            46: '443440',
            74: '40733333',
            98: '3f80',
            122: '4391',
            126: '4391',
            190: '41a0',
            202: '41a0',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '820dd5b366bfd50a09d11ecf',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
            712: '010101010101010101',
            723: '0f',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0x916e3893, '0000000001010100'),
            (0x13fa5150, '0000000001000100'),
            (0x16fa5609, '0000000001000100'),
            (0xd60c580b, '3333010100000001'),
        ],
    },
    254: {
        'eid': 1518,
        'runs': {
            18: '429d33333fdf9ffac0a1eb853f80',
            34: '80',
            42: '444040',
            46: '444040',
            74: '4080',
            98: '3f80',
            122: '435c',
            126: '435c',
            190: '41f0',
            202: '41a0',
            214: '428c',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '45072069162baa6d91dcd074',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
            712: '010101010101010101',
            723: '0f',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x553fcd73, '0000010101000100'),
            (0xee35beb6, '0000000001010100'),
            (0xef35c049, '0000000001000100'),
            (0xec35bb90, '0000000001000100'),
            (0xd60c580b, '999a010100000001'),
        ],
    },
    399: {
        'eid': 1517,
        'runs': {
            18: '429f51ec3fdf9ffabf68f5c33f80',
            34: '80',
            42: '4438c0',
            46: '4438c0',
            74: '4079999a',
            98: '3f80',
            122: '438880',
            126: '438880',
            190: '41f0',
            202: '41a0',
            214: '429c',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '653947964e8874c3cd67e44e',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
            712: '010101010101010101',
            723: '0f',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0x7311f238, '0000000001010100'),
            (0x7411f3cb, '0000000001000100'),
            (0x7511f55e, '0000000001000100'),
            (0xd60c580b, '3333010100000001'),
        ],
    },
    244: {
        'eid': 1516,
        'runs': {
            18: 'c29a0f5c3fa0733cbff851ec3f80',
            34: '80',
            42: '442b40',
            46: '442b40',
            74: '40733333',
            98: '3f80',
            122: '43c8',
            126: '43c8',
            190: '41c8',
            202: '41a0',
            214: '4296',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '056c28d3afb26ab1210e54b2',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
            713: '0101010101010101',
            722: '0f',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0xbe0716fa, '0000010101000100'),
            (0xdf768139, '0000000001010100'),
            (0x4454d39b, '0000010101000000'),
            (0xde767fa6, '0000000001000100'),
            (0xdd767e13, '0000000001000100'),
        ],
    },
    396: {
        'eid': 1515,
        'runs': {
            18: 'c2a39eb83fa22f563ffc28f63f80',
            34: '80',
            42: '4443c0',
            46: '4443c0',
            74: '4079999a',
            98: '3f80',
            122: '436a',
            126: '436a',
            190: '41f0',
            202: '41a0',
            214: '4294',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            557: '01',
            561: '02',
            565: '03',
            596: '0303',
            601: 'ff5e498bf5a3485b22e4b5cf',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
            713: '0101010101010101',
            722: '0f',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0x105f6a39, '0000000001010100'),
            (0x0f5f68a6, '0000000001000100'),
            (0x0e5f6713, '0000000001000100'),
            (0xd60c580b, '3333010100000001'),
        ],
    },
    925: {
        'eid': 1500,
        'runs': {
            18: 'c29c5c293fa22f563f6147ae3f80',
            34: '80',
            42: '444f80',
            46: '444f80',
            74: '4079999a',
            98: '3f80',
            122: '438980',
            126: '438980',
            190: '41f0',
            202: '41a0',
            214: '42ac',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '1e3304fc948685f56c371076',
            636: '0d',
            640: '03',
            644: '03',
            668: '01',
            672: '01',
            676: '01',
            708: '01ffffffff0101010101010101',
            722: '0f',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0xe7fc3f5d, '0000000001000100'),
            (0x5e4827e0, '0000000001010100'),
            (0x5f482973, '0000000001000100'),
            (0x60482b06, '0000000001000100'),
        ],
    },
    # --- 2026-09-07 corpus sweep: same capture corpus re-walked for more
    # --- 1011/1162 init frames (vg3 + vgc2s + vg5_final pcaps, keys
    # --- recovered from the recorded session uuids). Byte-extraction rule
    # --- mirrors the six entries above; offset 18 truncated to the 12
    # --- match-stable spawn bytes (byte 30 proved match-variable), tail
    # --- 712-723 (ability/level state) dropped as match-variable. Timers
    # --- re-derived with the first-7-unique 1162 rule, validated to
    # --- reproduce the 924 stored set byte-for-byte.
    245: {
        'eid': 1518,
        'runs': {
            18: '429d33333fdf9ffac0a1eb85',
            34: '80',
            42: '4431c0',
            46: '4431c0',
            74: '4079999a',
            98: '3f80',
            122: '438c00',
            126: '438c00',
            190: '41f0',
            202: '41a0',
            214: '429e',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '115d35732f030a7688ae7bae',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0x36c7a4f7, '0000010101000100'),
            (0x6a863145, '0000000001010100'),
            (0x69862fb2, '0000000001000100'),
            (0x68862e1f, '0000000001000100'),
        ],
    },
    253: {
        'eid': 1515,
        'runs': {
            18: 'c2a39eb83fa22f563ffc28f6',
            34: '80',
            42: '443980',
            46: '443980',
            74: '4079999a',
            98: '3f80',
            122: '43c300',
            126: '43c300',
            190: '420c',
            202: '41c8',
            214: '4284',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '98a643feb0ebcce6cfb8b255',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0xb87e7670, '0000010101000100'),
            (0x65bbcc86, '0000010101010000'),
            (0x0c76237b, '0000000001010100'),
            (0x0b7621e8, '0000000001000101'),
            (0x0e7626a1, '0000000001000100'),
        ],
    },
    257: {
        'eid': 1519,
        'runs': {
            18: '42a670a43fdf9ffa3f3851ec',
            34: '80',
            42: '445180',
            46: '445180',
            74: '4079999a',
            98: '3f80',
            190: '420c',
            202: '41c8',
            214: '42a0',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: 'dd876f0b35e412d76c705454',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0xd775fc96, '0000000001010100'),
            (0xd875fe29, '0000000001000100'),
            (0xd575f970, '0000000001000100'),
            (0xd60c580b, '3333010100000001'),
        ],
    },
    258: {
        'eid': 1517,
        'runs': {
            18: '429f51ec3fdf9ffabf68f5c3',
            34: '80',
            42: '4426c0',
            46: '4426c0',
            74: '40733333',
            98: '3f80',
            122: '434800',
            126: '434800',
            190: '41c8',
            202: '41a0',
            214: '4258',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '8875f26fa4da1c5f03f0cb8e',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
        },
        'timers': None,          # [Open] vg5_final capture starts after the init burst
    },
    268: {
        'eid': 1515,
        'runs': {
            18: 'c2a39eb83fa22f563ffc28f6',
            34: '80',
            42: '443e40',
            46: '443e40',
            74: '40800000',
            98: '3f80',
            190: '41f0',
            202: '41a0',
            214: '42a6',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: 'e79e521c0c6071d0cd9e0de9',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x26312d75, '0000010101000100'),
            (0x49d725bb, '0000000001010100'),
            (0xcd8619d8, '0000010101010000'),
            (0xb3dc27c4, '0000000001010100'),
            (0xb4dc2957, '0000000001000100'),
        ],
    },
    279: {
        'eid': 1519,
        'runs': {
            18: '42a670a43fdf9ffa3f3851ec',
            34: '80',
            42: '445f00',
            46: '445f00',
            74: '40600000',
            98: '3f80',
            122: '438700',
            126: '438700',
            190: '420c',
            202: '41c8',
            214: '42be',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: 'c8ab8bb302852dd7dcccfaef',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0x4f7024a5, '0000000001010100'),
            (0x4e702312, '0000000001000100'),
            (0x4d70217f, '0000000001000100'),
            (0xd60c580b, '3333010100000001'),
        ],
    },
    429: {
        'eid': 1517,
        'runs': {
            18: '429f51ec3fdf9ffabf68f5c3',
            34: '80',
            42: '443b80',
            46: '443b80',
            74: '40800000',
            98: '3f80',
            122: '434800',
            126: '434800',
            190: '41f0',
            202: '41a0',
            214: '42a4',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '02',
            565: '03',
            596: '0303',
            601: '8e5d428fa96f323d3c776ccd',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0x212a1d93, '0000000001010100'),
            (0x202a1c00, '0000000001000100'),
            (0x232a20b9, '0000000001000100'),
            (0xd60c580b, '3333010100000001'),
        ],
    },
    915: {
        'eid': 1517,
        'runs': {
            18: '429f51ec3fdf9ffabf68f5c3',
            34: '80',
            42: '443b80',
            46: '443b80',
            74: '40733333',
            98: '3f80',
            190: '41c8',
            202: '41a0',
            214: '42a4',
            226: '3f',
            286: '4416',
            290: '4416',
            294: '3f80',
            314: '3f80',
            322: '4288',
            334: 'bf80',
            561: '01',
            565: '02',
            596: '0303',
            601: '052d93ba366b01b85ce7a862',
            636: '01',
            640: '01',
            644: '01',
            668: '01',
            672: '01',
            676: '01',
            708: '01',
        },
        'timers': [
            (0xb855d752, '0000010101000100'),
            (0x1e275dc1, '0000010101000100'),
            (0x022982b5, '0000010101000100'),
            (0xba121030, '0000010101000101'),
            (0x352deb06, '0000000001010100'),
            (0x362dec99, '0000000001000100'),
            (0x332de7e0, '0000000001000100'),
        ],
    },
}


# --------------------------------------------------------------------------
# 1070 position / 1012 move — the movement slice (corpus-measured)
# --------------------------------------------------------------------------

POSITION_PAYLOAD_SIZE = 14        # s2c 1070: [u32 eid][f32 x][f32 y][u16 0]
MOVE_PAYLOAD_SIZE = 14            # c2s 1012: [f32 x][f32 y][6B 0]
MOVE_TICK = 0.2                   # s2c 1070 cadence while moving (corpus)
MOVE_SPEED = 5.0                  # u/s; corpus hero 1070s span 4.8–6.6 u/s

# Spawn of the local hero entity: corpus hero 0x5dc's first 1070 after its
# first move command (matches the f32 pair in the corpus 1011 stat run).
SPAWN_X = float(os.environ.get("HALCYON_HERO_SPAWN_X", "-78.18000030517578"))      # 0xC29C5C29
SPAWN_Y = float(os.environ.get("HALCYON_HERO_SPAWN_Y", "0.8799999952316284"))      # 0x3F6147AE

# Authoritative hero spawn coordinates measured from corpus 1011 blocks
# Team 1 (Halcyon / Left): negative X
# Team 2 (Right): positive X
HERO_SPAWNS = {
    1500: (SPAWN_X, SPAWN_Y),
    1515: (-81.81, 1.267),
    1516: (-77.03, 1.254),
    1517: (79.66, 1.747),
    1518: (78.60, 1.747),
    1519: (83.22, 1.747),
}
HERO_SPAWNS_TEAM1 = [HERO_SPAWNS[1500], HERO_SPAWNS[1515], HERO_SPAWNS[1516]]
HERO_SPAWNS_TEAM2 = [HERO_SPAWNS[1517], HERO_SPAWNS[1518], HERO_SPAWNS[1519]]


def build_position(eid: int, x: float, y: float) -> bytes:
    """s2c 1070 — authoritative entity position."""
    return struct.pack(">IffH", eid, x, y, 0)


def build_entity_stat(eid: int, value: float, attr: int, w2: int = 0) -> bytes:
    """s2c 1053 — [eid][f32 value][u16 attr][u16 w2][u16 0], 14 B
    (corpus 2026-09-07: hero keepalive pair 6.0@0x0600 / 1.0@0x0800 @1 Hz)."""
    return struct.pack(">IfHHH", eid, value, attr, w2, 0)


def build_entity_pose_3d(eid: int, seq: int, x: float, height: float, z: float) -> bytes:
    """s2c 1018 — [eid][u16 0][u16 seq][f32 x][f32 height][f32 z][u16 0], 22 B
    (layout measured on bot heroes 2026-09-07; z ≈ −1070.y for our spawn
    frame, height 1.05 from the hero 1019 sample; semantics [Open])."""
    return struct.pack(">IHHfffH", eid, 0, seq, x, height, z, 0)


def parse_move(payload: bytes) -> tuple[float, float]:
    """c2s 1012 — move command to an absolute map target."""
    if len(payload) != MOVE_PAYLOAD_SIZE or payload[8:] != bytes(6):
        raise ValueError("invalid 1012 move payload")
    point = struct.unpack_from(">ff", payload)
    if not all(math.isfinite(value) for value in point):
        raise ValueError("nonfinite move target")
    return point


def build_move(x: float, y: float) -> bytes:
    """c2s 1012 move intent (14 B): [f32 x][f32 y][6B 0]."""
    return struct.pack(">ff", x, y) + bytes(6)


# --------------------------------------------------------------------------
# 1010 ENTITY_FULL_UPDATE — two measured variants (126 B / 122 B), zero
# hero coverage: all 6645 corpus 1010s across matches 1+5 carry non-hero
# eids only (minions/monsters/camp statics) — the real server never sends
# 1010 for a hero (hero state rides 1011 blocks + 1070 + 1053/1086 deltas).
# --------------------------------------------------------------------------
ENTITY_FULL_UPDATE_PAYLOAD_SIZE = 126       # no-HP variant (match 1 ×173,
ENTITY_FULL_UPDATE_HP_PAYLOAD_SIZE = 122    # match 1: 126 only; match 5: 821×126 + 5651×122
# +0 u32 eid (upper u16 always 0) · +4 u32 entity-class id — match 1 has 4
#   values, match 5 has 6 (c10b41da/3df641a9/4dd5b7d0/eb39ce55/…), each
#   mapping 1:1 to an eid group; no hero value exists, we keep 0 [Open]
# +8 u32 global entity-write tick: +1 per consecutive frame in a burst,
#   advances between bursts with the rest of the entity stream (measured
#   ~10.6..51.7 writes/s across windows — production rule [Open]; ours +1 per
#   entity write we emit). The u8 seq at +116 is a separate counter, also +1
#   per frame, gaps across bursts.
# +12 f32 x · +16 f32 z (ground 0.00707 in 167/173; rare elevated values)
# +20 f32 y · +24 f32 facing cos · +28 f32 0.0 (all frames, both variants)
#   · +32 f32 facing sin — every (+24, +32) pair is a unit vector
# 126-B variant: +36..+87 zero (no HP block); 122-B variant: +36 f32 current
#   HP, +40 f32 maxHP (turret tiers 5000/3000, minion 450 — measured
#   histogram), everything after shifted −4 vs the 126-B tail.
# +117 0x01 and +118 0x00 in the 126-B variant (173/173); the 122-B sample
#   template below carries the measured jungle-minion-class tail [Open].
# Old wire-leaf row "124/128 B; id@+8; HP@+36/40" = these two variants with
# the 2-byte opcode counted into the record length (122+2 / 126+2).
GROUND_Z = struct.unpack(">f", bytes.fromhex("3be7a8f8"))[0]   # 0.00707…
FACING_DEFAULT = (0.0, 1.0)      # corpus idle default (cos, sin)
HERO_1010_PERIOD = 5.0           # s between full updates of one entity
#   (corpus per-entity refresh ≈ 5–6 s for the busiest statics)
_TAIL_88 = b"\x01" * 8           # majority class pattern at +88..95
_TAIL_112 = b"\xff\xff\xff\xff"  # +112..115 (164/173; 9 effect-class frames differ)
_TAIL_119 = b"\x01\x01\x02"      # +119..121, constant for the default class
_HP_TAIL_96 = bytes.fromhex("030f030303030303")   # 122-B +96..103 [Open]
_HP_TAIL_119 = b"\x01\xff\x01"                    # 122-B +119..121 [Open]


def build_entity_full_update(eid: int, tick: int, x: float, y: float, seq: int,
                             facing: tuple[float, float] = FACING_DEFAULT,
                             hp: tuple[float, float] | None = None) -> bytes:
    """s2c 1010 — per-entity full state. Pure: the caller owns the shared
    world tick and the per-1010 seq byte. hp=None emits the 126-B no-HP
    variant; hp=(current, max) emits the 122-B HP variant (the shape minions
    use — hero entities never receive 1010 in the corpus)."""
    if type(seq) is not int or not 0 <= seq <= 255:
        raise ValueError("compact actor slot must fit one byte")
    cos, sin = facing
    if hp is None:
        body = bytearray(ENTITY_FULL_UPDATE_PAYLOAD_SIZE)
    else:
        if len(hp) != 2:
            raise ValueError("hp must be (current, max)")
        body = bytearray(ENTITY_FULL_UPDATE_HP_PAYLOAD_SIZE)
    struct.pack_into(">I", body, 0, eid)
    struct.pack_into(">I", body, 8, tick)
    struct.pack_into(">fff", body, 12, x, GROUND_Z, y)
    struct.pack_into(">fff", body, 24, cos, 0.0, sin)
    if hp is not None:
        struct.pack_into(">ff", body, 36, *hp)
        body[88:96] = _TAIL_88
        body[96:104] = _HP_TAIL_96
        body[112:116] = _TAIL_112
        body[116] = seq & 0xFF
        body[119:122] = _HP_TAIL_119
    else:
        body[88:96] = _TAIL_88
        body[112:116] = _TAIL_112
        body[116] = seq & 0xFF
        body[117] = 0x01
        body[119:122] = _TAIL_119
    return bytes(body)


def facing_toward(x: float, y: float, tx: float, ty: float) -> tuple[float, float]:
    """Unit (cos, sin) from (x, y) to (tx, ty); FACING_DEFAULT when stationary."""
    dx, dy = tx - x, ty - y
    dist = (dx * dx + dy * dy) ** 0.5
    if dist <= 0.0:
        return FACING_DEFAULT
    return (dx / dist, dy / dist)


# --------------------------------------------------------------------------
# Lane-minion wave spawn — vg5_final.pcap match 5 (match id
# 045f86d4-7ef2-4125-a835-e70a96288c88, recovered 2026-09-06 from the .vgr
# chunk filename), 0..655 s world window, 242 lane-minion 1010s measured.
# The prompt's 1087/1010-HP assumption is falsified by the corpus: lane
# minions are NEVER 1087-allocated (0/326 moving non-hero eids have a 1087)
# and their spawn 1010 is the 126-B no-HP variant under a dedicated id map
# (+0 spawner structure eid, +4 class id, +8 the new minion's eid). The
# spawn sequence per minion pair is: 1010 → 1016 → 1070(A) ×2 sides →
# 1070(B) ×2 → 1067(state 0) ×2 → +0.10 s 1067(state 0x0f) ×2.
# --------------------------------------------------------------------------
LANE_MINION_CLASS = 0xEB39CE55  # 1010 +4 for every lane-minion spawn (242/242)
LANE_SPAWNER_EIDS = (366, 366, 367, 365, 365)   # 1010 +0 per pair, wave-1
#   measured (vg5_final +22.97..26.85 s); the rotation rule is [Open], the
#   wave-1 sequence is pinned, later waves repeat it.
LANE_MINION_FIRST_EID = 4610    # corpus wave-1 first eid (even = right side)
MINION_WAVE_SIZE = 10           # 5 pairs × 2 sides
MINION_WAVES_MEASURED = 33      # pairs 22.97 → 47.96 → …: 25.0 s interval,
#   six wave starts pinned 22.974/47.96/72.99/98.06/123.14/148.22 — the
#   mechanics leaf's 60 s is wrong for this mode (solo-bots 3v3).
WAVE_INTERVAL = 25.0
WAVE_FIRST_SPAWN_AT = 22.974     # wave-1 first pair after the world anchor
WAVE_PAIR_OFFSETS = (0.00, 0.92, 1.94, 2.86, 3.88)   # s after wave start
#   (measured 22.974, 23.895, 24.916, 25.833, 26.854)
WAVE_STATE_DELAY = 0.10         # 1067 state 00 → 0x0f, measured +0.104 s
MINION_SPEED = 4.5              # u/s (dominant measured 4.49–4.50)
MINION_POSITION_PERIOD = 1.33   # s between 1070s idle; walking adds
#   waypoint-arrival sends (measured heartbeat 1.32–1.35 s)

# Spawn 1070 points, f32-exact from corpus (right side; left = negated x):
#   A = the lane-side point, B = the 0.46 u behind-waypoint the minion
#   shuffles to first; the spawn 1010 carries B.
LANE_POINT_A = (struct.unpack(">f", bytes.fromhex("428daeb6"))[0],
                struct.unpack(">f", bytes.fromhex("414c9ca6"))[0])   # 70.841, 12.788
LANE_POINT_B = (struct.unpack(">f", bytes.fromhex("428e8f5c"))[0],
                struct.unpack(">f", bytes.fromhex("414ee148"))[0])   # 71.280, 12.930

# Lane polylines measured from wave-1 survivors eid 4610 (right) / 4611
# (left), from B to each one's meeting-point rest position. Simplification
# [documented in next-steps §15]: every pair walks its side's full line;
# corpus pairs 2–5 stop earlier (±9.5..10.5 x).
LANE_PATH_RIGHT = (
    (65.620, 11.101), (58.982, 7.905), (51.362, 6.400), (49.125, 5.957),
    (43.677, 5.256), (35.913, 4.749), (28.086, 4.913), (26.255, 5.057),
    (20.278, 5.528), (12.435, 5.521), (7.877, 5.006), (7.422, 5.033),
    (5.125, 5.169), (3.764, 5.249), (2.849, 5.297), (1.481, 5.380),
    (1.500, 5.500),
)
LANE_PATH_LEFT = (
    (-65.620, 11.101), (-59.129, 7.707), (-51.477, 6.377), (-49.218, 6.063),
    (-43.775, 5.307), (-36.014, 4.764), (-28.186, 4.915), (-26.355, 5.057),
    (-20.378, 5.522), (-12.534, 5.520), (-7.977, 5.011), (-7.521, 5.041),
    (-4.327, 5.250), (-3.865, 5.280), (-3.405, 5.310), (-1.130, 5.398),
    (-0.675, 5.427), (-0.500, 5.500),
)
LANE_SPAWN_RIGHT = LANE_POINT_B          # 1010 spawn position per side
LANE_SPAWN_LEFT = (-LANE_POINT_B[0], LANE_POINT_B[1])

ENTITY_STATE_PAYLOAD_SIZE = 14   # s2c 1067: [u32 eid][u8 side][01][state][7B 0]
ENTITY_STATE_SIDE_LEFT = 0x01
ENTITY_STATE_SIDE_RIGHT = 0x02
ENTITY_STATE_SPAWNED = 0x00
ENTITY_STATE_MOVING = 0x0F

MOVE_INTENT_PAYLOAD_SIZE = 14    # s2c 1016: [u8][f32 target-x][f32 target-y][5B 0]
#   the u8 was 33/34 for wave-1 pairs (equals the 1010 seq byte of the same
#   minion; hero samples show 00/05 = player slot instead) — semantics
#   [Open]; we reuse the seq byte of the minion's spawn 1010.


def build_entity_state(eid: int, side: int, state: int) -> bytes:
    """s2c 1067 ENTITY_STATE — minion spawn/update shape (14 B)."""
    if side not in (ENTITY_STATE_SIDE_LEFT, ENTITY_STATE_SIDE_RIGHT):
        raise ValueError("1067 side must be 0x01 (left) or 0x02 (right)")
    return struct.pack(">IBBB", eid, side, 0x01, state) + bytes(7)


def build_move_intent(seq: int, x: float, y: float) -> bytes:
    """s2c 1016 — the movement target the entity walks toward (14 B)."""
    if type(seq) is not int or not 0 <= seq <= 255:
        raise ValueError("compact actor slot must fit one byte")
    return struct.pack(">Bff", seq, x, y) + bytes(5)


# -- combat events (T3 slice 3; measured on vg5, measure_combat*.py) --------

COMBAT_DELTA_PAYLOAD_SIZE = 20  # s2c 1054: [u32 src][u32 tgt][f32 delta][8B tail]
#   corpus: damage is negative (minion-vs-minion melee first blood -19.4 at
#   distance 2.00; spread -6.3..-99.3 incl. hero/other-class sources
#   [Open: per-class damage]); the 8-B tail was `00 05 04 00 00 00 00 00`
#   in 400/400 sampled minion-target frames — pinned here.
COMBAT_DELTA_TAIL = bytes.fromhex("0005040000000000")
MINION_ATTACK_DAMAGE = 19.4     # melee first-blood hit (4610 -> 4611)
MINION_ATTACK_COOLDOWN = 0.6    # s between repeat hits of one (src, tgt)
MINION_ATTACK_RANGE = 2.0       # first blood happened at exactly 2.00
MINION_HP = 450.0               # lane-minion HP tier (mechanics leaf §17)

# Minion class profiles per pair (0..4) in a 5-pair wave:
#   (class_name, hp, damage, attack_range, attack_cooldown, stop_offset)
# Measured on vg5 corpus:
#   - Pair 0: Lead Melee (spawner 366, first blood 19.4, range 2.0, offset 0.0)
#   - Pair 1: Melee (spawner 366, damage 27.8 / -28 peak, range 2.0, offset 1.0)
#   - Pair 2: Captain (spawner 367, damage 38.8 / 46.0, range 5.0, offset 4.0)
#   - Pair 3: Ranged (spawner 365, damage 50.0 / -50 peak, range 6.0, offset 5.0)
#   - Pair 4: Ranged (spawner 365, damage 50.0 / -50 peak, range 6.0, offset 8.0)
MINION_PAIR_CLASSES = (
    ("lead_melee", 450.0, 19.4, 2.0, 0.6, 0.0),
    ("melee",      450.0, 27.8, 2.0, 0.6, 1.0),
    ("captain",    650.0, 38.8, 5.0, 0.8, 4.0),
    ("ranged",     350.0, 50.0, 6.0, 0.6, 5.0),
    ("ranged",     350.0, 50.0, 6.0, 0.6, 8.0),
)


def trim_polyline(path: tuple[tuple[float, float], ...] | list[tuple[float, float]],
                  offset: float) -> list[tuple[float, float]]:
    """Trim a polyline backwards from its end by `offset` units, returning the trimmed points."""
    if offset <= 0.0 or len(path) <= 1:
        return list(path)
    lens = []
    tot = 0.0
    for i in range(len(path) - 1):
        d = math.hypot(path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
        lens.append(d)
        tot += d
    if offset >= tot:
        return [path[0]]
    rem = offset
    idx = len(path) - 1
    new_path = list(path)
    while idx > 0:
        seg_len = lens[idx - 1]
        if rem < seg_len:
            t = (seg_len - rem) / seg_len
            x = path[idx - 1][0] + t * (path[idx][0] - path[idx - 1][0])
            y = path[idx - 1][1] + t * (path[idx][1] - path[idx - 1][1])
            new_path = new_path[:idx] + [(x, y)]
            break
        else:
            rem -= seg_len
            new_path.pop()
            idx -= 1
    return new_path

DESTROY_PAYLOAD_SIZE = 6        # s2c 1073 / 1035: [u32 eid][u16 0]
#   minion death chain measured: 1073 destroy then 1035 despawn, same
#   timestamp, tail 0000, NO overkill 1054 and no 1068/1037/1072 frames
#   (that longer chain belongs to structure 3563). Server HP is internal —
#   the client has no HP stream for minions (no 1053/1011/1162/122-B-1010
#   ever carries a minion eid) and computes its own HP from the 1054 stream.


# -- hero combat (T3 slice 5; measured on vg5, measure_hero_combat.py) ------

COMBAT_DELTA_HERO_TAIL = bytes.fromhex("0005000000000000")  # tag 5 weapon basic attack
HERO_BASE_HP = 740.0             # base HP for level 1 (Amael)
HERO_BASE_ATTACK_DAMAGE = 70.0   # base weapon attack damage
HERO_ATTACK_RANGE = 2.5          # melee basic attack range (u)
HERO_ATTACK_COOLDOWN = 0.8       # attack cadence (s)
HERO_RESPAWN_DURATION = 6.0      # level 1-2 respawn timer (s)

HERO_STAT_PAYLOAD_SIZE = 14      # s2c 1053: [u32 eid][f32 val][u8 type][5B tail]
STAT_HEALTH = 0
STAT_ENERGY = 2
STAT_GOLD = 6
STAT_EXPERIENCE = 8
TARGET_ENTITY_PAYLOAD_SIZE = 6   # c2s 1060: [u32 target_eid][u16 0]


def build_combat_delta(src_eid: int, tgt_eid: int, delta: float,
                       tail: bytes = COMBAT_DELTA_TAIL) -> bytes:
    """s2c 1054: victim first, attacker second (mechanics matrix section 19.1)."""
    return struct.pack(">IIf", tgt_eid, src_eid, delta) + tail


def build_hero_stat(eid: int, value: float, stat_type: int = STAT_HEALTH,
                    tail: bytes | None = None) -> bytes:
    """1053 delta: health 0, energy 2, gold 6, experience 8.

    The no-source HP/energy/XP deltas set the measured second flag to 1;
    gold deltas leave it 0. Explicit tails preserve corpus variants.
    """
    if tail is None:
        tail = bytes([0, 1, 0, 0, 0]) if stat_type in (0, 2, 8) else bytes(5)
    return struct.pack(">IfB", eid, value, stat_type) + tail


def build_hero_death_state(eid: int) -> bytes:
    """s2c 1067 ENTITY_STATE on hero death (14 B) — measured: [eid][02 01][8B zeros]."""
    return struct.pack(">IBB", eid, 0x02, 0x01) + bytes(8)


def parse_target_entity(payload: bytes) -> int:
    """c2s 1060 — target acquisition intent (6 B)."""
    if len(payload) != TARGET_ENTITY_PAYLOAD_SIZE:
        raise ValueError("invalid 1060 target entity payload")
    return struct.unpack_from(">I", payload)[0]


def build_target_entity(target_eid: int) -> bytes:
    """c2s 1060 target acquisition intent (6 B): [u32 target_eid][u16 0]."""
    return struct.pack(">IH", target_eid, 0)


def build_destroy(eid: int) -> bytes:
    """s2c 1073 DESTROY."""
    return struct.pack(">IH", eid, 0)


def build_despawn(eid: int) -> bytes:
    """s2c 1035 DESPAWN."""
    return struct.pack(">IH", eid, 0)


def build_target_acquire(src_eid: int, tgt_eid: int, flag: int = 1) -> bytes:
    """s2c 1045 TARGET_ACQUIRE (14 B) — target/aggro lock/drop."""
    return struct.pack(">IIB", src_eid, tgt_eid, flag) + bytes(5)


def build_entity_substate(eid: int, b1: int, b2: int) -> bytes:
    """s2c 1068 ENTITY_SUBSTATE (12 B) — sub-state transition in death chains."""
    return struct.pack(">IBB", eid, b1, b2) + bytes(6)


def build_entity_clear(eid: int) -> bytes:
    """s2c 1072 ENTITY_CLEAR (6 B) — clear active state."""
    return struct.pack(">IH", eid, 0)


def build_minion_spawn_1010(spawner_eid: int, minion_eid: int, x: float, y: float,
                            seq: int, side: int) -> bytes:
    """s2c 1010, lane-minion spawn variant (126-B no-HP): the id map differs
    from the static full update — +0 = spawner structure eid (365..367),
    +4 = LANE_MINION_CLASS, +8 = the new minion's eid (corpus: 4610.. at
    wave 1; the eid space doubles as the global entity-write counter, which
    reconciles the "+8 = tick" reading of the static frames). Position is
    the B waypoint; facing (0, 1); z ground. Team-dependent tail bytes are
    measured per side: +96..98 and +119..121 (right 00 00 01 / 01 01 02,
    left 00 01 00 / 01 00 01)."""
    if type(seq) is not int or not 0 <= seq <= 255:
        raise ValueError("compact actor slot must fit one byte")
    body = bytearray(ENTITY_FULL_UPDATE_PAYLOAD_SIZE)
    struct.pack_into(">I", body, 0, spawner_eid)
    struct.pack_into(">I", body, 4, LANE_MINION_CLASS)
    struct.pack_into(">I", body, 8, minion_eid)
    struct.pack_into(">fff", body, 12, x, GROUND_Z, y)
    struct.pack_into(">fff", body, 24, 0.0, 0.0, 1.0)
    body[88:96] = _TAIL_88
    if side == ENTITY_STATE_SIDE_RIGHT:
        body[96:99] = b"\x00\x00\x01"
        body[119:122] = b"\x01\x01\x02"
    else:
        body[96:99] = b"\x00\x01\x00"
        body[119:122] = b"\x01\x00\x01"
    body[112:116] = _TAIL_112
    body[116] = seq & 0xFF
    body[117] = 0x01
    body[118] = 0x00
    return bytes(body)


# --------------------------------------------------------------------------
# 1162 timer tick — [u32 eid][u32 tag][f32 remaining][f32 duration][6B state]
# --------------------------------------------------------------------------

def build_timer_tick(eid: int, tag: int, remaining: float = 0.0,
                     duration: float = 0.0, state: bytes = bytes(6)) -> bytes:
    from .cooldown_wire import TimerTick
    return TimerTick(eid, tag, remaining, duration, state).encode()


# --------------------------------------------------------------------------
# Abilities & Casts — 1046 POSITION_EVENT, 1078 ABILITY_CAST, 1102 SKILLSHOT_CAST
# --------------------------------------------------------------------------

POSITION_EVENT_PAYLOAD_SIZE = 22  # s2c 1046: [u32 eid][f32 x][u32 z][f32 y][u8 kind][3B 0]
ABILITY_CAST_PAYLOAD_SIZE = 6    # c2s/s2c 1078: [u8 slot][5B 0]
SKILLSHOT_CAST_PAYLOAD_SIZE = 22 # c2s 1102: [u32 caster][u32 target][f32 x][f32 z][f32 y][u8 slot][u8 flag]


def build_position_event(eid: int, x: float, y: float, z: int = 0, kind: int = 0) -> bytes:
    """s2c 1046 POSITION_EVENT (22 B) — ability impact, projectile, or AoE marker."""
    return struct.pack(">IfIfB", eid, x, z, y, kind) + bytes(5)


def build_ability_cast(slot: int) -> bytes:
    """c2s/s2c 1078 ABILITY_CAST (6 B) — ability activation (0=A, 1=B, 2=Ult)."""
    return struct.pack(">B", slot & 0xFF) + bytes(5)


def parse_targetless_cast(payload: bytes) -> tuple[int | None, int, int]:
    """1041 targeted/self action, including the measured slot byte."""
    if len(payload) != 6:
        raise ValueError("invalid 1041 payload")
    target, slot, flags = struct.unpack(">IBB", payload)
    return (None if target == 0xffffffff else target), slot, flags


def parse_ground_cast(payload: bytes) -> tuple[float, float, int, int]:
    """1042 ground action; height is retained by the renderer, not the 2D sim."""
    if len(payload) != 14:
        raise ValueError("invalid 1042 payload")
    x, height, y, slot, flags = struct.unpack(">fffBB", payload)
    if not all(math.isfinite(value) for value in (x, height, y)):
        raise ValueError("nonfinite ground cast")
    return x, y, slot, flags


def build_item_inventory(eid: int, item_id: int, instance_id: int) -> bytes:
    """1085 equipment insertion (vgfull initial purchases, frame 2295)."""
    return struct.pack(">IIIH", eid, item_id, instance_id, 0)


def build_item_remove(eid: int, instance_id: int) -> bytes:
    """1099 consumed equipment instance (vg5_final, 148.929 s)."""
    return struct.pack(">II", eid, instance_id) + bytes.fromhex("000100000000")


def build_entity_attribute(eid: int, delta: float, attribute_id: int) -> bytes:
    """1052 equipment attribute delta; distinct from 1053 resource deltas."""
    return struct.pack(">IIfBB", eid, 0xffffffff, delta, attribute_id, 1) + bytes(6)


def parse_ability_cast(payload: bytes) -> int:
    """Parse c2s 1078 ability slot index (0..2)."""
    if len(payload) < 1:
        raise ValueError("invalid 1078 payload")
    return payload[0]


def parse_skillshot_cast(payload: bytes) -> tuple[int, int, float, float, int, int]:
    """Parse c2s 1102 skillshot/target cast: returns (caster, target, x, y, slot, flag)."""
    if len(payload) < 22:
        raise ValueError("invalid 1102 payload")
    caster, target, x, z, y, slot, flag = struct.unpack_from(">IIfffBB", payload, 0)
    return caster, target, x, y, slot, flag


# --------------------------------------------------------------------------
# Economy & Shop — purchase helpers; native item use lives in item_input.py
# --------------------------------------------------------------------------

SHOP_BUY_PAYLOAD_SIZE = 14       # c2s 1081: [u32 eid][u32 item_id][6B 0]
INVENTORY_SLOT_PAYLOAD_SIZE = 14 # s2c 1082: [u32 eid][u32 slot][6B 0]


def parse_shop_buy(payload: bytes) -> tuple[int, int]:
    """Parse c2s 1081 shop item purchase: returns (eid, item_id)."""
    if len(payload) < SHOP_BUY_PAYLOAD_SIZE:
        raise ValueError("invalid 1081 payload")
    eid, item_id = struct.unpack_from(">II", payload, 0)
    return eid, item_id


def build_shop_buy(eid: int, item_id: int) -> bytes:
    """c2s 1081 shop purchase payload (14 B): [u32 eid][u32 item_id][6B 0]."""
    return struct.pack(">II", eid, item_id) + bytes(6)


def build_inventory_slot(eid: int, slot: int) -> bytes:
    """s2c 1082 inventory slot update (14 B): [u32 eid][u32 slot][6B 0]."""
    return struct.pack(">II", eid, slot) + bytes(6)


def parse_inventory_slot(payload: bytes) -> tuple[int, int]:
    """Parse s2c 1082 inventory slot update: returns (eid, slot)."""
    if len(payload) < INVENTORY_SLOT_PAYLOAD_SIZE:
        raise ValueError("invalid 1082 payload")
    eid, slot = struct.unpack_from(">II", payload, 0)
    return eid, slot


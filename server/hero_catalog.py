"""Hero-catalog names + the 1107 payload builder (2026-09-06 corpus decode).

1107 HERO_CATALOG carries ``*<name>*`` strings — 275 at join, §15.8. The
names are game constants (same class as the kit tables); the payload shape
is a protocol structure. The former verbatim 1001/1108 hex fixtures now
live as field builders in server/roster.py (build_game_setup /
build_game_mode) — no captured payload bytes are stored in the repo.
"""

HERO_CATALOG_1107_NAMES = (
    'Adagio', 'Alpha', 'Ardan', 'Baptiste', 'Baron',
    'Blackfeather', 'Catherine', 'Celeste', 'Churnwalker', 'Flicker',
    'Fortress', 'Glaive', 'Grumpjaw', 'Gwen', 'Grace',
    'Joule', 'Koshka', 'Hero009', 'Kestrel', 'Lance',
    'Lorelai', 'Lyra', 'Malene', 'Ozo', 'Petal',
    'Phinn', 'Reim', 'Reza', 'Ringo', 'Hero016',
    'Samuel', 'SAW', 'Hero010', 'Skye', 'Sayoc',
    'Tony', 'Vox', 'Idris', 'Varya', 'Silvernail',
    'Anka', 'Kinetic', 'Magnus', 'Kensei', 'Ylva',
    'Shin', 'Karas', 'Amael', 'Viola', 'Ishtar',
    'Miho', 'Warhawk', 'Caine', 'Leo', 'Sanfeng',
    'Inara', 'Yates', 'Adagio_Skin_Goth_T1', 'Adagio_Skin_Goth_T2', 'Adagio_Skin_Goth_T3',
    'Adagio_Skin_Angel', 'Adagio_Skin_Egypt', 'Alpha_Skin_Horror_T1', 'Alpha_Skin_Horror_T2', 'Alpha_Skin_Horror_T3',
    'Alpha_Skin_Tinman', 'Ardan_Skin_Fallen_T1', 'Ardan_Skin_Nether', 'Ardan_Skin_Fallen_T2', 'Ardan_Skin_Fallen_T3',
    'Ardan_Skin_Cagefighter', 'Ardan_Skin_Glad', 'Viola_Skin_Encore', 'Baptiste_Skin_Scarecrow', 'Baptiste_Skin_Egypt',
    'Tony_Skin_SteamKnight', 'Tony_Skin_Santa', 'Baron_Skin_Terran_T1', 'Baron_Skin_Heli', 'Blackfeather_Skin_Dynasty_T1',
    'Blackfeather_Skin_Dynasty_T3', 'Blackfeather_Skin_Vamp', 'Blackfeather_Skin_Summer', 'Blackfeather_Skin_Taizen', 'Catherine_Skin_Vampire_T1',
    'Catherine_Skin_Vampire_T2', 'Catherine_Skin_Vampire_T3', 'Catherine_Skin_Glad', 'Catherine_Skin_Worlds', 'Catherine_Skin_Summer',
    'Catherine_Skin_Summer_Blue', 'Catherine_Skin_Summer_Orange', 'Catherine_Skin_Ice_RI', 'Catherine_Skin_Dragonmaster', 'Caine_Skin_Mercenary',
    'Celeste_Skin_Queen_T1', 'Celeste_Skin_Queen_T2', 'Celeste_Skin_Queen_T3', 'Celeste_Skin_Butterfly', 'Celeste_Skin_Snow',
    'Celeste_Skin_Hlwn_RI', 'Celeste_Skin_Moon', 'Celeste_Skin_School', 'Churnwalker_Skin_Clown', 'Inara_Skin_Lunar',
    'Magnus_Skin_Masquerade', 'Magnus_Skin_Water', 'Flicker_Skin_Panda', 'Flicker_Skin_Scientist', 'Flicker_Skin_Hlwn',
    'Flicker_Skin_Genie', 'Fortress_Skin_Hell_T1', 'Fortress_Skin_Hell_T2', 'Fortress_Skin_Hell_T3', 'Fortress_Skin_Warg',
    'Fortress_Skin_Summer', 'Fortress_Skin_Xmas_RI', 'Fortress_Skin_Kirin', 'Glaive_Skin_Prehistoric_T1', 'Glaive_Skin_Prehistoric_T2',
    'Glaive_Skin_Prehistoric_T3', 'Glaive_Skin_Lion', 'Glaive_Skin_Sorrowblade', 'Glaive_Skin_Rainbow', 'Gwen_Skin_Hitman',
    'Gwen_Skin_CNY', 'Gwen_Skin_Snow', 'Gwen_Skin_Summer', 'Gwen_Skin_Snow_Holiday', 'Gwen_Skin_Snow_Black',
    'Grace_Skin_Valkyrie', 'Grace_Skin_Wonderland', 'Grumpjaw_Skin_Bulldog', 'Grumpjaw_Skin_Churn', 'Anka_Skin_Winter',
    'Anka_Skin_Peacock', 'Idris_Skin_Ninja', 'Idris_Skin_Crimson', 'Idris_Skin_Hlwn', 'Idris_Skin_Egypt',
    'Idris_Skin_Wander', 'Joule_Skin_Killa_T1', 'Joule_Skin_Killa_T2', 'Joule_Skin_Killa_T3', 'Joule_Skin_Snow',
    'Joule_Skin_Valentines', 'Joule_Skin_Valentines_Panda', 'Kensei_Skin_Tokyo', 'Kensei_Skin_Oni', 'Kestrel_Skin_Sylvan_T1',
    'Kestrel_Skin_Drow', 'Kestrel_Skin_Ice', 'Kestrel_Skin_Kyudo', 'Kestrel_Skin_Summer', 'Kestrel_Skin_Forest',
    'Kinetic_Skin_Enforcer', 'Kinetic_Skin_Valkyrie', 'Koshka_Skin_Rave_T1', 'Koshka_Skin_Rave_T2', 'Koshka_Skin_Rave_T3',
    'Koshka_Skin_School', 'Koshka_Skin_CNY_RI', 'Koshka_Skin_CNY_Lotus', 'Koshka_Skin_Jewel', 'Krul_Skin_Rock_T1',
    'Krul_Skin_Rock_T2', 'Krul_Skin_Rock_T3', 'Krul_Skin_Pirate', 'Krul_Skin_Summer', 'Krul_Skin_Samurai',
    'Krul_Skin_Cyber', 'Krul_Skin_Cyber_Blue', 'Krul_Skin_Cyber_White', 'Lance_Skin_Glad', 'Lance_Skin_Poseidon',
    'Lance_Skin_Deathknight', 'Lance_Skin_Deathknight_T3', 'Lorelai_Skin_Devilray', 'Leo_Skin_Mercenary', 'Leo_Skin_Metal',
    'Lyra_Skin_Unicorn', 'Lyra_Skin_School', 'Lyra_Skin_Autumn_CHN', 'Lyra_Skin_Autumn_JPN', 'Lyra_Skin_Autumn_KOR',
    'Lyra_Skin_Water', 'Lyra_Skin_Occult', 'Malene_Skin_Candy', 'Ozo_Skin_Fire', 'Ozo_Skin_Winged',
    'Ozo_Skin_Kungfu_T1', 'Petal_Skin_Bug_T1', 'Petal_Skin_Bug_T2', 'Petal_Skin_Bug_T3', 'Petal_Skin_Hlwn_RI',
    'Petal_Skin_Wonderland', 'Phinn_Skin_Troll_T1', 'Phinn_Skin_Troll_T2', 'Phinn_Skin_Troll_T3', 'Phinn_Skin_Bakuto',
    'Phinn_Skin_Captain', 'Phinn_Skin_Earth', 'Reim_Skin_Thunder_T1', 'Reim_Skin_Thunder_T2', 'Reim_Skin_Thunder_T3',
    'Reim_Skin_IceMage', 'Reim_Skin_Santa', 'Reza_Skin_CNY', 'Reza_Skin_Nether', 'Ringo_Skin_Shogun_T1',
    'Ringo_Skin_Shogun_T2', 'Ringo_Skin_Shogun_T3', 'Ringo_Skin_Bakuto', 'Ringo_Skin_Cowboy', 'Ringo_Skin_Pirate',
    'Rona_Skin_Fury_T1', 'Rona_Skin_Fury_T2', 'Rona_Skin_Fury_T3', 'Rona_Skin_Red', 'Rona_Skin_Bunny_RI',
    'Samuel_Skin_Apprentice', 'Samuel_Skin_Cyber', 'Sanfeng_Skin_Yinyang', 'SAW_Skin_SAWborg_T1', 'SAW_Skin_SAWborg_T2',
    'SAW_Skin_SAWborg_T3', 'SAW_Skin_Elite', 'SAW_Skin_Summer', 'SAW_Skin_Tank', 'SAW_Skin_Medieval',
    'Silvernail_Skin_Woad', 'Silvernail_Skin_Medieval', 'Skaarf_Skin_Infinity_T1', 'Skaarf_Skin_Infinity_T2', 'Skaarf_Skin_Infinity_T3',
    'Skaarf_Skin_CNY_A', 'Skaarf_Skin_CNY_B', 'Skaarf_Skin_CNY_C', 'Skaarf_Skin_CNY_D', 'Skaarf_Skin_CNY',
    'Skaarf_Skin_Rainbow', 'Skaarf_Skin_Rainbow_Tabby', 'Skaarf_Skin_Rainbow_Orange', 'Skye_Skin_Eagle_T1', 'Skye_Skin_Eagle_T2',
    'Skye_Skin_Eagle_T3', 'Skye_Skin_Bike', 'Skye_Skin_Exoframe', 'Taka_Skin_Shin_T1', 'Taka_Skin_Shin_T2',
    'Taka_Skin_Shin_T3', 'Taka_Skin_School', 'Taka_Skin_Oni_RI', 'Taka_Skin_Oni_T1', 'Taka_Skin_CHN',
    'Varya_Skin_WinterWarrior', 'Varya_Skin_Olympus', 'Varya_Skin_Olympus_Red', 'Vox_Skin_Pirate_T1', 'Vox_Skin_Pirate_T2',
    'Vox_Skin_Pirate_T3', 'Vox_Skin_School', 'Vox_Skin_Ice', 'Vox_Skin_Nether', 'Yates_Skin_Crimson',
    'Ylva_Skin_Medieval', 'Warhawk_Skin_Demolition', 'Warhawk_Skin_CNY', 'Miho_Skin_Twilight', 'Miho_Skin_Killbill',
    'Ishtar_Skin_Orchid', 'Ishtar_Skin_Vday', 'Karas_Skin_Crow', 'Shin_Skin_Crimson', 'Amael_Skin_Gladiator',
)


CATALOG_1107_PAYLOAD_SIZE = 38   # *<name>* + zero pad


def catalog_payload(name: str) -> bytes:
    """One 1107 HERO_CATALOG payload: '*<name>*' NUL-padded to 38 B."""
    body = f"*{name}*".encode("ascii")
    if len(body) > CATALOG_1107_PAYLOAD_SIZE:
        raise ValueError(f"hero name {name!r} exceeds {CATALOG_1107_PAYLOAD_SIZE} B payload")
    return body + bytes(CATALOG_1107_PAYLOAD_SIZE - len(body))

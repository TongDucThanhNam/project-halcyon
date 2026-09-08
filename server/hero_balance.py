"""Recovered numeric hero stats, build 147219 (mechanics matrix sections 17-18).

Only gameplay constants are retained, in a server-authored schema. The source
balance_db.json remains outside the repo. Registry IDs are resolved from the manifest pointer array and corroborated
by six matching 1011 fields (HP, energy, speed, armor, shield, weapon); Adagio/Amael are also
confirmed by the mobile hero-picker capture. Unmeasured IDs are not aliased.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class HeroStats:
    health_base: float
    health_per_level: float
    energy_base: float
    energy_per_level: float
    energy_regen: float
    energy_regen_per_level: float
    weapon_base: float
    weapon_per_level: float
    armor_base: float
    armor_per_level: float
    shield_base: float
    shield_per_level: float
    attack_range: float
    move_speed: float
    attack_speed_per_level: float


# Legacy content names: Hero009=Krul, Hero010=Skaarf, Hero016=Rona,
# Sayoc=Taka. Keep the source names so identity joins remain reproducible.
STATS = {
    'Adagio': HeroStats(685.0, 147.55, 400.0, 35.0, 3.66, 0.23, 75.0, 3.9, 25.0, 4.546, 20.0, 3.182, 6.0, 3.8, 0.02),
    'Alpha': HeroStats(761.0, 161.46, 0.0, 0.0, 0.0, 0.0, 83.0, 3.8, 30.0, 5.0, 20.0, 3.637, 2.1, 4.0, 0.033),
    'Amael': HeroStats(830.0, 152.0, 275.0, 25.0, 2.43, 0.18, 86.0, 6.0, 30.0, 5.0, 20.0, 3.637, 1.6, 3.9, 0.02),
    'Anka': HeroStats(750.0, 141.0, 200.0, 45.0, 2.6, 0.2, 82.0, 6.4, 30.0, 5.0, 20.0, 3.637, 1.6, 4.0, 0.033),
    'Ardan': HeroStats(838.0, 163.64, 0.0, 0.0, 0.0, 0.0, 80.0, 5.5, 35.0, 5.91, 25.0, 4.546, 1.8, 3.9, 0.033),
    'Baptiste': HeroStats(739.0, 144.0, 273.0, 33.0, 3.17, 0.19, 78.0, 8.1, 30.0, 5.0, 20.0, 3.637, 2.8, 3.9, 0.033),
    'Baron': HeroStats(679.0, 125.0, 320.0, 45.0, 7.67, 1.03, 71.0, 5.4, 26.0, 4.728, 21.0, 3.273, 5.8, 3.6, 0.01),
    'Blackfeather': HeroStats(657.0, 157.28, 0.0, 0.0, 0.0, 0.0, 81.0, 7.2, 25.0, 4.546, 20.0, 3.182, 1.8, 3.9, 0.02),
    'Caine': HeroStats(750.0, 118.0, 0.0, 0.0, 0.0, 0.0, 82.0, 7.0, 25.0, 4.5, 20.0, 3.5, 6.4, 3.8, 0.02),
    'Catherine': HeroStats(808.0, 169.55, 200.0, 24.0, 2.33, 0.16, 74.0, 6.1, 35.0, 5.91, 25.0, 4.546, 1.5, 4.1, 0.033),
    'Celeste': HeroStats(649.0, 125.37, 380.0, 32.0, 3.53, 0.21, 0.0, 0.0, 25.0, 4.546, 20.0, 3.182, 5.3, 3.8, 0.0227),
    'Churnwalker': HeroStats(863.0, 171.46, 380.0, 32.0, 2.38, 0.21, 80.0, 7.8, 35.0, 5.91, 25.0, 4.546, 1.7, 3.7, 0.02),
    'Flicker': HeroStats(797.0, 168.28, 295.0, 42.0, 2.94, 0.25, 77.0, 7.1, 35.0, 5.91, 25.0, 4.546, 1.5, 3.9, 0.033),
    'Fortress': HeroStats(761.0, 165.46, 300.0, 15.0, 2.56, 0.15, 73.0, 7.6, 30.0, 5.0, 20.0, 3.637, 1.8, 3.9, 0.04),
    'FortressMinion': HeroStats(600.0, 200.0, 0.0, 0.0, 0.0, 0.0, 20.0, 0.0, 150.0, 0.0, 150.0, 0.0, 1.5, 6.5, 0.0),
    'Glaive': HeroStats(834.0, 151.73, 275.0, 15.0, 2.47, 0.13, 70.0, 7.9, 30.0, 5.0, 20.0, 3.637, 2.8, 3.9, 0.02),
    'Grace': HeroStats(740.0, 158.46, 268.0, 35.0, 2.92, 0.21, 73.0, 7.2, 35.0, 5.91, 25.0, 4.546, 2.7, 4.1, 0.033),
    'Grumpjaw': HeroStats(783.0, 164.46, 234.0, 21.0, 2.51, 0.14, 74.0, 7.7, 30.0, 5.0, 20.0, 3.637, 2.6, 3.9, 0.012),
    'Gwen': HeroStats(661.0, 128.28, 175.0, 20.0, 2.2, 0.15, 68.0, 5.9, 25.0, 4.546, 20.0, 3.182, 6.0, 3.6, 0.033),
    'Hero009': HeroStats(769.0, 160.64, 220.0, 26.0, 2.33, 0.16, 70.0, 7.0, 30.0, 5.0, 20.0, 3.637, 1.5, 4.0, 0.033),
    'Hero010': HeroStats(638.0, 134.0, 200.0, 24.0, 2.33, 0.16, 80.0, 6.8, 25.0, 4.546, 20.0, 3.182, 5.5, 3.8, 0.02),
    'Hero016': HeroStats(778.0, 162.28, 0.0, 0.0, 0.0, 0.0, 77.0, 7.2, 30.0, 5.0, 20.0, 3.637, 1.8, 4.0, 0.02),
    'Hero034': HeroStats(761.0, 67.0, 280.0, 33.0, 1.87, 0.22, 79.0, 7.8, 20.0, 6.0, 20.0, 6.0, 1.7, 3.25, 0.033),
    'Hero049': HeroStats(761.0, 67.0, 280.0, 33.0, 1.87, 0.22, 79.0, 7.8, 20.0, 6.0, 20.0, 6.0, 8.0, 3.25, 0.033),
    'Hero050': HeroStats(761.0, 67.0, 280.0, 33.0, 1.87, 0.22, 79.0, 7.8, 20.0, 6.0, 20.0, 6.0, 6.1, 3.2, 0.033),
    'Hero051': HeroStats(709.0, 128.0, 280.0, 33.0, 1.87, 0.22, 72.0, 6.0, 20.0, 2.73, 20.0, 2.73, 6.2, 3.25, 0.033),
    'Hero052': HeroStats(761.0, 67.0, 280.0, 33.0, 1.87, 0.22, 79.0, 7.8, 20.0, 6.0, 20.0, 6.0, 8.0, 3.25, 0.033),
    'Hero057': HeroStats(761.0, 67.0, 280.0, 33.0, 1.87, 0.22, 79.0, 7.8, 20.0, 6.0, 20.0, 6.0, 1.7, 3.25, 0.033),
    'HeroPLU': HeroStats(800.0, 170.0, 0.0, 0.0, 0.0, 0.0, 79.0, 7.8, 20.0, 3.636, 20.0, 3.636, 1.7, 2.7, 0.033),
    'Idris': HeroStats(697.0, 141.82, 0.0, 0.0, 0.0, 0.0, 77.0, 7.7, 30.0, 4.546, 20.0, 3.182, 2.4, 4.0, 0.033),
    'Inara': HeroStats(805.0, 137.0, 201.0, 17.0, 2.53, 0.14, 78.0, 6.6, 30.0, 5.0, 20.0, 2.728, 2.4, 4.0, 0.033),
    'Ishtar': HeroStats(666.0, 145.0, 186.0, 25.0, 3.51, 0.23, 0.0, 0.0, 25.0, 4.546, 20.0, 3.182, 6.2, 3.8, 0.033),
    'Joule': HeroStats(742.0, 158.64, 390.0, 15.0, 6.3, 0.32, 66.0, 7.5, 35.0, 5.91, 25.0, 4.546, 2.4, 3.9, 0.012),
    'Karas': HeroStats(724.0, 118.0, 320.0, 25.0, 2.69, 0.3, 0.0, 0.0, 25.0, 4.546, 20.0, 3.182, 6.4, 3.8, 0.033),
    'Kensei': HeroStats(761.0, 157.5, 280.0, 33.0, 1.87, 0.22, 78.0, 5.637, 30.0, 5.0, 20.0, 3.637, 3.5, 4.0, 0.033),
    'Kestrel': HeroStats(728.0, 129.0, 404.0, 8.0, 4.0, 0.4, 70.0, 6.0, 25.0, 4.546, 20.0, 3.182, 6.2, 3.6, 0.033),
    'Kinetic': HeroStats(721.0, 118.0, 169.0, 20.0, 3.51, 0.23, 64.0, 3.0, 25.0, 4.546, 20.0, 3.182, 6.0, 3.8, 0.033),
    'Koshka': HeroStats(711.0, 150.55, 280.0, 33.0, 2.87, 0.22, 79.0, 7.8, 30.0, 5.0, 20.0, 3.637, 1.7, 3.9, 0.008),
    'Kraken_RaidBoss': HeroStats(600.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1000.0, 0.0, 200.0, 0.0, 200.0, 0.0, 2.5, 2.3, 0.0),
    'Lance': HeroStats(842.0, 160.64, 0.0, 0.0, 0.0, 0.0, 85.0, 8.5, 35.0, 5.91, 25.0, 4.546, 4.5, 3.9, 0.02),
    'Leo': HeroStats(830.0, 160.67, 328.0, 28.28, 2.43, 0.18, 95.0, 9.0, 30.0, 5.0, 20.0, 3.637, 3.8, 3.9, 0.02),
    'Lorelai': HeroStats(691.0, 141.92, 360.0, 30.0, 3.47, 0.23, 0.0, 0.0, 25.0, 4.546, 20.0, 3.182, 6.2, 3.8, 0.02),
    'Lyra': HeroStats(774.0, 134.46, 248.0, 60.0, 3.15, 0.45, 0.0, 0.0, 25.0, 4.546, 20.0, 3.182, 5.6, 3.7, 0.033),
    'Maaya': HeroStats(721.0, 118.0, 169.0, 20.0, 3.51, 0.23, 64.0, 3.0, 20.0, 2.73, 20.0, 2.73, 6.4, 3.4, 0.033),
    'Magnus': HeroStats(648.0, 128.88, 380.0, 32.0, 3.53, 0.21, 80.0, 7.1, 25.0, 4.546, 20.0, 3.182, 6.0, 3.8, 0.0227),
    'Malene': HeroStats(696.0, 132.0, 300.0, 35.0, 3.2, 0.2, 0.0, 0.0, 25.0, 4.546, 20.0, 3.182, 5.8, 3.8, 0.02),
    'Miho': HeroStats(775.0, 119.0, 0.0, 0.0, 0.0, 0.0, 75.0, 7.0, 25.0, 4.546, 20.0, 3.182, 3.0, 4.0, 0.033),
    'Ozo': HeroStats(769.0, 160.64, 350.0, 27.28, 3.3, 0.37, 80.0, 7.0, 30.0, 5.0, 20.0, 3.637, 1.7, 4.0, 0.033),
    'Petal': HeroStats(636.0, 122.46, 410.0, 28.0, 4.21, 0.19, 64.0, 6.4, 25.0, 4.546, 20.0, 3.182, 6.2, 3.8, 0.033),
    'Phinn': HeroStats(892.0, 171.73, 270.0, 25.0, 2.47, 0.13, 95.0, 5.4, 35.0, 5.91, 25.0, 4.546, 1.9, 3.5, 0.012),
    'Reim': HeroStats(746.0, 159.37, 220.0, 22.0, 2.97, 0.26, 80.0, 6.7, 30.0, 5.0, 20.0, 3.637, 1.9, 3.9, 0.033),
    'Reza': HeroStats(718.0, 144.37, 380.0, 32.0, 3.53, 0.21, 84.0, 6.4, 30.0, 5.0, 20.0, 3.637, 3.0, 3.9, 0.0227),
    'Ringo': HeroStats(703.0, 127.64, 163.0, 23.0, 2.2, 0.15, 74.0, 6.0, 25.0, 4.546, 20.0, 3.182, 6.2, 3.6, 0.033),
    'SAW': HeroStats(683.0, 121.82, 150.0, 15.0, 2.0, 0.11, 50.0, 5.0, 25.0, 4.546, 20.0, 3.182, 6.6, 3.5, 0.01),
    'Samuel': HeroStats(652.0, 126.19, 290.0, 30.0, 3.95, 0.45, 78.0, 6.4, 25.0, 4.546, 20.0, 3.182, 6.3, 3.8, 0.027),
    'Sanfeng': HeroStats(821.0, 123.23, 0.0, 0.0, 0.0, 0.0, 86.0, 7.2, 30.0, 5.0, 20.0, 3.637, 1.8, 3.9, 0.033),
    'Sayoc': HeroStats(717.0, 144.1, 180.0, 22.0, 2.33, 0.16, 70.0, 5.37, 30.0, 5.0, 20.0, 3.637, 2.0, 4.0, 0.033),
    'Shin': HeroStats(746.0, 150.37, 320.0, 22.0, 3.97, 0.26, 80.0, 6.7, 25.0, 4.56, 20.0, 3.637, 3.2, 3.9, 0.033),
    'Silvernail': HeroStats(745.0, 130.0, 203.0, 37.0, 2.36, 0.26, 74.0, 4.182, 25.0, 4.546, 20.0, 3.182, 6.2, 3.8, 0.033),
    'Skye': HeroStats(708.0, 126.55, 380.0, 32.0, 3.53, 0.21, 72.0, 3.63, 25.0, 4.546, 20.0, 3.182, 6.1, 3.7, 0.033),
    'Tony': HeroStats(762.0, 162.0, 280.0, 33.0, 1.87, 0.22, 83.0, 8.1, 30.0, 5.0, 20.0, 3.637, 1.7, 3.9, 0.033),
    'Varya': HeroStats(642.0, 135.0, 950.0, 50.0, 36.0, 2.6, 0.0, 0.0, 25.0, 4.546, 20.0, 3.182, 6.0, 3.7, 0.0136),
    'Viola': HeroStats(721.0, 118.0, 290.0, 35.0, 2.8, 0.3, 0.0, 0.0, 20.0, 2.73, 20.0, 2.73, 6.4, 3.8, 0.033),
    'Vox': HeroStats(667.0, 126.1, 200.0, 24.0, 2.33, 0.16, 54.0, 5.0, 25.0, 4.546, 20.0, 3.182, 5.8, 3.8, 0.033),
    'Warhawk': HeroStats(721.0, 118.0, 230.0, 20.0, 3.51, 0.23, 85.0, 6.0, 25.0, 2.73, 25.0, 2.73, 5.5, 3.8, 0.033),
    'Yates': HeroStats(857.0, 165.0, 174.0, 27.0, 2.14, 0.18, 82.0, 8.2, 35.0, 5.91, 25.0, 4.546, 3.4, 3.7, 0.033),
    'Ylva': HeroStats(703.0, 127.64, 203.0, 37.0, 2.36, 0.26, 70.0, 5.0, 25.0, 4.546, 20.0, 3.182, 5.5, 3.9, 0.033),
}

# Registry IDs derived from KindredManifest PTCH array slots (slot - 4) / 4.
HERO_NAMES = {242: 'Catherine', 243: 'Ringo', 244: 'Adagio', 245: 'Koshka', 246: 'Petal', 249: 'Glaive', 250: 'SAW', 253: 'Joule', 254: 'Hero009', 255: 'Hero010', 256: 'Sayoc', 257: 'Ardan', 258: 'Vox', 259: 'Fortress', 260: 'Hero016', 261: 'Baron', 265: 'Skye', 266: 'Reim', 267: 'Kestrel', 268: 'Alpha', 269: 'Lyra', 273: 'Idris', 274: 'Ozo', 275: 'Lance', 276: 'Samuel', 279: 'Phinn', 280: 'Blackfeather', 281: 'Malene', 284: 'FortressMinion', 285: 'Celeste', 393: 'Flicker', 395: 'Gwen', 396: 'Grumpjaw', 397: 'Tony', 399: 'Baptiste', 403: 'Reza', 406: 'Grace', 408: 'Churnwalker', 409: 'Lorelai', 412: 'Kensei', 413: 'Varya', 418: 'Magnus', 420: 'Kinetic', 421: 'Hero049', 423: 'Hero050', 424: 'Hero051', 425: 'Hero052', 429: 'Anka', 432: 'Silvernail', 435: 'Hero057', 436: 'Ylva', 439: 'Yates', 440: 'Inara', 445: 'Hero034', 446: 'Sanfeng', 447: 'HeroPLU', 913: 'Leo', 915: 'Caine', 916: 'Warhawk', 919: 'Miho', 922: 'Ishtar', 924: 'Viola', 925: 'Amael', 926: 'Karas', 927: 'Shin', 929: 'Maaya'}


def configure_hero(hero, hero_id, name=None):
    """Install level-one stats once, before equipment or match time advances."""
    name = name or HERO_NAMES.get(hero_id)
    stats = STATS.get(name)
    hero.hero_id = hero_id
    hero.hero_name = name
    if stats is None:
        return False
    hero.hp = hero.max_hp = hero.base_max_hp = stats.health_base
    hero.hp_per_level = stats.health_per_level
    hero.energy = hero.max_energy = hero.base_max_energy = stats.energy_base
    hero.energy_per_level = stats.energy_per_level
    hero.energy_regen = hero.base_energy_regen = stats.energy_regen
    hero.energy_regen_per_level = stats.energy_regen_per_level
    hero.attack_damage = hero.base_attack_damage = stats.weapon_base
    hero.weapon_per_level = stats.weapon_per_level
    hero.armor = hero.base_armor = stats.armor_base
    hero.armor_per_level = stats.armor_per_level
    hero.shield = hero.base_shield = stats.shield_base
    hero.shield_per_level = stats.shield_per_level
    hero.attack_range = stats.attack_range
    hero.base_speed = stats.move_speed
    hero.attack_speed_per_level = stats.attack_speed_per_level * 100
    # Ranged/melee exceptions must be explicit (e.g. Leo's long melee reach).
    hero.is_ranged = stats.attack_range > 3.0 and name not in ("Leo", "Lance", "Kensei")
    hero.projectile_speed = 22.0  # acceptance brief approximate speed; per-hero calibration open
    return True

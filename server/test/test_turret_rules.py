from types import SimpleNamespace
import unittest

from server.hero_movement import HeroMovement
from server.structures import Structure, StructureManager
from server import wire


class TestTurretRules(unittest.TestCase):
    def setUp(self):
        self.manager = StructureManager([Structure(1, "test", 2, 0, 0, 2500, 2500, tier=1)])
        self.turret = self.manager.structures[1]
        self.attacker = HeroMovement(eid=1500, team=1, x=2, y=0, hp=5000, max_hp=5000)
        self.ally = HeroMovement(eid=1517, team=2, x=3, y=0)
        self.minion = SimpleNamespace(eid=10, side=1, alive=True, x=1, y=0, hp=1000)

    def test_defender_aggro_overrides_minion_during_cooldown(self):
        self.manager.step(1, {1500: self.attacker}, [self.minion])
        self.assertEqual(self.turret.current_target_eid, 10)
        frames = self.manager.on_hero_damaged(self.attacker, self.ally)
        self.assertEqual(self.turret.current_target_eid, 1500)
        self.assertEqual(frames[0][0], wire.OP.TARGET_ACQUIRE)
        self.assertEqual(self.turret.last_attack_at, 1)

    def test_heat_ramps_and_caps(self):
        hits = []
        for now in range(1, 6):
            before = self.attacker.hp
            self.manager.step(now, {1500: self.attacker})
            hits.append(before - self.attacker.hp)
        for actual, expected in zip(hits, [160, 259.2, 352.512, 423.0144, 423.0144]):
            self.assertAlmostEqual(actual, expected)

    def test_new_target_resets_heat(self):
        self.manager.step(1, {1500: self.attacker})
        self.manager.step(2, {1500: self.attacker})
        replacement = HeroMovement(eid=1516, team=1, x=2, y=0)
        self.attacker.x = 100
        before = replacement.hp
        self.manager.step(3, {1500: self.attacker, 1516: replacement})
        self.assertEqual(before - replacement.hp, 160)

    def test_backdoor_reduces_hero_damage_without_enemy_minions(self):
        self.manager.apply_damage(1, 100, 1500, source_is_hero=True)
        self.assertEqual(self.turret.hp, 2475)

    def test_nearby_enemy_minion_removes_backdoor(self):
        self.manager.apply_damage(1, 100, 1500, source_is_hero=True, minions=[self.minion])
        self.assertEqual(self.turret.hp, 2400)

    def test_dead_friendly_and_distant_minions_do_not_disable_backdoor(self):
        for minion in [SimpleNamespace(alive=False, side=1, x=0, y=0),
                       SimpleNamespace(alive=True, side=2, x=0, y=0),
                       SimpleNamespace(alive=True, side=1, x=11, y=0)]:
            self.manager.apply_damage(1, 100, 1500, source_is_hero=True, minions=[minion])
        self.assertEqual(self.turret.hp, 2425)

    def test_structure_damage_uses_callback_once(self):
        calls = []
        def damage(source, target, raw, kind, now):
            calls.append((source.eid, target.eid, raw, kind, now))
            return []
        self.manager.step(1, {1500: self.attacker}, damage_callback=damage)
        self.assertEqual(calls, [(1, 1500, 160, "weapon", 1)])

    def test_crystal_requires_entire_defensive_chain(self):
        manager = StructureManager()
        for eid in (3539, 3540, 3541, 3542):
            manager.structures[eid].is_alive = False
        self.assertFalse(manager.is_vulnerable(3544))
        manager.structures[3543].is_alive = False
        self.assertTrue(manager.is_vulnerable(3544))
        manager.apply_damage(3544, 10000, 1500)
        self.assertTrue(manager.match_finished)
        self.assertEqual(manager.winner_team, 1)
        self.assertEqual(manager.apply_damage(3545, 100), [])

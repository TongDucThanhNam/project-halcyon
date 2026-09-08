"""Unit tests for authoritative structure and turret simulation (server/structures.py).

Verifies:
  - 12 static structures initialized (10 turrets + 2 Vain crystals).
  - Turret progression gates (Outer -> Middle -> Base -> Vain Turrets -> Crystal).
  - Damage application and measured death chain (1068/1067/1054 overkill/1072/1073/1035).
  - Turret acquisition (action 1), shot (0), self release/idle (2/3), and damage.
  - Vain crystal destruction triggers win condition and ends match.
  - Distinct native 126-byte creation and 122-byte HP snapshot forms.
"""
import struct
import unittest

from server import roster, wire
from server.hero_movement import HeroMovement
from server.structures import Structure, StructureManager
from server.test.test_native_actor_spawn import original_native_catalog


class TestStructures(unittest.TestCase):
    def setUp(self):
        self.mgr = StructureManager()

    def test_all_structures_initialized(self):
        self.assertEqual(len(self.mgr.structures), 12)
        # Check specific key structures
        self.assertIn(3545, self.mgr.structures)  # Team 1 Outer
        self.assertIn(3550, self.mgr.structures)  # Team 1 Vain Crystal
        self.assertIn(3539, self.mgr.structures)  # Team 2 Outer
        self.assertIn(3544, self.mgr.structures)  # Team 2 Vain Crystal

        # Check HP tiers
        self.assertEqual(self.mgr.structures[3539].max_hp, 2500.0)
        self.assertEqual(self.mgr.structures[3540].max_hp, 3000.0)
        self.assertEqual(self.mgr.structures[3541].max_hp, 3500.0)
        # Native archetype372 snapshots consistently identify 3000 maximum HP.
        self.assertEqual(self.mgr.structures[3542].max_hp, 3000.0)
        self.assertEqual(self.mgr.structures[3544].max_hp, 10000.0)

    def test_progression_gates(self):
        # Tier 1 (Outer) is vulnerable from start
        self.assertTrue(self.mgr.is_vulnerable(3539))
        # Tier 2 (Middle) is invulnerable while Outer is alive
        self.assertFalse(self.mgr.is_vulnerable(3540))
        # Tier 3 (Base) is invulnerable
        self.assertFalse(self.mgr.is_vulnerable(3541))
        # Tier 5 (Crystal) is invulnerable
        self.assertFalse(self.mgr.is_vulnerable(3544))

        # Destroy Outer (3539)
        self.mgr.structures[3539].is_alive = False
        self.assertTrue(self.mgr.is_vulnerable(3540))
        self.assertFalse(self.mgr.is_vulnerable(3541))

        # Destroy Middle (3540)
        self.mgr.structures[3540].is_alive = False
        self.assertTrue(self.mgr.is_vulnerable(3541))
        self.assertFalse(self.mgr.is_vulnerable(3542))

        # Destroy Base (3541)
        self.mgr.structures[3541].is_alive = False
        self.assertTrue(self.mgr.is_vulnerable(3542))
        self.assertTrue(self.mgr.is_vulnerable(3543))
        self.assertFalse(self.mgr.is_vulnerable(3544))

        # Destroy one Vain Turret (3542)
        self.mgr.structures[3542].is_alive = False
        self.assertFalse(self.mgr.is_vulnerable(3544))
        self.mgr.structures[3543].is_alive = False
        self.assertTrue(self.mgr.is_vulnerable(3544))

    def test_damage_and_measured_death_chain(self):
        # Apply 500 damage to Outer turret (2500 -> 2000)
        frames = self.mgr.apply_damage(3539, 500.0, src_eid=1500)
        self.assertEqual(len(frames), 1)
        op, payload = frames[0]
        self.assertEqual(op, wire.OP.COMBAT_DELTA)
        tgt, src, delta = struct.unpack_from(">IIf", payload, 0)
        self.assertEqual(src, 1500)
        self.assertEqual(tgt, 3539)
        self.assertEqual(delta, -500.0)
        self.assertEqual(self.mgr.structures[3539].hp, 2000.0)
        self.assertTrue(self.mgr.structures[3539].is_alive)

        # Fatal damage: 2000 damage kills it
        death_frames = self.mgr.apply_damage(3539, 2000.0, src_eid=1500)
        self.assertFalse(self.mgr.structures[3539].is_alive)
        self.assertEqual(self.mgr.structures[3539].hp, 0.0)

        # Natural match-six deaths retain the actor and attribute the killer.
        ops = [op for op, _ in death_frames]
        expected_ops = [
            wire.OP.COMBAT_DELTA,
            wire.OP.ENTITY_DEATH,
        ]
        self.assertEqual(ops, expected_ops)
        self.assertEqual(death_frames[-1][1], struct.pack(">II6x", 3539, 1500))

    def test_turret_aggro_acquisition_and_attack(self):
        # Place Team 1 hero near Team 2 Outer turret (3539 at x=17.06, y=1.93)
        hero = HeroMovement(1500, team=1, x=15.0, y=1.93)
        heroes = {1500: hero}

        # Step at t=1.0 -> turret acquires hero (dist ~2.06u <= 8.5u) and fires
        frames = self.mgr.step(now=1.0, heroes=heroes)
        ops = [op for op, _ in frames]
        self.assertIn(wire.OP.TARGET_ACQUIRE, ops)
        self.assertIn(wire.OP.COMBAT_DELTA, ops)

        # Check target acquire frame
        acq_payload = [p for op, p in frames if op == wire.OP.TARGET_ACQUIRE][0]
        src, tgt, flag = struct.unpack_from(">IIB", acq_payload, 0)
        self.assertEqual(src, 3539)
        self.assertEqual(tgt, 1500)
        self.assertEqual(flag, 1)

        # Check combat delta frame
        atk_payload = [p for op, p in frames if op == wire.OP.COMBAT_DELTA][0]
        a_tgt, a_src, a_delta = struct.unpack_from(">IIf", atk_payload, 0)
        self.assertEqual(a_src, 3539)
        self.assertEqual(a_tgt, 1500)
        self.assertEqual(a_delta, -160.0)
        self.assertEqual(hero.hp, hero.max_hp - 160.0)

        # Hero runs away out of range (dist > 8.5u)
        hero.x = 0.0
        drop_frames = self.mgr.step(now=2.0, heroes=heroes)
        drop_ops = [op for op, _ in drop_frames]
        self.assertIn(wire.OP.TARGET_ACQUIRE, drop_ops)
        drop_payload = [p for op, p in drop_frames if op == wire.OP.TARGET_ACQUIRE][0]
        d_src, d_tgt, d_flag = struct.unpack_from(">IIB", drop_payload, 0)
        self.assertEqual(d_src, 3539)
        self.assertEqual(d_tgt, 3539)
        self.assertEqual(d_flag, 2)
        self.assertEqual([struct.unpack_from(">IIB", p) for op, p in drop_frames
                          if op == wire.OP.TARGET_ACQUIRE], [(3539, 3539, 2), (3539, 3539, 3)])
        self.assertIsNone(self.mgr.structures[3539].current_target_eid)

    def test_vain_crystal_win_condition(self):
        # Unlock Red Vain Crystal (3544) by destroying prior structures
        self.mgr.structures[3539].is_alive = False
        self.mgr.structures[3540].is_alive = False
        self.mgr.structures[3541].is_alive = False
        self.mgr.structures[3542].is_alive = False
        self.mgr.structures[3543].is_alive = False

        self.assertFalse(self.mgr.match_finished)
        self.assertIsNone(self.mgr.winner_team)

        # Destroy Red Vain Crystal (3544)
        frames = self.mgr.apply_damage(3544, 10000.0, src_eid=1500)
        self.assertTrue(self.mgr.match_finished)
        self.assertEqual(self.mgr.winner_team, 1)  # Blue team (Team 1) wins!
        self.assertFalse(self.mgr.structures[3544].is_alive)

        # Crystal destruction starts its animation, then keeps the actor dead.
        ops = [op for op, _ in frames]
        self.assertEqual(ops, [wire.OP.COMBAT_DELTA, wire.OP.CRYSTAL_DESTROYED, wire.OP.ENTITY_DEATH])
        self.assertEqual(frames[1][1], bytes(6))
        self.assertEqual(frames[2][1], struct.pack(">II6x", 3544, 1500))

    def test_spawn_1010_frames(self):
        frames = self.mgr.get_spawn_1010_frames(tick_base=3539, catalog=original_native_catalog())
        self.assertEqual(len(frames), 12)
        for op, payload in frames:
            self.assertEqual(op, wire.OP.ENTITY_FULL_UPDATE)
            self.assertEqual(len(payload), 126)
            archetype, entity_class, eid = struct.unpack_from(">III", payload)
            self.assertIn(eid, self.mgr.structures)
            self.assertEqual(archetype, self.mgr.archetype(self.mgr.structures[eid]))
            self.assertEqual(entity_class, 0xC10B41DA)
        for op, payload in self.mgr.get_state_1010_frames():
            self.assertEqual(len(payload), 122)
            hp, max_hp = struct.unpack_from(">ff", payload, 36)
            self.assertEqual(hp, max_hp)


if __name__ == "__main__":
    unittest.main()

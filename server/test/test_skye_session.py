"""Skye native upgrade/cast input through the actual 50 ms match session."""
import struct
import unittest

from server import abilities, buff_wire, jungle, match_server, roster
from server.navigation import NavMesh
from server.status_effects import StatusType


class TestSkyeSession(unittest.TestCase):
    def setUp(self):
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                       [(0, 1, 2), (0, 2, 3)])
        players = roster.default_solo_bots('skye-test', 'skye-test')
        players = [players[0], players[3]]
        players[0].hero_id, players[1].hero_id = 265, 243
        for player in players:
            player.is_bot = False
        self.frames = []
        self.owner = object()
        self.world = match_server.SnapshotStream(self.owner, players, 'skye-test',
            lambda op, payload: self.frames.append((op, payload)), log=lambda _: None,
            navigation_mesh=mesh)
        self.world._finalize()
        self.hero, self.enemy = self.world.hero_sims.values()
        self.hero.teleport(0, 35)
        self.enemy.teleport(4, 35)
        self.hero.energy = self.hero.max_energy = 1000
        self.enemy.hp = self.enemy.max_hp = 10000
        self.world.jungle = jungle.JungleManager(open_time=1000000)
        for structure in self.world.structures.structures.values():
            structure.is_alive = False
        self.world.phase = self.world.WORLD
        self.kit = self.world.hero_kits[1500]
        self.frames.clear()

    def ticks(self, count):
        for _ in range(count):
            self.world.advance_simulation()

    def test_experimental_perk_control_is_persistent_and_not_recreated_every_tick(self):
        self.world.native_skye_control=True
        self.ticks(3)
        rows=[p for op,p in self.frames if op==1087 and struct.unpack_from('>H',p,14)[0]==600]
        self.assertEqual(len(rows),1)
        self.assertEqual(struct.unpack_from('>II',rows[0]),(1500,1500))
        self.assertEqual(struct.unpack_from('>e',rows[0],8)[0],-1)
        self.assertEqual(struct.unpack_from('>H4I',rows[0],16),(1,0,0,0,0))
        self.world.status_manager.clear_target(1500,now=self.world.sim_time)
        self.hero.is_alive=False
        self.frames.clear();self.ticks(1)
        self.assertFalse(any(op==1087 and struct.unpack_from('>H',p,14)[0]==600 for op,p in self.frames))
        self.hero.is_alive=True
        self.ticks(1)
        self.assertIn((1500,'skye_perk_control'),self.world.status_manager.presentation.active)

    def test_temporary_skye_speed_publication_preserves_equipment_and_expires(self):
        self.world.publish_skye_speed=True
        self.kit.locked_target=self.enemy
        self.kit.lock_expires_at=1.0
        self.kit._strafe_until=.3
        self.hero.item_move_speed=.3
        self.hero.set_target(10,35)
        self.ticks(2)
        speed=lambda:[struct.unpack_from('>f',p,8)[0] for op,p in self.frames
                      if op==1052 and p[:4]==struct.pack('>I',1500) and p[12]==18]
        self.assertEqual(speed(),[2.0])
        self.hero.set_target(-10,35)
        self.ticks(1)
        self.assertAlmostEqual(speed()[-1],-1.8,places=6)
        reconnect=[]
        self.world._reconnect_hero_state(self.world.players[0],lambda op,p:reconnect.append((op,p)))
        restored=[struct.unpack_from('>f',p,8)[0] for op,p in reconnect
                  if op==1052 and p[:4]==struct.pack('>I',1500) and p[12]==18]
        self.assertEqual(restored,[.5])
        self.ticks(4)
        self.assertEqual(len(speed()),3)
        self.assertAlmostEqual(speed()[-1],-.2,places=6)
        self.assertEqual(self.hero.item_move_speed,.3)
        self.assertAlmostEqual(self.hero.effective_speed(self.world.sim_time),4.0)

    def learn(self, slot):
        self.world._apply_event(1078, bytes((slot,)) + bytes(5), self.owner)

    def cast(self, native_action, point=(10, 35)):
        self.world._apply_event(1042, struct.pack('>fffBB', point[0], 0, point[1], native_action, 0))

    def establish_lock(self):
        self.world._apply_event(1060, roster.build_target_entity(1517))
        for _ in range(20):
            self.ticks(1)
            if self.kit.locked_target is self.enemy:
                break
        self.assertIs(self.kit.locked_target, self.enemy)
        self.world._apply_event(1012, roster.build_move(0, 35))
        self.hero.stop()
        self.frames.clear()

    def test_ui_upgrade_zero_one_two_echoes_and_native_rank_ack_zero_two_four(self):
        progression = self.world.economy.get_or_create(1500)
        progression.add_xp(500)
        progression.apply_to_hero(self.hero)
        for slot in (0, 1, 2):
            self.learn(slot)
        self.assertIsInstance(self.kit, abilities.SkyeKit)
        self.assertEqual(self.kit.ranks, {0: 1, 1: 1, 2: 1})
        self.assertEqual([p for op, p in self.frames if op == 1078],
                         [bytes((slot,)) + bytes(5) for slot in (0, 1, 2)])
        self.assertEqual([struct.unpack_from('>II', p) for op, p in self.frames if op == 1082],
                         [(1500, 0), (1500, 2), (1500, 4)])
        self.assertEqual(progression.ability_points, 3)

    def test_real_basic_projectile_impact_creates_lock_after_hit_and_not_at_windup(self):
        self.world._apply_event(1060, roster.build_target_entity(1517))
        self.ticks(1)
        self.assertIsNone(self.kit.locked_target)
        self.assertTrue(any(op == 1045 for op, _ in self.frames))
        self.assertFalse(any(op == 1086 and buff_wire.parse_buff_add(p).kind == 602
                             for op, p in self.frames))
        for _ in range(20):
            self.ticks(1)
            if self.kit.locked_target is self.enemy:
                break
        self.assertIs(self.kit.locked_target, self.enemy)
        hit = next(i for i, (op, p) in enumerate(self.frames) if op == 1054)
        lock = next(i for i, (op, p) in enumerate(self.frames)
                    if op == 1086 and buff_wire.parse_buff_add(p).kind == 602)
        self.assertLess(hit, lock)
        self.assertEqual(self.hero.revealed_targets[1517], self.world.sim_time + 3)

    def test_native_a_moves_without_basic_attacks_and_action_one_cancels_for_free(self):
        self.learn(0)
        self.cast(0)
        cost_energy, cooldown = self.hero.energy, self.kit.cooldowns[0]
        self.world._apply_event(1012, roster.build_move(0, 38))
        self.ticks(4)
        self.assertGreater(self.hero.y, 35)
        self.assertTrue(self.hero.basic_attack_disabled)
        self.assertEqual(self.hero.facing, (1, 0))
        self.assertFalse(any(op == 1037 for op, _ in self.frames))
        before = self.hero.energy
        self.world._apply_event(1041, struct.pack('>IBB', 0xffffffff, 1, 0))
        self.assertEqual(self.hero.energy, before)
        self.assertEqual(self.kit.cooldowns[0], cooldown)
        self.assertFalse(self.hero.basic_attack_disabled)
        self.assertEqual([p[8] for op, p in self.frames if op == 1045], [1])
        self.assertAlmostEqual(cost_energy, 960)

    def test_basic_target_resumes_after_barrage_without_a_second_selection_input(self):
        self.learn(0)
        self.world._apply_event(1060, roster.build_target_entity(1517))
        self.ticks(8)
        self.cast(0)
        self.assertIsNone(self.hero.target_eid)  # No automatic pursuit during mobile A.
        self.ticks(61)
        self.assertEqual(self.hero.target_eid, 1517)
        self.frames.clear()
        self.ticks(30)
        hits = [p for op, p in self.frames if op == 1054 and
                struct.unpack_from('>II', p) == (1517, 1500) and p[12:] == roster.COMBAT_DELTA_HERO_TAIL]
        self.assertTrue(hits, 'native selection is retained; no second1060 is required to resume basics')

    def test_new_ground_order_during_barrage_supersedes_the_suspended_attack_target(self):
        self.learn(0)
        self.world._apply_event(1060, roster.build_target_entity(1517))
        self.ticks(2)
        self.cast(0)
        self.world._apply_event(1012, roster.build_move(-10, 35))
        self.ticks(61)
        self.assertIsNone(self.hero.target_eid)
        self.assertLess(self.hero.x, 0)

    def test_barrage_target_restoration_respects_retarget_recall_stop_and_death(self):
        for cause in ('retarget', 'recall', 'stop', 'death'):
            with self.subTest(cause=cause):
                self.setUp()
                self.learn(0)
                self.hero.set_target_eid(1517)
                self.cast(0)
                if cause == 'retarget':
                    self.hero.set_target_eid(9001)
                elif cause == 'recall':
                    self.hero.start_recall(.1)
                elif cause == 'stop':
                    self.hero.stop()
                else:
                    self.hero.is_alive = False
                self.kit.cancel_native_action(1, .2)
                self.assertEqual(self.hero.target_eid, 9001 if cause == 'retarget' else None)

    def test_b_native_action_two_requires_lock_then_dash_and_missiles_resolve(self):
        self.learn(1)
        self.cast(2, (4, 35))
        self.assertFalse(any(op == 1046 for op, _ in self.frames))
        self.establish_lock()
        before = self.enemy.hp
        self.cast(2, (4, 35))
        self.assertTrue(self.hero.basic_attack_disabled)
        self.assertEqual([p[16] for op, p in self.frames if op == 1046], [2])
        self.ticks(4)
        self.assertAlmostEqual(self.hero.x, 3.6)
        self.assertEqual(self.enemy.hp, before)
        self.ticks(16)
        self.assertAlmostEqual(self.hero.x, 4)
        self.assertFalse(self.hero.basic_attack_disabled)
        self.assertLess(self.enemy.hp, before)
        self.assertEqual(sum(op == 1054 for op, _ in self.frames), 4)

    def test_suri_restores_retained_selection_and_resumes_basics_without_second_1060(self):
        self.learn(1)
        self.establish_lock()
        self.world._apply_event(1060,roster.build_target_entity(1517))
        self.cast(2,(2,35))
        self.assertIsNotNone(self.kit._suri)
        self.assertIsNone(self.hero.target_eid)
        self.ticks(12)
        self.assertEqual(self.hero.target_eid,1517)
        self.frames.clear()
        self.ticks(35)
        self.assertTrue(any(op==1054 and struct.unpack_from('>II',p)==(1517,1500)
                            and p[12:]==roster.COMBAT_DELTA_HERO_TAIL for op,p in self.frames))

    def test_suri_target_restoration_does_not_overwrite_superseding_intent_or_death(self):
        for cause in ('retarget','recall','stop','ground','death'):
            with self.subTest(cause=cause):
                self.setUp();self.learn(1);self.establish_lock()
                self.world._apply_event(1060,roster.build_target_entity(1517))
                self.cast(2,(2,35))
                if cause=='retarget':self.hero.set_target_eid(9001)
                elif cause=='recall':self.hero.start_recall(self.world.sim_time)
                elif cause=='stop':self.hero.stop()
                elif cause=='ground':self.hero.set_target(-5,35)
                else:self.hero.is_alive=False
                self.kit.interrupt_channel(self.world.sim_time+.05)
                self.assertEqual(self.hero.target_eid,9001 if cause=='retarget' else None)

    def test_c_native_action_four_pays_energy_and_waits_for_delayed_damage(self):
        progression = self.world.economy.get_or_create(1500)
        progression.add_xp(500)
        progression.apply_to_hero(self.hero)
        self.learn(2)
        self.establish_lock()
        before, energy = self.enemy.hp, self.hero.energy
        self.cast(4, (4, 35))
        self.assertEqual(energy - self.hero.energy, 70)
        self.assertEqual([p[16] for op, p in self.frames if op == 1046], [4])
        self.ticks(25)
        self.assertEqual(self.enemy.hp, before)
        self.ticks(1)
        self.assertLess(self.enemy.hp, before)
        self.assertTrue(self.world.status_manager.has_effect(1517, StatusType.STUN, self.world.sim_time))

    def test_c_field_activation_is_published_before_its_first_damage(self):
        """Owned native C episodes publish 613/615 before owner damage pulses."""
        progression = self.world.economy.get_or_create(1500)
        progression.add_xp(500)
        progression.apply_to_hero(self.hero)
        self.learn(2)
        self.establish_lock()
        self.cast(4, (4, 35))
        volley_eid = next(iter(self.world.skye_volleys.active))
        self.ticks(26)
        created = next(i for i, (op, p) in enumerate(self.frames)
                       if op == 1010 and len(p) == 126
                       and struct.unpack_from('>I', p, 8)[0] == volley_eid)
        activation = next(i for i, (op, p) in enumerate(self.frames)
                          if op == 1086 and buff_wire.parse_buff_add(p).target_eid == volley_eid
                          and buff_wire.parse_buff_add(p).kind == 613)
        damage = next(i for i, (op, p) in enumerate(self.frames)
                      if op == 1054 and struct.unpack_from('>II', p) == (1517, 1500))
        self.assertLess(created, activation)
        self.assertLess(activation, damage)
        self.assertEqual(sum(op == 1086 and buff_wire.parse_buff_add(p).target_eid == volley_eid
                             and buff_wire.parse_buff_add(p).kind == 613 for op, p in self.frames), 1)

    def test_live_target_provider_routes_barrage_through_structure_damage_rules(self):
        turret = next(s for s in self.world.structures.structures.values() if s.team == 2 and not s.is_crystal)
        turret.is_alive = True
        turret.x, turret.y = 3, 35
        turret.hp = 10000
        turret.armor = turret.shield = 0
        self.learn(0)
        self.cast(0)
        self.ticks(2)
        raw = (140 + 1.8 * self.hero.crystal_power + 1.2 * self.hero.attack_damage) * .1
        self.assertAlmostEqual(turret.hp, 10000 - raw * .5 * .25)
        self.assertEqual(self.enemy.hp, 10000)
        hits = [struct.unpack_from('>II', p) for op, p in self.frames if op == 1054]
        self.assertEqual(hits, [(turret.eid, 1500)])


if __name__ == '__main__':
    unittest.main()

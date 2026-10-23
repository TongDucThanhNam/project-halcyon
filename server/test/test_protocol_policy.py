import unittest

from Tools.protocol_observer import Actor
from Tools.protocol_policy import Policy, MixedRendezvous, mixed_structure_zones


def mixed_mesh():
    from server.navigation import NavMesh
    return NavMesh([(-100, -40), (100, -40), (100, 40), (-100, 40)], [(0, 1, 2), (0, 2, 3)])


def scene():
    return {1500:Actor(1500,'hero',1,0,hero_id=244,position=(0,2),spawn=(-70,30),hp=500,max_hp=500),
            3539:Actor(3539,'structure',2,7,position=(17,2),tier=1),
            3540:Actor(3540,'structure',2,8,position=(35,2),tier=2)}


class TestPolicy(unittest.TestCase):
    def test_per_team_stage_points_have_margin_mesh_and_own_structure_direction(self):
        import math
        from dataclasses import replace
        from server.structures import STRUCTURE_TEMPLATES
        from Tools.protocol_policy import MIXED_CLEAN_RADIUS
        for structures in (STRUCTURE_TEMPLATES,
                           [replace(s, team=3-s.team) for s in STRUCTURE_TEMPLATES]):
            r = MixedRendezvous(mixed_mesh(), structures=structures)
            self.assertNotEqual(r.stage_point(1), r.stage_point(2))
            for team in (1, 2):
                point = r.stage_point(team)
                own = next(s for s in structures if s.team == team and s.tier == 1)
                self.assertGreater((point[0]-r.point[0])*(own.x-r.point[0]), 0)
                self.assertTrue(r.mesh.contains(point))
                self.assertLessEqual(math.dist(point, r.point), MIXED_CLEAN_RADIUS-1)
                self.assertEqual(r.evidence()['stages'][team]['point'], point)
                self.assertEqual(len(r.evidence()['stages'][team]['structures']), len(structures))
        from unittest.mock import Mock
        mesh = Mock(contains=lambda p: p[0] == 0)
        with self.assertRaisesRegex(ValueError, 'stage point off-mesh'):
            MixedRendezvous(mesh)

    def test_mixed_structure_geometry_uses_production_range_plus_two_and_segments(self):
        self.assertEqual(mixed_structure_zones((17.06+10.5, 1.93), teams=(2,))[0]['eid'], 3539)
        self.assertFalse(mixed_structure_zones((17.06, -20), teams=(2,)))
        self.assertTrue(mixed_structure_zones((17.06, 20), teams=(2,), start=(17.06, -20)))
        self.assertFalse(mixed_structure_zones((0, -2)))
        self.assertIn(3544, [z['eid'] for z in mixed_structure_zones((76.12, 19.9))])
        with self.assertRaisesRegex(ValueError, 'finite'):
            mixed_structure_zones((float('nan'), 0))

    def test_mixed_opponent_engages_only_when_both_inside_clean_disk(self):
        import struct
        a = scene()
        a[1500].position = (-2, -2)
        a[1517] = Actor(1517, 'hero', 2, 3, position=(2, -2), spawn=(78, 1), hp=700, max_hp=700)
        p = Policy(1517, 'Baptiste', opponent_eid=1500, mixed_pair=(1500, 1517),
                   rendezvous=MixedRendezvous(mixed_mesh()))
        self.assertEqual(p.step(a, 1).opcode, 1060)
        for pos, who in (((17.06, 1.93), 1517), ((-17.06, 1.93), 1500), ((-6, -2), 1500)):
            a[1500].position, a[1517].position = (-2, -2), (2, -2)
            a[who].position = pos
            p.last_order, p.next_action = None, 0
            with self.subTest(who=who):
                intent = p.step(a, 3)
                self.assertEqual(intent.opcode, 1012)
                self.assertEqual(struct.unpack_from('>ff', intent.payload), (1.5, -2))
                self.assertEqual(p.engagement['phase'], 'staging')
        a[1500].position, a[1517].position = (-2, -2), (2, -2)
        self.assertEqual(p.step(a, 5).opcode, 1060)

    def test_mixed_low_health_does_not_leave_rendezvous_for_a_turret_or_recall(self):
        import struct
        a = scene()
        a[1517] = Actor(1517, 'hero', 2, 3, position=(5, 2), spawn=(78, 1), hp=20, max_hp=700)
        p = Policy(1517, 'Baptiste', opponent_eid=1500, mixed_pair=(1500, 1517),
                   rendezvous=MixedRendezvous(mixed_mesh()))
        intent = p.step(a, 1)
        self.assertEqual(intent.opcode, 1012)
        goal = struct.unpack_from('>ff', intent.payload)
        self.assertEqual(goal, (1.5, -2))
        self.assertFalse(mixed_structure_zones(goal))
        self.assertNotEqual(goal, a[1517].spawn)

    def test_rendezvous_derived_from_structures_refuses_offmesh_and_inzone_candidates(self):
        from dataclasses import replace
        from server.structures import STRUCTURE_TEMPLATES
        mesh = mixed_mesh()
        r = MixedRendezvous(mesh)
        self.assertEqual(r.point, (0, -2))
        self.assertGreater(min(s['clearance'] for s in r.clearances), 7)
        self.assertTrue(mesh.contains(r.point))
        with self.assertRaisesRegex(ValueError, 'off-mesh'):
            MixedRendezvous(mesh, candidate=(0, -41))
        for point in ((17.06, 1.93), (0, 1.93)):
            with self.subTest(point=point), self.assertRaisesRegex(ValueError, 'expanded structure zone'):
                MixedRendezvous(mesh, candidate=point)
        # Synthetic structure translation must translate R; this is not a
        # hard-coded point accepted irrespective of production templates.
        shifted = [replace(s, x=s.x+1) for s in STRUCTURE_TEMPLATES]
        self.assertEqual(MixedRendezvous(mesh, structures=shifted).point, (1, -2))

    def test_staging_never_pursues_far_ce_or_targets_ce_side_turrets(self):
        import struct
        r = MixedRendezvous(mixed_mesh())
        for ce in ((-78.18, .88), (-54, 2.92), (-6, -2), (80, 30)):
            a = scene()
            a[1500].position = ce
            a[1517] = Actor(1517, 'hero', 2, 3, position=(79.66, -.91), hp=700, max_hp=700)
            p = Policy(1517, 'Baptiste', opponent_eid=1500, mixed_pair=(1500, 1517), rendezvous=r)
            goal = struct.unpack_from('>ff', p.step(a, 0).payload)
            self.assertEqual(goal, r.stage_point(2))
            previous = a[1517].position
            for step in r.route(previous, 2):
                self.assertFalse(mixed_structure_zones(step, teams=(1,), start=previous))
                previous = step

    def test_enemy_crossing_nav_step_refused_even_with_safe_final_target(self):
        from unittest.mock import Mock
        mesh = Mock(contains=lambda p: True)
        mesh.find_path.return_value = [(-17.06, 1.93), (1.5, -2)]
        with self.assertRaisesRegex(ValueError, 'enemy structure zone'):
            MixedRendezvous(mesh).route((79.66, -.91), 2)

    def test_leaving_clean_zone_cancels_attack_before_pacing_deadline(self):
        a = scene()
        a[1500].position = (-2, -2)
        a[1517] = Actor(1517, 'hero', 2, 3, position=(2, -2), hp=700, max_hp=700)
        p = Policy(1517, 'Baptiste', opponent_eid=1500, mixed_pair=(1500, 1517),
                   rendezvous=MixedRendezvous(mixed_mesh()))
        self.assertEqual(p.step(a, 0).opcode, 1060)
        a[1500].position = (-3.01, -2)
        self.assertEqual(p.step(a, .1).opcode, 1012)
        self.assertIsNone(p.target)
        self.assertEqual(p.engagement['phase'], 'staging')

    def test_4q_initial_positions_reach_r_on_synthetic_route_without_enemy_zone_targets(self):
        from Tools.classic_client import path_step
        r = MixedRendezvous(mixed_mesh())
        # b4bc3c08: CE spawn and opponent spawn before the failed pursuit.
        for team, initial in ((1, (-78.18, .88)), (2, (79.66, -.91))):
            position, steps = initial, 0
            while position != r.stage_point(team):
                r.route(position, team)
                target = path_step(r.mesh, position, r.stage_point(team))
                self.assertFalse(mixed_structure_zones(target, teams=(3-team,), start=position))
                position = target
                steps += 1
                self.assertLess(steps, 30)
            self.assertTrue(r.contains(position))

    def test_mixed_other_participants_keep_lane_orders_without_attacking_pair(self):
        import struct
        a = scene()
        a[1517] = Actor(1517, 'hero', 2, 3, position=(5, 2))
        a[1515] = Actor(1515, 'hero', 1, 1, position=(-30, 2), spawn=(-78, 1), hp=700, max_hp=700)
        a[3545] = Actor(3545, 'structure', 1, 6, position=(-17.06, 1.93), tier=1)
        a[4000] = Actor(4000, 'minion', 2, 9, position=(-25, 2))
        p = Policy(1515, 'Catherine', mixed_pair=(1500, 1517))
        attack = p.step(a, 1)
        self.assertEqual(attack.opcode, 1060)
        self.assertEqual(struct.unpack_from('>I', attack.payload)[0], 4000)
        a[1517].position = (-25, 2)
        p.next_action = 0
        intent = p.step(a, 3)
        self.assertEqual(intent.opcode, 1012, 'cancel approach rather than interfere with the pair')
        self.assertEqual(struct.unpack_from('>ff', intent.payload), (-78, 1))
        self.assertIn('non-interference', p.hold['reason'])

    def test_declared_opponent_uses_observed_team_and_eid_not_index_or_nearest(self):
        import struct
        a = scene()
        a[1517] = Actor(1517, 'hero', 2, 3, position=(5, 2))
        a[1519] = Actor(1519, 'hero', 2, 5, position=(1, 2))
        p = Policy(1500, 'Skye', opponent_eid=1517)
        intent = p.step(a, 1)
        self.assertEqual(intent.opcode, 1060)
        self.assertEqual(struct.unpack_from('>I', intent.payload)[0], 1517)
        self.assertIsNone(p.step(a, 3), 'retain a legal target rather than reset windup')
        a[1517].alive = False
        self.assertEqual(p.step(a, 5).opcode, 1012, 'dead opponent cancels the previous order')
        a[1517].team = 1
        with self.assertRaisesRegex(ValueError, 'opposing hero'):
            p.step(a, 7)

    def test_soak_never_orders_structure_attacks_or_cross_river_pursuit(self):
        import struct
        for team, home in ((1,-1),(2,1)):
            with self.subTest(team=team):
                a = scene()
                me = a[1500]
                me.team, me.position, me.spawn = team, (home*5,2), (home*70,30)
                a[3539].team, a[3540].team = 3-team, team
                a[3539].position, a[3540].position = (-home*17,2), (home*17,2)
                policy = Policy(1500,'Skye',defend_farm=True)
                intent = policy.step(a,1)
                self.assertEqual(intent.opcode,1012)
                self.assertEqual(struct.unpack_from('>ff',intent.payload),(home*13.,2.))
                a[4000] = Actor(4000,'minion',3-team,9,position=(0,2))
                self.assertEqual(policy.step(a,3).opcode,1060)
                self.assertEqual(policy.target,4000)
                a[4000].position = (-home*6,2)
                intent = policy.step(a,5)
                self.assertEqual(intent.opcode,1012,'must cancel the persistent target beyond river fence')
                me.position = (-home*5,2)
                policy.last_order = None
                self.assertIn('stop cross-river',policy.step(a,7).reason)

    def test_soak_farmer_targets_own_side_neutrals_and_restocks_legally(self):
        a = scene()
        a[3540].team, a[3540].position = 1, (-17,2)
        me = a[1500]
        me.position = (-40,20)
        a[4000] = Actor(4000,'neutral',0,9,position=(-40.9,20.3),archetype=357)
        policy = Policy(1500,'Adagio',defend_farm=True)
        self.assertEqual(policy.step(a,1).opcode,1060)
        self.assertEqual(policy.target,4000)
        self.assertEqual(policy.step(a,121).reason,'retreat toward base')
        me.position = me.spawn
        me.gold = 600
        self.assertEqual(policy.step(a,123).opcode,1081)

    def test_unknown_structure_hp_is_targetable_and_lowest_tier_only(self):
        a = scene()
        a[1500].position = (5,2)
        p = Policy(1500,'Skye')
        intent = p.step(a,1)
        self.assertEqual(intent.opcode,1060)
        self.assertEqual(p.target,3539)
        self.assertIsNone(p.step(a,2))
        a[3539].alive = False
        self.assertEqual(p.step(a,3).opcode,1012)

    def test_minions_first_and_target_retention(self):
        a = scene()
        a[4000] = Actor(4000,'minion',2,9,position=(3,2))
        p = Policy(1500,'Skye')
        self.assertEqual(p.step(a,1).opcode,1060)
        self.assertEqual(p.target,4000)
        self.assertIsNone(p.step(a,30))
        a[4000].alive = False
        self.assertEqual(p.step(a,31).opcode,1012)

    def test_dead_waits_for_alive_and_low_health_recalls(self):
        a = scene()
        p = Policy(1500,'Skye')
        a[1500].alive = False
        self.assertIsNone(p.step(a,1))
        a[1500].alive = True
        a[1500].hp = 20
        self.assertEqual(p.step(a,2).reason,'safe recall')
        self.assertIsNone(p.step(a,3))

    def test_learn_gates_and_no_unpaced_spam(self):
        a = scene()
        a[1500].points = 1
        p = Policy(1500,'Skye')
        self.assertEqual(p.step(a,1).opcode,1078)
        self.assertIsNone(p.step(a,1.1))

    def test_shop_only_at_observed_base_with_gold(self):
        a = scene()
        me = a[1500]
        me.gold = 600
        p = Policy(1500,'Skye')
        self.assertNotEqual(p.step(a,1).opcode,1081)
        me.position = me.spawn
        self.assertEqual(p.step(a,3).opcode,1081)
        me.gold = None
        self.assertIsNone(p.step(a,7), 'unknown gold cannot authorize a buy; prior move remains active')


class TestFinishNegativeControls(unittest.TestCase):
    def test_soak_waits_full_live_interval_and_never_claims_a_result(self):
        from unittest.mock import patch
        from Tools import protocol_participants as pp
        output = pp.new_output()
        players = [pp.Participant('127.0.0.1',1,pp.MATCH_ID,h,output,heartbeat_port=0) for h in pp.HEROES]
        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
            def is_alive(self):
                return False
            def join(self, timeout):
                pass
        try:
            for p in players:
                p.eid = 1500
                p.neutral_deaths = 1
                p.observer.minion_spawns = p.observer.deaths = p.observer.revivals = 1
                p.observer.own_purchases = p.observer.own_learns = 1
            with patch.object(pp.time,'monotonic',side_effect=[0,0,71,1799,1800]), \
                    patch.object(pp.time,'sleep') as sleep, \
                    patch.object(pp.threading,'Thread',ImmediateThread), \
                    patch.object(pp,'reconnect') as reconnect:
                result = pp.full_match(players,output,soak=True)
            reconnect.assert_called_once_with(players[4])
            self.assertEqual(sleep.call_count,3,'must not end before the full measured interval')
            self.assertEqual(result['stability_duration_s'],1800)
            self.assertIn('not a match result',result['claim'])
            self.assertNotIn('winner',result)
        finally:
            for p in players:
                p.close()

    def test_soak_rejects_early_match_result(self):
        from Tools import protocol_participants as pp
        output = pp.new_output()
        players = [pp.Participant('127.0.0.1',1,pp.MATCH_ID,h,output,heartbeat_port=0) for h in pp.HEROES]
        try:
            players[0].observer.result = {'winner':1,'reason':0}
            with self.assertRaisesRegex(pp.StageFailure,'soak ended naturally'):
                pp.full_match(players,output,soak=True)
        finally:
            for p in players:
                p.close()

    def test_soak_requires_owned_journal_telemetry_and_excludes_full_match(self):
        from Tools.protocol_participants import main
        for args in (['--soak'], ['--soak','--full-match','--self-host','--journal','--telemetry']):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code,2)

    def test_timeout_cannot_pass_without_all_results(self):
        from Tools import protocol_participants as pp
        output = pp.new_output()
        players = [pp.Participant('127.0.0.1',1,pp.MATCH_ID,h,output,heartbeat_port=0) for h in pp.HEROES]
        try:
            for p in players:
                p.eid = 1500
            with self.assertRaisesRegex(pp.StageFailure,'timeout'):
                pp.full_match(players,output,timeout=0)
        finally:
            for p in players:
                p.close()

    def test_five_results_are_not_six(self):
        from Tools.protocol_observer import Observer
        from server.test.test_protocol_observer import actor
        from server import lifecycle_wire
        import struct
        observers = [Observer() for _ in range(6)]
        for o in observers[:5]:
            o.consume(1010,actor(archetype=293))
            o.consume(1106,bytes(6))
            o.consume(1072,lifecycle_wire.build_hero_death(4000,1500))
            o.consume(1009,struct.pack('>IBx',1,0))
        self.assertFalse(all(o.finished() for o in observers))

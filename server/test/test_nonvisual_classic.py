"""Ordinary match driver must not turn setup/input uncertainty into a pass."""
import unittest
import struct
from unittest.mock import Mock, patch

from Tools.classic_client import (ClassicMatchExercise, central_projection, next_upgrade,
                                 path_step, on_mesh_click, lane_goal, recent_target_lock, next_purchase,
                                 recall_needed)
from Tools.classic_client import native_damage_window, wire_payload_hex
from Tools.scenario_client import ClientStageFailure


CAMERA = {'view': [1,0,0,0, 0,1,0,0, 0,0,1,0, -2,0,0,1],
          'projection': [1,0,0,0, 0,1,0,0, 0,0,-11/9,-1, 0,0,-20/9,0],
          'dimensions': [960,540]}
PEER = {'identity': 'peer', 'eid': 1517, 'slot': 3, 'team': 2, 'match_id': 'm'}


class MixedMeasurementTests(unittest.TestCase):
    def b_pick(self):
        _, _, camera, _ = self.pick_move()
        # B's last classic-move-attempt at 1792713612.3296978; translate
        # view z to the first 100010 hold (1792713613.9167664) clip-w.
        camera['view'][-4:-1] = [17.92578887939453, -3.981868267059326, -27.062408447265625]
        actor = {'eid': 100010, 'position_xyz': [13, .007069703191518784, 37.70000076293945],
                 'selection_center_xyz': [13, .007069703191518784, 37.70000076293945],
                 'selection_height': 1.1200000047683716}
        return camera, actor

    @staticmethod
    def pick_anchors(camera, actor):
        ground, center = actor['position_xyz'], actor['selection_center_xyz']
        points = (ground, [center[0], center[1]+.5*actor['selection_height'], center[2]],
                  center, [center[0]+1.5, center[1], center[2]])
        vectors = []
        for point in points:
            v = list(point)+[1]
            for m in (camera['view'], camera['projection']):
                v = [sum(m[4*j+i]*v[j] for j in range(4)) for i in range(4)]
            vectors.append(v)
        return vectors

    def test_4ab_sub_near_all_positive_capsule_no_longer_holds_recorded_taps(self):
        import math
        from Tools.classic_client import mixed_pick_risk
        from server.hitboxes import segment_distance
        camera, actor = self.b_pick()
        anchors = self.pick_anchors(camera, actor)
        expected = (.43910690310059364, .022945774238344097,
                    .43910690310059364, .17933107080517585)
        n = camera['projection'][14]/(camera['projection'][10]-1)
        for v, w in zip(anchors, expected):
            self.assertAlmostEqual(v[3], w, delta=1e-3)
            self.assertGreater(v[3], 0)
            self.assertLess(v[3], n)
        # Pre-H1 all-projected branch: identical center/horizontal radius and
        # ground/top distance calculation, without the near-plane check.
        points = [((v[0]/v[3]+1)*480, (1-v[1]/v[3])*270) for v in anchors]
        legacy_r_px = math.dist(points[2], points[3])
        self.assertGreater(legacy_r_px, 1e4)
        for xy in ((590,266), (535,256), (507,251)):
            with self.subTest(tap=xy):
                self.assertLessEqual(segment_distance(xy, *points[:2]), legacy_r_px)
                self.assertIsNone(mixed_pick_risk(camera, (-11,-1.8), xy, [actor]))

    def test_all_positive_capsule_straddling_near_still_refuses(self):
        from Tools.classic_client import mixed_pick_risk
        camera, actor = self.partial_pick()
        actor.update(selection_center_xyz=[0,-1.5,0])
        self.assertTrue(all(v[3] > 0 for v in self.pick_anchors(camera, actor)))
        risk = mixed_pick_risk(camera, (10,10), (1200,540), [actor])
        self.assertEqual(risk['branch'], 'clipped')
        self.assertAlmostEqual(risk['r_px'], 720)
        self.assertIsNone(mixed_pick_risk(camera, (10,10), (1201,540), [actor]))

    def test_all_projected_retains_legacy_geometry_for_opponent_self_ally_neutral(self):
        import math
        from Tools.classic_client import mixed_pick_risk
        for eid, team in ((1517,2), (1500,1), (4000,1), (100010,0)):
            _, _, camera, actor = self.pick_move()
            actor.update(eid=eid, team=team)
            anchors = self.pick_anchors(camera, actor)
            n = camera['projection'][14]/(camera['projection'][10]-1)
            self.assertTrue(all(v[3] >= n for v in anchors))
            points = [((v[0]/v[3]+1)*480, (1-v[1]/v[3])*270) for v in anchors]
            with self.subTest(eid=eid, team=team):
                risk = mixed_pick_risk(camera, (10,-2), points[0], [actor])
                self.assertEqual(risk['branch'], 'all-projected')
                self.assertEqual(risk['r_px'], math.dist(points[2], points[3]))
                self.assertEqual(risk['reason'], 'screen pick capsule')
                self.assertEqual(risk['camera'], {k: camera[k] for k in ('view','projection','dimensions')})

    def test_all_positive_invalid_projection_refuses_as_unknown(self):
        from Tools.classic_client import mixed_pick_risk
        for index, value in ((14,0), (10,-1), (15,.5), (1,.1), (0,float('nan'))):
            _, _, camera, actor = self.pick_move()
            camera['projection'][index] = value
            with self.subTest(index=index):
                risk = mixed_pick_risk(camera, (10,10), (480,270), [actor])
                self.assertEqual(risk['branch'], 'unknown')
                self.assertIsNone(risk['r_px'])

    def test_hold_records_retain_camera_matrices_and_viewport(self):
        run, driver, camera, _ = self.pick_move()
        destination = (-.665484086369243, -2.0016972758627896)
        with patch('Tools.classic_client.path_step', return_value=destination):
            run.move(camera, (-4.665471076965332,-2.011898994445801), destination, pick_eids=[1500,1517])
        self.assertEqual(len(driver.observations['mixed_pick_holds']), 3)
        for hold in driver.observations['mixed_pick_holds']:
            self.assertEqual(hold['camera'], {k: camera[k] for k in ('view','projection','dimensions')})
            self.assertIn(hold['branch'], ('all-projected','clipped','unknown'))
            self.assertEqual(set(hold['clip_w']), {'ground','top','center','horizontal'})
            for k in ('position_xyz','selection_center_xyz','selection_height'):
                self.assertIn(k, hold)

    def partial_pick(self, ground_y=-3):
        import copy
        camera = copy.deepcopy(CAMERA)
        camera['view'] = [1,0,0,0, 0,1,1,0, 0,0,1,0, 0,0,0,1]
        actor = {'eid': 100009, 'position_xyz': [0, ground_y, 0],
                 'selection_center_xyz': [0, 0, 0], 'selection_height': 2}
        return camera, actor

    def test_4z_camera_neutral_straddling_camera_plane_no_longer_holds_recorded_taps(self):
        from Tools.classic_client import mixed_pick_risk
        _, _, camera, _ = self.pick_move()
        # Z/boot-1/entry/client-result-1792697127.json, last classic-move-attempt.
        camera['view'][-4:-1] = [67.8704833984375, -12.294020652770996, -18.962730407714844]
        actor = {'eid': 100009, 'position_xyz': [21.95, -.6, 24],
                 'selection_center_xyz': [21.95, -.6, 24], 'selection_height': 4}
        def w(y):
            return -(camera['view'][2]*21.95+camera['view'][6]*y+
                     camera['view'][10]*24+camera['view'][14])
        self.assertGreater(w(-.6), 0)
        self.assertLess(w(1.4), 0)
        self.assertLess(w(-.6), camera['projection'][14]/(camera['projection'][10]-1))
        for xy in ((592,266), (535,256), (507,251)):
            with self.subTest(tap=xy):
                self.assertIsNone(mixed_pick_risk(camera, (-66, .4), xy, [actor]))

    def test_clipped_straddling_capsule_still_refuses_at_conservative_radius(self):
        from Tools.classic_client import mixed_pick_risk
        camera, actor = self.partial_pick()
        risk = mixed_pick_risk(camera, (10,10), (1200,540), [actor])
        self.assertEqual(risk['branch'], 'clipped')
        self.assertEqual(risk['reason'], 'screen pick capsule')
        self.assertAlmostEqual(risk['r_px'], 720)
        self.assertIsNone(mixed_pick_risk(camera, (10,10), (1201,540), [actor]))

    def test_partial_capsule_entirely_before_near_plane_is_not_pickable_but_world_clearance_remains(self):
        from Tools.classic_client import mixed_pick_risk
        camera, actor = self.partial_pick(-.5)
        self.assertIsNone(mixed_pick_risk(camera, (10,10), (480,540), [actor]))
        risk = mixed_pick_risk(camera, (0,0), (480,540), [actor])
        self.assertEqual(risk['reason'], 'world clearance')
        self.assertEqual(risk['branch'], 'clipped')

    def test_partial_capsule_invalid_projection_stays_unknown(self):
        from Tools.classic_client import mixed_pick_risk
        for index, value in ((14, 0), (10, -1), (15, .5), (1, .1), (0, float('nan'))):
            camera, actor = self.partial_pick()
            camera['projection'][index] = value
            with self.subTest(index=index):
                risk = mixed_pick_risk(camera, (10,10), (480,540), [actor])
                self.assertEqual(risk['branch'], 'unknown')
                self.assertIsNone(risk['r_px'])

    def test_clipped_capsule_supports_finite_positive_sub_epsilon_near_plane(self):
        from Tools.classic_client import mixed_pick_risk
        camera, actor = self.partial_pick()
        camera['projection'][14] *= 1e-8
        risk = mixed_pick_risk(camera, (10,10), (480,540), [actor])
        self.assertEqual(risk['branch'], 'clipped')
        self.assertGreater(risk['r_px'], 1e9)

    def test_hold_records_retain_native_geometry_and_anchor_clip_w(self):
        run, driver, camera, actor = self.pick_move()
        destination = (-.665484086369243, -2.0016972758627896)
        with patch('Tools.classic_client.path_step', return_value=destination):
            run.move(camera, (-4.665471076965332, -2.011898994445801), destination, pick_eids=[1500,1517])
        for hold in driver.observations['mixed_pick_holds']:
            self.assertEqual(hold['position_xyz'], actor['position_xyz'])
            self.assertEqual(hold['selection_center_xyz'], actor['selection_center_xyz'])
            self.assertEqual(hold['selection_height'], actor['selection_height'])
            self.assertEqual(hold['branch'], 'all-projected')
            self.assertEqual(set(hold['clip_w']), {'ground','top','center','horizontal'})
            self.assertTrue(all(w > 0 for w in hold['clip_w'].values()))

    def pick_move(self):
        # 4w entry/client-result-1792683497.json, last classic-move-attempt.
        camera = {'dimensions': [960, 540],
            'projection': [1.7840219736099243,0,0,0, 0,3.1715946197509766,0,0,
                           0,0,-1.0053842067718506,-1, 0,0,-8.076369285583496,0],
            'view': [0.9659257531166077,-0.19234022498130798,0.1731838881969452,0,
                     0,0.6691305637359619,0.7431448698043823,0,
                     -0.2588192820549011,-0.717822790145874,0.6463304162025452,0,
                     4.040741443634033,-1.502847671508789,-28.674793243408203,1]}
        from server.test.test_protocol_policy import mixed_mesh
        driver = Mock(profile={}, observations={})
        run = ClassicMatchExercise(driver)
        run.mixed_team, run.mesh, run.slot, run.eid = 1, mixed_mesh(), 0, 1500
        actor = {'eid': 1517, 'position_xyz': [.0001, .00707, -2.0044],
                 'selection_center_xyz': [.0001, .00707, -2.0044], 'selection_height': 2}
        own = {'eid': 1500, 'position_xyz': [-4.665471076965332, 0, -2.011898994445801],
               'selection_center_xyz': [-4.665471076965332, 0, -2.011898994445801], 'selection_height': 2}
        run.observer = Mock(actor_states=Mock(return_value={'missing': [], 'actors': [actor, own]}))
        run.receipt = Mock(side_effect=[{'time': 1}, {'time': 2}])
        return run, driver, camera, actor

    def test_4w_old_destination_refused_without_taps_and_hold_is_paced(self):
        run, driver, camera, actor = self.pick_move()
        destination = (-.665484086369243, -2.0016972758627896)
        with patch('Tools.classic_client.path_step', return_value=destination) as step:
            run.move(camera, (-4.665471076965332, -2.011898994445801), destination, pick_eids=[1500, 1517])
        self.assertEqual([c.args[-1] for c in step.call_args_list], [4, 2, 1])
        driver.adb.tap.assert_not_called()
        self.assertEqual(len(driver.observations['mixed_pick_holds']), 3)
        self.assertTrue(all(h['actor_eid'] == 1517 and h['r_px'] > 0
                            for h in driver.observations['mixed_pick_holds']))
        from Tools.protocol_policy import MixedRendezvous
        run.mixed_rendezvous = MixedRendezvous(run.mesh)
        driver.observations['mixed_combat'] = {}
        me = {'position_xyz': [-4.665, 0, -2]}
        actor['alive'] = False
        run.last_target = 1517  # Cancellation must not bypass a pick hold.
        run.move = Mock()
        with patch('Tools.classic_client.time.monotonic', return_value=run.last_action+1.19):
            run.mixed_combat_action(camera, me, actor, pick_eids=[1500, 1517])
        run.move.assert_not_called()

    def test_team_stage_separation_allows_exactly_one_move_tap(self):
        run, driver, camera, actor = self.pick_move()
        actor.update(position_xyz=[1.5, .00707, -2], selection_center_xyz=[1.5, .00707, -2])
        run.move(camera, (-4.665, -2.012), (-1.5, -2), pick_eids=[1500, 1517])
        driver.adb.tap.assert_called_once()
        self.assertNotIn('mixed_pick_holds', driver.observations)

    def test_unsafe_long_step_shortens_before_one_tap(self):
        run, driver, camera, actor = self.pick_move()
        run.move(camera, (-4.665471076965332, -2.011898994445801),
                 (-.665484086369243, -2.0016972758627896), pick_eids=[1500, 1517])
        driver.adb.tap.assert_called_once()
        attempt = driver.gesture.call_args_list[0].kwargs
        self.assertLess(attempt['world_xyz'][0], -2.6)

    def test_screen_capsule_alone_refuses_and_wholly_behind_is_not_pickable(self):
        from Tools.classic_client import mixed_pick_risk
        run, driver, camera, actor = self.pick_move()
        ground_screen = central_projection(camera, actor['position_xyz'])
        risk = mixed_pick_risk(camera, (10, -2), ground_screen, [actor])
        self.assertEqual(risk['reason'], 'screen pick capsule')
        actor.update(position_xyz=[0, 0, 100], selection_center_xyz=[0, 0, 100])
        self.assertIsNone(mixed_pick_risk(camera, (10, -2), ground_screen, [actor]))

    def test_mixed_registry_bound_and_missing_native_actor_send_no_input(self):
        for eids, missing in ((None, []), (list(range(201)), []), ([1517], []), ([1500, 1517], [1517])):
            run, driver, camera, actor = self.pick_move()
            run.observer.actor_states.return_value['missing'] = missing
            with self.subTest(eids=eids), self.assertRaises(ClientStageFailure) as failure:
                run.move(camera, (-4.665, -2.012), (-1.5, -2), pick_eids=eids)
            self.assertEqual(failure.exception.stage, 'SETUP')
            driver.adb.tap.assert_not_called()

    def test_creature_under_destination_is_refused(self):
        run, driver, camera, actor = self.pick_move()
        actor.update(eid=4000, position_xyz=[-1.5, .00707, -2],
                     selection_center_xyz=[-1.5, .00707, -2])
        run.move(camera, (-1.6, -2), (-1.5, -2), pick_eids=[1500, 4000])
        run.observer.actor_states.assert_called_once_with([1500, 4000])
        driver.adb.tap.assert_not_called()
        self.assertEqual(driver.observations['mixed_pick_holds'][0]['actor_eid'], 4000)

    def test_move_1060_misfire_is_explicit_and_request_retained(self):
        run, driver, camera, actor = self.pick_move()
        actor.update(position_xyz=[1.5, .00707, -2], selection_center_xyz=[1.5, .00707, -2])
        run.receipt = Mock(return_value=None)
        request = {'direction': 'c2s', 'opcode': 1060, 'time': 11, 'payload': '000005ed0000'}
        driver.tail.records = [request]
        driver._on_connection.return_value = True
        with patch('Tools.classic_client.time.time', return_value=10), \
                self.assertRaisesRegex(ClientStageFailure, 'move tap consumed as native pick') as failure:
            run.move(camera, (-4.665, -2.012), (-1.5, -2), pick_eids=[1500, 1517])
        self.assertEqual(failure.exception.stage, 'CLIENT_INPUT_OBSERVED')
        self.assertEqual(driver.observations['move_pick_misfires'], [request])
        driver.adb.tap.assert_called_once()

    def test_4y_near_self_stage_tap_is_refused_without_input(self):
        run, driver, camera, _ = self.pick_move()
        # 4y outcome.json, classic-move-attempt at 1792694741.6601114.
        camera['view'][-4:-1] = [1.5742160081863403, -.9930818676948547, -29.133787155151367]
        own = {'eid': 1500, 'position_xyz': [-2.1629691123962402, .007069703191518784, -1.9874261617660522],
               'selection_center_xyz': [-2.1629691123962402, .007069703191518784, -1.9874261617660522],
               'selection_height': 2}
        run.observer.actor_states.return_value['actors'] = [own]
        run.mesh.height_at = Mock(return_value=.00707)  # Y's measured ground plane.
        run.move(camera, (-2.1629691123962402, -1.9874261617660522), (-1.5, -2), pick_eids=[1500])
        driver.adb.tap.assert_not_called()
        self.assertEqual(len(driver.observations['mixed_pick_holds']), 3)
        for hold in driver.observations['mixed_pick_holds']:
            self.assertEqual(hold['actor_eid'], 1500)
            self.assertEqual(hold['screen_point'], [498, 249])
            self.assertEqual(hold['reason'], 'world clearance')
            self.assertFalse(hold['input_submitted'])

    def test_allied_and_neutral_creature_pick_capsules_are_refused(self):
        for team in (1, 0):
            run, driver, camera, actor = self.pick_move()
            actor.update(eid=4000, team=team, position_xyz=[-1.5, .00707, -2],
                         selection_center_xyz=[-1.5, .00707, -2])
            with self.subTest(team=team), patch('Tools.classic_client.path_step', return_value=(-1.5, -2)):
                run.move(camera, (-4.665, -2.012), (-1.5, -2), pick_eids=[1500, 4000])
                driver.adb.tap.assert_not_called()
                self.assertEqual({h['actor_eid'] for h in driver.observations['mixed_pick_holds']}, {4000})

    def mixed_action(self):
        driver = Mock(profile={}, observations={'mixed_combat': {}})
        run = ClassicMatchExercise(driver)
        run.mixed_team, run.eid = 1, 1500
        from server.test.test_protocol_policy import mixed_mesh
        from Tools.protocol_policy import MixedRendezvous
        run.mesh = mixed_mesh()
        run.mixed_rendezvous = MixedRendezvous(run.mesh)
        run.target, run.move = Mock(), Mock()
        me = {'eid': 1500, 'position_xyz': [2, 0, -2]}
        target = {'eid': 1517, 'position_xyz': [3, 0, -2],
                  'selection_center_xyz': [3, 0, -2], 'selection_height': 2}
        return run, driver, me, target

    def test_mixed_nearby_off_playfield_target_approaches_without_a_pick(self):
        run, driver, me, target = self.mixed_action()
        with self.assertRaisesRegex(ValueError, 'outside qualified central playfield'):
            central_projection(CAMERA, [3, 1, -2])
        run.mixed_combat_action(CAMERA, me, target)
        run.target.assert_not_called()
        run.move.assert_called_once_with(CAMERA, (2, -2), (-1.5, -2), pick_eids=None)
        deferred, = driver.observations['mixed_target_deferrals']
        self.assertFalse(deferred['input_submitted'])
        self.assertEqual(deferred['target'], target)
        self.assertNotIn('classification', driver.observations['mixed_combat'])

    def test_mixed_fresh_in_playfield_target_keeps_ordinary_target_path(self):
        run, driver, me, target = self.mixed_action()
        target.update(position_xyz=[2, 0, -2], selection_center_xyz=[2, 0, -2], selection_height=0)
        run.mixed_combat_action(CAMERA, me, target)
        run.target.assert_called_once_with(CAMERA, target)
        run.move.assert_not_called()
        self.assertNotIn('mixed_target_deferrals', driver.observations)
        self.assertEqual(driver.observations['mixed_combat']['classification'],
                         'accepted; reciprocal CE-native effects pending')
        run.last_target = target['eid']
        run.target.reset_mock()
        run.mixed_combat_action(CAMERA, me, target)
        run.target.assert_not_called()
        run.move.assert_not_called()

    def test_dead_or_zero_hp_target_resets_then_respawn_is_targeted(self):
        for life in ({'alive': False, 'hp': .01}, {'alive': True, 'hp': 0}):
            run, driver, me, target = self.mixed_action()
            me['position_xyz'] = [-1.5, 0, -2]
            target.update(position_xyz=[2, 0, -2], selection_center_xyz=[2, 0, -2], selection_height=0, **life)
            run.last_target = 1517
            with self.subTest(life=life):
                run.mixed_combat_action(CAMERA, me, target, pick_eids=[1500])
                self.assertIsNone(run.last_target)
                run.move.assert_not_called()
                run.target.assert_not_called()
                driver.adb.tap.assert_not_called()
                self.assertNotIn('mixed_pick_holds', driver.observations)
                target.update(alive=True, hp=100)
                run.mixed_combat_action(CAMERA, me, target, pick_eids=[1500, 1517])
                run.target.assert_called_once_with(CAMERA, target)

    def test_inside_disk_near_stage_waits_but_outside_disk_and_clearance_boundary_do_not(self):
        for origin, expected_move in (((-2.16, -2), False), ((-3, -2), True), ((-3.01, -2), True)):
            run, driver, me, target = self.mixed_action()
            me['position_xyz'] = [origin[0], 0, origin[1]]
            target['position_xyz'] = [54, 0, 2.92]
            with self.subTest(origin=origin):
                run.mixed_combat_action(CAMERA, me, target, pick_eids=[1500, 1517])
                self.assertEqual(run.move.called, expected_move)
                run.target.assert_not_called()
                self.assertNotIn('mixed_pick_holds', driver.observations)
                self.assertNotIn('ce', driver.observations['mixed_combat'].get('stage_point_times', {}))

    def test_run_mixed_passes_only_living_pick_actors_of_every_team_including_self(self):
        import tempfile
        import time
        from pathlib import Path
        from Tools import scenario_client as sc
        from Tools.Teardown import observe_client_movement as native
        from server import navigation
        from server.test.test_protocol_policy import mixed_mesh
        with tempfile.TemporaryDirectory() as temp:
            driver = Mock(profile={'classic_match': {'mixed_combat': {
                'duration_s': 60, 'opponent_identity': 'peer', 'participant_log': str(Path(temp)/'peer.jsonl')}}},
                observations={}, out_dir=Path(temp), connection='ce')
            binding = {'eid': 1500, 'slot': 0, 'team': 1, 'match_id': 'm'}
            driver.observations.update(entry_binding={'world': binding}, nonvisual_entry=[
                {'stage': 'MIXED_DRAFT_READY', 'receipt': {'assignments': {'peer': PEER}}},
                {'stage': 'MIXED_WORLD_RELEASE'}])
            state = {'phase': 'world', 'match_id': 'm', 'tick': 2,
                'heroes': [dict(eid=eid, team=team, alive=alive) for eid, team, alive in
                           ((1500, 1, True), (1515, 1, True), (1517, 2, True), (1519, 2, False))],
                'nearby_creatures': [dict(eid=eid, team=team, alive=alive) for eid, team, alive in
                                    ((4000, 0, True), (4001, 1, True), (4002, 2, True), (4003, 0, False))]}
            driver._qualify_nonvisual_world.return_value = (1500, 0, 265)
            driver.setup.return_value = {'snapshot': {'tick': 1}}
            driver.qa.snapshot.return_value = state
            driver._foreground_package.return_value = sc.ANDROID_PACKAGE
            driver.tail.records = [{'direction': 's2c', 'time': time.time()}]
            observer = Mock(errors=[], output=Path(temp)/'native.jsonl')
            observer.resources.return_value = {'eid': 1500, 'current': {'hp': 100, 'barrier': 0, 'fortified': 0}, 'max_hp': 100}
            actors = {'missing': [], 'actors': [{'eid': eid, 'hp': 100} for eid in (1500, 1517)]}
            observer.actor_states.return_value = actors
            run = ClassicMatchExercise(driver)
            run.owned = Mock(return_value={'team': 1, 'statuses': []})
            run.mixed_respawn_ready = Mock(return_value=True)
            run.mixed_respawn_camera_ready = Mock(return_value=True)
            run.fresh_camera_actors = Mock(return_value=(CAMERA, actors))
            run.mixed_combat_action = Mock(side_effect=RuntimeError('pick set reached'))
            with patch.object(native, 'ClientMovementObserver', return_value=observer), \
                    patch.object(navigation, 'load_halcyon_navmesh', return_value=mixed_mesh()), \
                    self.assertRaisesRegex(RuntimeError, 'pick set reached'):
                run.run_mixed()
            self.assertEqual(run.mixed_combat_action.call_args.kwargs['pick_eids'],
                             [1500, 1515, 1517, 4000, 4001, 4002])
            observer.stop.assert_called_once_with()

    def test_mixed_projection_and_target_receipt_failures_are_not_retried(self):
        run, driver, me, target = self.mixed_action()
        with self.assertRaisesRegex(ValueError, 'unqualified viewport'):
            run.mixed_combat_action(dict(CAMERA, dimensions=[1920, 1080]), me, target)
        run.target.assert_not_called()
        run.move.assert_not_called()
        target.update(position_xyz=[2, 0, -2], selection_center_xyz=[2, 0, -2], selection_height=0)
        run.target.side_effect = ValueError('projected point outside qualified central playfield')
        with self.assertRaisesRegex(ValueError, 'outside qualified central playfield'):
            run.mixed_combat_action(CAMERA, me, target)
        run.target.assert_called_once_with(CAMERA, target)
        run.move.assert_not_called()
        self.assertNotIn('mixed_target_deferrals', driver.observations)

    def test_mixed_approach_keeps_action_interval_and_propagates_move_refusal(self):
        for far in (False, True):
            run, driver, me, target = self.mixed_action()
            if far:
                target['position_xyz'][2] = -20  # far, but outside the new protected turret zones
            with self.subTest(far=far), patch('Tools.classic_client.time.monotonic', return_value=100):
                run.last_action = 99
                run.mixed_combat_action(CAMERA, me, target)
                run.move.assert_not_called()
                run.target.assert_not_called()
                run.last_action = 98
                run.move.side_effect = ValueError('movement projection refused')
                with self.assertRaisesRegex(ValueError, 'movement projection refused'):
                    run.mixed_combat_action(CAMERA, me, target)
                run.move.assert_called_once()
                run.target.assert_not_called()

    def test_late_build_at_mixed_setup_is_dismissed_once_before_gameplay(self):
        import tempfile
        import time
        from pathlib import Path
        from Tools import scenario_client as sc
        from Tools.Teardown import observe_client_movement as native
        from server import navigation
        from contextlib import nullcontext
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            d = sc.ClientDriver('classic-match', adb=Mock(serial='A'), qa=Mock(), tail=Mock(),
                connection=7, profile={'classic_match': {'capture_backend': 'none', 'drive_entry': False,
                    'mixed_combat': {'duration_s': 60, 'opponent_identity': 'peer',
                                     'participant_log': str(Path(temp)/'peer.jsonl')}}},
                out_dir=Path(temp), timeout=1)
            binding = {'eid': 1500, 'slot': 0, 'team': 1, 'match_id': 'm'}
            d.observations.update(entry_binding={'world': binding}, nonvisual_entry=[
                {'stage': 'MIXED_DRAFT_READY', 'receipt': {'assignments': {
                    'peer': {'eid': 1517, 'slot': 3, 'team': 2}}}}, {'stage': 'MIXED_WORLD_RELEASE'}])
            d._qualify_nonvisual_world = Mock(return_value=(1500, 0, 265))
            d.setup = Mock(return_value={'snapshot': {'tick': 1}})
            d._lock_nonvisual_camera = Mock()
            d._foreground_package = Mock(return_value=sc.ANDROID_PACKAGE)
            d.qa.snapshot.side_effect = RuntimeError('gameplay reached after HUD')
            recorder = Mock()
            d._build_entry = SimpleNamespace(input_window=nullcontext, record=recorder)
            observer = Mock(errors=[], output=Path(temp)/'native.jsonl')
            observer.ui_state.side_effect = [
                {'labels': ['Choose a Build'], 'host_read_started': time.monotonic()},
                {'labels': ['BUY:', '0:20']}]
            with patch.object(native, 'ClientMovementObserver', return_value=observer), \
                    patch.object(navigation, 'load_halcyon_navmesh'), patch.object(sc.time, 'sleep'), \
                    self.assertRaisesRegex(RuntimeError, 'gameplay reached after HUD'):
                ClassicMatchExercise(d).run()
            d.adb.back.assert_called_once_with()
            d._lock_nonvisual_camera.assert_called_once_with(observer)
            d.qa.snapshot.assert_called_once_with()
            self.assertEqual(d.gestures[0]['kind'], 'native-ui-back')
            transport = [c.kwargs for c in recorder.call_args_list if 'input_transport' in c.kwargs]
            self.assertEqual(len(transport), 1)
            self.assertEqual(transport[0]['input_transport'], 'returned')
            observer.stop.assert_called_once_with()

    def test_mixed_mode_dispatch_remains_opt_in_and_rejects_missing_barriers_or_short_duration(self):
        for plan in ({'duration_s': 1}, {'duration_s': 60}):
            d = Mock(profile={'classic_match': {'mixed_combat': plan}}, observations={})
            with self.subTest(plan=plan), self.assertRaises(ClientStageFailure) as failed:
                ClassicMatchExercise(d).run()
            self.assertEqual(failed.exception.stage, 'SETUP')
            d._qualify_nonvisual_world.assert_not_called()
            d.adb.tap.assert_not_called()

    def fixture(self, *, barrier=0, fortified=0, regen=0, damage=-40):
        a = {'eid': 1517, 'generation': 1, 'hp': 100, 'max_hp': 200,
             'barrier': barrier, 'fortified': fortified, 'host_before': 10, 'host_after': 10.01}
        absorbed = min(barrier, -damage)
        remainder = -damage-absorbed
        fort = min(fortified, 100, remainder*.5)
        b = {**a, 'hp': 100-remainder+fort+regen, 'barrier': barrier-absorbed,
             'fortified': fortified-fort, 'host_before': 11, 'host_after': 11.01}
        def record(opcode, payload, at, direction='s2c'):
            return {'connection': 7, 'direction': direction, 'opcode': opcode, 'payload': payload.hex(), 'time': at}
        rows = [record(1060, struct.pack('>IH', 1517, 0), 10.1, 'c2s'),
                record(1045, struct.pack('>II', 1500, 1517), 10.2),
                record(1054, struct.pack('>IIf', 1517, 1500, damage), 10.4)]
        if regen:
            rows.append(record(1053, struct.pack('>IfB', 1517, regen, 0), 10.5))
        peer = [{'direction': 's2c', 'opcode': 1054, 'payload_hex': wire_payload_hex(rows[2]['payload']),
                 'wall_time': 10.41, 'generation': 1}]
        rows.append(dict(PEER, direction='identity', connection=8, time=9))
        owner = struct.pack('>I', PEER['eid'])
        block = bytearray(750)
        struct.pack_into('>II', block, 8, PEER['eid'], PEER['team'])
        block[745] = PEER['slot']
        peer.append({'direction': 'c2s', 'opcode': 1000, 'generation': 1, 'wall_time': 8.9,
                     'payload_hex': (b'peer'+bytes(34)).hex()})
        for op, payload in ((1001, owner), (1011, block)):
            rows.append(dict(record(op, payload, 9.1), connection=8))
            peer.append({'direction': 's2c', 'opcode': op, 'generation': 1, 'wall_time': 9.11,
                         'payload_hex': wire_payload_hex(payload.hex())})
        return {'actors': {1517: a}}, {'actors': {1517: b}}, rows, peer

    def measure(self, a, b, rows, peer, **kw):
        return native_damage_window(a, b, rows, participant_records=peer,
            participant_binding=PEER, connection=7, source=1500, victim=1517, require_basic_input=True, **kw)

    def test_reciprocal_parser_accounts_for_regen_and_pools_not_just_raw_hp_difference(self):
        for pools in ({}, {'regen': 3}, {'barrier': 10}, {'fortified': 10},
                      {'barrier': 10, 'fortified': 10, 'regen': 3}):
            with self.subTest(pools=pools):
                result = self.measure(*self.fixture(**pools))
                self.assertEqual(result['classification'], 'authoritative outcome + measured CE-native effect', result)
                self.assertEqual(result['predicted']['hp'], result['after']['actors'][1517]['hp'])
                self.assertEqual(result['request']['opcode'], 1060)
        a, b, rows, peer = self.fixture()
        # Incoming damage uses resources() for owner; it does not require a CE
        # outgoing 1060. Direction/source identity is still exact.
        result = native_damage_window(a, b, rows, participant_records=peer, connection=7,
                                      participant_binding=PEER, source=1500, victim=1517)
        self.assertEqual(result['classification'], 'authoritative outcome + measured CE-native effect')

    def test_other_attackers_missing_peer_wrong_owner_or_unknown_growth_never_pass(self):
        for kind in ('other-attacker', 'peer', 'wrong-connection', 'growth', 'native-mismatch',
                     'barrier-only', 'read-overlap', 'generation', 'no-input', 'superseded', 'nonfinite'):
            a, b, rows, peer = self.fixture(barrier=50 if kind == 'barrier-only' else 0)
            if kind == 'other-attacker':
                rows.append({**rows[2], 'time': 10.6, 'payload': struct.pack('>IIf',1517,1518,-1).hex()})
            elif kind == 'peer': peer = []
            elif kind == 'wrong-connection':
                for r in rows: r['connection'] = 8
            elif kind == 'growth': rows.append({**rows[2], 'opcode': 1076})
            elif kind == 'native-mismatch': b['actors'][1517]['hp'] -= 1
            elif kind == 'read-overlap': rows[2]['time'] = 10.005
            elif kind == 'generation': b['actors'][1517]['generation'] = 2
            elif kind == 'no-input': rows.pop(0)
            elif kind == 'superseded': rows.append({**rows[0], 'opcode': 1012, 'time': 10.3})
            elif kind == 'nonfinite': b['actors'][1517]['hp'] = float('nan')
            with self.subTest(kind=kind):
                result = self.measure(a,b,rows,peer)
                self.assertNotEqual(result['classification'], 'authoritative outcome + measured CE-native effect')
                self.assertIn('unknown', result)

    def test_duplicate_damage_requires_duplicate_peer_receipts_not_set_membership(self):
        a,b,rows,peer = self.fixture()
        rows.append({**rows[2], 'time': 10.6})
        b['actors'][1517]['hp'] -= 40
        self.assertIn('participant', self.measure(a,b,rows,peer)['unknown'])
        peer.append({**peer[0], 'wall_time': 10.61})
        self.assertEqual(self.measure(a,b,rows,peer)['classification'],
                         'authoritative outcome + measured CE-native effect')

    def reconnected_fixture(self):
        a, b, rows, peer = self.fixture()
        original = list(rows)
        rows.append(dict(PEER, direction='identity', connection=18, time=10))
        for row in original:
            if row.get('opcode') in (1001, 1011):
                rows.append(dict(row, connection=18, time=10.1))
        new_peer = [dict(row, generation=2,
                         wall_time=10.41 if row['opcode'] == 1054 else
                         9.9 if row['opcode'] == 1000 else 10.11) for row in peer]
        peer = [r for r in peer if r['opcode'] != 1054] + new_peer
        return a, b, rows, peer

    def test_post_reconnect_damage_binds_same_identity_new_connection_and_padding(self):
        result = self.measure(*self.reconnected_fixture())
        self.assertEqual(result['classification'], 'authoritative outcome + measured CE-native effect', result)
        self.assertEqual(result['participant_receipt_bindings'], [dict(PEER, generation=2, connection=18)])

    def test_post_reconnect_other_identity_match_owner_slot_or_stale_generation_is_refused(self):
        for kind in ('identity', 'match', 'owner', 'slot', 'stale-generation', 'missing-bootstrap', 'metadata'):
            a, b, rows, peer = self.reconnected_fixture()
            if kind == 'identity':
                next(r for r in peer if r['generation'] == 2 and r['opcode'] == 1000)['payload_hex'] = b'other\0'.hex()
            elif kind == 'match':
                next(r for r in rows if r.get('direction') == 'identity' and r['connection'] == 18)['match_id'] = 'other'
            elif kind == 'owner':
                next(r for r in peer if r['generation'] == 2 and r['opcode'] == 1001)['payload_hex'] = '000005ee0000'
            elif kind == 'slot':
                row = next(r for r in peer if r['generation'] == 2 and r['opcode'] == 1011)
                raw = bytearray.fromhex(row['payload_hex'])
                raw[745] = 4
                row['payload_hex'] = raw.hex()
            elif kind == 'stale-generation':
                next(r for r in peer if r['opcode'] == 1054)['generation'] = 1
            elif kind == 'missing-bootstrap':
                peer = [r for r in peer if not (r['generation'] == 2 and r['opcode'] == 1011)]
            else:
                next(r for r in peer if r['opcode'] == 1054)['identity'] = 'other'
            with self.subTest(kind=kind):
                result = self.measure(a, b, rows, peer)
                self.assertIn('identity/generation/bootstrap', result['unknown'])

    def test_padding_normalization_refuses_nonzero_or_extra_bytes(self):
        for suffix in ('01', '0000'):
            a, b, rows, peer = self.fixture()
            peer[0]['payload_hex'] = peer[0]['payload_hex'][:-2]+suffix
            with self.subTest(suffix=suffix):
                self.assertIn('absent/ambiguous', self.measure(a, b, rows, peer)['unknown'])

    def test_turret_confounded_window_stays_unverified_with_valid_peer(self):
        a, b, rows, peer = self.reconnected_fixture()
        rows.append(dict(rows[2], time=10.6, payload=struct.pack('>IIf', 1517, 3539, -1).hex()))
        result = self.measure(a, b, rows, peer)
        self.assertEqual(result['unknown'], 'other attackers confound HP attribution')
        self.assertNotEqual(result['classification'], 'authoritative outcome + measured CE-native effect')

    def test_ce_stages_without_holding_for_opponent_friendly_turret_zone(self):
        run, driver, me, target = self.mixed_action()
        me['position_xyz'] = [-78.18, 0, .88]
        target['position_xyz'] = [54, 0, 2.92]
        run.mixed_combat_action(CAMERA, me, target)
        run.move.assert_called_once_with(CAMERA, (-78.18, .88), (-1.5, -2), pick_eids=None)
        run.target.assert_not_called()
        self.assertNotIn('mixed_holds', driver.observations)
        self.assertEqual(driver.observations['mixed_staging'][0]['phase'], 'staging')

    def test_ce_outside_zone_or_dead_opponent_cancels_target_without_chasing(self):
        for position, alive in (((4, -2), True), ((2, -2), False)):
            run, driver, me, target = self.mixed_action()
            run.last_target = 1517
            target.update(position_xyz=[position[0], 0, position[1]], alive=alive)
            with patch('Tools.classic_client.time.monotonic', return_value=100):
                run.last_action = 100
                run.mixed_combat_action(CAMERA, me, target)
            if alive:
                run.move.assert_called_once_with(CAMERA, (2, -2), (-1.5, -2), pick_eids=None)
            else:
                run.move.assert_not_called()  # Dead-target reset preserves ordinary pacing.
                self.assertIsNone(run.last_target)
            run.target.assert_not_called()
            self.assertNotIn('engagement_started_at', driver.observations['mixed_combat'])

    def test_ce_in_enemy_zone_refuses_route_without_submitting_input(self):
        run, driver, me, target = self.mixed_action()
        me['position_xyz'] = [17.06, 0, 1.93]
        with self.assertRaisesRegex(ValueError, 'enemy structure zone'):
            run.mixed_combat_action(CAMERA, me, target)
        run.move.assert_not_called()
        run.target.assert_not_called()

    def test_ce_already_at_r_waits_without_repeated_clicks_or_a_pick(self):
        run, driver, me, target = self.mixed_action()
        me['position_xyz'] = [-1.5, 0, -2]
        target['position_xyz'] = [54, 0, 2.92]
        run.mixed_combat_action(CAMERA, me, target)
        run.move.assert_not_called()
        run.target.assert_not_called()
        self.assertEqual(driver.observations['mixed_staging'][0]['phase'], 'staging')

    def test_ce_move_checks_route_before_input_even_when_endpoint_is_outside(self):
        run, driver, me, target = self.mixed_action()
        run.observer = Mock(actor_states=Mock(return_value={"actors": [], "missing": []}))
        run.mesh = Mock()
        run.mesh.find_path.return_value = [(17.06, -20), (17.06, 20)]
        with patch('Tools.classic_client.path_step', return_value=(17.06, 20)), \
                patch('Tools.classic_client.on_mesh_click', return_value=((17.06, 20), 0, 0)), \
                patch('Tools.classic_client.central_projection', return_value=[480, 270]):
            ClassicMatchExercise.move(run, CAMERA, (17.06, -20), (17.06, 20), pick_eids=[1500])
        driver.adb.tap.assert_not_called()
        driver.gesture.assert_not_called()
        self.assertIn('route', driver.observations['mixed_holds'][0]['reason'])

    def test_respawn_waits_for_samples_time_and_fresh_centered_camera_then_ordinary_input(self):
        run, driver, me, target = self.mixed_action()
        self.assertFalse(run.mixed_respawn_ready({'alive': False}, 0, 1))
        for at in (2, 2.2, 2.4, 4.739):
            self.assertFalse(run.mixed_respawn_ready({'alive': True}, 708, at))
        run.move.assert_not_called()
        run.target.assert_not_called()
        self.assertTrue(run.mixed_respawn_ready({'alive': True}, 708, 4.741))
        camera = dict(CAMERA, eid=1500, owner_position_xyz=me['position_xyz'])
        with patch('Tools.classic_client.world_to_screen', return_value=[325.7, 224.6]):
            self.assertFalse(run.mixed_respawn_camera_ready(camera, me))
        with patch('Tools.classic_client.world_to_screen', return_value=[480, 246.242]):
            self.assertTrue(run.mixed_respawn_camera_ready(camera, me))
            run.mixed_combat_action(camera, me, target)
        run.target.assert_called_once_with(camera, target)
        run.move.assert_not_called()
        self.assertEqual(driver.observations['mixed_respawn_settles'][-1]['stage'], 'settled')

    def test_respawn_time_alone_is_insufficient_and_another_death_resets_it(self):
        run, driver, me, target = self.mixed_action()
        self.assertFalse(run.mixed_respawn_ready({'alive': False}, 0, 0))
        self.assertFalse(run.mixed_respawn_ready({'alive': True}, 708, 1))
        self.assertFalse(run.mixed_respawn_ready({'alive': True}, 708, 10))
        self.assertFalse(run.mixed_respawn_ready({'alive': False}, 0, 11))
        self.assertFalse(run.mixed_respawn_ready({'alive': True}, 708, 12))
        self.assertEqual(run.mixed_respawn['alive_samples'], 1)
        run.move.assert_not_called()
        run.target.assert_not_called()


class ClassicGuardTests(unittest.TestCase):
    def test_flask_rechecks_native_liveness_after_control_read(self):
        run, d = self.exercise()
        run.observer.default_item_control.return_value = {'eid': 1500, 'center': [324, 497]}
        run.observer.resources.return_value = {'current': {'hp': 0}}
        self.assertFalse(run.flask())
        d.adb.tap.assert_not_called()
        d.tail.wait_for.assert_not_called()
        self.assertEqual(run.counts['flask'], 0)
        # A living owner still needs a real input receipt; no skipped-input pass.
        run.observer.resources.return_value = {'current': {'hp': 100}}
        d.tail.wait_for.return_value = None
        with self.assertRaises(ClientStageFailure):
            run.flask()
        self.assertEqual(run.counts['flask'], 0)
        d.adb.tap.assert_called_once()

    def test_saturated_inventory_does_not_recall_for_unspendable_gold(self):
        owner = {'inventory': [{'item': 505} for _ in range(6)], 'gold': 1661.6,
                 'hp': 2100.05, 'max_hp': 2100.05, 'energy': 732}
        self.assertIsNone(next_purchase(owner))
        self.assertFalse(recall_needed(owner, 4))
        # Coverage and genuine recovery are not removed with the shop reason.
        self.assertTrue(recall_needed(owner, 0))
        self.assertTrue(recall_needed(dict(owner, hp=500), 4))
        self.assertTrue(recall_needed(dict(owner, energy=50), 4))
        run, d = self.exercise()
        self.assertFalse(run.purchase(owner))
        run.observer.shop_control.assert_not_called()
        d.adb.tap.assert_not_called()

    def test_full_inventory_can_still_recall_for_a_supported_component_upgrade(self):
        owner = {'inventory': [{'item': 505} for _ in range(5)]+[{'item': 458}],
                 'gold': 1200, 'hp': 1000, 'max_hp': 1000, 'energy': 500}
        self.assertEqual(next_purchase(owner), (505, 850))
        self.assertTrue(recall_needed(owner, 1))
        self.assertIsNone(next_purchase(dict(owner, gold=849)))
        self.assertFalse(recall_needed(dict(owner, gold=849), 1))

    def exercise(self, profile=None):
        d = Mock(profile=profile or {}, timeout=2, gestures=[], observations={})
        d.adb.screencap.side_effect = AssertionError('no images')
        exercise = ClassicMatchExercise(d)
        exercise.eid = 1500
        exercise.observer = Mock()
        return exercise, d

    @staticmethod
    def lock_record(*, target=1517, source=1500, duration=4, at=100, instance=9001, connection='owned'):
        from server.buff_wire import build_buff_add
        return {'direction':'s2c','opcode':1086,'time':at,'connection':connection,
                'payload':build_buff_add(target, source, duration, instance, 602).hex()}

    def test_lock_requires_owner_target_connection_fresh_duration_and_no_cancellation(self):
        lock=self.lock_record()
        self.assertIs(recent_target_lock([lock],'owned',1500,1517,100.2),lock)
        for invalid in (self.lock_record(target=1518), self.lock_record(source=1515),
                        self.lock_record(connection='other'), self.lock_record(at=98),
                        self.lock_record(duration=.5), self.lock_record(at=101)):
            with self.subTest(record=invalid):
                self.assertIsNone(recent_target_lock([invalid],'owned',1500,1517,100.2))
        from server.buff_wire import build_buff_cancel
        cancel={'direction':'s2c','opcode':1093,'connection':'owned','time':100.1,
                'payload':build_buff_cancel(1517,9001).hex()}
        self.assertIsNone(recent_target_lock([lock,cancel],'owned',1500,1517,100.2))
        newer=self.lock_record(target=1518,at=100.1,instance=9002)
        self.assertIsNone(recent_target_lock([lock,newer],'owned',1500,1517,100.2))

    def test_lock_does_not_survive_owner_or_target_death(self):
        for eid in (1500,1517):
            death={'direction':'s2c','opcode':1072,'connection':'owned','time':100.1,
                   'payload':eid.to_bytes(4,'big').hex()}
            self.assertIsNone(recent_target_lock([self.lock_record(),death],'owned',1500,1517,100.2))

    def test_lock_expired_during_native_control_read_does_not_send_b_input(self):
        run,d=self.exercise()
        d.connection='owned'
        d.tail.records=[self.lock_record()]
        run.observer.ability_control.return_value={'eid':1500,'action':2,'center':[480,500]}
        with patch('Tools.classic_client.time.time',return_value=101.2):
            self.assertFalse(run.cast(CAMERA,{'eid':1517,'position_xyz':[2,0,-2]},'B'))
        d.adb.swipe.assert_not_called()
        self.assertEqual(run.ability_counts['B'],0)

    def test_b_c_use_their_own_native_action_and_cooldown_and_one_gesture(self):
        for slot,action in (('B',2),('C',4)):
            run,d=self.exercise()
            d.connection='owned'
            d.tail.records=[self.lock_record()]
            run.observer.ability_control.return_value={'eid':1500,'action':action,'center':[480,500]}
            d.wait_client_input.return_value={'time':100.21}
            with patch('Tools.classic_client.time.time',return_value=100.2):
                self.assertTrue(run.cast(CAMERA,{'eid':1517,'position_xyz':[2,0,-2]},slot))
            d.adb.swipe.assert_called_once_with(480,500,480,270)
            d.wait_client_input.assert_called_once_with(action=action,since=100.2)
            d.wait_cooldown_tag.assert_called_once_with(slot=slot,hero_eid=1500,since=100.21)
            self.assertEqual(run.ability_counts[slot],1)

    def test_ack_without_cooldown_does_not_count_cast_or_retry(self):
        run,d=self.exercise()
        run.observer.ability_control.return_value={'eid':1500,'action':0,'center':[480,500]}
        d.wait_client_input.return_value={'time':100.21}
        d.wait_cooldown_tag.return_value=None
        with self.assertRaises(ClientStageFailure):
            run.cast_a(CAMERA,{'eid':1517,'position_xyz':[2,0,-2]})
        self.assertEqual(run.counts['cast'],0)
        d.adb.swipe.assert_called_once()

    def test_cast_gesture_overlapping_native_wire_death_is_not_counted_or_retried(self):
        run,d=self.exercise()
        d._on_connection.return_value=True
        run.observer.ability_control.return_value={'eid':1500,'action':0,'center':[480,500]}
        run.observer.resources.return_value={'current':{'hp':0}}
        d.wait_client_input.side_effect=ClientStageFailure('CLIENT_INPUT_OBSERVED','NOT_OBSERVED','missing')
        d.tail.records=[{'time':100.106,'direction':'s2c','opcode':1072,'payload':'000005dc'+'00'*10}]
        with patch('Tools.classic_client.time.time',side_effect=[100,100.278]):
            self.assertTrue(run.cast_a(CAMERA,{'eid':1517,'position_xyz':[2,0,-2]}))
        self.assertEqual(run.counts['cast'],0)
        self.assertEqual(run.counts['cast_interrupted'],1)
        self.assertEqual(run.ability_counts['A'],0)
        d.adb.swipe.assert_called_once()
        d.wait_acknowledgment.assert_not_called()

    def test_later_death_or_living_native_owner_does_not_excuse_missing_cast(self):
        for death_time,native_hp in ((101,0),(100.1,50)):
            run,d=self.exercise()
            d._on_connection.return_value=True
            run.observer.resources.return_value={'current':{'hp':native_hp}}
            d.tail.records=[{'time':death_time,'direction':'s2c','opcode':1072,'payload':'000005dc'+'00'*10}]
            self.assertFalse(run.cast_death_interruption(100,100.278,slot='A'))
            self.assertEqual(run.counts['cast_interrupted'],0)

    def test_target_death_and_exact_lock_cancel_during_swipe_is_not_cast_coverage(self):
        from server.buff_wire import build_buff_cancel
        run,d=self.exercise()
        d.connection='owned'
        d._on_connection.return_value=True
        lock=self.lock_record()
        d.tail.records=[lock]
        run.observer.ability_control.return_value={'eid':1500,'action':4,'center':[480,500]}
        run.observer.actor_states.return_value={'actors':[{'eid':1517,'hp':0}],'missing':[]}
        def missing(**_):
            d.tail.records.extend([
                {'time':100.32,'direction':'s2c','opcode':1072,'payload':'000005ed'+'00'*10},
                {'time':100.325,'direction':'s2c','opcode':1093,
                 'payload':build_buff_cancel(1517,9001).hex()}])
            raise ClientStageFailure('CLIENT_INPUT_OBSERVED','NOT_OBSERVED','missing')
        d.wait_client_input.side_effect=missing
        with patch('Tools.classic_client.time.time',side_effect=[100.2,100.2,100.478]):
            self.assertTrue(run.cast(CAMERA,{'eid':1517,'position_xyz':[2,0,-2]},'C'))
        self.assertEqual(run.counts['cast'],0)
        self.assertEqual(run.counts['cast_interrupted'],1)
        self.assertEqual(run.ability_counts['C'],0)
        d.adb.swipe.assert_called_once()
        d.wait_acknowledgment.assert_not_called()

    def test_target_interruption_requires_gesture_death_exact_cancel_and_native_evidence(self):
        from server.buff_wire import build_buff_cancel
        for death_at,cancel_id,native_hp,slot in ((101,9001,0,'C'),
                (100.1,9999,0,'C'),(100.1,9001,50,'C'),(100.1,9001,0,'A')):
            run,d=self.exercise()
            d._on_connection.return_value=True
            d.tail.records=[
                {'time':death_at,'direction':'s2c','opcode':1072,'payload':'000005ed'+'00'*10},
                {'time':100.12,'direction':'s2c','opcode':1093,
                 'payload':build_buff_cancel(1517,cancel_id).hex()}]
            run.observer.actor_states.return_value={'actors':[{'eid':1517,'hp':native_hp}],'missing':[]}
            self.assertFalse(run.cast_target_interruption(100,100.278,slot=slot,lock=self.lock_record()))
            self.assertEqual(run.counts['cast_interrupted'],0)

    def test_missing_native_target_requires_observed_destruction_too(self):
        from server.buff_wire import build_buff_cancel
        run,d=self.exercise()
        d._on_connection.return_value=True
        d.tail.records=[
            {'time':100.1,'direction':'s2c','opcode':1072,'payload':'000005ed'+'00'*10},
            {'time':100.12,'direction':'s2c','opcode':1093,
             'payload':build_buff_cancel(1517,9001).hex()}]
        run.observer.actor_states.return_value={'actors':[],'missing':[1517]}
        self.assertFalse(run.cast_target_interruption(100,100.278,slot='B',lock=self.lock_record()))
        d.tail.records.append({'time':102,'direction':'s2c','opcode':1073,'payload':'000005ed0000'})
        with patch('Tools.classic_client.time.time',return_value=103):
            self.assertTrue(run.cast_target_interruption(100,100.278,slot='B',lock=self.lock_record()))
        self.assertEqual(run.counts['cast'],0)

    def recall_fixture(self):
        from server import buff_wire, roster
        run,d=self.exercise()
        d._on_connection.return_value=True
        run.pending_recall={'request':{'time':100},'deadline':1000000000}
        records=[]
        for kind in (25,26):
            records.append({'direction':'s2c','opcode':1086,'time':100.01,
                            'payload':buff_wire.build_buff_add(1500,1500,4,9000+kind,kind).hex()})
        d.tail.records=records
        spawn=roster.HERO_SPAWNS[1500]
        owner={'alive':True,'recall_completes_at':None,'x':spawn[0],'y':spawn[1]}
        position={'position_xyz':[spawn[0],0,spawn[1]]}
        native={'current':{'hp':100}}
        return run,d,owner,position,native

    def test_recall_completion_requires_trigger_relocation_and_both_position_sources(self):
        run,d,owner,position,native=self.recall_fixture()
        relocation={'direction':'s2c','opcode':1033,'time':104,'payload':'000005dc'+'00'*14}
        trigger={'direction':'s2c','opcode':1094,'time':104,'payload':'000005dc'+(9025).to_bytes(4,'big').hex()}
        d.tail.records += [trigger,relocation]
        with patch('Tools.classic_client.time.monotonic',return_value=200):
            self.assertTrue(run.observe_recall(owner,{'position_xyz':[0,0,0]},native))
            self.assertEqual(run.counts['recall'],0)
            self.assertFalse(run.observe_recall(owner,position,native))
        self.assertEqual(run.counts['recall'],1)
        self.assertIsNone(run.pending_recall)
        d.adb.tap.assert_not_called()

    def test_recall_cancel_is_not_completion_and_does_not_repeat_input(self):
        from server.buff_wire import build_buff_cancel
        run,d,owner,position,native=self.recall_fixture()
        d.tail.records += [{'direction':'s2c','opcode':1093,'time':101,
                            'payload':build_buff_cancel(1500,i).hex()} for i in (9025,9026)]
        self.assertFalse(run.observe_recall(owner,position,native))
        self.assertEqual(run.counts['recall'],0)
        self.assertEqual(run.counts['recall_interrupted'],1)
        d.adb.tap.assert_not_called()

    def test_recall_death_requires_native_death_too_and_never_counts_return(self):
        run,d,owner,position,native=self.recall_fixture()
        owner['alive']=False
        d.tail.records += [{'direction':'s2c','opcode':1072,'time':101,'payload':'000005dc'+'00'*10}]
        with patch('Tools.classic_client.time.monotonic',return_value=200):
            self.assertTrue(run.observe_recall(owner,position,native))
            self.assertFalse(run.observe_recall(owner,position,{'current':{'hp':0}}))
        self.assertEqual(run.counts['recall'],0)
        self.assertEqual(run.counts['recall_interrupted'],1)

    def test_unknown_recall_end_fails_without_retry(self):
        run,d,owner,position,native=self.recall_fixture()
        run.pending_recall['deadline']=100
        with patch('Tools.classic_client.time.monotonic',return_value=200),self.assertRaises(ClientStageFailure):
            run.observe_recall(owner,position,native)
        self.assertEqual(run.counts['recall'],0)
        d.adb.tap.assert_not_called()

    def test_visible_but_hud_overlapping_projection_refused(self):
        self.assertEqual(central_projection(CAMERA, [2,0,-2]), [480,270])
        with self.assertRaises(ValueError):
            central_projection(CAMERA, [3,1,-2])  # inside frustum, outside playfield
        with self.assertRaises(ValueError):
            central_projection(dict(CAMERA, dimensions=[1920,1080]), [2,0,-2])

    def test_ordinary_pursuit_requires_native_and_authoritative_intent_not_attack_start(self):
        run,d=self.exercise()
        state={'heroes':[{'eid':1500,'hero_id':265,'target':1517,'alive':True}]}
        d.qa.snapshot.return_value=state
        run.observer.selected_target.return_value={'target_eid':1517}
        run.observe_pursuit_selection({'time':100},{'eid':1517},99.99,{})
        self.assertEqual(run.counts['target'],1)
        self.assertEqual(d.gesture.call_args.kwargs['acceptance_source'],
                         'read-only authoritative target intent; not1045')
        d.tail.wait_for.assert_not_called()
        d.adb.tap.assert_not_called()

    def test_death_during_observation_remains_unknown_not_accepted_intent(self):
        run,d=self.exercise()
        d.qa.snapshot.return_value={'heroes':[{'eid':1500,'hero_id':265,'target':None}]}
        run.observer.selected_target.return_value={'target_eid':None}
        d._on_connection.return_value=True
        d.tail.records=[{'time':100.2,'direction':'s2c','opcode':1072,'payload':'000005ed00000000'}]
        run.observer.actor_states.return_value={'missing':[],'actors':[{'eid':1517,'hp':0}]}
        with patch('Tools.classic_client.time.time',return_value=100.3):
            run.observe_pursuit_selection({'time':100},{'eid':1517},99.99,{})
        self.assertEqual(run.counts['target'],0)
        self.assertEqual(run.counts['target_race'],1)
        self.assertFalse(d.gesture.call_args.kwargs['acknowledged'])

    def test_persistent_live_intent_disagreement_still_fails(self):
        run,d=self.exercise()
        d.qa.snapshot.return_value={'heroes':[{'eid':1500,'hero_id':265,'target':1517}]}
        run.observer.selected_target.return_value={'target_eid':1519}
        d.tail.records=[]
        with patch('Tools.classic_client.time.monotonic',side_effect=[0,1]),self.assertRaises(ClientStageFailure):
            run.observe_pursuit_selection({'time':100},{'eid':1517},99.99,{})
        self.assertEqual(run.counts['target'],0)
        d.adb.tap.assert_not_called()

    def test_no_capture_or_legacy_entry_can_reach_a_client_action(self):
        for plan in ({'capture_backend': 'host'}, {'drive_entry': True}, {'max_duration_s': float('inf')}):
            run, d = self.exercise({'classic_match': plan})
            with self.subTest(plan=plan), self.assertRaises(ClientStageFailure):
                run.run()
            d._qualify_nonvisual_world.assert_not_called()
            d.adb.tap.assert_not_called()

    def test_late_join_cannot_claim_full_match(self):
        run, d = self.exercise()
        d._qualify_nonvisual_world.return_value = (1500, 0, 265)
        d.setup.return_value = {'snapshot': {'time': 300}}
        with self.assertRaises(ClientStageFailure) as caught:
            run.run()
        self.assertEqual(caught.exception.stage, 'SETUP')
        d.adb.tap.assert_not_called()

    def test_different_entity_pick_stops_after_one_input(self):
        run, d = self.exercise()
        d._on_connection.return_value = True
        def receive(predicate, *_args, **_kw):
            row = {'direction': 'c2s', 'opcode': 1060, 'payload': '000005ef0000'}
            return row if predicate(row) else None
        d.tail.wait_for.side_effect = receive
        actor = {'eid': 1517, 'selection_center_xyz': [2,0,-2], 'selection_height': 0}
        with self.assertRaises(ClientStageFailure) as caught:
            run.target(CAMERA, actor)
        self.assertEqual(caught.exception.stage, 'CLIENT_INPUT_OBSERVED')
        d.adb.tap.assert_called_once_with(480,270)
        self.assertEqual(run.counts['target'], 0)
        self.assertEqual(d.gesture.call_args.args[0], 'classic-target-attempt')

    def test_observed_target_request_without_ack_is_not_accepted(self):
        run, d = self.exercise()
        d.tail.wait_for.side_effect = [{'time': 1, 'payload': '000005ed0000'}, None]
        with self.assertRaises(ClientStageFailure) as caught:
            run.target(CAMERA, {'eid': 1517, 'selection_center_xyz': [2,0,-2], 'selection_height': 0})
        self.assertEqual(caught.exception.stage, 'SERVER_ACKNOWLEDGED')
        d.adb.tap.assert_called_once()
        self.assertEqual(run.counts['target'], 0)

    def test_lane_policy_records_actual_eligible_enemy_in_overlapping_pick(self):
        run, d = self.exercise()
        d._on_connection.return_value = True
        requested = {'eid': 1517, 'selection_center_xyz': [2,0,-2], 'selection_height': 0}
        actual = dict(requested, eid=1519)
        request = {'direction': 'c2s', 'opcode': 1060, 'payload': '000005ef0000', 'time': 1}
        ack = {'direction': 's2c', 'opcode': 1045, 'payload': '000005dc000005ef0000', 'time': 2}
        def receive(predicate, *_args, **_kw):
            row = request if d.tail.wait_for.call_count == 1 else ack
            self.assertTrue(predicate(row))
            return row
        d.tail.wait_for.side_effect = receive
        run.observer.selected_target.return_value = {'target_eid':1519}
        run.target(CAMERA, requested, eligible={1517:requested, 1519:actual})
        self.assertEqual(run.last_target, 1519)
        self.assertEqual(d.gesture.call_args.kwargs['target']['eid'], 1519)
        self.assertEqual(d.gesture.call_args.kwargs['projected_target']['eid'], 1517)

    def test_lane_policy_cannot_accept_unqualified_or_friendly_target(self):
        run, d = self.exercise()
        d._on_connection.return_value = True
        requested = {'eid': 1517, 'selection_center_xyz': [2,0,-2], 'selection_height': 0}
        def receive(predicate, *_args, **_kw):
            row = {'direction': 'c2s', 'opcode': 1060, 'payload': '000005eb0000'}  # ally1515
            self.assertFalse(predicate(row))
            return None
        d.tail.wait_for.side_effect = receive
        with self.assertRaises(ClientStageFailure):
            run.target(CAMERA, requested, eligible={1517:requested})
        self.assertEqual(run.counts['target'], 0)

    def test_concurrent_native_and_wire_target_death_is_classified_not_accepted(self):
        run, d = self.exercise()
        actor = {'eid':1517, 'selection_center_xyz':[2,0,-2], 'selection_height':0}
        d._on_connection.return_value = True
        d.tail.wait_for.side_effect = [{'time':100.02,'payload':'000005ed0000'}, None]
        d.tail.records = [{'time':100.03, 'direction':'s2c', 'opcode':1072, 'payload':'000005ed000005ee000000000000'}]
        run.observer.actor_states.return_value = {'missing':[], 'actors':[{'eid':1517,'hp':0}]}
        with patch('Tools.classic_client.time.time', return_value=100):
            run.target(CAMERA, actor, eligible={1517:actor})
        self.assertEqual(run.counts['target'], 0)
        self.assertEqual(run.counts['target_race'], 1)
        d.adb.tap.assert_called_once()
        self.assertFalse(d.gesture.call_args.kwargs['acknowledged'])

    def test_later_or_unknown_target_death_cannot_excuse_missing_ack(self):
        for death_time, native_hp in ((101,0), (100.03,100)):
            run, d = self.exercise()
            actor = {'eid':1517, 'selection_center_xyz':[2,0,-2], 'selection_height':0}
            d._on_connection.return_value = True
            d.tail.wait_for.side_effect = [{'time':100.02,'payload':'000005ed0000'}, None]
            d.tail.records = [{'time':death_time,'direction':'s2c','opcode':1072,'payload':'000005ed000005ee000000000000'}]
            run.observer.actor_states.return_value = {'missing':[], 'actors':[{'eid':1517,'hp':native_hp}]}
            with patch('Tools.classic_client.time.time', return_value=100), self.assertRaises(ClientStageFailure):
                run.target(CAMERA, actor, eligible={1517:actor})
            self.assertEqual(run.counts['target_race'],0)

    def test_owner_death_after_ack_is_interruption_not_presented_attack(self):
        run,d=self.exercise()
        actor={'eid':1517,'selection_center_xyz':[2,0,-2],'selection_height':0}
        d._on_connection.return_value=True
        d.tail.wait_for.side_effect=[{'time':100.02,'payload':'000005ed0000'},
                                     {'time':100.03,'payload':'000005dc000005ed0000'}]
        d.tail.records=[{'time':100.04,'direction':'s2c','opcode':1072,'payload':'000005dc000005ed000000000000'}]
        run.observer.selected_target.return_value={'target_eid':None}
        run.observer.actor_states.return_value={'missing':[],'actors':[{'eid':1500,'hp':.00001}]}
        with patch('Tools.classic_client.time.time',return_value=100):
            run.target(CAMERA,actor,eligible={1517:actor})
        self.assertEqual(run.counts['target'],0)
        self.assertEqual(run.counts['target_interrupted'],1)
        self.assertIn('ack',d.gesture.call_args.kwargs)
        d.adb.tap.assert_called_once()

    def test_legal_upgrade_gates_and_death(self):
        owner = {'alive': True, 'ability_points': 1, 'level': 5, 'ranks': {'0': 3, '1': 3, '2': 0}}
        self.assertIsNone(next_upgrade(owner))
        self.assertEqual(next_upgrade(dict(owner, level=6)), 2)
        self.assertIsNone(next_upgrade(dict(owner, alive=False, level=12)))

    def test_result_transition_requires_complete_later_tree_without_input(self):
        run,d=self.exercise()
        settled={'root':'0x1000','nodes':625,'labels':['Defeat','FINISH']}
        run.observer.ui_state.side_effect=[RuntimeError('native UI cycle/node limit'),settled]
        with patch('Tools.classic_client.time.sleep'):
            self.assertEqual(run.fresh_ui_state(),settled)
        self.assertEqual(len(d.observations['ui_read_gaps']),1)
        d.adb.tap.assert_not_called()
        d.adb.back.assert_not_called()

    def test_persistent_or_unrelated_ui_failure_is_not_an_empty_valid_tree(self):
        for error in ('native UI cycle/node limit','invalid native label'):
            run,d=self.exercise()
            run.observer.ui_state.side_effect=RuntimeError(error)
            with patch('Tools.classic_client.time.sleep'),self.assertRaises(Exception):
                run.fresh_ui_state()
            self.assertEqual(run.observer.ui_state.call_count,20 if 'cycle' in error else 1)
            d.adb.tap.assert_not_called()

    def test_hud_guard_uses_complete_bounded_reader_not_a_second_unguarded_traversal(self):
        from Tools.scenario_client import ClientDriver
        run,d=self.exercise()
        hud={'root':'0x1000','nodes':300,'labels':['BUY:','1:55']}
        run.observer.ui_state.side_effect=[RuntimeError('native UI cycle/node limit'),hud]
        with patch('Tools.classic_client.time.sleep'):
            ClientDriver._guard_nonvisual_movement_ui(
                d,run.observer,state_reader=run.fresh_ui_state)
        self.assertEqual(run.observer.ui_state.call_count,2)
        self.assertEqual(d.observations['native_ui_guards'][-1]['before'],hud)
        d.adb.tap.assert_not_called()
        d.adb.back.assert_not_called()

    def test_shop_transition_wait_never_accepts_unknown_tree_or_repeats_back(self):
        run, d = self.exercise()
        hud = {'root':'0x1000', 'nodes':100, 'labels':['BUY:', '1:00']}
        shop = dict(hud, labels=hud['labels']+['BACKPACK (DRAG TO RE-ORDER)'])
        run.observer.ui_state.side_effect = [RuntimeError('native UI cycle/node limit'), shop, hud, hud]
        with patch('Tools.classic_client.time.sleep'):
            run.settle_shop_closed()
        self.assertEqual(run.observer.ui_state.call_count,4)
        self.assertIn('unknown',d.observations['shop_close_reads'][0][0])
        d.adb.back.assert_not_called()
        d.adb.tap.assert_not_called()

    def test_dirty_camera_requires_a_later_qualified_read_and_fresh_actors(self):
        run, d = self.exercise()
        run.observer.camera_view.side_effect = [RuntimeError('camera matrices dirty/absent'), CAMERA]
        run.observer.actor_states.return_value = {'actors':[]}
        with patch('Tools.classic_client.time.sleep'):
            camera, actors = run.fresh_camera_actors([1517])
        self.assertEqual(camera,CAMERA)
        run.observer.actor_states.assert_called_once_with([1517])
        self.assertEqual(len(d.observations['camera_read_gaps']),1)
        d.adb.tap.assert_not_called()

    def test_level_up_ui_requires_enabled_native_upgrade_control_before_tap(self):
        run, d = self.exercise()
        run.observer.ability_control.side_effect = [RuntimeError('ability control absent, ambiguous or changed'),
                                                   {'eid':1500,'center':[480,270]}]
        d.tail.wait_for.return_value = {'payload':'000000000000','time':1}
        d.qa.snapshot.return_value = {'heroes':[{'eid':1500,'hero_id':265,'ranks':{'0':3}}]}
        with patch('Tools.classic_client.time.sleep'):
            run.upgrade({'ranks':{'0':2}},0)
        d.adb.tap.assert_called_once_with(480,270)
        self.assertEqual(run.counts['upgrade'],1)
        self.assertEqual(len(d.observations['upgrade_control_waits']),1)

    def test_persistent_dirty_camera_or_wrong_owner_stays_unqualified(self):
        for error in ('camera matrices dirty/absent','camera input owner not qualified'):
            run, d = self.exercise()
            run.observer.camera_view.side_effect = RuntimeError(error)
            with patch('Tools.classic_client.time.sleep'), self.assertRaises(Exception):
                run.fresh_camera_actors([1517])
            self.assertEqual(run.observer.camera_view.call_count,8 if 'dirty' in error else 1)
            run.observer.actor_states.assert_not_called()
            d.adb.tap.assert_not_called()

    def test_move_ack_uses_verified_compact_slot_not_entity_id(self):
        run, d = self.exercise()
        from server.roster import build_move_intent
        run.slot = 3  # Deliberately not the familiar slot0.
        run.mesh = Mock()
        run.mesh.height_at.return_value = 0
        d._on_connection.return_value = True
        request = {'direction': 'c2s', 'opcode': 1012, 'payload': '00'*14, 'time': 10}
        def receive(predicate, *_args, **_kw):
            if d.tail.wait_for.call_count == 1:
                self.assertTrue(predicate(request))
                return request
            for slot in (0, 3):
                row = {'direction': 's2c', 'opcode': 1016, 'payload': build_move_intent(slot, 2, -2).hex(), 'time': 11}
                self.assertEqual(predicate(row), slot == 3)
            return row
        d.tail.wait_for.side_effect = receive
        with patch('Tools.classic_client.path_step', return_value=(2,-2)):
            run.move(CAMERA, (2,-3), (2,-2))
        self.assertEqual(run.counts['move'], 1)

    def test_bounded_route_goal_respects_segment_distance(self):
        mesh = Mock()
        mesh.find_path.return_value = [(0,0), (3,0), (3,4)]
        self.assertEqual(path_step(mesh, (0,0), (3,4), 4), (3,1))
        self.assertEqual(path_step(mesh, (0,0), (3,4), 10), (3,4))
        mesh.find_path.return_value = []
        with self.assertRaises(ValueError):
            path_step(mesh, (0,0), (3,4))

    def test_click_endpoint_snaps_only_within_quantization_bound(self):
        mesh = Mock()
        mesh.height_at.return_value = 0.5
        self.assertEqual(on_mesh_click(mesh, (1.0, 2.0)), ((1.0, 2.0), 0.5, 0.0))
        mesh.nearest_point.assert_not_called()
        mesh.height_at.side_effect = [ValueError('height query must be on the navigation mesh'), 0.25]
        mesh.nearest_point.return_value = (1.0, 2.0000005)
        point, height, gap = on_mesh_click(mesh, (1.0, 2.0))
        self.assertEqual((point, height), ((1.0, 2.0000005), 0.25))
        self.assertAlmostEqual(gap, 5e-7)
        mesh.height_at.side_effect = ValueError('height query must be on the navigation mesh')
        mesh.nearest_point.return_value = (1.0, 2.01)
        with self.assertRaises(ValueError):
            on_mesh_click(mesh, (1.0, 2.0))

    def test_retained_c_4m_click_endpoint_snaps_on_owned_mesh(self):
        from server import navigation
        try:
            mesh = navigation.load_halcyon_navmesh()
        except (FileNotFoundError, OSError) as exc:
            self.skipTest(f'owned navmesh unavailable: {exc}')
        point = (-37.02497394895754, -1.2446980794459082)
        with self.assertRaises(ValueError):
            mesh.height_at(point)
        snapped, height, gap = on_mesh_click(mesh, point)
        self.assertLess(gap, 2e-6)
        self.assertEqual(mesh.height_at(snapped), height)

    def test_arrival_near_first_lane_waypoint_advances_to_objective(self):
        self.assertEqual(lane_goal((-65.694, 11.034), {'x':17.06, 'y':1.93}, 1), (13.059999999999999, 5.5))
        self.assertEqual(lane_goal((65.694, 11.034), {'x':-17.06, 'y':1.93}, 2), (-13.059999999999999, 5.5))


if __name__ == '__main__':
    unittest.main()

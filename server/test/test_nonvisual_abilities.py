"""Client ability gate requires native effects, never server-only success."""
import copy
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from Tools import scenario_client as sc
from Tools.Teardown import observe_client_movement as obs
from server.sandbox_qa import validate_command


class NonvisualAbilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.adb = Mock()
        self.adb.screencap.side_effect = AssertionError('images forbidden')
        self.qa = Mock(receipts=[], qa_dir=str(self.output / 'qa'))
        self.qa.submit.side_effect = lambda command, **kw: (validate_command(command), {'ok': True})[1]
        self.driver = sc.ClientDriver('skye-a', adb=self.adb, qa=self.qa,
            tail=Mock(records=[]), connection=77, profile=copy.deepcopy(sc.DEFAULT_PROFILE),
            out_dir=self.output, timeout=2)
        d = self.driver
        d._qualify_nonvisual_world = Mock(return_value=(1500, 0, 265))
        d.setup = Mock(return_value={'snapshot': {'match_id': 'test-match'}})
        d.start_capture = Mock(side_effect=AssertionError('recording forbidden'))
        d.capture_frame = Mock(side_effect=AssertionError('images forbidden'))
        d._guard_nonvisual_movement_ui = Mock()
        d._foreground_package = Mock(return_value=sc.ANDROID_PACKAGE)
        self.owner = dict(eid=1500, alive=True, statuses=[], ranks={'0': 1, '1': 1, '2': 1},
            level=6, ability_points=0, ability_cooldowns={}, hp=1000, energy=500, x=0, y=38)
        self.enemy = dict(eid=1517, alive=True, statuses=[], hp=1000, energy=500, x=4, y=38)
        d.skye = Mock(side_effect=lambda: self.owner)
        d.enemy = Mock(side_effect=lambda: self.enemy)
        d.refresh_rows = Mock(side_effect=self.refresh)
        d.wait_client_input = Mock(return_value={'time': time.time()})
        d.wait_acknowledgment = Mock()
        d.wait_cooldown_tag = Mock()
        d.classify_damage = Mock(return_value={'attributed': [{'delta': -100}]})
        d.collect_endpoint_linkage = Mock(return_value={'tick': 200})
        d._diag_linkage = {'tick': 100}
        self.owner_obs = Mock(errors=[], output=self.output / 'owner.jsonl')
        self.target_obs = Mock(errors=[], output=self.output / 'target.jsonl')
        for observer in (self.owner_obs, self.target_obs):
            observer.start.return_value = {'pid': 42}
            observer.stop.return_value = {'errors': [], 'samples': 12}
        self.owner_obs.camera_control.return_value = {'eid': 1500, 'locked': True, 'center': [880, 92]}
        self.owner_obs.selected_target.return_value = {'eid':1500,'target_eid':1517}
        self.owner_obs.movement_modifiers.return_value = {'eid':1500,'components':[]}
        self.qa.snapshot.side_effect = lambda: {'heroes':[self.owner,self.enemy]}
        self.owner_obs.ability_control.side_effect = lambda slot, **kw: dict(
            eid=1500, slot=slot, action=slot*2, center=[407+73*slot, 442 if kw else 493])
        self.owner_values = [self.value(1000, 500)] + [self.value(1000, 460) for _ in range(3)]
        self.target_values = [self.value(1000, 500)] + [self.value(900, 500) for _ in range(4)]
        self.owner_obs.resources.side_effect = self.owner_values
        self.target_obs.resources.side_effect = self.target_values
        self.owner_obs.snapshot.return_value = {'position_xyz': [0, .01, 38]}
        self.target_obs.snapshot.return_value = {'position_xyz': [4, .01, 38]}
        self.enterContext(patch.object(obs, 'ClientMovementObserver', side_effect=[self.owner_obs, self.target_obs]))
        self.enterContext(patch.object(sc.time, 'sleep'))
        self.enterContext(patch.object(sc.time, 'monotonic', side_effect=[0, 0, 10]))

    @staticmethod
    def value(hp, energy):
        return {'max_hp': 1000, 'max_energy': 500,
                'current': {'hp': hp, 'energy': energy, 'barrier': 0, 'fortified': 0}}

    def refresh(self):
        if self.driver.refresh_rows.call_count == 4:
            self.owner = self.owner | {'energy': 460, 'ability_cooldowns': {'0': 5, '1': 8, '2': 50}}
            self.enemy = self.enemy | {'hp': 900}
        return {'match_id': 'test-match', 'tick': 100, 'heroes': [self.owner, self.enemy]}

    def tearDown(self):
        self.adb.screencap.assert_not_called()
        self.driver.start_capture.assert_not_called()
        self.driver.capture_frame.assert_not_called()

    def reject(self, stage, slot='A'):
        with self.assertRaises(sc.ClientStageFailure) as caught:
            self.driver.run_nonvisual_cast(slot)
        self.assertEqual(caught.exception.stage, stage)

    def test_native_resources_required_for_success_and_animation_left_unknown(self):
        result = self.driver.run_nonvisual_cast('A')
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['observed']['model_animation'], 'UNVERIFIED')
        self.assertEqual(result['observed']['compare_pair'], 'NOT_RUN')
        self.adb.swipe.assert_called_once()

    def test_pursuit_diagnostic_may_outlast_the_already_observed_cast_cooldown(self):
        self.driver.profile['nonvisual_cast']={'pursuit_target_position':[12,38]}
        self.driver.tail.wait_for.return_value={'time':time.time()}
        def delayed_probe(*args):
            self.owner=self.owner|{'energy':500,'ability_cooldowns':{'0':0,'1':0,'2':0}}
            for value in self.owner_values[2:]:value['current']['energy']=500
        self.driver._observe_post_cast_pursuit=Mock(side_effect=delayed_probe)
        result=self.driver.run_nonvisual_cast('A')
        self.assertEqual(result['status'],'PASS')
        self.assertGreater(self.driver.observations['post_ability_selection']['state']['heroes'][0]['ability_cooldowns']['0'],0)
        self.assertEqual(self.owner['ability_cooldowns']['0'],0)

    def pursuit_trial(self, *, flags, gap, model_gap=None):
        initial={'time':100,'heroes':[self.owner|{'target':1517},self.enemy]}
        states=[{'time':100+i*.1,'heroes':[self.owner|{'x':i*.4,'target':1517},self.enemy]}
                for i in range(1,6)]
        self.qa.snapshot.side_effect=[initial]+states
        samples=[]
        for state in states:
            x=state['heroes'][0]['x']-gap
            model_x=state['heroes'][0]['x']-(gap if model_gap is None else model_gap)
            samples += [{'position_xyz':[x,0,38],'navigation_flags':flags,
                         'model':{'translation_xyz':[model_x,0,38]}}]*2
        self.owner_obs.snapshot.side_effect=samples
        self.target_obs.snapshot.return_value={'position_xyz':[12,0,38]}
        with patch.object(sc.time,'monotonic',side_effect=[0,0,.1,.2,.3,.4,4]):
            self.driver._observe_post_cast_pursuit(self.owner_obs,self.target_obs,1500,1517,[12,38])

    def test_pursuit_server_progress_and_correction_only_native_motion_cannot_pass(self):
        with self.assertRaises(sc.ClientStageFailure) as caught:
            self.pursuit_trial(flags=0,gap=0)
        self.assertEqual(caught.exception.stage,'PRESENTATION')
        self.assertIn('never activated',caught.exception.detail)
        self.assertEqual(self.driver.observations['post_cast_pursuit']['native_active_moving_rows'],0)
        self.adb.tap.assert_not_called()

    def test_pursuit_native_route_with_large_gap_still_fails(self):
        with self.assertRaises(sc.ClientStageFailure) as caught:
            self.pursuit_trial(flags=1,gap=1.56)
        self.assertEqual(caught.exception.stage,'PRESENTATION')
        self.assertIn('gap bound',caught.exception.detail)

    def test_pursuit_motion_cannot_hide_cleared_native_selection(self):
        self.owner_obs.selected_target.side_effect=[{'target_eid':1517}]+[{'target_eid':None}]*5
        with self.assertRaises(sc.ClientStageFailure) as caught:
            self.pursuit_trial(flags=1,gap=.05)
        self.assertEqual(caught.exception.stage,'PRESENTATION')
        self.assertIn('selected target',caught.exception.detail)

    def test_logical_agreement_cannot_hide_divergent_root_model(self):
        with self.assertRaises(sc.ClientStageFailure) as caught:
            self.pursuit_trial(flags=1,gap=.05,model_gap=1.2)
        self.assertEqual(caught.exception.stage,'PRESENTATION')
        self.assertIn('root-model',caught.exception.detail)

    def test_pursuit_qualification_retains_scope_and_measured_gap(self):
        self.pursuit_trial(flags=1,gap=.18)
        report=self.driver.observations['post_cast_pursuit']
        self.assertEqual(report['server_moving_rows'],5)
        self.assertEqual(report['native_active_moving_rows'],5)
        self.assertAlmostEqual(report['max_moving_gap'],.18)
        self.assertIn('not ordinary match',report['scope'])

    def test_refresh_preserves_setup_enemy_instead_of_switching_to_first_corpse(self):
        chosen=self.enemy|{'eid':1518,'team':2}
        self.driver._enemy=chosen
        self.driver._enemy_eid=1518
        owner=self.owner|{'hero_id':265,'team':1}
        self.qa.snapshot.side_effect=None
        self.qa.snapshot.return_value={'phase':'world','match_finished':False,
            'heroes':[owner,self.enemy|{'team':2,'alive':False},chosen]}
        sc.ClientDriver.refresh_rows(self.driver)
        self.assertEqual(self.driver._enemy['eid'],1518)
        # Losing that actor is an explicit missing fixture, not permission
        # to silently switch damage/lock attribution to a different enemy.
        self.qa.snapshot.return_value['heroes']=[owner,self.enemy|{'team':2},chosen|{'alive':False}]
        sc.ClientDriver.refresh_rows(self.driver)
        self.assertIsNone(self.driver._enemy)
        self.assertEqual(self.driver._enemy_eid,1518)

    def test_matching_server_damage_cannot_hide_wrong_native_target_hp(self):
        for v in self.target_values[1:]:
            v['current']['hp'] = 930
        self.reject('PRESENTATION')
        self.assertEqual(self.driver.stages['AUTHORITATIVE_EFFECT']['status'], 'PASS')

    def test_native_target_stranded_after_correction_stops_before_combat_input(self):
        self.target_obs.snapshot.return_value = {'position_xyz': [15.323611, .021, 29.2734375]}
        self.reject('SETUP')
        self.adb.tap.assert_not_called()
        self.adb.swipe.assert_not_called()

    def test_server_consumption_cannot_hide_unchanged_native_energy(self):
        for v in self.owner_values[1:]:
            v['current']['energy'] = 500
        self.reject('PRESENTATION')

    def test_natural_level_growth_does_not_hide_native_damage_fraction(self):
        original = self.driver.refresh_rows.side_effect
        def level_during_cast():
            state = original()
            if self.driver.refresh_rows.call_count == 4:
                self.enemy['hp'] = 1125
            return state
        self.driver.refresh_rows.side_effect = level_during_cast
        for value in self.target_values[1:]:
            value.update(max_hp=1200)
            value['current']['hp'] = 1125
        result = self.driver.run_nonvisual_cast('A')
        self.assertEqual(result['status'], 'PASS')

    def test_level_growth_without_damage_fraction_cannot_pass_native_gate(self):
        for value in self.target_values[1:]:
            value.update(max_hp=1200)
            value['current']['hp'] = 1200
        self.reject('PRESENTATION')

    def test_missing_target_lock_never_casts_or_retries(self):
        self.driver.tail.wait_for.return_value = None
        self.reject('CLIENT_INPUT_OBSERVED', 'B')
        self.adb.tap.assert_called_once()
        self.adb.swipe.assert_not_called()

    def test_no_legal_ultimate_rank_does_not_force_learning(self):
        self.owner.update(level=5, ranks={'2': 0}, ability_points=1)
        self.reject('SETUP', 'C')
        self.qa.submit.assert_not_called()
        self.adb.tap.assert_not_called()

    def test_upgrade_without_real_wire_input_stops_after_one_tap(self):
        self.owner.update(ranks={'0': 0}, ability_points=1)
        self.driver.tail.wait_for.return_value = None
        self.reject('SETUP')
        self.adb.tap.assert_called_once()
        self.adb.swipe.assert_not_called()

    def test_failed_camera_toggle_does_not_start_combat_setup(self):
        self.owner_obs.camera_control.return_value = {'eid': 1500, 'locked': False, 'center': [880, 92]}
        self.reject('SETUP')
        self.adb.tap.assert_called_once_with(880, 92)
        self.qa.submit.assert_not_called()

    def test_controlled_undeclared_fixture_refuses_before_unlocked_camera_gesture(self):
        self.owner.update(ranks={'0': 0}, ability_points=1)
        self.owner_obs.camera_control.return_value = {'eid': 1500, 'locked': False, 'center': [880, 92]}
        with self.assertRaises(sc.ClientStageFailure) as caught:
            self.driver.run_nonvisual_cast('A', controlled=True)
        self.assertEqual(caught.exception.stage, 'SETUP')
        self.assertIn('undeclared', caught.exception.detail)
        self.adb.tap.assert_not_called()
        self.adb.swipe.assert_not_called()
        self.owner_obs.camera_control.assert_not_called()
        self.driver._guard_nonvisual_movement_ui.assert_called_once_with(self.owner_obs)


if __name__ == '__main__':
    unittest.main()

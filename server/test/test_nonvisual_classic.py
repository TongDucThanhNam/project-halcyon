"""Ordinary match driver must not turn setup/input uncertainty into a pass."""
import unittest
from unittest.mock import Mock, patch

from Tools.classic_client import (ClassicMatchExercise, central_projection, next_upgrade,
                                 path_step, lane_goal, recent_target_lock, next_purchase,
                                 recall_needed)
from Tools.scenario_client import ClientStageFailure


CAMERA = {'view': [1,0,0,0, 0,1,0,0, 0,0,1,0, -2,0,0,1],
          'projection': [1,0,0,0, 0,1,0,0, 0,0,-11/9,-1, 0,0,-20/9,0],
          'dimensions': [960,540]}


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

    def test_arrival_near_first_lane_waypoint_advances_to_objective(self):
        self.assertEqual(lane_goal((-65.694, 11.034), {'x':17.06, 'y':1.93}, 1), (13.059999999999999, 5.5))
        self.assertEqual(lane_goal((65.694, 11.034), {'x':-17.06, 'y':1.93}, 2), (-13.059999999999999, 5.5))


if __name__ == '__main__':
    unittest.main()

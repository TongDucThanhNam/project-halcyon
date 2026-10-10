"""Qualified menu receipts and two-client admission fail closed before input."""
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from Tools import native_ui as ui
from Tools import nonvisual_entry as entry
from Tools import scenario_client as sc


def tree(label='PLAY', stage='MENU', y=200):
    markers = {'MENU': [], 'MODE': ['SOLO BOTS'], 'MAP': ['3V3'], 'DIFFICULTY': ['VERY EASY'],
               'DRAFT': ['Lock in a hero!'], 'LOCKED': ['LOCKED IN'], 'BUILD': ['Choose a Build'],
               'SHOP': ['BACKPACK (DRAG TO RE-ORDER)'], 'HUD': ['BUY:', '0:20']}
    button = {'address': 'button', 'parent': 'root', 'child': 'label', 'next': '0x0',
              'flags': 28, 'vtable': '0x26d2928',
              'events': [{'type': 10712282, 'words': ['0x1', 'button', '0x0', '0x0', '0x109']}],
              'bounds_method': '0xe02010', 'local_bounds': '0xe020b4', 'size_method': '0xe13e54',
              'origin': [400, y], 'anchor': [.5, .5], 'scale': [1, 1], 'size': [150, 50],
              'clip': [100, 80, 800, 450]}
    text = {**button, 'address': 'label', 'parent': 'button', 'child': '0x0', 'text': label, 'events': []}
    root = {**button, 'address': 'root', 'parent': '0x0', 'flags': 12, 'events': [],
            'origin': [0, 0], 'anchor': [0, 0], 'size': [960, 540], 'clip': [0, 0, 960, 540]}
    labels = list(dict.fromkeys([*markers[stage], label]))
    return {'root': 'root', 'nodes': [button, text, root], 'labels': labels,
            'traversal': {'visited': 3, 'active': 3, 'duration_ms': .2, 'node_limit': 4096,
                          'complete': True, 'root_unchanged': True},
            'host_read_started': time.monotonic(), 'host_read_ended': time.monotonic()}


def wire_binding(connection=7, identity='guest-a', eid=1500, slot=0, team=1, at=10):
    return [{'time': at, 'direction': 'identity', 'opcode': 1000, 'payload': '',
             'connection': connection, 'identity': identity, 'eid': eid, 'slot': slot,
             'team': team, 'match_id': 'match', 'phase': 'PICK'},
            {'time': at, 'direction': 's2c', 'opcode': 1001, 'payload': f'{eid:08x}'+'00'*98,
             'connection': connection},
            {'time': at+1, 'direction': 's2c', 'opcode': 1118, 'payload': '00000109', 'connection': connection}]


class NativeReceiptTests(unittest.TestCase):
    def test_active_label_has_code_qualified_click_ancestor(self):
        state = tree()
        receipt = ui.control_receipt(state, 'PLAY', 'MENU')
        self.assertEqual(receipt['center'], [400, 200])
        self.assertEqual(receipt['ancestors'], ['label', 'button'])
        ui.require_unchanged(receipt, copy.deepcopy(state))

    def test_negative_controls_never_produce_receipt(self):
        cases = {
            'duplicate': lambda s: s['nodes'].append({**s['nodes'][1], 'address': 'other'}),
            'stale': lambda s: s.update(host_read_started=time.monotonic()-2),
            'clipped': lambda s: s['nodes'][0].update(clip=[0, 0, 300, 540]),
            'offscreen': lambda s: s['nodes'][0].update(origin=[1000, 200]),
            'nonfinite': lambda s: s['nodes'][0].update(origin=[float('nan'), 200]),
            'inactive': lambda s: s['nodes'][0].update(flags=0),
            'disabled': lambda s: s['nodes'][0].update(flags=12),
            'missing_click': lambda s: s['nodes'][0].update(events=[]),
            'unknown_screen': lambda s: s.update(labels=['Unidentified']),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                state = tree()
                mutate(state)
                with self.assertRaises(ValueError):
                    ui.control_receipt(state, 'PLAY', 'MENU')

    def test_tree_mutation_between_read_and_tap_is_refused(self):
        state = tree()
        receipt = ui.control_receipt(state, 'PLAY', 'MENU')
        state['nodes'][0]['origin'][0] += 1
        with self.assertRaisesRegex(ValueError, 'mutation'):
            ui.require_unchanged(receipt, state)

    def test_premature_hud_is_loading_even_when_clock_and_buy_exist(self):
        state = tree(stage='HUD')
        state['labels'].append('Prepare For Battle... 1')
        self.assertEqual(ui.screen(state), 'LOADING')

    def test_mode_chooser_3v3_card_is_not_the_solo_bots_map_page(self):
        state = tree('SOLO BOTS', 'MODE')
        state['labels'] += ['3V3', '5V5', 'PRACTICE']
        self.assertEqual(ui.screen(state), 'MODE')
        self.assertEqual(ui.screen(tree('3V3', 'MAP')), 'MAP')

    def test_exact_bootstrap_connecting_is_not_a_qualified_menu(self):
        state = tree()
        state['labels'] = ['CONNECTING']
        self.assertEqual(ui.screen(state), 'BOOTSTRAP')
        with self.assertRaisesRegex(ValueError, 'unexpected native screen'):
            ui.control_receipt(state, 'PLAY', 'MENU')

    def test_retiring_mode_cards_are_read_only_transition_not_actionable_menu(self):
        state = tree()
        state['labels'] = ['Guest', 'PLAY', 'BAG', 'PLAY', '5V5', '25 MIN', 'BLITZ', '5 MIN']
        self.assertEqual(ui.screen(state), 'MENU_TRANSITION')
        with self.assertRaisesRegex(ValueError, 'unexpected native screen'):
            ui.control_receipt(state, 'PLAY', 'MENU')
        state['labels'].append('Unidentified dialog')
        self.assertEqual(ui.screen(state), 'UNKNOWN')

    def test_wrong_hero_callback_is_not_a_selection_receipt(self):
        with self.assertRaisesRegex(ValueError, 'hero callback'):
            ui.control_receipt(tree('Skye', 'DRAFT'), 'Skye', 'DRAFT', hero_id=925)

    def test_waiting_roster_is_read_only_and_rejects_unknown_or_missing_labels(self):
        state = tree('LOCK IN', 'DRAFT')
        state['labels'] = sorted(ui.DRAFT_WAIT_MARKERS) + ['Skye', 'Amael', 'Amael']
        self.assertEqual(ui.screen(state), 'DRAFT_WAIT')
        for expected in ('DRAFT', 'DRAFT_WAIT'):
            with self.assertRaisesRegex(ValueError, 'read-only transition'):
                ui.control_receipt(state, 'LOCK IN', expected)
        for added in ('Unidentified dialog', 'Lock in a hero!', 'LOCKED IN', 'Settings',
                      'Waiting for Players...', 'PLAY', 'VERY EASY'):
            with self.subTest(added=added):
                changed = copy.deepcopy(state)
                changed['labels'].append(added)
                self.assertEqual(ui.screen(changed), 'UNKNOWN')
        for missing in ui.DRAFT_WAIT_MARKERS - {'Waiting for Players...'}:
            with self.subTest(missing=missing):
                changed = copy.deepcopy(state)
                changed['labels'].remove(missing)
                self.assertEqual(ui.screen(changed), 'UNKNOWN')

    def test_read_gaps_are_bounded_without_input(self):
        observer, gaps = Mock(), []
        observer.ui_state.side_effect = RuntimeError('native UI root changed')
        with patch.object(ui.time, 'sleep'), self.assertRaisesRegex(ValueError, 'did not settle'):
            ui.fresh_ui_state(observer, gaps.append)
        self.assertEqual(len(gaps), 20)
        self.assertEqual(observer.ui_state.call_count, 20)


class IdentityAndAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.device = {'device_tag': 'A', 'listener_port': 9443, 'guest_id': 'guest-a'}
        self.rpc = [{'t': 10, 'method': 'startSessionForPlayer', **self.device, 'match_identities': ['guest-a']}]
        self.guest = entry.guest_binding(self.rpc, self.device, 5)

    def test_wrong_guest_or_listener_does_not_bind(self):
        self.assertIsNone(entry.guest_binding(self.rpc, {**self.device, 'listener_port': 9444}, 5))
        with self.assertRaisesRegex(ValueError, 'wrong guest'):
            entry.guest_binding(self.rpc, {**self.device, 'guest_id': 'guest-b'}, 5)

    def test_newest_connection_is_never_used(self):
        rows = wire_binding() + wire_binding(connection=999, identity='guest-b', eid=1517, team=2, at=100)
        self.assertEqual(entry.connection_binding(rows, self.guest, 5)['connection'], 7)
        self.assertIsNone(entry.connection_binding(rows, {**self.guest, 'identities': ['absent']}, 5))

    def test_duplicate_active_connection_and_wrong_owner_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'ambiguous active'):
            entry.connection_binding(wire_binding()+wire_binding(connection=8), self.guest, 5)
        rows = wire_binding()
        rows[1]['payload'] = f'{1517:08x}'+'00'*98
        with self.assertRaisesRegex(ValueError, 'owner disagree'):
            entry.connection_binding(rows, self.guest, 5)

    def test_disconnected_draft_can_handoff_only_by_same_guest(self):
        rows = wire_binding() + [{'direction': 'disconnect', 'connection': 7}]
        rows += wire_binding(connection=8, at=20)
        self.assertEqual(entry.connection_binding(rows, self.guest, 5)['connection'], 8)

    def test_both_selected_opposite_guests_before_any_lock(self):
        peer = {'guest_id': 'guest-b', 'identities': ['guest-b']}
        guests = [self.guest, peer]
        a = wire_binding()
        self.assertIsNone(entry.admission_roster(a, guests, 5))
        rows = a + wire_binding(connection=8, identity='guest-b', eid=1517, slot=3, team=2, at=20)
        self.assertEqual([b['eid'] for b in entry.admission_roster(rows, guests, 5)], [1500, 1517])
        rows.append({'time': 15, 'direction': 'c2s', 'opcode': 1123, 'connection': 7})
        with self.assertRaisesRegex(ValueError, 'locked before'):
            entry.admission_roster(rows, guests, 5)


class PairQualificationTests(unittest.TestCase):
    def outside_node(self, state, *, x=30, parent='root'):
        node = {**state['nodes'][0], 'address': 'dynamic', 'parent': parent,
                'origin': [x, 30], 'size': [20, 20], 'events': []}
        state['nodes'].append(node)
        state['traversal'].update(visited=len(state['nodes']), active=len(state['nodes']))
        return node

    def test_outside_differences_are_permitted_and_fully_retained(self):
        a = tree()
        self.outside_node(a)
        b = copy.deepcopy(a)
        b['nodes'][-1]['flags'] = 8940
        b['nodes'][-1]['origin'][0] += 2
        receipt = ui.qualify_pair(a, b, 'PLAY', 'MENU')
        self.assertEqual(receipt['ancestors'], ['label', 'button', 'root'])
        pair = receipt['pair']
        self.assertEqual(pair['outside_difference_count'], 1)
        self.assertEqual(pair['outside_differences'], [{'address': 'dynamic', 'fields': {
            'flags': {'before': 28, 'after': 8940},
            'origin': {'before': [30, 30], 'after': [32, 30]}}}])
        self.assertNotEqual(pair['before_sha256'], pair['after_sha256'])

    def test_full_ancestry_flags_and_layout_are_protected(self):
        for field, value in (('flags', 8940), ('origin', [1, 0])):
            with self.subTest(field=field):
                a, b = tree(), tree()
                b['nodes'][2][field] = value
                with self.assertRaisesRegex(ui.ControlMutation, 'full ancestry') as failure:
                    ui.qualify_pair(a, b, 'PLAY', 'MENU')
                self.assertTrue(failure.exception.ancestry)

    def test_descendant_mutation_is_refused_even_outside_bounds(self):
        a = tree()
        self.outside_node(a, parent='button')
        b = copy.deepcopy(a)
        b['nodes'][-1]['flags'] = 8940
        with self.assertRaisesRegex(ui.ControlMutation, 'descendant'):
            ui.qualify_pair(a, b, 'PLAY', 'MENU')

    def test_overlap_in_either_read_is_refused(self):
        a = tree()
        self.outside_node(a)
        b = copy.deepcopy(a)
        b['nodes'][-1]['origin'] = [400, 200]
        for left, right in ((a, b), (b, a)):
            with self.subTest(reverse=left is b), self.assertRaisesRegex(ui.ControlMutation, 'overlapping'):
                ui.qualify_pair(left, right, 'PLAY', 'MENU')

    def test_unknown_size_never_proves_non_overlap(self):
        a = tree()
        n = self.outside_node(a)
        n.update(size_method='unknown', resolved_size=None)
        b = copy.deepcopy(a)
        b['nodes'][-1]['flags'] = 8940
        with self.assertRaisesRegex(ui.ControlMutation, 'overlapping'):
            ui.qualify_pair(a, b, 'PLAY', 'MENU')

    def test_incomplete_root_and_blocker_changes_are_refused(self):
        for change, message in ((lambda s: s['traversal'].update(complete=False), 'incomplete'),
                                (lambda s: s['traversal'].update(root_unchanged=False), 'incomplete'),
                                (lambda s: s['labels'].append('Settings'), 'root/screen/blocker')):
            with self.subTest(message=message):
                a, b = tree(), tree()
                change(b)
                with self.assertRaisesRegex(ValueError, message):
                    ui.qualify_pair(a, b, 'PLAY', 'MENU')


class EntryInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.d = sc.ClientDriver('movement-walk', adb=Mock(serial='A'), qa=sc._AbsentQa(), tail=Mock(),
            connection=None, profile={'nonvisual_entry': {'enabled': True, 'not_before': 5,
                'device_tag': 'A', 'listener_port': 9443, 'java_bridge': self.temp,
                'rpc_journal': str(Path(self.temp)/'rpc.jsonl'), 'wire_dir': self.temp,
                'input_lock': str(Path(self.temp)/'input.lock'), 'timeout_s': .01}},
            out_dir=Path(self.temp), timeout=1)
        self.d._foreground_package = Mock(return_value=sc.ANDROID_PACKAGE)
        self.observer = Mock()
        self.enterContext(patch.object(entry, 'ClientMovementObserver', return_value=self.observer))
        self.e = entry.NonvisualEntry(self.d)
        self.e.java = Mock()
        self.good_view = {'paused': False, 'window_focus': True, 'initialized': True, 'enabled': True}
        self.e.java.snapshot.return_value = {'rows': [self.good_view]}
        self.e.input_window = lambda: nullcontext()
        self.enterContext(patch.object(entry, 'wait_native_input_ready', return_value={'ready': True}))
        self.launch_ready = self.enterContext(patch.object(entry, 'wait_launch_ready', return_value={'ready': True}))
        self.e.plan['launch_guest_wall'] = 5
        self.e.plan['host_window'] = {'executable': 'owned', 'pid': 1}
        self.enterContext(patch.object(entry, 'qualify_owned_ldplayer', return_value={'hwnd': 1, 'pid': 1}))
        self.enterContext(patch.object(entry, 'require_owned_window', return_value={
            'hwnd': 1, 'pid': 1, 'after_foreground': {'hwnd': 2, 'pid': 2}}))
        self.state = tree()
        self.e.read = Mock(side_effect=lambda: {**copy.deepcopy(self.state), 'host_read_started': time.monotonic()})

    def assert_no_input(self, callback, detail):
        self.assert_setup_failure(callback, detail)
        self.d.adb.tap.assert_not_called()
        self.d.adb.swipe.assert_not_called()
        self.assertEqual(self.d.gestures, [])

    def assert_setup_failure(self, callback, detail):
        """Exercise production entry's failure boundary, not just a utility."""
        self.d.adb.client_version.return_value = {'version_name': '4.13.4', 'version_code': 147219}
        self.observer.start.return_value = {'mode': 'ui-only', 'ui': tree()}
        self.e.java.start.return_value = {'source_sha256': 'fixture'}
        wait = self.e.wait
        guest = {'guest_id': 'guest-a', 'identities': ['guest-a'], **self.e.device}
        def await_signal(name, predicate, **kwargs):
            return guest if name.startswith('bootstrap:') else wait(name, predicate, **kwargs)
        with patch.object(self.e, 'wait', side_effect=await_signal), \
                patch.object(self.e, 'wait_screen', side_effect=lambda *a, **k: callback()), \
                patch.object(sc, 'verify_resolution'), \
                self.assertRaisesRegex(sc.ClientStageFailure, detail) as failure:
            self.e.run()
        self.assertEqual(failure.exception.stage, 'SETUP')
        self.assertEqual(failure.exception.status, 'FAIL')

    def test_focus_loss_and_paused_activity_send_zero_gestures(self):
        for change in ({'window_focus': False}, {'paused': True}, {'initialized': False}):
            with self.subTest(change=change):
                self.e.java.snapshot.return_value = {'rows': [{**self.good_view, **change}]}
                self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'readiness absent')

    def test_missing_pre_attach_readiness_never_attaches_or_inputs(self):
        self.launch_ready.return_value = {'ready': False}
        self.assert_no_input(lambda: None, 'pre-attach.*readiness absent')
        self.observer.start.assert_not_called()
        self.e.java.start.assert_not_called()

    def test_unrestorable_minimized_window_before_gesture_latches_setup(self):
        self.e.input_window = entry.NonvisualEntry.input_window.__get__(self.e)
        self.e.plan['host_window'] = {'executable': 'owned', 'pid': 1}
        with patch.object(entry, 'qualify_owned_ldplayer', return_value={'hwnd': 1, 'pid': 1}), \
                patch.object(entry, 'require_owned_window', side_effect=ValueError('owned window minimized or absent')):
            self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'owned window minimized or absent')
            self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'prior input ownership failure')
        events = [r for r in self.e.events if r['stage'] == 'INPUT_LEASE']
        self.assertEqual([r['event'] for r in events], ['acquire', 'release'])

    def test_waits_and_admission_do_not_hold_host_input_lock(self):
        self.e.input_window = entry.NonvisualEntry.input_window.__get__(self.e)
        self.e.act('PLAY', 'MENU')
        def other_can_own():
            with entry.input_lease(self.e.plan['input_lock'], .2, owner='B') as check:
                check()
                return True
        self.assertTrue(self.e.wait('loading/countdown', other_can_own))
        self.e.rpc_rows = Mock(side_effect=lambda: (other_can_own() and []))
        with self.assertRaisesRegex(ValueError, 'both humans'):
            self.e.admission()
        self.assertTrue(other_can_own())

    def test_other_host_foreground_allows_qualified_guest_input(self):
        self.e.input_window = entry.NonvisualEntry.input_window.__get__(self.e)
        self.e.plan['require_background_play'] = True
        self.e.act('PLAY', 'MENU')
        self.d.adb.swipe.assert_called_once()
        host = self.d.gestures[0]['host_window']
        self.assertNotEqual(host['hwnd'], host['after_foreground']['hwnd'])

    def test_background_proof_never_manufactures_foreground_change(self):
        self.e.input_window = entry.NonvisualEntry.input_window.__get__(self.e)
        self.e.plan['require_background_play'] = True
        with patch.object(entry, 'require_owned_window', return_value={
                'hwnd': 1, 'pid': 1, 'after_foreground': {'hwnd': 1}}):
            self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'nonforeground proof')

    def test_missing_host_window_fails_before_input(self):
        self.e.input_window = entry.NonvisualEntry.input_window.__get__(self.e)
        del self.e.plan['host_window']
        self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'host window/PID required')

    def test_window_disappears_after_gesture_stops_without_second_input(self):
        self.e.input_window = entry.NonvisualEntry.input_window.__get__(self.e)
        self.e.plan['host_window'] = {'executable': 'owned', 'pid': 1}
        with patch.object(entry, 'qualify_owned_ldplayer', return_value={'hwnd': 1, 'pid': 1}), \
                patch.object(entry, 'require_owned_window', side_effect=[{'qualified': True},
                    ValueError('owned window minimized or absent')]):
            self.assert_setup_failure(lambda: self.e.act('PLAY', 'MENU'), 'owned window minimized or absent')
            self.assert_setup_failure(lambda: self.e.act('PLAY', 'MENU'), 'prior input ownership failure')
        self.d.adb.swipe.assert_called_once()

    def test_focus_lost_after_receipt_sends_zero_gestures(self):
        self.e.java.snapshot.side_effect = [{'rows': [self.good_view]},
            {'rows': [{**self.good_view, 'window_focus': False}]}]
        self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'focus lost')

    def test_tree_mutation_sends_zero_gestures(self):
        changed = copy.deepcopy(self.state)
        changed['nodes'][0]['origin'][0] += 3
        self.e.read.side_effect = [self.state, self.state, changed]
        self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'mutation')

    def test_positive_control_records_receipt_before_single_input(self):
        self.e.act('PLAY', 'MENU')
        self.d.adb.swipe.assert_called_once_with(400, 200, 400, 200, duration_ms=180)
        self.assertEqual(self.d.gestures[0]['receipt']['label'], 'PLAY')
        receipt_rows = [r for r in self.e.events if 'input_receipt' in r]
        self.assertEqual(len(receipt_rows), 1)
        self.assertEqual(receipt_rows[0]['stage'], 'MENU')

    def test_failed_scroll_progress_has_no_further_gestures(self):
        self.state = tree('Skye', 'DRAFT', y=700)
        with patch.object(entry.time, 'sleep'):
            self.assert_setup_failure(self.e.select, 'scroll did not move')
        self.assertEqual(self.d.adb.swipe.call_count, 1)
        self.assertEqual(len(self.d.gestures), 1)

    def test_second_human_missing_never_locks_first(self):
        self.d.profile['nonvisual_entry']['peers'] = [{'device_tag': 'B', 'listener_port': 9444}]
        self.e.rpc_rows = Mock(return_value=[])
        self.assert_no_input(self.e.admission, 'both humans')

    def test_unknown_screen_does_not_fall_back_to_legacy_entry(self):
        self.state['labels'] = ['unknown']
        self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'unexpected native screen')

    def test_duplicate_stale_clipped_offscreen_controls_are_setup_failures(self):
        cases = {
            'duplicate': lambda s: s['nodes'].append({**s['nodes'][1], 'address': 'other'}),
            'stale': lambda s: s.update(host_read_started=time.monotonic()-2),
            'clipped': lambda s: s['nodes'][0].update(clip=[0, 0, 300, 540]),
            'offscreen': lambda s: s['nodes'][0].update(origin=[1000, 200]),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                state = tree()
                mutate(state)
                state['traversal'].update(visited=len(state['nodes']), active=len(state['nodes']))
                self.e.read = Mock(return_value=state)
                self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), name)

    def test_wrong_guest_connection_and_newest_other_guest_are_setup_failures(self):
        guest = {'guest_id': 'guest-a', 'identities': ['guest-a']}
        wrong_owner = wire_binding()
        wrong_owner[1]['payload'] = f'{1517:08x}'+'00'*98
        device = {**self.e.device, 'guest_id': 'guest-a'}
        wrong_rpc = [{'t': 10, 'method': 'startSessionForPlayer', **device,
                      'guest_id': 'guest-b', 'match_identities': ['guest-b']}]
        self.assert_no_input(lambda: entry.guest_binding(wrong_rpc, device, 5), 'wrong guest')
        self.assert_no_input(lambda: entry.connection_binding(wrong_owner, guest, 5), 'owner disagree')
        newer_other = wire_binding(connection=999, identity='guest-b', eid=1517, slot=3, team=2, at=100)
        self.assert_no_input(lambda: self.e.wait('explicit guest binding',
            lambda: entry.connection_binding(newer_other, guest, 5)), 'explicit guest binding')

    def test_premature_hud_stays_setup_failure_without_input(self):
        self.state = tree('BUY:', 'HUD')
        self.state['labels'].append('Prepare For Battle... 1')
        self.assert_no_input(lambda: self.e.wait('native HUD', self.e._ready_screen), 'native HUD')

    def test_preexisting_lock_before_peer_connection_is_setup_failure(self):
        guests = [{'guest_id': 'guest-a', 'identities': ['guest-a']},
                  {'guest_id': 'guest-b', 'identities': ['guest-b']}]
        rows = wire_binding() + wire_binding(connection=8, identity='guest-b', eid=1517, slot=3, team=2, at=20)
        rows.append({'time': 15, 'direction': 'c2s', 'opcode': 1123, 'connection': 7})
        self.assert_no_input(lambda: entry.admission_roster(rows, guests, 5), 'locked before')

    def test_per_stage_traversal_maxima_keep_every_complete_read(self):
        for visited, duration in ((1200, 20), (1300, 10)):
            state = tree('Skye', 'DRAFT')
            state['traversal'].update(visited=visited, active=600, duration_ms=duration)
            self.e.record_read(state)
        summary = self.d.observations['entry_ui_maxima']['DRAFT']
        self.assertEqual(summary, {'reads': 2, 'visited': 1300, 'active': 600, 'duration_ms': 20})
        self.assertEqual([r['traversal']['duration_ms'] for r in self.e.events], [20, 10])

    def test_never_stable_selected_ancestry_has_bounded_replan_with_no_input(self):
        count = 0
        def moving():
            nonlocal count
            state = tree()
            state['nodes'][0]['origin'][0] += count
            count += 1
            return state
        self.e.read.side_effect = moving
        with patch.object(entry.time, 'sleep'):
            self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'REPLAN.*20 complete read pairs')
        self.assertEqual(count, 40)
        refusals = [r for r in self.e.events if r['stage'] == 'CONTROL_PAIR_REFUSED']
        self.assertEqual(len(refusals), 20)
        self.assertTrue(all(r['differences'] and r['ancestry'] for r in refusals))

    def test_draft_observation_only_retains_complete_series_without_lock_input(self):
        self.e.draft_observation_reads = 50
        self.state = tree('LOCK IN', 'DRAFT')
        with patch.object(entry.time, 'sleep'):
            self.assert_no_input(self.e.observe_draft_only, '50 complete no-input reads.*stopped before LOCK IN')
        observations = [r for r in self.e.events if r['stage'] == 'DRAFT_OBSERVATION']
        self.assertEqual(len(observations), 50)
        self.assertEqual([r['index'] for r in observations], list(range(50)))
        self.assertTrue(all(r['native']['traversal']['complete'] for r in observations))

    def test_page_settles_before_receipt_but_no_input_retries_on_mutation(self):
        start = tree('SOLO BOTS', 'MODE')
        changed = copy.deepcopy(start)
        changed['nodes'][0]['origin'][0] += 10
        self.e.read.side_effect = [start, changed]
        self.e.timeout = 1
        with patch.object(entry.time, 'sleep'):
            self.assertEqual(self.e.wait_screen('MODE', 'MENU'), changed)
        self.assertEqual(self.e.read.call_count, 2)
        self.d.adb.swipe.assert_not_called()

    def test_waiting_roster_must_reach_two_draft_reads_without_input(self):
        waiting = tree('LOCK IN', 'DRAFT')
        waiting['labels'] = sorted(ui.DRAFT_WAIT_MARKERS) + ['Skye']
        draft = tree('LOCK IN', 'DRAFT')
        self.e.read.side_effect = [waiting, draft, draft]
        self.e.timeout = 1
        with patch.object(entry.time, 'sleep'):
            self.assertEqual(self.e.wait_screen('DRAFT', 'DIFFICULTY',
                transitions=('DRAFT_WAIT',)), draft)
        self.assertEqual(self.e.read.call_count, 3)
        self.d.adb.swipe.assert_not_called()

    def test_waiting_roster_times_out_and_is_not_a_general_transition(self):
        self.state = tree('LOCK IN', 'DRAFT')
        self.state['labels'] = sorted(ui.DRAFT_WAIT_MARKERS) + ['Skye']
        wait_screen = self.e.wait_screen
        self.assert_no_input(lambda: wait_screen('DRAFT', 'DIFFICULTY',
            transitions=('DRAFT_WAIT',)), 'bounded wait')
        self.assert_no_input(lambda: wait_screen('MODE', 'MENU'), 'unexpected native screen')

    def test_descendant_must_settle_before_receipt_and_not_at_final_boundary(self):
        a = tree()
        child = copy.deepcopy(a['nodes'][1])
        child.update(address='decoration', text='', flags=108)
        a['nodes'].append(child)
        a['traversal'].update(visited=4, active=4)
        b = copy.deepcopy(a)
        b['nodes'][-1]['scale'] = [.9, .9]
        self.e.read.side_effect = [a, b, b, b, a]
        with patch.object(entry.time, 'sleep'):
            self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'descendant mutation')
        self.assertEqual(self.e.read.call_count, 5)
        self.assertEqual(sum(r['stage'] == 'CONTROL_PAIR_REFUSED' for r in self.e.events), 1)

    def test_descendant_never_settles_is_bounded_setup_not_ancestry_replan(self):
        count = 0
        def moving():
            nonlocal count
            state = tree()
            child = copy.deepcopy(state['nodes'][1])
            child.update(address='decoration', text='', flags=108, scale=[1 + count, 1])
            state['nodes'].append(child)
            state['traversal'].update(visited=4, active=4)
            count += 1
            return state
        self.e.read.side_effect = moving
        with patch.object(entry.time, 'sleep'):
            self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'protected control region.*20 complete read pairs')
        self.assertEqual(count, 40)

    def leaf_pair(self):
        a = tree()
        leaf = {**copy.deepcopy(a['nodes'][1]), 'address': 'leaf', 'text': '', 'flags': 0x4C}
        a['nodes'].append(leaf)
        a['traversal'].update(visited=4, active=4)
        b = copy.deepcopy(a)
        b['nodes'][-1]['flags'] = 0x7FCD
        return a, b

    def test_unclassified_leaf_flags_are_recorded_in_candidate_and_final_receipts(self):
        a, b = self.leaf_pair()
        self.e.read.side_effect = [a, b, a, a, a]
        self.e.act('PLAY', 'MENU')
        self.d.adb.swipe.assert_called_once()
        receipt = self.d.gestures[0]['receipt']
        self.assertEqual(receipt['tolerated_difference_count'], 2)
        self.assertEqual(receipt['outside_difference_count'], 0)
        for pair in receipt['pairs']:
            self.assertEqual(pair['tolerated_difference_count'], 1)
            difference = pair['tolerated_differences'][0]
            self.assertEqual(difference['address'], 'leaf')
            self.assertEqual(difference['classification'], 'UNCLASSIFIED')
            self.assertEqual(difference['xor'], 0x7F81)
            self.assertEqual(difference['changed_bits'], [0, *range(7, 15)])
            self.assertEqual(set(difference['fields']), {'flags'})

    def test_all_bits_outside_qualifier_mask_remain_unclassified_not_semantic(self):
        a, b = self.leaf_pair()
        b['nodes'][-1]['flags'] = a['nodes'][-1]['flags'] ^ (0xFFFFFFFF ^ 0x1C)
        difference = ui.qualify_pair(a, b, 'PLAY', 'MENU')['pair']['tolerated_differences'][0]
        self.assertEqual(difference['xor'], 0xFFFFFFE3)
        self.assertEqual(difference['changed_bits'], [0, 1, *range(5, 32)])
        self.assertEqual(difference['classification'], 'UNCLASSIFIED')

    def test_rev4_strict_regions_and_nonflag_fields_are_setup_zero_gestures(self):
        cases = [('label', None), ('control', None), ('ancestor', None),
                 ('nonleaf', None), ('textful', None), ('eventful', None), ('overlap', None),
                 ('flags', 0x5C), ('flags', 0x48), ('enabled_both', None),
                 ('scale', [.9, .9]), ('origin', [401, 200]), ('clip', [101, 80, 800, 450]),
                 ('size', [149, 50]), ('anchor', [0, 0]), ('resolved_size', [150, 50]),
                 ('parent', 'root'), ('child', 'label'), ('next', 'label'), ('vtable', 'other'),
                 ('bounds_method', 'other'), ('local_bounds', 'other'), ('size_method', 'other'),
                 ('text', 'new'), ('events', [{'type': 1}])]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                a, b = self.leaf_pair()
                if field in ('label', 'control', 'ancestor'):
                    index = {'label': 1, 'control': 0, 'ancestor': 2}[field]
                    b = copy.deepcopy(a)
                    b['nodes'][index]['flags'] ^= 128
                elif field in ('nonleaf', 'textful', 'eventful', 'overlap', 'enabled_both'):
                    key, val = {'nonleaf': ('child', 'label'), 'textful': ('text', 'nonempty'),
                                'eventful': ('events', [{'type': 1}]), 'overlap': ('parent', 'root'),
                                'enabled_both': ('flags', 0x5C)}[field]
                    a['nodes'][-1][key] = val
                    b = copy.deepcopy(a)
                    b['nodes'][-1]['flags'] ^= 128
                else:
                    b = copy.deepcopy(a)
                    b['nodes'][-1][field] = value
                for left, right in ((a, b), (b, a)):
                    # Stable candidate, mutation at final boundary: never a retry.
                    self.e.read.side_effect = [left, left, right]
                    self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'mutation|REPLAN')

    def test_descendant_qualifier_bits_change_stops_first_candidate_pair_for_replan(self):
        a, b = self.leaf_pair()
        b['nodes'][-1]['flags'] = 0x5C
        self.e.read.side_effect = [a, b]
        self.assert_no_input(lambda: self.e.act('PLAY', 'MENU'), 'REPLAN.*0x1C.*without input')
        self.assertEqual(self.e.read.call_count, 2)
        refusal = next(r for r in self.e.events if r['stage'] == 'CONTROL_PAIR_REFUSED')
        self.assertTrue(refusal['replan'])

    def test_ancestor_bit_one_refuses_pair_then_accepts_stable_pair(self):
        a, b = tree(), tree()
        b['nodes'][2]['flags'] ^= 2
        self.e.read.side_effect = [a, b, b, b, b, b, b]
        with patch.object(entry.time, 'sleep'):
            self.e.act('PLAY', 'MENU')
        self.d.adb.swipe.assert_called_once()
        refusals = [r for r in self.e.events if r['stage'] == 'CONTROL_PAIR_REFUSED']
        self.assertEqual(len(refusals), 1)
        self.assertTrue(refusals[0]['ancestry'])

    def test_positive_mocked_path_all_stages_preserves_receipts_and_owner(self):
        self.run_mocked_path()

    def test_background_play_records_native_consumption_then_server_acceptance(self):
        self.run_mocked_path(background=True)
        proof = next(r for r in self.e.events if r['stage'] == 'BACKGROUND_PLAY_PROOF')
        self.assertTrue(proof['consumed'])
        acceptance = next(r for r in self.e.events if r['stage'] == 'BACKGROUND_ENTRY_SERVER_ACCEPTANCE')
        self.assertEqual(acceptance['server_acceptance'][0]['method'], 'joinLobby')
        self.assertLess(proof['at'], acceptance['at'])

    def test_background_play_missing_transition_is_replan_without_repeat(self):
        self.run_mocked_path(background=True, missing='MODE')
        proof = next(r for r in self.e.events if r['stage'] == 'BACKGROUND_PLAY_PROOF')
        self.assertIsNone(proof['consumed'])
        self.assertEqual(proof['status'], 'UNACKNOWLEDGED')
        self.d.adb.swipe.assert_called_once()

    def test_missing_lock_acceptance_or_native_transition_is_setup_without_repeat(self):
        for missing in (1123, 1119, 'LOCKED'):
            with self.subTest(missing=missing):
                self.setUp()
                self.run_mocked_path(missing=missing)

    def run_mocked_path(self, missing=None, background=False):
        if background:
            self.e.input_window = entry.NonvisualEntry.input_window.__get__(self.e)
            self.e.plan['require_background_play'] = True
        now = time.time()
        device = self.e.device
        rpc_rows = [{'t': now, 'method': 'startSessionForPlayer', **device,
                     'guest_id': 'guest-a', 'match_identities': ['guest-a']}]
        tail = Mock(path=Path(self.temp)/'wire-1.jsonl', records=[])
        self.e.tails[tail.path] = tail
        self.e.rpc_rows = lambda: rpc_rows
        self.d.adb.client_version.return_value = {'version_name': '4.13.4', 'version_code': 147219}
        self.observer.start.return_value = {'mode': 'ui-only', 'ui': tree()}
        self.e.java.start.return_value = {'source_sha256': 'fixture'}
        transitions = [('SOLO BOTS', 'MODE'), ('3V3', 'MAP'), ('VERY EASY', 'DIFFICULTY'),
                       ('Skye', 'DRAFT'), ('LOCK IN', 'DRAFT'), ('LOCKED IN', 'LOCKED')]
        actions = []
        def frame(op, payload='', direction='s2c'):
            tail.records.append({'time': time.time(), 'connection': 7, 'direction': direction,
                                 'opcode': op, 'payload': payload})
        def input_action(*_args, **_kwargs):
            label, stage = transitions[len(actions)]
            actions.append(self.d.gestures[-1]['receipt']['label'])
            self.state = tree(label, stage)
            if len(actions) == 1 and missing == 'MODE':
                self.state = tree('PLAY', 'MENU')
            if len(actions) == 4:
                rpc_rows.append({'t': time.time(), 'method': 'joinLobby', **device,
                    'guest_id': 'guest-a', 'response': {'code': 0, 'returnValue': {'state': 'pending_auto'}}})
                tail.records.extend(wire_binding(at=time.time())[:2])
                frame(1108)
                frame(1113)
            elif len(actions) == 5:
                frame(1118, '00000109')
            elif len(actions) == 6:
                if missing == 'LOCKED':
                    self.state = tree('LOCK IN', 'DRAFT')
                for op in (1123, 1119, 1006, 1132, 1137):
                    if op != missing:
                        frame(op)
                for op in (1134, 1137):
                    frame(op, direction='c2s')
                payload = bytearray(750)
                import struct
                struct.pack_into('>I', payload, 0, 265)
                struct.pack_into('>I', payload, 8, 1500)
                frame(1011, payload.hex())
        self.d.adb.swipe.side_effect = input_action
        original_ops = self.e.server_ops
        def ops(opcodes, *args, **kwargs):
            value = original_ops(opcodes, *args, **kwargs)
            if opcodes == [1134, 1137]:
                self.state = tree('BUY:', 'HUD')
            return value
        self.e.server_ops = ops
        with patch.object(sc, 'verify_resolution'):
            if missing is None:
                self.e.run()
            else:
                reason = ('REPLAN nonforeground PLAY consumption unverified' if missing == 'MODE'
                          else 'missing transition/signal.*no input retry')
                with self.assertRaisesRegex(sc.ClientStageFailure, reason) as failure:
                    self.e.run()
                self.assertEqual(failure.exception.stage, 'SETUP')
                if missing == 'MODE':
                    self.assertEqual(actions, ['PLAY'])
                    return
                self.assertEqual(actions.count('LOCK IN'), 1)
                self.assertEqual(self.d.adb.swipe.call_count, 6)
                return
        self.assertEqual(actions, ['PLAY', 'SOLO BOTS', '3V3', 'VERY EASY', 'Skye', 'LOCK IN'])
        self.assertEqual(self.d.connection, 7)
        self.assertEqual(self.d.observations['entry_binding']['world']['eid'], 1500)
        self.assertEqual(self.d.stages['SETUP']['status'], 'PASS')
        self.assertEqual(self.e.events[-1]['stage'], 'QUALIFIED_WORLD')
        for gesture in self.d.gestures:
            self.assertTrue(gesture['receipt']['tree_sha256'])
            self.assertTrue(gesture['health']['lifecycle']['ready'])
        self.d.adb.back.assert_not_called()
        self.d.adb.screencap.assert_not_called()


class HostLeaseTests(unittest.TestCase):
    def test_two_drivers_never_overlap_window_check_to_gesture_and_record_waiter(self):
        from concurrent.futures import ThreadPoolExecutor
        from types import SimpleNamespace
        import threading
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'input.lock')
            active, trace, receipts = [], [], []
            first_entered = threading.Event()
            def qualify(_executable, *, process_id):
                self.assertEqual(active, [])
                active.append(process_id)
                trace.append(('qualify', process_id))
                return {'pid': process_id, 'hwnd': process_id}
            def drive(pid):
                e = entry.NonvisualEntry.__new__(entry.NonvisualEntry)
                e.d = SimpleNamespace(adb=SimpleNamespace(serial=str(pid)))
                e.plan = {'input_lock': path, 'host_window': {'executable': 'owned', 'pid': pid}}
                e.timeout = 2
                e.record = lambda stage, **row: receipts.append({'stage': stage, **row})
                if pid == 2:
                    self.assertTrue(first_entered.wait(2))
                with e.input_window():
                    if pid == 1:
                        first_entered.set()
                        deadline = time.monotonic()+2
                        while not any(json.loads(p.read_text())['status'] == 'waiting'
                                      for p in Path(directory).glob('*.waiter-*.json')):
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(.01)
                    e._input_check()
                    self.assertEqual(active, [pid])
                    trace.append(('gesture', pid))
                    active.clear()
            with patch.object(entry, 'qualify_owned_ldplayer', side_effect=qualify), \
                    patch.object(entry, 'require_owned_window', return_value={'qualified': True}), \
                    ThreadPoolExecutor(2) as pool:
                futures = [pool.submit(drive, pid) for pid in (1, 2)]
                for future in futures:
                    future.result(timeout=5)
            self.assertEqual(trace, [('qualify', 1), ('gesture', 1), ('qualify', 2), ('gesture', 2)])
            leases = [r for r in receipts if r['stage'] == 'INPUT_LEASE']
            for driver in ('1', '2'):
                own = [r for r in leases if r['driver'] == driver]
                self.assertEqual([r['event'] for r in own], ['acquire', 'release'])
                self.assertLessEqual(own[0]['acquired_at'], own[1]['released_at'])
            release_a = next(r for r in leases if r['driver'] == '1' and r['event'] == 'release')
            self.assertEqual(release_a['waiting_peers'][0]['driver'], '2')

    def test_timeout_and_ownership_loss_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'input.lock'
            receipts = []
            with entry.input_lease(path, .2, owner='A') as check:
                with self.assertRaisesRegex(ValueError, 'lease unavailable'):
                    with entry.input_lease(path, .02, owner='B', record=lambda **r: receipts.append(r)):
                        self.fail('timed-out peer acquired input')
                path.with_name('input.lock.owner.json').write_text('{"token":"stolen"}')
                with self.assertRaisesRegex(ValueError, 'ownership lost'):
                    check()
                # Restore only this test's intentionally corrupted ownership record.
                token = next(json.loads(p.read_text())['token'] for p in Path(directory).glob('*.waiter-*.json')
                             if json.loads(p.read_text())['driver'] == 'A')
                path.with_name('input.lock.owner.json').write_text(json.dumps({'token': token}))
            self.assertEqual(receipts[0]['event'], 'timeout')


if __name__ == '__main__':
    unittest.main()

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


class MixedCoordinationTests(unittest.TestCase):
    def setUp(self):
        from Tools import protocol_participants as pp
        from server.test.test_protocol_participants import mixed_declaration, mixed_snapshot
        self.output = pp.new_output()
        self.plan = {'mixed_draft_ready': str(self.output/'mixed-draft-ready.json'),
                     'mixed_world_release': str(self.output/'release.json'),
                     'mixed_timeout_s': .01, 'not_before': time.time()-2}
        self.hook = entry.MixedCoordination(self.plan)
        self.binding = dict(identity='test-skye', eid=1500, slot=0, team=1, connection=17, match_id=pp.MATCH_ID)
        payload = mixed_snapshot(mixed_declaration()).hex()
        self.rows = [{'connection': 17, 'direction': 's2c', 'opcode': 1113,
                      'time': time.time()-1, 'payload': payload}]
        assignments = {r['identity']: r for r in pp.selections(bytes.fromhex(payload))}
        self.receipt = {'match_id': pp.MATCH_ID, 'not_before': self.plan['not_before'],
            'verified_at': time.time(), 'assignments': assignments,
            'streams': [{'identity': i, 'snapshot': {'direction': 's2c', 'opcode': 1113,
                        'wall_time': time.time()-1, 'payload_hex': payload}}
                        for i in assignments if i != 'test-skye']}

    def test_receipt_requires_match_start_all_six_and_current_ce_snapshot(self):
        self.assertEqual(self.hook.validate(self.receipt, self.binding, self.rows)['eid'], 1500)
        for field, value in (('match_id', 'old'), ('not_before', 0), ('verified_at', float('nan')),
                             ('verified_at', time.time()+100), ('streams', [])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.hook.validate({**self.receipt, field: value}, self.binding, self.rows)
        for change in ({'hero_id': 0xffff}, {'identity': 'other'}, {'flags': 0}, {'team': 1}, {'slot': 0}):
            bad = copy.deepcopy(self.receipt)
            bad['assignments']['test-ringo'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.hook.validate(bad, self.binding, self.rows)
        with self.assertRaisesRegex(ValueError, 'no current'):
            self.hook.validate(self.receipt, self.binding, [])
        changed = copy.deepcopy(self.receipt)
        changed['streams'][0]['snapshot']['payload_hex'] = '00'
        with self.assertRaises(Exception):
            self.hook.validate(changed, self.binding, self.rows)

    def test_bounded_hold_no_ui_reads_and_atomic_owner_bound_release(self):
        e = Mock(d=Mock(tail=Mock(records=self.rows)))
        e.timeout = .01
        e.wait = entry.NonvisualEntry.wait.__get__(e)
        with self.assertRaisesRegex(ValueError, 'bounded wait'):
            self.hook.hold(e, self.binding)
        e.read.assert_not_called()
        e.act.assert_not_called()
        self.hook.ready.write_text(json.dumps(self.receipt), encoding='utf-8')
        self.hook.hold(e, self.binding)
        qualified = {'stage': 'QUALIFIED_WORLD', 'at': time.time(), 'eid': 1500,
                     'slot': 0, 'hero_id': 265, 'connection': 17}
        for change in ({'connection': 18}, {'eid': 1517}, {'team': 2}):
            with self.assertRaisesRegex(ValueError, 'owner changed'):
                self.hook.publish({**self.binding, **change}, qualified)
        self.assertFalse(self.hook.release.exists())
        result = self.hook.publish(self.binding, qualified)
        self.assertEqual(json.loads(self.hook.release.read_text()), result)
        self.assertFalse(list(self.output.glob('*.pending')))
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.hook.publish(self.binding, qualified)

    def test_explicit_bisection_composition_is_slot_exact_and_default_still_refuses_it(self):
        from Tools import protocol_participants as pp
        from server.test.test_protocol_participants import mixed_declaration, mixed_snapshot
        declaration = mixed_declaration(evidenced=True)
        heroes = [r['hero'] for _, r in sorted(zip(pp.SLOTS, declaration['real_clients']+declaration['participants']))]
        hook = entry.MixedCoordination({**self.plan, 'mixed_heroes_by_slot': heroes})
        payload = mixed_snapshot(declaration).hex()
        receipt = copy.deepcopy(self.receipt)
        receipt['assignments'] = {r['identity']: r for r in pp.selections(bytes.fromhex(payload))}
        for stream in receipt['streams']:
            stream['snapshot']['payload_hex'] = payload
        rows = [{**self.rows[0], 'payload': payload}]
        self.assertEqual(hook.validate(receipt, self.binding, rows)['eid'], 1500)
        with self.assertRaisesRegex(ValueError, 'all six'):
            self.hook.validate(receipt, self.binding, rows)
        # The same six heroes in different slots are not the declared bisection.
        swapped = list(heroes)
        swapped[1], swapped[3] = swapped[3], swapped[1]
        wrong = entry.MixedCoordination({**self.plan, 'mixed_heroes_by_slot': swapped})
        with self.assertRaisesRegex(ValueError, 'all six'):
            wrong.validate(receipt, self.binding, rows)
        for invalid in (heroes[:5], ['Skye']*6, ['Ringo']+heroes[1:], ['Ardan']+heroes[1:], 'Skye', [None]*6):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                entry.MixedCoordination({**self.plan, 'mixed_heroes_by_slot': invalid})

    def test_stale_files_paths_and_unbounded_wait_refused_before_input(self):
        for value in (0, -1, 601, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                entry.MixedCoordination({**self.plan, 'mixed_timeout_s': value})
        with self.assertRaisesRegex(ValueError, 'under Local/evidence'):
            entry.MixedCoordination({**self.plan, 'mixed_draft_ready': 'outside.json'})
        self.hook.ready.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'initially absent'):
            entry.MixedCoordination(self.plan)


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


class DraftDifficultyValueTests(unittest.TestCase):
    def waiting(self, value='HARD'):
        labels = sorted(ui.DRAFT_WAIT_MARKERS) + ['Skye', value]
        return {'labels': labels, 'nodes': [
            {'address': 'panel', 'parent': 'root'},
            *({'address': str(i), 'text': label, 'parent': 'panel'}
              for i, label in enumerate(labels))]}

    def test_observed_value_direct_sibling_is_read_only_draft_wait(self):
        state = self.waiting()
        self.assertEqual(ui.DRAFT_DIFFICULTY_VALUES, {'HARD'})
        self.assertEqual(ui.screen(state), 'DRAFT_WAIT')
        for expected in ('DRAFT', 'DRAFT_WAIT'):
            with self.subTest(expected=expected), self.assertRaisesRegex(ValueError, 'read-only transition'):
                ui.control_receipt(state, 'LOCK IN', expected)
        with self.assertRaisesRegex(ValueError, 'read-only transition'):
            ui.control_receipt(state, 'Skye', 'DRAFT', hero_id=265)

    def test_observed_value_elsewhere_is_unknown(self):
        for parent in ('root', 'nested', None, '0x0'):
            state = self.waiting()
            state['nodes'][-1]['parent'] = parent
            state['nodes'].append({'address': 'nested', 'parent': 'panel'})
            with self.subTest(parent=parent):
                self.assertEqual(ui.screen(state), 'UNKNOWN')

    def test_unobserved_value_is_unknown_even_as_sibling(self):
        self.assertEqual(ui.screen(self.waiting('VERY HARD')), 'UNKNOWN')

    def test_two_extra_labels_including_duplicate_value_are_unknown(self):
        for extra in ('HARD', 'VERY HARD'):
            state = self.waiting()
            state['labels'].append(extra)
            state['nodes'].append({'address': 'extra', 'text': extra, 'parent': 'panel'})
            with self.subTest(extra=extra):
                self.assertEqual(ui.screen(state), 'UNKNOWN')

    def test_missing_or_duplicate_marker_never_qualifies(self):
        for marker in ui.DRAFT_WAIT_MARKERS:
            for duplicate in (False, True):
                state = self.waiting()
                if duplicate:
                    state['labels'].append(marker)
                else:
                    state['labels'].remove(marker)
                    state['nodes'] = [n for n in state['nodes'] if n.get('text') != marker]
                with self.subTest(marker=marker, duplicate=duplicate):
                    self.assertNotEqual(ui.screen(state), 'DRAFT_WAIT')

    def test_label_only_callers_do_not_gain_value_exception(self):
        state = {'labels': sorted(ui.DRAFT_WAIT_MARKERS)}
        self.assertEqual(ui.screen(state), 'DRAFT_WAIT')
        state['labels'].append('HARD')
        self.assertEqual(ui.screen(state), 'UNKNOWN')

    def test_missing_ambiguous_or_parentless_nodes_cannot_prove_siblings(self):
        for label in ('DIFFICULTY', 'HARD'):
            for duplicate in (False, True):
                state = self.waiting()
                node = next(n for n in state['nodes'] if n.get('text') == label)
                if duplicate:
                    state['nodes'].append({**node, 'address': 'duplicate'})
                else:
                    state['nodes'].remove(node)
                with self.subTest(label=label, duplicate=duplicate):
                    self.assertEqual(ui.screen(state), 'UNKNOWN')
        for parent in (None, '0x0', 'absent'):
            state = self.waiting()
            for node in state['nodes'][1:]:
                node['parent'] = parent
            with self.subTest(parent=parent):
                self.assertEqual(ui.screen(state), 'UNKNOWN')


class DraftRosterHandleTests(unittest.TestCase):
    @staticmethod
    def waiting(names=('Guest', 'Alpha Bot', 'Beta Bot')):
        nodes = [{'address': 'root', 'parent': '0x0'},
                 {'address': 'lca', 'parent': 'root', 'vtable': '0x27260b8'},
                 {'address': 'content', 'parent': 'lca', 'vtable': '0x27266f0'},
                 {'address': 'roster', 'parent': 'content', 'vtable': '0x26d27e0'},
                 {'address': 'pane', 'parent': 'roster', 'vtable': '0x27284a0'},
                 {'address': 'list', 'parent': 'pane', 'vtable': '0x27284a0'},
                 {'address': 'difficulty', 'parent': 'content'}]
        for i, text in enumerate(sorted(ui.DRAFT_WAIT_MARKERS) + ['HARD']):
            nodes.append({'address': f'marker{i}', 'text': text,
                          'parent': 'difficulty' if text in ('DIFFICULTY', 'HARD') else 'lca'})
        for i, text in enumerate(names):
            nodes.extend([{'address': f'card{i}', 'parent': 'list', 'vtable': '0x26fa2d0'},
                          {'address': f'name{i}', 'parent': f'card{i}', 'text': text,
                           'vtable': '0x2726530'}])
        return {'root': 'root', 'nodes': nodes, 'labels': [n['text'] for n in nodes if 'text' in n]}

    def test_wire_names_and_mixed_participant_handles_are_read_only(self):
        for names in (('Guest', 'Alpha Bot', 'Beta Bot'), ('Guest', 'Player 2', 'Player 3'),
                      ('Unlisted arbitrary handle',), ('Same', 'Same')):
            from collections import Counter
            state = self.waiting(names)
            with self.subTest(names=names):
                self.assertEqual(ui.screen(state, roster_handles=Counter(names)), 'DRAFT_WAIT')
                for expected in ('DRAFT', 'DRAFT_WAIT'):
                    with self.assertRaises(ValueError):
                        ui.control_receipt(state, 'LOCK IN', expected)
                with self.assertRaises(ValueError):
                    ui.qualify_pair(state, state, 'LOCK IN', 'DRAFT')

    def test_absent_unlisted_or_overcount_handle_is_unknown(self):
        state = self.waiting()
        self.assertEqual(ui.screen(state), 'UNKNOWN')
        for handles in ({}, {'Guest': 1}, {'Guest': 1, 'Alpha Bot': 1, 'Beta Bot': 0}):
            self.assertEqual(ui.screen(state, roster_handles=handles), 'UNKNOWN')
        self.assertEqual(ui.screen(self.waiting(('Same', 'Same')), roster_handles={'Same': 1}), 'UNKNOWN')
        base = DraftDifficultyValueTests().waiting()
        self.assertEqual(ui.screen(base), 'DRAFT_WAIT')
        self.assertEqual(ui.screen(base, roster_handles={}), 'DRAFT_WAIT')

    def test_wrong_missing_cyclic_or_ambiguous_structure_is_unknown(self):
        for kind in ('difficulty', 'root', 'card-type', 'same-card', 'different-list',
                     'cycle', 'missing', 'duplicate', 'label-node-disagreement', 'marker-in-list'):
            state = self.waiting()
            nodes = {n['address']: n for n in state['nodes']}
            if kind in ('difficulty', 'root'): nodes['name0']['parent'] = kind
            elif kind == 'card-type': nodes['card0']['vtable'] = '0x27284a0'
            elif kind == 'same-card': nodes['name1']['parent'] = 'card0'
            elif kind == 'different-list':
                state['nodes'].append({**nodes['list'], 'address': 'other-list'})
                nodes['card1']['parent'] = 'other-list'
            elif kind == 'cycle': nodes['list']['parent'] = 'card0'
            elif kind == 'missing': state['nodes'].remove(nodes['card0'])
            elif kind == 'duplicate': state['nodes'].append(dict(nodes['card0']))
            elif kind == 'label-node-disagreement': nodes['name0']['text'] = 'Other'
            elif kind == 'marker-in-list': nodes['marker0']['parent'] = 'list'
            with self.subTest(kind=kind):
                self.assertEqual(ui.screen(state, roster_handles={'Guest': 1, 'Alpha Bot': 1, 'Beta Bot': 1}), 'UNKNOWN')

    def test_hard_sibling_rule_cannot_be_bypassed_by_wire_handle(self):
        for duplicate in (False, True):
            state = self.waiting(('Guest',))
            hard = next(n for n in state['nodes'] if n.get('text') == 'HARD')
            if duplicate:
                state['labels'].append('HARD')
                state['nodes'].append({**hard, 'address': 'extra-hard'})
            else:
                hard['parent'] = 'lca'
            self.assertEqual(ui.screen(state, roster_handles={'Guest': 1, 'HARD': 2}), 'UNKNOWN')

    @staticmethod
    def wire():
        from server import roster
        binding = {'direction': 'identity', 'time': 10, 'connection': 7, 'identity': 'ce',
                   'match_id': 'match', 'eid': 1500, 'slot': 0, 'team': 1}
        players = roster.default_solo_bots('ce', 'match')
        payload = roster.build_snapshot(players).hex()
        return binding, [binding, {'direction': 's2c', 'time': 11, 'connection': 7,
                                  'opcode': 1113, 'payload': payload}], players

    def test_only_latest_bound_connection_snapshot_counts_not_frames(self):
        from server import roster
        binding, rows, players = self.wire()
        self.assertEqual(entry.bound_roster_handles(rows, binding, 5)['Guest'], 1)
        rows.append(dict(rows[-1]))
        self.assertEqual(entry.bound_roster_handles(rows, binding, 5)['Guest'], 1)
        players[1].handle = 'Guest'
        rows.append({**rows[-1], 'payload': roster.build_snapshot(players).hex(), 'time': 12})
        self.assertEqual(entry.bound_roster_handles(rows, binding, 5)['Guest'], 2)
        players[1].handle = 'Player 2'
        rows.append({**rows[-1], 'payload': roster.build_snapshot(players).hex(), 'time': 13})
        handles = entry.bound_roster_handles(rows, binding, 5)
        self.assertEqual(handles['Guest'], 1)
        self.assertEqual(handles['Player 2'], 1)
        self.assertNotIn('Alpha Bot', handles)

    def test_opener_sent_before_identity_trace_row_is_still_connection_bound(self):
        binding, rows, _ = self.wire()
        rows[-1]['time'] = 9
        rows.reverse()
        self.assertEqual(entry.bound_roster_handles(rows, binding, 5)['Guest'], 1)

    def test_other_connection_match_direction_old_missing_and_closed_are_not_sources(self):
        for kind in ('connection', 'match', 'direction', 'old', 'missing', 'closed', 'owner', 'truncated'):
            binding, rows, _ = self.wire()
            if kind == 'connection': rows[-1]['connection'] = 8
            elif kind == 'match': binding = {**binding, 'match_id': 'other'}
            elif kind == 'direction': rows[-1]['direction'] = 'c2s'
            elif kind == 'old': rows[-1]['time'] = 4
            elif kind == 'missing': rows.pop()
            elif kind == 'closed': rows.append({'direction': 'disconnect', 'connection': 7})
            elif kind == 'owner': binding['eid'] = 1517
            elif kind == 'truncated': rows[-1]['payload'] = '00'
            with self.subTest(kind=kind):
                if kind in ('owner', 'truncated'):
                    with self.assertRaises((ValueError, RuntimeError)):
                        entry.bound_roster_handles(rows, binding, 5)
                else:
                    self.assertIsNone(entry.bound_roster_handles(rows, binding, 5))


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
        wait_screen = self.e.wait_screen
        def at_menu(*args, **kwargs):
            return callback() if args == ('MENU', 'MENU') else wait_screen(*args, **kwargs)
        with patch.object(self.e, 'wait', side_effect=await_signal), \
                patch.object(self.e, 'wait_screen', side_effect=at_menu), \
                patch.object(sc, 'verify_resolution'), \
                self.assertRaisesRegex(sc.ClientStageFailure, detail) as failure:
            self.e.run()
        self.assertEqual(failure.exception.stage, 'SETUP')
        self.assertEqual(failure.exception.status, 'FAIL')

    def build_clock(self):
        clock = [time.monotonic()]
        self.enterContext(patch.object(entry.time, 'monotonic', side_effect=lambda: clock[0]))
        self.enterContext(patch.object(entry.time, 'sleep', side_effect=lambda seconds:
                                      clock.__setitem__(0, clock[0]+seconds)))
        return clock

    def test_entry_build_uses_one_gated_back_and_requires_hud(self):
        self.build_clock()
        self.state = tree('OPEN SHOP', 'BUILD')
        self.d.adb.back.side_effect = lambda: setattr(self, 'state', tree('BUY:', 'HUD'))
        self.e.leave_build(tree('Choose a Build', 'BUILD'))
        self.d.adb.back.assert_called_once_with()
        self.assertEqual([g['kind'] for g in self.d.gestures], ['native-ui-back'])
        transport = [r for r in self.e.events if r.get('input_transport') == 'returned']
        self.assertEqual(len(transport), 1)
        self.assertEqual(transport[0]['stage'], 'BUILD_DISMISS')
        self.assertEqual(self.e.events[-1]['stage'], 'BUILD_DISMISS_AFTER')
        self.assertEqual(ui.screen(self.e.events[-1]['native']), 'HUD')
        self.d.adb.swipe.assert_not_called()

    def test_entry_surviving_build_stops_after_one_back_without_shop_input(self):
        self.build_clock()
        self.state = tree('OPEN SHOP', 'BUILD')
        self.assert_setup_failure(lambda: self.e.leave_build(self.state), 'known native panel blocks walking')
        self.d.adb.back.assert_called_once_with()
        self.d.adb.swipe.assert_not_called()
        self.d.adb.tap.assert_not_called()
        self.assertEqual([g['kind'] for g in self.d.gestures], ['native-ui-back'])

    def test_build_freshness_is_checked_after_acquiring_the_same_input_lease(self):
        from contextlib import contextmanager
        clock = self.build_clock()
        self.state = tree('OPEN SHOP', 'BUILD')
        @contextmanager
        def delayed_lease():
            clock[0] += 2
            yield
        self.e.input_window = delayed_lease
        self.assert_no_input(lambda: self.e.leave_build(self.state), 'stale BUILD gating read')
        self.d.adb.back.assert_not_called()

    def test_build_back_holds_real_entry_lease_and_records_transport(self):
        self.build_clock()
        self.state = tree('OPEN SHOP', 'BUILD')
        self.e.input_window = entry.NonvisualEntry.input_window.__get__(self.e)
        def send():
            with self.assertRaisesRegex(ValueError, 'input lease unavailable'):
                with entry.input_lease(self.e.plan['input_lock'], 0, owner='other'):
                    self.fail('BACK sent outside entry lease')
            self.state = tree('BUY:', 'HUD')
        self.d.adb.back.side_effect = send
        self.e.leave_build(self.state)
        self.d.adb.back.assert_called_once_with()
        self.assertEqual(len([r for r in self.e.events if r.get('input_transport') == 'returned']), 1)

    def explicit_build_exit(self, outcome):
        self.build_clock()
        self.e.timeout = 1
        self.e.plan['shop_close_label'] = 'Shop'
        self.state = tree('OPEN SHOP', 'BUILD')
        def transition(*args, **kwargs):
            self.state = (tree('Shop', 'SHOP') if len(self.d.gestures) == 1
                          else tree({'HUD': 'BUY:', 'MENU': 'PLAY'}.get(outcome, 'OPEN SHOP'), outcome))
        self.d.adb.swipe.side_effect = transition

    def test_build_explicit_candidate_uses_two_ordinary_guarded_actions(self):
        self.explicit_build_exit('HUD')
        self.e.leave_build(self.state)
        self.assertEqual([g['receipt']['label'] for g in self.d.gestures], ['OPEN SHOP', 'Shop'])
        self.assertTrue(all(len(g['receipt']['pairs']) == 2 for g in self.d.gestures))
        self.assertEqual(self.e.events[-1]['stage'], 'BUILD_EXIT_HUD')
        self.d.adb.back.assert_not_called()

    def test_build_explicit_exit_non_hud_is_setup_without_another_guess(self):
        for outcome in ('BUILD', 'SHOP', 'MENU'):
            with self.subTest(outcome=outcome):
                self.d.gestures.clear()
                self.explicit_build_exit(outcome)
                self.assert_setup_failure(lambda: self.e.leave_build(self.state), 'SHOP exit: expected HUD')
                self.assertEqual(len(self.d.gestures), 2)

    def test_build_unqualified_explicit_exit_is_setup_without_exit_gesture(self):
        self.explicit_build_exit('HUD')
        self.e.plan['shop_close_label'] = 'CLOSE'
        self.assert_setup_failure(lambda: self.e.leave_build(self.state), "label 'CLOSE' absent")
        self.assertEqual([g['receipt']['label'] for g in self.d.gestures], ['OPEN SHOP'])

    def test_build_unknown_observation_is_setup_without_input(self):
        self.build_clock()
        self.e.read = Mock(return_value=self.unknown_tree())
        self.assert_no_input(lambda: self.e.leave_build(tree('OPEN SHOP', 'BUILD')), 'native gameplay HUD')
        self.d.adb.back.assert_not_called()

    def test_direct_hud_does_not_observe_or_input(self):
        self.e.leave_build(tree('BUY:', 'HUD'))
        self.e.read.assert_not_called()
        self.assertEqual(self.e.events, [])
        self.assertEqual(self.d.gestures, [])

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

    def scroll_fixture(self, starts, *, mutate=None, end_delay=.02, after_scroll=True,
                       label='Skye', y=200):
        """Synthetic read brackets; production signature and receipt code run."""
        self.state = tree(label, 'DRAFT', y=y)
        self.clock = 100.
        self.e._scroll_returned = self.clock if after_scroll else None
        self.enterContext(patch.object(entry.time, 'monotonic', side_effect=lambda: self.clock))
        self.enterContext(patch.object(entry.time, 'sleep'))
        iterator = iter(starts)
        index = 0
        def read():
            nonlocal index
            start = next(iterator)
            state = copy.deepcopy(self.state)
            state.update(host_read_started=100+start, host_read_ended=100+start+end_delay)
            if mutate:
                mutate(state, index)
            self.clock = state['host_read_ended']
            index += 1
            return state
        self.e.read = Mock(side_effect=read)

    def test_post_scroll_outside_churn_span_then_fresh_pair_and_single_input(self):
        def outside(state, i):
            PairQualificationTests().outside_node(state, x=20+i/100)
        self.scroll_fixture([i*.15 for i in range(31)], mutate=outside)
        self.e.act('Skye', 'DRAFT', hero_id=265)
        rows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
        self.assertEqual(rows[-1]['reads'], 28)
        self.assertAlmostEqual(rows[-1]['span_s'], 4.05)
        self.assertEqual(len({r['protected_signature'] for r in rows}), 1)
        self.assertEqual(self.e.read.call_count, 31)  # span + revalidation + post pair
        receipt = self.d.gestures[0]['receipt']
        self.assertGreater(receipt['outside_difference_count'], 0)
        self.assertEqual(len(receipt['pairs']), 2)
        self.d.adb.swipe.assert_called_once()
        self.assertIsNone(self.e._scroll_returned)

    def test_post_scroll_protected_geometry_change_restarts(self):
        def change(state, i):
            state['nodes'][2]['origin'][0] += 1 if i >= 20 else 0
        self.scroll_fixture([i*.15 for i in range(48)], mutate=change)
        self.e.control_pair('Skye', 'DRAFT', hero_id=265)
        rows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
        self.assertEqual([i for i, r in enumerate(rows) if r['restarted']], [0, 20])
        self.assertEqual(rows[-1]['reads'], 28)
        self.assertEqual(self.e.read.call_count, 48)
        self.d.adb.swipe.assert_not_called()

    def test_post_scroll_short_span_does_not_accept_even_with_enough_reads(self):
        self.scroll_fixture([i*.1 for i in range(28)] + [15])
        self.assert_no_input(lambda: self.e.act('Skye', 'DRAFT', hero_id=265), '15s budget')
        rows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
        self.assertEqual(rows[27]['reads'], 28)
        self.assertLess(rows[27]['span_s'], 3.888)

    def test_rev4_descendant_churn_with_pulses_holds_window_and_final_revalidation(self):
        def change(state, i):
            leaf = {**copy.deepcopy(state['nodes'][1]), 'address': 'leaf', 'text': '',
                    'flags': 76 if i % 2 else 204}
            state['nodes'].append(leaf)
            state['traversal'].update(visited=4, active=4)
            state['nodes'][2]['flags'] ^= 2 if i % 2 else 0
        self.scroll_fixture([i*.15 for i in range(31)], mutate=change)
        self.e.act('Skye', 'DRAFT', hero_id=265)
        windows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
        self.assertEqual([i for i, r in enumerate(windows) if r['restarted']], [0])
        self.assertEqual(windows[-1]['reads'], 28)
        for pair in self.d.gestures[0]['receipt']['pairs']:
            self.assertEqual({d['classification'] for d in pair['tolerated_differences']},
                             {'PULSE_0x2', 'UNCLASSIFIED'})
        self.assertEqual(len([r for r in self.e.events if r['stage'] == 'PULSE_0x2']), 27)
        self.d.adb.swipe.assert_called_once()

    def test_rev4_nondescendant_and_structural_mutations_restart_window(self):
        for field, value in (('parent', 'root'), ('flags', 72), ('text', 'decoration'),
                             ('events', [{'type': 1}]), ('child', 'label')):
            with self.subTest(field=field):
                def change(state, i):
                    leaf = {**copy.deepcopy(state['nodes'][1]), 'address': 'leaf', 'text': '',
                            'flags': 76 if i < 20 else 204}
                    if field == 'parent' or i >= 20:
                        leaf[field] = value
                    state['nodes'].append(leaf)
                    state['traversal'].update(visited=4, active=4)
                self.e.events.clear()
                self.scroll_fixture([i*.15 for i in range(48)], mutate=change)
                self.e.control_pair('Skye', 'DRAFT', hero_id=265)
                rows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
                self.assertEqual([i for i, r in enumerate(rows) if r['restarted']], [0, 20])
                self.assertEqual(self.e.read.call_count, 48)
                self.d.adb.swipe.assert_not_called()

    def test_post_scroll_fewer_than_count_does_not_accept_even_with_long_span(self):
        self.scroll_fixture([i*.2 for i in range(27)] + [15])
        self.assert_no_input(lambda: self.e.act('Skye', 'DRAFT', hero_id=265), '15s budget')
        rows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
        self.assertEqual(rows[26]['reads'], 27)
        self.assertGreater(rows[26]['span_s'], 3.888)

    def test_post_scroll_budget_includes_time_since_scroll_return(self):
        self.scroll_fixture([])
        self.clock = 115
        self.assert_no_input(lambda: self.e.act('Skye', 'DRAFT', hero_id=265), '15s budget')
        self.e.read.assert_not_called()

    def test_post_scroll_stale_final_pair_still_refused_without_retry(self):
        self.scroll_fixture([i*.15 for i in range(27)] + [6])
        self.assert_no_input(lambda: self.e.act('Skye', 'DRAFT', hero_id=265), 'stale native label receipt')
        self.assertEqual(self.e.read.call_count, 28)

    def test_post_scroll_revalidation_still_no_retry(self):
        def change(state, i):
            state['nodes'][2]['flags'] ^= 1 if i == 28 else 0
        self.scroll_fixture([i*.15 for i in range(29)], mutate=change)
        self.assert_no_input(lambda: self.e.act('Skye', 'DRAFT', hero_id=265), 'full ancestry mutation')
        self.assertEqual(self.e.read.call_count, 29)

    def test_pulse_window_and_terminal_revalidation_pass_without_reversal(self):
        def change(state, i):
            state['nodes'][2]['flags'] ^= 2 if i in (8, 15) or i >= 28 else 0
        self.scroll_fixture([i*.15 for i in range(31)], mutate=change)
        self.e.act('Skye', 'DRAFT', hero_id=265)
        windows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
        self.assertEqual([i for i,r in enumerate(windows) if r['restarted']], [0])
        self.assertEqual(windows[-1]['reads'], 28)
        pulses = [r for r in self.e.events if r['stage'] == 'PULSE_0x2']
        self.assertEqual(len(pulses), 4)
        self.assertTrue(all(r['differences'][0]['classification'] == 'PULSE_0x2' for r in pulses))
        final = self.d.gestures[0]['receipt']['pairs'][1]
        self.assertEqual(final['tolerated_difference_count'], 1)
        self.assertEqual(final['tolerated_differences'][0]['xor'], 2)
        self.d.adb.swipe.assert_called_once()

    def test_post_scroll_signature_has_no_age_dependency_and_rejects_partial_tree(self):
        state = tree('Skye', 'DRAFT')
        expected = ui.protected_signature(state, 'Skye', 'DRAFT', hero_id=265)
        state.pop('host_read_started')
        state.pop('host_read_ended')
        self.assertEqual(ui.protected_signature(state, 'Skye', 'DRAFT', hero_id=265), expected)
        state['traversal']['complete'] = False
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            ui.protected_signature(state, 'Skye', 'DRAFT', hero_id=265)

    def test_non_scroll_path_does_not_consult_structural_window(self):
        with patch.object(ui, 'protected_signature', side_effect=AssertionError('non-scroll changed')):
            self.e.act('PLAY', 'MENU')
        self.assertEqual(self.e.read.call_count, 5)
        self.d.adb.swipe.assert_called_once()

    def test_first_draft_scroll_waits_through_opening_animation(self):
        def opening(state, i):
            state['nodes'][2]['origin'][0] += 1 if i >= 8 else 0
        self.scroll_fixture([i*.15 for i in range(39)], mutate=opening,
                            after_scroll=False, y=700)
        self.e.act('Skye', 'DRAFT', hero_id=265, scroll=True)
        rows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
        self.assertEqual([i for i, r in enumerate(rows) if r['restarted']], [0, 8])
        self.assertEqual(rows[-1]['reads'], 28)
        self.assertAlmostEqual(rows[-1]['span_s'], 4.05)
        self.assertTrue(all(r['scroll_returned'] is None for r in rows))
        self.assertEqual(self.e.read.call_count, 39)
        self.d.adb.swipe.assert_called_once()
        self.assertEqual(self.d.gestures[0]['kind'], 'entry-scroll')

    def test_hero_tap_and_lock_each_collect_a_new_window_without_scroll(self):
        self.scroll_fixture([i*.15 for i in range(62)], after_scroll=False)
        self.e.act('Skye', 'DRAFT', hero_id=265)
        self.state = tree('LOCK IN', 'DRAFT')
        self.e.admission_guests = ['synthetic-guest']
        with patch.object(entry, 'admission_roster', return_value={'synthetic': True}) as admission:
            self.e.act('LOCK IN', 'DRAFT')
        admission.assert_called_once()
        rows = [r for r in self.e.events if r['stage'] == 'DRAFT_CONTROL_WINDOW']
        for label in ('Skye', 'LOCK IN'):
            window = [r for r in rows if r['label'] == label]
            self.assertEqual(len(window), 28)
            self.assertEqual(window[0]['reads'], 1)
            self.assertTrue(window[0]['restarted'])
            self.assertAlmostEqual(window[-1]['span_s'], 4.05)
        self.assertGreater(rows[28]['window_started'], rows[0]['window_started'])
        self.assertEqual(self.e.read.call_count, 62)
        self.assertEqual(self.d.adb.swipe.call_count, 2)

    def test_draft_opening_budget_exhaustion_sends_no_first_input(self):
        self.scroll_fixture([i*.5 for i in range(31)], after_scroll=False,
            mutate=lambda state, i: state['nodes'][2].update(flags=i % 2))
        self.assert_no_input(lambda: self.e.act('Skye', 'DRAFT', hero_id=265), '15s budget')

    def test_all_non_draft_controls_keep_adjacent_pairs_without_window(self):
        for label, stage in (('PLAY', 'MENU'), ('SOLO BOTS', 'MODE'),
                             ('3V3', 'MAP'), ('VERY EASY', 'DIFFICULTY')):
            with self.subTest(stage=stage):
                self.state = tree(label, stage)
                self.e.read.reset_mock()
                with patch.object(ui, 'protected_signature', side_effect=AssertionError('non-DRAFT changed')):
                    self.e.act(label, stage)
                self.assertEqual(self.e.read.call_count, 5)
        self.assertEqual(self.d.adb.swipe.call_count, 4)

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

    def wait_screen_sequence(self, states, times):
        """Synthetic wall clock advances only when a native read completes."""
        clock = [0.0]
        sequence = iter(zip(states, times, strict=True))
        def read():
            state, clock[0] = next(sequence)
            return state
        self.e.read.side_effect = read
        self.e.timeout = 30
        self.enterContext(patch.object(entry.time, 'monotonic', side_effect=lambda: clock[0]))
        self.enterContext(patch.object(entry.time, 'sleep'))
        return self.e.wait_screen

    def unknown_tree(self):
        state = tree()
        state['labels'] = ['unknown']
        return state

    def test_transient_unknown_between_previous_and_wanted_requires_fresh_pair(self):
        previous, unknown, wanted = tree(), self.unknown_tree(), tree('SOLO BOTS', 'MODE')
        wait = self.wait_screen_sequence([previous, unknown, wanted, wanted], [0, .1, .2, .3])
        self.assertEqual(wait('MODE', 'MENU'), wanted)
        self.assertEqual(self.e.read.call_count, 4)
        records = [r for r in self.e.events if r['stage'] == 'TRANSIENT_UNKNOWN']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['native'], unknown)
        self.assertEqual(records[0]['count'], 1)
        self.assertEqual(records[0]['continuous_s'], 0)
        self.d.adb.tap.assert_not_called()
        self.d.adb.swipe.assert_not_called()

    def test_transient_unknown_continuous_over_three_seconds_is_setup(self):
        unknown = self.unknown_tree()
        wait = self.wait_screen_sequence([unknown]*3, [0, 3.0, 3.001])
        self.assert_no_input(lambda: wait('MODE', 'MENU'), 'UNKNOWN bound exceeded')
        self.assertEqual(self.e.read.call_count, 3)
        records = [r for r in self.e.events if r['stage'] == 'TRANSIENT_UNKNOWN']
        self.assertEqual([r['continuous_s'] for r in records], [0, 3.0, 3.001])
        self.assertTrue(all(r['native'] == unknown for r in records))

    def test_transient_unknown_sixteenth_total_read_is_setup_even_when_interrupted(self):
        unknown, previous = self.unknown_tree(), tree()
        states = [unknown, previous]*15 + [unknown]
        wait = self.wait_screen_sequence(states, [i*.05 for i in range(len(states))])
        self.assert_no_input(lambda: wait('MODE', 'MENU'), '16 total reads')
        records = [r for r in self.e.events if r['stage'] == 'TRANSIENT_UNKNOWN']
        self.assertEqual(len(records), 16)
        self.assertEqual(self.e.read.call_count, 31)
        self.assertTrue(all(r['continuous_s'] == 0 for r in records))

    def test_transient_unknown_known_read_resets_continuous_timer(self):
        unknown, previous, wanted = self.unknown_tree(), tree(), tree('SOLO BOTS', 'MODE')
        states = [unknown, unknown, previous, unknown, unknown, wanted, wanted]
        wait = self.wait_screen_sequence(states, [0, 2.9, 3, 3.1, 6, 6.1, 6.2])
        self.assertEqual(wait('MODE', 'MENU'), wanted)
        self.assertEqual(self.e.read.call_count, 7)
        self.d.adb.swipe.assert_not_called()

    def test_wait_screen_unexpected_known_screen_is_immediate_setup(self):
        wait = self.wait_screen_sequence([tree('LOCK IN', 'DRAFT')], [0])
        self.assert_no_input(lambda: wait('MODE', 'MENU'), 'unexpected native screen DRAFT')
        self.assertEqual(self.e.read.call_count, 1)
        self.assertFalse(any(r['stage'] == 'TRANSIENT_UNKNOWN' for r in self.e.events))

    def test_transient_unknown_breaks_wanted_pair(self):
        wanted, unknown = tree('SOLO BOTS', 'MODE'), self.unknown_tree()
        wait = self.wait_screen_sequence([wanted, unknown, wanted, wanted], [0, .1, .2, .3])
        self.assertEqual(wait('MODE', 'MENU'), wanted)
        self.assertEqual(self.e.read.call_count, 4)
        self.assertEqual(sum(r['stage'] == 'SCREEN_PAIR' for r in self.e.events), 1)
        self.d.adb.tap.assert_not_called()
        self.d.adb.swipe.assert_not_called()

    def test_bound_wire_names_wait_read_only_then_require_two_draft_reads(self):
        waiting = DraftRosterHandleTests.waiting()
        waiting['traversal'] = {'complete': True, 'root_unchanged': True, 'node_limit': 4096,
                                'visited': len(waiting['nodes']), 'active': len(waiting['nodes'])}
        self.e.binding, self.d.tail.records, _ = DraftRosterHandleTests.wire()
        draft = tree('LOCK IN', 'DRAFT')
        self.e.read.side_effect = [waiting, draft, draft]
        with patch.object(entry.time, 'sleep'):
            self.assertEqual(self.e.wait_screen('DRAFT', 'DIFFICULTY', transitions=('DRAFT_WAIT',)), draft)
        self.d.tail.poll.assert_called_once()
        self.d.adb.tap.assert_not_called()
        self.d.adb.swipe.assert_not_called()
        self.assertEqual(self.e.read.call_count, 3)

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

    def test_ancestor_nonpulse_bit_refuses_pair_then_accepts_stable_pair(self):
        a, b = tree(), tree()
        b['nodes'][2]['flags'] ^= 1
        self.e.read.side_effect = [a, b, b, b, b, b, b]
        with patch.object(entry.time, 'sleep'):
            self.e.act('PLAY', 'MENU')
        self.d.adb.swipe.assert_called_once()
        refusals = [r for r in self.e.events if r['stage'] == 'CONTROL_PAIR_REFUSED']
        self.assertEqual(len(refusals), 1)
        self.assertTrue(refusals[0]['ancestry'])

    def test_positive_mocked_path_all_stages_preserves_receipts_and_owner(self):
        self.run_mocked_path()

    def test_absent_mixed_flags_preserves_windowed_ordinary_path_bytes(self):
        import hashlib
        # Step4g deliberately changes ordinary DRAFT behavior too. Pin the
        # windowed path, including all reads/receipts; normalize only TEMP.
        with patch.object(time, 'time', return_value=100.0), patch.object(time, 'monotonic', return_value=10.0), \
                patch.object(entry, 'MixedCoordination', side_effect=AssertionError('opt-in only')):
            self.setUp()
            self.run_mocked_path()
            value = {'events': self.e.events, 'gestures': self.d.gestures, 'observations': self.d.observations,
                     'stages': self.d.stages, 'preparation': self.d.preparation}
            encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).replace(
                json.dumps(self.temp)[1:-1], '<TEMP>').encode()
            self.assertEqual(hashlib.sha256(encoded).hexdigest(),
                             '92d94b21b624f4a2994c074775b92213daad907e10e986851db8226e38692eee')

    def test_mixed_hold_precedes_every_lock_read_and_release_follows_native_qualification(self):
        mixed = Mock()
        def held(e, binding):
            self.assertEqual(binding['eid'], 1500)
            self.assertEqual(self.d.adb.swipe.call_count, 5)
            self.assertFalse(any(r.get('receipt', {}).get('label') == 'LOCK IN' for r in e.events))
            # Change the entire selected control position while held. A stale
            # receipt would fail or click the old point instead of qualifying anew.
            self.state = tree('LOCK IN', 'DRAFT', y=250)
        def released(binding, qualification):
            self.assertEqual(qualification['stage'], 'QUALIFIED_WORLD')
            self.assertEqual(self.d.observations['entry_binding']['world'], binding)
            self.assertEqual(self.d.adb.swipe.call_count, 6)
            return {'qualified': True}
        mixed.hold.side_effect = held
        mixed.publish.side_effect = released
        self.run_mocked_path(mixed=mixed)
        self.assertEqual(self.d.gestures[-1]['receipt']['center'], [400, 250])
        mixed.hold.assert_called_once()
        mixed.publish.assert_called_once()

    def test_mixed_hold_failure_sends_no_lock_and_never_releases(self):
        mixed = Mock()
        mixed.hold.side_effect = ValueError('mixed draft timeout fixture')
        self.e.mixed = mixed
        with self.assertRaisesRegex(sc.ClientStageFailure, 'mixed draft timeout'):
            self.run_mocked_path()
        self.assertEqual(self.d.adb.swipe.call_count, 5)
        mixed.publish.assert_not_called()

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

    def run_mocked_path(self, missing=None, background=False, mixed=None):
        # Synthetic native cadence runs the real DRAFT window without wall-time
        # sleeps. No qualification/receipt/revalidation function is mocked.
        clock = [time.monotonic()]
        def read():
            if ui.screen(self.state) == 'DRAFT':
                clock[0] += .15
            return {**copy.deepcopy(self.state), 'host_read_started': clock[0],
                    'host_read_ended': clock[0]}
        self.e.read = Mock(side_effect=read)
        self.e.timeout = 1
        if mixed is not None:
            self.e.mixed = mixed
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
        with patch.object(sc, 'verify_resolution'), \
                patch.object(entry.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(entry.time, 'sleep', side_effect=lambda seconds:
                             clock.__setitem__(0, clock[0]+seconds)):
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
        self.assertEqual(self.e.events[-1]['stage'], 'MIXED_WORLD_RELEASE' if mixed else 'QUALIFIED_WORLD')
        for gesture in self.d.gestures:
            self.assertTrue(gesture['receipt']['tree_sha256'])
            self.assertTrue(gesture['health']['lifecycle']['ready'])
        self.d.adb.back.assert_not_called()
        self.d.adb.screencap.assert_not_called()


    def transition_unknown_tree(self, labels=()):
        """Retained 4s boot-1 entry-stages.jsonl:101 root/layer vtables, small fake."""
        root = {'address': '0x763874d82000', 'parent': '0x0', 'child': '0x763866dbece0', 'next': '0x0',
                'flags': 32716, 'vtable': '0x2726260', 'events': [], 'bounds_method': '0xe02010',
                'local_bounds': '0xe020b4', 'size_method': '0xe13e54', 'anchor': [0, 0], 'origin': [0, 0],
                'scale': [0.3515195846557617, 0.3515195846557617], 'size': [960, 540],
                'resolved_size': [960, 540], 'clip': [-1, -1, -1, -1]}
        layer = {**root, 'address': '0x763866dbece0', 'parent': '0x763874d82000', 'child': '0x0',
                 'flags': 1703018444, 'vtable': '0x26ba008', 'size': [2731, 1536.1875],
                 'resolved_size': [2731, 1536.1875], 'clip': [0, 0, 960, 540]}
        nodes = [root, layer]
        for index, text in enumerate(labels):
            nodes.append({**layer, 'address': f'0x763866dbf{index:03x}', 'parent': '0x763866dbece0',
                          'flags': 32716, 'vtable': '0x2726530', 'text': text, 'size': [100, 40],
                          'resolved_size': [100, 40]})
        return {'root': '0x763874d82000', 'nodes': nodes, 'labels': list(labels),
                'traversal': {'visited': len(nodes), 'active': len(nodes), 'duration_ms': 18.7,
                              'node_limit': 4096, 'complete': True, 'root_unchanged': True},
                'host_read_started': time.monotonic(), 'host_read_ended': time.monotonic()}

    def test_post_input_label_free_unknown_after_very_easy_defers_to_wait_screen_and_clears(self):
        difficulty = tree('VERY EASY', 'DIFFICULTY')
        unknown = self.transition_unknown_tree()
        draft = tree('LOCK IN', 'DRAFT')
        reads = [difficulty, difficulty, difficulty, unknown, unknown, unknown, draft, draft]
        clock = [100.0]
        def read():
            clock[0] += .05
            state = copy.deepcopy(reads.pop(0))
            state.update(host_read_started=clock[0], host_read_ended=clock[0])
            return state
        self.e.read = Mock(side_effect=read)
        self.e.timeout = 5
        with patch.object(entry.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(entry.time, 'sleep'):
            self.e.act('VERY EASY', 'DIFFICULTY', transition=True)
            self.assertEqual(self.e._transition_pending, 'DIFFICULTY')
            settled = self.e.wait_screen('DRAFT', 'DIFFICULTY', transitions=('MENU', 'MENU_TRANSITION', 'DRAFT_WAIT'))
        self.assertIsNone(self.e._transition_pending)
        self.assertEqual(ui.screen(settled), 'DRAFT')
        self.d.adb.swipe.assert_called_once()
        transients = [r for r in self.e.events if r['stage'] == 'POST_INPUT_TRANSIENT']
        self.assertEqual(len(transients), 1)
        self.assertEqual(transients[0]['input_stage'], 'DIFFICULTY')
        self.assertEqual(transients[0]['label'], 'VERY EASY')
        self.assertEqual(transients[0]['reason'], 'post-input UNKNOWN deferred to bounded wait_screen')
        self.assertEqual(transients[0]['before']['labels'], [])
        self.assertEqual(transients[0]['after']['labels'], [])
        self.assertEqual(sum(r['stage'] == 'TRANSIENT_UNKNOWN' for r in self.e.events), 1)

    def test_post_input_unknown_with_settings_still_raises_even_when_transition_true(self):
        difficulty = tree('VERY EASY', 'DIFFICULTY')
        settings_unknown = self.transition_unknown_tree(labels=('Settings',))
        self.e.read = Mock(side_effect=[difficulty, difficulty, difficulty, settings_unknown, settings_unknown])
        self.assert_setup_failure(lambda: self.e.act('VERY EASY', 'DIFFICULTY', transition=True),
                                  'DIFFICULTY: unknown post-input screen; no further gestures')
        self.d.adb.swipe.assert_called_once()
        self.assertFalse(any(r['stage'] == 'POST_INPUT_TRANSIENT' for r in self.e.events))
        self.assertIsNone(self.e._transition_pending)

    def test_act_while_transition_pending_refuses_before_any_read_or_gesture(self):
        self.e._transition_pending = 'DIFFICULTY'
        self.assert_no_input(lambda: self.e.act('Skye', 'DRAFT', hero_id=265),
                             'DRAFT: input refused; prior transition DIFFICULTY not yet qualified')
        self.e.read.assert_not_called()

    def test_persistent_post_input_unknown_exceeds_wait_screen_bound_with_no_further_gesture(self):
        difficulty = tree('VERY EASY', 'DIFFICULTY')
        unknown = self.transition_unknown_tree()
        times = iter([10.0, 10.02, 10.04, 10.06, 10.08, 10.1, 13.0, 13.15])
        clock = [10.0]
        def read():
            clock[0] = next(times)
            state = copy.deepcopy(difficulty if len(self.d.gestures) == 0 else unknown)
            state.update(host_read_started=clock[0], host_read_ended=clock[0])
            return state
        self.e.read = Mock(side_effect=read)
        self.e.timeout = 30
        def seq():
            self.e.act('VERY EASY', 'DIFFICULTY', transition=True)
            self.e.wait_screen('DRAFT', 'DIFFICULTY', transitions=('MENU', 'MENU_TRANSITION', 'DRAFT_WAIT'))
        with patch.object(entry.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(entry.time, 'sleep'):
            self.assert_setup_failure(seq, 'DIFFICULTY->DRAFT: transient UNKNOWN bound exceeded')
        self.assertEqual(self.d.adb.swipe.call_count, 1)
        self.assertEqual(self.e._transition_pending, 'DIFFICULTY')
        self.e.read.reset_mock()
        with self.assertRaisesRegex(ValueError, 'prior transition DIFFICULTY not yet qualified'):
            self.e.act('Skye', 'DRAFT', hero_id=265)
        self.e.read.assert_not_called()
        self.assertEqual(self.d.adb.swipe.call_count, 1)

    def test_hero_select_without_transition_still_raises_on_post_input_unknown(self):
        unknown = self.transition_unknown_tree()
        self.scroll_fixture([i*.15 for i in range(31)], after_scroll=False,
                            mutate=lambda state, i: state.update(root=unknown['root'], labels=[], nodes=unknown['nodes'],
                                                                 traversal=unknown['traversal']) if i >= 29 else None)
        self.assert_setup_failure(lambda: self.e.act('Skye', 'DRAFT', hero_id=265),
                                  'DRAFT: unknown post-input screen; no further gestures')
        self.assertEqual(self.d.adb.swipe.call_count, 1)
        self.assertFalse(any(r['stage'] == 'POST_INPUT_TRANSIENT' for r in self.e.events))
        self.assertIsNone(self.e._transition_pending)


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

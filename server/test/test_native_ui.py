"""Narrow geometry-free protected pulse classification; no reversal premise."""
import copy
import unittest

from Tools import native_ui as ui
from server.test import test_nonvisual_entry as fixtures

tree = fixtures.tree


class ProtectedPulseTests(unittest.TestCase):
    def pair(self):
        a = tree('Skye', 'DRAFT')
        b = copy.deepcopy(a)
        b['nodes'][2]['flags'] ^= 2
        return a, b

    def qualify(self, a, b):
        return ui.qualify_pair(a, b, 'Skye', 'DRAFT', hero_id=265)

    def leaf(self, state, **changes):
        leaf = {**copy.deepcopy(state['nodes'][1]), 'address': 'leaf', 'text': '', 'flags': 76,
                **changes}
        state['nodes'].append(leaf)
        state['traversal'].update(visited=4, active=4)
        return leaf

    def test_pulse_and_rev4_leaf_compose_but_geometry_still_refuses(self):
        a, b = self.pair()
        self.leaf(a)
        self.leaf(b, flags=204)
        pair = self.qualify(a, b)['pair']
        self.assertEqual({d['classification'] for d in pair['tolerated_differences']},
                         {'PULSE_0x2', 'UNCLASSIFIED'})
        self.assertEqual(pair['tolerated_difference_count'], 2)
        b['nodes'][-1]['origin'][0] += 1
        with self.assertRaises(ui.ControlMutation):
            self.qualify(a, b)

    def test_signature_preserves_rev4_boundaries_and_uses_existing_predicate(self):
        sig = lambda s: ui.protected_signature(s, 'Skye', 'DRAFT', hero_id=265)
        for field, value in (('flags', 72), ('text', 'decoration'), ('events', [{'type': 1}]),
                             ('child', 'label'), ('origin', [401, 200])):
            with self.subTest(field=field):
                a = tree('Skye', 'DRAFT')
                self.leaf(a)
                b = copy.deepcopy(a)
                b['nodes'][-1].update(flags=204)
                self.assertEqual(sig(a), sig(b))
                b['nodes'][-1][field] = value
                self.assertNotEqual(sig(a), sig(b))
        a = tree('Skye', 'DRAFT')
        self.leaf(a)
        b = copy.deepcopy(a)
        b['nodes'][-1]['flags'] = 204
        with fixtures.patch.object(ui, 'unclassified_leaf_flags', return_value=False) as predicate:
            self.assertNotEqual(sig(a), sig(b))
            self.assertTrue(predicate.called)

    def test_rev4_pattern_on_overlapping_non_descendant_or_nonleaf_is_not_masked(self):
        for changes in ({'parent': 'root'}, {'child': 'label'}, {'text': 'decoration'},
                        {'events': [{'type': 1}]}, {'flags': 92}):
            with self.subTest(changes=changes):
                a = tree('Skye', 'DRAFT')
                self.leaf(a, **changes)
                b = copy.deepcopy(a)
                b['nodes'][-1]['flags'] ^= 128
                self.assertNotEqual(ui.protected_signature(a, 'Skye', 'DRAFT', hero_id=265),
                                    ui.protected_signature(b, 'Skye', 'DRAFT', hero_id=265))
                with self.assertRaises(ui.ControlMutation):
                    self.qualify(a, b)

    def test_ancestor_set_and_clear_are_recorded_without_a_future_read(self):
        a, b = self.pair()
        for left, right in ((a,b),(b,a)):
            with self.subTest(flags=right['nodes'][2]['flags']):
                pair = self.qualify(left,right)['pair']
                self.assertEqual(pair['tolerated_difference_count'],1)
                d = pair['tolerated_differences'][0]
                self.assertEqual((d['address'],d['classification'],d['xor']), ('root','PULSE_0x2',2))

    def test_overlap_pulse_is_tolerated_and_signature_masks_only_bit_two(self):
        a = tree('Skye','DRAFT')
        fixtures.PairQualificationTests().outside_node(a,x=400)['origin'][1] = 200
        b = copy.deepcopy(a)
        b['nodes'][-1]['flags'] ^= 2
        self.assertEqual(self.qualify(a,b)['pair']['tolerated_differences'][0]['classification'],'PULSE_0x2')
        original = copy.deepcopy(b)
        sig = lambda s: ui.protected_signature(s,'Skye','DRAFT',hero_id=265)
        self.assertEqual(sig(a),sig(b))
        self.assertEqual(b,original)
        b['nodes'][-1]['flags'] ^= 1
        self.assertNotEqual(sig(a),sig(b))

    def test_same_node_geometry_or_any_other_protected_change_refuses(self):
        for node,field,value in ((2,'origin',[1,0]),(0,'origin',[401,200]),
                                 (0,'flags',29),(1,'text','changed')):
            with self.subTest(node=node,field=field):
                a,b = self.pair()
                b['nodes'][node][field] = value
                with self.assertRaises(ValueError):
                    self.qualify(a,b)

    def test_selected_control_pulse_and_other_bits_refuse(self):
        for node,xor in ((0,2),(2,3),(2,6),(2,4),(2,8),(2,16)):
            with self.subTest(node=node,xor=xor):
                a = tree('Skye','DRAFT')
                b = copy.deepcopy(a)
                b['nodes'][node]['flags'] ^= xor
                with self.assertRaises(ValueError):
                    self.qualify(a,b)
                try:
                    sig_a = ui.protected_signature(a,'Skye','DRAFT',hero_id=265)
                    sig_b = ui.protected_signature(b,'Skye','DRAFT',hero_id=265)
                except ValueError:
                    pass  # Invalid control cannot qualify even structurally.
                else:
                    self.assertNotEqual(sig_a,sig_b)

    def test_other_overlap_flag_disqualifies_the_whole_pulse_pair(self):
        a,b = self.pair()
        fixtures.PairQualificationTests().outside_node(a,x=400)['origin'][1] = 200
        b['nodes'].append(copy.deepcopy(a['nodes'][-1]))
        b['traversal'] = copy.deepcopy(a['traversal'])
        b['nodes'][-1]['flags'] ^= 0x180
        with self.assertRaises(ui.ControlMutation):
            self.qualify(a,b)


if __name__ == '__main__':
    unittest.main()

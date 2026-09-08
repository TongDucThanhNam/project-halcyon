"""Visibility publication and independent native reveal/targeting evidence."""
import copy
import os
import struct
import unittest

from server.actor_slots import ActorSlots
from server import combat
from server.hero_movement import HeroMovement
from server.structures import Structure
from server.vision import Vision, VisionRules, VisibilityUpdate, parse_visibility
from server.wave import Minion
from server.test.test_corpus import VGFULL_PCAP, _cached_frames
from server.test.test_item_input import CAPTURE, item_capture
from Tools.Teardown.inspect_visibility import initial_hero_banks, inspect


def decoded(frames):
    return {(update.eid, update.viewer_index): update.values
            for opcode, payload in frames if opcode == 1067
            for update in (parse_visibility(payload),)}


class TestVision(unittest.TestCase):
    def setUp(self):
        self.left = HeroMovement(1500, 1, x=0, y=40)
        self.right = HeroMovement(1517, 2, x=3, y=40)
        self.entities = {1517: self.right, 1500: self.left}
        self.vision = Vision()

    def test_nearby_heroes_receive_native_ordinary_visibility_and_only_changes_repeat(self):
        fields = decoded(self.vision.update(0, self.entities))
        self.assertEqual(fields, {(1500, 1): (1, 15, 0), (1500, 2): (1, 1, 0),
                                  (1517, 1): (1, 1, 0), (1517, 2): (1, 15, 0)})
        self.assertFalse(self.vision.update(.05, self.entities))
        self.right.x = 12
        self.assertFalse(self.vision.update(.1, self.entities))  # inclusive fixed-point boundary
        self.right.x = 12.000001
        hidden = decoded(self.vision.update(.15, self.entities))
        self.assertEqual(hidden, {(1500, 2): (1, 0, 0), (1517, 1): (1, 0, 0)})
        self.right.x = 3
        visible = decoded(self.vision.update(.2, self.entities))
        self.assertEqual(visible, {(1500, 2): (1, 1, 0), (1517, 1): (1, 1, 0)})

    def test_allied_minions_and_living_turrets_share_sight_but_crystals_and_dead_observers_do_not(self):
        self.right.x = 40
        minion = Minion(4611, 1, 0)
        minion.x, minion.y = 35, 40
        turret = Structure(3545, 'test-turret', 1, 35, 40, 1000, 1000, 1)
        crystal = Structure(3550, 'test-crystal', 1, 35, 40, 1000, 1000, 5, is_crystal=True)
        for actor, reveals in ((minion, True), (turret, True), (crystal, False)):
            with self.subTest(actor=type(actor).__name__, crystal=getattr(actor, 'is_crystal', False)):
                vision = Vision()
                entities = {**self.entities, actor.eid: actor}
                self.assertEqual(decoded(vision.update(0, entities))[1517, 1], (1, int(reveals), 0))
                if isinstance(actor, Minion):
                    actor.alive = False
                else:
                    actor.is_alive = False
                vision.update(.05, entities)
                self.assertEqual(vision.values[1517, 1], (1, 0, 0))

    def test_corpses_stay_visible_to_nearby_living_observers_and_their_own_team(self):
        self.vision.update(0, self.entities)
        self.right.hp, self.right.is_alive = 0, False
        changed = decoded(self.vision.update(.05, self.entities))
        self.assertNotIn((1517, 1), changed)
        self.assertEqual(self.vision.values[1517, 1], (1, 1, 0))
        self.assertEqual(self.vision.values[1517, 2], (1, 15, 0))
        self.assertEqual(changed[1500, 2], (1, 0, 0))  # corpse stops providing sight
        self.left.x = -20
        self.assertEqual(decoded(self.vision.update(.1, self.entities))[1517, 1], (1, 0, 0))

    def test_expiring_target_reveal_is_team_specific_and_requires_a_living_observer(self):
        self.right.x = 30
        self.left.revealed_targets = {1517: 1.0}
        fields = decoded(self.vision.update(0, self.entities))
        self.assertEqual(fields[1517, 1], (1, 1, 0))
        self.assertEqual(fields[1500, 2], (1, 0, 0))
        self.assertFalse(self.vision.update(.95, self.entities))
        self.assertEqual(decoded(self.vision.update(1.0, self.entities))[1517, 1], (1, 0, 0))
        self.left.revealed_targets[1517] = 2.0
        self.assertEqual(decoded(self.vision.update(1.05, self.entities))[1517, 1], (1, 1, 0))
        self.left.hp, self.left.is_alive = 0, False
        self.assertEqual(decoded(self.vision.update(1.1, self.entities))[1517, 1], (1, 0, 0))

    def test_actor_slots_exclude_future_and_removed_actors_without_post_removal_packets(self):
        slots = ActorSlots(reserved_slots=())
        slots.allocate(1500)
        vision = Vision(actor_slots=slots)
        fields = decoded(vision.update(0, self.entities))
        self.assertEqual({eid for eid, _ in fields}, {1500})
        slots.allocate(1517)
        vision.update(.05, self.entities)
        slots.release(1517)
        removed = decoded(vision.update(.1, self.entities))
        self.assertEqual(removed, {(1500, 2): (1, 0, 0)})
        self.assertFalse(any(eid == 1517 for eid, _ in vision.values))
        slots.allocate(1517)
        recreated = decoded(vision.update(.15, self.entities))
        self.assertEqual({eid for eid, _ in recreated}, {1500, 1517})
        self.assertEqual(recreated[1517, 1], (1, 1, 0))
        future = Minion(4610, 2, 1.0)
        slots.allocate(future.eid)
        entities = {**self.entities, future.eid: future}
        self.assertFalse(vision.update(.2, entities))
        self.assertIn((4610, 1), decoded(vision.update(1.0, entities)))

    def test_removed_dictionary_members_are_pruned_and_snapshot_is_pure(self):
        self.vision.update(0, self.entities)
        before = copy.deepcopy((self.vision.values, self.vision._last_update_at,
                                vars(self.left), vars(self.right)))
        snapshot = self.vision.snapshot_frames()
        self.assertEqual(decoded(snapshot), self.vision.values)
        self.assertEqual(before, (self.vision.values, self.vision._last_update_at,
                                  vars(self.left), vars(self.right)))
        self.assertEqual(list(decoded(snapshot)), [(1500, 1), (1500, 2), (1517, 1), (1517, 2)])
        self.vision.update(.05, {1500: self.left})
        self.assertFalse(any(eid == 1517 for eid, _ in self.vision.values))

    def test_same_entity_state_produces_identical_bytes_independent_of_mapping_order(self):
        one, two = Vision(VisionRules(radius=8)), Vision(VisionRules(radius=8))
        self.assertEqual(one.update(0, self.entities), two.update(0, dict(reversed(list(self.entities.items())))))
        self.right.x = 9
        self.assertEqual(one.update(.05, self.entities), two.update(.05, list(reversed(list(self.entities.values())))))

    def test_malformed_visibility_fields_and_policy_are_rejected(self):
        valid = VisibilityUpdate(1517, 1, (1, 1, 0)).encode()
        for invalid in (valid[:-1], valid + b'\0', valid[:-1] + b'\1', valid[:4] + b'\x08' + valid[5:]):
            with self.subTest(payload=invalid), self.assertRaises(ValueError):
                parse_visibility(invalid)
        for radius in (0, -1, float('nan'), float('inf')):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                VisionRules(radius=radius)

    def test_grid_matches_exhaustive_integer_distance_across_negative_cells_and_boundaries(self):
        actors = {}
        for index in range(48):
            x, y = (index % 8 - 4) * 6, (index // 8 - 3) * 8
            actors[1500 + index] = HeroMovement(1500 + index, 1 + index % 2, x=x, y=y)
        vision = Vision(VisionRules(radius=10))
        actual = decoded(vision.update(0, actors))
        expected = {}
        for actor in actors.values():
            x, y = actor.position_fixed
            for team in (1, 2):
                inside = any((x - observer.position_fixed[0]) ** 2 + (y - observer.position_fixed[1]) ** 2 <= 10_000_000 ** 2
                             for observer in actors.values() if combat.team(observer) == team)
                expected[actor.eid, team] = (1, 15 if actor.team == team else int(inside), 0)
        self.assertEqual(actual, expected)


@unittest.skipUnless(os.path.isfile(VGFULL_PCAP), 'external vgfull capture unavailable')
class TestNativeVisibility(unittest.TestCase):
    def test_all_5330_native_setters_rebuild_complete_payloads(self):
        frames, _ = _cached_frames()
        payloads = [payload for opcode, payload in frames if opcode == 1067]
        self.assertEqual(len(payloads), 5330)
        for payload in payloads:
            self.assertEqual(parse_visibility(payload).encode(), payload)

    def test_native_living_baptiste_reveal_hide_reveal_requires_no_resurrection(self):
        frames, _ = _cached_frames()
        for index, values in ((3342, (1, 1, 0)), (9335, (1, 0, 0)), (9959, (1, 1, 0))):
            self.assertEqual(frames[index], (1067, VisibilityUpdate(1517, 1, values).encode()))
        self.assertFalse(any(opcode in (1072, 1033) and int.from_bytes(payload[:4], 'big') == 1517
                             for opcode, payload in frames[:9960]))
        initial = next(payload for opcode, payload in frames if opcode == 1011 and int.from_bytes(payload[8:12], 'big') == 1517)
        self.assertEqual(int.from_bytes(initial[:4], 'big'), 399)
        self.assertEqual(initial_hero_banks(initial)[1], (1, 0, 0))
        self.assertEqual(initial_hero_banks(initial)[2], (1, 15, 0))

    def test_all_six_native_hero_corpses_keep_viewer_one_visibility_bit(self):
        frames, _ = _cached_frames()
        deaths = [(index, int.from_bytes(payload[:4], 'big')) for index, (opcode, payload) in enumerate(frames)
                  if opcode == 1072 and int.from_bytes(payload[:4], 'big') in (1500, 1515, 1516, 1517, 1518, 1519)]
        self.assertEqual(len(deaths), 6)
        fields = []
        for index, eid in deaths:
            payload = next(payload for opcode, payload in frames[index + 1:index + 180]
                           if opcode == 1067 and int.from_bytes(payload[:4], 'big') == eid and payload[4] == 1)
            value = parse_visibility(payload)
            self.assertEqual(value.values[1:], (1, 0))
            fields.append(value.values)
        self.assertEqual(fields.count((1, 1, 0)), 5)
        self.assertEqual(fields.count((3, 1, 0)), 1)  # brush-related first field remains distinct


@unittest.skipUnless(CAPTURE.is_file(), 'external vg5 capture unavailable')
class TestNativeTargetVisibility(unittest.TestCase):
    def test_all_22_actual_client_targets_have_received_nonzero_viewer_one_mask(self):
        frames = item_capture()
        result = inspect(frames, viewer_index=1, limit=100)
        self.assertEqual(result['click_count'], 22)
        for click in result['clicks']:
            self.assertLessEqual(click['visibility_time'], click['time'])
            self.assertIn(click['values'], ((1, 1, 0), (1, 3, 0), (1, 7, 0)))
        hero_clicks = [click for click in result['clicks'] if click['hero'] is not None]
        self.assertEqual(len(hero_clicks), 12)
        self.assertEqual(sum(click['values'] == (1, 1, 0) for click in result['clicks']), 6)
        chosen = next(click for click in hero_clicks if click['target'] == 1517)
        self.assertEqual((chosen['hero']['hero_id'], chosen['visibility_frame']), (258, 34942))

    def test_native_hero_bootstrap_initializes_owner_team_bank_fifteen_and_other_banks_zero(self):
        for row in item_capture()['s2c']:
            if row.opcode != 1011:
                continue
            payload = row.payload
            team = int.from_bytes(payload[12:16], 'big')
            self.assertEqual(initial_hero_banks(payload),
                             {viewer: (1, 15 if viewer == team else 0, 0) for viewer in range(8)})


if __name__ == '__main__':
    unittest.main()

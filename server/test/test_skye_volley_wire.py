"""Native C actor serializer joins and independent presentation lifecycle."""
import itertools
import os
from pathlib import Path
import struct
from types import SimpleNamespace
import unittest

from server import skye_wire
from server.actor_slots import ActorSlots


CORPUS = Path(os.environ.get('TEMP', '')) / ('vg_phaseB/vgr_live/'
    'ea4c7fda-4b61-481d-abb7-1c757d24ae58-a683aa80-9811-47c3-bb64-0731a802e889.32.vgr')


def buff_kinds(frames):
    return [struct.unpack_from('>H', payload, 14)[0] for op, payload in frames if op == 1086]


@unittest.skipUnless(CORPUS.is_file(), 'external native Skye volley corpus unavailable')
class TestSkyeVolley(unittest.TestCase):
    def test_invalid_geometry_does_not_allocate_an_identity_or_compact_slot(self):
        slots = ActorSlots()
        identities = []
        def allocate():
            identities.append(2_000_000)
            return identities[-1]
        manager = skye_wire.VolleyPresentation(slots, allocate)
        with self.assertRaises(ValueError):
            manager.start(SimpleNamespace(eid=1500, team=1), (float('nan'), 3), None,
                          0, activation_at=1.3, duration=2)
        self.assertFalse(identities)
        self.assertFalse(slots.by_eid)
        self.assertFalse(manager.active)

    def test_canonical_checkpoint_contains_future_volley_timeline(self):
        from Tools.verify_sandbox import freeze_state
        from server.test.test_projectile_wire import skye_session
        world, _ = skye_session()
        world.skye_volleys.start(world.hero_sim, (4, 5), None, 0, activation_at=1.3, duration=2)
        controller = SimpleNamespace(state={})
        first = freeze_state(world, controller, 'test-mesh')
        next(iter(world.skye_volleys.active.values())).activation_at += .05
        second = freeze_state(world, controller, 'test-mesh')
        self.assertNotEqual(first, second)

    def test_both_creations_rebuild_all_native_bytes_including_owner_and_actor_slot(self):
        templates = skye_wire.native_volley_templates()
        self.assertEqual(set(templates), {384, 385})
        for archetype, payload in templates.items():
            with self.subTest(archetype=archetype):
                eid = struct.unpack_from('>I', payload, 8)[0]
                owner = struct.unpack_from('>I', payload, 112)[0]
                center = tuple(struct.unpack_from('>f', payload, i)[0] for i in (12, 20))
                facing = tuple(struct.unpack_from('>f', payload, i)[0] for i in (24, 32))
                self.assertEqual(owner, 1517)
                self.assertEqual(skye_wire.build_volley(payload, eid, owner, payload[116],
                                 payload[121], center, facing), payload)

    def test_warning_precedes_activation_and_actor_slot_survives_until_native_removal(self):
        for direction, delay_kind, active_kind in ((None, 612, 613), ((0, 1), 614, 615)):
            with self.subTest(direction=direction):
                slots = ActorSlots()
                slots.register(1500, 0)
                allocate = itertools.count(2_000_000).__next__
                manager = skye_wire.VolleyPresentation(slots, allocate)
                hero = SimpleNamespace(eid=1500, team=1)
                initial = manager.start(hero, (2, 3), direction, 0, activation_at=1.3, duration=2)
                eid = next(iter(manager.active))
                self.assertEqual(initial[0][0], 1010)
                self.assertEqual(struct.unpack_from('>I', initial[0][1], 112)[0], 1500)
                self.assertEqual(initial[0][1][116], slots.by_eid[eid])
                self.assertEqual(initial[0][1][121], 1)
                self.assertEqual(buff_kinds(initial), [61, delay_kind, 616])
                self.assertEqual(manager.step(1.05), [])
                self.assertEqual(buff_kinds(manager.step(1.1)), [617])
                self.assertEqual(manager.step(1.25), [])
                self.assertEqual(buff_kinds(manager.step(1.3)), [active_kind])
                self.assertEqual(manager.step(3.25), [])
                death = manager.step(3.3)
                self.assertEqual([op for op, _ in death], [1072, 1086])
                self.assertIn(eid, slots.by_eid)
                self.assertEqual(manager.step(7.05), [])
                removed = manager.step(7.1)
                self.assertEqual([op for op, _ in removed], [1073, 1035])
                self.assertNotIn(eid, slots.by_eid)
                self.assertFalse(manager.active)
                self.assertEqual(manager.step(8), [])


if __name__ == '__main__':
    unittest.main()

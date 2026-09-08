"""Native structure creation and retained live/corpse reconnect state."""
import os
from pathlib import Path
import struct
import unittest

from server import entity_spawn, roster, wave
from server.actor_slots import ActorSlots
from server.structures import StructureManager


def original_native_catalog():
    """Authored test records; unknown bytes are deliberately not corpus bytes."""
    templates = []
    families = ((entity_spawn.STRUCTURE_ARCHETYPES, entity_spawn.STRUCTURE_CLASS),
                (entity_spawn.LANE_ARCHETYPES, entity_spawn.LANE_CLASS))
    for archetypes, entity_class in families:
        for archetype in archetypes:
            for team in (1, 2):
                for size in (122, 126):
                    body = bytearray(size)
                    struct.pack_into('>IIIfff', body, 0, archetype, entity_class, 90000, 1, 0.125, 2)
                    body[88:96] = b'original'
                    body[116], body[121] = 8, team
                    if size == 122:
                        struct.pack_into('>ff', body, 36, 100, 200)
                    templates.append(entity_spawn.NativeActorTemplate(bytes(body), 'authored-test-data'))
    return entity_spawn.NativeActorCatalog(templates)


class TestNativeActorCatalog(unittest.TestCase):
    def setUp(self):
        self.catalog = original_native_catalog()

    def test_creation_and_snapshot_have_distinct_shapes_and_same_actor_slot_offset(self):
        creation = self.catalog.build(371, 3539, 30, 4, 33, team=2)
        snapshot = self.catalog.build(371, 3539, 30, 4, 33, team=2, snapshot=True, hp=(15, 2500))
        for payload, size in ((creation, 126), (snapshot, 122)):
            self.assertEqual(len(payload), size)
            self.assertEqual(struct.unpack_from('>III', payload), (371, entity_spawn.STRUCTURE_CLASS, 3539))
            self.assertEqual(payload[116], 33)
            self.assertEqual(payload[88:96], b'original')
            self.assertEqual(struct.unpack_from('>f', payload, 16)[0], 0.125)
        self.assertEqual(struct.unpack_from('>ff', snapshot, 36), (15, 2500))
        with self.assertRaisesRegex(ValueError, 'no HP fields'):
            self.catalog.build(371, 3539, 30, 4, 33, team=2, hp=(15, 2500))

    def test_missing_archetype_team_form_is_never_faked(self):
        for kwargs in ({'team': 0}, {'team': 1, 'snapshot': True, 'hp': (-1, 100)},
                       {'team': 1, 'snapshot': True, 'hp': (200, 100)}):
            with self.assertRaises(ValueError):
                self.catalog.build(371, 3539, 0, 0, 33, **kwargs)
        with self.assertRaises(ValueError):
            self.catalog.build(924, 3539, 0, 0, 33, team=1)
        with self.assertRaises(ValueError):
            self.catalog.build(371, 1500, 0, 0, 33, team=1)

    def test_structure_reconnect_keeps_ids_slots_damage_and_destroyed_state(self):
        slots = ActorSlots()
        manager = StructureManager(spawn_catalog=self.catalog, actor_slots=slots)
        creations = manager.get_spawn_1010_frames()
        initial_slots = slots.by_eid.copy()
        manager.structures[3539].hp = 123
        manager.structures[3540].hp, manager.structures[3540].is_alive = 0, False
        second = manager.get_spawn_1010_frames()
        states = dict((struct.unpack_from('>I', p, 8)[0], p) for _, p in manager.get_state_1010_frames())
        self.assertEqual(creations, second)
        self.assertEqual(initial_slots, slots.by_eid)
        self.assertEqual(set(states), set(manager.structures))
        self.assertEqual(struct.unpack_from('>ff', states[3539], 36), (123, 2500))
        self.assertEqual(struct.unpack_from('>ff', states[3540], 36), (0, 3000))
        self.assertFalse(manager.structures[3540].is_alive)

    def test_minion_reconnect_keeps_live_position_hp_and_retained_corpse_then_excludes_removed(self):
        director = wave.Director(0, combat=False)
        director._spawn_pair(0, 0)
        alive, dead = director.minions
        alive.x, alive.y, alive.hp = 25, 6, 123
        director.on_minion_death(dead, 1500, 1)
        before = (director.next_minion, director.wave_index, director.pending_pairs.copy(), director.actor_slots.by_eid.copy())
        creations = director.get_spawn_frames(1)
        states = director.get_state_1010_frames(1, catalog=self.catalog)
        deaths = director.get_death_frames(1)
        self.assertEqual((director.next_minion, director.wave_index, director.pending_pairs, director.actor_slots.by_eid), before)
        self.assertEqual([struct.unpack_from('>I', p, 8)[0] for op, p in creations if op == 1010], [alive.eid, dead.eid])
        self.assertEqual([op for op, p in creations if op != 1016 and struct.unpack_from('>I', p, 8 if op == 1010 else 0)[0] == dead.eid], [1010])
        self.assertEqual([struct.unpack_from('>ff', p, 36) for _, p in states], [(123, alive.max_hp), (0, dead.max_hp)])
        self.assertEqual(deaths, [(1072, struct.pack('>II6x', dead.eid, 1500))])
        director._flush_removals(5)
        self.assertEqual(len([op for op, _ in director.get_spawn_frames(5) if op == 1010]), 1)
        self.assertEqual(director.get_death_frames(5), [])
        self.assertNotIn(dead.eid, director.actor_slots.by_eid)


EXTERNAL_CORPUS = Path(os.environ.get('TEMP', '.')) / 'vg_phaseB' / 'vgr_live'


@unittest.skipUnless(EXTERNAL_CORPUS.is_dir(), 'external native actor corpus unavailable')
class TestExternalNativeActors(unittest.TestCase):
    def test_all_external_static_creation_and_snapshot_templates_reproduce_exactly(self):
        catalog = entity_spawn.load_native_actor_catalog(EXTERNAL_CORPUS)
        count = 0
        for (archetype, team, size), placements in catalog.templates.items():
            if archetype not in entity_spawn.STRUCTURE_ARCHETYPES:
                continue
            for template in placements.values():
                payload = template.payload
                rebuilt = catalog.build(archetype, struct.unpack_from('>I', payload, 8)[0],
                    *template.position, payload[116], team=team, snapshot=size == 122,
                    hp=template.health)
                self.assertEqual(rebuilt, payload)
                count += 1
        self.assertEqual(count, 24)

    def test_every_measured_vain_turret_template_has_3000_maximum_hp(self):
        catalog = entity_spawn.load_native_actor_catalog(EXTERNAL_CORPUS)
        templates = [t for (archetype, _, size), entries in catalog.templates.items()
                     if archetype == 372 and size == 122 for t in entries.values()]
        self.assertEqual(len(templates), 4)
        self.assertTrue(all(t.health[1] == 3000 for t in templates))


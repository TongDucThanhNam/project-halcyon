"""Unit creation fields and byte-exact reproduction of external jungle spawns."""
import os
from pathlib import Path
import struct
import unittest

from server import entity_spawn, jungle, roster, wire
from server.hero_movement import HeroMovement


def original_test_catalog():
    """Original synthetic serializer tails, deliberately unlike corpus bytes."""
    templates = {}
    for archetype in (357, 359, 360, 362, 363):
        body = bytearray(126)
        struct.pack_into('>III', body, 0, archetype, entity_spawn.JUNGLE_CLASS, 98765)
        struct.pack_into('>fff', body, 12, 1, roster.GROUND_Z, 2)
        struct.pack_into('>fff', body, 24, 0, 0, 1)
        body[88:96] = b'original'
        body[96] = 1
        body[112:116] = bytes((255,)) * 4
        body[117:122] = bytes((1, 0, 1, 255, 0))
        templates[archetype] = entity_spawn.SpawnTemplate(archetype, bytes(body), 'original-test-data')
    return entity_spawn.SpawnCatalog(templates)


def original_jungle_state_catalog():
    """Authored neutral snapshot records for testing gated capture adaptation."""
    templates = []
    for archetype in (357, 359, 360, 362, 363):
        body = bytearray(122)
        struct.pack_into('>IIIfff', body, 0, archetype, entity_spawn.JUNGLE_CLASS, 98765, 1, 0.125, 2)
        struct.pack_into('>ff', body, 36, 123, 456)
        body[88:96] = b'original'
        body[96], body[120] = 15, 255
        templates.append(entity_spawn.NativeActorTemplate(bytes(body), 'original-test-state'))
    return entity_spawn.NativeActorCatalog(templates)


class TestNonheroSpawn(unittest.TestCase):
    def setUp(self):
        self.catalog = original_test_catalog()

    def test_mutable_identity_position_and_sequence_are_encoded_at_measured_offsets(self):
        payload = self.catalog.build(357, 100003, -40.9, 20.3, 37)
        self.assertEqual(struct.unpack_from('>III', payload), (357, entity_spawn.JUNGLE_CLASS, 100003))
        self.assertAlmostEqual(struct.unpack_from('>f', payload, 12)[0], -40.9, places=4)
        self.assertAlmostEqual(struct.unpack_from('>f', payload, 20)[0], 20.3, places=4)
        self.assertEqual(payload[116], 37)
        self.assertEqual(payload[88:96], b'original')
        with self.assertRaises(ValueError):
            self.catalog.build(357, 100003, 0, 0, 257)

    def test_hero_and_non_jungle_archetypes_are_rejected(self):
        with self.assertRaises(ValueError):
            self.catalog.build(357, 1500, 0, 0, 0)
        with self.assertRaises(ValueError):
            self.catalog.build(924, 100003, 0, 0, 0)

    def test_unmeasured_capture_requires_explicit_experiment(self):
        with self.assertRaises(ValueError):
            self.catalog.build(364, 100003, 0, 0, 0, team=1)
        payload = self.catalog.build(364, 100003, 0, 0, 0, team=1, experimental_capture=True)
        self.assertEqual(struct.unpack_from('>I', payload)[0], 364)
        self.assertEqual(payload[96:99], bytes((0, 1, 0)))
        # +120 is actor-specific (native Crystal Miners4/5, ownedshops255),
        # not a team-minus-one ownership byte. Preserve its neutral template.
        self.assertEqual(payload[120:122], bytes((255, 1)))

    def test_neutral_miner_faction_mutation_requires_explicit_experiment(self):
        with self.assertRaises(ValueError):
            self.catalog.build(362, 100003, 0, 0, 0, team=2)

    def test_opaque_word_override_has_exactly_four_bytes(self):
        payload = self.catalog.build(357, 100003, 0, 0, 0, opaque_word=b'test')
        self.assertEqual(payload[92:96], b'test')
        with self.assertRaises(ValueError):
            self.catalog.build(357, 100003, 0, 0, 0, opaque_word=b'bad')

    def test_bootstrap_spawns_every_living_camp_actor_with_shared_sequence(self):
        manager = jungle.JungleManager()
        sequence = [32]
        frames = manager.get_spawn_frames(sequence, catalog=self.catalog)
        spawns = [body for opcode, body in frames if opcode == wire.OP.ENTITY_FULL_UPDATE]
        self.assertEqual(len(spawns), 12)
        self.assertEqual({struct.unpack_from('>I', body, 8)[0] for body in spawns}, set(manager.monsters))
        self.assertEqual(sequence[0], 44)
        self.assertEqual([body[116] for body in spawns], list(range(33, 45)))
        self.assertTrue(all(struct.unpack_from('>I', body, 4)[0] == entity_spawn.JUNGLE_CLASS for body in spawns))

    def test_respawn_includes_real_actor_creation_before_position(self):
        manager = jungle.JungleManager()
        manager.get_spawn_frames(catalog=self.catalog)
        treant = next(m for m in manager.monsters.values() if m.camp_id == 'LCampA')
        manager.apply_damage_to_monster(treant.eid, treant.hp, HeroMovement(), 0)
        frames = manager.step(0.05, 85, {})
        living = next(m for m in manager.monsters.values() if m.camp_id == 'LCampA' and m.is_alive)
        self.assertNotEqual(living.eid, treant.eid)
        spawn = next(i for i, (op, p) in enumerate(frames) if op == 1010 and struct.unpack_from('>I', p, 8)[0] == living.eid)
        position = next(i for i, (op, p) in enumerate(frames) if op == 1070 and struct.unpack_from('>I', p)[0] == living.eid)
        self.assertLess(spawn, position)

    def test_experimental_capture_replaces_neutral_with_fresh_owned_actor(self):
        manager = jungle.JungleManager(state_catalog=original_jungle_state_catalog())
        manager.get_spawn_frames(catalog=self.catalog, experimental_capture=True)
        manager.step(0.05, 900, {})
        kraken = manager.active_kraken
        old_eid = kraken.eid
        frames = manager.apply_damage_to_monster(old_eid, kraken.hp, HeroMovement(), 901)
        self.assertNotEqual(kraken.eid, old_eid)
        self.assertIn(old_eid, manager.monsters)
        self.assertFalse(manager.monsters[old_eid].is_alive)
        self.assertEqual([op for op, _ in frames], [1072, 1010, 1010, 1070])
        creation, snapshot = frames[1][1], frames[2][1]
        self.assertEqual(struct.unpack_from('>I', creation)[0], 364)
        self.assertEqual(struct.unpack_from('>I', creation, 8)[0], kraken.eid)
        self.assertEqual(creation[121], 1)
        self.assertEqual((len(creation), len(snapshot)), (126, 122))
        self.assertEqual(struct.unpack_from('>ff', snapshot, 36), (5000, 5000))
        self.assertEqual(creation[116], snapshot[116])
        self.assertNotEqual(manager.actor_slots.by_eid[old_eid], creation[116])
        manager.step(0.05, 905, {})
        self.assertNotIn(old_eid, manager.monsters)
        self.assertNotIn(old_eid, manager.actor_slots.by_eid)

    def test_missing_external_evidence_fails_actionably(self):
        with self.assertRaisesRegex(FileNotFoundError, 'HALCYON_SPAWN_CORPUS'):
            entity_spawn.load_spawn_catalog('missing-original-corpus')


EXTERNAL_CORPUS = Path(os.environ.get('TEMP', '.')) / 'vg_phaseB' / 'vgr_live'


@unittest.skipUnless(EXTERNAL_CORPUS.is_dir(), 'external jungle spawn corpus unavailable')
class TestExternalJungleSpawn(unittest.TestCase):
    def test_neutral_archetype_builders_reproduce_complete_captured_payloads(self):
        catalog = entity_spawn.load_spawn_catalog(EXTERNAL_CORPUS)
        self.assertTrue(entity_spawn.REQUIRED_NEUTRAL_ARCHETYPES <= catalog.templates.keys())
        for archetype, template in catalog.templates.items():
            with self.subTest(archetype=archetype):
                body = template.payload
                eid = struct.unpack_from('>I', body, 8)[0]
                x, _, y = struct.unpack_from('>fff', body, 12)
                facing = struct.unpack_from('>f', body, 24)[0], struct.unpack_from('>f', body, 32)[0]
                rebuilt = catalog.build(archetype, eid, x, y, body[116], team=body[121], facing=facing)
                self.assertEqual(rebuilt, body)

    def test_actual_kraken_template_uses_observed_neutral_archetype_and_class(self):
        catalog = entity_spawn.load_spawn_catalog(EXTERNAL_CORPUS)
        payload = catalog.build(363, 100050, 0, 23.6, 40)
        self.assertEqual(struct.unpack_from('>III', payload), (363, 0x4DD5B7D0, 100050))
        self.assertEqual(len(payload), 126)
        self.assertEqual(payload[121], 0)

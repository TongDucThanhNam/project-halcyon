"""Built-in CC presentation from native action input and owned metadata/replays.

The silence replay is Vox: it proves the shared buff primitive, not Catherine's
cast geometry or timing. Catherine's own duration is joined from her CFF record.
"""
import pickle
import struct
import unittest

from server.paths import pc_data_dir, research_dir
from server import abilities, buff_wire, jungle, match_server, roster, wave, wire
from server.navigation import NavMesh
from server.status_effects import StatusEffect, StatusType
from Tools.Teardown.inspect_ability_constants import (
    FIRST_REVISION_ENTRY, LAST_REVISION_ENTRY, decode_inst, read_records,
)
from Tools.Teardown.inspect_kindred_registry import registry_entries


DATA = pc_data_dir()
BUFF_REGISTRY = DATA / '55/551BCB541D80053BACD0A897B7993A77'
CATHERINE = DATA / '98/98B6FF5C43A2EB13831F4EAD75CD0886'
VOX_REPLAY = research_dir('vg_max') / 'vgr5frames.pkl'


def revisions(path):
    raw = path.read_bytes()
    groups, current = [], {}
    offset = struct.unpack_from('<I', raw, 20)[0]
    while offset + 8 <= len(raw):
        tag, size = struct.unpack_from('<4sI', raw, offset)
        if size < 8 or offset + size > len(raw):
            raise AssertionError('invalid owned CFF chunk')
        current[tag] = raw[offset + 8:offset + size]
        if tag == b'SYMB':
            groups.append(current)
            current = {}
        offset += size
    if current:
        groups.append(current)
    return raw, groups


def session(hero_id=242, target_id=395, rank=1, slot=abilities.AbilitySlot.ULT):
    mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                   [(0, 1, 2), (0, 2, 3)])
    players = roster.default_solo_bots('cc-owner', 'cc-match')
    players = [players[0], players[3]]
    players[0].hero_id, players[1].hero_id = hero_id, target_id
    for player in players:
        player.is_bot = False
    owner, observer = object(), object()
    frames, observer_frames = [], []
    world = match_server.SnapshotStream(owner, players, 'cc-match',
        lambda op, payload: frames.append((op, payload)), log=lambda _: None,
        navigation_mesh=mesh)
    world.clients[observer] = (players[1], lambda op, payload: observer_frames.append((op, payload)))
    world._finalize()
    for index, hero in enumerate(world.hero_sims.values()):
        hero.teleport(index * 5, 0)
        hero.hp = hero.max_hp = 10000
        hero.energy = hero.max_energy = 1000
    world.jungle = jungle.JungleManager(open_time=1000000)
    world.wave_director = wave.Director(1000000)
    world.structures.structures.clear()
    world.phase = world.WORLD
    kit = world.hero_kits[1500]
    for _ in range(rank):
        if not kit.upgrade_ability(slot, 12):
            raise AssertionError('test ability could not be learned')
    for target_slot in (abilities.AbilitySlot.A, abilities.AbilitySlot.B):
        world.hero_kits[1517].upgrade_ability(target_slot, 12)
    frames.clear()
    observer_frames.clear()
    return world, frames, observer_frames, owner, observer


def adds(frames, kind):
    return [buff for op, payload in frames if op == 1086
            for buff in (buff_wire.parse_buff_add(payload),) if buff.kind == kind]


def ground_cast(world, owner, action=3, x=5, y=0):
    world._apply_event(wire.OP.GROUND_CAST, struct.pack('>fffBB', x, 0, y, action, 0), owner)


def advance_to(world, deadline):
    while world.sim_time + 1e-9 < deadline:
        world.advance_simulation()


class NativeCCEvidenceTests(unittest.TestCase):
    @unittest.skipUnless(BUFF_REGISTRY.is_file(), 'operator-owned KindredBuffs CFF unavailable')
    def test_both_registry_revisions_distinguish_builtin_silence_from_item_silence(self):
        raw, groups = revisions(BUFF_REGISTRY)
        first = decode_inst(groups[0][b'INST'], FIRST_REVISION_ENTRY)
        entries = registry_entries(raw, first)
        self.assertEqual({name: entries[name] for name in ('Buff_Stunned', 'Buff_ItemSilence', 'Buff_Silence')},
                         {'Buff_Stunned': 22, 'Buff_ItemSilence': 31, 'Buff_Silence': 32})
        last = groups[-1]
        plain = decode_inst(last[b'INST'], LAST_REVISION_ENTRY)
        count = struct.unpack_from('<I', last[b'PTCH'])[0]
        refs = dict(struct.unpack_from('<II', last[b'PTCH'], 8 + i * 8) for i in range(count))
        self.assertEqual(refs[0], 8)
        for kind, name in ((22, 'Buff_Stunned'), (31, 'Buff_ItemSilence'), (32, 'Buff_Silence')):
            name_at = refs[refs[8 + 8 * kind]]
            self.assertEqual(plain[name_at:plain.index(b'\0', name_at)].decode('ascii').strip('*'), name)

    @unittest.skipUnless(CATHERINE.is_file(), 'operator-owned Catherine CFF unavailable')
    def test_catherine_duration_comes_from_her_own_native_record(self):
        self.assertEqual(read_records(CATHERINE, {'silenceduration'}),
                         [{'name': 'SilenceDuration', 'pointer_offset': 4332,
                           'coefficients': [1.5, 0.5, 0.0, 0.0, 0.0, 0.0]}])
        _, groups = revisions(CATHERINE)
        first = groups[0]
        count = struct.unpack_from('<I', first[b'PTCH'])[0]
        refs = dict(struct.unpack_from('<II', first[b'PTCH'], 8 + i * 8) for i in range(count))
        # Native C action 3 -> definition -> property vector -> SilenceDuration.
        self.assertEqual((refs[1108], refs[3768], refs[4124]), (3628, 4112, 4332))
        last = decode_inst(groups[-1][b'INST'], LAST_REVISION_ENTRY)
        self.assertEqual(struct.unpack_from('<6f', last, 5200), (1.5, 0.5, 0, 0, 0, 0))

    @unittest.skipUnless(VOX_REPLAY.is_file(), 'operator-owned Vox replay unavailable')
    def test_shared_silence_primitive_matches_native_1086_goldens(self):
        frames = pickle.loads(VOX_REPLAY.read_bytes())
        for index, target, duration, instance in ((45015, 1515, 0.599609375, 13469),
                                                   (93229, 1516, 0.7998046875, 21489)):
            opcode, payload = frames[index]
            self.assertEqual(opcode, 1086)
            self.assertEqual(payload, buff_wire.build_buff_add(target, 1517, duration, instance, 32))


class AbilityCCSessionTests(unittest.TestCase):
    def test_catherine_c_delays_damage_and_silence_then_expires_at_each_native_rank(self):
        for rank, duration in ((1, 1.5), (2, 2.0), (3, 2.5)):
            with self.subTest(rank=rank):
                world, frames, peer, owner, _ = session(rank=rank)
                ground_cast(world, owner)
                self.assertEqual(world.hero_kits[1500].pending[0].ability.name, 'Blast Tremor')
                advance_to(world, 0.95)
                self.assertEqual(adds(frames, 32), [])
                self.assertEqual(world.hero_sims[1517].hp, 10000)
                advance_to(world, 1.0)
                buff, = adds(frames, 32)
                self.assertEqual((buff.target_eid, buff.source_eid, buff.duration), (1517, 1500, duration))
                self.assertEqual(adds(peer, 32), [buff])
                self.assertLess(world.hero_sims[1517].hp, 10000)
                manager = world.status_manager
                self.assertFalse(manager.can_cast(1517, world.sim_time))
                self.assertTrue(manager.can_move(1517, world.sim_time))
                self.assertTrue(manager.can_attack(1517, world.sim_time))
                advance_to(world, 1.0 + duration)
                self.assertTrue(manager.can_cast(1517, world.sim_time))
                self.assertFalse(any(p.instance_id == buff.instance_id for p in adds(manager.snapshot_frames(world.sim_time), 32)))
                self.assertNotIn((1093, buff_wire.build_buff_cancel(1517, buff.instance_id)), frames)

    def test_gwen_native_c_sends_builtin_stun_and_disables_all_actions(self):
        for rank, duration in ((1, 0.9), (2, 1.2), (3, 1.5)):
            with self.subTest(rank=rank):
                world, frames, _, owner, _ = session(hero_id=395, rank=rank)
                ground_cast(world, owner)
                self.assertEqual(world.hero_kits[1500].pending[0].ability.name, 'Aces High')
                advance_to(world, 0.55)
                self.assertEqual(adds(frames, 22), [])
                advance_to(world, 0.6)
                buff, = adds(frames, 22)
                self.assertEqual((buff.target_eid, buff.source_eid), (1517, 1500))
                self.assertEqual(buff.duration, struct.unpack('>e', struct.pack('>e', duration))[0])
                manager = world.status_manager
                self.assertFalse(manager.can_cast(1517, world.sim_time))
                self.assertFalse(manager.can_move(1517, world.sim_time))
                self.assertFalse(manager.can_attack(1517, world.sim_time))

    def test_cc_immunity_rejects_native_add_but_retains_ability_damage(self):
        for hero, kind, effect_type, deadline in ((242, 32, StatusType.SILENCE, 1.0),
                                                  (395, 22, StatusType.STUN, 0.6)):
            with self.subTest(hero=hero):
                world, frames, _, owner, _ = session(hero_id=hero)
                world.status_manager.apply_effect(StatusEffect('block', StatusType.CC_IMMUNITY,
                    1517, 1517, 2, 0, 2))
                ground_cast(world, owner)
                advance_to(world, deadline)
                self.assertLess(world.hero_sims[1517].hp, 10000)
                self.assertEqual(adds(frames, kind), [])
                self.assertFalse(world.status_manager.has_effect(1517, effect_type, world.sim_time))

    def test_silenced_native_cast_is_rejected_and_skedaddle_cancels_exact_instance(self):
        world, frames, _, owner, observer = session()
        ground_cast(world, owner)
        advance_to(world, 1.0)
        buff, = adds(frames, 32)
        target = world.hero_sims[1517]
        energy = target.energy
        # Gwen action 1 is an ordinary cast and must remain disabled by silence.
        ground_cast(world, observer, action=1, x=0)
        self.assertEqual(world.hero_kits[1517].pending, [])
        self.assertEqual(world.hero_kits[1517].cooldowns[0], 0)
        self.assertEqual(target.energy, energy)
        # Her action 2 is the explicit cleanse exception and removes presentation.
        world._apply_event(1041, struct.pack('>IBB', 0xffffffff, 2, 0), observer)
        self.assertTrue(world.status_manager.can_cast(1517, world.sim_time))
        self.assertEqual(frames.count((1093, buff_wire.build_buff_cancel(1517, buff.instance_id))), 1)
        ground_cast(world, observer, action=1, x=0)
        self.assertEqual(world.hero_kits[1517].pending[0].ability.name, 'Buckshot Bonanza')

    def test_reconnect_retains_silence_identity_source_and_remaining_lifetime(self):
        world, frames, _, owner, _ = session()
        ground_cast(world, owner)
        advance_to(world, 1.25)
        initial, = adds(frames, 32)
        reconnect = []
        world._dump_reconnect_state(object(), world.players[1], lambda op, p: reconnect.append((op, p)))
        restored, = adds(reconnect, 32)
        self.assertEqual((restored.target_eid, restored.source_eid, restored.instance_id),
                         (1517, 1500, initial.instance_id))
        # The scheduled impact is 0.966, even though the world emits it at tick 1.0.
        remaining = 0.966 + 1.5 - 1.25
        self.assertEqual(restored.duration, struct.unpack('>e', struct.pack('>e', remaining))[0])

    def test_celeste_stun_and_existing_achilles_specific_slow_keep_distinct_kinds(self):
        for hero_id, slot, action, kind, deadline in ((285, abilities.AbilitySlot.B, 1, 22, 0.8),
                                                      (243, abilities.AbilitySlot.A, 0, 380, 0.05)):
            with self.subTest(hero_id=hero_id):
                world, frames, _, owner, _ = session(hero_id=hero_id, slot=slot)
                if hero_id == 243:
                    world._apply_event(1041, struct.pack('>IBB', 1517, action, 0), owner)
                else:
                    ground_cast(world, owner, action)
                advance_to(world, deadline)
                buff, = adds(frames, kind)
                self.assertEqual((buff.source_eid, buff.target_eid), (1500, 1517))
                if hero_id == 243:
                    self.assertEqual(adds(frames, 22), [])
                    self.assertEqual(adds(frames, 32), [])


if __name__ == '__main__':
    unittest.main()

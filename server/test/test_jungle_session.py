"""Jungle actor lifecycle through the production fixed-tick/reconnect session."""
import struct
import unittest

from server import entity_spawn, jungle, match_server, roster
from server.navigation import NavMesh
from server.test.test_entity_spawn import original_test_catalog, original_jungle_state_catalog
from server.test.test_native_actor_spawn import original_native_catalog


def make_world(objective=None):
    players = roster.default_solo_bots('jungle-session-player', 'jungle-session-match')
    players[0].hero_id = 243
    mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)], [(0, 1, 2), (0, 2, 3)])
    frames = []
    world = match_server.SnapshotStream(None, players, 'jungle-session-match',
        lambda opcode, payload: frames.append((opcode, payload)), log=lambda _: None, navigation_mesh=mesh)
    records = [template for catalog in (original_native_catalog(), original_jungle_state_catalog())
               for placements in catalog.templates.values() for template in placements.values()]
    native = entity_spawn.NativeActorCatalog(records)
    world.structures.spawn_catalog = native
    world.jungle.spawn_catalog = original_test_catalog()
    world.jungle.state_catalog = native
    world.jungle.experimental_capture = True
    if objective == 'gold':
        world.jungle.rules = jungle.JungleRules(gold_spawn_at=45, kraken_spawn_at=1000000)
    elif objective == 'kraken':
        world.jungle.rules = jungle.JungleRules(gold_spawn_at=1000000, kraken_spawn_at=45)
    world.jungle.gold_reset_at = world.jungle.rules.gold_spawn_at
    world.tape_frames, world.tape_done = [], True
    world.enable_bots = False
    world.emit_waves = True
    world._finalize()
    world._dump_world()
    world._enter_world()
    # Isolate the actor contracts from unrelated lane fights while exercising
    # the production scheduler, hero/jungle/structure updates and broadcaster.
    world.wave_director.t0 = 1000000
    world.wave_director._state_catalog = native
    world.sim_time, world.sim_tick = 44.95, 899
    world.advance_simulation()
    frames.clear()
    return world, frames


def join(world):
    connection, frames = object(), []
    world.add_client(connection, world.players[0].uuid,
                     lambda opcode, payload: frames.append((opcode, payload)))
    return connection, frames


def capture(world, team=1):
    monster = world.jungle.active_kraken or world.jungle.gold_miner
    hero = next(hero for hero in world.hero_sims.values() if hero.team == team)
    defeated_eid = monster.eid
    frames = world._deal_damage(hero, monster, monster.hp, 'true', world.sim_time)
    world._emit_frames(frames)
    return monster, defeated_eid, hero, frames


class TestJungleSession(unittest.TestCase):
    def assert_actor_order(self, frames):
        created, snapshots, deaths, slots = {}, {}, {}, {}
        for index, (opcode, payload) in enumerate(frames):
            if opcode == 1011:
                created[struct.unpack_from('>I', payload, 8)[0]] = index
            elif opcode == 1010 and len(payload) in (122, 126):
                eid, slot = struct.unpack_from('>I', payload, 8)[0], payload[116]
                if len(payload) == 126:
                    self.assertNotIn(eid, created, 'reconnect created an actor twice')
                    self.assertNotIn(slot, slots, 'reconnect aliased an occupied compact slot')
                    created[eid], slots[slot] = index, eid
                else:
                    self.assertIn(eid, created, 'HP snapshot preceded actor creation')
                    self.assertEqual(slots[slot], eid)
                    self.assertNotIn(eid, snapshots)
                    snapshots[eid] = index
            elif opcode == 1070:
                self.assertIn(struct.unpack_from('>I', payload)[0], created, 'position preceded actor creation')
            elif opcode == 1072:
                eid = struct.unpack_from('>I', payload)[0]
                self.assertIn(eid, created, 'death preceded actor creation')
                self.assertIn(eid, snapshots, 'jungle corpse death preceded its zero-HP snapshot')
                self.assertLess(snapshots[eid], index)
                deaths[eid] = index
        return created, snapshots, deaths

    def test_nonhero_lethal_jungle_damage_retains_corpse_until_production_tick_removal(self):
        world, emitted = make_world()
        monster = next(m for m in world.jungle.monsters.values() if m.camp_id == 'LCampA')
        attacker = world.structures.structures[3539]
        slot, position = world.actor_slots.by_eid[monster.eid], (monster.x, monster.y)
        resources = {eid: (world.economy.get_or_create(eid).gold, world.economy.get_or_create(eid).xp)
                     for eid in world.hero_sims}
        frames = world._deal_damage(attacker, monster, monster.hp, 'true', world.sim_time)
        world._emit_frames(frames)
        self.assertEqual([opcode for opcode, _ in frames], [1054, 1072])
        self.assertEqual(struct.unpack_from('>IIf', frames[0][1]), (monster.eid, attacker.eid, -750))
        self.assertEqual(frames[1][1], struct.pack('>II6x', monster.eid, attacker.eid))
        self.assertFalse(monster.is_alive)
        self.assertEqual(monster.hp, 0)
        self.assertEqual(world.jungle.camp_respawns[monster.camp_id], 105)
        self.assertEqual(resources, {eid: (world.economy.get_or_create(eid).gold, world.economy.get_or_create(eid).xp)
                                     for eid in world.hero_sims})
        self.assertEqual(world._deal_damage(attacker, monster, 100, 'true', world.sim_time), [])
        for _ in range(79):
            world.advance_simulation()
        self.assertEqual(world.sim_time, 48.95)
        self.assertEqual(world.actor_slots.by_eid[monster.eid], slot)
        self.assertIn(monster.eid, world.jungle.monsters)
        self.assertEqual((monster.x, monster.y), position)
        self.assertFalse(any(op in (1070, 1073, 1035) and struct.unpack_from('>I', p)[0] == monster.eid for op, p in emitted))
        world.advance_simulation()
        removal = [(op, p) for op, p in emitted if op in (1073, 1035) and struct.unpack_from('>I', p)[0] == monster.eid]
        self.assertEqual(removal, [(1073, roster.build_destroy(monster.eid)), (1035, roster.build_despawn(monster.eid))])
        self.assertNotIn(monster.eid, world.actor_slots.by_eid)
        self.assertNotIn(monster.eid, world.jungle.monsters)
        self.assertNotIn(monster.eid, world._last_death_frames)

    def test_actual_turret_tick_kills_captured_kraken_through_jungle_lifecycle(self):
        world, emitted = make_world('kraken')
        kraken, neutral_eid, _, _ = capture(world)
        turret = world.structures.structures[3539]
        kraken.x, kraken.y = turret.x - 1, turret.y
        kraken.hp, kraken.siege_stage = 1, 'siege'
        kraken.next_attack_at = world.sim_time + 60
        captured_eid = kraken.eid
        emitted.clear()
        world.advance_simulation()
        self.assertFalse(kraken.is_alive)
        damage = [p for op, p in emitted if op == 1054 and struct.unpack_from('>II', p) == (captured_eid, turret.eid)]
        self.assertEqual(len(damage), 1)
        self.assertIn((1072, struct.pack('>II6x', captured_eid, turret.eid)), emitted)
        self.assertNotIn(kraken.camp_id, world.jungle.camp_respawns)
        self.assertIn(neutral_eid, world.jungle.pending_removals)
        self.assertIn(captured_eid, world.jungle.pending_removals)
        self.assertNotEqual(world.actor_slots.by_eid[neutral_eid], world.actor_slots.by_eid[captured_eid])
        self.assertFalse(any(op in (1073, 1035) for op, _ in emitted))

    def test_reconnect_restores_captured_objectives_and_retained_corpses_without_advancing_state(self):
        for objective in ('gold', 'kraken'):
            for team in (1, 2):
                with self.subTest(objective=objective, team=team):
                    world, _ = make_world(objective)
                    monster, defeated_eid, hero, capture_frames = capture(world, team)
                    self.assertNotEqual(monster.eid, defeated_eid)
                    self.assertEqual(struct.unpack_from('>II', capture_frames[0][1]), (defeated_eid, hero.eid))
                    monster.hp, monster.x, monster.y = 1234.5, 12.5, 6.25
                    treant = next(m for m in world.jungle.monsters.values() if m.camp_id == 'LCampA')
                    turret = world.structures.structures[3539]
                    world._emit_frames(world._deal_damage(turret, treant, treant.hp, 'true', world.sim_time))
                    expected = {eid: (m.team, m.hp, m.max_hp, m.x, m.y, m.is_alive)
                                for eid, m in world.jungle.monsters.items()}
                    slots, timers = world.actor_slots.by_eid.copy(), world.jungle.camp_respawns.copy()
                    pending = {eid: (state[0], state[2], state[3]) for eid, state in world.jungle.pending_removals.items()}
                    clock = world.sim_tick, world.sim_time, world.jungle.next_eid
                    _, frames = join(world)
                    created, states, deaths = self.assert_actor_order(frames)
                    self.assertEqual(world.actor_slots.by_eid, slots)
                    self.assertEqual(world.jungle.camp_respawns, timers)
                    self.assertEqual({eid: (state[0], state[2], state[3]) for eid, state in world.jungle.pending_removals.items()}, pending)
                    self.assertEqual((world.sim_tick, world.sim_time, world.jungle.next_eid), clock)
                    self.assertEqual({eid: (m.team, m.hp, m.max_hp, m.x, m.y, m.is_alive)
                                      for eid, m in world.jungle.monsters.items()}, expected)
                    for eid, (expected_team, hp, maximum, x, y, alive) in expected.items():
                        creation, snapshot = frames[created[eid]][1], frames[states[eid]][1]
                        self.assertEqual(struct.unpack_from('>ff', snapshot, 36), (hp, maximum))
                        self.assertEqual(creation[121], expected_team)
                        self.assertEqual(snapshot[121], expected_team)
                        self.assertEqual(creation[116], slots[eid])
                        self.assertEqual(snapshot[116], slots[eid])
                        self.assertAlmostEqual(struct.unpack_from('>f', creation, 12)[0], x, places=4)
                        self.assertAlmostEqual(struct.unpack_from('>f', creation, 20)[0], y, places=4)
                        self.assertEqual(eid in deaths, not alive)
                    self.assertEqual(struct.unpack_from('>I', frames[created[monster.eid]][1])[0], 362 if objective == 'gold' else 364)
                    self.assertIn((1072, struct.pack('>II6x', defeated_eid, hero.eid)), frames)
                    self.assertIn((1072, struct.pack('>II6x', treant.eid, turret.eid)), frames)
                    self.assertFalse(any(op in (1073, 1035) for op, _ in frames))

    def test_reconnect_after_removal_excludes_old_neutral_actor_and_keeps_owned_current_state(self):
        world, _ = make_world('kraken')
        kraken, defeated_eid, _, _ = capture(world)
        _, first = join(world)
        self.assertTrue(any(op == 1010 and struct.unpack_from('>I', p, 8)[0] == defeated_eid for op, p in first))
        for _ in range(80):
            world.advance_simulation()
        self.assertNotIn(defeated_eid, world.jungle.monsters)
        self.assertNotIn(defeated_eid, world.actor_slots.by_eid)
        self.assertNotIn(defeated_eid, world._last_death_frames)
        self.assertTrue(kraken.is_alive)
        before = kraken.hp, kraken.max_hp, kraken.x, kraken.y, world.actor_slots.by_eid[kraken.eid]
        _, second = join(world)
        created, states, deaths = self.assert_actor_order(second)
        self.assertNotIn(defeated_eid, created)
        self.assertNotIn(defeated_eid, states)
        self.assertNotIn(defeated_eid, deaths)
        self.assertEqual(struct.unpack_from('>ff', second[states[kraken.eid]][1], 36), before[:2])
        self.assertEqual(second[created[kraken.eid]][1][116], before[4])
        self.assertEqual((kraken.hp, kraken.max_hp, kraken.x, kraken.y, world.actor_slots.by_eid[kraken.eid]), before)

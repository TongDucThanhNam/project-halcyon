"""Returning clients need current actors and state before their first correction."""
import struct
import threading
import unittest

from server import cooldown_wire, economy, entity_spawn, item_input, match_server, roster, wave, wire
from server.navigation import NavMesh


def catalog():
    records = []
    groups = ((entity_spawn.STRUCTURE_ARCHETYPES, entity_spawn.STRUCTURE_CLASS, (1, 2)),
              (entity_spawn.LANE_ARCHETYPES, entity_spawn.LANE_CLASS, (1, 2)),
              (entity_spawn.JUNGLE_ARCHETYPES, entity_spawn.JUNGLE_CLASS, (0,)))
    for archetypes, kind, teams in groups:
        for archetype in archetypes:
            for team in teams:
                for size in (122, 126):
                    payload = bytearray(size)
                    struct.pack_into(">III", payload, 0, archetype, kind, 9000)
                    if size == 122:
                        struct.pack_into(">ff", payload, 36, 100.0, 100.0)
                    payload[121] = team
                    records.append((1010, bytes(payload)))
    return (entity_spawn.NativeActorCatalog.from_frames(records),
            entity_spawn.SpawnCatalog.from_frames(records))


class TestReconnectState(unittest.TestCase):
    def make_world(self):
        players = roster.default_solo_bots("reconnect-player", "reconnect-match")
        players[0].hero_id = 243
        mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)], [(0, 1, 2), (0, 2, 3)])
        world = match_server.SnapshotStream(None, players, "reconnect-match", None,
                                           log=lambda _: None, navigation_mesh=mesh)
        native, jungle = catalog()
        world.structures.spawn_catalog, world.jungle.spawn_catalog = native, jungle
        world.tape_frames, world.tape_done = [], True
        world._finalize()
        world._dump_world()
        world._enter_world()
        world.sim_time, world.sim_tick = 45.0, 900
        world.wave_director.t0 = 1000000.0
        world.wave_director._state_catalog = native
        return world

    def join(self, world):
        conn, frames = object(), []
        world.add_client(conn, world.players[0].uuid, lambda op, payload: frames.append((op, payload)))
        return conn, frames

    def test_hero_reconnect_restores_visible_then_hidden_corpse_without_releasing_slot(self):
        world = self.make_world()
        hero = world.hero_sims[1500]
        actor_slots = dict(world.actor_slots.by_eid)
        world._emit_frames(world._deal_damage(world.hero_sims[1517], hero, hero.hp, 'true', 45.0))
        _, early = self.join(world)
        early_death = [(op, p) for op, p in early if op in (1072, 1073, 1075)
                       and struct.unpack_from('>I', p)[0] == 1500]
        self.assertEqual([op for op, _ in early_death], [1072, 1075])
        world.sim_time = 46.8
        world._emit_frames(hero.check_respawn(world.sim_time))
        self.assertTrue(hero.corpse_hidden)
        _, late = self.join(world)
        late_death = [(op, p) for op, p in late if op in (1072, 1073, 1075)
                      and struct.unpack_from('>I', p)[0] == 1500]
        self.assertEqual([op for op, _ in late_death], [1072, 1075, 1073])
        self.assertEqual(late_death[-1][1], struct.pack('>IH', 1500, 0))
        self.assertAlmostEqual(struct.unpack_from('>f', late_death[1][1], 4)[0], hero.respawn_at - 46.8, places=5)
        self.assertEqual(world.actor_slots.by_eid, actor_slots)
        self.assertFalse(any(op == 1035 and struct.unpack_from('>I', p)[0] == 1500 for op, p in late))
        world.sim_time = hero.respawn_relocation_at
        world._emit_frames(hero.check_respawn(world.sim_time))
        self.assertFalse(hero.is_alive)
        self.assertTrue(hero.respawn_relocated)
        self.assertIn(1500, world._last_death_frames)
        _, relocated = self.join(world)
        stages = [op for op, p in relocated if op in (1072, 1073, 1075, 1033, 1074)
                  and struct.unpack_from('>I', p)[0] == 1500]
        self.assertEqual(stages, [1072, 1075, 1073, 1033])
        world.sim_time = hero.respawn_at
        world._emit_frames(hero.check_respawn(world.sim_time))
        _, alive = self.join(world)
        self.assertFalse(any(op in (1072, 1073, 1075) and struct.unpack_from('>I', p)[0] == 1500
                             for op, p in alive))
        self.assertEqual(world.actor_slots.by_eid, actor_slots)

    def test_creation_precedes_positions_and_retained_corpse_death(self):
        world = self.make_world()
        live, corpse = wave.Minion(4610, 2, 0), wave.Minion(4611, 2, 0)
        live.hp = 123.0
        world.wave_director.minions.extend((live, corpse))
        for minion in (live, corpse):
            world.actor_slots.allocate(minion.eid)
        world._emit_frames(world.wave_director.on_minion_death(corpse, 1500, 44.0))
        slots = dict(world.actor_slots.by_eid)
        _, frames = self.join(world)
        known, created_at, deaths = set(), {}, {}
        for index, (opcode, payload) in enumerate(frames):
            if opcode == 1011:
                known.add(struct.unpack_from(">I", payload, 8)[0])
            elif opcode == 1010 and len(payload) == 126:
                eid = struct.unpack_from(">I", payload, 8)[0]
                known.add(eid)
                created_at[eid] = index
            elif opcode == 1070:
                self.assertIn(struct.unpack_from(">I", payload)[0], known)
            elif opcode == 1072:
                eid = struct.unpack_from(">I", payload)[0]
                self.assertIn(eid, known)
                deaths[eid] = index
        self.assertLess(created_at[corpse.eid], deaths[corpse.eid])
        states = {struct.unpack_from(">I", p, 8)[0]: struct.unpack_from(">ff", p, 36)
                  for op, p in frames if op == 1010 and len(p) == 122}
        self.assertEqual(states[live.eid], (123.0, live.max_hp))
        self.assertEqual(states[corpse.eid], (0.0, corpse.max_hp))
        self.assertEqual(world.actor_slots.by_eid, slots)
        self.assertEqual((world.sim_tick, world.sim_time), (900, 45.0))
        self.assertFalse(any(op in (1073, 1035) for op, _ in frames))

    def test_completed_tape_replayed_once_and_ready_echoes_are_local(self):
        world = self.make_world()
        allocation = struct.pack(">II", 1500, 1500) + bytes(32)
        captured_ready = struct.pack(">IBB", 1519, 1, 0)
        world.tape_frames = [(0, struct.pack(">H", 1087) + allocation),
                             (1, struct.pack(">H", 1137) + captured_ready)]
        conn, frames = self.join(world)
        self.assertIn((1087, allocation), frames)
        self.assertNotIn((1137, captured_ready), frames)
        ready = struct.pack(">IBB", 1500, 1, 0)
        world._apply_event(1134, bytes(6), conn)
        world._apply_event(1137, ready, conn)
        self.assertEqual(sum(op == 1011 for op, _ in frames), len(world.players))
        self.assertIn((1134, bytes(6)), frames)
        self.assertIn((1137, ready), frames)
        world._broadcast(1087, allocation, bootstrap=True)
        self.assertEqual(frames.count((1087, allocation)), 1)
        self.assertIn(conn, world.dumped_conns)

    def test_current_resources_inventory_skills_and_cooldowns(self):
        world = self.make_world()
        hero = world.hero_sim
        econ = world.economy.get_or_create(hero.eid)
        econ.add_xp(250.0)
        boots = economy.ITEMS_BY_KEY["sprint_boots"]
        slot = econ.buy_item(boots.id)
        econ.apply_to_hero(hero)
        econ.gold = 987.5
        hero.hp, hero.energy = 321.0, 95.25
        kit = world.hero_kits[hero.eid]
        self.assertTrue(world.economy.upgrade_ability(hero.eid, 0, kit))
        kit.cooldowns[0] = 50.0
        activated = world.activate_item(hero.eid, slot)
        self.assertTrue(activated.success)
        _, frames = self.join(world)
        block = next(p for op, p in frames if op == 1011 and struct.unpack_from(">I", p, 8)[0] == hero.eid)
        self.assertEqual(block[42:50], struct.pack(">ff", 321.0, hero.max_hp))
        self.assertEqual(block[122:130], struct.pack(">ff", 95.25, hero.max_energy))
        stats = {(struct.unpack_from(">I", p)[0], p[8]): struct.unpack_from(">f", p, 4)[0]
                 for op, p in frames if op == 1053}
        self.assertEqual(stats[hero.eid, 6], 387.5)
        self.assertNotIn((hero.eid, 8), stats)
        self.assertEqual(struct.unpack_from(">f", block, 294)[0], econ.level)
        replayed_points = sum(op == 1082 and struct.unpack_from(">I", p)[0] == hero.eid
                              for op, p in frames)
        self.assertEqual(struct.unpack_from(">f", block, 314)[0] - replayed_points, econ.ability_points)
        self.assertEqual(struct.unpack_from(">f", block, 318)[0], 98.0)
        self.assertEqual(struct.unpack_from(">f", block, 322)[0], 100.0)
        self.assertIn((1085, roster.build_item_inventory(hero.eid, boots.id, econ.inventory_instances[slot])), frames)
        timers = {tick.tag: tick for op, p in frames if op == 1162
                  for tick in (cooldown_wire.parse_timer_tick(p),) if tick.eid == hero.eid}
        self.assertEqual(timers[kit.abilities[0].tag_inst].remaining, 5.0)
        self.assertEqual(timers[boots.cooldown_tag].remaining, boots.cooldown)
        self.assertIn((1078, bytes(6)), frames)

    def test_item_instance_ownership_cooldown_ack_and_no_skill_upgrade(self):
        world = self.make_world()
        hero = world.hero_sim
        econ = world.economy.get_or_create(hero.eid)
        boots = economy.ITEMS_BY_KEY["sprint_boots"]
        slot = econ.buy_item(boots.id)
        conn, frames = self.join(world)
        frames.clear()
        before_points = econ.ability_points
        payload = item_input.build_item_use(econ.inventory_instances[slot])
        world._apply_event(1096, payload, conn)
        expiry = econ.item_cooldowns["sprint"]
        world._apply_event(1096, payload, conn)
        self.assertEqual(frames.count((1096, payload)), 2)
        self.assertEqual(sum(op == 1162 for op, _ in frames), 1)
        self.assertEqual(econ.item_cooldowns["sprint"], expiry)
        self.assertEqual(econ.ability_points, before_points)
        count = len(frames)
        for invalid in (item_input.build_item_use(9000), bytes(6), payload[:-1] + b"\x01"):
            world._apply_event(1096, invalid, conn)
        self.assertEqual(len(frames), count)

    def test_simulation_waits_for_reconnect_state_lock(self):
        world = self.make_world()
        entered, finished = threading.Event(), threading.Event()
        def tick():
            entered.set()
            world.advance_simulation()
            finished.set()
        with world._state_lock:
            worker = threading.Thread(target=tick)
            worker.start()
            self.assertTrue(entered.wait(1.0))
            self.assertFalse(finished.wait(0.02))
        worker.join(2.0)
        self.assertFalse(worker.is_alive())
        self.assertTrue(finished.is_set())


if __name__ == "__main__":
    unittest.main()

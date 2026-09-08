"""Cross-system contracts exercised through the production fixed-tick session."""
import struct
import unittest

from server import abilities, economy, jungle, match_server, roster, wire
from server.navigation import NavMesh
from server.replay import RecordedFrame, DeterminismVerifier
from server.status_effects import StatusEffect, StatusType


def session():
    mesh = NavMesh([(-100, -100), (100, -100), (100, 100), (-100, 100)],
                   [(0, 1, 2), (0, 2, 3)])
    players = roster.default_solo_bots("sandbox-test", "sandbox-test")
    players[0].hero_id = 243
    players = [players[0], players[3]]
    players[1].hero_id = 242
    frames = []
    world = match_server.SnapshotStream(None, players, "sandbox-test",
        lambda op, payload: frames.append((op, payload)), log=lambda _: None,
        navigation_mesh=mesh)
    world._finalize()
    world.hero_sims[1500].teleport(0, 5)
    world.hero_sims[1517].teleport(4, 5)
    world.jungle = jungle.JungleManager(open_time=1000000)
    for building in world.structures.structures.values():
        building.is_alive = False
    world.phase = world.WORLD
    frames.clear()
    return world, frames


def ticks(world, count):
    for _ in range(count):
        world.advance_simulation()


class TestSandboxIntegration(unittest.TestCase):
    def test_damage_mitigated_once_and_client_health_changes_once(self):
        world, _ = session()
        attacker, victim = world.hero_sims.values()
        victim.armor = 100
        before = victim.hp
        frames = world._deal_damage(attacker, victim, 100, "weapon", 0)
        self.assertEqual(before - victim.hp, 50)
        self.assertEqual(struct.unpack_from(">IIf", frames[0][1]), (victim.eid, attacker.eid, -50))
        self.assertFalse(any(op == 1053 and payload[8] == 0 for op, payload in frames))

    def test_ranged_release_survives_move_and_impacts_later(self):
        world, frames = session()
        hero, enemy = world.hero_sims.values()
        before = enemy.hp
        world._apply_event(wire.OP.TARGET_ENTITY, roster.build_target_entity(enemy.eid))
        for _ in range(20):
            world.advance_simulation()
            if world.attacks.projectiles:
                break
        self.assertTrue(world.attacks.projectiles)
        self.assertEqual(enemy.hp, before)
        world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-10, 5))
        start = hero.x
        ticks(world, 6)
        self.assertLess(hero.x, start)
        self.assertLess(enemy.hp, before)
        self.assertEqual(len([op for op, _ in frames if op == 1054]), 1)

    def test_shop_gate_and_boots_change_authoritative_travel(self):
        world, _ = session()
        hero = world.hero_sim
        item = economy.ITEMS_BY_KEY["sprint_boots"]
        econ = world.economy.get_or_create(hero.eid)
        starting = econ.gold
        world._apply_event(wire.OP.SHOP_BUY, roster.build_shop_buy(hero.eid, item.id))
        self.assertEqual(econ.gold, starting)
        hero.teleport(hero.spawn_x, hero.spawn_y)
        world._apply_event(wire.OP.SHOP_BUY, roster.build_shop_buy(hero.eid, item.id))
        self.assertLess(econ.gold, starting)
        slot = next(i for i, owned in enumerate(econ.inventory) if owned is item)
        self.assertTrue(world.activate_item(hero.eid, slot).success)
        hero.teleport(0, 5)
        world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-20, 5))
        ticks(world, 20)
        self.assertAlmostEqual(-hero.x, hero.speed + 2, places=4)

    def test_ability_spends_energy_and_hits_neutral_creature(self):
        world, frames = session()
        world.jungle = jungle.JungleManager()
        monster = next(iter(world.jungle.monsters.values()))
        hero = world.hero_sim
        hero.teleport(monster.x - 3, monster.y)
        kit = world.hero_kits[hero.eid]
        self.assertTrue(world.economy.upgrade_ability(hero.eid, 0, kit))
        energy, health = hero.energy, monster.hp
        world._apply_event(wire.OP.TARGETLESS_CAST, struct.pack(">IBB", monster.eid, 0, 0))
        self.assertLess(hero.energy, energy)
        self.assertLess(monster.hp, health)
        self.assertTrue(any(op == 1053 and p[8] == 2 and struct.unpack_from(">f", p, 4)[0] < 0
                            for op, p in frames))

    def test_aftershock_procs_once_after_real_cast(self):
        world, _ = session()
        hero, enemy = world.hero_sims.values()
        kit = world.hero_kits[hero.eid]
        self.assertTrue(world.economy.upgrade_ability(hero.eid, 1, kit))
        econ = world.economy.get_or_create(hero.eid)
        econ.inventory[0] = economy.ITEMS_BY_KEY["aftershock"]
        world._apply_event(wire.OP.TARGETLESS_CAST, struct.pack(">IBB", 0xffffffff, 1, 0))
        first = world._deal_damage(hero, enemy, 10, "weapon", 0, basic=True)
        second = world._deal_damage(hero, enemy, 10, "weapon", 0.5, basic=True)
        self.assertEqual(sum(op == 1054 for op, _ in first), 2)
        self.assertEqual(sum(op == 1054 for op, _ in second), 1)

    def test_recall_uses_match_ticks_and_damage_cancels(self):
        world, _ = session()
        hero, enemy = world.hero_sims.values()
        recall = struct.pack(">IBB", 0xffffffff, 4, 0)
        world._apply_event(wire.OP.TARGETLESS_CAST, recall)
        ticks(world, 79)
        self.assertEqual((hero.x, hero.y), (0, 5))
        ticks(world, 1)
        self.assertAlmostEqual(hero.x, hero.spawn_x, places=6)
        self.assertAlmostEqual(hero.y, hero.spawn_y, places=6)
        hero.teleport(0, 5)
        world._apply_event(wire.OP.TARGETLESS_CAST, recall)
        world._deal_damage(enemy, hero, 10, "true", world.sim_time)
        ticks(world, 80)
        self.assertEqual((hero.x, hero.y), (0, 5))

    def test_stun_cancels_pending_channel_before_damage(self):
        world, _ = session()
        hero, enemy = world.hero_sims.values()
        kit = abilities.create_ringo_kit(hero)
        world.hero_kits[hero.eid] = kit
        world._apply_event(wire.OP.TARGETLESS_CAST, struct.pack(">IBB", enemy.eid, 2, 0))
        self.assertTrue(hero.channeling)
        hp = enemy.hp
        world.status_manager.apply_effect(StatusEffect("stun", StatusType.STUN,
            enemy.eid, hero.eid, 1, 0, 1, 1))
        ticks(world, 50)
        self.assertFalse(hero.channeling)
        self.assertEqual(enemy.hp, hp)

    def test_repeated_full_session_intents_have_identical_wire_output(self):
        def run():
            world, frames = session()
            world._apply_event(wire.OP.TARGET_ENTITY, roster.build_target_entity(1517))
            result = []
            for tick in range(200):
                if tick == 16:
                    world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-8, 5))
                if tick == 70:
                    world._apply_event(wire.OP.TARGET_ENTITY, roster.build_target_entity(1517))
                world.advance_simulation()
                result.extend(RecordedFrame(tick, op, payload) for op, payload in frames)
                frames.clear()
            return result
        first = run()
        self.assertTrue(any(f.opcode == 1054 for f in first))
        for _ in range(3):
            equal, message = DeterminismVerifier.verify(first, run())
            self.assertTrue(equal, message)

    def test_crystal_freezes_gameplay_and_reports_winner_after_six_seconds(self):
        world, frames = session()
        hero = world.hero_sim
        crystal = world.structures.structures[3544]
        crystal.is_alive = True
        world._emit_frames(world._deal_damage(hero, crystal, crystal.hp, "true", 0))
        self.assertEqual([op for op, _ in frames], [1054, 1106, 1072])
        position, gold = (hero.x, hero.y), world.economy.get_or_create(hero.eid).gold
        world._apply_event(wire.OP.MOVE_CAST, roster.build_move(-20, 5))
        ticks(world, 119)
        self.assertEqual((hero.x, hero.y), position)
        self.assertEqual(world.economy.get_or_create(hero.eid).gold, gold)
        self.assertFalse(any(op == wire.OP.MATCH_RESULT for op, _ in frames))
        ticks(world, 1)
        results = [p for op, p in frames if op == wire.OP.MATCH_RESULT]
        self.assertEqual(results, [struct.pack(">IBx", 1, 0)])
        ticks(world, 20)
        self.assertEqual(sum(op == wire.OP.MATCH_RESULT for op, _ in frames), 1)

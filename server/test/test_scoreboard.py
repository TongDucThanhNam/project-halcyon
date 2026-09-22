"""CE wire counters and production last-hit/death/reconnect integration."""
import struct
import unittest

from server import scoreboard, wave, jungle
from server.test.test_ability_cc_presentation import session
from server.test.test_cooldown_wire import recorded_frames
from server.test import test_reconnect_state


class ScoreboardWireTests(unittest.TestCase):
    def test_all_independent_counter_payloads_match_measured_builders(self):
        counts = {41: 0, 42: 0, 14: 0}
        for name, index, op, body in recorded_frames():
            if op == 1052 and len(body) > 13 and body[12] in (41, 42):
                eid, owner, value, attribute, layer = struct.unpack_from('>IIfBB', body)
                self.assertEqual((owner, value, layer), (0xffffffff, 1.0, 0), (name, index))
                self.assertEqual(scoreboard.base_counter(eid, attribute, 1), (op, body))
                counts[attribute] += 1
            elif op == 1053 and body[8] == 14:
                eid, value = struct.unpack_from('>If', body)
                self.assertEqual(value, 1)
                scores = scoreboard.Scoreboard([eid])
                self.assertEqual(scores.last_hit(eid), [(op, body)], (name, index))
                counts[14] += 1
        self.assertEqual(counts, {41: 30, 42: 30, 14: 466})

    def test_kill_death_once_per_life_and_not_again_on_corpse(self):
        world, _, _, _, _ = session()
        attacker, victim = world.hero_sims[1500], world.hero_sims[1517]
        for now in (10.0, 100.0):
            frames = world._deal_damage(attacker, victim, victim.hp, 'true', now)
            self.assertIn(scoreboard.base_counter(victim.eid, 42, 1), frames)
            self.assertIn(scoreboard.base_counter(attacker.eid, 41, 1), frames)
            death_index = next(i for i, (op, _) in enumerate(frames) if op == 1072)
            self.assertGreater(frames.index(scoreboard.base_counter(victim.eid, 42, 1)), death_index)
            self.assertEqual(world._deal_damage(attacker, victim, 100, 'true', now + 1), [])
            victim.check_respawn(victim.respawn_at)
            self.assertTrue(victim.is_alive)
        self.assertEqual(world.scoreboard.players[1500].kills, 2)
        self.assertEqual(world.scoreboard.players[1517].deaths, 2)

    def test_nonhero_killer_counts_death_but_not_hero_kill(self):
        world, _, _, _, _ = session()
        victim = world.hero_sims[1500]
        minion = wave.Minion(5000, 2, 0)
        frames = world._deal_damage(minion, victim, victim.hp, 'true', 10)
        self.assertIn(scoreboard.base_counter(1500, 42, 1), frames)
        self.assertEqual(sum(s.kills for s in world.scoreboard.players.values()), 0)

    def test_fountain_lifecycle_death_is_not_omitted_or_counted_twice(self):
        world, _, _, _, _ = session()
        hero = world.hero_sims[1500]
        enemy = world.hero_sims[1517]
        hero.teleport(enemy.spawn_x, enemy.spawn_y)
        hero.hp = 10
        world._step_heroes(.05, 10)
        self.assertFalse(hero.is_alive)
        world._step_heroes(.05, 10.05)
        self.assertEqual(world.scoreboard.players[1500].deaths, 1)
        self.assertEqual(sum(s.kills for s in world.scoreboard.players.values()), 0)

    def test_lane_and_ordinary_jungle_last_hits_count_once(self):
        world, _, _, _, _ = session()
        hero = world.hero_sims[1500]
        minion = wave.Minion(5000, 2, 0)
        world.wave_director.minions.append(minion)
        world.actor_slots.allocate(minion.eid)
        frames = world._deal_damage(hero, minion, minion.hp, 'true', 10)
        self.assertTrue(any(op == 1053 and body[8] == 14 for op, body in frames))
        self.assertEqual(world._deal_damage(hero, minion, 100, 'true', 11), [])
        world.jungle = jungle.JungleManager()
        monster = next(m for m in world.jungle.monsters.values()
                       if m.config.monster_type == jungle.MonsterType.SMALL_BEAR)
        frames = world._deal_damage(hero, monster, monster.hp, 'true', 12)
        self.assertTrue(any(op == 1053 and body[8] == 14 for op, body in frames))
        self.assertEqual(world.scoreboard.players[1500].farm, 2)

    def test_reconnect_restores_counters_without_awarding_again(self):
        helper = test_reconnect_state.TestReconnectState()
        world = helper.make_world()
        hero, enemy = world.hero_sims[1500], world.hero_sims[1517]
        world._emit_frames(world._deal_damage(hero, enemy, enemy.hp, 'true', 45))
        world.scoreboard.last_hit(hero.eid)
        for _ in range(2):
            _, frames = helper.join(world)
            for eid in (1500, 1517):
                for frame in world.scoreboard.reconnect_frames(eid):
                    self.assertEqual(frames.count(frame), 1)
        self.assertEqual(world.scoreboard.players[1500].kills, 1)
        self.assertEqual(world.scoreboard.players[1517].deaths, 1)
        self.assertEqual(world.scoreboard.players[1500].farm, 1)


if __name__ == '__main__':
    unittest.main()

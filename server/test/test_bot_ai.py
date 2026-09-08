"""Unit tests for Project Halcyon Bot AI decision layer."""
import unittest

from server import abilities, bot_ai, economy, hero_movement, roster, wire


class TestBotAI(unittest.TestCase):
    def setUp(self):
        self.bot = bot_ai.BotAI(eid=1515, team=1)
        self.hero = hero_movement.HeroMovement(eid=1515, team=1, x=-76.0, y=0.88)
        self.all_heroes = {1515: self.hero}

    def test_push_lane_intents(self):
        intents = self.bot.step(
            now=1.0,
            hero=self.hero,
            all_heroes=self.all_heroes,
            minions=[],
            structures={},
        )
        self.assertEqual(self.bot.state, bot_ai.BotState.PUSHING)
        self.assertTrue(any(op == wire.OP.MOVE_CAST for op, _ in intents))

    def test_target_enemy_hero_in_combat(self):
        # Enemy hero nearby (5.0u away)
        enemy = hero_movement.HeroMovement(eid=1517, team=2, x=-71.0, y=0.88)
        self.all_heroes[1517] = enemy

        intents = self.bot.step(
            now=1.0,
            hero=self.hero,
            all_heroes=self.all_heroes,
            minions=[],
            structures={},
        )
        self.assertEqual(self.bot.state, bot_ai.BotState.COMBAT)
        target_intents = [p for op, p in intents if op == wire.OP.TARGET_ENTITY]
        self.assertTrue(len(target_intents) > 0)
        target_eid = roster.parse_target_entity(target_intents[0])
        self.assertEqual(target_eid, 1517)

    def test_combat_casts_abilities(self):
        enemy = hero_movement.HeroMovement(eid=1517, team=2, x=-71.0, y=0.88)
        self.all_heroes[1517] = enemy
        kit = abilities.create_ringo_kit(self.hero)

        intents = self.bot.step(
            now=1.0,
            hero=self.hero,
            all_heroes=self.all_heroes,
            minions=[],
            structures={},
            hero_kit=kit,
        )
        # Expect ability cast intent (slot B or A)
        ability_casts = [p for op, p in intents if op == wire.OP.ABILITY_CAST]
        self.assertTrue(len(ability_casts) > 0)

    def test_low_hp_retreat(self):
        # Drop hero HP to 15%
        self.hero.hp = self.hero.max_hp * 0.15

        intents = self.bot.step(
            now=1.0,
            hero=self.hero,
            all_heroes=self.all_heroes,
            minions=[],
            structures={},
        )
        self.assertEqual(self.bot.state, bot_ai.BotState.RETREAT)
        move_intents = [p for op, p in intents if op == wire.OP.MOVE_CAST]
        self.assertTrue(len(move_intents) > 0)
        tx, ty = roster.parse_move(move_intents[0])
        # Moving towards friendly base spawn (-78.18, 0.88)
        self.assertAlmostEqual(tx, -78.18, places=2)

    def test_item_purchasing(self):
        econ = economy.PlayerEconomy(eid=1515, start_gold=1200.0)
        intents = self.bot.step(
            now=1.0,
            hero=self.hero,
            all_heroes=self.all_heroes,
            minions=[],
            structures={},
            econ=econ,
        )
        shop_buys = [p for op, p in intents if op == wire.OP.SHOP_BUY]
        self.assertTrue(len(shop_buys) > 0)
        eid, item_id = roster.parse_shop_buy(shop_buys[0])
        self.assertEqual(eid, 1515)
        self.assertEqual(item_id, economy.ITEMS_BY_KEY["heavy_steel"].id)


if __name__ == "__main__":
    unittest.main()

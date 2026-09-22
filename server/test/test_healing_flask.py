"""Default-item ownership and the independently measured Flask resource contract."""
import struct
import unittest

from server import buff_wire, cooldown_wire, item_input, roster, wire
from server.status_effects import StatusEffect, StatusType
from server.test.test_ability_cc_presentation import session


class HealingFlaskTests(unittest.TestCase):
    def setUp(self):
        self.world, self.frames, self.other, self.owner, _ = session()
        self.hero = self.world.hero_sims[1500]
        self.player = self.world.economy.get_or_create(1500)
        self.hero.hp = 500
        self.hero.energy = 100
        self.hero.max_hp = 2000
        self.hero.max_energy = 370
        self.hero.level = self.player.level = 5

    def use(self, instance=2000):
        self.world._apply_event(wire.OP.ITEM_USE, item_input.build_item_use(instance), self.owner)

    def advance_items(self, seconds):
        for tick in range(1, round(seconds / .05) + 1):
            at = tick * .05
            self.world._emit_frames(self.world.items.step(at, self.world.hero_sims))
            self.world.status_manager.clean_expired(at)
            self.world._drain_effect_frames()

    def test_default_instance_routes_buff_barrier_cooldown_and_seventeen_pulses(self):
        self.use()
        self.assertEqual([p for op, p in self.frames if op == 1096], [item_input.build_item_use(2000)])
        self.assertFalse(any(op == 1096 for op, _ in self.other))
        buff, = [buff_wire.parse_buff_add(p) for op, p in self.frames if op == 1086]
        self.assertEqual((buff.kind, buff.duration), (259, 5))
        self.assertEqual(self.world.status_manager.get_barrier(1500, 0), 255)
        self.assertEqual(self.player.default_items[2000].cooldown_until, 120)
        self.assertAlmostEqual(self.hero.energy, 106.66, places=5)
        self.advance_items(5)
        heals = [struct.unpack_from('>f', p, 8)[0] for op, p in self.frames
                 if op == 1054 and struct.unpack_from('>II', p) == (1500, 1500)]
        energy = [struct.unpack_from('>f', p, 4)[0] for op, p in self.frames
                  if op == 1053 and p[8] == 2]
        self.assertEqual(heals, [18] * 17)
        self.assertEqual(len(energy), 17)
        self.assertTrue(all(abs(value - 6.66) < 1e-5 for value in energy))
        self.assertEqual(self.hero.hp, 806)
        self.assertAlmostEqual(self.hero.energy, 213.22, places=5)
        self.assertEqual(self.world.status_manager.get_barrier(1500, 5), 0)
        self.assertFalse(self.world.items._periodic)

    def test_duplicate_foreign_and_unsupported_default_do_not_change_resources(self):
        self.use(123456)
        self.assertFalse(self.frames)
        self.use(2001)
        self.assertEqual(self.player.default_items[2001].cooldown_until, 0)
        self.assertEqual((self.hero.hp, self.hero.energy), (500, 100))
        self.frames.clear()
        self.use()
        state = (self.hero.hp, self.hero.energy, self.player.default_items[2000].cooldown_until)
        self.frames.clear()
        self.use()
        self.assertEqual(self.frames, [(1096, item_input.build_item_use(2000))])
        self.assertEqual((self.hero.hp, self.hero.energy, self.player.default_items[2000].cooldown_until), state)
        timer = cooldown_wire.parse_timer_tick(self.player.default_items[2000].timer_payload(1500, 20))
        self.assertEqual((timer.remaining, timer.duration), (100, 120))

    def test_wound_caps_death_and_hard_control_use_shared_lifecycle(self):
        self.world.status_manager.apply_effect(StatusEffect('stun', StatusType.STUN, 1517, 1500, 1, 0, 1))
        self.use()
        self.assertEqual(self.player.default_items[2000].cooldown_until, 0)
        self.world.status_manager.remove_effect(1500, 'stun', now=0)
        self.world.status_manager.apply_effect(StatusEffect('wound', StatusType.WOUND, 1517, 1500, 5, 0, 5, .5))
        self.hero.hp = 1995
        self.hero.energy = 369
        self.use()
        self.assertEqual(self.hero.energy, 370)
        self.world.items.step(.3, self.world.hero_sims)
        self.assertEqual(self.hero.hp, 2000)
        self.hero.hp = 1000
        self.world.items.step(.6, self.world.hero_sims)
        self.assertEqual(self.hero.hp, 1009)
        self.hero.hp = 0
        self.hero.is_alive = False
        self.world.items.step(5, self.world.hero_sims)
        self.assertEqual(self.hero.hp, 0)
        self.assertFalse(self.world.items._periodic)
        self.assertEqual(self.world.status_manager.get_barrier(1500, 5), 0)

    def test_second_independent_level_and_coarse_step_preserve_all_due_pulses(self):
        self.hero.level = self.player.level = 7
        self.hero.max_energy = 420
        self.use()
        self.assertEqual(self.world.status_manager.get_barrier(1500, 0), 325)
        self.world.items.step(5, self.world.hero_sims)
        self.assertEqual(self.hero.hp, 857)
        self.assertAlmostEqual(self.hero.energy, 228.52, places=5)
        ready = self.world.items.step(120, self.world.hero_sims)
        timers = [cooldown_wire.parse_timer_tick(p) for op, p in ready if op == 1162]
        self.assertEqual([(t.tag, t.remaining) for t in timers], [(cooldown_wire.ITEM_TAGS['healing_flask'], 0)])
        self.assertFalse(self.world.items.step(121, self.world.hero_sims))


if __name__ == '__main__':
    unittest.main()

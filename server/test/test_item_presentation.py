"""Native item presentation follows the authoritative status lifetime."""
import unittest

from server import buff_wire, cooldown_wire, economy, hero_movement, items
from server.status_effects import StatusEffect, StatusManager, StatusType


class TestItemPresentation(unittest.TestCase):
    def setUp(self):
        self.next_instance = 400000
        self.allocations = []
        def allocate():
            value = self.next_instance
            self.next_instance += 1
            self.allocations.append(value)
            return value
        self.status = StatusManager(instance_allocator=allocate)
        self.economy = economy.EconomyManager()
        self.items = items.ItemManager(self.economy, self.status)
        self.hero = hero_movement.HeroMovement(1500, 1, x=0, y=0, hp=500, max_hp=1000)
        self.ally = hero_movement.HeroMovement(1515, 1, x=1, y=0, hp=500, max_hp=1000)
        self.enemy = hero_movement.HeroMovement(1517, 2, x=3, y=0, hp=1000, max_hp=1000)
        self.heroes = {hero.eid: hero for hero in (self.enemy, self.ally, self.hero)}

    def equip(self, key):
        self.economy.get_or_create(1500).inventory[0] = economy.ITEMS_BY_KEY[key]

    def adds(self):
        frames = self.status.drain_frames()
        self.assertTrue(all(op == 1086 for op, _ in frames))
        return [buff_wire.parse_buff_add(payload) for _, payload in frames]

    def test_every_boots_family_has_native_visual_and_one_ready_transition(self):
        for item_key, native_kind in (("sprint_boots", 278), ("travel_boots", 279), ("halcyon_chargers", 281)):
            with self.subTest(item=item_key):
                self.setUp()
                self.equip(item_key)
                result = self.items.activate(1500, 0, 10.0, self.heroes)
                buff, = self.adds()
                self.assertEqual((buff.target_eid, buff.source_eid, buff.kind, buff.duration),
                                 (1500, 1500, native_kind, 3.0))
                timer = cooldown_wire.parse_timer_tick(result.frames(1500)[0][1])
                self.assertEqual(timer.remaining, result.cooldown)
                self.status.clean_expired(13.0)
                self.assertEqual(self.status.get_flat_speed_bonus(1500, 13.0), 0)
                self.assertFalse(self.status.drain_frames())  # native natural expiry
                ready = self.items.step(10.0 + result.cooldown, self.heroes)
                self.assertEqual(len(ready), 1)
                self.assertEqual(cooldown_wire.parse_timer_tick(ready[0][1]).remaining, 0)
                self.assertFalse(self.items.step(11.0 + result.cooldown, self.heroes))

    def test_fountain_target_order_and_cleanse_control_real_healing(self):
        self.equip("fountain_of_renewal")
        self.assertTrue(self.items.activate(1500, 0, 0.0, self.heroes).success)
        buffs = self.adds()
        self.assertEqual([(buff.target_eid, buff.kind, buff.duration) for buff in buffs],
                         [(1500, 270, 3.0), (1515, 270, 3.0)])
        self.items.step(1.0, self.heroes)
        first_hp = self.ally.hp
        self.assertGreater(first_hp, 500)
        self.status.remove_effect(1515, "fountain:1500", now=1.2)
        cancel, = self.status.drain_frames()
        self.assertEqual(cancel[0], 1093)
        self.assertEqual(buff_wire.parse_buff_cancel(cancel[1]), (1515, buffs[1].instance_id))
        self.items.step(3.0, self.heroes)
        self.assertEqual(self.ally.hp, first_hp)
        self.assertGreater(self.hero.hp, first_hp)
        self.status.clean_expired(3.0)
        self.assertFalse(self.status.drain_frames())

    def test_reflex_variants_have_one_buff_for_barrier_and_immunity(self):
        for item_key, targets, duration in (("reflex_block", [1500], 1.0), ("aegis", [1500], 1.0),
                                             ("crucible", [1500, 1515], 1.2)):
            with self.subTest(item=item_key):
                self.setUp()
                self.equip(item_key)
                self.items.activate(1500, 0, 0.0, self.heroes)
                buffs = self.adds()
                self.assertEqual([buff.target_eid for buff in buffs], targets)
                self.assertTrue(all(buff.kind == 268 for buff in buffs))
                self.assertTrue(all(abs(buff.duration - duration) < 0.001 for buff in buffs))
                self.status.absorb_damage_with_barrier(1500, 300.0, 0.1)
                self.assertEqual(self.status.get_barrier(1500, 0.1), 0)
                self.assertTrue(self.status.has_effect(1500, StatusType.CC_IMMUNITY, 0.1))
                self.assertFalse(self.status.drain_frames())
                self.status.remove_effect(1500, "reflex-immunity:1500:1500", now=0.2)
                cancel, = self.status.drain_frames()
                self.assertEqual(buff_wire.parse_buff_cancel(cancel[1]), (1500, buffs[0].instance_id))

    def test_atlas_visual_starts_at_delayed_resolution_and_immunity_rejects_it(self):
        self.equip("atlas_pauldron")
        self.items.activate(1500, 0, 0.0, self.heroes)
        self.assertFalse(self.status.drain_frames())
        self.items.step(0.79, self.heroes)
        self.assertFalse(self.status.drain_frames())
        self.items.step(0.8, self.heroes)
        buff, = self.adds()
        self.assertEqual((buff.target_eid, buff.source_eid, buff.kind, buff.duration), (1517, 1500, 295, 5.0))
        self.assertAlmostEqual(self.status.get_attack_speed_multiplier(1517, 0.8), 0.35)
        self.status.clear_target(1517, now=1.0)
        self.status.drain_frames()
        self.status.apply_effect(StatusEffect("immune", StatusType.CC_IMMUNITY, 1517, 1517, 100, 1, 101))
        self.economy.players[1500].item_cooldowns.clear()
        self.items.activate(1500, 0, 2.0, self.heroes)
        self.items.step(2.8, self.heroes)
        self.assertFalse(self.status.drain_frames())
        self.assertEqual(self.status.get_attack_speed_multiplier(1517, 2.8), 1)

    def test_death_cancels_living_target_buffs_and_stops_remaining_ticks(self):
        self.equip("fountain_of_renewal")
        self.items.activate(1500, 0, 0.0, self.heroes)
        buffs = self.adds()
        self.ally.hp = 0
        self.ally.is_alive = False
        self.items.step(1.0, self.heroes)
        cancel, = self.status.drain_frames()
        self.assertEqual(buff_wire.parse_buff_cancel(cancel[1]), (1515, buffs[1].instance_id))
        self.assertEqual(self.ally.hp, 0)
        self.assertNotIn(1515, self.status.effects)

    def test_refresh_cancels_old_identity_and_snapshot_preserves_current_identity(self):
        effect = lambda at: StatusEffect("speed", StatusType.MOVE_SPEED_FLAT, 1500, 1500,
                                         3, at, at + 3, 2, native_buff_kind=278)
        self.status.apply_effect(effect(1.0))
        old, = self.adds()
        self.status.apply_effect(effect(2.0))
        frames = self.status.drain_frames()
        self.assertEqual([op for op, _ in frames], [1093, 1086])
        self.assertEqual(buff_wire.parse_buff_cancel(frames[0][1]), (1500, old.instance_id))
        new = buff_wire.parse_buff_add(frames[1][1])
        self.assertEqual(new.instance_id, old.instance_id + 1)
        count = len(self.allocations)
        snapshot, = self.status.snapshot_frames(3.0)
        state = buff_wire.parse_buff_add(snapshot[1])
        self.assertEqual((state.instance_id, state.duration), (new.instance_id, 2.0))
        self.assertEqual(len(self.allocations), count)
        self.assertFalse(self.status.drain_frames())
        self.assertFalse(self.status.snapshot_frames(5.0))

    def test_bad_allocator_cannot_duplicate_a_live_native_identity(self):
        status = StatusManager(instance_allocator=lambda: 400000)
        status.apply_presentation("one", 1500, 1500, 278, 0, 3)
        with self.assertRaises(ValueError):
            status.apply_presentation("two", 1500, 1515, 270, 0, 3)
        self.assertEqual(len(status.presentation.active), 1)
        self.assertEqual(len(status.drain_frames()), 1)

    def test_shortened_buff_keeps_identity_and_cancels_only_at_its_new_deadline(self):
        instance = self.status.apply_presentation("stormguard", 1500, 1500, 373, 10, 4)
        self.status.drain_frames()
        self.assertTrue(self.status.shorten_presentation(1500, "stormguard", 13.8, 11))
        self.assertTrue(self.status.shorten_presentation(1500, "stormguard", 13.6, 12))
        self.assertFalse(self.status.drain_frames())
        snapshot, = self.status.snapshot_frames(12.6)
        buff = buff_wire.parse_buff_add(snapshot[1])
        self.assertEqual((buff.instance_id, buff.duration), (instance, 1.0))
        self.status.clean_expired(13.59)
        self.assertFalse(self.status.drain_frames())
        self.status.clean_expired(13.6)
        cancel, = self.status.drain_frames()
        self.assertEqual(buff_wire.parse_buff_cancel(cancel[1]), (1500, instance))
        self.assertEqual(cancel[0], 1093)
        self.status.clean_expired(14)
        self.assertFalse(self.status.drain_frames())

    def test_shortening_through_present_time_cancels_immediately_without_readding(self):
        instance = self.status.apply_presentation("stormguard", 1500, 1500, 373, 0, 4)
        self.status.drain_frames()
        self.assertTrue(self.status.shorten_presentation(1500, "stormguard", 1, 2))
        cancel, = self.status.drain_frames()
        self.assertEqual(buff_wire.parse_buff_cancel(cancel[1]), (1500, instance))
        self.assertFalse(self.status.snapshot_frames(2))


if __name__ == "__main__":
    unittest.main()

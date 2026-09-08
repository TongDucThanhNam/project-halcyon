"""Native purchase permission, authoritative shop geometry and reconnect state."""
import copy
import itertools
import struct
from types import SimpleNamespace
import unittest

from server import buff_wire, economy, hero_movement, roster, shop_wire
from server.status_effects import StatusManager
from server.test.test_item_input import CAPTURE, item_capture


class TestShopPresentation(unittest.TestCase):
    def setUp(self):
        self.allocations = []
        counter = itertools.count(400000)
        def allocate():
            instance = next(counter)
            self.allocations.append(instance)
            return instance
        self.status = StatusManager(instance_allocator=allocate)
        self.shop = shop_wire.ShopPresentation(self.status, allocate)
        self.hero = hero_movement.HeroMovement(1500, 1, x=-88.5, y=2.0)
        self.enemy = hero_movement.HeroMovement(1517, 2, x=0, y=0)
        self.heroes = {hero.eid: hero for hero in (self.enemy, self.hero)}

    def permission(self, frame):
        self.assertEqual(frame[0], 1087)
        self.assertEqual(len(frame[1]), 38)
        result = buff_wire.parse_buff_state(frame[1])
        self.assertEqual((result.buff.kind, result.state_count, result.words),
                         (174, 1, (0, 0, 452, 0)))
        self.assertEqual(result.buff.target_eid, result.buff.source_eid)
        return result.buff

    def test_entry_refresh_and_same_tick_do_not_duplicate_icon_or_permission(self):
        first, = self.shop.step(10.0, self.heroes)
        permission = self.permission(first)
        self.assertEqual((permission.target_eid, permission.duration), (1500, 1.5))
        icon_frame, = self.status.drain_frames()
        icon = buff_wire.parse_buff_add(icon_frame[1])
        self.assertEqual((icon_frame[0], icon.target_eid, icon.source_eid, icon.kind, icon.duration),
                         (1086, 1500, 1500, 173, -1.0))
        self.assertNotEqual(icon.instance_id, permission.instance_id)
        self.assertFalse(self.shop.step(10.0, self.heroes))
        self.assertFalse(self.shop.step(10.49, self.heroes))
        next_frame, = self.shop.step(10.5, self.heroes)
        refreshed = self.permission(next_frame)
        self.assertNotEqual(refreshed.instance_id, permission.instance_id)
        self.assertFalse(self.status.drain_frames())
        self.assertEqual(len(self.allocations), 3)

    def test_exit_stops_refresh_then_cancels_only_the_icon_at_last_permission_expiry(self):
        self.shop.step(0, self.heroes)
        icon = buff_wire.parse_buff_add(self.status.drain_frames()[0][1])
        self.shop.step(0.5, self.heroes)
        self.hero.x, self.hero.y = 0, 0
        for now in (0.55, 1.0, 1.99):
            self.assertFalse(self.shop.step(now, self.heroes))
            self.assertFalse(self.status.drain_frames())
        self.assertFalse(self.shop.step(2.0, self.heroes))
        cancel, = self.status.drain_frames()
        self.assertEqual((cancel[0], buff_wire.parse_buff_cancel(cancel[1])),
                         (1093, (1500, icon.instance_id)))
        self.assertFalse(self.shop.snapshot_frames(2.0))
        self.assertFalse(self.shop.step(3.0, self.heroes))
        self.assertFalse(self.status.drain_frames())

    def test_quick_reentry_refreshes_immediately_and_keeps_existing_icon(self):
        old, = self.shop.step(0, self.heroes)
        self.status.drain_frames()
        self.hero.x, self.hero.y = 0, 0
        self.shop.step(0.1, self.heroes)
        self.hero.x, self.hero.y = economy.BASE_SHOP_POSITIONS[1]
        refreshed, = self.shop.step(0.2, self.heroes)
        self.assertNotEqual(self.permission(old).instance_id, self.permission(refreshed).instance_id)
        self.assertFalse(self.status.drain_frames())

    def test_shared_gate_covers_own_bases_jungle_boundary_dead_and_nonfinite_actors(self):
        jungle_x, jungle_y = economy.JUNGLE_SHOP_POSITION
        scenarios = (
            (1, *roster.HERO_SPAWNS[1500], True, True),
            (1, *economy.BASE_SHOP_POSITIONS[1], True, True),
            (2, *roster.HERO_SPAWNS[1517], True, True),
            (2, *economy.BASE_SHOP_POSITIONS[2], True, True),
            (1, jungle_x + economy.JUNGLE_SHOP_RADIUS, jungle_y, True, True),
            (2, jungle_x, jungle_y, True, True),
            (1, jungle_x + economy.JUNGLE_SHOP_RADIUS + .01, jungle_y, True, False),
            (1, *economy.BASE_SHOP_POSITIONS[2], True, False),
            (2, *economy.BASE_SHOP_POSITIONS[1], True, False),
            (1, *economy.BASE_SHOP_POSITIONS[1], False, False),
            (1, float('nan'), 2, True, False),
            (1, float('inf'), 2, True, False),
        )
        for team, x, y, alive, expected in scenarios:
            with self.subTest(team=team, x=x, y=y, alive=alive):
                self.setUp()
                actor = SimpleNamespace(eid=1500, team=team, x=x, y=y, is_alive=alive)
                self.assertEqual(economy.can_shop(actor), expected)
                self.assertEqual(bool(self.shop.step(0, [actor])), expected)
                self.assertEqual(bool(self.status.drain_frames()), expected)

    def test_shared_allocations_and_self_targets_do_not_grant_another_hero_access(self):
        self.enemy.x, self.enemy.y = economy.BASE_SHOP_POSITIONS[2]
        existing = self.status.apply_presentation('item-speed', 1500, 1500, 278, 0, 3)
        frames = self.shop.step(0, self.heroes)
        self.assertEqual([self.permission(frame).target_eid for frame in frames], [1500, 1517])
        pending = self.status.drain_frames()
        self.assertEqual([buff_wire.parse_buff_add(p).kind for _, p in pending], [278, 173, 173])
        self.assertEqual(len(self.allocations), len(set(self.allocations)))
        self.hero.x, self.hero.y = 0, 0
        self.shop.step(0.1, self.heroes)
        refreshed, = self.shop.step(0.5, self.heroes)
        self.assertEqual(self.permission(refreshed).target_eid, 1517)
        self.shop.step(1.5, self.heroes)
        cancel, = self.status.drain_frames()
        self.assertEqual(buff_wire.parse_buff_cancel(cancel[1])[0], 1500)
        self.assertEqual(self.status.presentation.active[(1500, 'item-speed')].instance_id, existing)
        self.assertIn((1517, shop_wire.SHOP_ICON_KEY), self.status.presentation.active)

    def test_reconnect_uses_remaining_current_permission_without_changing_live_schedule(self):
        self.assertFalse(self.shop.snapshot_frames(0))
        self.shop.step(10, self.heroes)
        latest, = self.shop.step(10.5, self.heroes)
        state = copy.deepcopy((self.shop.latest, self.shop._eligible, self.shop._last_step_at,
                               self.allocations, self.status.presentation.active,
                               self.status.presentation._frames))
        snapshot, = self.shop.snapshot_frames(10.75)
        permission = self.permission(snapshot)
        self.assertEqual(permission.instance_id, self.permission(latest).instance_id)
        self.assertEqual(permission.duration, 1.25)
        self.assertEqual((self.shop.latest, self.shop._eligible, self.shop._last_step_at,
                          self.allocations, self.status.presentation.active,
                          self.status.presentation._frames), state)
        self.assertFalse(self.shop.step(10.99, self.heroes))
        self.assertEqual(len(self.shop.step(11, self.heroes)), 1)
        self.hero.x, self.hero.y = 0, 0
        self.shop.step(11.1, self.heroes)
        remaining, = self.shop.snapshot_frames(12)
        self.assertEqual(self.permission(remaining).duration, .5)
        self.assertFalse(self.shop.snapshot_frames(12.5))

    def test_death_stops_permission_and_respawn_restores_cleared_icon(self):
        self.shop.step(0, self.heroes)
        self.status.drain_frames()
        self.hero.is_alive = False
        self.status.clear_target(1500, now=.1)
        self.status.drain_frames()
        self.assertFalse(self.shop.step(.1, self.heroes))
        self.assertFalse(self.shop.step(.5, self.heroes))
        self.hero.is_alive = True
        self.assertEqual(len(self.shop.step(.6, self.heroes)), 1)
        icon, = self.status.drain_frames()
        self.assertEqual(buff_wire.parse_buff_add(icon[1]).kind, 173)


@unittest.skipUnless(CAPTURE.is_file(), 'external passive item capture unavailable')
class TestShopNativeCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = item_capture()['s2c']

    def test_all_409_native_permission_payloads_match_remaining_state_and_never_cancel(self):
        records = [row for row in self.frames if row.opcode == 1087 and
                   struct.unpack_from('>I', row.payload)[0] == 1500 and
                   struct.unpack_from('>H', row.payload, 14)[0] == 174]
        self.assertEqual(len(records), 409)
        identities = set()
        for row in records:
            target, source, duration, instance, kind = struct.unpack_from('>IIeIH', row.payload)
            self.assertEqual((target, source, kind), (1500, 1500, 174))
            self.assertEqual(struct.unpack_from('>H4I', row.payload, 16), (1, 0, 0, 452, 0))
            current = shop_wire.ShopPermission(target, instance, 0)
            self.assertEqual(current.payload(1.5 - duration), row.payload)
            identities.add(instance)
        self.assertEqual(len(identities), 409)
        self.assertEqual(sum(struct.unpack_from('>e', row.payload, 8)[0] == 1.5 for row in records), 408)
        cancels = {struct.unpack_from('>II', row.payload) for row in self.frames if row.opcode == 1093}
        self.assertFalse({(1500, instance) for instance in identities} & cancels)

    def test_live_emitter_matches_native_permission_before_a_successful_buy(self):
        native = self.frames[1991]
        self.assertEqual(native.opcode, 1087)
        self.assertEqual(struct.unpack_from('>IIeIH', native.payload), (1500, 1500, 1.5, 4190, 174))
        allocate = itertools.count(4190).__next__
        status = StatusManager(instance_allocator=allocate)
        presentation = shop_wire.ShopPresentation(status, allocate)
        hero = hero_movement.HeroMovement(1500, 1, x=-88.5, y=2)
        emitted, = presentation.step(native.time, {1500: hero})
        self.assertEqual(emitted, (native.opcode, native.payload))
        echo = self.frames[2046]
        self.assertEqual(echo.opcode, 1081)
        self.assertEqual(struct.unpack_from('>II', echo.payload), (1500, 467))

    def test_native_icon_is_indefinite_with_explicit_cancellation_after_last_refresh(self):
        for add_index, last_refresh_index, cancel_index in (
                (13814, 14419, 14654), (39701, 40604, 40760), (49755, 50415, 50702)):
            added, refresh, canceled = (self.frames[index] for index in (add_index, last_refresh_index, cancel_index))
            self.assertEqual((added.opcode, refresh.opcode, canceled.opcode), (1086, 1087, 1093))
            icon = buff_wire.parse_buff_add(added.payload)
            self.assertEqual((icon.target_eid, icon.source_eid, icon.kind, icon.duration), (1500, 1500, 173, -1))
            self.assertEqual(buff_wire.build_buff_add(1500, 1500, -1, icon.instance_id, 173), added.payload)
            self.assertEqual(buff_wire.build_buff_cancel(1500, icon.instance_id), canceled.payload)
            self.assertGreaterEqual(canceled.time - refresh.time, 1.5)
            self.assertLess(canceled.time - refresh.time, 1.6)


if __name__ == '__main__':
    unittest.main()

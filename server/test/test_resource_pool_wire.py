"""Production damage/publication against the pinned native resource consumer.

The small wire ledger below models only 1053/1054's recovered arithmetic:
ELF c01624 -> caa5a0, c5f6b0. It is not a gameplay simulation oracle.
"""
import struct
import unittest

from server import roster, wire
from server.status_effects import StatusEffect, StatusType
from server.structures import StructureManager
from server.test.test_ability_cc_presentation import session


class NativeResources:
    def __init__(self, eid, hp):
        self.eid, self.hp, self.barrier, self.fortified = eid, hp, 0.0, 0.0

    def consume(self, frames):
        for op, payload in frames:
            if len(payload) < 4 or struct.unpack_from('>I', payload)[0] != self.eid:
                continue
            if op == 1053:
                field = {0: 'hp', 4: 'barrier', 5: 'fortified'}.get(payload[8])
                if field:
                    amount = struct.unpack_from('>f', payload, 4)[0]
                    setattr(self, field, max(0.0, getattr(self, field) + amount))
            elif op == 1054:
                amount = struct.unpack_from('>f', payload, 8)[0]
                if amount < 0:
                    absorbed = min(self.barrier, -amount)
                    self.barrier -= absorbed
                    amount += absorbed
                    fortified = min(self.fortified, self.hp, -amount * .5)
                    self.fortified -= fortified
                    amount += fortified
                self.hp = max(0.0, self.hp + amount)


class ResourcePoolWireTests(unittest.TestCase):
    def setUp(self):
        self.world, self.frames, _, _, _ = session()
        self.hero = self.world.hero_sims[1500]
        self.enemy = self.world.hero_sims[1517]
        self.hero.hp = self.hero.max_hp = 1000
        self.native = NativeResources(1500, 1000)

    def pool(self, key, amount, *, kind=StatusType.BARRIER, until=5):
        self.world.status_manager.apply_effect(StatusEffect(key, kind, 1500, 1500,
            until, 0, until, amount))

    def drain(self):
        self.world._drain_effect_frames()
        self.native.consume(self.frames)
        self.frames.clear()

    def hit(self, damage, at):
        frames = self.world._deal_damage(self.enemy, self.hero, damage, 'true', at)
        self.world._emit_frames(frames)
        self.drain()
        self.assertAlmostEqual(self.native.hp, self.hero.hp)
        self.assertAlmostEqual(self.native.barrier, self.world.status_manager.get_barrier(1500, at))
        self.assertAlmostEqual(self.native.fortified, self.world.status_manager.get_fortified_health(1500, at))
        return frames

    def test_barrier_gain_partial_hit_break_and_expiry_keep_client_resources_equal(self):
        self.pool('flask', 255)
        self.drain()
        self.assertEqual(self.native.barrier, 255)
        self.assertTrue(any(op == 1054 for op, _ in self.hit(100, 1)))
        self.hit(200, 2)
        self.assertEqual(self.hero.hp, 955)
        self.pool('remaining', 325)
        self.drain()
        self.hit(119.4523468, 3)
        self.world.status_manager.clean_expired(5)
        self.drain()
        self.assertEqual(self.native.barrier, 0)
        self.assertEqual(self.hero.hp, 955)

    def test_expiry_before_hit_and_fortified_health_are_not_double_absorbed(self):
        self.pool('expired', 255, until=1)
        self.pool('husk', 300, kind=StatusType.FORTIFIED_HEALTH)
        self.drain()
        self.hit(400, 1)
        self.assertEqual((self.hero.hp, self.native.fortified), (800, 100))
        self.hit(300, 2)
        self.assertEqual((self.hero.hp, self.native.fortified), (600, 0))

    def test_unpublished_gain_is_sent_before_the_first_absorbed_hit(self):
        self.pool('husk', 300, kind=StatusType.FORTIFIED_HEALTH)
        frames = self.hit(100, 1)
        gain = next(i for i, (op, p) in enumerate(frames) if op == 1053 and p[8] == 5)
        damage = next(i for i, (op, _) in enumerate(frames) if op == 1054)
        self.assertLess(gain, damage)

    def test_reconnect_and_refresh_or_cleanse_preserve_remaining_pool(self):
        self.pool('first', 200)
        self.pool('second', 100)
        self.drain()
        self.hit(75, 1)
        reconnect = NativeResources(1500, self.hero.hp)
        reconnect.consume(self.world.status_manager.snapshot_frames(1))
        self.assertEqual(reconnect.barrier, 225)
        self.pool('first', 400)
        self.drain()
        self.assertEqual(self.native.barrier, 500)
        self.world.status_manager.remove_effect(1500, 'first', now=2)
        self.drain()
        self.assertEqual(self.native.barrier, 100)
        self.world.status_manager.clear_target(1500, now=3)
        self.drain()
        self.assertEqual(self.native.barrier, 0)

    def test_lethal_damage_caps_fortified_absorption_at_current_health(self):
        self.hero.hp = self.native.hp = 100
        self.pool('husk', 150, kind=StatusType.FORTIFIED_HEALTH)
        self.drain()
        frames = self.world._deal_damage(self.enemy, self.hero, 400, 'true', 1)
        # Observe the combat action before the separate death clear transition.
        self.native.consume(frames)
        self.assertEqual(self.hero.hp, 0)
        self.assertEqual(self.native.hp, 0)
        self.assertEqual(self.native.fortified, 50)
        self.assertEqual(self.world.status_manager.get_fortified_health(1500, 1), 50)

    def test_structure_protection_applies_before_a_published_pool(self):
        self.world.structures = StructureManager()
        target = self.world.structures.structures[3539]
        native = NativeResources(target.eid, target.hp)
        self.world.status_manager.apply_effect(StatusEffect('structure-pool', StatusType.BARRIER,
            target.eid, target.eid, 5, 0, 5, 20))
        native.consume(self.world.status_manager.drain_frames())
        frames = self.world._deal_damage(self.hero, target, 100, 'true', 1)
        native.consume(frames)
        self.assertEqual(target.hp, target.max_hp - 5)  # 100 * .25 protection, then 20 absorbed
        self.assertEqual(native.hp, target.hp)
        self.assertEqual(native.barrier, 0)


if __name__ == '__main__':
    unittest.main()

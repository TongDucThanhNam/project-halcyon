"""Native inventory-instance input validation and independent passive evidence."""
from functools import lru_cache
import math
import struct
import unittest

from server.paths import research_dir
from server import buff_wire, cooldown_wire, economy, item_input
from Tools.Teardown.inspect_item_input import inspect_uses, read_capture


CAPTURE = research_dir('vg_max') / 'vg5_final.pcap'
MATCH_UUID = "045f86d4-7ef2-4125-a835-e70a96288c88"


@lru_cache(maxsize=1)
def item_capture():
    """The operator-owned corpus remains outside the repository."""
    return read_capture(CAPTURE, MATCH_UUID, 7034)


class TestItemInputValidation(unittest.TestCase):
    def test_native_default_items_remain_owned_with_all_six_equipment_slots_full(self):
        player = economy.PlayerEconomy(1500, start_gold=10000)
        for slot in range(6):
            self.assertEqual(player.buy_item(458), slot)
        self.assertEqual(player.inventory_instances, list(range(2002, 2008)))
        self.assertEqual(item_input.resolve_owned_item(player, 2000), item_input.OwnedItemInstance(2000, 457))
        self.assertEqual(item_input.resolve_owned_item(player, 2001), item_input.OwnedItemInstance(2001, 526))
        self.assertEqual(item_input.resolve_owned_item(player, 2005), item_input.OwnedItemInstance(2005, 458, 3))
        player.sell_item(3)
        self.assertIsNone(item_input.resolve_owned_item(player, 2005))
        self.assertEqual(set(player.default_items), {2000, 2001})

    def test_default_item_frames_preserve_native_inventory_and_timer_state(self):
        player = economy.PlayerEconomy(1500)
        self.assertTrue(player.default_items[2000].begin_cooldown(10))
        self.assertFalse(player.default_items[2000].begin_cooldown(11))
        frames = player.default_item_frames(20)
        self.assertEqual([op for op, _ in frames], [1085, 1162, 1085, 1162])
        self.assertEqual(struct.unpack_from(">IIIH", frames[0][1]), (1500, 457, 2000, 0))
        self.assertEqual(struct.unpack_from(">IIIH", frames[2][1]), (1500, 526, 2001, 0))
        flask = cooldown_wire.parse_timer_tick(frames[1][1])
        totem = cooldown_wire.parse_timer_tick(frames[3][1])
        self.assertEqual((flask.remaining, flask.duration, flask.state), (110.0, 120.0, bytes((0, 1, 2, 0, 0, 0))))
        self.assertEqual((totem.remaining, totem.duration, totem.state), (0.0, 150.0, bytes((1, 2, 2, 0, 0, 0))))
        self.assertTrue(player.default_items[2000].is_ready(130))

    def test_instance_resolution_uses_only_current_authenticated_inventory(self):
        inventory = [2002, None, 2005, None, None, None]
        self.assertEqual(item_input.resolve_inventory_slot(inventory, 2005), 2)
        self.assertIsNone(item_input.resolve_inventory_slot(inventory, 2003))
        self.assertIsNone(item_input.resolve_inventory_slot(inventory, 2000))
        inventory[2] = None  # a sold or consumed item cannot reuse its old slot
        self.assertIsNone(item_input.resolve_inventory_slot(inventory, 2005))
        with self.assertRaises(ValueError):
            item_input.resolve_inventory_slot([2002, 2002], 2002)

    def test_rejects_malformed_instance_intent(self):
        valid = item_input.build_item_use(2002)
        for payload in (valid[:-1], valid + bytes(1), valid[:-1] + b"\x01", bytes(6)):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                item_input.parse_item_input(1096, payload)
        for instance in (-1, 0, 2**32, True):
            with self.subTest(instance=instance), self.assertRaises(ValueError):
                item_input.build_item_use(instance)
        with self.assertRaises(ValueError):
            item_input.parse_item_input(1078, valid)

    def test_rejects_malformed_ground_intent(self):
        valid = item_input.build_ground_item_use(2001, 10.0, -4.0, height=0.5)
        for payload in (valid[:-1], valid + bytes(1), valid[:-1] + b"\x01",
                        struct.pack(">f", math.nan) + valid[4:],
                        struct.pack(">f", math.inf) + valid[4:]):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                item_input.parse_item_input(1098, payload)


@unittest.skipUnless(CAPTURE.is_file(), "external passive item capture unavailable")
class TestItemInputCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = item_capture()

    def test_all_targetless_and_ground_intents_rebuild_exactly(self):
        rows = [row for row in self.frames["c2s"] if row.opcode in (1096, 1098)]
        self.assertEqual(sum(row.opcode == 1096 for row in rows), 8)
        self.assertEqual(sum(row.opcode == 1098 for row in rows), 1)
        instances = {}
        for row in rows:
            intent = item_input.parse_item_input(row.opcode, row.payload)
            instances[intent.instance_id] = instances.get(intent.instance_id, 0) + 1
            rebuilt = (item_input.build_item_use(intent.instance_id)
                       if intent.target_position is None else
                       item_input.build_ground_item_use(intent.instance_id, *intent.target_position,
                                                        height=intent.height))
            self.assertEqual(rebuilt, row.payload)
        self.assertEqual(instances, {2000: 2, 2005: 6, 2001: 1})

    def test_inventory_creation_and_server_echo_anchor_item_identity(self):
        uses = inspect_uses(self.frames, 1500)
        self.assertEqual(len(uses), 9)
        for row in uses:
            self.assertEqual(row["item"], {2000: 457, 2001: 526, 2005: 487}[row["instance"]])
        self.assertEqual(sum(row["echo_time"] is not None for row in uses), 7)
        self.assertEqual(sum(bool(row["following_buffs"]) for row in uses), 4)
        self.assertEqual([row["following_buffs"][0]["kind"] for row in uses
                          if row["following_buffs"]], [259, 270, 259, 270])
        # The repeated Fountain click is acknowledged without another activation.
        repeated = next(row for row in uses if abs(row["time"] - 427.481874) < 0.001)
        self.assertIsNotNone(repeated["echo_time"])
        self.assertFalse(repeated["following_buffs"])

    def test_flask_and_fountain_acks_precede_native_timed_buffs(self):
        expected = ((281.153880, 2000, 259, 5.0), (427.281952, 2005, 270, 3.0),
                    (484.615350, 2000, 259, 5.0), (503.272990, 2005, 270, 3.0))
        for time, instance, kind, duration in expected:
            request = next(row for row in self.frames["c2s"]
                           if row.opcode == 1096 and abs(row.time - time) < 0.001)
            self.assertEqual(item_input.parse_item_input(1096, request.payload).instance_id, instance)
            ack = next(row for row in self.frames["s2c"] if request.time < row.time < request.time + 0.4
                       and row.opcode == 1096 and row.payload == request.payload)
            adds = [buff_wire.parse_buff_add(row.payload) for row in self.frames["s2c"]
                    if ack.time < row.time < ack.time + 0.1 and row.opcode == 1086]
            selected = [buff for buff in adds if buff.target_eid == 1500 and buff.kind == kind]
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].source_eid, 1500)
            self.assertEqual(selected[0].duration, duration)
            self.assertNotEqual(selected[0].instance_id, instance)

    def test_ground_totem_intent_echoes_and_creates_matching_native_actor(self):
        request = next(row for row in self.frames["c2s"] if row.opcode == 1098)
        intent = item_input.parse_item_input(1098, request.payload)
        ack = next(row for row in self.frames["s2c"] if request.time < row.time < request.time + 0.4
                   and row.opcode == 1098 and row.payload == request.payload)
        # Native 1010 VisionTotem archetype 392; this check uses observed field
        # offsets independently of our actor-spawn builder.
        spawn = next(row for row in self.frames["s2c"] if ack.time < row.time < ack.time + 0.1
                     and row.opcode == 1010 and struct.unpack_from(">I", row.payload, 8)[0] == 7071)
        self.assertEqual(struct.unpack_from(">I", spawn.payload)[0], 392)
        self.assertEqual(struct.unpack_from(">f", spawn.payload, 12)[0], intent.target_position[0])
        self.assertEqual(struct.unpack_from(">f", spawn.payload, 20)[0], intent.target_position[1])
        aura = next(buff_wire.parse_buff_add(row.payload) for row in self.frames["s2c"]
                    if spawn.time <= row.time < spawn.time + 0.1 and row.opcode == 1086
                    and struct.unpack_from(">I", row.payload)[0] == 7071)
        self.assertEqual((aura.source_eid, aura.kind, aura.duration), (1500, 287, -1.0))


if __name__ == "__main__":
    unittest.main()

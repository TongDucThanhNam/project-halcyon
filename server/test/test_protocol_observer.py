"""Independent synthetic wire contracts; no owned payload fixtures."""
import struct
import unittest

from Tools.protocol_observer import Observer
from server import lifecycle_wire, roster


def hero(eid=1500, *, hp=500, points=1, level=1):
    b = bytearray(746)
    struct.pack_into('>IIII',b,0,244,0,eid,1)
    for offset,value in ((18,-70),(26,30),(42,hp),(46,500),(122,200),(294,level),(314,points)):
        struct.pack_into('>f',b,offset,value)
    return bytes(b)


def actor(eid=4000, slot=6, archetype=371, cls=0xC10B41DA, size=126):
    b = bytearray(size)
    struct.pack_into('>IIIfff',b,0,archetype,cls,eid,17,0,2)
    b[116],b[121] = slot,2
    if size == 122:
        struct.pack_into('>ff',b,36,123,2500)
    return bytes(b)


class TestObserver(unittest.TestCase):
    def test_eid_offset_unknown_hp_and_snapshot(self):
        o = Observer()
        o.consume(1010,actor())
        self.assertNotIn(371,o.actors)
        self.assertEqual(o.actors[4000].position,(17,2))
        self.assertEqual(o.actors[4000].tier,1)
        self.assertIsNone(o.actors[4000].hp)
        o.consume(1054,roster.build_combat_delta(1500,4000,-50))
        self.assertIsNone(o.actors[4000].hp)
        o.consume(1010,actor(size=122))
        self.assertEqual(o.actors[4000].hp,123)

    def test_slot_release_not_retirement_and_reuse_generation(self):
        o = Observer()
        o.consume(1010,actor())
        generation = o.actors[4000].generation
        o.consume(1073,roster.build_destroy(4000))
        self.assertEqual(o.slots[6],4000)
        o.consume(1035,roster.build_despawn(4000))
        self.assertNotIn(6,o.slots)
        self.assertNotIn(4000,o.actors)
        o.consume(1010,actor(eid=5000))
        self.assertEqual(o.actors[5000].generation,generation+1)
        o.consume(1016,roster.build_move_intent(6,5,6))
        self.assertEqual(o.actors[5000].destination,(5,6))

    def test_resource_pool_arithmetic(self):
        o = Observer()
        o.consume(1011,hero())
        for attr,amount in ((4,20),(5,100)):
            o.consume(1053,roster.build_hero_stat(1500,amount,attr))
        o.consume(1054,roster.build_combat_delta(1517,1500,-100))
        a = o.actors[1500]
        self.assertEqual((a.hp,a.barrier,a.fortified),(460,0,60))

    def test_lifecycle_waits_for_1074(self):
        o = Observer()
        o.consume(1011,hero())
        o.consume(1072,lifecycle_wire.build_hero_death(1500,1517))
        o.consume(1075,lifecycle_wire.build_respawn_countdown(1500,10))
        o.consume(1073,lifecycle_wire.build_hero_corpse_hide(1500))
        o.consume(1033,lifecycle_wire.build_hero_respawn(1500,-70,30))
        self.assertFalse(o.actors[1500].alive)
        self.assertEqual(o.slots[0],1500)
        o.consume(1074,lifecycle_wire.build_hero_respawn_complete(1500,-70,30))
        self.assertTrue(o.actors[1500].alive)
        self.assertEqual(o.actors[1500].hp,500)
        self.assertEqual((o.deaths,o.revivals),(1,1))

    def test_unmeasured_level_growth_invalidates_not_fabricates_resources(self):
        o = Observer()
        o.consume(1011,hero())
        o.consume(1076,struct.pack('>II6x',1500,1))
        a = o.actors[1500]
        self.assertEqual((a.level,a.points),(2,2))
        self.assertIsNone(a.hp)
        self.assertIsNone(a.max_hp)
        o.consume(1053,roster.build_hero_stat(1500,5,0))
        self.assertIsNone(a.hp)

    def test_structure_death_order_detects_locked_tier_violation(self):
        o = Observer()
        o.consume(1010,actor())
        o.consume(1010,actor(eid=4001,slot=7,archetype=370))
        o.consume(1072,lifecycle_wire.build_hero_death(4001,1500))
        self.assertEqual(o.structure_order_errors,[{'eid':4001,'preceding_alive':[4000]}])

    def test_reconnect_ranks_inventory_and_gold_reset(self):
        o = Observer()
        for _ in range(2):
            o.reconnect()
            o.consume(1011,hero(points=4,level=4))
            for _ in range(3):
                o.consume(1082,roster.build_inventory_slot(1500,0))
            o.consume(1085,roster.build_item_inventory(1500,458,999))
            o.consume(1053,roster.build_hero_stat(1500,700,6))
            self.assertEqual(o.actors[1500].ranks,{0:3})
            self.assertEqual(o.actors[1500].points,1)
            self.assertEqual(o.actors[1500].gold,1300)
            self.assertEqual(o.actors[1500].inventory,{999:458})

    def test_result_requires_notice_crystal_death_reason_and_order(self):
        o = Observer()
        o.consume(1010,actor(archetype=293))
        result = struct.pack('>IBx',1,0)
        o.consume(1009,result)
        self.assertFalse(o.finished())
        o.consume(1106,bytes(6))
        o.consume(1072,lifecycle_wire.build_hero_death(4000,1500))
        self.assertFalse(o.finished())
        o.consume(1009,struct.pack('>IBx',1,1))
        self.assertFalse(o.finished())
        o.consume(1009,result)
        self.assertTrue(o.finished())

    def test_bounded_retention_and_released_actor_state(self):
        o = Observer(retention=8)
        for eid in range(4000,4100):
            o.consume(1010,actor(eid=eid))
            o.consume(1035,roster.build_despawn(eid))
        self.assertEqual(len(o.window),8)
        self.assertEqual(len(o.actors),0)
        self.assertEqual(len(o.slot_generations),1)
        self.assertEqual(o.sequence,200)

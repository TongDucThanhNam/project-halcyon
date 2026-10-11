import unittest

from Tools.protocol_observer import Actor
from Tools.protocol_policy import Policy


def scene():
    return {1500:Actor(1500,'hero',1,0,hero_id=244,position=(0,2),spawn=(-70,30),hp=500,max_hp=500),
            3539:Actor(3539,'structure',2,7,position=(17,2),tier=1),
            3540:Actor(3540,'structure',2,8,position=(35,2),tier=2)}


class TestPolicy(unittest.TestCase):
    def test_unknown_structure_hp_is_targetable_and_lowest_tier_only(self):
        a = scene()
        a[1500].position = (5,2)
        p = Policy(1500,'Skye')
        intent = p.step(a,1)
        self.assertEqual(intent.opcode,1060)
        self.assertEqual(p.target,3539)
        self.assertIsNone(p.step(a,2))
        a[3539].alive = False
        self.assertEqual(p.step(a,3).opcode,1012)

    def test_minions_first_and_target_retention(self):
        a = scene()
        a[4000] = Actor(4000,'minion',2,9,position=(3,2))
        p = Policy(1500,'Skye')
        self.assertEqual(p.step(a,1).opcode,1060)
        self.assertEqual(p.target,4000)
        self.assertIsNone(p.step(a,30))
        a[4000].alive = False
        self.assertEqual(p.step(a,31).opcode,1012)

    def test_dead_waits_for_alive_and_low_health_recalls(self):
        a = scene()
        p = Policy(1500,'Skye')
        a[1500].alive = False
        self.assertIsNone(p.step(a,1))
        a[1500].alive = True
        a[1500].hp = 20
        self.assertEqual(p.step(a,2).reason,'safe recall')
        self.assertIsNone(p.step(a,3))

    def test_learn_gates_and_no_unpaced_spam(self):
        a = scene()
        a[1500].points = 1
        p = Policy(1500,'Skye')
        self.assertEqual(p.step(a,1).opcode,1078)
        self.assertIsNone(p.step(a,1.1))

    def test_shop_only_at_observed_base_with_gold(self):
        a = scene()
        me = a[1500]
        me.gold = 600
        p = Policy(1500,'Skye')
        self.assertNotEqual(p.step(a,1).opcode,1081)
        me.position = me.spawn
        self.assertEqual(p.step(a,3).opcode,1081)
        me.gold = None
        self.assertIsNone(p.step(a,7), 'unknown gold cannot authorize a buy; prior move remains active')


class TestFinishNegativeControls(unittest.TestCase):
    def test_timeout_cannot_pass_without_all_results(self):
        from Tools import protocol_participants as pp
        output = pp.new_output()
        players = [pp.Participant('127.0.0.1',1,pp.MATCH_ID,h,output,heartbeat_port=0) for h in pp.HEROES]
        try:
            for p in players:
                p.eid = 1500
            with self.assertRaisesRegex(pp.StageFailure,'timeout'):
                pp.full_match(players,output,timeout=0)
        finally:
            for p in players:
                p.close()

    def test_five_results_are_not_six(self):
        from Tools.protocol_observer import Observer
        from server.test.test_protocol_observer import actor
        from server import lifecycle_wire
        import struct
        observers = [Observer() for _ in range(6)]
        for o in observers[:5]:
            o.consume(1010,actor(archetype=293))
            o.consume(1106,bytes(6))
            o.consume(1072,lifecycle_wire.build_hero_death(4000,1500))
            o.consume(1009,struct.pack('>IBx',1,0))
        self.assertFalse(all(o.finished() for o in observers))

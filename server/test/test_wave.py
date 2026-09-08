"""Lane-minion wave slice — unit tests against corpus-pinned byte shapes.

Corpus source: vg5_final.pcap match 5 (match id 045f86d4-7ef2-4125-a835-
e70a96288c88), wave-1 raw burst at +22.974 s, eid 4610 (right) / 4611
(left). Only proven fields are pinned (AGENTS.md payload rule: constants +
layout, not wholesale captured payloads).
"""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server import roster, wave

# Corpus-pinned f32 fragments (vg5_final raw hex)
HEX_SPAWN_X_R = "428e8f5c"      # 71.280 (right spawn / 1010 position)
HEX_SPAWN_Y = "414ee148"        # 12.930
HEX_POINT_A_X = "428daeb6"      # 70.841 (lane-side 1070)
HEX_POINT_A_Y = "414c9ca6"      # 12.788


class TestMinionSpawn1010(unittest.TestCase):
    """s2c 1010 lane-minion variant: +0 spawner, +4 class, +8 minion eid,
    126-B no-HP map — measured on all 242 vg5_final lane-minion frames."""

    def test_id_map_and_position(self):
        body = roster.build_minion_spawn_1010(
            366, 4610, roster.LANE_SPAWN_RIGHT[0], roster.LANE_SPAWN_RIGHT[1],
            33, roster.ENTITY_STATE_SIDE_RIGHT)
        self.assertEqual(len(body), roster.ENTITY_FULL_UPDATE_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">I", body, 0)[0], 366)
        self.assertEqual(struct.unpack_from(">I", body, 4)[0],
                         roster.LANE_MINION_CLASS)
        self.assertEqual(struct.unpack_from(">I", body, 8)[0], 4610)
        x, z, y = struct.unpack_from(">fff", body, 12)
        self.assertEqual(struct.pack(">f", x), bytes.fromhex(HEX_SPAWN_X_R))
        self.assertEqual(struct.pack(">f", y), bytes.fromhex(HEX_SPAWN_Y))
        self.assertEqual(z, roster.GROUND_Z)
        self.assertEqual(struct.unpack_from(">fff", body, 24),
                         (0.0, 0.0, 1.0))                     # facing (0, 1)

    def test_measured_tail_bytes_per_side(self):
        right = roster.build_minion_spawn_1010(
            366, 4610, 71.28, 12.93, 33, roster.ENTITY_STATE_SIDE_RIGHT)
        left = roster.build_minion_spawn_1010(
            366, 4611, -71.28, 12.93, 34, roster.ENTITY_STATE_SIDE_LEFT)
        self.assertEqual(right[88:96], b"\x01" * 8)          # _TAIL_88
        self.assertEqual(right[112:116], b"\xff\xff\xff\xff")
        self.assertEqual(right[96:99], b"\x00\x00\x01")
        self.assertEqual(right[116:122], b"\x21\x01\x00\x01\x01\x02")
        self.assertEqual(left[96:99], b"\x00\x01\x00")
        self.assertEqual(left[116:122], b"\x22\x01\x00\x01\x00\x01")
        self.assertEqual(right[122:], bytes(4))
        self.assertEqual(left[122:], bytes(4))
        self.assertNotEqual(right[4:8], bytes(4))            # class present

    def test_actor_slot_rejects_overflow_instead_of_aliasing_live_entity(self):
        with self.assertRaises(ValueError):
            roster.build_minion_spawn_1010(
                366, 4610, 71.28, 12.93, 0x1FF, roster.ENTITY_STATE_SIDE_RIGHT)


class TestEntityState1067(unittest.TestCase):
    """s2c 1067 spawn shape: [u32 eid][side][01][state][7B 0] — corpus
    00001202 02 01 00… then 02 01 0f… (+0.104 s)."""

    def test_spawn_and_moving_states(self):
        spawned = roster.build_entity_state(
            4610, roster.ENTITY_STATE_SIDE_RIGHT, roster.ENTITY_STATE_SPAWNED)
        moving = roster.build_entity_state(
            4610, roster.ENTITY_STATE_SIDE_RIGHT, roster.ENTITY_STATE_MOVING)
        self.assertEqual(len(spawned), roster.ENTITY_STATE_PAYLOAD_SIZE)
        self.assertEqual(spawned, bytes.fromhex("00001202") + b"\x02\x01\x00" + bytes(7))
        self.assertEqual(moving[-10:], b"\x02\x01\x0f" + bytes(7))
        self.assertEqual(moving[6], 0x0F)

    def test_left_side_and_validation(self):
        left = roster.build_entity_state(
            4611, roster.ENTITY_STATE_SIDE_LEFT, roster.ENTITY_STATE_SPAWNED)
        self.assertEqual(left[4], 0x01)
        with self.assertRaises(ValueError):
            roster.build_entity_state(4611, 0x03, 0)


class TestMoveIntent1016(unittest.TestCase):
    """s2c 1016: [u8 seq][f32 target][f32 target][5B 0]; corpus wave-1
    carried the first lane point of the walking side."""

    def test_shape_and_first_target(self):
        intent = roster.build_move_intent(
            33, roster.LANE_PATH_RIGHT[0][0], roster.LANE_PATH_RIGHT[0][1])
        self.assertEqual(len(intent), roster.MOVE_INTENT_PAYLOAD_SIZE)
        self.assertEqual(intent[0], 33)
        x, y = struct.unpack_from(">ff", intent, 1)
        self.assertEqual((round(x, 3), round(y, 3)),
                         (round(roster.LANE_PATH_RIGHT[0][0], 3),
                          round(roster.LANE_PATH_RIGHT[0][1], 3)))
        self.assertEqual(intent[9:], bytes(5))


class TestWaveDirector(unittest.TestCase):
    """Deterministic schedule: wave 1 at +22.974 s, 5 pairs at the measured
    offsets, eids 4610.. sequential, right-even/left-odd pairing."""

    def _director(self, **kw):
        return wave.Director(100.0, seq_1010=kw.pop("seq", [0x20]), **kw)

    def _pump_until(self, d, duration, step=0.05):
        """Pump in `step` increments for `duration` seconds (relative to the
        director's t0)."""
        frames = []
        t = 0.0
        while t < duration:
            t += step
            frames += d.pump(d.t0 + t)
        return frames

    def test_wave1_pair0_emission_order(self):
        d = self._director()
        frames = d.pump(d.t0 + roster.WAVE_FIRST_SPAWN_AT + 0.01)
        ops = [op for op, _ in frames]
        # corpus raw-burst order: 1010,1016,1070(B) right · 1010,1016,1070(B)
        # left · 1070(A) left · 1070(A) right · 1067 left · 1067 right
        self.assertEqual(ops, [1010, 1016, 1070, 1010, 1016, 1070,
                               1070, 1070, 1067, 1067])
        # minion eid lives at +8 on the 1010, +0 on 1070/1067
        eids = [struct.unpack_from(">I", p, 8)[0] if op == 1010
                else struct.unpack_from(">I", p, 0)[0]
                for op, p in frames if op in (1010, 1070, 1067)]
        self.assertEqual(sorted(set(eids)), [4610, 4611])
        # 1010: right eid first, then left
        self.assertEqual(struct.unpack_from(">I", frames[0][1], 8)[0], 4610)
        self.assertEqual(struct.unpack_from(">I", frames[3][1], 8)[0], 4611)
        # spawner +0 and class +4 (wave-1 pair 0 → 366)
        self.assertEqual(struct.unpack_from(">I", frames[0][1], 0)[0], 366)
        # B positions at spawn, A points after
        b_r = struct.unpack_from(">ff", frames[2][1], 4)
        self.assertEqual((round(b_r[0], 3), round(b_r[1], 3)),
                         (round(roster.LANE_SPAWN_RIGHT[0], 3),
                          round(roster.LANE_SPAWN_RIGHT[1], 3)))
        a_l = struct.unpack_from(">ff", frames[6][1], 4)
        self.assertLess(a_l[0], -70.0)                       # mirrored A
        # 1067 states: left (01) before right (02), spawn state 00
        self.assertEqual(frames[8][1][4:7], b"\x01\x01\x00")
        self.assertEqual(frames[9][1][4:7], b"\x02\x01\x00")
        # seq: shared counter, +1 per 1010 (corpus 33/34)
        self.assertEqual(frames[0][1][116], 0x21)
        self.assertEqual(frames[3][1][116], 0x22)
        self.assertEqual(d.seq_1010[0], 0x22)
        # 1016 carries the same seq byte as the minion's 1010
        self.assertEqual(frames[1][1][0], 0x21)
        self.assertEqual(frames[4][1][0], 0x22)

    def test_full_wave_has_10_minions_on_measured_grid(self):
        d = self._director()
        frames = self._pump_until(
            d, roster.WAVE_FIRST_SPAWN_AT + max(roster.WAVE_PAIR_OFFSETS)
            + roster.WAVE_STATE_DELAY + 0.05, step=0.01)
        spawns = [p for op, p in frames if op == 1010]
        self.assertEqual(len(spawns), 10)
        eids = [struct.unpack_from(">I", p, 8)[0] for p in spawns]
        self.assertEqual(eids, list(range(4610, 4620)))
        states = [p for op, p in frames if op == 1067]
        self.assertEqual(len(states), 20)                    # 10 × (00 + 0f)
        spawners = [struct.unpack_from(">I", p, 0)[0] for p in spawns]
        self.assertEqual(spawners[::2],
                         [366, 366, 366, 365, 365])          # requested three melee + two ranged
        for pair in range(5):
            right_i, left_i = 2 * pair, 2 * pair + 1
            xr = struct.unpack_from(">f", spawns[right_i], 12)[0]
            xl = struct.unpack_from(">f", spawns[left_i], 12)[0]
            self.assertGreater(xr, 0)
            self.assertLess(xl, 0)
            self.assertAlmostEqual(abs(xr), abs(xl), places=4)

    def test_second_wave_on_25s_grid(self):
        d = self._director()
        duration = (roster.WAVE_FIRST_SPAWN_AT + roster.WAVE_INTERVAL
                    + max(roster.WAVE_PAIR_OFFSETS) + roster.WAVE_STATE_DELAY
                    + 0.05)
        frames = self._pump_until(d, duration, step=0.25)
        spawns = [struct.unpack_from(">I", p, 8)[0]
                  for op, p in frames if op == 1010]
        self.assertEqual(len(spawns), 20)                    # waves 1 + 2
        self.assertEqual(spawns[10:], list(range(4620, 4630)))
        # wave 1 continues at the same eids, no re-use
        self.assertEqual(len(set(spawns)), 20)

    def test_minions_walk_and_stop_at_lane_end(self):
        d = self._director(combat=False)   # walk/heartbeat layer in isolation
        end = roster.WAVE_FIRST_SPAWN_AT + 30.0
        frames = self._pump_until(d, end, step=0.05)
        tail = [p for op, p in frames if op == 1070
                and struct.unpack_from(">I", p, 0)[0] == 4610]
        self.assertTrue(tail)
        x, y = struct.unpack_from(">ff", tail[-1], 4)
        goal = roster.LANE_PATH_RIGHT[-1]
        self.assertEqual((round(x, 3), round(y, 3)),
                         (round(goal[0], 3), round(goal[1], 3)))
        # monotone approach along x for the right-side walker
        xs = [struct.unpack_from(">ff", p, 4)[0] for p in tail]
        self.assertLessEqual(xs[-1], xs[0] + 1e-6)           # walks toward -x
        # after arrival: rest-position heartbeats continue at the same spot
        d.pump(d.t0 + end + roster.MINION_POSITION_PERIOD + 0.10)
        more = [p for op, p in d.pump(
                    d.t0 + end + 2 * roster.MINION_POSITION_PERIOD + 0.20)
                if op == 1070 and struct.unpack_from(">I", p, 0)[0] == 4610]
        self.assertTrue(more)
        hx, hy = struct.unpack_from(">ff", more[-1], 4)
        self.assertEqual((round(hx, 3), round(hy, 3)),
                         (round(goal[0], 3), round(goal[1], 3)))

    def test_determinism_same_schedule_same_frames(self):
        def run():
            d = self._director()
            return self._pump_until(d, roster.WAVE_FIRST_SPAWN_AT + 5.0,
                                    step=0.05)
        self.assertEqual(run(), run())

    def test_empty_before_first_wave(self):
        d = self._director()
        self.assertEqual(d.pump(d.t0 + roster.WAVE_FIRST_SPAWN_AT - 0.05), [])


class TestCombatBuilders(unittest.TestCase):
    """s2c 1054 / 1073 / 1035 — shapes pinned on the vg5 corpus
    (measure_combat*.py): tail 00050400… in 400/400 minion-target frames;
    corpse removal = destroy then despawn, tail 0000, same instant."""

    def test_combat_delta_1054(self):
        p = roster.build_combat_delta(4610, 4611, -19.4)
        self.assertEqual(len(p), roster.COMBAT_DELTA_PAYLOAD_SIZE)
        self.assertEqual(struct.unpack_from(">II", p, 0), (4611, 4610))
        self.assertAlmostEqual(struct.unpack_from(">f", p, 8)[0], -19.4,
                               places=2)   # f32 roundtrip
        self.assertEqual(p[12:], roster.COMBAT_DELTA_TAIL)

    def test_destroy_and_despawn_1073_1035(self):
        for build in (roster.build_destroy, roster.build_despawn):
            p = build(4614)
            self.assertEqual(len(p), roster.DESTROY_PAYLOAD_SIZE)
            self.assertEqual(struct.unpack_from(">IH", p, 0), (4614, 0))


class TestCombatDirector(unittest.TestCase):
    """The fight at the lane meeting point: first blood is 4610 -> 4611
    (corpus-measured pair) once both walkers hold their endpoints 2.0 apart;
    repeat hits every 0.6 s; death1072 stops heartbeats, followed by
    corpse removal1073/1035 after the measured retention period.
    The wave grid is shrunk (spawn at +0.5 s) — walk time to the meeting
    point stays real, so first blood lands ~16.5 s in."""

    @classmethod
    def setUpClass(cls):
        cls._old_spawn = roster.WAVE_FIRST_SPAWN_AT
        roster.WAVE_FIRST_SPAWN_AT = 0.5

    @classmethod
    def tearDownClass(cls):
        roster.WAVE_FIRST_SPAWN_AT = cls._old_spawn

    def _director(self, **kw):
        return wave.Director(100.0, seq_1010=kw.pop("seq", [0x20]), **kw)

    def _pump_until(self, d, duration, step=0.05):
        frames = []
        t = 0.0
        while t < duration:
            t += step
            frames += d.pump(d.t0 + t)
        return frames

    def _hits(self, frames, src=None, tgt=None):
        out = []
        for op, p in frames:
            if op != 1054:
                continue
            t, s = struct.unpack_from(">II", p, 0)
            if (src is None or s == src) and (tgt is None or t == tgt):
                out.append((s, t, struct.unpack_from(">f", p, 8)[0]))
        return out

    def test_first_blood_is_4610_to_4611_at_meeting_point(self):
        d = self._director()
        frames = self._pump_until(d, roster.WAVE_FIRST_SPAWN_AT + 16.5)
        hits = self._hits(frames)
        self.assertTrue(hits)
        self.assertEqual(hits[0][:2], (4610, 4611))
        self.assertAlmostEqual(hits[0][2], -roster.MINION_ATTACK_DAMAGE,
                               places=2)   # f32 roundtrip

    def test_repeat_hits_on_measured_cooldown(self):
        d = self._director()
        frames = self._pump_until(d, roster.WAVE_FIRST_SPAWN_AT + 20.0)
        seq4610 = [op for op, p in frames if op == 1054
                   and struct.unpack_from(">II", p, 0) == (4611, 4610)]
        self.assertGreaterEqual(len(seq4610), 2)
        # 0.6 s cadence over a ~4.5 s window: bounded burst, never a flood
        self.assertLessEqual(len(seq4610), 8)

    def test_death_is_destroy_then_despawn_and_stops_heartbeats(self):
        d = self._director()
        frames = self._pump_until(d, roster.WAVE_FIRST_SPAWN_AT + 60.0)
        ops = [op for op, _ in frames]
        self.assertIn(1073, ops)
        self.assertIn(1035, ops)
        for i, op in enumerate(ops):
            if op != 1073:
                continue
            eid = struct.unpack_from(">I", frames[i][1], 0)[0]
            self.assertEqual(ops[i + 1], 1035)
            self.assertEqual(
                struct.unpack_from(">I", frames[i + 1][1], 0)[0], eid)
        death_idx = {struct.unpack_from(">I", p, 0)[0]: i
                     for i, (op, p) in enumerate(frames) if op == 1073}
        for i, (op, p) in enumerate(frames):
            if op != 1070:
                continue
            eid = struct.unpack_from(">I", p, 0)[0]
            if eid in death_idx and i > death_idx[eid]:
                self.fail(f"dead eid {eid} published a later 1070")

    def test_hero_never_a_combat_target(self):
        d = self._director()
        frames = self._pump_until(d, roster.WAVE_FIRST_SPAWN_AT + 60.0)
        for op, p in frames:
            if op == 1054:
                src, tgt = struct.unpack_from(">II", p, 0)
                for eid in (src, tgt):
                    self.assertNotIn(eid, (1500, 1515, 1516, 1517, 1518, 1519))

    def test_combat_determinism(self):
        def run():
            d = self._director()
            return self._pump_until(d, roster.WAVE_FIRST_SPAWN_AT + 40.0,
                                    step=0.05)
        self.assertEqual(run(), run())


class TestMinionClassesAndRanged(unittest.TestCase):
    """Corpus-measured minion classes: melee vs ranged, per-class damage
    (-19.4, -27.8, -38.8, -50.0), engagement range (p90 6.08 / max 7.28 for ranged),
    and per-pair stop offsets."""

    def test_minion_class_stats_and_spawners(self):
        d = wave.Director(100.0)
        # Spawn wave 1 (5 pairs = 10 minions)
        frames = []
        for pair in range(5):
            d._spawn_pair(100.0, pair)

        self.assertEqual(len(d.minions), 10)
        # Accepted sandbox composition supersedes the old inferred captain
        # range, while roster.MINION_PAIR_CLASSES retains that corpus profile.
        expected_classes = ["lead_melee", "melee", "melee", "ranged", "ranged"]
        expected_damages = [19.4, 27.8, 27.8, 50.0, 50.0]
        expected_ranges = [2.0, 2.0, 2.0, 6.5, 6.5]

        for pair in range(5):
            m_r = d.minions[2 * pair]
            m_l = d.minions[2 * pair + 1]
            self.assertEqual(m_r.minion_class, expected_classes[pair])
            self.assertEqual(m_l.minion_class, expected_classes[pair])
            self.assertAlmostEqual(m_r.attack_damage, expected_damages[pair], places=1)
            self.assertAlmostEqual(m_r.attack_range, expected_ranges[pair], places=1)
            self.assertAlmostEqual(m_l.attack_damage, expected_damages[pair], places=1)
            self.assertAlmostEqual(m_l.attack_range, expected_ranges[pair], places=1)

    def test_ranged_minion_engagement_distance(self):
        """Ranged minions (pair 3 & 4) acquire and attack at 5.5u (> melee 2.0u)."""
        d = wave.Director(100.0, combat=True)
        # Pair 3 is ranged (range 6.0u, damage 50.0)
        d._spawn_pair(100.0, 3)
        m_r = d.minions[0]  # Right side (Red)
        m_l = d.minions[1]  # Left side (Blue)

        # Place them 5.5 units apart
        m_r.x, m_r.y = 5.5, 0.0
        m_l.x, m_l.y = 0.0, 0.0
        self.assertAlmostEqual(d._dist(m_r, m_l), 5.5)

        # Pump combat at now=100.0
        frames = d.pump(100.0)
        self.assertFalse(any(op == wave.OP_COMBAT_1054 for op, _ in frames))
        frames = d.pump(101.35)
        hits = [f for f in frames if f[0] == wave.OP_COMBAT_1054]
        self.assertTrue(hits)
        tgt, src, delta = struct.unpack_from(">IIf", hits[0][1], 0)
        self.assertEqual(src, m_r.eid)
        self.assertEqual(tgt, m_l.eid)
        self.assertAlmostEqual(delta, -50.0, places=1)

    def test_melee_minion_cannot_attack_at_range(self):
        """Melee minions (pair 0/1, range 2.0u) cannot attack at 3.5u."""
        d = wave.Director(100.0, combat=True)
        d._spawn_pair(100.0, 0)
        m_r = d.minions[0]
        m_l = d.minions[1]

        # Place them 3.5 units apart (outside melee 2.0u range)
        m_r.x, m_r.y = 3.5, 0.0
        m_l.x, m_l.y = 0.0, 0.0

        frames = d.pump(100.0)
        hits = [f for f in frames if f[0] == wave.OP_COMBAT_1054]
        self.assertEqual(len(hits), 0)

    def test_minion_stop_offset_trimming(self):
        """Verify polyline trimming produces staggered stop coordinates."""
        raw_path = roster.LANE_PATH_RIGHT
        end_p0 = roster.trim_polyline(raw_path, 0.0)[-1]
        end_p1 = roster.trim_polyline(raw_path, 1.0)[-1]
        end_p2 = roster.trim_polyline(raw_path, 4.0)[-1]
        end_p3 = roster.trim_polyline(raw_path, 5.0)[-1]
        end_p4 = roster.trim_polyline(raw_path, 8.0)[-1]

        self.assertEqual((round(end_p0[0], 3), round(end_p0[1], 3)), (1.500, 5.500))
        # Each subsequent pair stops earlier along x (larger positive x for right side)
        self.assertGreater(end_p1[0], end_p0[0])
        self.assertGreater(end_p2[0], end_p1[0])
        self.assertGreater(end_p3[0], end_p2[0])
        self.assertGreater(end_p4[0], end_p3[0])


if __name__ == "__main__":
    unittest.main()

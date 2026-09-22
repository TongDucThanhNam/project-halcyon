"""Skye A/B wire presentation against the native contract recovered from
owned replay captures (match ea4c7fda...-a683aa80, chunks 32 and 36).

Native facts encoded here (arrival-clock jitter prevents sub-second phase
assertions; frame order and payload shapes are exact):
- A cast publishes 1086 cast-state 61, then 1087 Barrage 607 (count 1,
  word0 = f32 aim angle), and one 1039 projectile per 0.3 s pulse window
  (eleven captured per 3 s cast) with 1086 BarrageSlow 608 on victims.
- B cast publishes 1086 61, 1087 Firing B Missiles 610 (word0 = f32 dash
  angle, word1 = f32 dash distance), the first 1038 missile, 1087 Executing
  B Dash 609 (word2 = missiles still to fire), then the 1027 dash; the
  remaining missiles fire along the dash path.
- The pre-fix implementation emitted plain 1086 kinds 607/609/610 and all
  four missiles at once; those frames never rendered in the client.
"""
from __future__ import annotations

import math
import os
import struct
import unittest

from server import abilities, buff_wire, decode, hero_balance, projectile_wire, roster, skye_wire, status_effects, wire
from server.abilities import AbilitySlot, SkyeKit
from server.hero_movement import HeroMovement
from server.paths import runtime_corpus_dir


CORPUS_MATCH = ('ea4c7fda-4b61-481d-abb7-1c757d24ae58'
                '-a683aa80-9811-47c3-bb64-0731a802e889')


def _corpus_chunk(chunk: int):
    base = os.environ.get('HALCYON_SKYE_VOLLEY_CORPUS', str(runtime_corpus_dir()))
    path = os.path.join(base, f'{CORPUS_MATCH}.{chunk}.vgr')
    if not os.path.isfile(path):
        return None
    frames, stats = decode.walk_vgr(path)
    if stats.get('failures'):
        raise ValueError('native Skye corpus has decode failures')
    return frames


class TestProjectileWireEncoders(unittest.TestCase):
    def test_dash_translation_encode_decode(self):
        eid = 1515
        speed = 18.0
        dest = (20.5, 5.5)
        payload = projectile_wire.build_dash_translation(eid, speed, dest)
        self.assertEqual(len(payload), 22)
        p_eid, p_spd, dx, dz, dy = projectile_wire.parse_dash_translation(payload)
        self.assertEqual(p_eid, eid)
        self.assertAlmostEqual(p_spd, speed, places=4)
        self.assertAlmostEqual(dx, 20.5, places=4)
        self.assertAlmostEqual(dy, 5.5, places=4)
        self.assertEqual(struct.pack('>f', dz), struct.pack('>I', skye_wire.GROUND_ELEVATION_BITS))

        payload3d = projectile_wire.build_dash_translation(eid, speed, (20.5, 1.2, 5.5))
        _, _, dx, dz, dy = projectile_wire.parse_dash_translation(payload3d)
        self.assertAlmostEqual(dz, 1.2, places=4)

        with self.assertRaises(ValueError):
            projectile_wire.build_dash_translation(0, speed, dest)
        with self.assertRaises(ValueError):
            projectile_wire.build_dash_translation(eid, -5.0, dest)

    def test_curved_projectile_encode_decode(self):
        inst = 0x43CB
        sock = skye_wire.SOCKET_ROCKET_POD_L
        pos = (23.74, 5.65)
        curve = 1.0
        slot = 3
        payload = projectile_wire.build_curved_projectile(inst, sock, pos, curve, slot)
        self.assertEqual(len(payload), 30)
        p_inst, p_sock, px, pz, py, p_curve, kind, src, own = projectile_wire.parse_curved_projectile(payload)
        self.assertEqual(p_inst, inst)
        self.assertEqual(p_sock, sock)
        self.assertAlmostEqual(px, 23.74, places=2)
        self.assertAlmostEqual(py, 5.65, places=2)
        self.assertAlmostEqual(p_curve, 1.0, places=4)
        self.assertEqual(kind, 111)
        self.assertEqual(src, slot)
        self.assertEqual(own, slot)

    def test_barrage_projectile_encode_decode(self):
        inst = 0x3CEA
        sock = skye_wire.SOCKET_BARRAGE
        origin = (6.5, 3.5)
        direction = (-0.999477, 0.032325)
        slot = 3
        payload = projectile_wire.build_barrage_projectile(inst, origin, direction, slot)
        self.assertEqual(len(payload), 46)
        p_inst, p_sock, px, pz, py, d1, d2, kind, src, own = projectile_wire.parse_barrage_projectile(payload)
        self.assertEqual(p_inst, inst)
        self.assertEqual(p_sock, sock)
        self.assertAlmostEqual(px, 6.5, places=2)
        self.assertAlmostEqual(py, 3.5, places=2)
        self.assertAlmostEqual(d1, direction[0], places=4)
        self.assertAlmostEqual(d2, direction[1], places=4)
        self.assertEqual(kind, 110)
        self.assertEqual(src, slot)
        self.assertEqual(own, slot)


class TestNativeCaptureCalibration(unittest.TestCase):
    """Rebuild captured native frames through our builders; bytes must match."""

    def test_barrage_projectile_rebuilds_native_bytes(self):
        frames = _corpus_chunk(36)
        if frames is None:
            self.skipTest('native Skye replay corpus not available')
        native = frames[1348][2]
        self.assertEqual(frames[1348][1], 1039)
        inst, sock, px, pz, py, d1, d2, kind, src, own = projectile_wire.parse_barrage_projectile(native)
        built = projectile_wire.build_barrage_projectile(
            inst, (px, py), (d1, d2), src, owner_slot=own, socket_hash=sock, kind=kind)
        self.assertEqual(built, native)

    def test_missile_rebuilds_native_bytes(self):
        frames = _corpus_chunk(36)
        if frames is None:
            self.skipTest('native Skye replay corpus not available')
        for row, expected_curve in ((2119, 1.0), (2143, -1.0)):
            native = frames[row][2]
            self.assertEqual(frames[row][1], 1038)
            inst, sock, px, pz, py, curve, kind, src, own = projectile_wire.parse_curved_projectile(native)
            self.assertEqual(curve, expected_curve)
            self.assertEqual(kind, 111)
            built = projectile_wire.build_curved_projectile(
                inst, sock, (px, py), curve, src, owner_slot=own, kind=kind, elevation=pz)
            self.assertEqual(built, native)

    def test_dash_rebuilds_native_bytes(self):
        frames = _corpus_chunk(36)
        if frames is None:
            self.skipTest('native Skye replay corpus not available')
        native = frames[2121][2]
        self.assertEqual(frames[2121][1], 1027)
        eid, spd, dx, dz, dy = projectile_wire.parse_dash_translation(native)
        self.assertEqual(eid, 1517)
        built = projectile_wire.build_dash_translation(eid, spd, (dx, dy))
        self.assertEqual(built, native)

    def test_barrage_state_words_match_native(self):
        frames = _corpus_chunk(36)
        if frames is None:
            self.skipTest('native Skye replay corpus not available')
        native = frames[1341][2]
        self.assertEqual(frames[1341][1], 1087)
        tgt, src = struct.unpack_from('>II', native, 0)
        dur = struct.unpack_from('>e', native, 8)[0]
        inst = struct.unpack_from('>I', native, 10)[0]
        kind = struct.unpack_from('>H', native, 14)[0]
        cnt = struct.unpack_from('>H', native, 16)[0]
        words = struct.unpack_from('>4I', native, 18)
        self.assertEqual(kind, skye_wire.BUFF_SKYE_BARRAGE)
        self.assertEqual(cnt, 1)
        self.assertAlmostEqual(dur, 3.0, places=3)
        built = buff_wire.build_buff_state(tgt, src, dur, inst, kind, cnt, words)
        self.assertEqual(built, native)
        # word0 is the aim angle: within ~2e-3 rad of atan2 over the rounded
        # 1039 direction components of the same cast.
        angle = struct.unpack('>f', struct.pack('>I', words[0]))[0]
        _, _, _, _, _, d1, d2, _, _, _ = projectile_wire.parse_barrage_projectile(frames[1348][2])
        self.assertLess(abs(angle - math.atan2(d2, d1)), 2e-3)

    def test_dash_state_words_match_native(self):
        frames = _corpus_chunk(36)
        if frames is None:
            self.skipTest('native Skye replay corpus not available')
        for row, kind, expect_words in ((2118, 610, None), (2120, 609, None)):
            native = frames[row][2]
            self.assertEqual(frames[row][1], 1087)
            tgt, src = struct.unpack_from('>II', native, 0)
            dur = struct.unpack_from('>e', native, 8)[0]
            inst = struct.unpack_from('>I', native, 10)[0]
            got_kind = struct.unpack_from('>H', native, 14)[0]
            cnt = struct.unpack_from('>H', native, 16)[0]
            words = struct.unpack_from('>4I', native, 18)
            self.assertEqual(got_kind, kind)
            self.assertEqual(cnt, 1)
            self.assertEqual(tgt, 1517)
            built = buff_wire.build_buff_state(tgt, src, dur, inst, got_kind, cnt, words)
            self.assertEqual(built, native)
        # 610 words: f32 dash angle, f32 dash distance; 609 word2: missiles left.
        w610 = struct.unpack_from('>4I', frames[2118][2], 18)
        angle = struct.unpack('>f', struct.pack('>I', w610[0]))[0]
        distance = struct.unpack('>f', struct.pack('>I', w610[1]))[0]
        self.assertLess(abs(angle - math.atan2(-0.113, -3.219)), 2e-3)
        self.assertLess(abs(distance - 3.219), 5e-3)
        w609 = struct.unpack_from('>4I', frames[2120][2], 18)
        self.assertEqual(w609[2], 3)


class TestSkyeWirePresentationConstants(unittest.TestCase):
    def test_constants_match_registry_and_captures(self):
        # Buff kinds resolved from the KindredBuffs store registry (2026-09-20):
        # Barrage 607, BarrageSlow 608, Executing B Dash 609, Firing B Missiles
        # 610, HitBy B Missiles 611; the proven C anchors 612-618 are unchanged.
        self.assertEqual(skye_wire.BUFF_SKYE_BARRAGE, 607)
        self.assertEqual(skye_wire.BUFF_SKYE_BARRAGE_SLOW, 608)
        self.assertEqual(skye_wire.BUFF_SKYE_EXECUTING_B_DASH, 609)
        self.assertEqual(skye_wire.BUFF_SKYE_FIRING_B_MISSILES, 610)
        self.assertEqual(skye_wire.BUFF_SKYE_HIT_BY_B_MISSILES, 611)
        # Sockets and kinds are captured 1038/1039 payload values.
        self.assertEqual(skye_wire.SOCKET_BARRAGE, 0x259FD523)
        self.assertEqual(skye_wire.SOCKET_ROCKET_POD_L, 0x4578DE4F)
        self.assertEqual(skye_wire.SOCKET_ROCKET_POD_R, 0x3B78CE91)
        self.assertEqual(skye_wire.KIND_SKYE_BARRAGE, 110)
        self.assertEqual(skye_wire.KIND_SKYE_MISSILE, 111)

    def test_registry_resolves_skye_state_kinds(self):
        """The buff kind numbering comes from the KindredBuffs registry."""
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                'ikr', os.path.join('Tools', 'Teardown', 'inspect_kindred_registry.py'))
            if spec is None or spec.loader is None:
                self.skipTest('registry inspector not importable')
            ikr = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ikr)
            from server.paths import local_root
            manifest = (local_root() / 'vainglory/pc/Vainglory 4.13/Vainglory/Data'
                        / '55/551BCB541D80053BACD0A897B7993A77')
            inst = None
            for candidate in (local_root() / 'research/vg_max/inst_dump/KindredBuffs.last.inst.bin',):
                if candidate.is_file():
                    inst = candidate
            if not manifest.is_file() or inst is None:
                self.skipTest('KindredBuffs store inputs not available')
            import struct as _struct
            raw = manifest.read_bytes()
            if raw[:4] == b'RSC0':
                raw = raw[32:]
            if raw[:4] != b'CFF0':
                self.skipTest('unexpected manifest container')
            offset = _struct.unpack_from('<I', raw, 20)[0]
            body = None
            while offset + 8 <= len(raw):
                tag = raw[offset:offset + 4]
                size = _struct.unpack_from('<I', raw, offset + 4)[0]
                if tag == b'INST':
                    body = raw[offset + 8:offset + size]
                    break
                offset += size
            if body is None:
                self.skipTest('manifest has no INST chunk')
            M = 0xffffffff

            def u(x):
                return x & M

            def mix(a, b, c):
                a = u((a - b - c) ^ (c >> 13)); b = u((b - c - a) ^ (a << 8)); c = u((c - a - b) ^ (b >> 13))
                a = u((a - b - c) ^ (c >> 12)); b = u((b - c - a) ^ (a << 16)); c = u((c - a - b) ^ (b >> 5))
                a = u((a - b - c) ^ (c >> 3)); b = u((b - c - a) ^ (a << 10)); c = u((c - a - b) ^ (b >> 15))
                return u(c)

            def rol(x, n):
                return ((x << n) | (x >> (32 - n))) & M

            def decrypt(c, k):
                out = bytearray(c)
                st = len(c)
                for i in range(0, len(c) & ~3, 4):
                    cw = _struct.unpack_from('<I', c, i)[0]
                    _struct.pack_into('<I', out, i, (k ^ rol(st, 1) ^ cw) & M)
                    st = cw
                return bytes(out)

            # This is the revision-0 key table entry used by extract_final.py.
            key = mix((0x9e3779b9 + 0x9dea872e) & M, 0x9e3779b9, (len(body) + 4) & M)
            plain = decrypt(body, key)
            entries = ikr.registry_entries(raw, plain)
        except Exception as exc:  # pragma: no cover - environment boundary
            self.skipTest(f'registry resolution unavailable: {exc}')
        self.assertEqual(entries.get('Buff_Skye_Barrage'), 607)
        self.assertEqual(entries.get('Buff_Skye_Executing_B_Dash'), 609)
        self.assertEqual(entries.get('Buff_Skye_Firing_B_Missiles'), 610)
        self.assertEqual(entries.get('Buff_Skye_HitByMissileVolley'), 618)


class TestSkyeABPresentation(unittest.TestCase):
    def setUp(self):
        self.hero = HeroMovement(1500, 1)
        self.hero.x, self.hero.y = 0.0, 0.0
        self.hero.slot = 1
        hero_balance.configure_hero(self.hero, 265)

        self.enemy = HeroMovement(1517, 2)
        self.enemy.x, self.enemy.y = 4.0, 0.0
        self.enemy.slot = 4
        hero_balance.configure_hero(self.enemy, 243)

        self.manager = status_effects.StatusManager()
        self.kit = abilities.create_skye_kit(self.hero)
        self.heroes = {1500: self.hero, 1517: self.enemy}

    def _buff_kinds(self, frames, opcode=None):
        kinds = []
        for op, payload in frames:
            if opcode is not None and op != opcode:
                continue
            if op in (buff_wire.BUFF_ADD, buff_wire.BUFF_STATE) and len(payload) >= 16:
                kinds.append((op, struct.unpack_from('>H', payload, 14)[0]))
        return kinds

    def test_skye_a_presentation_lifecycle(self):
        self.kit.upgrade_ability(AbilitySlot.A, 1)
        now = 1.0

        cast_ability_frames = self.kit.cast_ability(
            AbilitySlot.A, now, target_pos=(4.0, 0.0),
            status_manager=self.manager, all_heroes=self.heroes, all_minions=[])
        now += self.kit.abilities[AbilitySlot.A].delay
        step_frames = self.kit.step(now, status_manager=self.manager,
                                    all_heroes=self.heroes, all_minions=[])
        exec_buffs = self.manager.drain_frames()
        # The A delay is zero: the pending executes inside cast_ability.
        buffs = (self._buff_kinds(exec_buffs) + self._buff_kinds(cast_ability_frames)
                 + self._buff_kinds(step_frames))
        self.assertIn((buff_wire.BUFF_ADD, 61), buffs,
                      'native cast-state 61 must precede the barrage state')
        self.assertIn((buff_wire.BUFF_STATE, 607), buffs,
                      'Barrage 607 must be published as 1087 with state words')
        self.assertNotIn((buff_wire.BUFF_ADD, 607), buffs,
                         'pre-fix regression: 607 must not be a plain 1086 add')

        # 1039 appears on every third 0.1 s pulse (native 0.3 s projectile
        # cadence; eleven captured per 3 s cast).
        projectiles = [p for op, p in cast_ability_frames + step_frames
                       if op == projectile_wire.OP_BARRAGE_PROJECTILE]
        for step_index in range(1, 11):
            now += self.kit.BARRAGE_INTERVAL
            frames = self.kit.step(now, status_manager=self.manager,
                                   all_heroes=self.heroes, all_minions=[])
            projectiles.extend(p for op, p in frames if op == projectile_wire.OP_BARRAGE_PROJECTILE)
        self.assertEqual(len(projectiles), 4,
                         'pulses 0..9 carry projectiles on pulses 0,3,6,9')
        inst, sock, px, pz, py, d1, d2, kind, src, own = projectile_wire.parse_barrage_projectile(projectiles[0])
        self.assertEqual(sock, skye_wire.SOCKET_BARRAGE)
        self.assertEqual(kind, skye_wire.KIND_SKYE_BARRAGE)
        self.assertEqual(src, own)
        self.assertEqual(struct.pack('>f', pz), struct.pack('>I', skye_wire.GROUND_ELEVATION_BITS))

        # Cancel A: the 607 instance must be addressed by 1093.
        cancel_frames = self.kit.cancel_native_action(1, now, status_manager=self.manager)
        cancel_buffs = self.manager.drain_frames()
        self.assertTrue(any(op == buff_wire.BUFF_CANCEL for op, _ in cancel_buffs),
                        'Barrage 607 must be cancelled through 1093')

    def test_skye_a_state_word_is_aim_angle(self):
        self.kit.upgrade_ability(AbilitySlot.A, 1)
        cast_frames = self.kit.cast_ability(AbilitySlot.A, 1.0, target_pos=(4.0, 0.0),
                                            status_manager=self.manager,
                                            all_heroes=self.heroes, all_minions=[])
        step_frames = self.kit.step(1.0 + self.kit.abilities[AbilitySlot.A].delay,
                                    status_manager=self.manager, all_heroes=self.heroes, all_minions=[])
        frames = self.manager.drain_frames() + cast_frames + step_frames
        state = [p for op, p in frames
                 if op == buff_wire.BUFF_STATE
                 and struct.unpack_from('>H', p, 14)[0] == skye_wire.BUFF_SKYE_BARRAGE]
        self.assertEqual(len(state), 1)
        word0 = struct.unpack_from('>I', state[0], 18)[0]
        angle = struct.unpack('>f', struct.pack('>I', word0))[0]
        # Cast aims +x; captured 1087 words decode as atan2(dir_y, dir_x).
        self.assertLess(abs(angle - 0.0), 1e-4)

    def test_skye_b_presentation_lifecycle(self):
        self.kit.upgrade_ability(AbilitySlot.B, 1)
        now = 1.0

        self.kit.on_basic_attack(self.enemy, now, status_manager=self.manager)
        self.manager.drain_frames()

        dest = (6.0, 0.0)
        cast_frames = self.kit.cast_ability(AbilitySlot.B, now, target_pos=dest,
                                            status_manager=self.manager,
                                            all_heroes=self.heroes, all_minions=[])
        drained = self.manager.drain_frames()

        # Native order: 61, 1087-610, first 1038, 1087-609, 1027.
        ordered = list(drained) + list(cast_frames)
        ops_only = [op for op, _ in ordered]
        kinds = self._buff_kinds(ordered)
        self.assertIn((buff_wire.BUFF_ADD, 61), kinds)
        self.assertIn((buff_wire.BUFF_STATE, 610), kinds)
        self.assertIn((buff_wire.BUFF_STATE, 609), kinds)
        self.assertNotIn((buff_wire.BUFF_ADD, 609), kinds)
        self.assertNotIn((buff_wire.BUFF_ADD, 610), kinds)
        # Ordering: 61 and 610 precede the first missile; 609 precedes 1027.
        first_missile = ops_only.index(projectile_wire.OP_CURVED_PROJECTILE)
        dash = ops_only.index(projectile_wire.OP_DASH_TRANSLATION)
        self.assertLess(ops_only.index(buff_wire.BUFF_STATE), first_missile)
        self.assertGreater(ops_only.index(projectile_wire.OP_DASH_TRANSLATION), 0)

        # The 610 state words carry the dash angle and distance.
        fire = [p for op, p in ordered if op == buff_wire.BUFF_STATE
                and struct.unpack_from('>H', p, 14)[0] == skye_wire.BUFF_SKYE_FIRING_B_MISSILES][0]
        w = struct.unpack_from('>4I', fire, 18)
        angle = struct.unpack('>f', struct.pack('>I', w[0]))[0]
        distance = struct.unpack('>f', struct.pack('>I', w[1]))[0]
        self.assertLess(abs(angle - 0.0), 1e-4)      # dash aims +x
        self.assertAlmostEqual(distance, 6.0, places=3)

        # 609 word2 counts the missiles still to fire (3 after the first).
        dash_state = [p for op, p in ordered if op == buff_wire.BUFF_STATE
                      and struct.unpack_from('>H', p, 14)[0] == skye_wire.BUFF_SKYE_EXECUTING_B_DASH][0]
        self.assertEqual(struct.unpack_from('>4I', dash_state, 18)[2], 3)

        # Dash frame: native layout (eid, speed, x, z, y, 0).
        dash_frames = [p for op, p in cast_frames if op == projectile_wire.OP_DASH_TRANSLATION]
        self.assertEqual(len(dash_frames), 1)
        eid, spd, dx, dz, dy = projectile_wire.parse_dash_translation(dash_frames[0])
        self.assertEqual(eid, self.hero.eid)
        self.assertAlmostEqual(spd, self.kit.DASH_SPEED, places=2)

        # Missiles 2-4 fire along the dash, alternating pods and curves.
        missile_frames = [p for op, p in cast_frames if op == projectile_wire.OP_CURVED_PROJECTILE]
        for _ in range(10):
            now += 0.1
            step_frames = self.kit.step(now, status_manager=self.manager,
                                        all_heroes=self.heroes, all_minions=[])
            missile_frames.extend(p for op, p in step_frames if op == projectile_wire.OP_CURVED_PROJECTILE)
        self.assertEqual(len(missile_frames), 4)
        pods = [projectile_wire.parse_curved_projectile(p)[1] for p in missile_frames]
        curves = [projectile_wire.parse_curved_projectile(p)[5] for p in missile_frames]
        self.assertEqual(pods, [skye_wire.SOCKET_ROCKET_POD_L, skye_wire.SOCKET_ROCKET_POD_R,
                                skye_wire.SOCKET_ROCKET_POD_L, skye_wire.SOCKET_ROCKET_POD_R])
        self.assertEqual(curves, [1.0, -1.0, 1.0, -1.0])

        # Missile impact still applies victim buff 611 (C-era behavior).
        now += self.kit.MISSILE_TRAVEL_SECONDS
        self.kit.step(now, status_manager=self.manager, all_heroes=self.heroes, all_minions=[])
        impact_buffs = self.manager.drain_frames()
        impact_kinds = self._buff_kinds(impact_buffs)
        self.assertIn((buff_wire.BUFF_ADD, 611), impact_kinds)

    def test_b_state_cancelled_on_interrupt(self):
        self.kit.upgrade_ability(AbilitySlot.B, 1)
        now = 1.0
        self.kit.on_basic_attack(self.enemy, now, status_manager=self.manager)
        self.manager.drain_frames()
        self.kit.cast_ability(AbilitySlot.B, now, target_pos=(6.0, 0.0),
                              status_manager=self.manager,
                              all_heroes=self.heroes, all_minions=[])
        self.manager.drain_frames()
        self.kit.interrupt_channel(now + 0.05)
        cancels = self.manager.drain_frames()
        cancelled = {struct.unpack_from('>I', p, 4)[0]
                     for op, p in cancels if op == buff_wire.BUFF_CANCEL}
        active = {value.instance_id for value in self.manager.presentation.active.values()
                  if value.target_eid == self.hero.eid
                  and value.kind in (skye_wire.BUFF_SKYE_EXECUTING_B_DASH,
                                     skye_wire.BUFF_SKYE_FIRING_B_MISSILES)}
        self.assertFalse(active & cancelled, 'cancel must address the live 609/610 instances')
        self.assertTrue(any(op == buff_wire.BUFF_CANCEL for op, _ in cancels))


class TestSkyeCPreservation(unittest.TestCase):
    def test_c_volley_wire_structures_preserved(self):
        self.assertEqual(skye_wire.VOLLEY_CLASS, 0xF59CDB08)
        self.assertEqual(skye_wire.CLUSTER_ARCHETYPE, 384)
        self.assertEqual(skye_wire.LINE_ARCHETYPE, 385)

        hero = HeroMovement(1500, 1)
        hero.slot = 1
        hero_balance.configure_hero(hero, 265)
        kit = abilities.create_skye_kit(hero)
        self.assertIsNotNone(kit.abilities.get(AbilitySlot.ULT))
        self.assertEqual(kit.C_CLUSTER_THRESHOLD, 2.0)

    def test_c_volley_buffs_remain_1086_adds(self):
        """Native volleys publish 612-618 as plain 1086 adds; unchanged."""
        frames = _corpus_chunk(36)
        if frames is None:
            self.skipTest('native Skye replay corpus not available')
        row = frames[328]
        self.assertEqual(row[1], 1086)
        self.assertEqual(struct.unpack_from('>H', row[2], 14)[0], 612)


class TestSkyeABCalibration(unittest.TestCase):
    """Pre-fix (no visible VFX) versus post-fix presentation emissions."""

    def test_prefix_vs_postfix_skye_a_vfx_emissions(self):
        # Pre-fix: A emitted damage and a plain 1086 kind 607 the client does
        # not render, with no 1087 state and no 1039 stream. Post-fix: the
        # captured 1087 state plus the 0.3 s 1039 projectile stream.
        hero = HeroMovement(1500, 1)
        hero.x, hero.y = 0.0, 0.0
        hero.slot = 1
        hero_balance.configure_hero(hero, 265)
        enemy = HeroMovement(1517, 2)
        enemy.x, enemy.y = 4.0, 0.0
        enemy.slot = 4
        hero_balance.configure_hero(enemy, 243)
        manager = status_effects.StatusManager()
        kit = abilities.create_skye_kit(hero)
        heroes = {1500: hero, 1517: enemy}

        kit.upgrade_ability(AbilitySlot.A, 1)
        cast_frames = kit.cast_ability(AbilitySlot.A, 1.0, target_pos=(4.0, 0.0),
                                       status_manager=manager, all_heroes=heroes, all_minions=[])
        now = 1.0 + kit.abilities[AbilitySlot.A].delay
        all_frames = list(cast_frames)
        for _ in range(12):
            now += kit.BARRAGE_INTERVAL
            all_frames.extend(kit.step(now, status_manager=manager,
                                       all_heroes=heroes, all_minions=[]))
        drained = manager.drain_frames()
        drained = list(cast_frames) + drained

        # Known-good: 1087-607 state and 1039 projectiles are present.
        state607 = [p for op, p in drained if op == buff_wire.BUFF_STATE
                    and struct.unpack_from('>H', p, 14)[0] == 607]
        self.assertGreater(len(state607), 0)
        projectiles = [p for op, p in all_frames if op == projectile_wire.OP_BARRAGE_PROJECTILE]
        self.assertGreater(len(projectiles), 0)
        # Known-bad (the pre-fix emission) must be gone.
        plain607 = [p for op, p in drained if op == buff_wire.BUFF_ADD
                    and struct.unpack_from('>H', p, 14)[0] == 607]
        self.assertEqual(len(plain607), 0)
        # Damage pulses still flow (gameplay unchanged).
        damage_frames = [p for op, p in all_frames if op == wire.OP.COMBAT_DELTA]
        self.assertGreater(len(damage_frames), 0)

    def test_prefix_vs_postfix_skye_b_vfx_emissions(self):
        # Pre-fix: B moved the hero and dealt damage with a plain 1086 609/610
        # and all four missiles at once. Post-fix: captured 1087 states with
        # angle/distance words, sequential missiles, 1027 dash frame.
        hero = HeroMovement(1500, 1)
        hero.x, hero.y = 0.0, 0.0
        hero.slot = 1
        hero_balance.configure_hero(hero, 265)
        enemy = HeroMovement(1517, 2)
        enemy.x, enemy.y = 4.0, 0.0
        enemy.slot = 4
        hero_balance.configure_hero(enemy, 243)
        manager = status_effects.StatusManager()
        kit = abilities.create_skye_kit(hero)
        heroes = {1500: hero, 1517: enemy}

        kit.upgrade_ability(AbilitySlot.B, 1)
        kit.on_basic_attack(enemy, 1.0, status_manager=manager)
        cast_frames = kit.cast_ability(AbilitySlot.B, 1.0, target_pos=(6.0, 0.0),
                                       status_manager=manager, all_heroes=heroes, all_minions=[])
        drained = manager.drain_frames()
        ordered = list(drained) + list(cast_frames)

        dash_frames = [p for op, p in cast_frames if op == projectile_wire.OP_DASH_TRANSLATION]
        self.assertEqual(len(dash_frames), 1)
        state610 = [p for op, p in ordered if op == buff_wire.BUFF_STATE
                    and struct.unpack_from('>H', p, 14)[0] == 610]
        state609 = [p for op, p in ordered if op == buff_wire.BUFF_STATE
                    and struct.unpack_from('>H', p, 14)[0] == 609]
        self.assertEqual(len(state610), 1)
        self.assertEqual(len(state609), 1)
        plain609 = [p for op, p in ordered if op == buff_wire.BUFF_ADD
                    and struct.unpack_from('>H', p, 14)[0] in (609, 610)]
        self.assertEqual(len(plain609), 0)
        missiles = [p for op, p in cast_frames if op == projectile_wire.OP_CURVED_PROJECTILE]
        self.assertEqual(len(missiles), 1, 'only the first missile fires at cast')


if __name__ == "__main__":
    unittest.main()

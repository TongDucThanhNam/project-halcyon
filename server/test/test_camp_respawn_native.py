"""Camp timers tied to complete native actor generations and exact timestamps."""
from functools import lru_cache
import os
from pathlib import Path
import struct
import unittest

from server import decode, jungle
from server.hero_movement import HeroMovement
from server.test.test_corpus import _cached_frames, VGFULL_PCAP
from Tools.Teardown.inspect_attack_sequence import pcap_frame_times
from Tools.Teardown.inspect_jungle_lifecycle import inspect_camp_respawns


MATCHES = {
    'b9f511e0-11cd-4cfa-ad62-dc8612b8d270': 'vgr/vgrtmp',
    '591146df-33f2-4f12-9a04-8d800d239821': 'vgr2',
}


@lru_cache(maxsize=2)
def native_match(match):
    root = Path(os.environ.get('TEMP', '')) / 'vg_max' / MATCHES[match]
    paths = sorted(root.glob(f'*-{match}.*.vgr'), key=lambda path: int(path.name.split('.')[-2]))
    if not paths:
        raise unittest.SkipTest(f'external VGR match unavailable: {root}')
    frames, times, origins = [], [], []
    for path in paths:
        rows, stats = decode.walk_vgr(str(path))
        if stats['failures'] or stats.get('trailing'):
            raise AssertionError(f'incomplete native chunk: {path.name}')
        chunk = int(path.name.split('.')[-2])
        frames.extend((op, payload) for _, op, payload in rows)
        times.extend(struct.unpack('>f', struct.pack('>I', token))[0] for token, _, _ in rows)
        origins.extend((chunk, row) for row in range(len(rows)))
    return frames, times, origins


class TestNativeCampRespawn(unittest.TestCase):
    def test_all_twenty_six_complete_camp_intervals_match_the_timer_by_type(self):
        manager = jungle.JungleManager()
        intervals = []
        for match in MATCHES:
            frames, times, origins = native_match(match)
            report = inspect_camp_respawns(frames, times, origins)
            self.assertEqual(report['incomplete_intervals'], [])
            self.assertEqual(report['unclassified_creations'], [])
            self.assertEqual(len(report['camp_intervals']), 13)
            self.assertEqual({row['camp'] for row in report['camp_intervals']}, set(jungle.CAMP_ANCHORS))
            lookup = dict(zip(origins, frames))
            for row in report['camp_intervals']:
                with self.subTest(match=match, camp=row['camp'], previous=row['previous_eids']):
                    expected_type = {'A': 357, 'B': 359, 'C': 357, 'D': 360}[row['camp'][-1]]
                    self.assertEqual(row['archetypes'], [expected_type] * (1 if expected_type == 357 else 2))
                    expected_seconds = 60 if expected_type == 357 else 50
                    self.assertAlmostEqual(row['clear_to_creation_seconds'], expected_seconds, delta=0.11)
                    self.assertEqual(manager._get_respawn_duration(row['camp']), expected_seconds)
                    for old_at, death_at, new_at, old_eid, new_eid in zip(
                            row['previous_creations'], row['deaths'], row['new_creations'],
                            row['previous_eids'], row['new_eids']):
                        old_op, old = lookup[old_at]
                        death_op, death = lookup[death_at]
                        new_op, new = lookup[new_at]
                        self.assertEqual((old_op, death_op, new_op), (1010, 1072, 1010))
                        self.assertEqual(struct.unpack_from('>II', old), (expected_type, 0x4DD5B7D0))
                        self.assertEqual(old[:8], new[:8])
                        self.assertEqual((old[12:16], old[20:24]), (new[12:16], new[20:24]))
                        self.assertEqual(int.from_bytes(old[8:12], 'big'), old_eid)
                        self.assertEqual(int.from_bytes(death[:4], 'big'), old_eid)
                        self.assertEqual(int.from_bytes(new[8:12], 'big'), new_eid)
                        self.assertNotEqual(old_eid, new_eid)
            intervals.extend(report['camp_intervals'])
        self.assertEqual(len(intervals), 26)

    def test_original_match_two_golden_locations_and_timestamps_replace_chunk_estimates(self):
        frames, times, origins = native_match('591146df-33f2-4f12-9a04-8d800d239821')
        report = inspect_camp_respawns(frames, times, origins)
        examples = {
            'LCampA': ((4, 792), (10, 748), 44.94699478149414, 105.01122283935547),
            'LCampB': ((5, 301), (10, 276), 50.632389068603516, 100.69361877441406),
            'LCampC': ((5, 1177), (11, 1335), 58.551326751708984, 118.63159942626953),
            'LCampD': ((7, 388), (12, 342), 70.91975402832031, 121.01486206054688),
        }
        for camp, expected in examples.items():
            row = next(row for row in report['camp_intervals'] if row['camp'] == camp)
            self.assertEqual((row['last_death'], row['first_creation'],
                              row['last_death_time'], row['first_creation_time']), expected)
        first_times = {chunk: times[index] for index, (chunk, row) in enumerate(origins) if row == 0}
        self.assertEqual(len(first_times), 21)
        for chunk, timestamp in first_times.items():
            self.assertAlmostEqual(timestamp, chunk * 10, delta=0.1)

    @unittest.skipUnless(Path(VGFULL_PCAP).is_file(), 'external vgfull capture unavailable')
    def test_same_native_event_bytes_agree_between_vgr_and_tcp_capture_clocks(self):
        frames, info = _cached_frames()
        self.assertEqual((info['nframes'], info['missed']), (32640, 0))
        times = pcap_frame_times(Path(VGFULL_PCAP), info['flow'], info['start'], len(frames))
        native_frames, native_times, origins = native_match('b9f511e0-11cd-4cfa-ad62-dc8612b8d270')
        lookup = dict(zip(origins, native_frames))
        wire_at = {(op, payload): index for index, (op, payload) in enumerate(frames)
                   if op == 1072 or op == 1010 and len(payload) == 126}
        report = inspect_camp_respawns(native_frames, native_times, origins)
        for row in report['camp_intervals']:
            # These are full byte-equal native actions from two recording
            # routes of the same match, not a match by an assumed global EID.
            death = wire_at[lookup[row['last_death']]]
            spawn = wire_at[lookup[row['first_creation']]]
            observed = times[spawn] - times[death]
            self.assertAlmostEqual(observed, row['clear_to_creation_seconds'], delta=0.03)

    def test_partial_bear_generation_is_not_misreported_as_full_clear(self):
        frames, times, origins = native_match('591146df-33f2-4f12-9a04-8d800d239821')
        # Remove the last-dead sibling's death from the first right-D cycle.
        # Its partner's earlier death must not silently become the camp timer.
        missing = origins.index((4, 561))
        selected = [i for i in range(len(frames)) if i != missing]
        report = inspect_camp_respawns([frames[i] for i in selected], [times[i] for i in selected],
                                       [origins[i] for i in selected])
        self.assertEqual(len(report['camp_intervals']), 12)
        self.assertEqual(len(report['incomplete_intervals']), 1)
        self.assertEqual(report['incomplete_intervals'][0]['camp'], 'RCampD')
        self.assertEqual(report['incomplete_intervals'][0]['previous_eids'], [4674, 4675])


class TestCampRespawnDeadlines(unittest.TestCase):
    def test_each_camp_respawns_at_its_full_clear_deadline_with_fresh_actors(self):
        for camp in jungle.CAMP_ANCHORS:
            with self.subTest(camp=camp):
                manager, hero = jungle.JungleManager(), HeroMovement()
                members = [actor for actor in manager.monsters.values() if actor.camp_id == camp]
                previous = {actor.eid for actor in members}
                for index, actor in enumerate(members):
                    manager.apply_damage_to_monster(actor.eid, actor.hp, hero, 10 + index * 2)
                    if index + 1 < len(members):
                        self.assertNotIn(camp, manager.camp_respawns)
                clear = 10 + (len(members) - 1) * 2
                deadline = clear + (60 if camp.endswith(('CampA', 'CampC')) else 50)
                self.assertEqual(manager.camp_respawns[camp], deadline)
                self.assertEqual(manager.apply_damage_to_monster(members[-1].eid, 1000, hero, clear + .5), [])
                self.assertEqual(manager.camp_respawns[camp], deadline)
                manager.step(.05, deadline - .05, {})
                self.assertFalse(any(actor.is_alive for actor in manager.monsters.values() if actor.camp_id == camp))
                manager.step(.05, deadline, {})
                current = [actor for actor in manager.monsters.values() if actor.camp_id == camp and actor.is_alive]
                self.assertEqual(len(current), len(members))
                self.assertFalse(previous & {actor.eid for actor in current})
                self.assertNotIn(camp, manager.camp_respawns)
                self.assertTrue(all(actor.hp == actor.max_hp for actor in current))


if __name__ == '__main__':
    unittest.main()

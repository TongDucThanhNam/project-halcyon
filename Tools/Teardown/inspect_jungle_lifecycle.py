"""Read-only jungle lifecycle, faction-field and respawn census of our corpus.

Prints scalar evidence only. Capture files remain outside the repository.
Receive timestamps and VGR record timestamps are identified separately;
neither is silently treated as a native simulation tick.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server import decode
from Tools.Teardown.inspect_attack_sequence import pcap_frame_times


# Measured map-placement identities, independent of any match's actor IDs.
# Both members of a bear camp lie within two units of its authored anchor.
NATIVE_CAMP_ANCHORS = {
    'LCampA': (-40.915, 20.251), 'LCampB': (-44.42, 31.91),
    'LCampC': (-21.95, 24.0), 'LCampD': (-13.47, 37.67),
    'RCampA': (40.59, 20.75), 'RCampB': (44.60, 31.60),
    'RCampC': (22.5, 23.5), 'RCampD': (13.635, 37.46),
}
NATIVE_CAMP_ARCHETYPES = {'A': 357, 'B': 359, 'C': 357, 'D': 360}


def inspect_camp_respawns(frames, times, origins=None):
    """Join complete generations by native class/archetype/creation position.

    The timer begins at the last member's death, not each member's death.
    A missing sibling, changed placement, or missing removal is reported
    instead of being silently treated as a complete camp respawn.
    """
    if len(frames) != len(times):
        raise ValueError('frame and timestamp counts differ')
    origin = lambda index: origins[index] if origins is not None else index
    generations = {camp: [] for camp in NATIVE_CAMP_ANCHORS}
    deaths, removals, unknown = {}, {}, []
    for index, (opcode, payload) in enumerate(frames):
        if opcode in (1072, 1035) and len(payload) >= 4:
            eid = struct.unpack_from('>I', payload)[0]
            (deaths if opcode == 1072 else removals)[eid] = index
        if opcode != 1010 or len(payload) != 126:
            continue
        archetype, actor_class, eid = struct.unpack_from('>III', payload)
        if archetype not in (357, 359, 360):
            continue
        if actor_class != 0x4DD5B7D0 or payload[121] != 0:
            unknown.append(dict(creation=origin(index), eid=eid, reason='unexpected class or faction'))
            continue
        position = struct.unpack_from('>f', payload, 12)[0], struct.unpack_from('>f', payload, 20)[0]
        matches = [camp for camp, anchor in NATIVE_CAMP_ANCHORS.items()
                   if NATIVE_CAMP_ARCHETYPES[camp[-1]] == archetype and math.dist(position, anchor) <= 2.0]
        if len(matches) != 1:
            unknown.append(dict(creation=origin(index), eid=eid, position=position, reason='ambiguous camp placement'))
            continue
        camp = matches[0]
        groups = generations[camp]
        actor = dict(eid=eid, archetype=archetype, position=position, index=index)
        if not groups or abs(times[index] - times[groups[-1][0]['index']]) > 0.1:
            groups.append([])
        groups[-1].append(actor)
    intervals, incomplete = [], []
    for camp, groups in generations.items():
        expected = 1 if camp[-1] in 'AC' else 2
        for old, new in zip(groups, groups[1:]):
            previous_eids = [actor['eid'] for actor in old]
            new_eids = [actor['eid'] for actor in new]
            reason = None
            signature = lambda group: sorted((actor['archetype'], actor['position']) for actor in group)
            if len(old) != expected or len(new) != expected:
                reason = 'incomplete camp generation'
            elif signature(old) != signature(new):
                reason = 'creation positions or types changed'
            elif set(previous_eids) & set(new_eids):
                reason = 'actor identity reused'
            else:
                first_spawn = new[0]['index']
                for actor in old:
                    eid = actor['eid']
                    if not actor['index'] < deaths.get(eid, -1) < removals.get(eid, -1) < first_spawn:
                        reason = 'missing ordered death/removal before new generation'
                        break
            if reason:
                incomplete.append(dict(camp=camp, previous_eids=previous_eids,
                                       new_eids=new_eids, reason=reason))
                continue
            death_index = max((deaths[eid] for eid in previous_eids), key=lambda index: (times[index], index))
            spawn_index = new[0]['index']
            intervals.append(dict(camp=camp, archetypes=[actor['archetype'] for actor in old],
                positions=[actor['position'] for actor in old], previous_eids=previous_eids, new_eids=new_eids,
                previous_creations=[origin(actor['index']) for actor in old],
                deaths=[origin(deaths[eid]) for eid in previous_eids],
                removals=[origin(removals[eid]) for eid in previous_eids],
                new_creations=[origin(actor['index']) for actor in new],
                last_death=origin(death_index), first_creation=origin(spawn_index),
                last_death_time=times[death_index], first_creation_time=times[spawn_index],
                clear_to_creation_seconds=times[spawn_index] - times[death_index]))
    periods = defaultdict(list)
    for row in intervals:
        periods[row['camp'][-1]].append(row['clear_to_creation_seconds'])
    return dict(camp_intervals=intervals, incomplete_intervals=incomplete, unclassified_creations=unknown,
                periods={kind: dict(count=len(values), minimum=min(values), maximum=max(values))
                         for kind, values in sorted(periods.items())})


def inspect(frames, times, origins=None, limit=8):
    actors, deaths, destroys, previous_at_anchor = {}, {}, {}, {}
    lifecycles, respawns, forms = [], [], {}
    creations, gaps = Counter(), defaultdict(list)
    integer = lambda body, offset=0: struct.unpack_from('>I', body, offset)[0]
    origin = lambda index: origins[index] if origins is not None else index
    for index, (opcode, payload) in enumerate(frames):
        if opcode == 1010 and len(payload) in (122, 126) and 357 <= integer(payload) <= 364:
            if integer(payload, 4) != 0x4DD5B7D0:
                raise ValueError('jungle archetype has an unexpected actor class')
            archetype, eid = integer(payload), integer(payload, 8)
            team, size = payload[121], len(payload)
            form = forms.setdefault((archetype, team, size), {'records': 0, 'actor_index': Counter(), 'maximum_hp': set()})
            form['records'] += 1
            form['actor_index'][payload[120]] += 1
            if size == 122:
                form['maximum_hp'].add(struct.unpack_from('>f', payload, 40)[0])
            actors[eid] = archetype, team
            if size == 126:
                creations[archetype] += 1
                anchor = (archetype, round(struct.unpack_from('>f', payload, 12)[0], 2),
                          round(struct.unpack_from('>f', payload, 20)[0], 2))
                previous = previous_at_anchor.get(anchor)
                if previous is not None and previous in deaths:
                    respawns.append(dict(archetype=archetype, previous_eid=previous, eid=eid,
                        death_to_new_creation_seconds=round(times[index] - times[deaths[previous]], 6),
                        death=origin(deaths[previous]), creation=origin(index)))
                previous_at_anchor[anchor] = eid
        elif opcode in (1072, 1073, 1035) and len(payload) >= 4 and integer(payload) in actors:
            eid = integer(payload)
            if opcode == 1072:
                deaths[eid] = index
            elif opcode == 1073:
                destroys[eid] = index
            else:
                death, destroy = deaths.get(eid), destroys.get(eid)
                archetype, team = actors[eid]
                row = dict(archetype=archetype, team=team, eid=eid, death=None if death is None else origin(death),
                           destroy=None if destroy is None else origin(destroy), removal=origin(index))
                if death is not None and destroy is not None:
                    period, removal_gap = times[destroy] - times[death], times[index] - times[destroy]
                    row.update(death_to_destroy_seconds=round(period, 6), destroy_to_removal_seconds=round(removal_gap, 6))
                    gaps[archetype].append((period, removal_gap))
                lifecycles.append(row)
    return dict(
        frame_count=len(frames),
        jungle_creation_counts=dict(sorted(creations.items())),
        faction_forms=[dict(archetype=key[0], team=key[1], payload_size=key[2], records=value['records'],
                            actor_index_counts=dict(sorted(value['actor_index'].items())),
                            maximum_hp=sorted(value['maximum_hp'])) for key, value in sorted(forms.items())],
        lifecycle_count=len(lifecycles),
        lifecycle_missing_death=sum(row['death'] is None for row in lifecycles),
        lifecycle_periods=[dict(archetype=archetype, count=len(values),
                               death_to_destroy_min=round(min(v[0] for v in values), 6),
                               death_to_destroy_median=round(statistics.median(v[0] for v in values), 6),
                               death_to_destroy_max=round(max(v[0] for v in values), 6),
                               destroy_to_removal_max=round(max(v[1] for v in values), 6))
                           for archetype, values in sorted(gaps.items())],
        lifecycle_samples=lifecycles[:limit],
        same_anchor_respawn_count=len(respawns),
        same_anchor_respawn_samples=respawns[:limit],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--pcap', type=Path)
    source.add_argument('--vgr', type=Path)
    parser.add_argument('--match', required=True)
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--camp-respawns', action='store_true', help='complete camp generations and clear-to-spawn times only')
    args = parser.parse_args()
    if args.pcap:
        frames, stats = decode.decode_pcap(str(args.pcap), args.match)
        if frames is None or stats['missed']:
            parser.error(f'capture did not decode completely: {stats}')
        times = pcap_frame_times(args.pcap, stats['flow'], stats['start'], len(frames))
        origins, clock_domain = None, 'TCP first-byte completion receive time'
    else:
        paths = [args.vgr] if args.vgr.is_file() else sorted(args.vgr.glob(f'*-{args.match}.*.vgr'),
                    key=lambda path: int(path.name.split('.')[-2]))
        if not paths:
            parser.error('no matching external VGR chunks')
        frames, times, origins = [], [], []
        for path in paths:
            chunk, stats = decode.walk_vgr(str(path))
            if stats['failures'] or stats.get('trailing'):
                parser.error(f'VGR did not decode completely: {path}')
            frames.extend((op, body) for _, op, body in chunk)
            times.extend(struct.unpack('>f', struct.pack('>I', token))[0] for token, _, _ in chunk)
            origins.extend(f'{path.name}:{index}' for index in range(len(chunk)))
        clock_domain = 'VGR record float timestamp'
    if args.camp_respawns:
        result = inspect_camp_respawns(frames, times, origins)
        result['camp_interval_count'] = len(result['camp_intervals'])
        result['camp_intervals'] = result['camp_intervals'][:args.limit]
    else:
        result = inspect(frames, times, origins, args.limit)
    result['clock_domain'] = clock_domain
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

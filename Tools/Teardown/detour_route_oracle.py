"""Compare retained native steering paths with a pinned public Detour build.

Offline, diagnostic only. Does not drive a client, send packets or replace
production navigation. A native128-point cap is reported, not hidden/extended.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from server.detour_query import DetourRouteQuery as DetourOracle, MESH_SHA256, point


def compare_path(native, oracle):
    if not native['observed']['navigation_flags'] & 1:
        # c60208 only advances the path with bit0 set. Stops/death can update
        # +7b0 while leaving the previous array intact; it is not a query pair.
        raise ValueError('inactive native path has no qualified current query destination')
    points = [point(p) for p in native['points']]
    if native['count'] != len(points) or not 1 <= len(points) <= 128:
        raise ValueError('unqualified native path count')
    result = oracle.query(points[0],point(native['destination']))
    actual = [point(p) for p in result['points']]
    lengths = lambda ps: sum(math.dist(a,b) for a,b in zip(ps,ps[1:]))
    return {'native_count':len(points),'oracle_count':len(actual),
            'exact_float32':points==actual,
            'max_aligned_point_error':max(map(math.dist,points,actual)) if len(points)==len(actual) else None,
            'endpoint_error':math.dist(points[-1],actual[-1]),
            'native_length_3d':lengths(points),'oracle_length_3d':lengths(actual),
            'native_destination':native['destination'],
            'native_endpoint':points[-1], 'oracle':result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--native-paths',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        parser.error('evidence output must stay outside the checkout')
    oracle = DetourOracle(args.library)
    results,seen,empty,inactive = [],set(),0,0
    try:
        for line in args.native_paths.read_text().splitlines():
            record = json.loads(line)
            native = record['native']
            if not native['observed']['navigation_flags'] & 1:
                inactive += 1
                continue
            if native['count'] == 0:
                empty += 1
                continue
            identity = json.dumps([native['points'],native['destination']],separators=(',',':'))
            if identity in seen:
                continue
            seen.add(identity)
            result = compare_path(native,oracle)
            results.append({'host_before':record['host_before'],**result})
        report = {'scope':'offline client-path reproduction; not server fidelity or movement smoothness',
                  'input':str(args.native_paths.resolve()),'library':oracle.library_path,
                  'library_sha256':oracle.manifest['library_sha256'],'mesh_sha256':MESH_SHA256,
                  'unique_paths':len(results),'empty_reads':empty,
                  'inactive_reads':inactive,
                  'exact_paths':sum(r['exact_float32'] for r in results),'results':results}
        with args.output.open('x',encoding='utf-8') as f:
            json.dump(report,f,indent=2)
        print(json.dumps({k:v for k,v in report.items() if k != 'results'}))
    finally:
        oracle.close()


if __name__ == '__main__':
    main()

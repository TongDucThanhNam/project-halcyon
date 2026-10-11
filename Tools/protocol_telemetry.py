"""Opt-in diagnostics observer. No measurement is passed to participant policy."""
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import threading
import time


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count':0}
    return {'count':len(values),'p50':values[len(values)//2],
            'p95':values[round((len(values)-1)*.95)],'max':values[-1]}


def population_time_fit(points):
    """OLS y = intercept + elapsed minutes + live population, no exclusions.

    Points are (minutes, population, measured work). Report rank failure rather
    than fabricate a zero time effect. Approximate 95% intervals use minute-
    clustered sandwich errors because adjacent fixed ticks are not independent.
    Descriptive diagnostic only: correlation is not a causal history test.
    """
    n = len(points)
    if n < 4:
        return {'count':n, 'identifiable':False, 'reason':'fewer than four observations'}
    mt, mp, my = (sum(row[i] for row in points)/n for i in range(3))
    centered = [(t-mt,p-mp,y-my) for t,p,y in points]
    tt = sum(t*t for t,p,y in centered)
    pp = sum(p*p for t,p,y in centered)
    tp = sum(t*p for t,p,y in centered)
    det = tt*pp-tp*tp
    if tt == 0 or pp == 0 or det <= 1e-12*tt*pp:
        return {'count':n, 'identifiable':False, 'reason':'constant or collinear time/population'}
    ty = sum(t*y for t,p,y in centered)
    py = sum(p*y for t,p,y in centered)
    bt, bp = (ty*pp-py*tp)/det, (py*tt-ty*tp)/det
    scores = defaultdict(lambda:[0.0,0.0])
    squared_error = 0.0
    for (minute,_,_), (t,p,y) in zip(points,centered):
        error = y-bt*t-bp*p
        squared_error += error*error
        scores[math.floor(minute)][0] += t*error
        scores[math.floor(minute)][1] += p*error
    g = len(scores)
    se = None
    if g > 1:
        variance = sum(((pp*t-tp*p)/det)**2 for t,p in scores.values())
        se = math.sqrt(max(0,variance*g/(g-1)*(n-1)/(n-3)))
    total = sum(y*y for t,p,y in centered)
    return {'count':n, 'identifiable':True, 'intercept':my-bt*mt-bp*mp,
            'elapsed_coefficient_per_minute':bt, 'population_coefficient':bp,
            'elapsed_cluster_se':se,
            'elapsed_approx_95pct_interval':[bt-1.96*se,bt+1.96*se] if se is not None else None,
            'minute_clusters':g, 'time_population_correlation':tp/math.sqrt(tt*pp),
            'r_squared':1-squared_error/total if total else None,
            'rmse':math.sqrt(squared_error/n),
            'minutes_range':[min(r[0] for r in points),max(r[0] for r in points)],
            'population_range':[min(r[1] for r in points),max(r[1] for r in points)]}


class Telemetry:
    def __init__(self, gateway, output, *, role='combined', filename='telemetry.jsonl'):
        import psutil
        self.process = psutil.Process()
        self.gateway, self.output = gateway, output
        self.role, self.filename = role, filename
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run,name='m3-telemetry',daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError('telemetry did not produce its first sample')
        if self.error:
            raise RuntimeError('telemetry startup: '+self.error)

    def run(self):
        try:
            with (self.output/self.filename).open('x',encoding='utf-8') as log:
                while not self.stop_event.is_set():
                    memory, cpu = self.process.memory_info(),self.process.cpu_times()
                    row = {'wall_time':time.time(),'cpu_s':cpu.user+cpu.system,
                           'pid':self.process.pid,'role':self.role,
                           'rss':memory.rss,'private_bytes':getattr(memory,'private',None),'matches':[]}
                    for match in list(self.gateway.matches) if self.gateway is not None else ():
                        world = match.session
                        if world is None:
                            continue
                        with world._state_lock:
                            wave = world.wave_director
                            row['matches'].append({'tick':world.sim_tick,'phase':world.phase,
                                'minions_total':len(wave.minions) if wave else 0,
                                'minions_live':sum(m.alive for m in wave.minions) if wave else 0,
                                'actor_slots':len(world.actor_slots.by_eid),
                                'input_queue':world.events.qsize(),'join_sequence':len(match.join_sequence),
                                'keepalive_ticks':len(match.keepalive_ticks),
                                'buff_allocations':len(world.status_manager.presentation._allocated),
                                'shop_allocations':len(world.shop_presentation._allocated),
                                'interrupt_serials':len(world.status_manager._interrupt_serial),
                                'attack_interrupt_serials':len(world.status_manager._attack_interrupt_serial),
                                'thread_alive':world.is_alive()})
                    log.write(json.dumps(row)+'\n')
                    log.flush()
                    self.ready.set()
                    self.stop_event.wait(5)
        except Exception as exc:
            self.error = repr(exc)
            self.ready.set()

    def close(self):
        self.stop_event.set()
        self.thread.join(10)
        if self.thread.is_alive():
            self.error = 'telemetry thread did not stop'


def summarize(output, summary):
    """Stream evidence from disk, retaining only scalars and lifecycle anchors."""
    buckets = defaultdict(lambda:defaultdict(list))
    started = summary['started_at']
    samples = []
    tick_rows = []
    checkpoint_ticks = set()
    with (output/'telemetry.jsonl').open(encoding='utf-8') as f:
        for line in f:
            row = json.loads(line)
            samples.append(row)
            minute = max(0,int((row['wall_time']-started)//60))
            for name in ('rss','private_bytes','cpu_s'):
                if row[name] is not None:
                    buckets[minute][name].append(row[name])
            for match in row['matches']:
                for name in ('minions_total','minions_live','actor_slots','input_queue','join_sequence','keepalive_ticks',
                             'buff_allocations','shop_allocations','interrupt_serials','attack_interrupt_serials'):
                    if name in match:
                        buckets[minute][name].append(match[name])
    with (output/'server.log').open(encoding='utf-8') as f:
        for line in f:
            if '[movement-tick] ' not in line:
                continue
            row = json.loads(line.split('[movement-tick] ',1)[1])
            if 'population' in row:
                tick_rows.append((row['tick'],row['sim_time']/60,row['population'],row['work_ms']))
            minute = max(0,int((row['wall_time']-started)//60))
            for name in ('work_ms','late_ms'):
                buckets[minute][name].append(row[name])
    latency = defaultdict(list)
    anchors = defaultdict(list)
    # Prefer the producer's explicit receipts. The legacy fallback deliberately
    # excludes both historical and current diagnostic sidecar names.
    journals = ([Path(row['path']) for row in summary['journals']] if 'journals' in summary else
                [path for path in output.glob('inputs-*.jsonl')
                 if re.fullmatch(r'inputs-[0-9a-f]{32}\.jsonl', path.name)])
    for path in journals:
        with path.open(encoding='utf-8') as f:
            for line in f:
                row = json.loads(line)
                if row['kind'] != 'operation':
                    continue
                args = row['arguments']
                checkpoint_ticks.update(c['tick'] for c in row['checkpoints'] if c['label']=='periodic')
                if args.get('receive_monotonic_ns') is not None:
                    value = (row['apply_monotonic_ns']-args['receive_monotonic_ns'])/1e6
                    phase = row['phase'] + ('/readiness' if args['opcode'] in (1134,1137) else '/input')
                    latency[phase].append(value)
                    minute = max(0,int((row['apply_monotonic_ns']-summary['started_monotonic_ns'])/60e9))
                    buckets[minute]['receive_apply_ms'].append(value)
                for event in row['events']:
                    if event['opcode'] in (1072,1074,1106,1009,1085,1082):
                        anchors[event['uuid']].append(event)
    summary['telemetry_per_minute'] = [dict(minute=minute,**{name:distribution(values) for name,values in data.items()})
                                       for minute,data in sorted(buckets.items())]
    summary['latency_by_phase_ms'] = {name:distribution(values) for name,values in latency.items()}
    summary['peak_rss'] = max((r['rss'] for r in samples),default=None)
    summary['peak_private_bytes'] = max((r['private_bytes'] or 0 for r in samples),default=None)
    summary['process_cpu_s'] = samples[-1]['cpu_s']-samples[0]['cpu_s'] if len(samples)>1 else None
    summary['population_time_fits'] = {}
    for label, group in (('all_ticks',tick_rows),
                         ('checkpoint_ticks',[row for row in tick_rows if row[0] in checkpoint_ticks])):
        summary['population_time_fits'][label] = {
            population:{window:population_time_fit([(minute,counts[population],work)
                        for _,minute,counts,work in group if minute>=start])
                        for window,start in (('all_samples',0),('after_two_minutes',2))}
            for population in ('minions_live','actor_slots')}
    summary['population_time_fit_limits'] = [
        'Linear observational fits; live population and time can be correlated, not proof of causality.',
        'Approximate 95% intervals cluster residuals by simulation minute; few clusters limit precision.',
        'Whole-run and declared after-two-minute fits retain all outliers in their respective intervals.',
        'These fits do not erase >50ms findings or define an automatic numerical acceptance waiver.']
    process_samples = [samples]
    participant_path = output/'participant-telemetry.jsonl'
    if participant_path.is_file():
        with participant_path.open(encoding='utf-8') as source:
            process_samples.append([json.loads(line) for line in source])
    summary['process_telemetry'] = {}
    for rows in process_samples:
        if not rows:
            raise ValueError('empty process telemetry')
        identities = {(row.get('role','combined'),row.get('pid')) for row in rows}
        if len(identities) != 1:
            raise ValueError('mixed process identities in telemetry')
        role,pid = identities.pop()
        if role in summary['process_telemetry']:
            raise ValueError('duplicate process telemetry role')
        per_minute = defaultdict(lambda:defaultdict(list))
        for row in rows:
            minute = max(0,int((row['wall_time']-started)//60))
            for name in ('rss','private_bytes','cpu_s'):
                if row[name] is not None:
                    per_minute[minute][name].append(row[name])
        summary['process_telemetry'][role] = {'pid':pid, 'samples':len(rows),
            'peak_rss':max(row['rss'] for row in rows),
            'peak_private_bytes':max(row['private_bytes'] or 0 for row in rows),
            'cpu_seconds':rows[-1]['cpu_s']-rows[0]['cpu_s'],
            'per_minute':[dict(minute=minute,**{name:distribution(values) for name,values in data.items()})
                          for minute,data in sorted(per_minute.items())]}
    summary['peak_rss_process_role'] = samples[0].get('role','combined')
    if summary.get('server_process',{}).get('isolated'):
        server, participant = (summary['process_telemetry'].get(role) for role in ('server','participants'))
        receipt = summary['server_process']
        if (server is None or participant is None or server['pid'] == participant['pid']
                or server['pid'] != receipt['server_pid'] or participant['pid'] != receipt['participant_pid']):
            raise ValueError('isolated process telemetry does not match server/participant receipts')
    # Independent recipient/tick anchors are in the journal; stream proofs remain
    # each participant's own JSONL and must pass before these are summarized.
    (output/'lifecycle-tick-anchors.json').write_text(json.dumps(dict(anchors),indent=2),encoding='utf-8')
    summary['journal_tick_anchors'] = str(output/'lifecycle-tick-anchors.json')

"""Opt-in diagnostics observer. No measurement is passed to participant policy."""
from collections import defaultdict
import json
import threading
import time


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count':0}
    return {'count':len(values),'p50':values[len(values)//2],
            'p95':values[round((len(values)-1)*.95)],'max':values[-1]}


class Telemetry:
    def __init__(self, gateway, output):
        import psutil
        self.process = psutil.Process()
        self.gateway, self.output = gateway, output
        self.stop_event = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.run,name='m3-telemetry',daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        try:
            with (self.output/'telemetry.jsonl').open('x',encoding='utf-8') as log:
                while not self.stop_event.is_set():
                    memory, cpu = self.process.memory_info(),self.process.cpu_times()
                    row = {'wall_time':time.time(),'cpu_s':cpu.user+cpu.system,
                           'rss':memory.rss,'private_bytes':getattr(memory,'private',None),'matches':[]}
                    for match in list(self.gateway.matches):
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
                                'thread_alive':world.is_alive()})
                    log.write(json.dumps(row)+'\n')
                    log.flush()
                    self.stop_event.wait(5)
        except Exception as exc:
            self.error = repr(exc)

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
    with (output/'telemetry.jsonl').open(encoding='utf-8') as f:
        for line in f:
            row = json.loads(line)
            samples.append(row)
            minute = max(0,int((row['wall_time']-started)//60))
            for name in ('rss','private_bytes','cpu_s'):
                if row[name] is not None:
                    buckets[minute][name].append(row[name])
            for match in row['matches']:
                for name in ('minions_total','minions_live','actor_slots','input_queue','join_sequence','keepalive_ticks','buff_allocations'):
                    buckets[minute][name].append(match[name])
    with (output/'server.log').open(encoding='utf-8') as f:
        for line in f:
            if '[movement-tick] ' not in line:
                continue
            row = json.loads(line.split('[movement-tick] ',1)[1])
            minute = max(0,int((row['wall_time']-started)//60))
            for name in ('work_ms','late_ms'):
                buckets[minute][name].append(row[name])
    latency = defaultdict(list)
    anchors = defaultdict(list)
    for path in output.glob('inputs-*.jsonl'):
        with path.open(encoding='utf-8') as f:
            for line in f:
                row = json.loads(line)
                if row['kind'] != 'operation':
                    continue
                args = row['arguments']
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
    # Independent recipient/tick anchors are in the journal; stream proofs remain
    # each participant's own JSONL and must pass before these are summarized.
    (output/'lifecycle-tick-anchors.json').write_text(json.dumps(dict(anchors),indent=2),encoding='utf-8')
    summary['journal_tick_anchors'] = str(output/'lifecycle-tick-anchors.json')

"""Opt-in ordinary menu/draft entry for ClientDriver; not an executable path.

All controls come from the pinned native tree. Server records bind one
explicit listener/guest to connections; ordering never substitutes for identity.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
import json
import math
import os
from pathlib import Path
import time
import uuid

from Tools import native_ui
from Tools.android_input_health import (qualify_owned_ldplayer, require_owned_window,
                                       wait_launch_ready, wait_native_input_ready)
from Tools.Teardown.observe_client_movement import ClientMovementObserver


class MixedCoordination:
    """Opt-in one-CE barrier; no UI receipt survives the bounded hold."""
    def __init__(self, plan):
        from Tools.protocol_participants import MIXED_HEROES, bounded_seconds
        from server import hero_catalog
        from Tools.verification_support import reject_link_traversal
        self.ready = Path(plan['mixed_draft_ready'])
        self.release = Path(plan['mixed_world_release'])
        self.after = plan['not_before']
        if type(self.after) not in (int, float) or not math.isfinite(self.after) or not 0 < self.after <= time.time():
            raise ValueError('mixed coordination requires a finite past run epoch')
        self.timeout = bounded_seconds(plan.get('mixed_timeout_s', 120))
        root = Path(__file__).resolve().parents[1] / 'Local/evidence'
        for path in (self.ready, self.release):
            reject_link_traversal(path)
            if root not in path.resolve().parents:
                raise ValueError('mixed coordination files must be under Local/evidence')
        if self.release.resolve() == self.ready.resolve():
            raise ValueError('mixed coordination requires distinct barrier paths')
        if self.release.exists() or self.ready.exists():
            raise ValueError('mixed coordination requires initially absent run files')
        self.assignment = None
        self.connection = None
        # Optional explicit slot-ordered composition for the measured bot-hero
        # bisection. Absent this field, retain the original six-hero contract.
        heroes = plan.get('mixed_heroes_by_slot')
        self.heroes_by_slot = None
        if heroes is not None:
            if (not isinstance(heroes, list) or len(heroes) != 6
                    or any(not isinstance(h, str) or h not in MIXED_HEROES for h in heroes)):
                raise ValueError('mixed draft: explicit six-hero slot composition required')
            ids = [hero_catalog.resolve_hero_id(h) for h in heroes]
            if ids[0] != 265 or len(set(ids)) != 6:
                raise ValueError('mixed draft: distinct heroes and CE Skye in slot0 required')
            self.heroes_by_slot = ids

    def validate(self, value, binding, rows):
        from Tools.protocol_participants import HEROES, EIDS, SLOTS, selections
        from server import hero_catalog, roster
        verified = value.get('verified_at')
        if (value.get('match_id') != binding['match_id'] or value.get('not_before') != self.after
                or type(verified) not in (int, float) or not math.isfinite(verified)
                or not self.after <= verified <= time.time()):
            raise ValueError('mixed draft: wrong match/start epoch or stale receipt')
        assigned = value.get('assignments', {})
        six = list(assigned.values())
        if (len(six) != 6 or {r['slot'] for r in six} != set(range(6))
                or (any(r['hero_id'] != self.heroes_by_slot[r['slot']] for r in six)
                    if self.heroes_by_slot is not None else
                    {r['hero_id'] for r in six} != {hero_catalog.resolve_hero_id(h) for h in HEROES})
                or any(k != r['identity'] or not k or k == roster.BOT_UUID_SENTINEL for k, r in assigned.items())
                or any((r['eid'], r['team'], r['flags']) !=
                       (dict(zip(SLOTS, EIDS))[r['slot']], 1 if r['slot'] < 3 else 2,
                        roster.PICK_FLAG_SELECTED) for r in six)):
            raise ValueError('mixed draft: all six selected human assignments required')
        own = assigned.get(binding['identity'])
        if not own or any(own[k] != binding[k] for k in ('eid', 'slot', 'team')) or own['hero_id'] != 265:
            raise ValueError('mixed draft: CE owner/selection mismatch')
        streams = value.get('streams', [])
        if len(streams) != 5 or {s['identity'] for s in streams} != set(assigned)-{binding['identity']}:
            raise ValueError('mixed draft: five participant streams required (one CE only)')
        for stream in streams:
            snapshot = stream['snapshot']
            if (snapshot['direction'] != 's2c' or snapshot['opcode'] != 1113
                    or not self.after <= snapshot['wall_time'] <= verified
                    or {r['identity']: r for r in selections(bytes.fromhex(snapshot['payload_hex']))} != assigned):
                raise ValueError('mixed draft: participant snapshot disagrees')
        latest = [r for r in rows if r.get('connection') == binding['connection']
                  and r.get('direction') == 's2c' and r.get('opcode') == 1113
                  and r['time'] >= self.after]
        if not latest:
            raise ValueError('mixed draft: no current CE roster')
        current = {r['identity']: r for r in selections(bytes.fromhex(latest[-1]['payload']))}
        if (set(current) != set(assigned) or any(any(current[i][k] != a[k]
                for k in ('eid', 'slot', 'team', 'hero_id')) for i, a in assigned.items())
                or any(r['flags'] not in (roster.PICK_FLAG_SELECTED, roster.PICK_FLAG_LOCKED)
                       for r in current.values())
                or current[binding['identity']]['flags'] != roster.PICK_FLAG_SELECTED):
            raise ValueError('mixed draft: current CE roster changed or CE already locked')
        return own

    def hold(self, entry, binding):
        entry.record('MIXED_HOLD', path=str(self.ready))
        def ready():
            if not self.ready.exists():
                return None
            value = json.loads(self.ready.read_text(encoding='utf-8'))
            entry.d.tail.poll()
            self.assignment = self.validate(value, binding, entry.d.tail.records)
            self.connection = binding['connection']
            return value
        receipt = entry.wait('mixed draft-ready', ready, timeout=self.timeout)
        entry.record('MIXED_DRAFT_READY', receipt=receipt)

    def publish(self, binding, qualified):
        if (self.assignment is None or binding['connection'] != self.connection
                or any(binding[k] != self.assignment[k] for k in ('eid', 'slot', 'team', 'identity'))):
            raise ValueError('mixed release: owner changed after hold')
        if (qualified.get('stage') != 'QUALIFIED_WORLD'
                or any(qualified[k] != binding[k] for k in ('eid', 'slot', 'connection')) or qualified['hero_id'] != 265
                or type(qualified.get('at')) not in (int, float) or not math.isfinite(qualified['at'])
                or not self.after <= qualified['at'] <= time.time()):
            raise ValueError('mixed release: native qualification owner mismatch')
        value = {'match_id': binding['match_id'], 'qualified_at': qualified['at'],
                 'clients': [{**{k: binding[k] for k in ('identity', 'connection', 'eid', 'slot', 'team')},
                              'hero_id': qualified['hero_id'], 'qualified_world': True}]}
        if self.release.exists():
            raise ValueError('mixed release already exists')
        pending = self.release.with_name(self.release.name + '.' + uuid.uuid4().hex + '.pending')
        with pending.open('x', encoding='utf-8') as output:
            output.write(json.dumps(value, allow_nan=False))
            output.flush()
            os.fsync(output.fileno())
        # Windows rename refuses an existing destination; never overwrite a release.
        if self.release.exists():
            raise ValueError('mixed release already exists')
        pending.rename(self.release)
        return value


def guest_binding(rows, device, after):
    sessions = [r for r in rows if r.get('t', 0) >= after
                and r.get('method') == 'startSessionForPlayer'
                and r.get('device_tag') == device['device_tag']
                and r.get('listener_port') == device['listener_port']]
    guests = {r.get('guest_id') for r in sessions}
    if not sessions:
        return None
    if len(guests) != 1 or None in guests:
        raise ValueError('bootstrap: guest identity absent or ambiguous on explicit listener')
    guest = next(iter(guests))
    if device.get('guest_id', guest) != guest:
        raise ValueError('bootstrap: wrong guest on explicit listener')
    return {'device_tag': device['device_tag'], 'listener_port': device['listener_port'],
            'guest_id': guest, 'identities': sorted({i for r in sessions for i in r['match_identities']}),
            'bootstrap': [{k: r[k] for k in ('t', 'method', 'guest_id', 'device_tag', 'listener_port')} for r in sessions]}


def connection_binding(rows, guest, after, *, world=False):
    closed = {r['connection'] for r in rows if r.get('direction') == 'disconnect'}
    candidates = [r for r in rows if r.get('direction') == 'identity' and r.get('time', 0) >= after
                  and r.get('identity') in guest['identities'] and r['connection'] not in closed]
    if world:
        candidates = [r for r in candidates if any(w.get('connection') == r['connection']
            and w.get('direction') == 's2c' and w.get('opcode') == 1011 for w in rows)]
    if not candidates:
        return None
    if len({r['connection'] for r in candidates}) != 1:
        raise ValueError('binding: ambiguous active connections for guest; never choose newest')
    binding = candidates[0]
    owners = {int(r['payload'][:8], 16) for r in rows if r.get('connection') == binding['connection']
              and r.get('direction') == 's2c' and r.get('opcode') == 1001 and len(r['payload']) == 204}
    if owners != {binding['eid']}:
        raise ValueError('binding: 1000 identity and 1001 owner disagree')
    return binding


def admission_roster(rows, guests, after):
    bindings = [connection_binding(rows, guest, after) for guest in guests]
    if any(b is None for b in bindings):
        return None
    if (len({g['guest_id'] for g in guests}) != len(guests)
            or len({b['eid'] for b in bindings}) != len(guests)
            or len({b['connection'] for b in bindings}) != len(guests)
            or len({b['match_id'] for b in bindings}) != 1):
        raise ValueError('admission: guests/connections/owners not distinct in one match')
    if len(bindings) == 2 and {b['team'] for b in bindings} != {1, 2}:
        raise ValueError('admission: two clients are not on opposite teams')
    connected_at = max(b['time'] for b in bindings)
    connections = {b['connection'] for b in bindings}
    if any(r.get('connection') in connections and r.get('opcode') in (1006, 1132, 1011)
           and r.get('direction') == 's2c' for r in rows):
        raise ValueError('admission: draft already finalized; no lock input')
    if any(r.get('connection') in connections and r.get('opcode') == 1123
           and r.get('direction') == 'c2s' and r['time'] < connected_at for r in rows):
        raise ValueError('admission: a human locked before both were connected')
    # Selection echoes prove that both drivers are actually in draft. No
    # first-client lock or timeout auto-lock is used to manufacture admission.
    if not all(any(r.get('connection') == b['connection'] and r.get('direction') == 's2c'
                   and r.get('opcode') == 1118 and r['time'] >= b['time'] for r in rows) for b in bindings):
        return None
    return bindings


def bound_roster_handles(rows, binding, after):
    """Latest s2c1113 on this admitted CE connection, never accumulated frames."""
    from Tools.protocol_participants import selections
    from server import roster
    if binding is None:
        return None
    connection = binding['connection']
    if (binding.get('direction') != 'identity' or binding['time'] < after
            or binding not in rows or any(r.get('connection') == connection
                                         and r.get('direction') == 'disconnect' for r in rows)):
        return None
    snapshots = [r for r in rows if r.get('connection') == connection
                 and r.get('direction') == 's2c' and r.get('opcode') == 1113
                 # _serve_join logs identity AFTER sending the opener. The
                 # connection binding, not trace-row order, identifies it.
                 and r.get('time', 0) >= after]
    if not snapshots:
        return None
    payload = bytes.fromhex(snapshots[-1]['payload'])
    players = selections(payload)
    own = [p for p in players if p['identity'] == binding['identity']]
    if len(own) != 1 or any(own[0][k] != binding[k] for k in ('slot', 'eid', 'team')):
        raise ValueError('draft handles: bound CE identity/owner differs from 1113')
    return Counter(payload[roster.SNAPSHOT_RECORD_BASE + p['slot'] * roster.SNAPSHOT_RECORD_STRIDE + 17:
                           roster.SNAPSHOT_RECORD_BASE + p['slot'] * roster.SNAPSHOT_RECORD_STRIDE + 97]
                   .split(b'\0', 1)[0].decode('ascii') for p in players)


@contextmanager
def input_lease(path, timeout, *, owner=None, record=lambda **row: None):
    """Serialize qualified gestures for owned clients, not game time."""
    import msvcrt
    path = Path(path).resolve()
    token = uuid.uuid4().hex
    identity = {'token': token, 'driver': owner, 'host_pid': os.getpid()}
    owner_path = path.with_name(path.name + '.owner.json')
    waiter = path.with_name(path.name + '.waiter-' + token + '.json')
    def publish(target, row):
        temporary = target.with_name(target.name + '.' + token + '.tmp')
        temporary.write_text(json.dumps(row), encoding='utf-8')
        temporary.replace(target)
    def peers():
        return [row for p in path.parent.glob(path.name + '.waiter-*.json')
                if p != waiter and (row := json.loads(p.read_text(encoding='utf-8')))['status'] == 'waiting']
    requested = time.time()
    publish(waiter, {**identity, 'status': 'waiting', 'requested_at': requested})
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    publish(waiter, {**identity, 'status': 'timeout', 'at': time.time()})
                    record(event='timeout', **identity, requested_at=requested, waiting_peers=peers())
                    raise ValueError('entry: owned-window input lease unavailable')
                time.sleep(.1)
        acquired = time.time()
        def check():
            os.fstat(handle.fileno())
            if json.loads(owner_path.read_text(encoding='utf-8')).get('token') != token:
                raise ValueError('entry: host input ownership lost; no further gestures')
        try:
            publish(owner_path, {**identity, 'acquired_at': acquired})
            publish(waiter, {**identity, 'status': 'acquired', 'at': acquired})
            record(event='acquire', **identity, requested_at=requested, acquired_at=acquired, waiting_peers=peers())
            yield check
            check()
        finally:
            waiting = peers()
            try:
                publish(waiter, {**identity, 'status': 'released', 'at': time.time()})
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            record(event='release', **identity, acquired_at=acquired, released_at=time.time(), waiting_peers=waiting)


class NonvisualEntry:
    def __init__(self, driver):
        self.d = driver
        self.plan = driver.profile['nonvisual_entry']
        self.after = self.plan['not_before']
        self.timeout = min(180, float(self.plan.get('timeout_s', 90)))
        if not 0 < self.timeout <= 180 or not isinstance(self.after, (float, int)):
            raise ValueError('entry: invalid bounded timeout/start instant')
        self.draft_observation_reads = self.plan.get('draft_observation_only', 0)
        if self.draft_observation_reads != 0 and (type(self.draft_observation_reads) is not int
                or not 50 <= self.draft_observation_reads <= 100):
            raise ValueError('entry: draft observation-only requires 50..100 complete reads')
        self.device = {k: self.plan[k] for k in ('device_tag', 'listener_port')}
        if 'guest_id' in self.plan:
            self.device['guest_id'] = self.plan['guest_id']
        if self.device['device_tag'] and self.device['device_tag'] != self.d.adb.serial:
            raise ValueError('entry: device serial differs from listener tag')
        self.hero = int(self.plan.get('hero_id', 265))
        self.hero_label = self.plan.get('hero_label', 'Skye')
        self.observer = ClientMovementObserver(driver.adb, driver.out_dir / 'entry-native.jsonl', None,
                                               ui_only=True, **self.plan.get('runtime_observer', {}))
        self.java = native_ui.ClientInputState(self.observer, driver.out_dir, self.plan['java_bridge'])
        self.events = driver.observations.setdefault('nonvisual_entry', [])
        self.guest = None
        self.binding = None
        self.admission_guests = None
        self._scroll_returned = None
        self._transition_pending = None
        from Tools.scenario_client import TraceTail
        self.rpc = TraceTail(self.plan['rpc_journal'])
        self.tails = {}
        self.mixed = (MixedCoordination(self.plan) if
                      'mixed_draft_ready' in self.plan or 'mixed_world_release' in self.plan else None)
        # Reuse this entry's input lease and evidence writer for a late BUILD
        # at mixed setup, after the entry observer has stopped.
        self.d._build_entry = self

    def record(self, stage, **detail):
        row = {'stage': stage, 'at': time.time(), **detail}
        self.events.append(row)
        with (self.d.out_dir / 'entry-stages.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, allow_nan=False) + '\n')
        return row

    def read(self):
        state = native_ui.fresh_ui_state(self.observer,
            lambda gap: self.record('UI_READ_GAP', **gap), bracket=True)
        self.record_read(state)
        return state

    def record_read(self, state):
        """Retain each completed read and measured per-screen resource maxima."""
        metrics = state['traversal']
        stage = self.screen(state)
        self.record('UI_READ', native_stage=stage, traversal=metrics)
        summary = self.d.observations.setdefault('entry_ui_maxima', {}).setdefault(stage,
            {'reads': 0, 'visited': 0, 'active': 0, 'duration_ms': 0})
        summary['reads'] += 1
        for field in ('visited', 'active', 'duration_ms'):
            summary[field] = max(summary[field], metrics[field])

    def screen(self, state):
        handles = None
        if self.binding is not None and 'Waiting for Players...' in state['labels']:
            self.d.tail.poll()
            handles = bound_roster_handles(self.d.tail.records, self.binding, self.after)
        return native_ui.screen(state, roster_handles=handles)

    def wait(self, name, predicate, *, timeout=None):
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            value = predicate()
            if value:
                return value
            if time.monotonic() >= deadline:
                raise ValueError(f'{name}: missing transition/signal within bounded wait; no input retry')
            time.sleep(.15)

    def wait_screen(self, wanted, previous, *, transitions=()):
        stable = None
        last = None
        unknown_since = None
        unknown_count = 0
        def check():
            nonlocal stable, last, unknown_since, unknown_count
            state = self.read()
            native_ui.complete_tree(state)
            stage = self.screen(state)
            if stage == 'UNKNOWN':
                now = time.monotonic()
                if unknown_since is None:
                    unknown_since = now
                unknown_count += 1
                stable = last = None
                duration = now - unknown_since
                self.record('TRANSIENT_UNKNOWN', expected=wanted, previous=previous,
                            count=unknown_count, continuous_s=duration, native=state)
                # Step3/3b/3c HARD/roster frames and step4d d922fd52
                # boot-1/entry/entry-stages.jsonl:114 (missing SEC) were
                # retained 0.11-0.35s after transition input. 3s/15 reads are
                # orchestrator-chosen margins, NOT measured settling times.
                # This wait sends no input; control qualification is unchanged.
                if duration > 3.0 or unknown_count > 15:
                    raise ValueError(f'{previous}->{wanted}: transient UNKNOWN bound exceeded '
                                     f'({duration:.3f}s continuous, {unknown_count} total reads)')
                return None
            unknown_since = None
            permitted = (wanted, previous, 'LOADING', *transitions) + (('BOOTSTRAP',) if wanted == 'MENU' else ())
            if stage not in permitted:
                self.record('UNEXPECTED_SCREEN', expected=wanted, previous=previous, native=state)
                raise ValueError(f'{previous}->{wanted}: unknown/unexpected native screen {stage}')
            if stage != wanted:
                stable = None
                return None
            signature = (state['root'], native_ui.screen_context(state))
            settled = stable == signature
            stable = signature
            if settled:
                self.record('SCREEN_PAIR', native_stage=stage, before=last, after=state,
                            differences=native_ui.tree_differences(last, state))
            last = state
            # Screen recognition is not control qualification. Each eventual
            # gesture separately protects the full selected ancestry and region.
            return state if settled else None
        state = self.wait(f'{previous}->{wanted}', check)
        self._transition_pending = None
        self.record(wanted, native=state)
        return state

    def health(self):
        if self.d._foreground_package() != 'com.superevilmegacorp.game':
            raise ValueError('entry: focused Android package lost')
        java = self.java.snapshot()
        self.record('JAVA_READINESS', state=java)
        rows = java['rows']
        if (len(rows) != 1 or rows[0].get('paused') is not False
                or rows[0].get('window_focus') is not True
                or rows[0].get('initialized') is not True or rows[0].get('enabled') is not True):
            raise ValueError('entry: Java view focus/initialized/unpaused readiness absent')
        lifecycle = wait_native_input_ready(self.d.adb, timeout=min(10, self.timeout))
        self.record('NATIVE_READINESS', lifecycle=lifecycle)
        if not lifecycle['ready']:
            raise ValueError('entry: native Resume readiness absent')
        return {'java': java, 'lifecycle': lifecycle}

    @contextmanager
    def input_window(self):
        if getattr(self, '_input_failed', False):
            raise ValueError('entry: prior input ownership failure; no further gestures')
        try:
            with input_lease(self.plan['input_lock'], self.timeout, owner=self.d.adb.serial,
                             record=lambda **row: self.record('INPUT_LEASE', **row)) as check:
                host = self.plan.get('host_window')
                if not host:
                    raise ValueError('entry: path-qualified host window/PID required')
                window = qualify_owned_ldplayer(host['executable'], process_id=host['pid'])
                self.record('HOST_WINDOW', receipt=window)
                def verify():
                    check()
                    self._last_host_window = require_owned_window(window)
                    self.record('HOST_WINDOW_CHECK', receipt=self._last_host_window)
                self._input_check = verify
                yield
                verify()
        except Exception:
            self._input_failed = True
            raise
        finally:
            self._input_check = None

    def control_pair(self, label, stage, *, hero_id=None, scroll=False):
        """Window every DRAFT control; never retry a prepared input."""
        if stage == 'DRAFT':
            return self.draft_control_pair(label, stage, hero_id=hero_id, scroll=scroll)
        ancestry_failures = 0
        for attempt in range(20):
            before, after = self.read(), self.read()
            try:
                receipt = native_ui.qualify_pair(before, after, label, stage,
                    hero_id=hero_id, allow_offscreen=scroll)
            except native_ui.ControlMutation as exc:
                self.record('CONTROL_PAIR_REFUSED', attempt=attempt, label=label, reason=str(exc),
                    ancestry=exc.ancestry, replan=exc.replan, differences=exc.differences, before=before, after=after)
                ancestry_failures += int(exc.ancestry)
                if not exc.settling:
                    raise
                if attempt == 19:
                    reason = ('REPLAN selected control/full ancestry never stable'
                              if ancestry_failures == 20 else 'protected control region never stable')
                    raise ValueError(f'{stage}: {reason} within 20 complete read pairs; no input') from exc
                time.sleep(.1)
            else:
                self.record('CONTROL_PAIR', receipt=receipt, before=before, after=after)
                return after, receipt

    def draft_control_pair(self, label, stage, *, hero_id=None, scroll=False):
        """Exact structural span followed by a fresh adjacent input pair."""
        # ba0ea6b2: last protected changes at 3.10/3.09/1.88s, stable tails
        # 34..43 reads (5.0..6.3s). Historical censored floor 3.388s + chosen
        # 0.5s margin => T=3.888s; median read-start cadence .147s => N=28
        # (ceil(T/cadence)+1). These are margins, not a settling guarantee.
        # e72b7c5e: the first control's revalidation changed six ancestors by
        # 0x2 only 1.11s after DRAFT_OPEN. Apply the same window to opening,
        # every scroll, hero selection and LOCK IN, not just post-scroll.
        # Preserve the scroll-return budget; otherwise start a new per-control
        # budget here. Each call collects its own span, never a cached receipt.
        started = self._scroll_returned if self._scroll_returned is not None else time.monotonic()
        deadline = started + 15
        signature, first, previous, count = None, None, None, 0
        while time.monotonic() < deadline:
            state = self.read()
            current, pulse_nodes = native_ui.protected_signature(state, label, stage,
                hero_id=hero_id, allow_offscreen=scroll, include_pulse_nodes=True)
            changed = signature != current
            if previous is not None and not changed:
                # Equal structural signatures prove every protected field is
                # identical except pulse bit 2 and rev4 descendant leaf flags.
                # Only pulse-maskable nodes are logged as PULSE_0x2 below.
                # This is historical
                # evidence, NOT a receipt: no freshness checks until the final
                # adjacent qualify_pair and the single revalidation below.
                pulses = [{**d, 'classification': 'PULSE_0x2', 'xor': 2, 'changed_bits': [1]}
                          for d in native_ui.tree_differences(previous, state)
                          if d['address'] in pulse_nodes]
                if pulses:
                    self.record('PULSE_0x2', label=label, differences=pulses,
                        before_started=previous['host_read_started'], before_ended=previous['host_read_ended'],
                        after_started=state['host_read_started'], after_ended=state['host_read_ended'])
            if changed:
                first, count = state['host_read_started'], 0
            count += 1
            span = state['host_read_started'] - first
            self.record('DRAFT_CONTROL_WINDOW', native=state, label=label, scroll=scroll,
                protected_signature=current, restarted=changed, reads=count, span_s=span,
                scroll_returned=self._scroll_returned, window_started=started, deadline=deadline)
            if time.monotonic() >= deadline:
                break
            if count >= 28 and span >= 3.888:
                # Last two adjacent reads belong to the identical-signature
                # window. Old span endpoints are NEVER qualified as receipts.
                receipt = native_ui.qualify_pair(previous, state, label, stage,
                    hero_id=hero_id, allow_offscreen=scroll)
                self.record('CONTROL_PAIR', receipt=receipt, before=previous, after=state)
                self._scroll_returned = None
                return state, receipt
            signature, previous = current, state
        raise ValueError(f'{stage}: structural window exhausted 15s budget; no input')

    def act(self, label, stage, *, hero_id=None, scroll=False, transition=False):
        if pending := getattr(self, '_transition_pending', None):
            raise ValueError(f'{stage}: input refused; prior transition {pending} not yet qualified')
        with self.input_window():
            health = self.health()
            state, receipt = self.control_pair(label, stage, hero_id=hero_id, scroll=scroll)
            if scroll:
                clip, center = receipt['clip'], receipt['center']
                if receipt['visible'] or center[1] <= clip[3] or clip[3]-clip[1] < 100:
                    raise ValueError('DRAFT: unsupported scroll direction/region; no gesture')
                # The region is the selected hero control's measured clip, not
                # retained 960x540 swipe coordinates. Stay strictly inside it.
                x = round((clip[0]+clip[2])/2)
                start = [x, round(clip[3]-30)]
                end = [x, round(max(clip[1]+30, start[1]-min(250, center[1]-clip[3]+60)))]
                receipt.update(scroll_start=start, scroll_end=end)
            # Revalidate once after the prepared receipt; no settling/retry at
            # this boundary. Outside differences remain in the gesture receipt.
            rechecked = self.read()
            self.record('CONTROL_REVALIDATION', receipt=receipt, before=state, after=rechecked)
            final = native_ui.qualify_pair(state, rechecked, label, stage,
                                          hero_id=hero_id, allow_offscreen=scroll)
            receipt['pairs'] = [receipt.pop('pair'), final['pair']]
            receipt['outside_difference_count'] = sum(p['outside_difference_count'] for p in receipt['pairs'])
            receipt['tolerated_difference_count'] = sum(p['tolerated_difference_count'] for p in receipt['pairs'])
            view = self.java.snapshot()['rows']
            if (len(view) != 1 or view[0].get('window_focus') is not True
                    or view[0].get('paused') is not False or view[0].get('initialized') is not True
                    or view[0].get('enabled') is not True):
                raise ValueError(f'{stage}: Java focus lost between receipt and gesture')
            if label == 'LOCK IN':
                self.d.tail.poll()
                if self.admission_guests is None or admission_roster(
                        self.d.tail.records, self.admission_guests, self.after) is None:
                    raise ValueError('admission: peer left or selection disappeared before LOCK IN')
            if check := getattr(self, '_input_check', None):
                check()
            if time.monotonic()-state['host_read_started'] > 1.5:
                raise ValueError(f'{stage}: stale control pair immediately before input')
            host = getattr(self, '_last_host_window', None)
            if label == 'PLAY' and self.plan.get('require_background_play'):
                if not host or host['after_foreground']['hwnd'] == host['hwnd']:
                    raise ValueError('PLAY: nonforeground proof requires another host foreground; no input')
            before = time.time()
            self.d.gesture('entry-scroll' if scroll else 'entry-control', receipt=receipt,
                           health=health, host_window=host, wall_before=before)
            self.record(stage, input_receipt=receipt, health=health, host_window=host, wall_before=before)
            if scroll:
                self.d.adb.swipe(*start, *end, duration_ms=500)
                self._scroll_returned = time.monotonic()
            else:
                x, y = receipt['center']
                self.d.adb.swipe(x, y, x, y, duration_ms=180)
            self.record(stage, input_transport='returned', wall_before=before)
            if check := getattr(self, '_input_check', None):
                check()
            self.health()
            after_a, after_b = self.read(), self.read()
            native_ui.complete_tree(after_a)
            native_ui.complete_tree(after_b)
            self.record('POST_INPUT_PAIR', input_stage=stage, label=label, before=after_a, after=after_b,
                        differences=native_ui.tree_differences(after_a, after_b),
                        context_stable=(after_a['root'] == after_b['root']
                            and native_ui.screen_context(after_a) == native_ui.screen_context(after_b)))
            if 'UNKNOWN' in (native_ui.screen(after_a), native_ui.screen(after_b)):
                if not transition or 'Settings' in after_a['labels'] or 'Settings' in after_b['labels']:
                    raise ValueError(f'{stage}: unknown post-input screen; no further gestures')
                self.record('POST_INPUT_TRANSIENT', input_stage=stage, label=label, before=after_a, after=after_b,
                            reason='post-input UNKNOWN deferred to bounded wait_screen')
                self._transition_pending = stage
        return before, receipt

    def poll_wire(self):
        from Tools.scenario_client import TraceTail
        # Enumerate this explicit fresh run's directory; bind by identity, not
        # timestamp/newest-file/newest-connection heuristics.
        for path in Path(self.plan['wire_dir']).glob('wire-*.jsonl'):
            self.tails.setdefault(path, TraceTail(path)).poll()
        return [(tail, row) for tail in self.tails.values() for row in tail.records]

    def bind(self, *, world=False):
        self.poll_wire()
        matching = []
        for tail in self.tails.values():
            binding = connection_binding(tail.records, self.guest, self.after, world=world)
            if binding:
                matching.append((tail, binding))
        if len(matching) > 1:
            raise ValueError('binding: guest exists in multiple traces; refusing ambiguous match')
        if not matching:
            return None
        tail, binding = matching[0]
        self.binding = binding
        self.d.tail, self.d.connection = tail, binding['connection']
        self.record('WORLD_BINDING' if world else 'DRAFT_BINDING', guest=self.guest,
                    device_serial=self.d.adb.serial, binding=binding, wire_trace=str(tail.path))
        return binding

    def rpc_rows(self):
        self.rpc.poll()
        return self.rpc.records

    def server_ops(self, opcodes, since, *, direction='s2c'):
        self.d.tail.poll()
        rows = [r for r in self.d.tail.records if r.get('connection') == self.d.connection
                and r.get('direction') == direction and r.get('time', 0) >= since and r.get('opcode') in opcodes]
        return rows if {r['opcode'] for r in rows} == set(opcodes) else None

    def select(self):
        for attempt in range(7):
            state = self.read()
            receipt = native_ui.control_receipt(state, self.hero_label, 'DRAFT', hero_id=self.hero, allow_offscreen=True)
            if receipt['visible']:
                before, _ = self.act(self.hero_label, 'DRAFT', hero_id=self.hero)
                rows = self.wait('hero selection 1118 echo', lambda: self.server_ops([1118], before))
                if any(int(r['payload'][:8], 16) != self.hero for r in rows):
                    raise ValueError('DRAFT: selected hero echo mismatch')
                self.record('HERO_SELECTED', server_acceptance=rows, native=self.read())
                return
            if attempt == 6:
                raise ValueError('DRAFT: bounded hero scrolling exhausted')
            _, before = self.act(self.hero_label, 'DRAFT', hero_id=self.hero, scroll=True)
            time.sleep(.7)
            after = native_ui.control_receipt(self.read(), self.hero_label, 'DRAFT', hero_id=self.hero, allow_offscreen=True)
            if after['center'][1] >= before['center'][1]-20:
                raise ValueError('DRAFT: scroll did not move target toward viewport; no repeated swipe')
            self.record('HERO_SCROLL_PROGRESS', before=before, after=after)

    def admission(self):
        devices = [self.device] + self.plan.get('peers', [])
        if len(devices) not in (1, 2):
            raise ValueError('admission: this entry stage supports one or two explicit devices')
        def ready():
            guests = [guest_binding(self.rpc_rows(), device, self.after) for device in devices]
            if any(g is None for g in guests):
                return None
            self.d.tail.poll()
            roster = admission_roster(self.d.tail.records, guests, self.after)
            if roster:
                self.admission_guests = guests
            return roster
        roster = self.wait('admission: both humans connected and selected before LOCK IN', ready)
        self.record('ADMISSION', roster=roster)

    def observe_draft_only(self):
        """Bounded no-input evidence series; never claims WORLD qualification."""
        root = None
        for index in range(self.draft_observation_reads):
            state = self.read()
            native_ui.complete_tree(state)
            receipt = native_ui.control_receipt(state, 'LOCK IN', 'DRAFT')
            if root is not None and state['root'] != root:
                raise ValueError('DRAFT observation-only: root changed during series')
            root = state['root']
            self.record('DRAFT_OBSERVATION', index=index, native=state, control=receipt)
            time.sleep(.1)
        raise ValueError(f'DRAFT observation-only: {self.draft_observation_reads} complete no-input '
                         'reads retained; stopped before LOCK IN, not WORLD acceptance')

    def run(self):
        from Tools.scenario_client import ClientStageFailure, verify_resolution
        try:
            self.d._client_version = self.d.adb.client_version()
            if self.d._client_version != {'version_name': '4.13.4', 'version_code': 147219}:
                raise ValueError('entry: pinned CE 4.13.4/build 147219 required')
            verify_resolution(self.d.adb, self.d.profile)
            readiness = wait_launch_ready(self.d.adb, after_guest_wall=self.plan['launch_guest_wall'],
                record=lambda row: self.record('PRE_ATTACH_READINESS', **row))
            if not readiness['ready']:
                raise ValueError('entry: pre-attach stable PID/resumed/initialized/native Resume readiness absent')
            qualification = self.observer.start()
            self.record('UI_READER', qualification=qualification)
            self.record_read(qualification['ui'])
            self.record('JAVA_READER', qualification=self.java.start())
            self.guest = self.wait('bootstrap: device/listener guest',
                lambda: guest_binding(self.rpc_rows(), self.device, self.after))
            self.record('BOOTSTRAP', guest=self.guest, device_serial=self.d.adb.serial)
            self.wait_screen('MENU', 'MENU')
            for label, stage, target in (('PLAY', 'MENU', 'MODE'), ('SOLO BOTS', 'MODE', 'MAP'),
                                         ('3V3', 'MAP', 'DIFFICULTY')):
                self.act(label, stage, transition=True)
                try:
                    transition = self.wait_screen(target, stage)
                except ValueError as exc:
                    if label == 'PLAY' and self.plan.get('require_background_play'):
                        self.record('BACKGROUND_PLAY_PROOF', consumed=None,
                                    status='UNACKNOWLEDGED', reason=str(exc))
                        raise ValueError('REPLAN nonforeground PLAY consumption unverified: '+str(exc)) from exc
                    raise
                if label == 'PLAY' and self.plan.get('require_background_play'):
                    self.record('BACKGROUND_PLAY_PROOF', consumed=True, native=transition,
                                server_acceptance='pending ordinary joinLobby after mode/map/difficulty')
            before, _ = self.act('VERY EASY', 'DIFFICULTY', transition=True)
            def joined():
                rows = [r for r in self.rpc_rows() if r.get('t', 0) >= before and r.get('method') == 'joinLobby'
                        and r.get('device_tag') == self.device['device_tag']
                        and r.get('listener_port') == self.device['listener_port']
                        and r.get('guest_id') == self.guest['guest_id']]
                return rows or None
            rows = self.wait('joinLobby RPC acceptance', joined)
            self.record('JOIN_LOBBY', server_acceptance=rows)
            if any(r.get('response', {}).get('code') != 0 for r in rows):
                raise ValueError('joinLobby: observed non-success reply; retained response, no retry')
            if self.plan.get('require_background_play'):
                self.record('BACKGROUND_ENTRY_SERVER_ACCEPTANCE', server_acceptance=rows)
            draft = self.wait('gateway: guest->draft connection->owner', self.bind)
            self.record('DRAFT_OPEN', server_acceptance=self.wait('1001/1108/1113 draft opener',
                lambda: self.server_ops([1001, 1108, 1113], before)))
            # Retained live-07: the queue panels retire to MENU after the
            # bound server opener, before draft attaches. No MENU input here.
            self.wait_screen('DRAFT', 'DIFFICULTY', transitions=('MENU', 'MENU_TRANSITION', 'DRAFT_WAIT'))
            self.select()
            if self.draft_observation_reads:
                self.observe_draft_only()
            if self.mixed is not None:
                self.mixed.hold(self, draft)
            self.admission()
            before, _ = self.act('LOCK IN', 'DRAFT', transition=True)
            self.record('LOCK_INPUT', server_acceptance=self.wait('1123 lock acknowledgment',
                lambda: self.server_ops([1123], before)))
            self.wait_screen('LOCKED', 'DRAFT')
            self.record('FINALIZATION', server_acceptance=self.wait('1119/1006/1132 finalization',
                lambda: self.server_ops([1119, 1006, 1132], before)))
            self.record('LOAD_INPUT', server_acceptance=self.wait('1134/1137 client load readiness',
                lambda: self.server_ops([1134, 1137], before, direction='c2s')))
            world = self.wait('WORLD: bound owner 1011 on explicit guest connection', lambda: self.bind(world=True))
            if (world['eid'], world['slot'], world['match_id']) != (draft['eid'], draft['slot'], draft['match_id']):
                raise ValueError('WORLD: owner/slot/match changed at draft handoff')
            self.wait('WORLD: ready echo', lambda: self.server_ops([1137], before))
            # Never the ungated roster-era BACK (before-run-04/07). A fresh
            # WORLD BUILD title may gate one BACK: retained movement-consumer
            # short-patched-guarded and reference-oracle ce-short-second/fourth
            # reach HUD afterward (run-1791786914358-020cdcb8/PHASE1.md).
            state = self.wait('loading/build/native HUD', lambda: self._ready_screen())
            self.leave_build(state)
            self.d._guard_nonvisual_movement_ui(self.observer, dismiss_build=True, state_reader=self.read)
            eid, slot, hero = self.d._qualify_nonvisual_world({'hero_id': self.hero})
            self.d.profile['local_player_eid'] = eid
            self.record('QUALIFIED_WORLD', eid=eid, slot=slot, hero_id=hero, connection=self.d.connection,
                        native=self.read(), provenance=self.d.provenance_frame())
            self.d.observations['entry_binding'] = {'guest': self.guest, 'draft': draft, 'world': world,
                                                   'device_serial': self.d.adb.serial}
            if self.mixed is not None:
                self.record('MIXED_WORLD_RELEASE', receipt=self.mixed.publish(world, self.events[-1]))
            self.d.stage('SETUP', 'PASS', 'ordinary nonvisual menu/draft -> identity-bound WORLD with native HUD')
        except ClientStageFailure:
            raise
        except Exception as exc:
            raise ClientStageFailure('SETUP', 'FAIL', f'nonvisual entry: {exc}') from exc
        finally:
            self.java.stop()
            self.observer.stop()
            self.d.artifact(self.d.out_dir / 'entry-stages.jsonl')

    def leave_build(self, state):
        """Dismiss only a freshly identified BUILD, or use the explicit shop plan."""
        if native_ui.screen(state) == 'HUD':
            return
        native_ui.complete_tree(state)
        if native_ui.screen(state) != 'BUILD':
            raise ValueError(f'BUILD exit: unexpected native screen {native_ui.screen(state)}')
        if 'shop_close_label' not in self.plan:
            self.d._guard_nonvisual_movement_ui(self.observer, dismiss_build=True, state_reader=self.read)
            return
        # No default: retained 4j SHOP trees qualify neither Shop nor Item Shop.
        # CLOSE is unevidenced and remains available only as an explicit
        # shop_close_label plan option, still subject to ordinary act guards.
        label = self.plan.get('shop_close_label')
        if not isinstance(label, str) or not label.strip():
            raise ValueError('BUILD: no evidence-qualified shop exit candidate; no shop input')
        self.act('OPEN SHOP', 'BUILD', transition=True)
        self.wait_screen('SHOP', 'BUILD')
        self.act(label, 'SHOP')
        # Unlike a generic transition wait, any non-HUD outcome is terminal.
        before = self.read()
        after = self.read()
        for current in (before, after):
            native_ui.complete_tree(current)
            if native_ui.screen(current) != 'HUD':
                self.record('BUILD_EXIT_REFUSED', native=current)
                raise ValueError(f'SHOP exit: expected HUD, got {native_ui.screen(current)}')
        if before['root'] != after['root'] or native_ui.screen_context(before) != native_ui.screen_context(after):
            raise ValueError('SHOP exit: HUD pair changed')
        self.record('BUILD_EXIT_HUD', before=before, after=after)

    def _ready_screen(self):
        before, state = self.read(), self.read()
        native_ui.complete_tree(before)
        native_ui.complete_tree(state)
        self.record('LOADING_PAIR', before=before, after=state,
                    differences=native_ui.tree_differences(before, state))
        if (before['root'] != state['root']
                or native_ui.screen_context(before) != native_ui.screen_context(state)):
            return None
        stage = native_ui.screen(state)
        if stage in ('HUD', 'BUILD'):
            return state
        if stage not in ('LOCKED', 'LOADING'):
            raise ValueError(f'loading: unknown screen {stage}')
        return None

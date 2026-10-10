"""Opt-in ordinary menu/draft entry for ClientDriver; not an executable path.

All controls come from the pinned native tree. Server records bind one
explicit listener/guest to connections; ordering never substitutes for identity.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
import uuid

from Tools import native_ui
from Tools.android_input_health import (activate_owned_ldplayer, require_owned_foreground,
                                       wait_launch_ready, wait_native_input_ready)
from Tools.Teardown.observe_client_movement import ClientMovementObserver


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


@contextmanager
def input_lease(path, timeout, *, owner=None, record=lambda **row: None):
    """Serialize two owned windows' focus + qualified gestures, not game time."""
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
        self.admission_guests = None
        from Tools.scenario_client import TraceTail
        self.rpc = TraceTail(self.plan['rpc_journal'])
        self.tails = {}

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
        stage = native_ui.screen(state)
        self.record('UI_READ', native_stage=stage, traversal=metrics)
        summary = self.d.observations.setdefault('entry_ui_maxima', {}).setdefault(stage,
            {'reads': 0, 'visited': 0, 'active': 0, 'duration_ms': 0})
        summary['reads'] += 1
        for field in ('visited', 'active', 'duration_ms'):
            summary[field] = max(summary[field], metrics[field])

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
        def check():
            nonlocal stable, last
            state = self.read()
            native_ui.complete_tree(state)
            stage = native_ui.screen(state)
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
                activation = None
                if host:
                    activation = activate_owned_ldplayer(host['executable'], process_id=host['pid'])
                    self.record('HOST_FOCUS', receipt=activation)
                def verify():
                    check()
                    if activation:
                        self.record('HOST_FOCUS_CHECK', receipt=require_owned_foreground(activation))
                self._input_check = verify
                yield
                verify()
        except Exception:
            self._input_failed = True
            raise
        finally:
            self._input_check = None

    def control_pair(self, label, stage, *, hero_id=None, scroll=False):
        """At most 20 pre-receipt pairs; never retry a prepared input."""
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

    def act(self, label, stage, *, hero_id=None, scroll=False):
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
            if time.monotonic()-state['host_read_started'] > 1.5:
                raise ValueError(f'{stage}: stale control pair immediately before input')
            if check := getattr(self, '_input_check', None):
                check()
            before = time.time()
            self.d.gesture('entry-scroll' if scroll else 'entry-control', receipt=receipt,
                           health=health, wall_before=before)
            self.record(stage, input_receipt=receipt, health=health, wall_before=before)
            if scroll:
                self.d.adb.swipe(*start, *end, duration_ms=500)
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
                raise ValueError(f'{stage}: unknown post-input screen; no further gestures')
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
                self.act(label, stage)
                self.wait_screen(target, stage)
            before, _ = self.act('VERY EASY', 'DIFFICULTY')
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
            draft = self.wait('gateway: guest->draft connection->owner', self.bind)
            self.record('DRAFT_OPEN', server_acceptance=self.wait('1001/1108/1113 draft opener',
                lambda: self.server_ops([1001, 1108, 1113], before)))
            # Retained live-07: the queue panels retire to MENU after the
            # bound server opener, before draft attaches. No MENU input here.
            self.wait_screen('DRAFT', 'DIFFICULTY', transitions=('MENU', 'MENU_TRANSITION'))
            self.select()
            if self.draft_observation_reads:
                self.observe_draft_only()
            self.admission()
            before, _ = self.act('LOCK IN', 'DRAFT')
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
            # Qualified panel control, never the legacy build/back gesture.
            state = self.wait('loading/build/native HUD', lambda: self._ready_screen())
            if native_ui.screen(state) == 'BUILD':
                self.act('OPEN SHOP', 'BUILD')
                self.wait_screen('SHOP', 'BUILD')
                # Shop's identified native CLOSE label must be present; never
                # replace a missing control with a guessed screen coordinate.
                self.act(self.plan.get('shop_close_label', 'CLOSE'), 'SHOP')
                self.wait_screen('HUD', 'SHOP')
            self.d._guard_nonvisual_movement_ui(self.observer, state_reader=self.read)
            eid, slot, hero = self.d._qualify_nonvisual_world({'hero_id': self.hero})
            self.d.profile['local_player_eid'] = eid
            self.record('QUALIFIED_WORLD', eid=eid, slot=slot, hero_id=hero, connection=self.d.connection,
                        native=self.read(), provenance=self.d.provenance_frame())
            self.d.observations['entry_binding'] = {'guest': self.guest, 'draft': draft, 'world': world,
                                                   'device_serial': self.d.adb.serial}
            self.d.stage('SETUP', 'PASS', 'ordinary nonvisual menu/draft -> identity-bound WORLD with native HUD')
        except ClientStageFailure:
            raise
        except Exception as exc:
            raise ClientStageFailure('SETUP', 'FAIL', f'nonvisual entry: {exc}') from exc
        finally:
            self.java.stop()
            self.observer.stop()
            self.d.artifact(self.d.out_dir / 'entry-stages.jsonl')

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

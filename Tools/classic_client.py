"""Data-only ordinary Classic match exercise, invoked by scenario_client.

This is a deliberately simple lane-playing policy, not a server AI, gameplay
oracle, or proof of official parity. QA is read-only; all actions use Android
input and code-qualified native controls/projection. No image/capture API.
"""
from __future__ import annotations

import json
import math
import struct
import time

from Tools.Teardown.client_projection import world_to_screen

PICK_CLEARANCE_WORLD = 1.5


def mixed_pick_risk(camera, destination, xy, actors):
    """Pick geometry may extend offscreen; the actual tap stays central-guarded."""
    from server.hitboxes import segment_distance
    def clip(xyz):
        vector = list(xyz)+[1]
        for matrix in (camera['view'], camera['projection']):
            vector = [sum(matrix[4*j+i]*vector[j] for j in range(4)) for i in range(4)]
        return vector
    def project(vector, minimum_w=1e-6):
        if vector[3] <= minimum_w:
            return None  # A capsule wholly behind the camera cannot be picked.
        return ((vector[0]/vector[3]+1)*camera['dimensions'][0]/2,
                (1-vector[1]/vector[3])*camera['dimensions'][1]/2)
    for actor in actors:
        ground = actor['position_xyz']
        center = actor['selection_center_xyz']
        top = [center[0], center[1]+.5*actor['selection_height'], center[2]]
        horizontal = [center[0]+PICK_CLEARANCE_WORLD, center[1], center[2]]
        anchors = list(map(clip, (ground, top, center, horizontal)))
        ground_xy, top_xy, center_xy, horizontal_xy = (project(v, 0) for v in anchors)
        p = camera['projection']
        perspective = (all(math.isfinite(v) for v in p) and p[0] > 0 and p[5] > 0
                       and p[10] < -1 and p[11] == -1 and p[14] < 0
                       and all(p[i] == 0 for i in (1, 2, 3, 4, 6, 7, 12, 13, 15)))
        n = p[14]/(p[10]-1) if perspective else float('nan')
        branch = 'all-projected'
        if perspective and math.isfinite(n) and n > 0 and all(v[3] >= n for v in anchors):
            r_px = math.dist(center_xy, horizontal_xy)
            capsule = segment_distance(xy, ground_xy, top_xy) <= r_px
        else:
            r_px, capsule = None, True  # Unknown capsule is not permission to tap.
            branch = 'unknown'
            if perspective:
                if math.isfinite(n) and n > 0:
                    branch = 'clipped'
                    a, b = sorted(anchors[:2], key=lambda v: v[3])
                    r_px, capsule = 0, False
                    if b[3] >= n:
                        if a[3] < n:
                            t = (n-a[3])/(b[3]-a[3])
                            a = [x+t*(y-x) for x, y in zip(a, b)]
                            a[3] = n
                        r_px = PICK_CLEARANCE_WORLD*p[0]*camera['dimensions'][0]/2/a[3]
                        capsule = segment_distance(xy, project(a, 0), project(b, 0)) <= r_px
        near = math.dist(destination, (ground[0], ground[2])) < PICK_CLEARANCE_WORLD
        if near or capsule:
            return dict(actor_eid=actor['eid'], destination=destination, screen_point=xy,
                        r_px=r_px, reason='world clearance' if near else 'screen pick capsule', branch=branch,
                        position_xyz=ground, selection_center_xyz=center, selection_height=actor['selection_height'],
                        camera={k: camera[k] for k in ('view', 'projection', 'dimensions')},
                        clip_w=dict(zip(('ground', 'top', 'center', 'horizontal'), (v[3] for v in anchors))))
    return None


def wire_payload_hex(payload):
    """Server traces precede encryption; socket receipts retain cipher padding."""
    raw = bytes.fromhex(payload)
    return (raw + bytes((-2-len(raw)) % 8)).hex()


def participant_receipt_binding(receipt, peer_records, records, expected):
    """Bind a peer generation to its ordinary handshake and server identity.

    Never pin the initial connection across reconnect, or accept another log
    merely because every peer receives the same broadcast damage payload.
    """
    generation, at = receipt.get('generation'), receipt.get('wall_time', 0)
    if type(generation) is not int or generation < 1:
        return None
    identities = [r for r in records if r.get('direction') == 'identity'
                  and r.get('identity') == expected['identity']]
    identities.sort(key=lambda r: r['time'])
    if len(identities) < generation:
        return None
    identity = identities[generation-1]
    keys = ('identity', 'eid', 'slot', 'team', 'match_id')
    if (any(identity.get(k) != expected[k] for k in keys) or identity['time'] > at
            or len({r['connection'] for r in identities}) != len(identities)
            or any(r['time'] <= at for r in identities[generation:])):
        return None
    # New logs carry these fields; old retained logs are bound below through
    # their 1000/1001/1011 handshake, not through an invented identity label.
    if any(k in receipt and receipt[k] != expected[k] for k in keys):
        return None
    rows = [r for r in peer_records if r.get('generation') == generation and r.get('wall_time', 0) <= at]
    joins = [r for r in rows if r.get('direction') == 'c2s' and r.get('opcode') == 1000]
    owners = [r for r in rows if r.get('direction') == 's2c' and r.get('opcode') == 1001]
    blocks = [r for r in rows if r.get('direction') == 's2c' and r.get('opcode') == 1011
              and len(r.get('payload_hex', '')) >= 24
              and int(r['payload_hex'][16:24], 16) == expected['eid']]
    if len(joins) != 1 or len(owners) != 1 or len(blocks) != 1:
        return None
    join = bytes.fromhex(joins[0]['payload_hex']).split(b'\0', 1)[0]
    owner, block = bytes.fromhex(owners[0]['payload_hex']), bytes.fromhex(blocks[0]['payload_hex'])
    if (join != expected['identity'].encode('ascii') or len(owner) < 4 or len(block) < 746
            or int.from_bytes(owner[:4], 'big') != expected['eid']
            or int.from_bytes(block[12:16], 'big') != expected['team'] or block[745] != expected['slot']):
        return None
    # Match both bootstrap receipts byte-for-byte (including canonical padding)
    # on this connection. Identity/EID reuse in another match cannot qualify.
    for peer in (owners[0], blocks[0]):
        anchors = [r for r in records if r.get('connection') == identity['connection']
                   and r.get('direction') == 's2c' and r.get('opcode') == peer['opcode']
                   and r.get('time', 0) <= at
                   and wire_payload_hex(r.get('payload', '')) == peer['payload_hex']]
        if len(anchors) != 1:
            return None
    return {k: identity[k] for k in (*keys, 'connection')} | {'generation': generation}


def native_damage_window(before, after, records, *, connection, source, victim,
                         participant_records, participant_binding, require_basic_input=False):
    """Conservative time-bracketed correlation, not a server-output oracle.

    Replay *all* resource deltas onto the measured native baseline, including
    regen/healing and barrier/fortified absorption. Reject ambiguous lifetimes,
    read-boundary events, implicit growth, other attackers and missing peer
    receipts. Float32 accumulation error is bounded from the actual operands;
    it is not a gameplay tolerance. Unknown windows remain UNVERIFIED.
    """
    from collections import Counter
    from Tools.protocol_observer import Actor, Observer
    result = {'classification': 'missing input', 'source': source, 'victim': victim,
              'before': {'actors': {victim: before['actors'].get(victim)}, 'tick': before.get('tick')},
              'after': {'actors': {victim: after['actors'].get(victim)}, 'tick': after.get('tick')},
              'damage': [], 'resource_events': []}
    def unknown(reason):
        result['unknown'] = reason
        return result
    a, b = before['actors'].get(victim), after['actors'].get(victim)
    if not a or not b:
        return unknown('native actor missing')
    start, end = a['host_before'], b['host_after']
    if not start <= a['host_after'] < b['host_before'] <= end or end-start > 5:
        return unknown('native sampling bracket invalid or longer than five seconds')
    fields = ('hp', 'max_hp', 'barrier', 'fortified')
    if any(type(r.get(k)) not in (int, float) or not math.isfinite(r[k]) or r[k] < 0
           for r in (a, b) for k in fields):
        return unknown('native resource values invalid')
    if (any(r.get('eid') != victim or type(r.get('generation')) is not int for r in (a, b))
            or a['generation'] != b['generation'] or a['max_hp'] != b['max_hp']):
        return unknown('native lifetime/max HP changed')
    rows = [r for r in records if r.get('connection') == connection and start <= r.get('time', 0) <= end]
    damage, resource = [], []
    for r in rows:
        if r.get('direction') != 's2c':
            continue
        op, p = r.get('opcode'), bytes.fromhex(r.get('payload', ''))
        if len(p) < 4 or int.from_bytes(p[:4], 'big') != victim:
            continue
        if op in (1052, 1076, 1072, 1074, 1035):
            return unknown('implicit growth/lifecycle change inside measurement')
        if op == 1054:
            if len(p) < 12:
                return unknown('truncated damage payload')
            delta = struct.unpack_from('>f', p, 8)[0]
            if not math.isfinite(delta):
                return unknown('nonfinite damage')
            if delta < 0:
                damage.append(r)
            resource.append(r)
        elif op == 1053:
            if len(p) < 9:
                return unknown('truncated resource payload')
            if p[8] in (0, 4, 5):
                if not math.isfinite(struct.unpack_from('>f', p, 4)[0]):
                    return unknown('nonfinite resource delta')
                resource.append(r)
    selected = [r for r in damage if int(r['payload'][8:16], 16) == source]
    result.update(damage=selected, resource_events=resource)
    if not selected:
        return unknown('no source-bound 1054 in native bracket')
    result['classification'] = 'authoritative outcome observed; CE-native effect unverified'
    if any(r['time'] <= a['host_after'] or r['time'] >= b['host_before'] for r in resource):
        return unknown('resource event overlaps native accessor read')
    if len(selected) != len(damage):
        return unknown('other attackers confound HP attribution')
    expected = Counter(wire_payload_hex(r['payload']) for r in selected)
    peer = [r for r in participant_records if r.get('direction') == 's2c' and r.get('opcode') == 1054
            and start <= r.get('wall_time', 0) <= end and r.get('payload_hex') in expected]
    if Counter(r['payload_hex'] for r in peer) != expected:
        return unknown('participant damage receipts absent/ambiguous in same bracket')
    bindings = [participant_receipt_binding(r, participant_records, records, participant_binding) for r in peer]
    if not all(bindings):
        return unknown('participant receipt identity/generation/bootstrap absent or ambiguous')
    result['participant_receipts'] = peer
    result['participant_receipt_bindings'] = bindings
    if require_basic_input:
        first = selected[0]['time']
        inputs = [r for r in records if r.get('connection') == connection and r.get('direction') == 'c2s'
                  and r.get('opcode') == 1060 and len(r.get('payload', '')) == 12
                  and int(r['payload'][:8], 16) == victim and r['time'] <= first]
        if not inputs:
            return unknown('CE ordinary 1060 not observed')
        request = inputs[-1]
        intervening = [r for r in records if r.get('connection') == connection and r.get('direction') == 'c2s'
                       and request['time'] < r['time'] <= first and r.get('opcode') in (1012, 1060, 1041, 1042)]
        attacks = [r for r in records if r.get('connection') == connection and r.get('direction') == 's2c'
                   and r.get('opcode') == 1045 and r.get('payload', '')[:16] == struct.pack('>II', source, victim).hex()
                   and request['time'] <= r['time'] <= first]
        if intervening or not attacks:
            return unknown('basic input superseded or attack start unobserved')
        result.update(request=request, attack_start=attacks[-1])
    observer = Observer()
    actor = Actor(victim, 'hero', 0, 0, hp=a['hp'], max_hp=a['max_hp'],
                  barrier=a['barrier'], fortified=a['fortified'])
    observer.bind(actor)
    # A conservative sum of one float32 rounding unit per operation, scaled by
    # the largest actual operand. No latency or unmeasured regen allowance.
    scale = max(a['max_hp'], a['barrier'], a['fortified'], 1)
    for r in resource:
        payload = bytes.fromhex(r['payload'])
        delta = struct.unpack_from('>f', payload, 8 if r['opcode'] == 1054 else 4)[0]
        scale = max(scale, abs(delta))
        observer.consume(r['opcode'], payload)
        if actor.hp > actor.max_hp:
            return unknown('healing at cap has unqualified clamping order')
    tolerance = (len(resource)*8+2)*scale*2**-23
    result.update(predicted={k: getattr(actor, k) for k in ('hp', 'barrier', 'fortified')},
                  numeric_tolerance=tolerance, native_hp_drop=a['hp']-b['hp'])
    if any(abs(getattr(actor, k)-b[k]) > tolerance for k in ('hp', 'barrier', 'fortified')):
        return unknown('native resource delta does not reconcile with complete wire window')
    if a['hp'] <= b['hp']:
        return unknown('no measured native HP drop (absorption/regen may mask it)')
    result['classification'] = 'authoritative outcome + measured CE-native effect'
    return result


def central_projection(camera, xyz):
    """Never let a world action hit persistent HUD controls."""
    if camera['dimensions'] != [960, 540]:
        raise ValueError('unqualified viewport')
    xy = list(map(round, world_to_screen(camera, xyz)))
    if not (240 <= xy[0] <= 680 and 100 <= xy[1] <= 420):
        raise ValueError('projected point outside qualified central playfield')
    return xy


def next_upgrade(owner):
    if not owner['alive'] or not owner['ability_points']:
        return None
    for slot in (2, 0, 1):
        rank = owner['ranks'].get(str(slot), 0)
        gates = (6, 9, 12) if slot == 2 else (1, 2, 4, 6, 8)
        if rank < len(gates) and owner['level'] >= gates[rank]:
            return slot
    return None


def next_purchase(owner):
    """An affordable purchase supported by the qualified native shop controls."""
    ids = [i['item'] for i in owner['inventory']]
    item, cost = (505, 850) if 458 in ids else (458, 300)
    if (len(ids) >= 6 and item == 458) or owner['gold'] < cost:
        return None
    return item, cost


def recall_needed(owner, completed_recalls):
    # Surplus gold is not a reason to return when this policy cannot spend it.
    # Keep the first coverage Recall and ordinary resource-recovery reasons.
    return (completed_recalls == 0 or owner['hp']/owner['max_hp'] < .5
            or owner['energy'] < 100
            or (owner['gold'] >= 1000 and next_purchase(owner) is not None))


def vulnerable_structures(state, team):
    """Use the current production tier contract, not an official-rule claim."""
    from server.structures import STRUCTURE_TEMPLATES
    tiers = {s.eid: s.tier for s in STRUCTURE_TEMPLATES}
    alive = [s for s in state['structures'] if s['team'] != team and s['alive']]
    return [s for s in alive if tiers[s['eid']] == min(tiers[a['eid']] for a in alive)] if alive else []


def path_step(mesh, origin, goal, distance=4.0):
    """Choose a bounded native-click goal; the real client still plans the walk."""
    path = mesh.find_path(origin, goal)
    if not path:
        raise ValueError('no walkable route to lane goal')
    previous = origin
    for point in path:
        length = math.dist(previous, point)
        if length >= distance:
            return tuple(a + (b-a)*distance/length for a, b in zip(previous, point))
        distance -= length
        previous = point
    return tuple(previous)


# A float interpolation along an on-mesh route can quantize just outside an
# edge (C 4m: 1.32e-6 units). Snap only within this bound; a larger gap is a
# genuinely off-mesh goal and still raises.
ON_MESH_CLICK_TOLERANCE = 1e-3


def on_mesh_click(mesh, point):
    """Return (point, height, snapped_distance) for a click endpoint on the owned mesh."""
    try:
        return tuple(point), mesh.height_at(point), 0.0
    except ValueError:
        snapped = tuple(mesh.nearest_point(point))
        gap = math.dist(point, snapped)
        if gap > ON_MESH_CLICK_TOLERANCE:
            raise
        return snapped, mesh.height_at(snapped), gap


def lane_goal(origin, objective, team):
    direction = 1 if team == 1 else -1
    # The base waypoint is at -65.62, so a -65 threshold would repeatedly
    # click the owner at its arrival point and never leave this first leg.
    if origin[0]*direction < -67:
        return (-65.62*direction, 11.101)
    return (objective['x']-direction*4, max(5.5, objective['y']))


def recent_target_lock(records, connection, owner_eid, target_eid, now):
    """A fresh, uncancelled wire lock, not inferred from target selection.

    The one-second age bound is a conservative input policy, not the game's
    lock duration. Reverse traversal bounds work to this recent trace window.
    A newer lock on another target supersedes any older candidate.
    """
    from server import buff_wire
    cancelled, dead = set(), set()
    for record in reversed(records):
        age = now-record['time']
        if age > 1:
            break
        if record.get('connection') != connection or record.get('direction') != 's2c':
            continue
        payload = bytes.fromhex(record.get('payload', ''))
        opcode = record.get('opcode')
        if opcode == 1093:
            cancelled.add(buff_wire.parse_buff_cancel(payload))
        elif opcode == 1072 and len(payload) >= 4:
            dead.add(struct.unpack_from('>I', payload)[0])
        elif opcode == 1086:
            buff = buff_wire.parse_buff_add(payload)
            if buff.source_eid != owner_eid or buff.kind != 602:
                continue
            if (buff.target_eid != target_eid or age < 0 or buff.duration-age < .75
                    or (buff.target_eid, buff.instance_id) in cancelled
                    or {owner_eid, target_eid} & dead):
                return None
            return record
    return None


class ClassicMatchExercise:
    def __init__(self, driver):
        self.d = driver
        self.plan = {'hero_id': 265, 'capture_backend': 'none', 'drive_entry': False,
                     'max_duration_s': 1800, 'max_entry_sim_time_s': 75, 'require_fresh_start': True,
                     'abilities': ['A', 'B', 'C'], 'require_recall': True}
        self.plan.update(driver.profile.get('classic_match') or {})
        self.counts = dict(move=0, target=0, target_race=0, target_interrupted=0,
                           upgrade=0, purchase=0, cast=0, flask=0, recall=0,
                           recall_attempt=0, recall_interrupted=0, cast_interrupted=0)
        self.last_target = None
        self.last_action = 0.0
        self.no_action_since = time.monotonic()
        self.cast_until = 0.0
        self.owner_damage = 0.0
        self.samples = 0
        self.ability_counts = dict(A=0, B=0, C=0)
        self.pending_recall = None
        self.last_recall_attempt = -math.inf
        self.mixed_team = None
        self.mixed_respawn = None
        self.mixed_rendezvous = None

    @staticmethod
    def require(ok, stage, detail):
        if not ok:
            from Tools.scenario_client import ClientStageFailure
            raise ClientStageFailure(stage, 'FAIL', detail)

    def owned(self, state):
        rows = [r for r in state['heroes'] if r['eid'] == self.eid]
        self.require(len(rows) == 1 and rows[0]['hero_id'] == 265,
                     'TRIAL_CONTINUITY', 'owned Skye identity changed')
        return rows[0]

    def receipt(self, direction, opcode, predicate, since, stage, *, allow_missing=False):
        r = self.d.tail.wait_for(lambda r: self.d._on_connection(r)
            and r.get('direction') == direction and r.get('opcode') == opcode and predicate(r),
            min(self.d.timeout, 2), min_time=since)
        self.require(r is not None or allow_missing, stage,
                     f'ordinary action missing matching {direction} {opcode}; no blind retry')
        return r

    def record(self, kind, **detail):
        self.counts[kind] += 1
        self.last_action = time.monotonic()
        self.no_action_since = self.last_action
        self.d.gesture('classic-' + kind, **detail)

    def tap_control(self, control):
        self.require(control['eid'] == self.eid, 'SETUP', 'native control owner mismatch')
        before = time.time()
        self.d.gesture('classic-control-attempt', control=control, wall_before=before)
        self.d.adb.tap(*control['center'])
        self.d.stage('UI_COMMAND_SUBMITTED', 'PASS', 'ordinary native-qualified control submitted')
        return before

    def fresh_ui_state(self):
        """Read-only wait for a complete tree during native panel transitions.

        The live result panel settled at625 nodes, below the existing1024
        bound. A transient traversal failure is unknown, never an empty UI.
        Keep the bound unchanged and do not send/repeat any Android input.
        """
        from Tools.native_ui import fresh_ui_state
        try:
            return fresh_ui_state(self.observer,
                self.d.observations.setdefault('ui_read_gaps', []).append)
        except ValueError as exc:
            self.require(False, 'PRESENTATION', str(exc))

    def upgrade(self, owner, slot):
        # The native Level Up panel can precede its enabled upgrade controls.
        # Wait for the same complete owner/lifetime/binding/rectangle checks;
        # never send a tap based only on the server's new ability point.
        for attempt in range(16):
            try:
                control = self.observer.ability_control(slot, upgrade=True)
                break
            except Exception as exc:
                if 'ability control absent, ambiguous or changed' not in str(exc):
                    raise
                self.d.observations.setdefault('upgrade_control_waits', []).append(
                    {'at':time.time(), 'slot':slot, 'attempt':attempt, 'unknown':str(exc)})
                self.require(attempt < 15, 'SETUP', 'native upgrade control never qualified; no input attempted')
                time.sleep(.1)
        before = self.tap_control(control)
        request = self.receipt('c2s', 1078, lambda r: r['payload'] == (bytes([slot])+bytes(5)).hex(),
                               before, 'CLIENT_INPUT_OBSERVED')
        after = self.owned(self.d.qa.snapshot())
        self.require(after['ranks'].get(str(slot), 0) == owner['ranks'].get(str(slot), 0)+1,
                     'SERVER_ACKNOWLEDGED', 'ordinary upgrade did not increment rank')
        self.record('upgrade', control=control, request=request, before=owner, after=after)

    def purchase(self, owner):
        # Only the two native catalog controls already live-qualified. Multiple
        # Heavy Steels are ordinary purchases, not simulated inventory writes.
        from server import roster
        planned = next_purchase(owner)
        if planned is None:
            return False
        item, cost = planned
        self.tap_control(self.observer.shop_control())
        time.sleep(.25)
        self.tap_control(self.observer.shop_item_control(item))
        time.sleep(.25)
        before = self.tap_control(self.observer.shop_buy_control(item))
        request = self.receipt('c2s', 1081, lambda r: r['payload'] == roster.build_shop_buy(self.eid, item).hex(),
                               before, 'CLIENT_INPUT_OBSERVED')
        ack = self.receipt('s2c', 1081, lambda r: r['payload'] == request['payload'],
                           request['time'], 'SERVER_ACKNOWLEDGED')
        state = self.d.qa.snapshot()
        after = self.owned(state)
        native = self.observer.inventory()
        identity = lambda items: sorted((i['item'], i['instance']) for i in items)
        self.require(identity(native['items']) == identity(after['inventory']+after['default_items']),
                     'PRESENTATION', 'native purchased inventory differs')
        self.d.adb.back()
        self.settle_shop_closed()
        self.d._guard_nonvisual_movement_ui(self.observer, state_reader=self.fresh_ui_state)
        self.record('purchase', item=item, cost=cost, request=request, ack=ack,
                    before=owner, after=after, native=native)
        return True

    def settle_shop_closed(self):
        """Read-only transition wait; never act on an incomplete native tree.

        Rapid close/reopen can overlap retiring catalog trees. Preserve every
        failed read and require two stable, HUD-only qualified trees before
        another action. Do not increase traversal bounds or repeat Back.
        """
        deadline = time.monotonic()+2
        reads, previous = [], None
        self.d.observations.setdefault('shop_close_reads', []).append(reads)
        while time.monotonic() < deadline:
            try:
                state = self.observer.ui_state()
            except Exception as exc:
                reads.append({'at':time.time(), 'unknown':str(exc)})
                previous = None
            else:
                reads.append({'at':time.time(), 'state':state})
                ready = 'BUY:' in state['labels'] and 'BACKPACK (DRAG TO RE-ORDER)' not in state['labels']
                identity = (state['root'], state['nodes']) if ready else None
                if identity is not None and identity == previous:
                    return
                previous = identity
            time.sleep(.1)
        self.require(False, 'SETUP', 'shop closing never reached two stable qualified HUD trees; no repeated input')

    def fresh_camera_actors(self, eids):
        """Retry only concurrent camera reads, never a touch or native update.

        All candidate actors are read again after a qualified camera sample;
        no stale actors from before a dirty-matrix interval are projected.
        """
        for attempt in range(8):
            try:
                camera = self.observer.camera_view()
            except Exception as exc:
                detail = str(exc)
                if not any(reason in detail for reason in ('camera matrices dirty/absent', 'camera changed during read')):
                    raise
                self.d.observations.setdefault('camera_read_gaps', []).append(
                    {'at':time.time(), 'attempt':attempt, 'unknown':detail})
                self.require(attempt < 7, 'SETUP', 'camera did not yield a qualified sample; no input attempted')
                time.sleep(.01)
            else:
                return camera, self.observer.actor_states(eids)

    def move(self, camera, origin, goal, *, pick_eids=None):
        # Shorten only before input if a projected point is outside the proven
        # playfield. Never retry a swallowed or rejected click.
        actors, risks = [], []
        if self.mixed_team is not None:
            self.require(pick_eids is not None and self.eid in pick_eids and len(pick_eids) <= 200,
                         'SETUP', 'native target registry missing or bound exceeded')
            native = self.observer.actor_states(pick_eids)
            self.require(not native['missing'], 'SETUP', 'mixed pick-safety actors unavailable')
            actors = native['actors']
        for length in (4.0, 2.0, 1.0):
            destination = (goal if self.mixed_team is not None and math.dist(origin, goal) <= 1e-3
                           else path_step(self.mesh, origin, goal, length))
            point, height, snapped = on_mesh_click(self.mesh, destination)
            xyz = [point[0], height, point[1]]
            try:
                xy = central_projection(camera, xyz)
            except ValueError:
                if length == 1.0:
                    raise
                continue
            risk = mixed_pick_risk(camera, point, xy, actors)
            if risk is None:
                break
            risks.append(dict(at=time.time(), **risk, input_submitted=False))
        else:
            self.d.observations.setdefault('mixed_pick_holds', []).extend(risks)
            self.last_action = time.monotonic()
            self.mixed_pick_hold_until = self.last_action+1.2
            return
        if self.mixed_team is not None:
            from Tools.protocol_policy import mixed_structure_zones
            route = self.mesh.find_path(origin, point)
            if not route and math.dist(origin, point) <= 1e-3 and self.mesh.contains(origin):
                route = [point]
            self.require(bool(route), 'SETUP', 'mixed movement route unavailable before input')
            previous, zones = origin, []
            for step in route:
                zones.extend(mixed_structure_zones(step, teams=(3-self.mixed_team,), start=previous))
                previous = step
            if zones:
                self.mixed_hold('movement route enters enemy structure zone', origin, goal, zones)
                return
        before = time.time()
        self.d.gesture('classic-move-attempt', screen_xy=xy, world_xyz=xyz, camera=camera, wall_before=before,
                       on_mesh_snap=snapped)
        self.d.adb.tap(*xy)
        self.d.stage('UI_COMMAND_SUBMITTED', 'PASS', 'ordinary projected movement submitted')
        request = self.receipt('c2s', 1012, lambda r: True, before, 'CLIENT_INPUT_OBSERVED', allow_missing=True)
        if request is None:
            picks = [r for r in self.d.tail.records if self.d._on_connection(r)
                     and r.get('direction') == 'c2s' and r.get('opcode') == 1060 and r['time'] >= before]
            if picks:
                pick = picks[0]
                self.d.observations.setdefault('move_pick_misfires', []).append(pick)
                self.require(False, 'CLIENT_INPUT_OBSERVED',
                    f'move tap consumed as native pick (1060 target {int(pick["payload"][:8], 16)})')
            self.require(False, 'CLIENT_INPUT_OBSERVED',
                         'ordinary action missing matching c2s 1012; no blind retry')
        from server.roster import MOVE_INTENT_PAYLOAD_SIZE
        ack = self.receipt('s2c', 1016, lambda r: len(r['payload']) == MOVE_INTENT_PAYLOAD_SIZE*2 and r['payload'][:2] == f'{self.slot:02x}',
                           request['time'], 'SERVER_ACKNOWLEDGED')
        self.record('move', screen_xy=xy, world_xyz=xyz, camera=camera, request=request, ack=ack)
        self.last_target = None

    def observe_pursuit_selection(self, request, actual, before, detail):
        """1060 accepts pursuit;1045 is an attack start, not a selection ACK.

        Read actual intent and native selection before a low-health target can
        die on approach. Never turn an unobserved intent into accepted coverage.
        """
        deadline = time.monotonic()+.5
        observations=[]
        while True:
            state=self.d.qa.snapshot()
            owner=self.owned(state)
            native=self.observer.selected_target()
            after=time.time()
            observations.append({'before':before,'after':after,'state':state,'native_selection':native})
            if owner['target']==actual['eid'] and native['target_eid']==actual['eid']:
                self.record('target',target=actual,request=request,native_selection=native,
                            acceptance_source='read-only authoritative target intent; not1045',
                            observations=observations,**detail)
                self.last_target=actual['eid']
                return
            self.d.tail.poll()
            deaths=[r for r in self.d.tail.records if self.d._on_connection(r)
                    and r.get('direction')=='s2c' and r.get('opcode')==1072
                    and int(r['payload'][:8],16) in (self.eid,actual['eid'])
                    and before <= r['time'] <= after]
            for death in deaths:
                proof=self.observer.actor_states([int(death['payload'][:8],16)])
                if not proof['missing'] and len(proof['actors'])==1 and proof['actors'][0]['hp']<=.01:
                    self.record('target_race',target=actual,request=request,death=death,native=proof,
                                observations=observations,acknowledged=False,
                                classification='input observed; death before intent/native agreement; acceptance unknown')
                    return
            self.require(time.monotonic()<deadline,'SERVER_ACKNOWLEDGED',
                         'target intent/native selection did not agree within bounded observation')
            time.sleep(.05)

    def target(self, camera, actor, *, eligible=None, accept_pursuit=False):
        # Exact-target diagnostic calls remain strict. The ordinary lane policy
        # may deliberately attack any currently qualified enemy under an
        # overlapping pick capsule; record the actual choice, never pretend it
        # was the originally projected actor or accept a friendly/unknown EID.
        allowed = {actor['eid']: actor} if eligible is None else eligible
        self.require(actor['eid'] in allowed, 'SETUP', 'projected target not eligible')
        xyz = list(actor['selection_center_xyz'])
        xyz[1] += actor['selection_height'] * .5
        xy = central_projection(camera, xyz)
        before = time.time()
        selected = self.observer.selected_target()
        self.d.gesture('classic-target-attempt', target=actor, screen_xy=xy, camera=camera,
                       native_selection=selected, wall_before=before,
                       eligible_eids=sorted(allowed), exact_target=eligible is None)
        self.d.adb.tap(*xy)
        self.d.stage('UI_COMMAND_SUBMITTED', 'PASS', 'ordinary projected entity selection submitted')
        request = self.receipt('c2s', 1060,
                               lambda r: len(r['payload']) == 12 and int(r['payload'][:8], 16) in allowed,
                               before, 'CLIENT_INPUT_OBSERVED')
        actual = allowed[int(request['payload'][:8], 16)]
        if accept_pursuit:
            self.require(eligible is not None,'SETUP','pursuit observation is for ordinary lane policy only')
            self.observe_pursuit_selection(request,actual,before,
                {'projected_target':actor,'screen_xy':xy,'camera':camera})
            return
        ack = self.receipt('s2c', 1045,
            lambda r: r['payload'][:16] == struct.pack('>II', self.eid, actual['eid']).hex(),
            request['time'], 'SERVER_ACKNOWLEDGED', allow_missing=eligible is not None)
        if ack is None:
            # Ordinary combat can kill a low-health target between the native
            # pick and server processing. Classify only a tightly observed
            # death race, never a generic missing acknowledgement or a pass.
            self.d.tail.poll()
            deaths = [r for r in self.d.tail.records if self.d._on_connection(r)
                      and r.get('direction') == 's2c' and r.get('opcode') == 1072
                      and r['payload'][:8] == f'{actual["eid"]:08x}'
                      and before <= r['time'] <= request['time']+.1]
            native_dead = self.observer.actor_states([actual['eid']]) if deaths else None
            self.require(deaths and native_dead and not native_dead['missing']
                         and len(native_dead['actors']) == 1 and native_dead['actors'][0]['hp'] <= .01,
                         'SERVER_ACKNOWLEDGED', 'target request unacknowledged without a qualified concurrent death')
            self.record('target_race', target=actual, request=request, death=deaths[0],
                        native=native_dead, acknowledged=False,
                        classification='input observed; target died in command window; no explicit rejection observed')
            return
        native = self.observer.selected_target()
        self.d.gesture('classic-target-receipt', request=request, ack=ack, native_selection=native)
        if eligible is not None and native['target_eid'] != actual['eid']:
            self.d.tail.poll()
            deaths = [r for r in self.d.tail.records if self.d._on_connection(r)
                      and r.get('direction') == 's2c' and r.get('opcode') == 1072
                      and int(r['payload'][:8],16) in (self.eid, actual['eid'])
                      and before <= r['time'] <= request['time']+.1]
            for death in deaths:
                dead_eid = int(death['payload'][:8],16)
                proof = self.observer.actor_states([dead_eid])
                if not proof['missing'] and len(proof['actors']) == 1 and proof['actors'][0]['hp'] <= .01:
                    self.record('target_interrupted', target=actual, request=request, ack=ack,
                                native_selection=native, death=death, native=proof,
                                classification='acknowledged selection interrupted by concurrent native/wire death')
                    return
        self.require(native['target_eid'] == actual['eid'], 'PRESENTATION', 'accepted target differs from native selection')
        self.record('target', target=actual, projected_target=actor, screen_xy=xy,
                    camera=camera, request=request, ack=ack, native_selection=native)
        self.last_target = actual['eid']

    def cast_a(self, camera, actor):
        return self.cast(camera, actor, 'A')

    def cast_death_interruption(self, before, after, *, slot, request=None):
        """Only an observed death overlapping THIS gesture can qualify this gap.

        This does not identify the exact client input-drop site and does not
        count as an accepted cast. A later/unobserved death cannot excuse it.
        """
        self.d.tail.poll()
        deaths=[r for r in self.d.tail.records if self.d._on_connection(r)
            and r.get('direction')=='s2c' and r.get('opcode')==1072
            and before<=r['time']<=after+.05 and r['payload'][:8]==f'{self.eid:08x}']
        if not deaths:
            return False
        native=self.observer.resources()
        if native['current']['hp']>.01:
            return False
        self.record('cast_interrupted',ability=slot,gesture_window=[before,after],
                    death=deaths[0],native=native,request=request,acknowledged=False,
                    classification='gesture overlaps observed native/wire death; cast unacknowledged, exact drop/rejection site unknown')
        return True

    def cast_target_interruption(self, before, after, *, slot, lock, request=None):
        """A locked target dying during release is not a completed B/C cast."""
        from server import buff_wire
        if slot not in ('B', 'C') or lock is None:
            return False
        buff = buff_wire.parse_buff_add(bytes.fromhex(lock['payload']))
        if buff.kind != 602 or buff.source_eid != self.eid:
            return False
        self.d.tail.poll()
        rows = [r for r in self.d.tail.records if self.d._on_connection(r)
                and r.get('direction') == 's2c']
        deaths = [r for r in rows if r.get('opcode') == 1072
                  and before <= r['time'] <= after+.05
                  and r['payload'][:8] == f'{buff.target_eid:08x}']
        cancels = [r for r in rows if r.get('opcode') == 1093
                   and before <= r['time'] <= after+.05
                   and buff_wire.parse_buff_cancel(bytes.fromhex(r['payload']))
                   == (buff.target_eid, buff.instance_id)]
        if not deaths or not cancels:
            return False
        native = self.observer.actor_states([buff.target_eid])
        actors = [a for a in native['actors'] if a['eid'] == buff.target_eid]
        destroyed = [r for r in rows if r.get('opcode') == 1073
                     and deaths[0]['time'] <= r['time'] <= time.time()
                     and r['payload'][:8] == f'{buff.target_eid:08x}']
        if not ((len(actors) == 1 and actors[0]['hp'] <= .01)
                or (not actors and buff.target_eid in native['missing'] and destroyed)):
            return False
        self.record('cast_interrupted', ability=slot, gesture_window=[before, after],
                    death=deaths[0], lock=lock, cancellation=cancels[0],
                    native=native, destruction=destroyed, request=request,
                    acknowledged=False,
                    classification='locked target died and lock cancelled during gesture; cast unacknowledged, exact drop/rejection site unknown')
        return True

    def cast(self, camera, actor, slot, *, lock=None):
        from Tools.scenario_client import SKYE_NATIVE_ACTIONS, ClientStageFailure
        index = ('A', 'B', 'C').index(slot)
        control = self.observer.ability_control(index)
        action = SKYE_NATIVE_ACTIONS[slot]
        self.require(control['action'] == action and control['eid'] == self.eid,
                     'SETUP', 'native Skye cast binding changed')
        xy = central_projection(camera, actor['position_xyz'])
        if slot in ('B', 'C'):
            # Requalify after control/projection reads, before the sole input.
            self.d.tail.poll()
            fresh = recent_target_lock(self.d.tail.records, self.d.connection,
                                       self.eid, actor['eid'], time.time())
            if fresh is None:
                return False  # no input; normal basic attacks may establish a later lock
            lock = fresh
        before = time.time()
        self.d.gesture('classic-cast-attempt', ability=slot, control=control,
                       screen_xy=xy, wall_before=before, lock=lock, target=actor)
        self.d.adb.swipe(*control['center'], *xy)
        after = time.time()
        request = None
        try:
            request = self.d.wait_client_input(action=action, since=before)
            ack = self.d.wait_acknowledgment(action=action, hero_eid=self.eid, since=request['time'])
        except ClientStageFailure as exc:
            if (exc.stage in ('CLIENT_INPUT_OBSERVED','SERVER_ACKNOWLEDGED')
                    and (self.cast_death_interruption(before,after,slot=slot,request=request)
                         or self.cast_target_interruption(before,after,slot=slot,
                                                          lock=lock,request=request))):
                return True  # action window consumed; NOT a counted or retried cast
            raise
        timer = self.d.wait_cooldown_tag(slot=slot, hero_eid=self.eid, since=request['time'])
        self.require(timer is not None, 'AUTHORITATIVE_EFFECT', 'accepted cast has no matching ability cooldown')
        self.record('cast', ability=slot, target=actor, control=control, screen_xy=xy,
                    request=request, ack=ack, cooldown=timer, lock=lock)
        self.ability_counts[slot] += 1
        self.cast_until = time.monotonic() + {'A': 3.2, 'B': 1.8, 'C': 3.5}[slot]
        return True

    def flask(self):
        control = self.observer.default_item_control(2000)
        # The loop's QA snapshot can precede a lethal hit while the native
        # control is being read. A dead client's ignored tap is not item use.
        native = self.observer.resources()
        if native['current']['hp'] <= .01:
            self.d.gesture('classic-flask-skip', reason='native owner already dead',
                           control=control, native=native)
            return False
        before = self.tap_control(control)
        request = self.receipt('c2s', 1096, lambda r: r['payload'] == struct.pack('>IH', 2000, 0).hex(),
                               before, 'CLIENT_INPUT_OBSERVED')
        self.record('flask', request=request, control=control)
        return True

    def recall(self):
        from server import ability_wire
        control = self.observer.recall_control()
        action = ability_wire.hero_action_variant(265, 'recall')
        before = self.tap_control(control)
        request = self.receipt('c2s',1041,
            lambda r:r['payload']==struct.pack('>IBB',0xffffffff,action,0).hex(),
            before,'CLIENT_INPUT_OBSERVED')
        ack = self.receipt('s2c',1045,
            lambda r:r['payload']==ability_wire.build_target_cast(self.eid,None,action).hex(),
            request['time'],'SERVER_ACKNOWLEDGED')
        self.last_recall_attempt = time.monotonic()
        self.pending_recall = {'request':request,'ack':ack,'deadline':self.last_recall_attempt+8}
        self.record('recall_attempt',control=control,request=request,ack=ack)

    def observe_recall(self, owner, position, native):
        """Observe the one pending ordinary recall; never submit a retry."""
        from server import buff_wire, roster
        pending = self.pending_recall
        if pending is None:
            return False
        self.d.tail.poll()
        window=[]
        for r in reversed(self.d.tail.records):
            if r['time'] < pending['request']['time']:
                break
            if self.d._on_connection(r) and r.get('direction')=='s2c':
                window.append(r)
        deaths=[r for r in window if r.get('opcode')==1072 and r['payload'][:8]==f'{self.eid:08x}']
        if deaths and not owner['alive'] and native['current']['hp']<=.01:
            self.record('recall_interrupted',classification='ordinary channel interrupted by native/wire owner death',
                        request=pending['request'],death=deaths[0])
            self.pending_recall=None
            return False
        buffs={}
        for r in reversed(window):
            if r.get('opcode')==1086:
                buff=buff_wire.parse_buff_add(bytes.fromhex(r['payload']))
                if buff.source_eid==self.eid and buff.target_eid==self.eid and buff.kind in (25,26):
                    buffs[buff.kind]=buff.instance_id
        relocations=[r for r in window if r.get('opcode')==1033 and r['payload'][:8]==f'{self.eid:08x}']
        if owner['recall_completes_at'] is None and len(relocations)==1 and not deaths:
            xyz=position['position_xyz']
            spawn=roster.HERO_SPAWNS[self.eid]
            trigger=any(r.get('opcode')==1094 and r['payload'][:16]==struct.pack('>II',self.eid,buffs.get(25,0)).hex()
                        for r in window)
            if (set(buffs)=={25,26} and trigger and math.dist((owner['x'],owner['y']),spawn)<.05
                    and math.dist((xyz[0],xyz[2]),spawn)<.1):
                self.record('recall',request=pending['request'],relocation=relocations[0],
                            duration_s=relocations[0]['time']-pending['request']['time'],
                            authoritative=owner,native_position=position,native_resources=native)
                self.pending_recall=None
                return False
        if owner['recall_completes_at'] is None and not relocations and set(buffs)=={25,26}:
            cancelled={buff_wire.parse_buff_cancel(bytes.fromhex(r['payload'])) for r in window if r.get('opcode')==1093}
            if all((self.eid,instance) in cancelled for instance in buffs.values()):
                self.record('recall_interrupted',classification='acknowledged channel cancelled; exact cause unqualified',
                            request=pending['request'],authoritative=owner,cancelled=sorted(cancelled))
                self.pending_recall=None
                return False
        self.require(time.monotonic()<pending['deadline'],'AUTHORITATIVE_EFFECT',
                     'ordinary Recall has no qualified completion/interruption; no retry')
        return True

    def mixed_hold(self, reason, origin, goal, zones):
        self.d.observations.setdefault('mixed_holds', []).append(
            {'at': time.time(), 'reason': reason, 'owner': origin, 'target': goal,
             'zones': zones, 'input_submitted': False})

    def mixed_respawn_ready(self, owner, native_hp, at):
        """Read-only settle; retained successes: >=4 alive samples, >=2.74s.

        Faster retained moves also succeeded: this is a conservative measured
        precondition, not proof that delay caused the prior unacknowledged move.
        Camera centring is checked separately on the final fresh camera read.
        """
        if not owner['alive'] or native_hp <= 0:
            if self.mixed_respawn is None:
                self.mixed_respawn = {'death_observed_at': at, 'dead_samples': 0}
            self.mixed_respawn.update(first_alive_at=None, alive_samples=0)
            self.mixed_respawn['dead_samples'] += 1
            self.last_target = None
            return False
        if self.mixed_respawn is None:
            return True
        pending = self.mixed_respawn
        if pending['first_alive_at'] is None:
            pending['first_alive_at'] = at
        pending['alive_samples'] += 1
        pending['elapsed_s'] = at-pending['first_alive_at']
        ready = pending['alive_samples'] >= 4 and pending['elapsed_s'] >= 2.74
        self.d.observations.setdefault('mixed_respawn_settles', []).append(
            {'at': at, **pending, 'stage': 'camera pending' if ready else 'waiting for alive settle',
             'input_submitted': False})
        return ready

    def mixed_respawn_camera_ready(self, camera, me):
        if self.mixed_respawn is None:
            return True
        # The eleven retained centred-camera successes project the owner to
        # (480, 246.242) at 960x540. The boot-2 failed move projected to (325.726,
        # 224.607). One pixel bounds centring, not gameplay outcome tolerance.
        central_projection(camera, me['position_xyz'])
        projected = world_to_screen(camera, me['position_xyz'])
        ready = (self.mixed_respawn['alive_samples'] >= 4 and self.mixed_respawn.get('elapsed_s', 0) >= 2.74
                 and camera.get('eid') == me['eid']
                 and math.dist(camera['owner_position_xyz'], me['position_xyz']) <= .01
                 and abs(projected[0]-480) <= 1 and abs(projected[1]-246.242) <= 1)
        self.d.observations.setdefault('mixed_respawn_settles', []).append(
            {'at': time.time(), **self.mixed_respawn, 'stage': 'settled' if ready else 'waiting for centred camera',
             'camera': camera, 'owner': me, 'owner_screen': projected, 'input_submitted': False})
        if ready:
            self.mixed_respawn = None
        return ready

    def mixed_combat_action(self, camera, me, target, *, pick_eids=None):
        """Stage at the fixed rendezvous, then use the existing ordinary pick.

        World distance alone does not prove that the actor's pick capsule is
        inside the guarded screen rectangle. This is pre-input planning only:
        target(), its receipts and every projection guard remain unchanged.
        """
        if not target.get('alive', True) or target.get('hp', 1) <= 0:
            self.last_target = None
        origin = tuple(me['position_xyz'][i] for i in (0, 2))
        goal = tuple(target['position_xyz'][i] for i in (0, 2))
        from Tools.protocol_policy import MixedRendezvous
        self.require(self.mixed_team in (1, 2), 'SETUP', 'mixed CE team not bound')
        if self.mixed_rendezvous is None:
            self.mixed_rendezvous = MixedRendezvous(self.mesh)
        rendezvous = self.mixed_rendezvous
        stage_point = rendezvous.stage_point(self.mixed_team)
        clean = (target.get('alive', True) and target.get('hp', 1) > 0
                 and rendezvous.contains(origin) and rendezvous.contains(goal))
        at = time.time()
        outcome = self.d.observations['mixed_combat']
        outcome.setdefault('rendezvous', rendezvous.evidence())
        for label, point in (('ce', origin), ('participant', goal)):
            if rendezvous.contains(point):
                outcome.setdefault('staging_times', {}).setdefault(label, at)
            team = self.mixed_team if label == 'ce' else 3-self.mixed_team
            if math.dist(point, rendezvous.stage_point(team)) <= .25:
                outcome.setdefault('stage_point_times', {}).setdefault(label, at)
        self.d.observations.setdefault('mixed_staging', []).append(dict(at=at,
            phase='engagement' if clean else 'staging', owner=origin, opponent=goal,
            target_alive=target.get('alive', True)))
        if clean:
            outcome.setdefault('engagement_started_at', at)
            if self.last_target == target['eid']:
                return
            xyz = list(target['selection_center_xyz'])
            xyz[1] += target['selection_height'] * .5
            try:
                central_projection(camera, xyz)
            except ValueError as exc:
                if str(exc) != 'projected point outside qualified central playfield':
                    raise
                self.d.observations.setdefault('mixed_target_deferrals', []).append(
                    {'at': time.time(), 'reason': str(exc), 'camera': camera,
                     'owner': me, 'target': target, 'input_submitted': False})
            else:
                self.target(camera, target)
                self.d.observations['mixed_combat']['classification'] = 'accepted; reciprocal CE-native effects pending'
                return
        if (not clean and rendezvous.contains(origin)
                and math.dist(origin, stage_point) < PICK_CLEARANCE_WORLD and self.last_target is None):
            return  # Already staged, not a hold caused by the opponent's route.
        if ((self.last_target is not None or time.monotonic()-self.last_action >= 1.2)
                and time.monotonic() >= getattr(self, 'mixed_pick_hold_until', 0)):
            # No opponent-position holds during staging and no target pursuit
            # outside the disk. Pick holds retain the ordinary action pacing.
            rendezvous.route(origin, self.mixed_team)
            self.move(camera, origin, stage_point, pick_eids=pick_eids)

    def run_mixed(self):
        """Opt-in bounded reciprocal exercise through the existing classic path."""
        from collections import deque
        from Tools.scenario_client import ANDROID_PACKAGE, TraceTail
        from Tools.Teardown.observe_client_movement import ClientMovementObserver
        from Tools.protocol_participants import bounded_seconds
        from server import navigation
        plan = self.plan['mixed_combat']
        limit = bounded_seconds(plan.get('duration_s', 90))
        self.require(limit >= 60, 'SETUP', 'mixed gameplay requires at least60 seconds')
        self.require(self.plan['capture_backend'] == 'none' and not self.plan['drive_entry'],
                     'SETUP', 'mixed exercise forbids legacy entry/capture')
        barriers = [r for r in self.d.observations.get('nonvisual_entry', [])
                    if r['stage'] == 'MIXED_DRAFT_READY']
        releases = [r for r in self.d.observations.get('nonvisual_entry', [])
                    if r['stage'] == 'MIXED_WORLD_RELEASE']
        self.require(len(barriers) == len(releases) == 1, 'SETUP', 'mixed exercise needs qualified entry barriers')
        assignments = barriers[0]['receipt']['assignments']
        opponent = assignments[plan['opponent_identity']]
        binding = self.d.observations['entry_binding']['world']
        self.eid, self.slot, _ = self.d._qualify_nonvisual_world(self.plan)
        self.require(opponent['team'] != binding['team'] and opponent['eid'] != self.eid,
                     'SETUP', 'mixed opponent must be an observed enemy hero')
        foe = opponent['eid']
        self.mixed_team = binding['team']
        participant_binding = {**opponent, 'identity': plan['opponent_identity'], 'match_id': binding['match_id']}
        session = self.d.setup()
        initial = session['snapshot']
        self.mesh = navigation.load_halcyon_navmesh()
        from Tools.protocol_policy import MixedRendezvous
        self.mixed_rendezvous = MixedRendezvous(self.mesh)
        self.observer = ClientMovementObserver(self.d.adb, self.d.out_dir/'mixed-native.jsonl',
                                               self.eid, period_ms=50, model_transform=True)
        peer = TraceTail(plan['participant_log'])
        path = self.d.out_dir/'mixed-native-samples.jsonl'
        receipts_path = self.d.out_dir/'mixed-receipt-windows.jsonl'
        outcome = {'assignments': assignments, 'ce_identity': binding, 'reciprocal': {}, 'reconnect': None,
                   'classification': 'missing input',
                   'started_at': time.time(), 'scope': 'bounded mixed exercise; not full match or independent fidelity'}
        self.d.observations['mixed_combat'] = outcome
        recent, samples = deque(maxlen=12), []
        seen_tick, progressed_at = initial['tick'], time.monotonic()
        original_adb, bridge = self.d.adb, None
        try:
            if self.plan.get('input_bridge_dex'):
                from Tools.input_bridge import InputBridge
                bridge = InputBridge(original_adb, self.plan['input_bridge_dex'], self.d.out_dir/'ordinary-input.jsonl')
                self.d.adb = bridge.start()
            self.d.observations['mixed_runtime'] = self.observer.start()
            self.d._guard_nonvisual_movement_ui(self.observer, dismiss_build=True, state_reader=self.fresh_ui_state)
            self.d._lock_nonvisual_camera(self.observer)
            deadline = time.monotonic()+limit
            with path.open('x', encoding='utf-8') as log, receipts_path.open('x', encoding='utf-8') as receipt_log:
                while time.monotonic() < deadline:
                    self.require(not self.observer.errors, 'TRIAL_CONTINUITY', repr(self.observer.errors))
                    self.require(self.d._foreground_package() == ANDROID_PACKAGE, 'SETUP', 'owned game lost foreground')
                    state = self.d.qa.snapshot()
                    owner = self.owned(state)
                    self.require(state['phase'] == 'world' and state['match_id'] == binding['match_id']
                                 and state['tick'] >= seen_tick, 'TRIAL_CONTINUITY', 'mixed WORLD changed/regressed')
                    if state['tick'] > seen_tick:
                        seen_tick, progressed_at = state['tick'], time.monotonic()
                    self.require(time.monotonic()-progressed_at < 5, 'TRIAL_CONTINUITY', 'mixed server ticks stalled')
                    start = time.time()
                    resources = self.observer.resources()
                    resources_end = time.time()
                    actors_start = time.time()
                    actors = self.observer.actor_states([self.eid, foe])
                    actors_end = time.time()
                    self.require(resources['eid'] == self.eid and not actors['missing'],
                                 'TRIAL_CONTINUITY', 'native owner/opponent accessor unavailable')
                    normalized = {a['eid']: {**a, 'host_before': actors_start, 'host_after': actors_end}
                                  for a in actors['actors']}
                    normalized[self.eid].update(**{k: resources['current'][k] for k in ('hp', 'barrier', 'fortified')},
                                                max_hp=resources['max_hp'], host_before=start, host_after=resources_end)
                    self.d.tail.poll()
                    peer.poll()
                    received = [r for r in self.d.tail.records if self.d._on_connection(r) and r.get('direction') == 's2c']
                    self.require(received and time.time()-received[-1]['time'] < 5,
                                 'TRIAL_CONTINUITY', 'CE stopped receiving')
                    self.require(not any(r.get('connection') == self.d.connection and r.get('direction') == 'disconnect'
                                         for r in self.d.tail.records), 'TRIAL_CONTINUITY', 'CE connection disconnected')
                    row = {'at': actors_end, 'tick': state['tick'], 'actors': normalized,
                           'resources': resources, 'native_actors': actors, 'state': state,
                           'ce_last_received': received[-1]['time'], 'connection': self.d.connection}
                    log.write(json.dumps(row, allow_nan=False)+'\n')
                    log.flush()
                    samples.append({'at': row['at'], 'tick': row['tick'], 'connection': self.d.connection,
                                    'ce_last_received': row['ce_last_received'], 'hp': resources['current']['hp']})
                    for previous in reversed(recent):
                        for label, source, victim in (('participant_to_ce', foe, self.eid), ('ce_to_participant', self.eid, foe)):
                            measured = native_damage_window(previous, row, self.d.tail.records,
                                connection=self.d.connection, source=source, victim=victim,
                                participant_records=peer.records, participant_binding=participant_binding,
                                require_basic_input=(source == self.eid))
                            receipt_log.write(json.dumps({'label': label, 'before_at': previous['at'],
                                'after_at': row['at'], **measured}, allow_nan=False)+'\n')
                            if measured['classification'] == 'authoritative outcome + measured CE-native effect':
                                retained = outcome['reciprocal'].setdefault(label, [])
                                if not retained or measured['damage'][-1]['time'] > retained[-1]['damage'][-1]['time']:
                                    retained.append(measured)
                            elif measured['damage']:
                                outcome.setdefault('last_unverified', {})[label] = measured
                    receipt_log.flush()
                    recent.append(row)
                    # Same ordinary native HUD, camera/projection and input receipts
                    # as classic-match; no QA mutation or ability damage substitutes.
                    self.d._guard_nonvisual_movement_ui(self.observer, state_reader=self.fresh_ui_state)
                    settled = self.mixed_respawn_ready(owner, resources['current']['hp'], row['at'])
                    if not settled or any(s['type'] in ('STUN', 'SUPPRESSION', 'ROOT') for s in owner['statuses']):
                        self.last_target = None
                        time.sleep(.2)
                        continue
                    camera, fresh = self.fresh_camera_actors([self.eid, foe])
                    mapped = {a['eid']: a for a in fresh['actors']}
                    self.require(not fresh['missing'], 'SETUP', 'fresh mixed target actors missing')
                    me, target = mapped[self.eid], mapped[foe]
                    # Native HP may retain a tiny residual on a dead actor (4q).
                    # Authoritative lifecycle can veto a pick, never prove its
                    # native effect. Keep the existing native receipt acceptance.
                    target['alive'] = next(h['alive'] for h in state['heroes'] if h['eid'] == foe)
                    if me['hp'] <= 0:
                        self.last_target = None
                        time.sleep(.2)
                        continue
                    if not self.mixed_respawn_camera_ready(camera, me):
                        time.sleep(.2)
                        continue
                    pick_eids = sorted({r['eid'] for r in state['heroes']+state['nearby_creatures']
                        if r['alive']})
                    self.mixed_combat_action(camera, me, target, pick_eids=pick_eids)
                    time.sleep(.2)
            outcome['ended_at'] = time.time()
            outcome['samples'] = samples
            identities = [r for r in self.d.tail.records if r.get('direction') == 'identity'
                          and r.get('identity') == plan['opponent_identity'] and r.get('match_id') == binding['match_id']]
            self.require(len(identities) == 2 and identities[0]['connection'] != identities[1]['connection']
                         and all(all(r[k] == opponent[k] for k in ('eid', 'slot', 'team')) for r in identities),
                         'TRIAL_CONTINUITY', 'same-identity Ringo reconnect not proven on a new connection')
            at = identities[1]['time']
            prior = [r for r in samples if r['at'] < at]
            later = [r for r in samples if r['at'] > at]
            self.require(prior and later and later[0]['tick'] > prior[-1]['tick']
                         and later[0]['ce_last_received'] > prior[-1]['ce_last_received']
                         and prior[-1]['hp'] > 0 and later[0]['hp'] > 0,
                         'TRIAL_CONTINUITY', 'CE live native/tick/receive continuity across reconnect unverified')
            outcome['reconnect'] = {'identities': identities, 'ce_before': prior[-1], 'ce_after': later[0]}
            self.require(all(outcome['reciprocal'].get(k) for k in ('participant_to_ce', 'ce_to_participant')),
                         'PRESENTATION', 'reciprocal source-bound CE-native HP drops not both measured')
            self.require(any(r['damage'][0]['time'] > at for effects in outcome['reciprocal'].values() for r in effects),
                         'PRESENTATION', 'no resumed native effect involving Ringo after reconnect')
            outcome['classification'] = 'authoritative outcome + measured CE-native effect'
            for stage in ('UI_COMMAND_SUBMITTED', 'CLIENT_INPUT_OBSERVED', 'SERVER_ACKNOWLEDGED',
                          'AUTHORITATIVE_EFFECT', 'PRESENTATION', 'TRIAL_CONTINUITY'):
                self.d.stage(stage, 'PASS', 'bounded reciprocal mixed native/wire exercise')
        finally:
            outcome['samples'] = samples
            self.d.observations['mixed_runtime'] = self.observer.stop()
            self.d.artifact(path)
            self.d.artifact(receipts_path)
            self.d.artifact(self.observer.output)
            if bridge is not None:
                bridge.close()
            self.d.adb = original_adb
        return self.d.finish('PASS', observed=outcome, expected={'official_fidelity': 'UNVERIFIED', 'full_match': False})

    def run(self):
        if self.plan.get('mixed_combat') is not None:
            return self.run_mixed()
        from Tools.scenario_client import ANDROID_PACKAGE
        from Tools.Teardown.observe_client_movement import ClientMovementObserver
        from server import navigation, roster
        self.require(self.plan['capture_backend'] == 'none' and not self.plan['drive_entry'],
                     'SETUP', 'Classic exercise forbids image/video and legacy entry')
        limit = self.plan['max_duration_s']
        self.require(type(limit) in (int, float) and 30 <= limit <= 2400,
                     'SETUP', 'Classic duration must be bounded to30..2400 seconds')
        self.require(isinstance(self.plan['abilities'], list) and self.plan['abilities']
                     and all(isinstance(name, str) for name in self.plan['abilities'])
                     and len(set(self.plan['abilities'])) == len(self.plan['abilities'])
                     and set(self.plan['abilities']) <= {'A', 'B', 'C'},
                     'SETUP', 'Classic abilities must be a nonempty unique subset of A/B/C')
        self.require(type(self.plan['require_recall']) is bool,'SETUP','require_recall must be boolean')
        self.eid, slot, _ = self.d._qualify_nonvisual_world(self.plan)
        self.slot = slot
        session = self.d.setup()
        initial = session['snapshot']
        self.fresh_start = initial['time'] <= min(75, self.plan['max_entry_sim_time_s'])
        self.d.observations['fresh_start'] = self.fresh_start
        self.require(type(self.plan['require_fresh_start']) is bool and
                     (self.fresh_start or not self.plan['require_fresh_start']),
                     'SETUP', 'not a fresh match; cannot label a late join full-match exercise')
        self.mesh = navigation.load_halcyon_navmesh()
        self.observer = ClientMovementObserver(self.d.adb, self.d.out_dir/'client-movement.jsonl',
                                               self.eid, period_ms=50, model_transform=True)
        self.d.observations['wire_identity'] = {'eid': self.eid, 'slot': slot, 'connection': self.d.connection}
        self.d.observations['classic_scope'] = 'ordinary lane policy; read-only QA; no forced gameplay state'
        self.d.observations['classic_counts'] = self.counts
        self.d.observations['classic_ability_counts'] = self.ability_counts
        sample_path = self.d.out_dir/'classic-state.jsonl'
        start = time.time()
        deadline = time.monotonic()+limit
        seen_tick = initial['tick']
        last_progress = time.monotonic()
        observed_end = None
        end_wait_started = None
        trace_index = len(self.d.tail.records)
        original_adb, bridge = self.d.adb, None
        try:
            if self.plan.get('input_bridge_dex'):
                from Tools.input_bridge import InputBridge
                bridge = InputBridge(original_adb, self.plan['input_bridge_dex'],
                                     self.d.out_dir/'ordinary-input.jsonl')
                self.d.adb = bridge.start()
                self.d.observations['input_transport'] = 'persistent device /system/bin/input class; ordinary Android events'
            self.d.observations['client_runtime'] = self.observer.start()
            self.d._guard_nonvisual_movement_ui(self.observer, state_reader=self.fresh_ui_state)
            self.d._lock_nonvisual_camera(self.observer)
            initial_structures = self.observer.actor_states([s['eid'] for s in initial['structures']])
            self.d.observations['initial_native_structures'] = initial_structures
            self.require(not initial_structures['missing'] and
                         all(s['barrier'] == 0 and s['fortified'] == 0 for s in initial_structures['actors']),
                         'SETUP', 'unmodeled native structure resource pool before ordinary gameplay')
            with sample_path.open('x', encoding='utf-8') as journal:
                while time.monotonic() < deadline:
                    before = time.time()
                    self.require(not self.observer.errors, 'TRIAL_CONTINUITY', repr(self.observer.errors))
                    self.require(self.d._foreground_package() == ANDROID_PACKAGE,
                                 'SETUP', 'owned game lost foreground; no input')
                    state = self.d.qa.snapshot()
                    owner = self.owned(state)
                    self.require(state['match_id'] == initial['match_id'] and state['phase'] == 'world'
                                 and state['tick'] >= seen_tick, 'TRIAL_CONTINUITY', 'world changed/regressed')
                    if state['tick'] > seen_tick:
                        seen_tick, last_progress = state['tick'], time.monotonic()
                    self.require(time.monotonic()-last_progress < 5, 'TRIAL_CONTINUITY', 'server ticks stalled')
                    native = self.observer.resources()
                    position = self.observer.snapshot()
                    ui = self.fresh_ui_state()
                    row = {'host_before': before, 'host_after': time.time(), 'state': state,
                           'native': native, 'position': position, 'labels': ui['labels'],
                           'native_selection': self.observer.selected_target()}
                    journal.write(json.dumps(row, separators=(',', ':'))+'\n')
                    journal.flush()
                    self.samples += 1
                    self.d.tail.poll()
                    for r in self.d.tail.records[trace_index:]:
                        if self.d._on_connection(r) and r.get('direction') == 's2c' and r.get('opcode') == 1054:
                            victim, source, amount = struct.unpack_from('>IIf', bytes.fromhex(r['payload']))
                            if source == self.eid and victim != self.eid and amount < 0:
                                self.owner_damage -= amount
                    trace_index = len(self.d.tail.records)
                    if state['match_finished']:
                        if end_wait_started is None:
                            end_wait_started = time.monotonic()
                        wanted = 'Victory' if state['winner_team'] == owner['team'] else 'Defeat'
                        if wanted in ui['labels'] and 'FINISH' in ui['labels']:
                            observed_end = row
                            break
                        self.require(time.monotonic()-end_wait_started < 45,
                                     'PRESENTATION', 'server ended but native result UI not observed')
                        time.sleep(.5)
                        continue
                    if self.observe_recall(owner,position,native):
                        self.no_action_since=time.monotonic()
                        time.sleep(.2)
                        continue
                    if (not owner['alive'] or any(s['type'] in ('STUN', 'SUPPRESSION', 'ROOT') for s in owner['statuses'])
                            or time.monotonic() < self.cast_until):
                        self.no_action_since = time.monotonic()
                        time.sleep(.5)
                        continue
                    self.d._guard_nonvisual_movement_ui(self.observer, state_reader=self.fresh_ui_state)
                    if owner['recall_completes_at'] is not None:
                        time.sleep(.5)
                        continue
                    upgrade = next_upgrade(owner)
                    if upgrade is not None:
                        self.upgrade(owner, upgrade)
                        continue
                    origin = (position['position_xyz'][0], position['position_xyz'][2])
                    at_base = math.dist(origin, roster.HERO_SPAWNS[self.eid]) < 5
                    if at_base and self.purchase(owner):
                        continue
                    if at_base and (native['current']['hp'] < native['max_hp']*.9
                                    or native['current']['energy'] < native['max_energy']*.7):
                        time.sleep(.5)
                        continue
                    flask = next((i for i in owner['default_items'] if i['item'] == 457), None)
                    if flask and flask['remaining'] == 0 and owner['hp']/owner['max_hp'] < .55:
                        self.flask()
                        time.sleep(.5)
                        continue
                    enemies = [r for r in state['heroes']+state['nearby_creatures']
                        if r['alive'] and r['team'] not in (0, owner['team'])]
                    if (not at_base and self.plan['require_recall'] and time.monotonic()-self.last_recall_attempt>30
                            # One planned ordinary Recall qualifies the declared
                            # scenario coverage before repeated combat deaths
                            # can consume every later opportunity.
                            and recall_needed(owner, self.counts['recall'])
                            and not any(math.dist(origin,(r['x'],r['y']))<10 for r in enemies)):
                        self.recall()
                        continue
                    targets = [r for r in enemies if math.dist(origin,(r['x'],r['y'])) <= 8]
                    objectives = vulnerable_structures(state, owner['team'])
                    targets += [r for r in objectives if math.dist(origin, (r['x'], r['y'])) <= 9]
                    targets = sorted({r['eid']: r for r in targets}.values(),
                                     key=lambda r: (r['eid'] != owner['target'], math.dist(origin, (r['x'], r['y'])), r['eid']))[:40]
                    # Selection capsules can overlap a projected minion with
                    # a hero outside the policy's8-unit search radius. Read
                    # all known living enemies for actual-pick qualification;
                    # the radius chooses an aim, not the identity of a pick.
                    eligible_eids=sorted({r['eid'] for r in enemies+objectives})
                    self.require(len(eligible_eids)<=200,'SETUP','native target registry bound exceeded')
                    camera, actors = self.fresh_camera_actors(eligible_eids)
                    native_by_id = {a['eid']: a for a in actors['actors']}
                    target = None
                    for candidate in targets:
                        actor = native_by_id.get(candidate['eid'])
                        if actor is None or actor['hp'] <= .01:
                            continue
                        xyz = list(actor['selection_center_xyz'])
                        xyz[1] += actor['selection_height']*.5
                        try:
                            central_projection(camera, xyz)
                        except ValueError:
                            continue
                        target = actor
                        break
                    if target is not None:
                        self.no_action_since = time.monotonic()  # autoattack may own several seconds
                        if owner['target'] != target['eid']:
                            self.target(camera, target, eligible={a['eid']: a for a in actors['actors'] if a['hp'] > .01},
                                        accept_pursuit=True)
                        elif (owner['energy'] >= 100 and target['eid'] not in {r['eid'] for r in state['structures']}
                              and math.dist(origin, (target['position_xyz'][0], target['position_xyz'][2])) < 6):
                            lock = recent_target_lock(self.d.tail.records, self.d.connection,
                                                      self.eid, target['eid'], time.time())
                            for spell in sorted(self.plan['abilities'], key=lambda name:self.ability_counts[name]):
                                index = str(('A','B','C').index(spell))
                                if (owner['ranks'].get(index, 0) and owner['ability_cooldowns'].get(index, 0) == 0
                                        and (spell == 'A' or lock is not None)):
                                    if self.cast(camera, target, spell, lock=lock):
                                        break
                        time.sleep(.5)
                        continue
                    if time.monotonic()-self.last_action >= 1.2:
                        # Approach the enemy outer structure along the lane;
                        # after it falls, advance to the next actual objective.
                        self.require(objectives, 'AUTHORITATIVE_EFFECT', 'no enemy objective before match end')
                        objective = min(objectives, key=lambda r: math.dist(origin, (r['x'], r['y'])))
                        goal = lane_goal(origin, objective, owner['team'])
                        self.move(camera, origin, goal)
                    self.require(time.monotonic()-self.no_action_since < 20,
                                 'AUTHORITATIVE_EFFECT', 'lane policy made no observable progress')
                    time.sleep(.5)
            self.d.observations['classic_outcome'] = {'counts': self.counts, 'owner_damage': self.owner_damage,
                'samples': self.samples, 'end': observed_end, 'started_wall': start, 'ended_wall': time.time()}
            self.require(observed_end is not None, 'AUTHORITATIVE_EFFECT', 'bounded match exercise did not reach native result screen')
            self.require(all(self.counts[k] for k in ('move', 'target', 'upgrade', 'purchase', 'cast')) and self.owner_damage > 0,
                         'AUTHORITATIVE_EFFECT', 'match ended without the required ordinary gameplay coverage')
            self.require(all(self.ability_counts[slot] for slot in self.plan['abilities']),
                         'AUTHORITATIVE_EFFECT', 'match ended without all declared ordinary ability casts')
            self.require(not self.plan['require_recall'] or self.counts['recall']>0,
                         'AUTHORITATIVE_EFFECT','match ended without a qualified ordinary Recall completion')
            end_state = observed_end['state']
            native_structures = self.observer.actor_states([s['eid'] for s in end_state['structures']])
            self.d.observations['final_native_structures'] = native_structures
            mapped = {s['eid']: s for s in native_structures['actors']}
            self.require(not native_structures['missing'] and all(abs(mapped[s['eid']]['hp']-s['hp']) < .1
                         for s in end_state['structures']), 'PRESENTATION', 'native/server final structure HP disagrees')
            end_owner = self.owned(end_state)
            self.require(all(observed_end['native']['score'][k] == end_owner['score'][k]
                             for k in ('kills', 'deaths', 'farm')), 'PRESENTATION', 'native K/D/farm counters disagree')
            diagnostics = self.d.qa.submit({'command': 'diagnostics'}, label='classic-end-diagnostics')
            receipt = diagnostics.get('result') or {}
            self.d.observations['classic_end_diagnostics'] = receipt
            self.require(diagnostics.get('ok') and self.d._diag_linkage is not None and
                         all(receipt.get(k) == self.d._diag_linkage[k] for k in ('pid', 'startup_at', 'match_id'))
                         and receipt.get('match_finished') is True and receipt.get('tick', 0) >= end_state['tick'],
                         'TRIAL_CONTINUITY', 'completed match process/session linkage unavailable or changed')
            for stage in ('UI_COMMAND_SUBMITTED', 'CLIENT_INPUT_OBSERVED', 'SERVER_ACKNOWLEDGED',
                          'AUTHORITATIVE_EFFECT', 'PRESENTATION', 'TRIAL_CONTINUITY'):
                self.d.stage(stage, 'PASS', 'ordinary match lifecycle with retained native/wire evidence; not official parity')
        finally:
            try:
                self.d.observations['client_runtime'] = self.observer.stop()
                self.d.artifact(sample_path)
                self.d.artifact(self.observer.output)
                self.d.artifact(self.observer.output.with_suffix('.metadata.json'))
            finally:
                if bridge is not None:
                    bridge.close()
                    self.d.artifact(bridge.output)
                    self.d.artifact(bridge.output.with_suffix('.stderr.log'))
                self.d.adb = original_adb
        self.require(not self.observer.errors, 'TRIAL_CONTINUITY', 'native observer failed at teardown')
        return self.d.finish('PASS', observed=self.d.observations['classic_outcome'], expected={
            'ordinary_completed_match': self.fresh_start, 'official_parity': 'UNVERIFIED',
            'general_smoothness': 'UNVERIFIED', 'zero_bugs': 'NOT_CLAIMED'})

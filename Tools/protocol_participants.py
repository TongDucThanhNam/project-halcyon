"""Ordinary wire participants against an operator-owned Halcyon server.

No client rendering, privileged gameplay controls, simulation stepping or replay
claims. All observations come from each participant's decoded s2c stream.

Mixed mode uses an existing platform gateway, never protocol_host. --mixed-roster
is JSON with real_clients [{identity, hero, slot, eid, team}] and participants
[{identity, hero, opponent}]. Exactly six distinct heroes/identities are declared;
one or two real slots are reserved. --admission-wire is the fresh server JSONL
trace, scoped by --not-before and --match-id. No participant connects until a
1113 on each identity-bound real connection proves its selection.

The CE driver MUST hold ordinary LOCK IN until mixed-draft-ready.json exists.
That receipt proves all six selections, not WORLD. After native QUALIFIED_WORLD,
the driver atomically creates the previously absent --world-release JSON:
{match_id, qualified_at, clients:[{identity, connection, eid, slot, team,
hero_id, qualified_world:true}]}. Every real client is required. qualified_at is
host epoch time after finalization. This explicit native-driver signal (not a
participant's own 1011/1137) releases gameplay. No native acceptance is claimed
by this runner; Phase 3 must correlate CE-native effects separately.
"""
from __future__ import annotations

import argparse
from collections import deque
import copy
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import select
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Tools.verification_support import output_directory, reject_link_traversal
from Tools.protocol_observer import Observer
from server import ability_wire, cooldown_wire, hero_catalog, roster, wire

MATCH_ID = "00000000-1111-4222-8333-444455556666"
HEROES = ("Skye", "Ringo", "Catherine", "Gwen", "Adagio", "Amael")
# Additional selections are only the measured bot-sequence bisection, not kit
# qualification. Declarations must explicitly name replacements; never silently
# substitute a hero or synthesize a hash from the 1107 catalog's name strings.
MIXED_HEROES = frozenset(HEROES) | {
    hero_catalog.resolve_hero_name(hero_id) for hero_id, _ in roster.BOT_HERO_CHOICES}
SLOTS = (0, 3, 1, 4, 2, 5)
EIDS = (1500, 1517, 1515, 1518, 1516, 1519)
# One rank-one native action, not a complete kit qualification.
SKILLS = {"Skye": (0, 40), "Ringo": (1, 40), "Catherine": (0, 30),
          "Gwen": (1, 60), "Adagio": (1, 105), "Amael": (0, 40)}
STAGES = ("join", "select", "lock", "ready", "learn", "cast", "move",
          "attack", "purchase", "recall", "reconnect")
OBSERVED = "authoritative outcome observed"
PRIVATE = tuple(ipaddress.ip_network(n) for n in
                ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class StageFailure(RuntimeError):
    pass


def selection_hashes(hero_id):
    """Measured (1118 selection, 1119 commit, provenance), never a zero guess.

    Bot pairs: server/roster.py BOT_HERO_CHOICES, corpus countdown/1011.
    Skye: retained ordinary CE B wire, run-1791763148710-3e93d183/phase-b,
    lines312/320 (indexed by run-1791767114575-ac79e405/B-frames.json).
    Catherine: retained ordinary CE gateway_log.txt lines38231/38234,
    wire-1789922117332526700; selection then commit, followed by1134/1137.
    Amael: corpus 1118/1119 pair in server/test/test_roster.py and
    Docs/Teardown/vainglory-protocol-wire.md, roster/join-completion decode.
    Selection and commit may differ; neither is a catalog index or credential.
    """
    measured = {
        265: (0xF59CDB08, 0xD063A8B6, 'ordinary CE B wire lines312/320; run-1791763148710-3e93d183/phase-b'),
        242: (0x62DBDC96, 0xC3C86A12, 'ordinary CE gateway_log.txt lines38231/38234; wire-1789922117332526700'),
        925: (0x2FD7245D, 0x4260123E, 'ordinary CE corpus 1118/1119; test_roster.py and protocol-wire roster decode'),
    }
    measured.update({hid: (value, value, 'server/roster.py BOT_HERO_CHOICES; corpus countdown/1011')
                     for hid, value in roster.BOT_HERO_CHOICES})
    if hero_id not in measured:
        raise StageFailure(f'no evidenced selection/commit hash for hero {hero_id}; '
                           'declare the bot-sequence hero for that slot instead')
    return measured[hero_id]


def draft_payloads(participants):
    """Resolve every hash before any socket opens; retain provenance per hero."""
    payloads = {}
    for p in participants:
        selected, committed, source = selection_hashes(p.hero_id)
        p.hash_evidence = {'selection_hash': f'{selected:08x}', 'commit_hash': f'{committed:08x}',
                           'source': source}
        payloads[p.identity] = (struct.pack('>II', p.hero_id, selected)+bytes(6),
                               struct.pack('>I', committed)+bytes(2))
    return payloads


def private_host(host: str) -> str:
    """Resolve once and pin an address; do not allow DNS rebinding/public peers."""
    addresses = {row[4][0] for row in socket.getaddrinfo(host, None, socket.AF_INET)}
    if not addresses:
        raise ValueError("host has no IPv4 address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not (ip.is_loopback or any(ip in network for network in PRIVATE)):
            raise ValueError(f"refusing non-loopback/non-RFC1918 host: {address}")
    return sorted(addresses)[0]


def new_output(explicit=None) -> Path:
    path = explicit or ROOT / "Local/evidence" / f"protocol-participants-{uuid.uuid4().hex}"
    if (ROOT / "Local/evidence").resolve() not in Path(path).resolve().parents:
        raise ValueError("participant evidence must be a new directory under Local/evidence")
    return output_directory(path, allow_existing_empty=False)


def source_identity():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    names = set(tracked) | {str(p.relative_to(ROOT)).replace('\\', '/')
                            for pattern in ('Tools/protocol_*.py', 'server/test/test_protocol_*.py')
                            for p in ROOT.glob(pattern)}
    manifest = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in sorted(names) if name and (ROOT / name).is_file()}
    encoded = json.dumps(manifest, sort_keys=True).encode()
    return {"manifest": manifest, "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
            "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "dirty_files": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True).splitlines()}


def u32(payload, offset=0):
    return struct.unpack_from(">I", payload, offset)[0]


def bounded_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 < seconds <= 600:
        raise ValueError('wait/duration must be finite and in (0, 600] seconds')
    return seconds


def require_default_allocation():
    if os.environ.get('HALCYON_TEAM_ALLOCATION', '') not in ('', 'default'):
        raise StageFailure('mixed mode requires default HALCYON_TEAM_ALLOCATION, not coop')


def mixed_roster(declaration):
    """Validate declarations before opening any participant socket."""
    require_default_allocation()
    plan = copy.deepcopy(declaration)
    real, bots = plan['real_clients'], plan['participants']
    if len(real) not in (1, 2) or len(bots) != 6-len(real):
        raise ValueError('mixed mode requires one/two real clients and five/four participants')
    identities, heroes, slots = set(), set(), set()
    for row in real + bots:
        identity = row['identity']
        if (not isinstance(identity, str) or not identity.isascii() or not 1 <= len(identity) < 64
                or any(ord(c) < 33 or ord(c) > 126 for c in identity)
                or identity == roster.BOT_UUID_SENTINEL or identity in identities):
            raise ValueError('mixed identities must be distinct nonempty ASCII roster identities')
        # Canonical names keep policy/actions and one wire log per hero unambiguous.
        if row['hero'] not in MIXED_HEROES:
            raise ValueError('mixed declared hero must be in the declared composition or measured bot sequence')
        row['hero_id'] = hero_catalog.resolve_hero_id(row['hero'])
        if row['hero_id'] in heroes:
            raise ValueError('duplicate/reserved real-client hero selection')
        identities.add(identity)
        heroes.add(row['hero_id'])
    for row in real:
        slot = row['slot']
        if type(slot) is not int or slot not in range(6) or slot in slots:
            raise ValueError('real-client slots must be distinct valid reservations')
        if (type(row['eid']) is not int or type(row['team']) is not int
                or (row['eid'], row['team']) != (dict(zip(SLOTS, EIDS))[slot], 1 if slot < 3 else 2)):
            raise ValueError('reserved EID/team disagree with the wire slot layout')
        slots.add(slot)
    for row in bots:
        if row['opponent'] not in identities-{row['identity']}:
            raise ValueError('each participant needs a declared opponent identity')
    if not any(p['opponent'] in {r['identity'] for r in real} for p in bots):
        raise ValueError('at least one participant must target a real client')
    return plan


def selections(payload):
    """Decode the six occupied 1113 records, not arrival-order guesses."""
    if len(payload) != roster.SNAPSHOT_PAYLOAD_SIZE:
        raise StageFailure('invalid 1113 payload length')
    rows = []
    for slot in range(6):
        p = payload[8+slot*161:8+(slot+1)*161]
        if p[0] != 1 or p[1] != slot:
            raise StageFailure('invalid occupied 1113 slot')
        rows.append({'identity': p[97:161].split(b'\0', 1)[0].decode('ascii'),
                     'slot': p[1], 'team': p[8], 'hero_id': struct.unpack_from('>H', p, 9)[0],
                     'eid': struct.unpack_from('>H', p, 11)[0],
                     'flags': struct.unpack_from('>H', p, 2)[0]})
    return rows


def verify_selections(plan, rows, *, all_six=False, unlocked=False):
    expected = plan['real_clients'] + (plan['participants'] if all_six else [])
    if all_six and {r['identity'] for r in rows} != {r['identity'] for r in expected}:
        raise StageFailure('six selections contain an undeclared/missing identity or bot')
    assignments = {}
    for declaration in expected:
        matches = [r for r in rows if r['identity'] == declaration['identity']]
        if len(matches) != 1:
            raise StageFailure('missing/ambiguous declared identity in 1113')
        row = matches[0]
        if row['hero_id'] == 0xffff:
            raise StageFailure('unselected human slot (0xffff); no lock allowed')
        if (hero_catalog.resolve_hero_id(row['hero_id']) != declaration['hero_id']
                or (row['eid'], row['team']) != (dict(zip(SLOTS, EIDS))[row['slot']], 1 if row['slot'] < 3 else 2)):
            raise StageFailure('1113 hero/EID/team differs from declared composition or slot layout')
        if declaration in plan['real_clients'] and any(row[k] != declaration[k] for k in ('slot', 'eid', 'team')):
            raise StageFailure('real-client reserved slot/EID/team mismatch')
        if unlocked and row['flags'] != roster.PICK_FLAG_SELECTED:
            raise StageFailure('human locked before all six selections were verified')
        if row['flags'] not in (roster.PICK_FLAG_SELECTED, roster.PICK_FLAG_LOCKED):
            raise StageFailure('human selection flags invalid; no lock allowed')
        assignments[row['identity']] = row
    if all_six:
        for row in plan['participants']:
            if assignments[row['identity']]['team'] == assignments[row['opponent']]['team']:
                raise StageFailure('declared opponent is not on the opposing observed team')
    return assignments


class MixedEntry:
    """Evidence barriers for a single, fresh existing-gateway mixed match."""
    def __init__(self, plan, match_id, trace, not_before, release, output, *,
                 admission_timeout=120, finalization_timeout=180, world_timeout=180):
        self.plan = mixed_roster(plan)
        self.match_id, self.trace = match_id, Path(trace)
        self.release, self.output = Path(release), Path(output)
        self.not_before = float(not_before)
        if not math.isfinite(self.not_before) or self.not_before <= 0 or self.not_before > time.time():
            raise ValueError('mixed mode requires an explicit past run start epoch')
        for path in (self.trace, self.release):
            reject_link_traversal(path)
            if ROOT/'Local' not in path.resolve().parents:
                raise ValueError('mixed trace/release must stay under checkout Local/')
        if self.release.exists():
            raise StageFailure('WORLD release already exists; refuse stale release')
        self.admission_timeout = bounded_seconds(admission_timeout)
        self.finalization_timeout = bounded_seconds(finalization_timeout)
        self.world_timeout = bounded_seconds(world_timeout)
        self.connections, self.assignments = {}, {}
        self.receipts = {}
        self.offset = 0
        self.finalized_at = None

    def record(self, name, data):
        path = self.output/('mixed-'+name+'.json')
        pending = path.with_suffix('.pending')
        with pending.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(data, indent=2))
        pending.replace(path)  # the CE driver must never read a partial barrier
        self.receipts[name] = data

    def trace_rows(self):
        reject_link_traversal(self.trace)
        with self.trace.open(encoding='utf-8') as source:
            source.seek(0, 2)
            if source.tell() < self.offset:
                raise StageFailure('admission wire trace truncated during the run')
            source.seek(self.offset)
            while True:
                line = source.readline()
                if not line.endswith('\n'):
                    return  # partial append is not evidence yet
                self.offset = source.tell()
                row = json.loads(line)
                if row.get('time', 0) >= self.not_before:
                    yield row

    def wait_real_locks(self, deadline):
        """Deadline finalization is not evidence of ordinary real-client locks."""
        proofs = {identity: {} for identity in self.connections}
        while time.monotonic() < deadline:
            for row in self.trace_rows():
                identity = row.get('identity')
                if row.get('direction') == 'identity' and identity in self.connections:
                    if row['connection'] != self.connections[identity] or row.get('match_id') != self.match_id:
                        raise StageFailure('real connection/match changed during draft')
                owners = [i for i, c in self.connections.items() if c == row.get('connection')]
                if not owners or row.get('opcode') not in (1123, 1119):
                    continue
                proof = proofs[owners[0]]
                if row['direction'] == 'c2s':
                    if row['time'] < self.receipts['draft-ready']['verified_at']:
                        raise StageFailure('real client locked before all six selections were verified')
                    payload = bytes.fromhex(row['payload'])
                    if row['opcode'] == 1123 and payload != bytes(6):
                        raise StageFailure('real-client 1123 payload invalid')
                    if row['opcode'] == 1119:
                        roster.parse_commit_hash(payload)
                    proof[row['opcode']] = row
                elif row['direction'] == 's2c' and row['opcode'] == 1123:
                    if 1123 not in proof or row['time'] < proof[1123]['time']:
                        raise StageFailure('real-client lock acknowledgment is not bound to its lock input')
                    proof['1123_ack'] = row
            if all(set(proof) == {1123, 1119, '1123_ack'} for proof in proofs.values()):
                self.record('real-locks', proofs)
                return
            time.sleep(.1)
        raise StageFailure('mixed finalization timeout: ordinary real-client 1123/1119 not observed')

    def wait_admission(self):
        """Read only: no probe connection may consume a reserved human slot."""
        deadline = time.monotonic()+self.admission_timeout
        snapshots = {}
        real = {r['identity']: r for r in self.plan['real_clients']}
        while time.monotonic() < deadline:
            if self.trace.exists():
                for row in self.trace_rows():
                    identity = row.get('identity')
                    if row.get('direction') == 'identity' and identity in real:
                        if row.get('match_id') != self.match_id:
                            raise StageFailure('real identity belongs to a different match')
                        if any(row.get(k) != real[identity][k] for k in ('eid', 'slot', 'team')):
                            raise StageFailure('real connection owner differs from its reserved identity')
                        if identity in self.connections and self.connections[identity] != row['connection']:
                            raise StageFailure('real admission connection changed')
                        self.connections[identity] = row['connection']
                        if len(set(self.connections.values())) != len(self.connections):
                            raise StageFailure('real clients must have distinct observed connections')
                    conn = row.get('connection')
                    if conn not in self.connections.values():
                        continue
                    if ((row.get('direction') == 'c2s' and row.get('opcode') in (1123, 1119))
                            or (row.get('direction') == 's2c' and row.get('opcode') in (1006, 1132, 1011))):
                        raise StageFailure('real client locked/finalized before mixed admission')
                    if row.get('direction') == 's2c' and row.get('opcode') == 1113:
                        snapshots[conn] = row
                if len(self.connections) == len(real) and all(c in snapshots for c in self.connections.values()):
                    decoded = [selections(bytes.fromhex(snapshots[c]['payload']))
                               for c in self.connections.values()]
                    # Waiting for the human selection is allowed here, never at lock.
                    if all(all(any(r['identity'] == identity and r['hero_id'] != 0xffff for r in rows)
                               for identity in real) for rows in decoded):
                        for rows in decoded:
                            verify_selections(self.plan, rows, unlocked=True)
                        self.record('admission', {'match_id': self.match_id, 'connections': self.connections,
                                                 'snapshots': list(snapshots.values())})
                        return
            time.sleep(.1)
        raise StageFailure('mixed admission timeout: no identity-bound real selection on 1113')

    def verify_release(self, value):
        if (value.get('match_id') != self.match_id or type(value.get('qualified_at')) not in (float, int)
                or not math.isfinite(value['qualified_at'])
                or not self.finalized_at <= value['qualified_at'] <= time.time()):
            raise StageFailure('WORLD release has stale/wrong match/time')
        clients = value.get('clients', [])
        if len(clients) != len(self.plan['real_clients']):
            raise StageFailure('WORLD release must qualify every real client')
        for declared in self.plan['real_clients']:
            matches = [r for r in clients if r.get('identity') == declared['identity']]
            actual = self.assignments[declared['identity']]
            if (len(matches) != 1 or matches[0].get('qualified_world') is not True
                    or matches[0].get('connection') != self.connections[declared['identity']]
                    or any(matches[0].get(k) != actual[k] for k in ('eid', 'slot', 'team', 'hero_id'))):
                raise StageFailure('WORLD release identity/connection/selection qualification mismatch')
        return value

    def wait_release(self, participants):
        deadline = time.monotonic()+self.world_timeout
        while time.monotonic() < deadline:
            if any(p.error for p in participants):
                raise StageFailure('participant receive failed before WORLD release')
            reject_link_traversal(self.release)
            if self.release.exists():
                value = self.verify_release(json.loads(self.release.read_text(encoding='utf-8')))
                self.record('world-release', value)
                return
            time.sleep(.1)
        raise StageFailure('native WORLD release timeout; gameplay remains withheld')


class Participant:
    """A socket owner with a continuously drained stream and bounded waits."""

    def __init__(self, host, port, match_id, hero, output, *, identity=None, heartbeat_port=2112):
        self.host, self.port = private_host(host), port
        self.heartbeat_port = heartbeat_port
        self.hero, self.hero_id = hero, hero_catalog.resolve_hero_id(hero)
        self.match_id = match_id
        self.hash_evidence = None
        self.identity = identity or str(uuid.uuid4())
        self.cipher = wire.MatchCipher(match_id)
        self.eid = self.slot = self.team = None
        self.messages = deque(maxlen=8192)
        self.message_count = 0
        self.record_count = 0
        self.observer = Observer(self.identity)
        self.neutral_deaths = 0
        self.heroes, self.timers, self.ranks = {}, {}, {}
        self.stages = {name: {"classification": "missing input", "proving_opcodes": [],
                              "inputs": [], "started_at": None}
                       for name in STAGES}
        self.condition = threading.Condition(threading.RLock())
        self.send_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.error = None
        self.sock = self.heartbeat = self.thread = None
        self.generation = 0
        self.log = (output / f"{hero.lower()}.jsonl").open("x", encoding="utf-8")

    def _record(self, direction, opcode, payload, lane="match"):
        with self.condition:
            self.record_count += 1
            row = {"direction": direction, "wall_time": time.time(), "opcode": opcode,
                   "payload_hex": payload.hex(), "lane": lane, "generation": self.generation,
                   'record_index':self.record_count, 'identity': self.identity, 'match_id': self.match_id,
                   'eid': self.eid, 'slot': self.slot, 'team': self.team}
            self.log.write(json.dumps(row) + "\n")
            self.log.flush()
            return row

    def send(self, opcode, payload=b""):
        with self.send_lock:
            self.sock.sendall(wire.encode_message(self.cipher, opcode, payload))
            return self._record("c2s", opcode, payload)

    def connect(self, stage="join"):
        self.stop_event.clear()
        self.error = None
        self.generation += 1
        if self.generation > 1:
            with self.condition:
                self.observer.reconnect()
                self.heroes.clear()
                self.ranks.clear()
                self.timers.clear()
        self.sock = socket.create_connection((self.host, self.port), timeout=5)
        route = wire.build_route_request(self.host)
        self.sock.sendall(route)
        request = self._record("c2s", 5, route[2:], "route")
        self.stages[stage]["inputs"].append(request)
        self.stages[stage]["classification"] = "unacknowledged (reason unknown)"
        ack = wire.read_frame(self.sock)
        if ack != wire.ROUTE_ACK_BODY:
            raise StageFailure(f"unexpected route ack: {ack!r}")
        self._record("s2c", 6, ack, "route")
        self.sock.settimeout(None)
        if self.heartbeat_port:
            self.heartbeat = socket.create_connection((self.host, self.heartbeat_port), timeout=5)
            self.heartbeat.settimeout(None)
        self.thread = threading.Thread(target=self._receive, name=f"wire-{self.hero}", daemon=True)
        self.thread.start()
        # These are newly generated test identities, never account tokens.
        self.input(stage, wire.OP.PLAYER_UUID, self.identity.encode("ascii") + bytes(34))

    def _receive(self):
        reader, heartbeat_buffer = wire.FrameReader(), b""
        next_keepalive, started = time.monotonic(), time.monotonic()
        try:
            while not self.stop_event.is_set():
                sockets = [self.sock] + ([self.heartbeat] if self.heartbeat else [])
                readable, _, exceptional = select.select(sockets, [], sockets, 0.1)
                if exceptional:
                    raise OSError("socket exception")
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        raise OSError("server EOF")
                    if sock is self.heartbeat:
                        heartbeat_buffer += data
                        while len(heartbeat_buffer) >= 2:
                            beat, heartbeat_buffer = heartbeat_buffer[:2], heartbeat_buffer[2:]
                            if beat != wire.HEARTBEAT_S2C:
                                raise wire.WireError("unexpected heartbeat")
                            self._record("s2c", 0x89, beat, "heartbeat")
                            sock.sendall(wire.HEARTBEAT_C2S)
                            self._record("c2s", 0x8a, wire.HEARTBEAT_C2S, "heartbeat")
                    else:
                        for body in reader.feed(data):
                            op, payload = wire.decode_body(self.cipher, body)
                            with self.condition:
                                row = self._record("s2c", op, payload)
                                self.message_count += 1
                                row['stream_index'] = self.message_count
                                self.messages.append((op, payload, row))
                                self.observer.consume(op, payload, row)
                                self._observe(op, payload)
                                self.condition.notify_all()
                if time.monotonic() >= next_keepalive:
                    tick = int((time.monotonic() - started) * 513) & 0xffff
                    self.send(0, struct.pack(">HHH", wire.KEEPALIVE_MAGIC, tick, 0))
                    next_keepalive = time.monotonic() + wire.KEEPALIVE_INTERVAL
        except (OSError, ValueError, wire.WireError, struct.error, IndexError, KeyError) as exc:
            if not self.stop_event.is_set():
                with self.condition:
                    self.error = repr(exc)
                    self.condition.notify_all()

    def _observe(self, op, p):
        self.eid = self.observer.owner
        if op == 1072 and len(p) >= 8:
            actor = self.observer.actors.get(u32(p))
            if actor is not None and actor.kind == 'neutral':
                self.neutral_deaths += 1
        if op in (wire.OP.SNAPSHOT_JOIN, wire.OP.SNAPSHOT):
            for index in range(6):
                start = 8 + index * roster.SNAPSHOT_RECORD_STRIDE
                record = p[start:start + roster.SNAPSHOT_RECORD_STRIDE]
                if record[97:161].split(b"\0", 1)[0].decode("ascii") == self.identity:
                    self.slot, self.team = record[1], record[8]
        # Compatibility view for the small M2 stage harness. All arithmetic and
        # slot interpretation live in the typed observer, not a second decoder.
        for eid,a in self.observer.actors.items():
            if a.kind != 'hero':
                continue
            self.heroes[eid] = {name:getattr(a,name) for name in
                ('hero_id','team','slot','position','hp','energy','points','gold')}
            if eid == self.eid:
                self.slot,self.team = a.slot,a.team
        self.ranks = {(a.eid,action):rank for a in self.observer.actors.values()
                      if a.kind == 'hero' for action,rank in a.ranks.items()}
        self.timers = {(a.eid,tag):timer for a in self.observer.actors.values()
                       if a.kind == 'hero' for tag,timer in a.timers.items()}

    def mark(self):
        with self.condition:
            return self.message_count

    def wait(self, predicate, *, after=0, timeout=8):
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                if self.messages and after and after < self.messages[0][2]['stream_index']-1:
                    raise StageFailure(f'{self.hero}: evidence wait exceeded bounded retention')
                for op, payload, row in self.messages:
                    if row['stream_index'] <= after:
                        continue
                    if predicate(op, payload):
                        return row
                after = self.message_count
                if self.error:
                    raise StageFailure(f"{self.hero} receive failure: {self.error}")
                left = deadline - time.monotonic()
                if left <= 0:
                    raise StageFailure(f"{self.hero}: no matching s2c within {timeout}s")
                self.condition.wait(left)

    def begin(self, name):
        self.stages[name] = {"classification": "missing input",
                             "started_at": time.time(), "proving_opcodes": [], "inputs": []}
        return self.mark()

    def input(self, name, opcode, payload):
        row = self.send(opcode, payload)
        self.stages[name]["inputs"].append(row)
        self.stages[name]["classification"] = "unacknowledged (reason unknown)"

    def accepted(self, name, row):
        self.stages[name].update(classification="accepted", proving_opcodes=[row["opcode"]], evidence=[row])

    def prove(self, name, rows):
        self.stages[name].update(classification=OBSERVED, completed_at=time.time(),
                                 proving_opcodes=sorted({r["opcode"] for r in rows}), evidence=rows)

    def state(self):
        with self.condition:
            return dict(self.heroes[self.eid])

    def disconnect(self):
        self.stop_event.set()
        for sock in (self.sock, self.heartbeat):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        if self.thread:
            self.thread.join(5)
            if self.thread.is_alive():
                raise StageFailure(f"{self.hero} receive thread did not stop")
        self.sock = self.heartbeat = self.thread = None

    def close(self):
        try:
            self.disconnect()
        finally:
            self.log.close()

    def report(self):
        return {"hero": self.hero, "hero_id": self.hero_id, "identity": self.identity,
                "hash_evidence": self.hash_evidence,
                "eid": self.eid, "slot": self.slot, "team": self.team,
                "stages": self.stages, "receive_error": self.error,
                "wire_log": str(Path(self.log.name).resolve())}


def enter_mixed(participants, mixed):
    require_default_allocation()
    payloads = draft_payloads(participants)
    mixed.wait_admission()
    for p in participants:
        mark = p.begin('join')
        p.connect()
        setup = p.wait(lambda op, b: op == 1001, after=mark)
        snapshot = p.wait(lambda op, b: op == 1113, after=mark)
        rows = selections(bytes.fromhex(snapshot['payload_hex']))
        verify_selections(mixed.plan, rows, unlocked=True)
        own = [r for r in rows if r['identity'] == p.identity]
        if (len(own) != 1 or own[0]['slot'] in {r['slot'] for r in mixed.plan['real_clients']}
                or (p.eid, p.slot, p.team) != (own[0]['eid'], own[0]['slot'], own[0]['team'])
                or u32(bytes.fromhex(setup['payload_hex'])) != p.eid):
            raise StageFailure('participant owner mismatch or reserved slot consumed')
        p.prove('join', [setup, snapshot])
    for p in participants:
        mark = p.begin('select')
        payload = payloads[p.identity][0]
        p.input('select', 1118, payload)
        echo = p.wait(lambda op, b: op == 1118 and b == payload, after=mark)
        p.prove('select', [echo])
    # The last selection's snapshot is a server-serialized view of all six.
    # Do not accept an older opener, or wait past an invalid human selection.
    final = p.wait(lambda op, b: op == 1113 and any(
        r['identity'] == p.identity and r['hero_id'] == p.hero_id for r in selections(b)), after=mark)
    mixed.assignments = verify_selections(mixed.plan, selections(bytes.fromhex(final['payload_hex'])),
                                          all_six=True, unlocked=True)
    proofs = []
    for p in participants:
        proof = p.wait(lambda op, b: op == 1113 and selections(b) == selections(bytes.fromhex(final['payload_hex'])))
        proofs.append({'identity': p.identity, 'snapshot': proof})
    mixed.record('draft-ready', {'match_id': mixed.match_id, 'not_before': mixed.not_before, 'verified_at': time.time(),
                                'assignments': mixed.assignments, 'streams': proofs})
    # CE driver may now execute its ordinary guarded LOCK IN. Participants do
    # not substitute a deadline, nor emit readiness to manufacture finalization.
    marks = []
    for p in participants:
        with p.condition:
            latest = next(b for op, b, row in reversed(p.messages) if op == 1113)
            assignments = verify_selections(mixed.plan, selections(latest), all_six=True)
        if any(any(assignments[i][k] != old[k] for k in ('slot', 'eid', 'team', 'hero_id'))
               for i, old in mixed.assignments.items()):
            raise StageFailure('six selections changed before participant lock')
        marks.append(p.begin('lock'))
        p.input('lock', 1123, bytes(6))
        p.input('lock', 1119, payloads[p.identity][1])
    deadline = time.monotonic()+mixed.finalization_timeout
    mixed.wait_real_locks(deadline)
    def remaining():
        left = deadline-time.monotonic()
        if left <= 0:
            raise StageFailure('mixed finalization timeout: waiting for human locks and 1006/1132')
        return left
    for p, mark in zip(participants, marks):
        proof = [p.wait(lambda op, b: op == 1123, after=mark, timeout=remaining())]
        for row in mixed.assignments.values():
            proof.append(p.wait(lambda op, b: op == 1006 and (u32(b, 160), u32(b, 164)) ==
                                (row['eid'], row['hero_id']), after=mark, timeout=remaining()))
        proof.append(p.wait(lambda op, b: op == 1132, after=mark, timeout=remaining()))
        p.prove('lock', proof)
    # Use server finalization receipt time, not the later local scan time:
    # a fast real client may qualify while other participant streams are drained.
    mixed.finalized_at = max(r['wall_time'] for p in participants
                             for r in p.stages['lock']['evidence'] if r['opcode'] == 1132)
    # The ordinary CE must lead the corpus bootstrap. The first ready socket
    # receives its retained slot0 echo; a participant racing the CE can receive
    # 1137 for EID1500 instead of its own EID (step4b host-review evidence).
    # Never accept that wrong-owner echo or manufacture readiness to bypass it.
    mixed.wait_release(participants)
    ready_participants(participants, mixed.world_timeout)
    for p in participants:
        with p.condition:
            for row in mixed.assignments.values():
                hero = p.heroes.get(row['eid'])
                if not hero or any(hero[k] != row[k] for k in ('slot', 'team', 'hero_id')):
                    raise StageFailure('WORLD 1011 differs from the verified six selections')


def ready_participants(participants, timeout):
    deadline = time.monotonic()+bounded_seconds(timeout)
    # Preserve first-socket bootstrap ownership: slot0 leads wire-only entry;
    # mixed entry calls this only after the native CE's qualified release.
    for p in participants:
        mark = p.begin('ready')
        p.input('ready', 1134, bytes(6))
        p.input('ready', 1137, roster.build_hero_ready_ack(p.eid))
        def wait(predicate):
            left = deadline-time.monotonic()
            if left <= 0:
                raise StageFailure('participant WORLD bootstrap timeout')
            return p.wait(predicate, after=mark, timeout=left)
        block = wait(lambda op, b: op == 1011 and u32(b, 8) == p.eid and u32(b) == p.hero_id)
        echo = wait(lambda op, b: op == 1137 and b == roster.build_hero_ready_ack(p.eid))
        world = wait(lambda op, b: op == 1116)
        p.prove('ready', [block, echo, world])


def enter_world(participants, timeout=180):
    timeout = bounded_seconds(timeout)
    payloads = draft_payloads(participants)
    for index, p in enumerate(participants):
        mark = p.begin("join")
        p.connect()
        setup = p.wait(lambda op, b: op == 1001, after=mark)
        snapshot = p.wait(lambda op, b: op == 1113, after=mark)
        if (p.eid, p.slot, p.team) != (EIDS[index], SLOTS[index], 1 if index % 2 == 0 else 2):
            raise StageFailure(f"unexpected identity assignment: {p.report()}")
        p.prove("join", [setup, snapshot])
    for p in participants:
        mark = p.begin("select")
        payload = payloads[p.identity][0]
        p.input("select", 1118, payload)
        p.prove("select", [p.wait(lambda op, b: op == 1118 and b == payload, after=mark)])
    marks = []
    for p in participants:
        marks.append(p.begin("lock"))
        p.input("lock", 1123, bytes(6))
        p.input("lock", 1119, payloads[p.identity][1])
    for p, mark in zip(participants, marks):
        p.prove("lock", [p.wait(lambda op, b: op == 1123, after=mark),
                         p.wait(lambda op, b: op == 1132, after=mark, timeout=timeout)])
    ready_participants(participants, timeout)


def native_cast(p):
    slot, _cost = SKILLS[p.hero]
    action = ability_wire.hero_action_variant(p.hero_id, "ABC"[slot])
    if p.hero == "Skye":
        x, y = p.state()["position"]
        return 1042, struct.pack(">fffBB", x + 3, 0, y, action, 0), 1046
    return 1041, struct.pack(">IBB", 0xffffffff, action, 0), 1045


def learn_and_cast(p):
    slot, cost = SKILLS[p.hero]
    action = ability_wire.hero_action_variant(p.hero_id, "ABC"[slot])
    tag = cooldown_wire.native_ability_tag(f"Ability__{p.hero}__{'ABC'[slot]}")
    if p.state()["points"] < 1:
        raise StageFailure(f"{p.hero}: no observed available skill point")
    mark = p.begin("learn")
    p.input("learn", 1078, roster.build_ability_cast(slot))
    rank = p.wait(lambda op, b: op == 1082 and (u32(b), u32(b, 4)) == (p.eid, action), after=mark)
    ready = p.wait(lambda op, b: op == 1162 and (u32(b), u32(b, 4)) == (p.eid, tag)
                   and cooldown_wire.parse_timer_tick(b).state[:2] == b"\x01\x01", after=mark)
    p.prove("learn", [rank, ready])
    if p.state()["energy"] < cost:
        raise StageFailure(f"{p.hero}: insufficient observed energy")
    mark = p.begin("cast")
    opcode, payload, response = native_cast(p)
    p.input("cast", opcode, payload)
    start = p.wait(lambda op, b: op == response and u32(b) == p.eid
                   and b[16 if op == 1046 else 8] == action, after=mark)
    p.accepted("cast", start)
    debit = p.wait(lambda op, b: op == 1053 and u32(b) == p.eid and b[8] == 2
                   and math.isclose(struct.unpack_from(">f", b, 4)[0], -cost), after=mark)
    cooldown = p.wait(lambda op, b: op == 1162 and (u32(b), u32(b, 4)) == (p.eid, tag)
                      and cooldown_wire.parse_timer_tick(b).remaining > 0, after=mark)
    p.prove("cast", [start, debit, cooldown])


def participant_by_identity(participants, identity):
    matches = [p for p in participants if p.identity == identity]
    if len(matches) != 1:
        raise StageFailure('reconnect identity must identify exactly one wire participant')
    return matches[0]


def play_mixed(participants, mixed, *, duration, reconnect_identity, reconnect_after):
    """Bounded ordinary identity-paired exercise; NOT reciprocal native acceptance."""
    from Tools.protocol_policy import Policy, MixedRendezvous
    duration, reconnect_after = bounded_seconds(duration), bounded_seconds(reconnect_after)
    if reconnect_after >= duration:
        raise ValueError('mixed reconnect must occur before exercise duration ends')
    if 'world-release' not in mixed.receipts:
        raise StageFailure('mixed gameplay requires a verified native WORLD release')
    target = participant_by_identity(participants, reconnect_identity)
    declarations = {r['identity']: r for r in mixed.plan['participants']}
    opponents = {p.identity: mixed.assignments[declarations[p.identity]['opponent']]['eid'] for p in participants}
    real = {r['identity'] for r in mixed.plan['real_clients']}
    declared = [p for p in participants if declarations[p.identity]['opponent'] in real]
    rendezvous = None
    if len(real) == 1:
        if len(declared) != 1:
            raise StageFailure('clean one-CE exercise requires exactly one declared participant opponent')
        opponent = declared[0]
        pair = (opponents[opponent.identity], opponent.eid)
        from server.navigation import load_halcyon_navmesh
        rendezvous = MixedRendezvous(load_halcyon_navmesh())
        mixed.record('rendezvous', rendezvous.evidence())
        policies = {p.identity: Policy(p.eid, p.hero, mixed_pair=pair,
                    opponent_eid=opponents[p.identity] if p is opponent else None,
                    rendezvous=rendezvous) for p in participants}
    else:
        policies = {p.identity: Policy(p.eid, p.hero, opponent_eid=opponents[p.identity]) for p in participants}
    start, reconnected, orders = time.monotonic(), False, {p.identity: 0 for p in participants}
    engagement_at = None
    with (mixed.output/'mixed-orders.jsonl').open('x', encoding='utf-8') as log, \
            (mixed.output/'mixed-holds.jsonl').open('x', encoding='utf-8') as hold_log, \
            (mixed.output/'mixed-staging.jsonl').open('x', encoding='utf-8') as staging_log:
        while time.monotonic()-start < duration:
            now = time.monotonic()-start
            if any(p.error for p in participants):
                raise StageFailure('mixed exercise receive failure')
            if (not reconnected and now >= reconnect_after
                    and (rendezvous is None or engagement_at is not None and now > engagement_at)):
                mixed.record('reconnect-schedule', dict(engagement_elapsed_s=engagement_at,
                    configured_elapsed_s=reconnect_after, reconnect_elapsed_s=now, at=time.time()))
                reconnect(target)
                reconnected = True
                policies[target.identity].last_order = policies[target.identity].target = None
                policies[target.identity].next_action = 0
            views = []
            for p in participants:
                with p.condition:
                    views.append(copy.deepcopy(p.observer.actors))
            for index, p in enumerate(participants):
                actors = views[index]
                peer = views[(index+1) % len(views)].get(p.eid)
                if peer and p.eid in actors:
                    actors[p.eid].position = peer.position
                intent = policies[p.identity].step(actors, now)
                if policies[p.identity].engagement is not None:
                    staging = dict(wall_time=time.time(), elapsed_s=now, identity=p.identity,
                                   **policies[p.identity].engagement)
                    staging_log.write(json.dumps(staging)+'\n')
                    staging_log.flush()
                    if staging['phase'] == 'engagement' and engagement_at is None:
                        engagement_at = now
                if policies[p.identity].hold:
                    hold_log.write(json.dumps({'wall_time': time.time(), 'identity': p.identity,
                        'kind': 'mixed-hold', 'input_submitted': bool(intent),
                        **policies[p.identity].hold})+'\n')
                    hold_log.flush()
                if intent:
                    stage = {1078:'learn', 1081:'purchase', 1012:'move', 1060:'attack', 1041:'recall'}[intent.opcode]
                    if p.stages[stage]['started_at'] is None:
                        p.begin(stage)
                    # Record sent input, but do not infer acceptance/damage from
                    # sendall success. Phase 3 must correlate ordinary effects.
                    p.input(stage, intent.opcode, intent.payload)
                    row = p.stages[stage]['inputs'][-1]
                    orders[p.identity] += 1
                    log.write(json.dumps({'identity': p.identity, 'opponent': declarations[p.identity]['opponent'],
                                          'reason': intent.reason, **row})+'\n')
                    log.flush()
            time.sleep(.5)
    if not reconnected or not all(orders.values()):
        raise StageFailure('mixed exercise missing ordinary orders or configured reconnect')
    return {'exercise_duration_s': time.monotonic()-start, 'orders': orders,
            'engagement_elapsed_s': engagement_at,
            'opponents': opponents, 'reconnect_identity': target.identity,
            'claim': 'bounded mixed protocol exercise; reciprocal CE-native effects remain unverified'}


def play(participants, timeout=75, *, reconnect_identity=None):
    # Preserve M2's original six-hero pairs while resolving owners by identity,
    # not by adjacency in a caller's list. Mixed mode supplies its own declarations.
    paired_heroes = dict(zip(HEROES, ('Ringo', 'Skye', 'Gwen', 'Catherine', 'Amael', 'Adagio')))
    identities = {p.hero: p.identity for p in participants}
    targets = {p.identity: participant_by_identity(participants, identities[paired_heroes[p.hero]])
               for p in participants}
    for p in participants:
        learn_and_cast(p)
    # Let finite cast channels finish; no simulation-time acceleration.
    time.sleep(5)
    for index, p in enumerate(participants):
        mark = p.begin("move")
        peer = next(other for other in participants if other is not p)
        p.stages["move"]["peer_log"] = peer.log.name
        p.stages["move"]["peer_mark"] = peer.mark()
        destination = (-1.5 if p.team == 1 else 1.5, 41.0 + (index // 2))
        p.input("move", 1012, roster.build_move(*destination))
        ack = p.wait(lambda op, b: op == 1016 and b[0] == p.slot, after=mark)
        p.prove("move", [ack])
    # Ordinary walking to the jungle shop, using only received coordinates.
    deadline = time.monotonic() + timeout
    while not all(math.dist(peer_position(p, participants), (0.2, 42)) < 4 for p in participants):
        if time.monotonic() >= deadline:
            raise StageFailure("rendezvous not observed before deadline")
        if any(p.error for p in participants):
            raise StageFailure("receive loop failed during rendezvous")
        time.sleep(0.1)
    for p in participants:
        peer = next(other for other in participants if other is not p)
        endpoint = peer.wait(lambda op, b: op == 1070 and u32(b) == p.eid
                             and math.dist(struct.unpack_from(">ff", b, 4), (0.2, 42)) < 4,
                             after=p.stages["move"]["peer_mark"])
        p.prove("move", p.stages["move"]["evidence"] + [endpoint])
    for p in participants:
        target = targets[p.identity]
        if target.team == p.team:
            raise StageFailure('declared M2 opponent is not on the opposing team')
        if p.state()["hp"] <= 0 or target.state()["hp"] <= 0:
            raise StageFailure("attack requires observed living participants")
        mark = p.begin("attack")
        p.input("attack", 1060, roster.build_target_entity(target.eid))
        start = p.wait(lambda op, b: op == 1045 and (u32(b), u32(b, 4)) == (p.eid, target.eid), after=mark)
        p.accepted("attack", start)
        damage = p.wait(lambda op, b: op == 1054 and (u32(b), u32(b, 4)) == (target.eid, p.eid)
                        and struct.unpack_from(">f", b, 8)[0] < 0, after=mark, timeout=15)
        p.prove("attack", [start, damage])
        p.send(1012, roster.build_move(*peer_position(p, participants)))
    for p in participants:
        if p.state()["gold"] < 300:
            raise StageFailure(f"{p.hero}: insufficient observed gold")
        mark = p.begin("purchase")
        p.input("purchase", 1081, roster.build_shop_buy(p.eid, 458))
        inventory = p.wait(lambda op, b: op == 1085 and (u32(b), u32(b, 4)) == (p.eid, 458), after=mark)
        gold = p.wait(lambda op, b: op == 1053 and u32(b) == p.eid and b[8] == 6
                      and struct.unpack_from(">f", b, 4)[0] == -300, after=mark)
        p.prove("purchase", [inventory, gold])
    for p in participants:
        mark = p.begin("recall")
        action = ability_wire.hero_action_variant(p.hero_id, "recall")
        p.input("recall", 1041, struct.pack(">IBB", 0xffffffff, action, 0))
        start = p.wait(lambda op, b: op == 1045 and u32(b) == p.eid and b[8] == action, after=mark)
        done = p.wait(lambda op, b: op == 1094 and u32(b) == p.eid, after=mark, timeout=12)
        position = p.wait(lambda op, b: op == 1070 and u32(b) == p.eid
                          and math.dist(struct.unpack_from(">ff", b, 4), roster.HERO_SPAWNS[p.eid]) < 1,
                          after=mark, timeout=12)
        p.prove("recall", [start, done, position])
    reconnect(participant_by_identity(participants, reconnect_identity or identities['Skye']))


def peer_position(p, participants):
    # The production owner-prediction policy suppresses the owner's periodic
    # 1070. A peer's received s2c position is evidence, not a sim accessor.
    peer = next(other for other in participants if other is not p)
    with peer.condition:
        return peer.heroes[p.eid]["position"]


def reconnect(p):
    expected = p.eid, p.slot, p.team
    p.disconnect()
    mark = p.begin("reconnect")
    p.connect("reconnect")
    setup = p.wait(lambda op, b: op == 1001 and u32(b) == expected[0], after=mark)
    block = p.wait(lambda op, b: op == 1011 and u32(b, 8) == expected[0], after=mark)
    first = p.wait(lambda op, b: op == 1070 and u32(b) == expected[0], after=mark)
    ready_mark = p.mark()
    p.input('reconnect', 1134, bytes(6))
    p.input('reconnect', 1137, roster.build_hero_ready_ack(p.eid))
    ready = p.wait(lambda op, b: op == 1137 and b == roster.build_hero_ready_ack(p.eid), after=ready_mark)
    later = p.wait(lambda op, b: op == 1116, after=p.mark(), timeout=8)
    if (p.eid, p.slot, p.team) != expected:
        raise StageFailure("reconnect changed identity assignment")
    p.prove("reconnect", [setup, block, first, ready, later])


def full_match(participants, output, *, timeout=2400, stall_seconds=300, soak=False, reconnect_identity=None):
    from Tools.protocol_policy import Policy
    policies = [Policy(p.eid,p.hero,defend_farm=soak) for p in participants]
    start = time.monotonic()
    last_progress, destroyed = start, set()
    reconnect_thread, reconnect_errors = None, []
    reconnect_before = None
    soak_started = None
    default_identity = next(p.identity for p in participants if p.hero == 'Adagio')
    reconnect_target = participant_by_identity(participants, reconnect_identity or default_identity)
    def reconnect_once():
        try:
            reconnect(reconnect_target)
        except Exception as exc:
            reconnect_errors.append(repr(exc))
    with (output/'policy.jsonl').open('x',encoding='utf-8') as log:
        try:
            while True:
                now = time.monotonic()
                if now-start >= timeout:
                    raise StageFailure('soak timeout: incomplete stability interval' if soak else
                                       'match timeout: no natural result on all six streams')
                if reconnect_errors:
                    raise StageFailure('reconnect: '+str(reconnect_errors))
                if any(p.error for p in participants):
                    raise StageFailure('receive/EOF: '+str([p.error for p in participants]))
                views = []
                for p in participants:
                    with p.condition:
                        views.append(copy.deepcopy(p.observer.actors))
                fresh = set().union(*(p.observer.structure_deaths for p in participants))
                if fresh != destroyed:
                    destroyed, last_progress = fresh, now
                    print(f'Match {now-start:.1f}s: destroyed structures {sorted(destroyed)}',flush=True)
                if not soak and now-last_progress > stall_seconds:
                    snapshot = {p.hero:{eid:vars(a) | {'timers':{tag:str(t) for tag,t in a.timers.items()}}
                               for eid,a in view.items()} for p,view in zip(participants,views)}
                    (output/'stall.json').write_text(json.dumps(snapshot,indent=2),encoding='utf-8')
                    raise StageFailure(f'policy stall: no structure destruction for {stall_seconds}s; inspect stall.json')
                if soak:
                    if any(p.observer.result or p.observer.crystal_notice for p in participants):
                        raise StageFailure('soak ended naturally; required live stability interval not completed')
                    if soak_started is None and all(p.observer.minion_spawns for p in participants):
                        # Start from live wave evidence, not menu/tape wall time.
                        soak_started = now
                    if soak_started is not None and now-soak_started >= 1800:
                        if reconnect_thread is None or reconnect_thread.is_alive():
                            raise StageFailure('soak missing completed mid-match reconnect')
                        if not all(p.observer.deaths and p.observer.revivals and p.neutral_deaths
                                   and p.observer.own_purchases and p.observer.own_learns for p in participants):
                            raise StageFailure('soak missing death/revival/jungle/shop/learn coverage')
                        return {'claim':'30-minute protocol stability; not a match result',
                                'match_duration_s':now-start, 'stability_duration_s':now-soak_started,
                                'termination':'participants stopped after measured interval',
                                'reconnect_other_stream_frames':{p.hero:p.message_count-reconnect_before[p.hero]
                                    for p in participants if p is not reconnect_target}}
                if all(p.observer.finished() for p in participants):
                    if reconnect_thread is None or reconnect_thread.is_alive():
                        raise StageFailure('natural finish without completed mid-match reconnect')
                    if not any(p.observer.deaths and p.observer.revivals for p in participants):
                        raise StageFailure('natural finish missing hero death/1074 coverage')
                    if not all(p.observer.minion_spawns and p.observer.own_purchases and p.observer.own_learns for p in participants):
                        raise StageFailure('natural finish missing wave/shop/learn coverage')
                    winners = {p.observer.result['winner'] for p in participants}
                    if len(winners) != 1:
                        raise StageFailure('1009 winner differs between streams')
                    if any(p.observer.structure_order_errors for p in participants):
                        raise StageFailure('structure death violates observed vulnerability order')
                    if not all(sum(a.kind == 'structure' for a in view.values()) == 12 for view in views):
                        raise StageFailure('incomplete structure registry')
                    return {'match_duration_s':now-start,'winner':winners.pop(),
                            'reconnect_other_stream_frames':{p.hero:p.message_count-reconnect_before[p.hero]
                                for p in participants if p is not reconnect_target}}
                if reconnect_thread is None and now-start > 70 and any(p.observer.minion_spawns for p in participants):
                    reconnect_before = {p.hero:p.message_count for p in participants}
                    reconnect_thread = threading.Thread(target=reconnect_once,name='m3-reconnect')
                    reconnect_thread.start()
                for index,(p,policy,actors) in enumerate(zip(participants,policies,views)):
                    if p is reconnect_target and reconnect_thread and reconnect_thread.is_alive():
                        continue
                    # Owner periodic 1070 is suppressed: borrow only a peer's
                    # received coordinate, never the peer's simulation object.
                    peer = views[(index+1)%len(views)].get(p.eid)
                    if peer and p.eid in actors:
                        actors[p.eid].position = peer.position
                    intent = policy.step(actors,now-start)
                    if intent:
                        row = p.send(intent.opcode,intent.payload)
                        log.write(json.dumps({'hero':p.hero,'reason':intent.reason,**row})+'\n')
                        log.flush()
                time.sleep(.5)
        finally:
            if reconnect_thread:
                reconnect_thread.join(30)
                if reconnect_thread.is_alive():
                    raise StageFailure('reconnect thread did not stop')


def run(host, port, output, *, match_id=MATCH_ID, heartbeat_port=2112, mode="existing-server", inputs=None,
        lifecycle=False, soak=False, mixed=None, finalization_timeout=180, reconnect_identity=None,
        mixed_seconds=60, reconnect_after=20):
    summary = {"source": source_identity(), "host": private_host(host), "port": port,
               "mode": mode, "started_at": time.time(), 'started_monotonic_ns':time.monotonic_ns(), "status": "RUNNING",
               "setup_failures": [], "gameplay_failures": [], "owned_inputs": inputs,
               "limits": ["Protocol/session evidence, not native-client behavior or independent gameplay fidelity.",
                          "One rank-one cast per hero; no complete-kit, full-match or exact-replay claim.",
                          "Gold uses the native 600 initial baseline plus received deltas."]}
    participants = []
    entered = False
    try:
        if mixed:
            if lifecycle or soak:
                raise ValueError('mixed mode is a bounded exercise, not M3 full-match/soak acceptance')
            if mixed.match_id != match_id:
                raise ValueError('mixed admission match ID differs from participant match ID')
            summary['mode'] = 'mixed-existing-gateway'
            summary['composition'] = mixed.plan
            summary['limits'] = ['Protocol/session exercise only; no CE-native effects or independent gameplay-fidelity acceptance.',
                                 'Explicit CE driver WORLD release is trusted only after wire-bound identity/finalization checks.',
                                 'CE driver must hold LOCK IN for mixed-draft-ready.json; early lock is a stop condition.']
            for declaration in mixed.plan['participants']:
                participants.append(Participant(host, port, match_id, declaration['hero'], output,
                                    identity=declaration['identity'], heartbeat_port=heartbeat_port))
            participant_by_identity(participants, reconnect_identity)
            if not bounded_seconds(reconnect_after) < bounded_seconds(mixed_seconds):
                raise ValueError('mixed reconnect must precede exercise end')
            enter_mixed(participants, mixed)
        else:
            for hero in HEROES:
                participants.append(Participant(host, port, match_id, hero, output, heartbeat_port=heartbeat_port))
            if reconnect_identity:
                participant_by_identity(participants, reconnect_identity)
            enter_world(participants, timeout=finalization_timeout)
        entered = True
        if mixed:
            summary.update(play_mixed(participants, mixed, duration=mixed_seconds,
                                      reconnect_identity=reconnect_identity, reconnect_after=reconnect_after))
        elif lifecycle or soak:
            summary['limits'] = ['Wire-only server/session acceptance, not native rendering or independent gameplay fidelity.',
                                 'Nonhero HP unknown until an HP-bearing snapshot; gold starts at native 600.',
                                 'Hero resources become unknown after implicit 1076 growth until a numeric baseline; no fabricated HP.',
                                 'Tick anchors from journal; per-stream evidence independently received.']
            summary.update(full_match(participants,output,soak=soak,reconnect_identity=reconnect_identity))
        else:
            play(participants, reconnect_identity=reconnect_identity)
        errors = [f"{p.hero}: {p.error}" for p in participants if p.error]
        if errors:
            raise StageFailure("; ".join(errors))
        summary["status"] = "PASS"
    except (StageFailure, OSError, ValueError) as exc:
        summary["status"] = "FAILED" if entered else "SETUP"
        summary["gameplay_failures" if entered else "setup_failures"].append(str(exc))
    except Exception as exc:
        summary["status"] = "ERROR"
        summary["gameplay_failures" if entered else "setup_failures"].append(repr(exc))
        (output / "exception.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        for p in participants:
            try:
                p.close()
            except (OSError, StageFailure) as exc:
                summary["status"] = "ERROR"
                summary["setup_failures"].append(f"cleanup {p.hero}: {exc}")
        summary["participants"] = [p.report() for p in participants]
        if mixed:
            summary['mixed_barriers'] = mixed.receipts
        if lifecycle or soak:
            for report,p in zip(summary['participants'],participants):
                report['observer'] = p.observer.metrics()
                report['generation'] = p.generation
                report['neutral_deaths'] = p.neutral_deaths
        summary["source_stable"] = summary["source"]["manifest_sha256"] == source_identity()["manifest_sha256"]
        if not summary["source_stable"]:
            summary["status"] = "ERROR"
            summary["setup_failures"].append("source changed during run")
        summary["completed_at"] = time.time()
        summary["duration_s"] = summary["completed_at"] - summary["started_at"]
        (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7100)
    parser.add_argument("--heartbeat-port", type=int, default=2112)
    parser.add_argument("--match-id", default=MATCH_ID)
    parser.add_argument("--output")
    parser.add_argument("--self-host", action="store_true")
    parser.add_argument('--server-process', action='store_true',
                        help='[self-host] isolate production server from participant decoding/policy')
    parser.add_argument("--journal", action="store_true",
                        help="[self-host] record application-order journal and tick-work evidence")
    parser.add_argument('--full-match', action='store_true', help='M3 natural lifecycle, 40-minute wall cap')
    parser.add_argument('--soak', action='store_true', help='30 minutes after first live wave; defend/farm, no match-result claim')
    parser.add_argument('--telemetry', action='store_true', help='self-host process and queue measurements')
    parser.add_argument('--mixed-roster', type=Path, help='JSON declared real-client reservations and identity/opponent participants')
    parser.add_argument('--admission-wire', type=Path, help='fresh platform-owned gateway wire JSONL')
    parser.add_argument('--not-before', type=float, help='fresh run start epoch, for mixed wire admission')
    parser.add_argument('--world-release', type=Path, help='new atomic CE-native WORLD release JSON; see module contract')
    parser.add_argument('--admission-timeout', type=bounded_seconds, default=120)
    parser.add_argument('--finalization-timeout', type=bounded_seconds, default=180,
                        help='bounded ordinary locks and 1006/1132 wait; never deadline-entry')
    parser.add_argument('--world-timeout', type=bounded_seconds, default=180)
    parser.add_argument('--mixed-seconds', type=bounded_seconds, default=60)
    parser.add_argument('--reconnect-after', type=bounded_seconds, default=20)
    parser.add_argument('--reconnect-identity', help='wire identity to reconnect (required for mixed mode)')
    args = parser.parse_args(argv)
    host = private_host(args.host)
    if args.self_host and not ipaddress.ip_address(host).is_loopback:
        parser.error("--self-host binds loopback only")
    if args.server_process and not args.self_host:
        parser.error('--server-process requires --self-host')
    if args.journal and not args.self_host:
        parser.error("--journal requires --self-host")
    if args.telemetry and not args.self_host:
        parser.error('--telemetry requires --self-host')
    if args.full_match and args.soak:
        parser.error('--full-match and --soak are mutually exclusive')
    if (args.full_match or args.soak) and not (args.self_host and args.journal and args.telemetry):
        parser.error('--full-match/--soak requires --self-host --journal --telemetry')
    if args.mixed_roster:
        if args.self_host or args.full_match or args.soak:
            parser.error('mixed mode requires an existing platform gateway and a bounded exercise')
        if not all((args.admission_wire, args.not_before, args.world_release, args.reconnect_identity)):
            parser.error('mixed mode requires --admission-wire --not-before --world-release --reconnect-identity')
        if args.reconnect_after >= args.mixed_seconds:
            parser.error('--reconnect-after must precede --mixed-seconds')
    elif any((args.admission_wire, args.not_before, args.world_release)):
        parser.error('admission/release arguments require --mixed-roster')
    output = new_output(args.output)
    print(f"Evidence: {output}", flush=True)
    server = None
    telemetry = None
    inputs = None
    try:
        mixed = None
        if args.mixed_roster:
            try:
                mixed = MixedEntry(json.loads(args.mixed_roster.read_text(encoding='utf-8')), args.match_id,
                                   args.admission_wire, args.not_before, args.world_release, output,
                                   admission_timeout=args.admission_timeout,
                                   finalization_timeout=args.finalization_timeout, world_timeout=args.world_timeout)
            except (OSError, ValueError, KeyError, TypeError, StageFailure) as exc:
                (output/'summary.json').write_text(json.dumps({'status':'SETUP', 'mode':'mixed-existing-gateway',
                    'setup_failures':[str(exc)], 'participants':[], 'gameplay_failures':[]}, indent=2), encoding='utf-8')
                print(f'SETUP: {exc}', flush=True)
                return 2
        if args.self_host:
            from Tools.protocol_host import LocalServer, ServerProcess, SetupFailure
            server_type = ServerProcess if args.server_process else LocalServer
            server = server_type(host, args.match_id, output, journal=args.journal, telemetry=args.telemetry)
            try:
                ready = server.start()
            except Exception as exc:
                summary = {"status": "SETUP", "source": source_identity(), "mode": "self-host",
                           "host": host, "port": None, "participants": [],
                           "setup_failures": exc.failures if isinstance(exc, SetupFailure) else [repr(exc)],
                           "gameplay_failures": []}
                (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
                return 2
            inputs = ready['inputs']
            args.port, args.heartbeat_port = ready['port'], ready['heartbeat_port']
            if args.telemetry and args.server_process:
                from Tools.protocol_telemetry import Telemetry
                telemetry = Telemetry(None, output, role='participants', filename='participant-telemetry.jsonl')
                telemetry.start()
        summary = run(host, args.port, output, match_id=args.match_id,
                      heartbeat_port=args.heartbeat_port,
                      mode='self-host-process' if args.server_process else 'self-host' if args.self_host else 'existing-server', inputs=inputs,
                      lifecycle=args.full_match, soak=args.soak, mixed=mixed,
                      finalization_timeout=args.finalization_timeout, reconnect_identity=args.reconnect_identity,
                      mixed_seconds=args.mixed_seconds, reconnect_after=args.reconnect_after)
        if telemetry:
            telemetry.close()
            summary['participant_telemetry_error'] = telemetry.error
            if telemetry.error:
                summary['status'] = 'ERROR'
        if server is not None:
            result = server.close()
            summary['server_process'] = {'isolated':args.server_process, 'server_pid':result.get('pid'),
                                         'participant_pid':os.getpid(), 'close_receipt':result}
            summary['journals'] = result['journals']
            summary['telemetry_error'] = result.get('telemetry_error')
            if result['status'] != 'PASS' or args.journal and not result['journals']:
                summary['status'] = 'ERROR'
                summary['setup_failures'].extend(result['failures'] or ['missing input journal'])
            (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if args.telemetry and not summary.get('telemetry_error'):
            from Tools.protocol_telemetry import summarize
            summarize(output,summary)
            (output / 'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(f"{summary['status']}: {output / 'summary.json'}", flush=True)
        return 0 if summary["status"] == "PASS" else 1
    finally:
        if telemetry:
            telemetry.close()
        if server:
            server.close()


if __name__ == "__main__":
    raise SystemExit(main())

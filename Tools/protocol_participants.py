"""Six ordinary wire participants against an operator-owned Halcyon server.

No client rendering, privileged gameplay controls, simulation stepping or replay
claims. All observations come from each participant's decoded s2c stream.
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

from Tools.verification_support import output_directory
from Tools.protocol_observer import Observer
from server import ability_wire, cooldown_wire, hero_catalog, roster, wire

MATCH_ID = "00000000-1111-4222-8333-444455556666"
HEROES = ("Skye", "Ringo", "Catherine", "Gwen", "Adagio", "Amael")
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


class Participant:
    """A socket owner with a continuously drained stream and bounded waits."""

    def __init__(self, host, port, match_id, hero, output, *, identity=None, heartbeat_port=2112):
        self.host, self.port = private_host(host), port
        self.heartbeat_port = heartbeat_port
        self.hero, self.hero_id = hero, hero_catalog.resolve_hero_id(hero)
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
                   'record_index':self.record_count}
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
                "eid": self.eid, "slot": self.slot, "team": self.team,
                "stages": self.stages, "receive_error": self.error,
                "wire_log": str(Path(self.log.name).resolve())}


def enter_world(participants, timeout=35):
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
        payload = struct.pack(">II", p.hero_id, 0) + bytes(6)
        p.input("select", 1118, payload)
        p.prove("select", [p.wait(lambda op, b: op == 1118 and b == payload, after=mark)])
    marks = []
    for p in participants:
        marks.append(p.begin("lock"))
        p.input("lock", 1123, bytes(6))
        p.input("lock", 1119, bytes(6))
    for p, mark in zip(participants, marks):
        p.prove("lock", [p.wait(lambda op, b: op == 1123, after=mark),
                         p.wait(lambda op, b: op == 1132, after=mark, timeout=timeout)])
    marks = [p.begin("ready") for p in participants]
    for p in participants:
        p.input("ready", 1134, bytes(6))
        p.input("ready", 1137, roster.build_hero_ready_ack(p.eid))
    for p, mark in zip(participants, marks):
        block = p.wait(lambda op, b: op == 1011 and u32(b, 8) == p.eid and u32(b) == p.hero_id, after=mark, timeout=timeout)
        echo = p.wait(lambda op, b: op == 1137 and b == roster.build_hero_ready_ack(p.eid), after=mark, timeout=timeout)
        world = p.wait(lambda op, b: op == 1116, after=mark, timeout=timeout)
        p.prove("ready", [block, echo, world])


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


def play(participants, timeout=75):
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
    for index, p in enumerate(participants):
        target = participants[index ^ 1]
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
    reconnect(participants[0])


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


def full_match(participants, output, *, timeout=2400, stall_seconds=300, soak=False):
    from Tools.protocol_policy import Policy
    policies = [Policy(p.eid,p.hero,defend_farm=soak) for p in participants]
    start = time.monotonic()
    last_progress, destroyed = start, set()
    reconnect_thread, reconnect_errors = None, []
    reconnect_before = None
    soak_started = None
    def reconnect_once():
        try:
            reconnect(participants[4])
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
                                    for p in participants if p is not participants[4]}}
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
                                for p in participants if p is not participants[4]}}
                if reconnect_thread is None and now-start > 70 and any(p.observer.minion_spawns for p in participants):
                    reconnect_before = {p.hero:p.message_count for p in participants}
                    reconnect_thread = threading.Thread(target=reconnect_once,name='m3-reconnect')
                    reconnect_thread.start()
                for index,(p,policy,actors) in enumerate(zip(participants,policies,views)):
                    if p is participants[4] and reconnect_thread and reconnect_thread.is_alive():
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


def run(host, port, output, *, match_id=MATCH_ID, heartbeat_port=2112, mode="existing-server", inputs=None, lifecycle=False, soak=False):
    summary = {"source": source_identity(), "host": private_host(host), "port": port,
               "mode": mode, "started_at": time.time(), 'started_monotonic_ns':time.monotonic_ns(), "status": "RUNNING",
               "setup_failures": [], "gameplay_failures": [], "owned_inputs": inputs,
               "limits": ["Protocol/session evidence, not native-client behavior or independent gameplay fidelity.",
                          "One rank-one cast per hero; no complete-kit, full-match or exact-replay claim.",
                          "Gold uses the native 600 initial baseline plus received deltas."]}
    participants = [Participant(host, port, match_id, hero, output, heartbeat_port=heartbeat_port) for hero in HEROES]
    entered = False
    try:
        enter_world(participants)
        entered = True
        if lifecycle or soak:
            summary['limits'] = ['Wire-only server/session acceptance, not native rendering or independent gameplay fidelity.',
                                 'Nonhero HP unknown until an HP-bearing snapshot; gold starts at native 600.',
                                 'Hero resources become unknown after implicit 1076 growth until a numeric baseline; no fabricated HP.',
                                 'Tick anchors from journal; per-stream evidence independently received.']
            summary.update(full_match(participants,output,soak=soak))
        else:
            play(participants)
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
    output = new_output(args.output)
    print(f"Evidence: {output}", flush=True)
    server = None
    telemetry = None
    inputs = None
    try:
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
                      lifecycle=args.full_match, soak=args.soak)
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

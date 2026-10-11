"""Bounded, wire-derived participant state. Unknown resource baselines stay unknown."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
import struct

from server import cooldown_wire, roster


def u32(body, offset=0):
    return struct.unpack_from('>I', body, offset)[0]


def f32(body, offset):
    return struct.unpack_from('>f', body, offset)[0]


@dataclass
class Actor:
    eid: int
    kind: str
    team: int
    slot: int
    generation: int = 0
    archetype: int = 0
    hero_id: int = 0
    position: tuple[float, float] | None = None
    destination: tuple[float, float] | None = None
    spawn: tuple[float, float] | None = None
    hp: float | None = None
    max_hp: float | None = None
    energy: float | None = None
    max_energy: float | None = None
    resource_unknown: str | None = None
    barrier: float = 0.0
    fortified: float = 0.0
    gold: float | None = None
    points: float = 0.0
    level: int = 1
    alive: bool = True
    lifecycle: str = 'alive'
    ranks: dict[int, int] = field(default_factory=dict)
    inventory: dict[int, int] = field(default_factory=dict)
    timers: dict = field(default_factory=dict)
    damage_received: float = 0.0
    tier: int = 0


class Observer:
    def __init__(self, identity='', retention=4096):
        self.identity = identity
        self.owner = None
        self.actors: dict[int, Actor] = {}
        self.slots: dict[int, int] = {}
        self.slot_generations: Counter = Counter()
        self.window = deque(maxlen=retention)
        self.counts = Counter()
        self.sequence = 0
        self.result = None
        self.crystal_notice = None
        self.crystal_death = None
        self.deaths = self.revivals = self.minion_spawns = 0
        self.own_purchases = self.own_learns = 0
        self.structure_deaths: dict[int, dict] = {}
        self.structure_order_errors = []
        self.spawns = {}

    def reconnect(self):
        # Catchup is a fresh baseline, not additive replay onto old ranks/pools.
        self.actors.clear()
        self.slots.clear()

    def bind(self, actor):
        old = self.slots.get(actor.slot)
        if old != actor.eid:
            self.slot_generations[actor.slot] += 1
            if old is not None:
                self.actors.pop(old, None)
        actor.generation = self.slot_generations[actor.slot]
        self.slots[actor.slot] = actor.eid
        self.actors[actor.eid] = actor

    def consume(self, op, b, row=None):
        self.sequence += 1
        self.counts[op] += 1
        evidence = {'sequence': self.sequence, **(row or {}), 'opcode': op}
        self.window.append(evidence)
        eid = u32(b) if len(b) >= 4 else None
        a = self.actors.get(eid)
        if op == 1001:
            self.owner = eid
        elif op == 1113:
            for i in range(6):
                p = b[8+i*roster.SNAPSHOT_RECORD_STRIDE:8+(i+1)*roster.SNAPSHOT_RECORD_STRIDE]
                if len(p) == roster.SNAPSHOT_RECORD_STRIDE and p[97:161].split(b'\0')[0].decode('ascii') == self.identity:
                    self.owner = struct.unpack_from('>H', p, 11)[0]
        elif op == 1011:
            eid = u32(b, 8)
            position = (f32(b, 18), f32(b, 26))
            self.spawns.setdefault(eid, position)
            a = Actor(eid, 'hero', u32(b, 12), b[745], hero_id=u32(b),
                      position=position, spawn=self.spawns[eid],
                      hp=f32(b, 42), max_hp=f32(b, 46), energy=f32(b, 122), max_energy=f32(b,126),
                      gold=600.0, level=int(f32(b, 294)), points=f32(b, 314))
            a.alive = a.hp > 0
            self.bind(a)
        elif op == 1010 and len(b) in (122, 126):
            archetype, cls, eid = struct.unpack_from('>III', b)
            a = self.actors.get(eid)
            if a is None:
                kind = ('structure' if cls == 0xC10B41DA and archetype in (292,293,369,370,371,372)
                        else 'minion' if cls == 0xEB39CE55
                        else 'neutral' if archetype in range(357,365) else 'other')
                a = Actor(eid, kind, b[121], b[116], archetype=archetype,
                          tier={371:1,370:2,369:3,372:4,292:5,293:5}.get(archetype,0))
                self.bind(a)
                if kind == 'minion':
                    self.minion_spawns += 1
            a.position = (f32(b,12), f32(b,20))
            if len(b) == 122:
                a.hp, a.max_hp = struct.unpack_from('>ff', b,36)
                a.alive = a.hp > 0
        elif op == 1035 and a:
            if self.slots.get(a.slot) == eid:
                del self.slots[a.slot]
            del self.actors[eid]
        elif op == 1070 and a:
            a.position = struct.unpack_from('>ff', b,4)
        elif op == 1016:
            actor = self.actors.get(self.slots.get(b[0]))
            if actor:
                actor.destination = struct.unpack_from('>ff', b,1)
        elif op == 1053 and a:
            name = {0:'hp',2:'energy',4:'barrier',5:'fortified',6:'gold'}.get(b[8])
            if name and getattr(a,name) is not None:
                setattr(a,name,max(0.0,getattr(a,name)+f32(b,4)))
        elif op == 1054 and a:
            delta = f32(b,8)
            a.damage_received += max(0,-delta)
            if delta < 0:
                absorbed = min(a.barrier,-delta)
                a.barrier -= absorbed
                delta += absorbed
                if a.hp is not None:
                    absorbed = min(a.fortified,a.hp,-delta*.5)
                    a.fortified -= absorbed
                    delta += absorbed
            if a.hp is not None:
                a.hp = max(0.0,a.hp+delta)
        elif op == 1052 and a and len(b) >= 14 and b[12] in (0,2):
            name = 'max_hp' if b[12] == 0 else 'max_energy'
            maximum = getattr(a,name)
            if b[13] == 1 and maximum is not None:
                setattr(a,name,maximum+f32(b,8))
            elif len(b) >= 15 and b[14] == 1:
                setattr(a,name,f32(b,8))
        elif op == 1076 and a:
            a.level += u32(b,4)
            a.points += u32(b,4)
            # 1076 invokes archetype growth in the native client; the growth
            # numbers are NOT in this frame. Do not pretend old HP is current.
            a.hp = a.max_hp = a.energy = a.max_energy = None
            a.resource_unknown = '1076 implicit growth; numeric baseline unavailable'
        elif op == 1082 and a:
            action = u32(b,4)
            a.ranks[action] = a.ranks.get(action,0)+1
            # Reconnect 1011 includes allocated points; each replay consumes one.
            a.points -= 1
            if eid == self.owner:
                self.own_learns += 1
        elif op == 1085 and a:
            a.inventory[u32(b,8)] = u32(b,4)
            if eid == self.owner and u32(b,4) in (458,469,505,464,471):
                self.own_purchases += 1
        elif op == 1099 and a:
            a.inventory.pop(u32(b,4),None)
        elif op == 1162 and a:
            timer = cooldown_wire.parse_timer_tick(b)
            a.timers[timer.tag] = timer
        elif op in (1072,1075,1073,1033,1074) and a:
            if op == 1072 and len(b) >= 8:
                a.alive, a.lifecycle, a.hp = False, 'dead', 0.0
                if a.kind == 'hero':
                    self.deaths += 1
                if a.kind == 'structure':
                    if eid not in self.structure_deaths:
                        preceding = [other.eid for other in self.actors.values()
                                     if other.kind == 'structure' and other.team == a.team
                                     and other.tier < a.tier and other.alive]
                        if preceding:
                            self.structure_order_errors.append({'eid':eid,'preceding_alive':preceding})
                    self.structure_deaths.setdefault(eid,evidence)
                    if a.tier == 5:
                        self.crystal_death = evidence
            elif op == 1075:
                a.lifecycle = 'countdown'
            elif op == 1073:
                a.alive, a.lifecycle = False, 'hidden'
            elif op in (1033,1074):
                a.position = (f32(b,4),f32(b,12))
                a.lifecycle = 'revived' if op == 1074 else 'returning'
                if op == 1074:
                    a.alive = True
                    a.hp, a.energy = a.max_hp, a.max_energy
                    self.revivals += 1
        elif op == 1106:
            self.crystal_notice = evidence
        elif op == 1009:
            self.result = {**evidence,'winner':eid,'reason':b[4]}

    def finished(self):
        return bool(self.result and self.result['winner'] in (1,2) and self.result['reason'] == 0
                    and self.crystal_notice and self.crystal_death
                    and self.crystal_notice['sequence'] < self.crystal_death['sequence'] < self.result['sequence'])

    def metrics(self):
        return {'actors':len(self.actors),'slots':len(self.slots),'retained':len(self.window),
                'frames':self.sequence,'minion_spawns':self.minion_spawns,
                'own_purchases':self.own_purchases,'own_learns':self.own_learns,
                'hero_deaths':self.deaths,'hero_revivals':self.revivals,
                'structure_order_errors':self.structure_order_errors,
                'structure_deaths':self.structure_deaths,'result':self.result,
                'crystal_notice':self.crystal_notice,'crystal_death':self.crystal_death}

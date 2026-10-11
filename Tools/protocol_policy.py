"""Modest asymmetric human-paced rules, consuming only decoded wire actors."""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from server import ability_wire, roster
from Tools.protocol_observer import Actor


@dataclass(frozen=True)
class Intent:
    opcode: int
    payload: bytes
    reason: str


class Policy:
    def __init__(self, eid, hero):
        self.eid, self.hero = eid, hero
        self.target = None
        self.last_order = None
        self.next_action = 0.0
        self.next_learn = self.next_shop = 0.0
        self.retreating = False
        self.recalling_until = 0.0
        self.was_dead = False

    def order(self, now, opcode, payload, reason):
        key = opcode,payload
        if key == self.last_order:
            return None
        self.last_order = key
        self.next_action = now+1.0
        return Intent(opcode,payload,reason)

    def move(self, now, point, reason):
        self.target = None
        return self.order(now,1012,roster.build_move(*point),reason)

    def step(self, actors: dict[int, Actor], now):
        me = actors.get(self.eid)
        if me is None or me.position is None or now < self.next_action:
            return None
        if not me.alive:
            self.was_dead = True
            self.last_order = self.target = None
            self.retreating = False
            return None
        if self.was_dead:
            # Only 1074 changes an observed dead actor back to alive.
            self.was_dead = False
            self.recalling_until = 0
        if now < self.recalling_until:
            return None
        if me.points >= 1 and now >= self.next_learn:
            for slot in (0,1,2):
                action = ability_wire.hero_action_variant(me.hero_id,'ABC'[slot])
                rank = me.ranks.get(action,0)
                levels = (6,9,12) if slot == 2 else (1,2,4,6,8)
                if rank < len(levels) and me.level >= levels[rank]:
                    self.next_learn = now+3
                    self.next_action = now+1
                    return Intent(1078,roster.build_ability_cast(slot),'learn available point')
        at_base = me.spawn is not None and math.dist(me.position,me.spawn) < 5
        items = list(me.inventory.values())
        if at_base:
            self.retreating = False
            if now >= self.next_shop and me.gold is not None:
                # Public catalog prices, not an economy accessor. Conservative full
                # prices are safe even if owned components reduce the actual fee.
                wishes = ((458,300),(469,300),(505,1150),(464,3100),(471,1900))
                for item,cost in wishes:
                    satisfied = (item in items or item in (458,505) and 464 in items
                                 or item == 458 and 505 in items or item == 469 and 471 in items)
                    if not satisfied and me.gold >= cost:
                        self.next_shop = now+3
                        self.next_action = now+1
                        return Intent(1081,roster.build_shop_buy(me.eid,item),'base purchase')
            if me.hp is not None and me.max_hp and me.hp < .85*me.max_hp:
                return None
        elif me.hp is not None and me.max_hp and me.hp < .25*me.max_hp:
            self.retreating = True
        if self.retreating:
            nearby = [a for a in actors.values() if a.alive and a.position
                      and a.team not in (0,me.team) and a.kind in ('hero','minion','structure')
                      and math.dist(a.position,me.position) < 12]
            if nearby:
                return self.move(now,me.spawn,'retreat toward base')
            self.target = self.last_order = None
            self.recalling_until = now+5
            action = ability_wire.hero_action_variant(me.hero_id,'recall')
            return Intent(1041,struct.pack('>IBB',0xffffffff,action,0),'safe recall')
        structures = [a for a in actors.values() if a.kind == 'structure' and a.alive and a.position]
        enemies = [a for a in structures if a.team != me.team]
        if not enemies:
            return None
        lowest = min(a.tier for a in enemies)
        objective = min((a for a in enemies if a.tier == lowest),key=lambda a:math.dist(a.position,me.position))
        active = actors.get(self.target)
        if active and active.alive and active.position and math.dist(active.position,me.position) < 22:
            return None  # A target order persists; do not reset windup every poll.
        candidates = [a for a in actors.values() if a.alive and a.position and a.eid != me.eid
                      and a.team not in (0,me.team) and a.kind in ('minion','hero')
                      and math.dist(a.position,me.position) < 12]
        if me.team == 2 and self.hero != 'Ringo':
            # Two defensive farmers stay on their own side, away from the push.
            candidates = [a for a in actors.values() if a.alive and a.position
                          and a.kind == 'neutral' and a.archetype in (357,359)
                          and a.position[0] > 20 and math.dist(a.position,me.position) < 18]
            destination = (35.0,28.0) if self.hero == 'Gwen' else (55.0,25.0)
        elif me.team == 2:
            own = [a for a in structures if a.team == me.team]
            front = min(own,key=lambda a:a.tier)
            destination = (front.position[0]-4,front.position[1])
        else:
            destination = objective.position
            # Support the wave; allow a reduced-damage tower attempt after
            # clearing nearby enemies. Low-HP retreat is still mandatory.
            if math.dist(me.position,objective.position) < 17 and not candidates:
                candidates = [objective]
        if candidates:
            target = min(candidates,key=lambda a:(0 if a.kind == 'minion' else 1,math.dist(a.position,me.position),a.eid))
            self.target = target.eid
            return self.order(now,1060,roster.build_target_entity(target.eid),'attack '+target.kind)
        return self.move(now,destination,'lane push' if me.team == 1 else 'defend/farm')

"""Modest asymmetric human-paced rules, consuming only decoded wire actors."""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct

from server import ability_wire, roster
from Tools.protocol_observer import Actor


MIXED_STRUCTURE_MARGIN = 2.0
MIXED_ENGAGEMENT_RADIUS = 7.0  # Conservative envelope for the existing CE target path.
MIXED_CLEAN_RADIUS = 3.0  # Both inside => pair separation <=6, before ordinary pursuit.


def mixed_structure_zones(point, *, teams=(1, 2), start=None):
    """Production centre-distance attack zones, conservatively including dead towers.

    Turrets acquire/retain at <= attack_range (no bounding-radius addition).
    The zero-range crystals retain the same two-unit exclusion margin. For
    movement, check the whole segment, not just an endpoint outside the circle.
    """
    from server.structures import STRUCTURE_TEMPLATES
    from server.hitboxes import segment_distance
    points = (point,) if start is None else (point, start)
    if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points):
        raise ValueError('mixed structure geometry requires finite two-dimensional points')
    zones = []
    for s in STRUCTURE_TEMPLATES:
        if s.team not in teams:
            continue
        distance = (math.dist(point, (s.x, s.y)) if start is None else
                    segment_distance((s.x, s.y), start, point))
        if distance <= s.attack_range + MIXED_STRUCTURE_MARGIN:
            zones.append({'eid': s.eid, 'team': s.team, 'position': [s.x, s.y],
                          'attack_range': s.attack_range, 'margin': MIXED_STRUCTURE_MARGIN,
                          'distance': distance})
    return zones


class MixedRendezvous:
    """Fixed lane staging geometry; only the mixed harness consumes this.

    Derive x from the opposing outer turrets. Move the midpoint toward the
    lower lane edge just far enough to clear every expanded structure circle,
    rounding down to a quarter unit. Refuse an off-mesh result, never project it
    silently. The clean disk is smaller than the reserved engagement envelope.
    """
    def __init__(self, mesh, *, structures=None, candidate=None):
        from server.structures import STRUCTURE_TEMPLATES
        self.mesh = mesh
        self.structures = tuple(STRUCTURE_TEMPLATES if structures is None else structures)
        outer = [s for s in self.structures if s.tier == 1]
        if len(outer) != 2 or {s.team for s in outer} != {1, 2}:
            raise ValueError('mixed rendezvous requires two opposing outer structures')
        x, y = (sum(getattr(s, axis) for s in outer)/2 for axis in ('x', 'y'))
        if candidate is None:
            for s in self.structures:
                radius = s.attack_range + MIXED_STRUCTURE_MARGIN + MIXED_ENGAGEMENT_RADIUS
                dx = abs(s.x-x)
                if dx < radius:
                    y = min(y, s.y-math.sqrt(radius**2-dx**2))
            candidate = (x, math.floor(y*4)/4)
        self.point = tuple(candidate)
        if (len(self.point) != 2 or not all(math.isfinite(v) for v in self.point)
                or not mesh.contains(self.point)):
            raise ValueError('mixed rendezvous candidate off-mesh or nonfinite')
        self.clearances = [dict(eid=s.eid, team=s.team, position=[s.x, s.y],
            attack_range=s.attack_range, margin=MIXED_STRUCTURE_MARGIN,
            clearance=math.dist(self.point, (s.x, s.y))-s.attack_range-MIXED_STRUCTURE_MARGIN)
            for s in self.structures]
        if any(row['clearance'] < MIXED_ENGAGEMENT_RADIUS for row in self.clearances):
            raise ValueError('mixed rendezvous candidate inside expanded structure zone')
        self.stage_points = {s.team: (self.point[0]+math.copysign(1.5, s.x-self.point[0]),
                                     self.point[1]) for s in outer}
        if any(not mesh.contains(p) or math.dist(p, self.point) > MIXED_CLEAN_RADIUS-1.0
               for p in self.stage_points.values()):
            raise ValueError('mixed stage point off-mesh or outside clean margin')

    def stage_point(self, team):
        if team not in (1, 2):
            raise ValueError('mixed rendezvous requires an observed team')
        return self.stage_points[team]

    def evidence(self):
        return dict(point=self.point, clean_radius=MIXED_CLEAN_RADIUS,
                    engagement_radius=MIXED_ENGAGEMENT_RADIUS, on_mesh=True,
                    structures=self.clearances,
                    stages={team: dict(point=p, on_mesh=self.mesh.contains(p),
                        structures=[dict(eid=s.eid, team=s.team,
                            clearance=math.dist(p, (s.x, s.y))-s.attack_range-MIXED_STRUCTURE_MARGIN)
                            for s in self.structures]) for team, p in self.stage_points.items()})

    def contains(self, point):
        return (point is not None and len(point) == 2 and all(math.isfinite(v) for v in point)
                and self.mesh.contains(point) and math.dist(point, self.point) <= MIXED_CLEAN_RADIUS)

    def route(self, origin, team):
        """Check the destination AND every nav step/segment against enemy zones."""
        from server.hitboxes import segment_distance
        if team not in (1, 2):
            raise ValueError('mixed rendezvous requires an observed team')
        goal = self.stage_point(team)
        route = self.mesh.find_path(origin, goal)
        if not route and math.dist(origin, goal) <= 1e-3 and self.mesh.contains(origin):
            route = [goal]  # Ordinary zero-distance move cancels a target.
        if not route or math.dist(route[-1], goal) > 1e-3:
            raise ValueError('mixed rendezvous route unavailable')
        previous = origin
        for point in route:
            if any(s.team != team and segment_distance((s.x, s.y), previous, point)
                   <= s.attack_range+MIXED_STRUCTURE_MARGIN for s in self.structures):
                raise ValueError('mixed rendezvous route enters enemy structure zone')
            previous = point
        return route


@dataclass(frozen=True)
class Intent:
    opcode: int
    payload: bytes
    reason: str


class Policy:
    def __init__(self, eid, hero, *, defend_farm=False, opponent_eid=None, mixed_pair=None,
                 rendezvous=None):
        self.eid, self.hero = eid, hero
        self.target = None
        self.last_order = None
        self.next_action = 0.0
        self.next_learn = self.next_shop = 0.0
        self.retreating = False
        self.recalling_until = 0.0
        self.was_dead = False
        self.defend_farm = defend_farm
        self.next_restock = 120.0
        self.opponent_eid = opponent_eid
        self.mixed_pair = tuple(mixed_pair) if mixed_pair is not None else None
        self.hold = None
        self.rendezvous = rendezvous
        self.engagement = None

    def mixed_stage(self, me, opponent, now):
        if self.rendezvous is None:
            from server.navigation import load_halcyon_navmesh
            self.rendezvous = MixedRendezvous(load_halcyon_navmesh())
        clean = (opponent.alive and self.rendezvous.contains(me.position)
                 and self.rendezvous.contains(opponent.position))
        self.engagement = dict(phase='engagement' if clean else 'staging',
            owner=me.position, opponent=opponent.position, rendezvous=self.rendezvous.point)
        if clean:
            return True, None
        # This cancellation has priority over pacing, learning and shopping:
        # a persistent target must not pursue an actor leaving the clean disk.
        self.rendezvous.route(me.position, me.team)
        return False, self.move(now, self.rendezvous.stage_point(me.team), 'mixed rendezvous staging')

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
        self.hold = None
        self.engagement = None
        me = actors.get(self.eid)
        mixed_opponent = self.mixed_pair is not None and self.opponent_eid is not None
        if me is None or me.position is None or (not mixed_opponent and now < self.next_action):
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
        if mixed_opponent:
            opponent = actors.get(self.opponent_eid)
            if opponent is None or opponent.kind != 'hero' or opponent.team in (0, me.team):
                raise ValueError('declared opponent missing or not an opposing hero')
            clean, intent = self.mixed_stage(me, opponent, now)
            if not clean:
                return intent
            if now < self.next_action:
                return None
            self.target = opponent.eid
            return self.order(now, 1060, roster.build_target_entity(opponent.eid), 'attack declared opponent')
        if now < self.next_action:
            return None
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
            self.next_restock = now + 120.0
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
        if self.defend_farm and not at_base and now >= self.next_restock:
            self.retreating = True
        if self.retreating:
            nearby = [a for a in actors.values() if a.alive and a.position
                      and (a.team not in (0,me.team) and a.kind in ('hero','minion','structure')
                           or self.defend_farm and a.kind == 'neutral')
                      and math.dist(a.position,me.position) < 12]
            if nearby:
                return self.move(now,me.spawn,'retreat toward base')
            self.target = self.last_order = None
            self.recalling_until = now+5
            action = ability_wire.hero_action_variant(me.hero_id,'recall')
            return Intent(1041,struct.pack('>IBB',0xffffffff,action,0),'safe recall')
        if self.defend_farm:
            return self._defend_farm(actors, me, now)
        if self.opponent_eid is not None:
            opponent = actors.get(self.opponent_eid)
            if opponent is None or opponent.kind != 'hero' or opponent.team in (0, me.team):
                raise ValueError('declared opponent missing or not an opposing hero')
            if not opponent.alive or opponent.position is None:
                return self.move(now, me.position, 'stop: declared opponent unavailable')
            if math.dist(opponent.position, me.position) < 8:
                self.target = opponent.eid
                return self.order(now, 1060, roster.build_target_entity(opponent.eid), 'attack declared opponent')
            return self.move(now, opponent.position, 'approach declared opponent')
        if self.mixed_pair is not None:
            # Other participants retain the existing defensive lane/farm policy,
            # with the measured pair and its immediate vicinity excluded. No
            # minion simulation or damage is altered.
            pair = [actors.get(eid) for eid in self.mixed_pair]
            if any(a is None or a.position is None for a in pair):
                raise ValueError('mixed protected pair positions unavailable')
            safe = {eid: a for eid, a in actors.items() if eid not in self.mixed_pair
                    and (a.eid == me.eid or a.kind == 'structure' or a.position is not None
                         and all(math.dist(a.position, p.position) >= 12 for p in pair))}
            home = -1 if me.team == 1 else 1
            if any(math.dist(me.position, p.position) < 12 for p in pair):
                self.hold = {'reason': 'mixed pair non-interference', 'pair': self.mixed_pair}
                return self.move(now, me.spawn, 'mixed move away from protected pair')
            intent = self._defend_farm(safe, me, now)
            if intent and intent.opcode == 1012:
                goal = struct.unpack_from('>ff', intent.payload)
                from server.hitboxes import segment_distance
                if any(segment_distance(p.position, me.position, goal) < 12 for p in pair):
                    self.hold = {'reason': 'mixed lane path approaches protected pair', 'pair': self.mixed_pair}
                    return self.move(now, (home*40.9, 20.3), 'mixed lane/farm away from pair')
            return intent
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

    def _defend_farm(self, actors, me, now):
        """Ordinary orders only: two defenders + one farmer on each team.

        No structure target, enemy-base destination or persistent pursuit across
        the river. Restocking still uses ordinary walking/Recall and shop input.
        This intentionally claims stability, never a completed match.
        """
        home = -1 if me.team == 1 else 1
        farmer = self.hero in ('Adagio', 'Amael')
        own = [a for a in actors.values() if a.kind == 'structure'
               and a.team == me.team and a.alive and a.position]
        if not own:
            return self.move(now, me.spawn, 'soak defend base')
        front = min(own, key=lambda a: (a.tier, a.eid))
        destination = ((home * 40.9, 20.3) if farmer
                       else (front.position[0] - home * 4, front.position[1]))
        if home * me.position[0] < -4:
            return self.move(now, destination, 'soak stop cross-river pursuit')
        candidates = [a for a in actors.values() if a.alive and a.position
                      and home * a.position[0] >= -4
                      and math.dist(a.position, me.position) < 18
                      and (a.kind == 'neutral' and a.archetype in (357,359) if farmer else
                           a.kind in ('minion','hero') and a.team not in (0,me.team))]
        active = actors.get(self.target)
        # Preserve windup for the active category, but defend against a new
        # wave rather than chasing a hero while its minions pass our tower.
        priority = min((0 if a.kind == 'minion' else 1 for a in candidates), default=2)
        if active in candidates and (0 if active.kind == 'minion' else 1) == priority:
            return None
        if candidates:
            target = min(candidates, key=lambda a: (0 if a.kind == 'minion' else 1,
                          math.dist(a.position, me.position), a.eid))
            self.target = target.eid
            return self.order(now,1060,roster.build_target_entity(target.eid),'soak attack '+target.kind)
        return self.move(now,destination,'soak farm' if farmer else 'soak defend')

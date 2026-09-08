"""Fixed-point hero locomotion and lifecycle; attack resolution is world-owned.

Sessions inject the external A001 NavMesh. The wire uses floats only at the
boundary; position integration and pathfinding use integer coordinates.
"""
from __future__ import annotations

import math
from . import roster, wire
from .navigation import SCALE, fixed, within_distance
from . import lifecycle_wire, recall_wire

RECALL_SECONDS = recall_wire.RECALL_SECONDS
BASE_RADIUS = 8.0
FOUNTAIN_REGEN_FRACTION = 0.15
FOUNTAIN_LASER_DAMAGE = 1000.0
RESPAWN_SECONDS_PER_MINUTE = 1.0  # Explicit policy, not a recovered coefficient.


class HeroMovement:
    def __init__(
        self, eid=1500, team=1, x=None, y=None, speed=roster.MOVE_SPEED,
        hp=roster.HERO_BASE_HP, max_hp=roster.HERO_BASE_HP,
        attack_damage=roster.HERO_BASE_ATTACK_DAMAGE,
        attack_range=roster.HERO_ATTACK_RANGE,
        attack_cooldown=roster.HERO_ATTACK_COOLDOWN,
        respawn_duration=None, *, navigation=None,
        energy=300.0, max_energy=300.0, energy_regen=2.5,
        energy_stat_type=2,
    ):
        self.eid, self.team = eid, team
        fallback = roster.HERO_SPAWNS.get(1500 if team == 1 else 1517, (roster.SPAWN_X, roster.SPAWN_Y))
        spawn = roster.HERO_SPAWNS.get(eid, fallback)
        self.spawn_x = spawn[0] if x is None else x
        self.spawn_y = spawn[1] if y is None else y
        self.x, self.y = self.spawn_x, self.spawn_y
        self.navigation = navigation
        self.base_speed = speed
        self.item_move_speed = 0.0
        self.attr_0x284 = self.attr_0x1D0 = 0.0
        self._speed_modifiers = {}
        self._movement_remainder = 0
        self.hp, self.max_hp = hp, max_hp
        self.max_energy = max(0.0, max_energy)
        self.energy = min(self.max_energy, max(0.0, energy))
        self.energy_regen = max(0.0, energy_regen)
        self.base_max_energy, self.base_energy_regen = self.max_energy, self.energy_regen
        # vgfull: discriminator 0 = HP, 2 = energy, 6 = gold; resource
        # updates share tail 0001000000 (measured alongside regeneration/casts).
        self.energy_stat_type = energy_stat_type
        self.attack_damage, self.attack_range = attack_damage, attack_range
        self.attack_cooldown = attack_cooldown
        self.respawn_duration = respawn_duration
        self.armor, self.shield = 25.0, 20.0
        self.armor_pierce = self.shield_pierce = self.damage_reduction = 0.0
        self.base_max_hp, self.base_attack_damage = max_hp, attack_damage
        self.base_armor, self.base_shield = 25.0, 20.0
        self.crystal_power = self.bonus_attack_speed = 0.0
        self.cooldown_reduction = 0.0
        self.level = 1
        self.is_alive = True
        self.respawn_at = None
        self.respawn_relocation_at = None
        self.respawn_relocated = False
        self.corpse_hide_at = None
        self.corpse_hidden = False
        self.match_elapsed = 0.0
        self.target_eid = None
        self.next_attack_at = 0.0
        self.order_version = 0
        self.channeling = False
        self._pursuit_destination = None
        self.facing = roster.FACING_DEFAULT
        self.waypoints, self.move_target = [], None
        self.is_moving = self._start_emitted = self.just_respawned = False
        self.recall_started_at = self.recall_completes_at = None
        self.last_recall_completed_at = None
        self._next_fountain_laser_at = 0.0

    @property
    def x(self):
        return self._x_fixed / SCALE

    @x.setter
    def x(self, value):
        self._x_fixed = fixed(value)

    @property
    def y(self):
        return self._y_fixed / SCALE

    @y.setter
    def y(self, value):
        self._y_fixed = fixed(value)

    @property
    def position_fixed(self):
        return self._x_fixed, self._y_fixed

    @property
    def attr_0x11C(self):
        return self.base_speed

    @attr_0x11C.setter
    def attr_0x11C(self, value):
        self.base_speed = value

    @property
    def attr_0x68(self):
        return self.item_move_speed

    @attr_0x68.setter
    def attr_0x68(self, value):
        self.item_move_speed = value

    @property
    def speed(self):
        """Unbuffed base plus equipment speed, for legacy stat consumers."""
        return self.base_speed + self.item_move_speed

    @speed.setter
    def speed(self, value):
        self.base_speed = value - self.item_move_speed

    def add_speed_modifier(self, key, *, bonus=0.0, multiplier=0.0, expires_at):
        self._speed_modifiers[key] = bonus, multiplier, expires_at

    def remove_speed_modifier(self, key):
        self._speed_modifiers.pop(key, None)

    def effective_speed(self, now=None, status_multiplier=1.0, status_manager=None):
        flat, ratio = self.attr_0x68, self.attr_0x284
        for key in sorted(self._speed_modifiers):
            bonus, multiplier, expires_at = self._speed_modifiers[key]
            if now is None or expires_at > now:
                flat += bonus
                ratio += multiplier
        if status_manager is not None and now is not None:
            if hasattr(status_manager, 'get_flat_speed_bonus'):
                flat += status_manager.get_flat_speed_bonus(self.eid, now)
            if hasattr(status_manager, 'get_move_speed_bonus_ratio'):
                ratio += status_manager.get_move_speed_bonus_ratio(self.eid, now)
        return max(0.0, ((1 + ratio) * self.attr_0x11C + flat) * (1 + self.attr_0x1D0) * status_multiplier)

    def is_in_base(self, team=None):
        base_team = self.team if team is None else team
        center = roster.HERO_SPAWNS[1500 if base_team == 1 else 1517]
        dx, dy = self._x_fixed - fixed(center[0]), self._y_fixed - fixed(center[1])
        return dx * dx + dy * dy <= fixed(BASE_RADIUS) ** 2

    def _energy_frames(self, delta):
        if not delta or self.energy_stat_type is None:
            return []
        return [(wire.OP.ENTITY_STAT, roster.build_hero_stat(self.eid, delta, stat_type=self.energy_stat_type, tail=bytes.fromhex('0001000000')))]

    def spend_energy(self, amount):
        if not math.isfinite(amount) or amount < 0 or amount > self.energy:
            raise ValueError('invalid or unaffordable energy cost')
        self.energy -= amount
        return self._energy_frames(-amount)

    def heal(self, amount, now=0.0, status_manager=None):
        if not self.is_alive or amount <= 0:
            return []
        if status_manager is not None and hasattr(status_manager, 'get_healing_multiplier'):
            amount *= status_manager.get_healing_multiplier(self.eid, now)
        actual = min(max(0.0, amount), self.max_hp - self.hp)
        self.hp += actual
        return [(wire.OP.ENTITY_STAT, roster.build_hero_stat(self.eid, actual, stat_type=0, tail=bytes.fromhex('0001000000')))] if actual else []

    def start_recall(self, now):
        if not self.is_alive:
            return []
        self.order_version += 1
        frames = self.stop(input_order=False)
        self.target_eid = None
        self.recall_started_at, self.recall_completes_at = now, now + RECALL_SECONDS
        return frames

    def cancel_recall(self):
        was_active = self.recall_completes_at is not None
        self.recall_started_at = self.recall_completes_at = None
        return was_active

    def respawn_seconds(self, match_elapsed=None):
        if self.respawn_duration is not None:
            return self.respawn_duration
        elapsed = self.match_elapsed if match_elapsed is None else match_elapsed
        return 6.0 + self.level * 2.5 + max(0, int(elapsed // 60)) * RESPAWN_SECONDS_PER_MINUTE

    def tick_lifecycle(self, dt, now, match_elapsed=None, status_manager=None):
        if dt < 0 or not math.isfinite(dt):
            raise ValueError('invalid lifecycle delta time')
        if match_elapsed is not None:
            self.match_elapsed = max(0.0, match_elapsed)
        if not self.is_alive:
            return self.check_respawn(now)
        frames = []
        if self.recall_completes_at is not None:
            if status_manager is not None and (
                not status_manager.can_cast(self.eid, now) or not status_manager.can_move(self.eid, now)
            ):
                self.cancel_recall()
            elif now >= self.recall_completes_at:
                self.cancel_recall()
                frames.extend(self.teleport(self.spawn_x, self.spawn_y))
                self.last_recall_completed_at = now
                # Successful Recall has a one-time 25% refill before ordinary
                # fountain regeneration. The native positive self-1054 changes
                # HP itself, so discard heal()'s alternative 1053 encoding.
                before_hp = self.hp
                if self.hp < self.max_hp:
                    self.heal(self.max_hp * recall_wire.RECALL_RESOURCE_FRACTION, now, status_manager)
                healed = self.hp - before_hp
                if healed:
                    frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(
                        self.eid, self.eid, healed, tail=roster.COMBAT_DELTA_HERO_TAIL)))
                before_energy = self.energy
                self.energy = min(self.max_energy, self.energy
                    + self.max_energy * recall_wire.RECALL_RESOURCE_FRACTION)
                frames.extend(self._energy_frames(self.energy - before_energy))
        in_base = self.is_in_base()
        if in_base:
            frames.extend(self.heal(self.max_hp * FOUNTAIN_REGEN_FRACTION * dt, now, status_manager))
        old_energy = self.energy
        regeneration = self.energy_regen + (self.max_energy * FOUNTAIN_REGEN_FRACTION if in_base else 0)
        self.energy = min(self.max_energy, self.energy + regeneration * dt)
        frames.extend(self._energy_frames(self.energy - old_energy))
        if self.is_in_base(2 if self.team == 1 else 1) and now >= self._next_fountain_laser_at:
            self._next_fountain_laser_at = now + 1.0
            frames.extend(self.apply_damage(FOUNTAIN_LASER_DAMAGE, attacker_eid=0, now=now, damage_type='true'))
        return frames

    def set_target_eid(self, target_eid):
        if not self.is_alive:
            return
        self.order_version += 1
        self.cancel_recall()
        self.target_eid = target_eid
        self.waypoints, self.move_target = [], None
        self._pursuit_destination = None

    def clear_target(self):
        self.target_eid = None
        self._pursuit_destination = None

    def apply_damage(self, amount, attacker_eid, now, damage_type='weapon', status_manager=None, modifier_queue=None):
        if not self.is_alive or amount <= 0:
            return []
        actual_hp_damage = amount
        if modifier_queue is not None:
            from .status_effects import DamageContext, DamageType
            dtype = DamageType.WEAPON if damage_type == 'weapon' else DamageType.CRYSTAL if damage_type == 'crystal' else DamageType.TRUE
            result = modifier_queue.resolve(DamageContext(
                source_eid=attacker_eid, target_eid=self.eid, damage_type=dtype,
                raw_amount=amount, now=now, armor=self.armor, shield=self.shield,
                armor_pierce=self.armor_pierce, shield_pierce=self.shield_pierce,
                damage_reduction=self.damage_reduction,
            ), status_manager=status_manager)
            actual_hp_damage = result.final_damage
        elif status_manager is not None:
            actual_hp_damage, _ = status_manager.absorb_damage_with_barrier(self.eid, amount, now)
        actual_hp_damage = min(self.hp, max(0.0, actual_hp_damage))
        if actual_hp_damage:
            self.cancel_recall()
        self.hp -= actual_hp_damage
        frames = [(wire.OP.ENTITY_STAT, roster.build_hero_stat(self.eid, -actual_hp_damage, stat_type=0, tail=bytes.fromhex('0001000000')))]
        if self.hp <= 0:
            self.is_alive = False
            duration = self.respawn_seconds()
            self.respawn_at = now + duration
            self.respawn_relocation_at = max(now,
                self.respawn_at - lifecycle_wire.HERO_RESPAWN_TRANSITION_SECONDS)
            self.respawn_relocated = False
            self.corpse_hide_at = min(now + lifecycle_wire.HERO_CORPSE_SECONDS, self.respawn_relocation_at)
            self.corpse_hidden = False
            self.target_eid = None
            self.waypoints, self.move_target = [], None
            self.is_moving = False
            self.cancel_recall()
            self.order_version += 1
            # 1072 carries the killer; 1075 starts the countdown. The later
            # 1073 hides the corpse but never releases the actor with 1035.
            frames.append((lifecycle_wire.OP_HERO_DEATH, lifecycle_wire.build_hero_death(self.eid, attacker_eid)))
            frames.append((lifecycle_wire.OP_RESPAWN_COUNTDOWN, lifecycle_wire.build_respawn_countdown(self.eid, duration)))
        return frames

    def check_respawn(self, now):
        if self.is_alive or self.respawn_at is None:
            return []
        frames = []
        if not self.corpse_hidden and self.corpse_hide_at is not None and now >= self.corpse_hide_at:
            frames.append((lifecycle_wire.OP_HERO_CORPSE_HIDE,
                           lifecycle_wire.build_hero_corpse_hide(self.eid)))
            self.corpse_hidden = True
            self.corpse_hide_at = None
        if not self.respawn_relocated and self.respawn_relocation_at is not None and now >= self.respawn_relocation_at:
            # Native 1011 snapshots during this transition still contain HP0
            # at the new base position. 1033 does not complete resurrection.
            self.facing = roster.FACING_DEFAULT
            frames.append((lifecycle_wire.OP_HERO_RESPAWN,
                           lifecycle_wire.build_hero_respawn(self.eid, self.spawn_x, self.spawn_y)))
            frames.extend(self.teleport(self.spawn_x, self.spawn_y))
            self.respawn_relocated = True
            self.respawn_relocation_at = None
        if now < self.respawn_at:
            return frames
        self.is_alive, self.respawn_at, self.just_respawned = True, None, True
        self.respawn_relocated, self.respawn_relocation_at = False, None
        self.corpse_hidden, self.corpse_hide_at = False, None
        self.hp, self.energy = self.max_hp, self.max_energy
        # 1074 completes the measured transition and restores native pools;
        # no extra full-pool HP/energy deltas accompany it in the corpus.
        frames.append((lifecycle_wire.OP_HERO_RESPAWN_COMPLETE,
                       lifecycle_wire.build_hero_respawn_complete(self.eid, self.spawn_x, self.spawn_y)))
        return frames

    def set_target(self, tx, ty):
        return self.set_path([(tx, ty)])

    def set_path(self, waypoints):
        if not self.is_alive:
            return []
        self.order_version += 1
        self.cancel_recall()
        self.target_eid = None
        route, origin = [], (self.x, self.y)
        for target in waypoints:
            destination = fixed(target[0]) / SCALE, fixed(target[1]) / SCALE
            segment = self.navigation.find_path(origin, destination) if self.navigation is not None else [destination]
            if not segment:
                break
            route.extend(segment)
            origin = segment[-1]
        if not route:
            return self.stop(input_order=False)
        self.waypoints, self.move_target = route, route[-1]
        was_moving = self.is_moving
        self.is_moving = True
        self.facing = roster.facing_toward(self.x, self.y, *route[0])
        if was_moving:
            return []
        self._start_emitted = True
        return [(wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y))]

    def _advance(self, dt, speed):
        numerator = fixed(speed) * fixed(dt) + self._movement_remainder
        remaining, self._movement_remainder = divmod(numerator, SCALE)
        while remaining > 0 and self.waypoints:
            tx, ty = map(fixed, self.waypoints[0])
            dx, dy = tx - self._x_fixed, ty - self._y_fixed
            squared = dx * dx + dy * dy
            distance = math.isqrt(squared)
            if distance * distance < squared:
                distance += 1
            if distance <= remaining:
                self._x_fixed, self._y_fixed = tx, ty
                remaining -= distance
                self.waypoints.pop(0)
            else:
                nx = self._x_fixed + (abs(dx) * remaining // distance) * (1 if dx >= 0 else -1)
                ny = self._y_fixed + (abs(dy) * remaining // distance) * (1 if dy >= 0 else -1)
                if self.navigation is not None:
                    endpoint = self.navigation.clamp_segment((self.x, self.y), (nx / SCALE, ny / SCALE))
                    nx, ny = map(fixed, endpoint)
                self._x_fixed, self._y_fixed = nx, ny
                remaining = 0
            if self.waypoints:
                self.facing = roster.facing_toward(self.x, self.y, *self.waypoints[0])
        frame = (wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y))
        if not self.waypoints:
            self.is_moving, self.move_target = False, None
            return [frame, frame]
        return [frame]

    def step(self, dt, now=None, target_pos=None, status_manager=None):
        if dt < 0 or not math.isfinite(dt):
            raise ValueError('invalid movement delta time')
        self.just_respawned = False
        if not self.is_alive:
            return self.check_respawn(now) if now is not None else []
        if self.channeling:
            return self.stop(input_order=False)
        if status_manager is not None and now is not None:
            dx, dy = status_manager.get_knockback_displacement(self.eid, dt, now)
            if dx or dy:
                self.cancel_recall()
                endpoint = self.x + dx, self.y + dy
                if self.navigation is not None:
                    endpoint = self.navigation.clamp_segment((self.x, self.y), endpoint)
                return self.teleport(*endpoint)
            can_move = status_manager.can_move(self.eid, now)
            multiplier = status_manager.get_speed_multiplier(self.eid, now)
        else:
            can_move, multiplier = True, 1.0
        speed = self.effective_speed(now, multiplier, status_manager)
        if self.target_eid is not None:
            if target_pos is None:
                self.clear_target()
            else:
                dx, dy = target_pos[0] - self.x, target_pos[1] - self.y
                if within_distance((self.x, self.y), target_pos, self.attack_range):
                    frames = self.stop(input_order=False)
                    self.facing = roster.facing_toward(self.x, self.y, *target_pos)
                    return frames
                if can_move:
                    moved = self._pursuit_destination is None or sum((target_pos[k] - self._pursuit_destination[k]) ** 2 for k in (0, 1)) >= 0.25 ** 2
                    if self.navigation is not None:
                        if moved or not self.waypoints:
                            route = self.navigation.find_path((self.x, self.y), target_pos)
                            self._pursuit_destination = target_pos
                        else:
                            route = self.waypoints
                    else:
                        route = [target_pos]
                    if route:
                        self.waypoints, self.move_target, self.is_moving = route, route[-1], True
                        if len(route) == 1:
                            fx = fixed(target_pos[0]) - self._x_fixed
                            fy = fixed(target_pos[1]) - self._y_fixed
                            squared = fx * fx + fy * fy
                            distance = math.isqrt(squared)
                            distance += distance * distance < squared
                            # _advance rounds each axis toward the origin.
                            # Step two coordinate quanta inside the range so
                            # an oblique approach cannot stall just outside it.
                            approach = max(0, distance - fixed(self.attack_range) + 2)
                            speed = min(speed, approach / SCALE / dt) if dt else 0.0
                    else:
                        return self.stop(input_order=False)
        if not can_move:
            self.cancel_recall()
            return self.stop(input_order=False)
        if not self.is_moving or not self.waypoints or dt == 0 or speed <= 0:
            return []
        return self._advance(dt, speed)

    def stop(self, *, input_order=True):
        if input_order:
            self.order_version += 1
            self.cancel_recall()
        was_moving = self.is_moving
        self.is_moving, self.waypoints, self.move_target = False, [], None
        if not was_moving:
            return []
        frame = (wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y))
        return [frame, frame]

    def teleport(self, x, y):
        self.x, self.y = x, y
        self.waypoints, self.move_target, self.is_moving = [], None, False
        self._movement_remainder = 0
        self.cancel_recall()
        return [(wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y))]

    def dash_to(self, x, y, now=None):
        if not self.is_alive:
            return []
        endpoint = self.navigation.dash_endpoint((self.x, self.y), (x, y)) if self.navigation is not None else (x, y)
        self.order_version += 1
        return self.teleport(*endpoint)

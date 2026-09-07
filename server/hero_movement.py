"""Hero movement simulation (T3 Slice 4).

Authoritative movement for hero entities:
- Consumes c2s 1012 move targets and multi-waypoint paths.
- Simulates path traversal with constant move speed (roster.MOVE_SPEED = 5.0 u/s).
- Authoritative 1070 emission:
  * Start anchor: emits current position when a move starts from idle.
  * Cadence: emits 1070 every roster.MOVE_TICK (0.20 s) while moving.
  * Arrival: emits exact target position with duplicate confirmation frame (measured in corpus).
  * Silence: emits zero 1070s when stationary.
  * Anti-rubberband: seamless retargeting while in motion without snapping back.
  * Facing: tracks unit (cos, sin) facing vector along the motion direction.
  * Eid / team aware: supports any hero eid (1500 / 1515-1519) and team (1 or 2).
"""
import math
from typing import List, Optional, Tuple

from . import roster, wire


class HeroMovement:
    """Simulates authoritative hero movement along paths with 1070 pacing."""

    def __init__(
        self,
        eid: int = 1500,
        team: int = 1,
        x: Optional[float] = None,
        y: Optional[float] = None,
        speed: float = roster.MOVE_SPEED,
        hp: float = roster.HERO_BASE_HP,
        max_hp: float = roster.HERO_BASE_HP,
        attack_damage: float = roster.HERO_BASE_ATTACK_DAMAGE,
        attack_range: float = roster.HERO_ATTACK_RANGE,
        attack_cooldown: float = roster.HERO_ATTACK_COOLDOWN,
        respawn_duration: float = roster.HERO_RESPAWN_DURATION,
    ):
        self.eid = eid
        self.team = team
        if x is None or y is None:
            spawn = roster.HERO_SPAWNS.get(eid, (roster.SPAWN_X, roster.SPAWN_Y))
            self.spawn_x = spawn[0] if x is None else x
            self.spawn_y = spawn[1] if y is None else y
        else:
            self.spawn_x = x
            self.spawn_y = y
        self.x = self.spawn_x
        self.y = self.spawn_y

        self.speed = speed
        self.hp = hp
        self.max_hp = max_hp
        self.attack_damage = attack_damage
        self.attack_range = attack_range
        self.attack_cooldown = attack_cooldown
        self.respawn_duration = respawn_duration
        self.armor: float = 25.0
        self.shield: float = 20.0
        self.armor_pierce: float = 0.0
        self.shield_pierce: float = 0.0
        self.damage_reduction: float = 0.0
        self.base_max_hp: float = max_hp
        self.base_attack_damage: float = attack_damage
        self.base_armor: float = 25.0
        self.base_shield: float = 20.0
        self.base_speed: float = speed
        self.crystal_power: float = 0.0
        self.level: int = 1
        self.is_alive = True
        self.respawn_at: Optional[float] = None

        self.target_eid: Optional[int] = None
        self.next_attack_at: float = 0.0

        self.facing = roster.FACING_DEFAULT  # (cos, sin)
        self.waypoints: List[Tuple[float, float]] = []
        self.move_target: Optional[Tuple[float, float]] = None
        self.is_moving = False
        self._start_emitted = False
        self.just_respawned = False

    def set_target_eid(self, target_eid: int):
        """Acquire target entity (c2s 1060). Stops ground pathing to pursue target."""
        if not self.is_alive:
            return
        self.target_eid = target_eid
        self.waypoints = []
        self.move_target = None

    def clear_target(self):
        """Clear current entity target."""
        self.target_eid = None

    def apply_damage(
        self,
        amount: float,
        attacker_eid: int,
        now: float,
        damage_type: str = "weapon",
        status_manager: Optional[Any] = None,
        modifier_queue: Optional[Any] = None,
    ) -> List[Tuple[int, bytes]]:
        """Apply damage to hero: emits 1053 type-6 HP stat delta.
        If HP reaches 0: hero dies and emits death chain (1073 + 1067 + 1162)."""
        if not self.is_alive:
            return []

        actual_hp_damage = amount
        if modifier_queue is not None:
            from .status_effects import DamageContext, DamageType
            dtype = DamageType.WEAPON if damage_type == "weapon" else (
                DamageType.CRYSTAL if damage_type == "crystal" else DamageType.TRUE
            )
            ctx = DamageContext(
                source_eid=attacker_eid,
                target_eid=self.eid,
                damage_type=dtype,
                raw_amount=amount,
                now=now,
                armor=self.armor,
                shield=self.shield,
                armor_pierce=self.armor_pierce,
                shield_pierce=self.shield_pierce,
                damage_reduction=self.damage_reduction,
            )
            res = modifier_queue.resolve(ctx, status_manager=status_manager)
            actual_hp_damage = res.final_damage
        elif status_manager is not None:
            actual_hp_damage, _ = status_manager.absorb_damage_with_barrier(self.eid, amount, now)

        self.hp = max(0.0, self.hp - actual_hp_damage)
        frames: List[Tuple[int, bytes]] = [
            (wire.OP.ENTITY_STAT, roster.build_hero_stat(self.eid, -actual_hp_damage, stat_type=6))
        ]
        if self.hp <= 0:
            self.is_alive = False
            self.respawn_at = now + self.respawn_duration
            self.target_eid = None
            self.waypoints = []
            self.move_target = None
            self.is_moving = False
            # Death chain: 1073 DESTROY + 1067 ENTITY_STATE (dead) + 1162 TIMER_TICK (respawn countdown)
            frames.append((wire.OP.DESTROY, roster.build_destroy(self.eid)))
            frames.append((wire.OP.ENTITY_STATE, roster.build_hero_death_state(self.eid)))
            frames.append((wire.OP.TIMER_TICK, roster.build_timer_tick(
                self.eid, 0xb855d752, self.respawn_duration)))
        return frames

    def check_respawn(self, now: float) -> List[Tuple[int, bytes]]:
        """If dead and respawn timer has elapsed, resurrect at spawn base with full HP."""
        if self.is_alive or self.respawn_at is None:
            return []
        if now < self.respawn_at:
            return []

        self.is_alive = True
        self.respawn_at = None
        self.just_respawned = True
        self.hp = self.max_hp
        self.x = self.spawn_x
        self.y = self.spawn_y
        self.waypoints = []
        self.move_target = None
        self.is_moving = False
        self.facing = roster.FACING_DEFAULT

        frames: List[Tuple[int, bytes]] = []
        pos_frame = roster.build_position(self.eid, self.x, self.y)
        frames.append((wire.OP.POSITION, pos_frame))
        frames.append((wire.OP.POSITION, pos_frame))
        # Restore full HP bar on HUD
        frames.append((wire.OP.ENTITY_STAT, roster.build_hero_stat(self.eid, self.max_hp, stat_type=6)))
        return frames

    def set_target(self, tx: float, ty: float) -> List[Tuple[int, bytes]]:
        """Set a single target destination. Move command clears entity target (orb-walk)."""
        if not self.is_alive:
            return []
        self.target_eid = None
        return self.set_path([(tx, ty)])

    def set_path(self, waypoints: List[Tuple[float, float]]) -> List[Tuple[int, bytes]]:
        """Set a multi-waypoint path.

        Anti-rubberband design:
        If already in motion, waypoints update seamlessly from current (x, y) without
        resetting position or re-emitting an outdated start anchor.
        If stationary, emits initial 1070 anchor at current position to acknowledge motion start.
        """
        if not self.is_alive:
            return []
        self.target_eid = None
        if not waypoints:
            self.waypoints = []
            self.move_target = None
            self.is_moving = False
            return []

        self.waypoints = list(waypoints)
        self.move_target = self.waypoints[-1]
        was_moving = self.is_moving
        self.is_moving = True

        # Update facing toward next waypoint
        next_wp = self.waypoints[0]
        self.facing = roster.facing_toward(self.x, self.y, next_wp[0], next_wp[1])

        frames = []
        if not was_moving:
            # Emit start anchor frame
            frames.append((wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y)))
            self._start_emitted = True

        return frames

    def step(
        self,
        dt: float,
        now: Optional[float] = None,
        target_pos: Optional[Tuple[float, float]] = None,
        status_manager: Optional[Any] = None,
    ) -> List[Tuple[int, bytes]]:
        """Advance hero simulation:
        - If dead: checks respawn countdown.
        - If knockback active: displaces position and emits 1070.
        - If stunned/rooted: disables motion.
        - If slowed: scales motion speed.
        - If stunned/disarmed: suppresses basic attack.
        - If target_eid is set and target_pos provided:
          * If distance > attack_range: walks toward target.
          * If distance <= attack_range: stops, faces target, and attacks on cooldown (1054).
        - If no target_eid: advances along waypoints with anti-rubberband 1070 pacing.
        """
        self.just_respawned = False
        if not self.is_alive:
            if now is not None:
                return self.check_respawn(now)
            return []

        # 1. Knockback displacement (forced displacement interrupts pathing)
        frames: List[Tuple[int, bytes]] = []
        if status_manager is not None and now is not None:
            kb_dx, kb_dy = status_manager.get_knockback_displacement(self.eid, dt, now)
            if abs(kb_dx) > 1e-5 or abs(kb_dy) > 1e-5:
                self.x += kb_dx
                self.y += kb_dy
                self.is_moving = False
                self.waypoints = []
                self.move_target = None
                frames.append((wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y)))
                return frames

        # 2. Status restrictions
        can_move = True
        can_attack = True
        speed_mult = 1.0
        if status_manager is not None and now is not None:
            can_move = status_manager.can_move(self.eid, now)
            can_attack = status_manager.can_attack(self.eid, now)
            speed_mult = status_manager.get_speed_multiplier(self.eid, now)

        effective_speed = self.speed * speed_mult

        # Target pursuit & basic attack
        if self.target_eid is not None:
            if target_pos is not None:
                tx, ty = target_pos
                dx = tx - self.x
                dy = ty - self.y
                dist = math.hypot(dx, dy)
                if dist > self.attack_range:
                    # Pursue target if allowed to move
                    if can_move:
                        move_dist = min(effective_speed * dt, dist - self.attack_range + 0.1)
                        if move_dist > 0:
                            self.x += (dx / dist) * move_dist
                            self.y += (dy / dist) * move_dist
                            self.facing = roster.facing_toward(self.x, self.y, tx, ty)
                            self.is_moving = True
                            return [(wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y))]
                    else:
                        if self.is_moving:
                            frames.extend(self.stop())
                        return frames
                else:
                    # In attack range: stop and attack
                    if self.is_moving:
                        frames.extend(self.stop())
                    self.facing = roster.facing_toward(self.x, self.y, tx, ty)
                    if can_attack and now is not None and now >= self.next_attack_at:
                        self.next_attack_at = now + self.attack_cooldown
                        frames.append((wire.OP.COMBAT_DELTA, roster.build_combat_delta(
                            self.eid, self.target_eid, -self.attack_damage,
                            tail=roster.COMBAT_DELTA_HERO_TAIL)))
                    return frames
            else:
                # Target dead or vanished
                self.target_eid = None

        if not can_move:
            if self.is_moving:
                return self.stop()
            return []

        if not self.is_moving or not self.waypoints:
            return []

        remaining_dist = effective_speed * dt
        frames: List[Tuple[int, bytes]] = []

        while remaining_dist > 0 and self.waypoints:
            tx, ty = self.waypoints[0]
            dx = tx - self.x
            dy = ty - self.y
            seg_dist = math.hypot(dx, dy)

            if seg_dist <= remaining_dist:
                # Reached this waypoint
                self.x = tx
                self.y = ty
                remaining_dist -= seg_dist
                self.waypoints.pop(0)

                if self.waypoints:
                    # Still have more waypoints in path: update facing toward next
                    next_wp = self.waypoints[0]
                    self.facing = roster.facing_toward(self.x, self.y, next_wp[0], next_wp[1])
                else:
                    # Reached final destination!
                    self.is_moving = False
                    self.move_target = None
                    pos_frame = roster.build_position(self.eid, self.x, self.y)
                    # Measured corpus behavior: duplicate 1070 on arrival confirmation
                    frames.append((wire.OP.POSITION, pos_frame))
                    frames.append((wire.OP.POSITION, pos_frame))
                    return frames
            else:
                # Advance along current segment
                frac = remaining_dist / seg_dist
                self.x += dx * frac
                self.y += dy * frac
                self.facing = roster.facing_toward(self.x, self.y, tx, ty)
                remaining_dist = 0.0

        if self.is_moving:
            # Traveling: emit current position at cadence
            frames.append((wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y)))

        return frames

    def stop(self) -> List[Tuple[int, bytes]]:
        """Stop movement immediately at current position."""
        if not self.is_moving:
            return []
        self.is_moving = False
        self.waypoints = []
        self.move_target = None
        pos_frame = roster.build_position(self.eid, self.x, self.y)
        return [(wire.OP.POSITION, pos_frame), (wire.OP.POSITION, pos_frame)]

    def teleport(self, x: float, y: float) -> List[Tuple[int, bytes]]:
        """Teleport hero to exact position (e.g. spawn, respawn)."""
        self.x = x
        self.y = y
        self.waypoints = []
        self.move_target = None
        self.is_moving = False
        return [(wire.OP.POSITION, roster.build_position(self.eid, self.x, self.y))]

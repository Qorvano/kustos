"""Pure panel state machine for Kustos.

Deliberately free of Home Assistant imports: the hub (core/hub.py) adapts it
to HA (clock, timers, event bus, entity states). The FSM receives resolved
numbers (delays already merged from panel config and settings) and returns
Effects; it never schedules or fires anything itself. Timers are represented
as absolute UTC datetimes (ends_at) so a restart can restore or catch up.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from ..const import (
    ALWAYS_ON_ALARM_TYPES,
    ATTR_ALARM_TYPE,
    ATTR_AREA_ID,
    ATTR_ARM_MODE,
    ATTR_ACTOR,
    ATTR_BYPASSED_ZONES,
    ATTR_DELAY_TOTAL_S,
    ATTR_ENDS_AT,
    ATTR_ENTITY_ID,
    ATTR_OPEN_ZONES,
    ATTR_PANEL_ID,
    ATTR_REASON,
    ATTR_ZONE_ID,
    EVENT_ACKNOWLEDGED,
    EVENT_ARM_FAILED,
    EVENT_ARMED,
    EVENT_ARMING,
    EVENT_DISARMED,
    EVENT_PENDING,
    EVENT_TRIGGERED,
    EVENT_ZONE_BYPASSED,
    AlarmType,
    ArmFailReason,
    ArmMode,
    ZoneRole,
)


class PanelState(StrEnum):
    DISARMED = "disarmed"
    ARMING = "arming"
    ARMED = "armed"
    PENDING = "pending"
    TRIGGERED = "triggered"


@dataclass(frozen=True)
class ModeTimes:
    """Fully resolved timing for one arm mode (config merged with settings)."""

    exit_delay_s: float
    entry_delay_s: float
    trigger_time_s: float  # 0 = alarm chain runs until acknowledge/disarm


@dataclass(frozen=True)
class ZoneConfig:
    zone_id: str
    entity_id: str
    alarm_type: AlarmType
    modes: dict[ArmMode, ZoneRole]
    use_exit_delay: bool = False
    arm_after_closing: bool = False
    allow_open: bool = False
    auto_bypass: bool = False
    trigger_when_unavailable: bool = False
    unavailable_policy: str = "ignore"
    sensor_type: str = "opening"
    invert: bool = False
    evaluation: dict[str, Any] | None = None

    @property
    def always_on(self) -> bool:
        """Safety zones (fire/water/co/tamper) are armed 24/7, derived from type."""
        return self.alarm_type in ALWAYS_ON_ALARM_TYPES

    def role_in(self, mode: ArmMode | None) -> ZoneRole:
        if mode is None:
            return ZoneRole.INACTIVE
        return self.modes.get(mode, ZoneRole.INACTIVE)


@dataclass(frozen=True)
class PanelBehavior:
    """Panel options relevant to the FSM."""

    rearm_after_trigger: bool
    require_explicit_ack: bool
    disarm_acknowledges: bool


@dataclass
class Effects:
    """What the hub must do after a transition."""

    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    timer_ends_at: datetime | None = None
    cancel_timer: bool = False
    critical_save: bool = False
    state_changed: bool = False


@dataclass(frozen=True)
class ArmResult:
    ok: bool
    reason: ArmFailReason | None = None
    open_zones: tuple[str, ...] = ()


class PanelFsm:
    """State machine for one area panel."""

    def __init__(
        self,
        panel_id: str,
        area_id: str | None,
        zones: dict[str, ZoneConfig],
        mode_times: Callable[[ArmMode], ModeTimes],
        behavior: PanelBehavior,
        clock: Callable[[], datetime],
        enabled_modes: frozenset[ArmMode],
        default_times: ModeTimes,
    ) -> None:
        self.panel_id = panel_id
        self.area_id = area_id
        self.zones = zones
        self._mode_times = mode_times
        self.behavior = behavior
        self._clock = clock
        self.enabled_modes = enabled_modes
        # Used when an alarm starts without an armed mode (24/7 zones while
        # disarmed): timing then comes straight from the settings defaults.
        self._default_times = default_times

        self.state = PanelState.DISARMED
        self.arm_mode: ArmMode | None = None
        self.ends_at: datetime | None = None
        self.bypassed_zones: set[str] = set()
        self.alarm_memory: list[dict[str, Any]] = []
        self.active_alarm_types: set[AlarmType] = set()
        # Zone whose trip started the running entry delay (context for events).
        self._pending_zone_id: str | None = None

    # ------------------------------------------------------------------
    # Event payload helpers
    # ------------------------------------------------------------------

    def blocking_zones(
        self,
        mode: ArmMode,
        open_zones: set[str],
        unavailable_zones: set[str] | None = None,
    ) -> list[str]:
        """Zones that would block arming into mode right now (ready check)."""
        blocking = self._classify_open(mode, open_zones, force=False, skip_delay=False)[0]
        for zone_id in sorted(unavailable_zones or set()):
            zone = self.zones.get(zone_id)
            if (
                zone is not None
                and zone.role_in(mode) is not ZoneRole.INACTIVE
                and zone.unavailable_policy == "block_arm"
            ):
                blocking.append(zone_id)
        return blocking

    def _classify_open(
        self, mode: ArmMode, open_zones: set[str], force: bool, skip_delay: bool
    ) -> tuple[list[str], set[str]]:
        """Split open zones into blocking vs. to-be-bypassed for an arm attempt."""
        times = self._mode_times(mode)
        blocking: list[str] = []
        bypassed: set[str] = set()
        for zone_id in sorted(open_zones):
            zone = self.zones.get(zone_id)
            if zone is None or zone.role_in(mode) is ZoneRole.INACTIVE:
                continue
            if zone.allow_open:
                continue
            if zone.use_exit_delay and times.exit_delay_s > 0 and not skip_delay:
                continue  # may still be open while leaving; re-checked at completion
            if zone.auto_bypass or force:
                bypassed.add(zone_id)
                continue
            blocking.append(zone_id)
        return blocking, bypassed

    def _base_payload(self, actor: str) -> dict[str, Any]:
        return {
            ATTR_PANEL_ID: self.panel_id,
            ATTR_AREA_ID: self.area_id,
            ATTR_ACTOR: actor,
        }

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def arm(
        self,
        mode: ArmMode,
        open_zones: set[str],
        actor: str,
        force: bool = False,
        skip_delay: bool = False,
        unavailable_zones: set[str] | None = None,
    ) -> tuple[ArmResult, Effects]:
        """Arm into a mode. open_zones = zone_ids currently open (hub-supplied)."""
        fx = Effects()
        if self.state in (PanelState.PENDING, PanelState.TRIGGERED):
            return ArmResult(False, ArmFailReason.NOT_ALLOWED), fx
        if mode not in self.enabled_modes:
            return ArmResult(False, ArmFailReason.MODE_DISABLED), fx

        times = self._mode_times(mode)
        blocking, bypassed = self._classify_open(
            mode, open_zones, force=force, skip_delay=skip_delay
        )
        for zone_id in sorted(unavailable_zones or set()):
            zone = self.zones.get(zone_id)
            if zone is None or zone.role_in(mode) is ZoneRole.INACTIVE:
                continue
            if zone.unavailable_policy == "block_arm" and not force:
                blocking.append(zone_id)
            elif zone.unavailable_policy == "auto_bypass" or force:
                bypassed.add(zone_id)

        if blocking:
            payload = self._base_payload(actor) | {
                ATTR_ARM_MODE: mode,
                ATTR_REASON: ArmFailReason.OPEN_ZONES,
                ATTR_OPEN_ZONES: blocking,
            }
            fx.events.append((EVENT_ARM_FAILED, payload))
            return ArmResult(False, ArmFailReason.OPEN_ZONES, tuple(blocking)), fx

        self.bypassed_zones = bypassed
        for zone_id in sorted(bypassed):
            fx.events.append(
                (
                    EVENT_ZONE_BYPASSED,
                    self._base_payload(actor)
                    | {ATTR_ZONE_ID: zone_id, ATTR_ARM_MODE: mode},
                )
            )

        self.arm_mode = mode
        self._pending_zone_id = None
        self.active_alarm_types.clear()
        fx.critical_save = True
        fx.state_changed = True

        if skip_delay or times.exit_delay_s == 0:
            self.state = PanelState.ARMED
            self.ends_at = None
            fx.cancel_timer = True
            fx.events.append(
                (EVENT_ARMED, self._base_payload(actor) | {ATTR_ARM_MODE: mode})
            )
        else:
            self.state = PanelState.ARMING
            self.ends_at = self._clock() + _seconds(times.exit_delay_s)
            fx.timer_ends_at = self.ends_at
            fx.events.append(
                (
                    EVENT_ARMING,
                    self._base_payload(actor)
                    | {
                        ATTR_ARM_MODE: mode,
                        ATTR_ENDS_AT: self.ends_at.isoformat(),
                        ATTR_DELAY_TOTAL_S: times.exit_delay_s,
                    },
                )
            )
        return ArmResult(True), fx

    def disarm(self, actor: str) -> Effects:
        fx = Effects(critical_save=True, state_changed=True, cancel_timer=True)
        self.state = PanelState.DISARMED
        self.arm_mode = None
        self.ends_at = None
        self._pending_zone_id = None
        self.active_alarm_types.clear()
        # Bypass lasts exactly one arm cycle.
        self.bypassed_zones.clear()
        if self.alarm_memory and (
            self.behavior.disarm_acknowledges or not self.behavior.require_explicit_ack
        ):
            self.alarm_memory.clear()
        fx.events.append((EVENT_DISARMED, self._base_payload(actor)))
        return fx

    def acknowledge(self, actor: str) -> Effects:
        fx = Effects(critical_save=True)
        if self.alarm_memory:
            self.alarm_memory.clear()
            fx.state_changed = True
            fx.events.append((EVENT_ACKNOWLEDGED, self._base_payload(actor)))
        return fx

    # ------------------------------------------------------------------
    # Zone inputs (edge-triggered; hub applies debounce and invert first)
    # ------------------------------------------------------------------

    def zone_tripped(self, zone_id: str) -> Effects:
        zone = self.zones.get(zone_id)
        fx = Effects()
        if zone is None or zone_id in self.bypassed_zones:
            return fx

        if zone.always_on:
            return self._trigger(zone, fx)

        if self.state == PanelState.ARMED:
            role = zone.role_in(self.arm_mode)
            if role is ZoneRole.INACTIVE:
                return fx
            if role is ZoneRole.DELAYED:
                return self._start_pending(zone, fx)
            # INSTANT, and FOLLOWER without a running entry delay, trigger now.
            return self._trigger(zone, fx)

        if self.state == PanelState.PENDING:
            role = zone.role_in(self.arm_mode)
            if role in (ZoneRole.DELAYED, ZoneRole.FOLLOWER):
                return fx  # follows the running entry delay
            if role is ZoneRole.INSTANT:
                return self._trigger(zone, fx)
            return fx

        if self.state == PanelState.ARMING:
            role = zone.role_in(self.arm_mode)
            if role is ZoneRole.INACTIVE or zone.allow_open:
                return fx
            if zone.use_exit_delay:
                return fx  # expected traffic while leaving
            # Anything else opening during exit delay is a real breach.
            return self._trigger(zone, fx)

        if self.state == PanelState.TRIGGERED:
            role = zone.role_in(self.arm_mode)
            if role is not ZoneRole.INACTIVE or zone.always_on:
                self._record_memory(zone)
                fx.critical_save = True
                fx.state_changed = True
            return fx

        return fx  # DISARMED and not always_on: nothing to do

    def zone_closed(self, zone_id: str, open_zones: set[str]) -> Effects:
        """arm_after_closing: complete the exit delay early once all closed."""
        fx = Effects()
        if self.state is not PanelState.ARMING:
            return fx
        zone = self.zones.get(zone_id)
        if zone is None or not zone.arm_after_closing:
            return fx
        assert self.arm_mode is not None
        relevant_open = {
            zid
            for zid in open_zones
            if (z := self.zones.get(zid)) is not None
            and z.role_in(self.arm_mode) is not ZoneRole.INACTIVE
            and not z.allow_open
        }
        if relevant_open:
            return fx
        return self._complete_arming(open_zones=set(), fx=fx, actor="arm_after_closing")

    def zone_unavailable(self, zone_id: str) -> Effects:
        zone = self.zones.get(zone_id)
        if zone is None or not zone.trigger_when_unavailable:
            return Effects()
        return self.zone_tripped(zone_id)

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------

    def timer_expired(self, open_zones: set[str]) -> Effects:
        fx = Effects()
        if self.state is PanelState.ARMING:
            return self._complete_arming(open_zones, fx, actor="timer")
        if self.state is PanelState.PENDING:
            zone = self.zones.get(self._pending_zone_id or "")
            if zone is None:  # zone deleted mid-delay; still a real alarm
                zone = next(iter(self.zones.values()), None)
            if zone is not None:
                return self._trigger(zone, fx)
            return fx
        if self.state is PanelState.TRIGGERED:
            return self._end_trigger_time(open_zones, fx)
        return fx

    # ------------------------------------------------------------------
    # Restore after restart
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "arm_mode": self.arm_mode,
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "bypassed_zones": sorted(self.bypassed_zones),
            "alarm_memory": list(self.alarm_memory),
            "active_alarm_types": sorted(self.active_alarm_types),
            "pending_zone_id": self._pending_zone_id,
        }

    def restore(self, data: dict[str, Any], open_zones: set[str]) -> Effects:
        """Restore persisted state; catch up timers that expired while down."""
        self.state = PanelState(data["state"])
        self.arm_mode = ArmMode(data["arm_mode"]) if data.get("arm_mode") else None
        raw_ends = data.get("ends_at")
        self.ends_at = datetime.fromisoformat(raw_ends) if raw_ends else None
        self.bypassed_zones = set(data.get("bypassed_zones", []))
        self.alarm_memory = list(data.get("alarm_memory", []))
        self.active_alarm_types = {
            AlarmType(item) for item in data.get("active_alarm_types", [])
        }
        self._pending_zone_id = data.get("pending_zone_id")

        fx = Effects(state_changed=True)
        if self.ends_at is None:
            return fx
        if self.ends_at > self._clock():
            fx.timer_ends_at = self.ends_at  # re-schedule the remaining time
            return fx
        # Expired while Home Assistant was down: catch up now. A pending that
        # ran out becomes a real alarm (fail-secure), an exit delay completes.
        return self.timer_expired(open_zones)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _complete_arming(
        self, open_zones: set[str], fx: Effects, actor: str
    ) -> Effects:
        assert self.arm_mode is not None
        # Zones still open at completion: auto-bypass where allowed, else trip.
        tripped: ZoneConfig | None = None
        for zone_id in sorted(open_zones):
            zone = self.zones.get(zone_id)
            if (
                zone is None
                or zone.role_in(self.arm_mode) is ZoneRole.INACTIVE
                or zone.allow_open
                or zone_id in self.bypassed_zones
            ):
                continue
            if zone.auto_bypass:
                self.bypassed_zones.add(zone_id)
                fx.events.append(
                    (
                        EVENT_ZONE_BYPASSED,
                        self._base_payload(actor)
                        | {ATTR_ZONE_ID: zone_id, ATTR_ARM_MODE: self.arm_mode},
                    )
                )
            else:
                tripped = zone
        self.state = PanelState.ARMED
        self.ends_at = None
        fx.cancel_timer = True
        fx.critical_save = True
        fx.state_changed = True
        fx.events.append(
            (EVENT_ARMED, self._base_payload(actor) | {ATTR_ARM_MODE: self.arm_mode})
        )
        if tripped is not None:
            return self._after_armed_trip(tripped, fx)
        return fx

    def _after_armed_trip(self, zone: ZoneConfig, fx: Effects) -> Effects:
        """A zone was still open when arming completed: treat as fresh trip."""
        role = zone.role_in(self.arm_mode)
        if role is ZoneRole.DELAYED:
            return self._start_pending(zone, fx)
        return self._trigger(zone, fx)

    def _start_pending(self, zone: ZoneConfig, fx: Effects) -> Effects:
        assert self.arm_mode is not None
        times = self._mode_times(self.arm_mode)
        if times.entry_delay_s == 0:
            return self._trigger(zone, fx)
        self.state = PanelState.PENDING
        self._pending_zone_id = zone.zone_id
        self.ends_at = self._clock() + _seconds(times.entry_delay_s)
        fx.timer_ends_at = self.ends_at
        fx.critical_save = True
        fx.state_changed = True
        fx.events.append(
            (
                EVENT_PENDING,
                self._base_payload("zone")
                | {
                    ATTR_ZONE_ID: zone.zone_id,
                    ATTR_ENTITY_ID: zone.entity_id,
                    ATTR_ARM_MODE: self.arm_mode,
                    ATTR_ENDS_AT: self.ends_at.isoformat(),
                    ATTR_DELAY_TOTAL_S: times.entry_delay_s,
                },
            )
        )
        return fx

    def _trigger(self, zone: ZoneConfig, fx: Effects) -> Effects:
        previous_state = self.state
        self.state = PanelState.TRIGGERED
        self._record_memory(zone)
        self.active_alarm_types.add(zone.alarm_type)
        self._pending_zone_id = None
        trigger_time = self._trigger_time_s()
        if trigger_time > 0:
            self.ends_at = self._clock() + _seconds(trigger_time)
            fx.timer_ends_at = self.ends_at
        else:
            self.ends_at = None
            fx.cancel_timer = True
        fx.critical_save = True
        fx.state_changed = True
        fx.events.append(
            (
                EVENT_TRIGGERED,
                self._base_payload("zone")
                | {
                    ATTR_ZONE_ID: zone.zone_id,
                    ATTR_ENTITY_ID: zone.entity_id,
                    ATTR_ALARM_TYPE: zone.alarm_type,
                    ATTR_ARM_MODE: self.arm_mode,
                    "previous_state": previous_state,
                },
            )
        )
        return fx

    def _end_trigger_time(self, open_zones: set[str], fx: Effects) -> Effects:
        """trigger_time ran out: acoustics end; panel rearms or disarms.

        The alarm memory stays until acknowledged (critique finding 5/13).
        """
        self.active_alarm_types.clear()
        self.ends_at = None
        fx.cancel_timer = True
        fx.critical_save = True
        fx.state_changed = True
        if self.behavior.rearm_after_trigger and self.arm_mode is not None:
            # Still-open zones would re-trigger immediately: bypass them,
            # visibly, to end the siren cycle deterministically.
            for zone_id in sorted(open_zones):
                zone = self.zones.get(zone_id)
                if (
                    zone is not None
                    and zone.role_in(self.arm_mode) is not ZoneRole.INACTIVE
                    and not zone.allow_open
                    and zone_id not in self.bypassed_zones
                ):
                    self.bypassed_zones.add(zone_id)
                    fx.events.append(
                        (
                            EVENT_ZONE_BYPASSED,
                            self._base_payload("timer")
                            | {ATTR_ZONE_ID: zone_id, ATTR_ARM_MODE: self.arm_mode},
                        )
                    )
            self.state = PanelState.ARMED
            fx.events.append(
                (
                    EVENT_ARMED,
                    self._base_payload("timer") | {ATTR_ARM_MODE: self.arm_mode},
                )
            )
        else:
            self.state = PanelState.DISARMED
            self.arm_mode = None
            fx.events.append((EVENT_DISARMED, self._base_payload("timer")))
        return fx

    def _record_memory(self, zone: ZoneConfig) -> None:
        entry = {
            "zone_id": zone.zone_id,
            "entity_id": zone.entity_id,
            "alarm_type": zone.alarm_type,
            "at": self._clock().isoformat(),
        }
        if not any(item["zone_id"] == zone.zone_id for item in self.alarm_memory):
            self.alarm_memory.append(entry)

    def _trigger_time_s(self) -> float:
        if self.arm_mode is not None:
            return self._mode_times(self.arm_mode).trigger_time_s
        return self._default_times.trigger_time_s


def _seconds(value: float) -> timedelta:
    return timedelta(seconds=value)

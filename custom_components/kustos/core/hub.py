"""Hub: adapts the pure panel FSMs to Home Assistant.

Owns timers, zone-entity listeners, event firing, runtime persistence and
master aggregation. Entities and the WebSocket API talk to the hub only;
they never touch an FSM directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import collection
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from ..const import (
    ATTR_ALARM_TYPE,
    EVENT_TRIGGERED,
    ArmMode,
    PanelScope,
    SIGNAL_CONFIG_UPDATED,
    SIGNAL_PANEL_STATE,
    AlarmType,
)
from .engine import ReactionEngine
from .fsm import (
    ArmResult,
    Effects,
    ModeTimes,
    PanelBehavior,
    PanelFsm,
    PanelState,
    ZoneConfig,
)
from .snapshot import SnapshotManager

if TYPE_CHECKING:
    from ..storage import KustosStorage

MASTER_ID = "master"


class KustosHub:
    """Runtime brain: one FSM per area panel plus master aggregation."""

    def __init__(self, hass: HomeAssistant, storage: KustosStorage) -> None:
        self._hass = hass
        self._storage = storage
        self.fsms: dict[str, PanelFsm] = {}
        self._timers: dict[str, Any] = {}
        self._zone_unsub: Any | None = None
        self._config_unsub: Any | None = None
        self._zone_by_entity: dict[str, list[tuple[str, str]]] = {}
        self.snapshots = SnapshotManager(hass, storage)
        self.engine = ReactionEngine(hass, storage, self.snapshots)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        self._rebuild()
        self._restore_runtime()
        await self.engine.async_resume()
        # Zone changes rebuild in place; panel add/remove is handled by the
        # config entry (reload) so entities are created/removed cleanly.
        self._config_unsub = self._storage.zones.async_add_listener(
            self._on_config_change
        )

    async def async_stop(self) -> None:
        # No restore here: the alarm may still be real; resume happens on boot.
        await self.engine.async_shutdown()
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        if self._zone_unsub:
            self._zone_unsub()
            self._zone_unsub = None
        if self._config_unsub:
            self._config_unsub()
            self._config_unsub = None

    async def _on_config_change(
        self, change_type: str, item_id: str, config: dict[str, Any]
    ) -> None:
        """Panel/zone configuration changed: rebuild, keeping runtime state."""
        saved = {panel_id: fsm.to_dict() for panel_id, fsm in self.fsms.items()}
        self._rebuild()
        for panel_id, fsm in self.fsms.items():
            if panel_id in saved:
                fx = fsm.restore(saved[panel_id], self._open_zone_ids(panel_id))
                self._apply_effects(panel_id, fx)
        async_dispatcher_send(self._hass, SIGNAL_CONFIG_UPDATED)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        settings = self._storage.settings
        defaults = settings["defaults"]
        default_times = ModeTimes(
            exit_delay_s=defaults["exit_delay_s"],
            entry_delay_s=defaults["entry_delay_s"],
            trigger_time_s=defaults["trigger_time_s"],
        )

        zones_by_panel: dict[str, dict[str, ZoneConfig]] = {}
        self._zone_by_entity = {}
        for item in self._storage.zones.async_items():
            zone = ZoneConfig(
                zone_id=item["id"],
                entity_id=item["entity_id"],
                alarm_type=AlarmType(item["alarm_type"]),
                modes={ArmMode(k): v for k, v in item["modes"].items()},
                use_exit_delay=item["options"]["use_exit_delay"],
                arm_after_closing=item["options"]["arm_after_closing"],
                allow_open=item["options"]["allow_open"],
                auto_bypass=item["options"]["auto_bypass"],
                trigger_when_unavailable=item["options"]["trigger_when_unavailable"],
            )
            zones_by_panel.setdefault(item["panel_id"], {})[zone.zone_id] = zone
            self._zone_by_entity.setdefault(item["entity_id"], []).append(
                (item["panel_id"], zone.zone_id)
            )

        self.fsms = {}
        for item in self._storage.panels.async_items():
            if item["scope"]["type"] == PanelScope.MASTER or not item["enabled"]:
                continue
            panel_id = item["id"]
            mode_cfg = {ArmMode(k): v for k, v in item["modes"].items()}
            enabled_modes = frozenset(
                mode for mode, cfg in mode_cfg.items() if cfg["enabled"]
            )

            def make_times(cfg_map: dict[ArmMode, dict[str, Any]]):
                def mode_times(mode: ArmMode) -> ModeTimes:
                    cfg = cfg_map.get(mode, {})
                    return ModeTimes(
                        exit_delay_s=cfg.get("exit_delay_s", defaults["exit_delay_s"]),
                        entry_delay_s=cfg.get("entry_delay_s", defaults["entry_delay_s"]),
                        trigger_time_s=cfg.get("trigger_time_s", defaults["trigger_time_s"]),
                    )

                return mode_times

            self.fsms[panel_id] = PanelFsm(
                panel_id=panel_id,
                area_id=item["scope"].get("area_id"),
                zones=zones_by_panel.get(panel_id, {}),
                mode_times=make_times(mode_cfg),
                behavior=PanelBehavior(
                    rearm_after_trigger=item["options"]["rearm_after_trigger"],
                    require_explicit_ack=settings["security"]["require_explicit_ack"],
                    disarm_acknowledges=settings["security"]["disarm_acknowledges"],
                ),
                clock=dt_util.utcnow,
                enabled_modes=enabled_modes,
                default_times=default_times,
            )

        self._resubscribe_zones()

    def _resubscribe_zones(self) -> None:
        if self._zone_unsub:
            self._zone_unsub()
            self._zone_unsub = None
        if self._zone_by_entity:
            self._zone_unsub = async_track_state_change_event(
                self._hass, list(self._zone_by_entity), self._on_zone_state
            )

    def _restore_runtime(self) -> None:
        stored = self._storage.runtime.get("panels", {})
        for panel_id, fsm in self.fsms.items():
            if panel_id in stored:
                fx = fsm.restore(stored[panel_id], self._open_zone_ids(panel_id))
                self._apply_effects(panel_id, fx)

    # ------------------------------------------------------------------
    # Zone state handling
    # ------------------------------------------------------------------

    @callback
    def _on_zone_state(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return
        for panel_id, zone_id in self._zone_by_entity.get(entity_id, []):
            fsm = self.fsms.get(panel_id)
            if fsm is None:
                continue
            zone = fsm.zones.get(zone_id)
            if zone is None:
                continue
            if new_state.state == STATE_UNAVAILABLE:
                self._apply_effects(panel_id, fsm.zone_unavailable(zone_id))
                continue
            was_open = old_state is not None and self._is_open_state(old_state.state)
            is_open = self._is_open_state(new_state.state)
            if is_open and not was_open:
                self._apply_effects(panel_id, fsm.zone_tripped(zone_id))
            elif was_open and not is_open:
                self._apply_effects(
                    panel_id, fsm.zone_closed(zone_id, self._open_zone_ids(panel_id))
                )

    def _is_open_state(self, state: str) -> bool:
        return state == STATE_ON

    def _zone_open(self, entity_id: str) -> bool:
        state = self._hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        return self._is_open_state(state.state)

    def _open_zone_ids(self, panel_id: str) -> set[str]:
        fsm = self.fsms.get(panel_id)
        if fsm is None:
            return set()
        return {
            zone_id
            for zone_id, zone in fsm.zones.items()
            if self._zone_open(zone.entity_id)
        }

    # ------------------------------------------------------------------
    # Commands (called by entities, services, WS API)
    # ------------------------------------------------------------------

    async def async_arm(
        self,
        panel_id: str,
        mode: ArmMode,
        actor: str,
        force: bool = False,
        skip_delay: bool = False,
    ) -> ArmResult:
        if panel_id == MASTER_ID:
            result = ArmResult(True)
            for area_panel_id in self.fsms:
                result = await self.async_arm(
                    area_panel_id, mode, actor, force=force, skip_delay=skip_delay
                )
                if not result.ok:
                    return result
            return result
        fsm = self.fsms[panel_id]
        result, fx = fsm.arm(
            mode, self._open_zone_ids(panel_id), actor, force=force, skip_delay=skip_delay
        )
        self._apply_effects(panel_id, fx)
        return result

    async def async_disarm(self, panel_id: str, actor: str) -> None:
        if panel_id == MASTER_ID:
            for area_panel_id in self.fsms:
                await self.async_disarm(area_panel_id, actor)
            return
        fsm = self.fsms[panel_id]
        self._apply_effects(panel_id, fsm.disarm(actor))

    async def async_acknowledge(self, panel_id: str, actor: str) -> None:
        if panel_id == MASTER_ID:
            for area_panel_id in self.fsms:
                await self.async_acknowledge(area_panel_id, actor)
            return
        fsm = self.fsms[panel_id]
        self._apply_effects(panel_id, fsm.acknowledge(actor))

    def blocking_zones(self, panel_id: str, mode: ArmMode) -> list[str]:
        fsm = self.fsms[panel_id]
        return fsm.blocking_zones(mode, self._open_zone_ids(panel_id))

    def zone_entity_ids(self, panel_id: str) -> list[str]:
        fsm = self.fsms.get(panel_id)
        if fsm is None:
            return []
        return [zone.entity_id for zone in fsm.zones.values()]

    # ------------------------------------------------------------------
    # Master aggregation (provisional M1 policy, configurable later)
    # ------------------------------------------------------------------

    @property
    def master_state(self) -> tuple[PanelState, ArmMode | None]:
        states = [(fsm.state, fsm.arm_mode) for fsm in self.fsms.values()]
        if not states:
            return (PanelState.DISARMED, None)
        for severity in (PanelState.TRIGGERED, PanelState.PENDING, PanelState.ARMING):
            for state, mode in states:
                if state is severity:
                    return (severity, mode)
        armed_modes = {mode for state, mode in states if state is PanelState.ARMED}
        if armed_modes and all(state is PanelState.ARMED for state, _ in states):
            if len(armed_modes) == 1:
                return (PanelState.ARMED, next(iter(armed_modes)))
            # Mixed armed modes: report the most restrictive one.
            return (PanelState.ARMED, ArmMode.AWAY)
        return (PanelState.DISARMED, None)

    # ------------------------------------------------------------------
    # Effects
    # ------------------------------------------------------------------

    def _apply_effects(self, panel_id: str, fx: Effects) -> None:
        for event_name, payload in fx.events:
            self._hass.bus.async_fire(event_name, payload)
            if event_name == EVENT_TRIGGERED:
                fsm = self.fsms[panel_id]
                self._hass.async_create_task(
                    self.engine.async_start(
                        panel_id, fsm.area_id, payload[ATTR_ALARM_TYPE]
                    )
                )

        if fx.cancel_timer and panel_id in self._timers:
            self._timers.pop(panel_id)()
        if fx.timer_ends_at is not None:
            if panel_id in self._timers:
                self._timers.pop(panel_id)()

            @callback
            def _expired(_now, panel_id=panel_id) -> None:
                self._timers.pop(panel_id, None)
                fsm = self.fsms.get(panel_id)
                if fsm is not None:
                    self._apply_effects(
                        panel_id, fsm.timer_expired(self._open_zone_ids(panel_id))
                    )

            self._timers[panel_id] = async_track_point_in_utc_time(
                self._hass, _expired, fx.timer_ends_at
            )

        if fx.state_changed or fx.critical_save:
            self._storage.runtime.setdefault("panels", {})[panel_id] = self.fsms[
                panel_id
            ].to_dict()
            if fx.critical_save:
                self._hass.async_create_task(self._storage.async_save_runtime())
            else:
                self._storage.delay_save_runtime()
        if fx.state_changed:
            fsm = self.fsms.get(panel_id)
            if (
                fsm is not None
                and fsm.state is not PanelState.TRIGGERED
                and self.engine.has_instances(panel_id)
            ):
                self._hass.async_create_task(
                    self.engine.async_stop_panel(panel_id, restore=True)
                )
            async_dispatcher_send(self._hass, SIGNAL_PANEL_STATE, panel_id)
            async_dispatcher_send(self._hass, SIGNAL_PANEL_STATE, MASTER_ID)

"""Alarm control panel entities: one per area panel plus a master panel."""
from __future__ import annotations

from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KustosConfigEntry
from .const import DOMAIN, SIGNAL_PANEL_STATE, ArmMode
from .core.fsm import PanelState
from .core.hub import MASTER_ID, KustosHub

_MODE_TO_FEATURE = {
    ArmMode.AWAY: AlarmControlPanelEntityFeature.ARM_AWAY,
    ArmMode.HOME: AlarmControlPanelEntityFeature.ARM_HOME,
    ArmMode.NIGHT: AlarmControlPanelEntityFeature.ARM_NIGHT,
    ArmMode.VACATION: AlarmControlPanelEntityFeature.ARM_VACATION,
    ArmMode.CUSTOM_BYPASS: AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS,
}

_MODE_TO_STATE = {
    ArmMode.AWAY: AlarmControlPanelState.ARMED_AWAY,
    ArmMode.HOME: AlarmControlPanelState.ARMED_HOME,
    ArmMode.NIGHT: AlarmControlPanelState.ARMED_NIGHT,
    ArmMode.VACATION: AlarmControlPanelState.ARMED_VACATION,
    ArmMode.CUSTOM_BYPASS: AlarmControlPanelState.ARMED_CUSTOM_BYPASS,
}

SERVICE_ACKNOWLEDGE = "acknowledge"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KustosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = entry.runtime_data.hub
    entities: list[AlarmControlPanelEntity] = [
        KustosAreaPanel(hub, panel_id) for panel_id in hub.fsms
    ]
    entities.append(KustosMasterPanel(hub))
    for group in entry.runtime_data.storage.groups.async_items():
        entities.append(KustosGroupPanel(hub, group))
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ACKNOWLEDGE, cv.make_entity_service_schema({}), "async_acknowledge"
    )


class _KustosPanelBase(AlarmControlPanelEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False

    def __init__(self, hub: KustosHub, panel_id: str) -> None:
        self._hub = hub
        self._panel_id = panel_id
        self._attr_unique_id = f"{DOMAIN}_{panel_id}"

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PANEL_STATE, self._on_panel_state)
        )

    @callback
    def _on_panel_state(self, panel_id: str) -> None:
        if panel_id == self._panel_id:
            self.async_write_ha_state()

    @staticmethod
    def _to_ha_state(
        state: PanelState, arm_mode: ArmMode | None
    ) -> AlarmControlPanelState:
        if state is PanelState.DISARMED:
            return AlarmControlPanelState.DISARMED
        if state is PanelState.ARMING:
            return AlarmControlPanelState.ARMING
        if state is PanelState.PENDING:
            return AlarmControlPanelState.PENDING
        if state is PanelState.TRIGGERED:
            return AlarmControlPanelState.TRIGGERED
        if arm_mode is not None:
            return _MODE_TO_STATE[arm_mode]
        return AlarmControlPanelState.DISARMED

    def _code_required_for(self, action: str) -> bool:
        raise NotImplementedError

    @property
    def code_format(self) -> CodeFormat | None:
        """State-dependent (Alarmo pattern): the format for the NEXT action."""
        if not self._hub.has_pin_users():
            return None
        action = "arm" if self.alarm_state == AlarmControlPanelState.DISARMED else "disarm"
        return CodeFormat.NUMBER if self._code_required_for(action) else None

    @property
    def code_arm_required(self) -> bool:
        return self._hub.has_pin_users() and self._code_required_for("arm")

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._hub.async_disarm(self._panel_id, actor=self._actor(), code=code)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._arm(ArmMode.AWAY, code)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self._arm(ArmMode.HOME, code)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        await self._arm(ArmMode.NIGHT, code)

    async def async_alarm_arm_vacation(self, code: str | None = None) -> None:
        await self._arm(ArmMode.VACATION, code)

    async def async_alarm_arm_custom_bypass(self, code: str | None = None) -> None:
        await self._arm(ArmMode.CUSTOM_BYPASS, code)

    async def async_acknowledge(self) -> None:
        await self._hub.async_acknowledge(self._panel_id, actor=self._actor())

    async def _arm(self, mode: ArmMode, code: str | None = None) -> None:
        await self._hub.async_arm(self._panel_id, mode, actor=self._actor(), code=code)

    def _actor(self) -> str:
        context = self._context
        if context is not None and context.user_id:
            return f"user:{context.user_id}"
        return "service"


class KustosAreaPanel(_KustosPanelBase):
    def _code_required_for(self, action: str) -> bool:
        return self._hub.code_required(self._panel_id, action)

    def __init__(self, hub: KustosHub, panel_id: str) -> None:
        super().__init__(hub, panel_id)
        fsm = hub.fsms[panel_id]
        self._attr_supported_features = AlarmControlPanelEntityFeature(0)
        for mode in fsm.enabled_modes:
            self._attr_supported_features |= _MODE_TO_FEATURE[mode]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, panel_id)},
            name=f"Kustos {hub.panel_title(panel_id)}",
            manufacturer="Qorvano",
            model="Kustos Panel",
        )

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        fsm = self._hub.fsms[self._panel_id]
        return self._to_ha_state(fsm.state, fsm.arm_mode)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fsm = self._hub.fsms[self._panel_id]
        return {
            "panel_id": fsm.panel_id,
            "area_id": fsm.area_id,
            "arm_mode": fsm.arm_mode,
            "ends_at": fsm.ends_at.isoformat() if fsm.ends_at else None,
            "bypassed_zones": sorted(fsm.bypassed_zones),
            "active_alarm_types": sorted(fsm.active_alarm_types),
            "alarm_memory": list(fsm.alarm_memory),
        }


class KustosMasterPanel(_KustosPanelBase):
    def _code_required_for(self, action: str) -> bool:
        return any(
            self._hub.code_required(panel_id, action) for panel_id in self._hub.fsms
        )

    def __init__(self, hub: KustosHub) -> None:
        super().__init__(hub, MASTER_ID)
        features = AlarmControlPanelEntityFeature(0)
        for fsm in hub.fsms.values():
            for mode in fsm.enabled_modes:
                features |= _MODE_TO_FEATURE[mode]
        self._attr_supported_features = features
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, MASTER_ID)},
            name="Kustos",
            manufacturer="Qorvano",
            model="Kustos Master",
        )

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        state, mode = self._hub.master_state
        return self._to_ha_state(state, mode)


class KustosGroupPanel(_KustosPanelBase):
    """A user-defined set of panels; the union counts (arming pre-checks all
    member zones, the aggregate state follows the most severe member)."""

    def _code_required_for(self, action: str) -> bool:
        return any(
            self._hub.code_required(pid, action)
            for pid in self._hub.resolve_target(self._panel_id)
        )

    def __init__(self, hub: KustosHub, group: dict) -> None:
        super().__init__(hub, group["id"])
        self._group = group
        features = AlarmControlPanelEntityFeature(0)
        for pid in hub.resolve_target(group["id"]):
            for mode in hub.fsms[pid].enabled_modes:
                features |= _MODE_TO_FEATURE[mode]
        self._attr_supported_features = features
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, group["id"])},
            name=f"Kustos {group['name']}",
            manufacturer="Qorvano",
            model="Kustos Gruppe",
        )

    @callback
    def _on_panel_state(self, panel_id: str) -> None:
        # Any member change may move the aggregate.
        self.async_write_ha_state()

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        state, mode = self._hub.group_state(self._panel_id)
        return self._to_ha_state(state, mode)

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "group_id": self._panel_id,
            "panels": self._hub.resolve_target(self._panel_id),
        }

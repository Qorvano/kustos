"""Companion entities: a ready-to-arm sensor per area panel."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from . import KustosConfigEntry
from .const import DOMAIN, SIGNAL_CONFIG_UPDATED, SIGNAL_PANEL_STATE
from .core.hub import KustosHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KustosConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub = entry.runtime_data.hub
    async_add_entities(KustosReadySensor(hub, panel_id) for panel_id in hub.fsms)


class KustosReadySensor(BinarySensorEntity):
    """On when every enabled mode of the panel could be armed right now."""

    _attr_has_entity_name = True
    _attr_translation_key = "ready"
    _attr_should_poll = False

    def __init__(self, hub: KustosHub, panel_id: str) -> None:
        self._hub = hub
        self._panel_id = panel_id
        self._attr_unique_id = f"{DOMAIN}_{panel_id}_ready"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, panel_id)})
        self._zone_track_unsub: Any | None = None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_PANEL_STATE, self._on_signal)
        )
        # Zones can be added/removed at runtime: re-track on every config change.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONFIG_UPDATED, self._on_config_updated
            )
        )
        self._track_zones()

    async def async_will_remove_from_hass(self) -> None:
        self._untrack_zones()

    @callback
    def _track_zones(self) -> None:
        self._untrack_zones()
        zone_entities = self._hub.zone_entity_ids(self._panel_id)
        if zone_entities:
            self._zone_track_unsub = async_track_state_change_event(
                self.hass, zone_entities, self._on_zone_change
            )

    @callback
    def _untrack_zones(self) -> None:
        if self._zone_track_unsub is not None:
            self._zone_track_unsub()
            self._zone_track_unsub = None

    @callback
    def _on_config_updated(self) -> None:
        self._track_zones()
        self.async_write_ha_state()

    @callback
    def _on_signal(self, panel_id: str) -> None:
        if panel_id == self._panel_id:
            self.async_write_ha_state()

    @callback
    def _on_zone_change(self, _event) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        fsm = self._hub.fsms[self._panel_id]
        return not any(
            self._hub.blocking_zones(self._panel_id, mode)
            for mode in fsm.enabled_modes
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        fsm = self._hub.fsms[self._panel_id]
        return {
            "blocking_zones": {
                mode.value: self._hub.blocking_zones(self._panel_id, mode)
                for mode in sorted(fsm.enabled_modes)
            }
        }

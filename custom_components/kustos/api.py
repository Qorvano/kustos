"""WebSocket API: resource-oriented CRUD plus settings and runtime state.

Everything here is admin-only (critique finding 11: zone and config details
are reconnaissance information). Registered exactly once per HA run.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.collection import DictStorageCollectionWebsocket

from .const import DOMAIN
from .schemas import (
    PANEL_CREATE_FIELDS,
    PANEL_UPDATE_FIELDS,
    PROFILE_CREATE_FIELDS,
    PROFILE_UPDATE_FIELDS,
    SETTINGS_SCHEMA,
    ZONE_CREATE_FIELDS,
    ZONE_UPDATE_FIELDS,
    merge_defaults,
)
from .storage import KustosStorage


@callback
def async_register(hass: HomeAssistant, storage: KustosStorage) -> None:
    """Register all WebSocket commands (called once, when storage is created)."""
    DictStorageCollectionWebsocket(
        storage.panels,
        f"{DOMAIN}/panels",
        "panel",
        PANEL_CREATE_FIELDS,
        PANEL_UPDATE_FIELDS,
        admin_only=True,
    ).async_setup(hass)
    DictStorageCollectionWebsocket(
        storage.zones,
        f"{DOMAIN}/zones",
        "zone",
        ZONE_CREATE_FIELDS,
        ZONE_UPDATE_FIELDS,
        admin_only=True,
    ).async_setup(hass)
    DictStorageCollectionWebsocket(
        storage.profiles,
        f"{DOMAIN}/profiles",
        "profile",
        PROFILE_CREATE_FIELDS,
        PROFILE_UPDATE_FIELDS,
        admin_only=True,
    ).async_setup(hass)
    websocket_api.async_register_command(hass, ws_settings_get)
    websocket_api.async_register_command(hass, ws_settings_update)
    websocket_api.async_register_command(hass, ws_state_list)


def _storage(hass: HomeAssistant) -> KustosStorage:
    return hass.data[DOMAIN]["storage"]


def _hub(hass: HomeAssistant):
    for entry in hass.config_entries.async_entries(DOMAIN):
        if hasattr(entry, "runtime_data") and entry.runtime_data is not None:
            return entry.runtime_data.hub
    return None


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/settings/get"})
@websocket_api.require_admin
@callback
def ws_settings_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    connection.send_result(msg["id"], _storage(hass).settings)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/settings/update",
        vol.Required("settings"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_settings_update(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Deep-merge a partial settings patch over the current document."""
    storage = _storage(hass)
    merged = merge_defaults(storage.settings, msg["settings"])
    try:
        validated = SETTINGS_SCHEMA(merged)
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
        return
    await storage.async_save_settings(validated)
    connection.send_result(msg["id"], validated)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/state/list"})
@websocket_api.require_admin
@callback
def ws_state_list(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Runtime state of all panels plus the master aggregate."""
    hub = _hub(hass)
    if hub is None:
        connection.send_error(msg["id"], "not_loaded", "Kustos is not loaded")
        return
    panels = [
        {
            "panel_id": fsm.panel_id,
            "area_id": fsm.area_id,
            "state": fsm.state,
            "arm_mode": fsm.arm_mode,
            "ends_at": fsm.ends_at.isoformat() if fsm.ends_at else None,
            "bypassed_zones": sorted(fsm.bypassed_zones),
            "active_alarm_types": sorted(fsm.active_alarm_types),
            "alarm_memory": list(fsm.alarm_memory),
        }
        for fsm in hub.fsms.values()
    ]
    master_state, master_mode = hub.master_state
    connection.send_result(
        msg["id"],
        {"panels": panels, "master": {"state": master_state, "arm_mode": master_mode}},
    )

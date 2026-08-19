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
from .core.auth import hash_pin
from .schemas import (
    PANEL_CREATE_FIELDS,
    PANEL_UPDATE_FIELDS,
    PERSON_CREATE_FIELDS,
    PERSON_UPDATE_FIELDS,
    PIN_SCHEMA,
    RULE_CREATE_FIELDS,
    RULE_UPDATE_FIELDS,
    PROFILE_CREATE_FIELDS,
    PROFILE_UPDATE_FIELDS,
    USER_CREATE_FIELDS,
    USER_UPDATE_FIELDS,
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
    DictStorageCollectionWebsocket(
        storage.users,
        f"{DOMAIN}/users",
        "user",
        USER_CREATE_FIELDS,
        USER_UPDATE_FIELDS,
        admin_only=True,
    ).async_setup(hass)
    DictStorageCollectionWebsocket(
        storage.persons,
        f"{DOMAIN}/persons",
        "person",
        PERSON_CREATE_FIELDS,
        PERSON_UPDATE_FIELDS,
        admin_only=True,
    ).async_setup(hass)
    DictStorageCollectionWebsocket(
        storage.rules,
        f"{DOMAIN}/rules",
        "rule",
        RULE_CREATE_FIELDS,
        RULE_UPDATE_FIELDS,
        admin_only=True,
    ).async_setup(hass)
    websocket_api.async_register_command(hass, ws_abort_auto_arm)
    websocket_api.async_register_command(hass, ws_import_alarmo)
    websocket_api.async_register_command(hass, ws_user_set_pin)
    websocket_api.async_register_command(hass, ws_settings_get)
    websocket_api.async_register_command(hass, ws_settings_update)
    websocket_api.async_register_command(hass, ws_state_list)
    websocket_api.async_register_command(hass, ws_audit_query)
    websocket_api.async_register_command(hass, ws_walk_test)


def _storage(hass: HomeAssistant) -> KustosStorage:
    return hass.data[DOMAIN]["storage"]


def _hub(hass: HomeAssistant):
    for entry in hass.config_entries.async_entries(DOMAIN):
        if hasattr(entry, "runtime_data") and entry.runtime_data is not None:
            return entry.runtime_data.hub
    return None


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/import/alarmo",
        # The "data" object of .storage/alarmo_storage, pasted by the user.
        vol.Required("data"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_import_alarmo(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    from .core.importer import async_import_alarmo

    result = await async_import_alarmo(hass, _storage(hass), msg["data"])
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/auto_arm/abort",
        vol.Required("rule_id"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_abort_auto_arm(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    hub = _hub(hass)
    if hub is None:
        connection.send_error(msg["id"], "not_loaded", "Kustos is not loaded")
        return
    connection.send_result(
        msg["id"], {"aborted": hub.presence.abort_prewarn_by_id(msg["rule_id"])}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/users/set_pin",
        vol.Required("user_id"): str,
        # None removes the PIN of that kind.
        vol.Required("pin"): vol.Any(None, PIN_SCHEMA),
        vol.Required("kind", default="normal"): vol.In(["normal", "duress"]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_user_set_pin(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Set or remove a user PIN. Hashes only; plaintext never persists."""
    storage = _storage(hass)
    if not any(u["id"] == msg["user_id"] for u in storage.users.async_items()):
        connection.send_error(msg["id"], "not_found", "unknown user")
        return
    pins = storage.pins.setdefault(msg["user_id"], {})
    if msg["pin"] is None:
        pins.pop(msg["kind"], None)
    else:
        pins[msg["kind"]] = hash_pin(msg["pin"])
    await storage.async_save_pins()
    connection.send_result(msg["id"], {"kinds": sorted(pins)})


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


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/audit/query",
        vol.Optional("month"): str,
        vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_audit_query(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    from homeassistant.util import dt as dt_util

    hub = _hub(hass)
    if hub is None:
        connection.send_error(msg["id"], "not_loaded", "Kustos is not loaded")
        return
    storage = _storage(hass)
    month = msg.get("month") or dt_util.utcnow().strftime("%Y-%m")
    limit = min(
        msg.get("limit") or storage.setting("audit", "query_limit"),
        storage.setting("audit", "query_limit"),
    )
    connection.send_result(
        msg["id"], {"month": month, "entries": await hub.audit.async_query(month, limit)}
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/walk_test",
        vol.Required("panel_id"): str,
        vol.Required("action"): vol.In(["start", "stop"]),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_walk_test(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    hub = _hub(hass)
    if hub is None or msg["panel_id"] not in hub.fsms:
        connection.send_error(msg["id"], "not_found", "unknown panel")
        return
    actor = f"user:{connection.user.name}" if connection.user else "ws"
    if msg["action"] == "start":
        await hub.async_walk_test_start(msg["panel_id"], actor)
    else:
        await hub.async_walk_test_stop(msg["panel_id"], actor)
    info = hub.walk_tests.get(msg["panel_id"])
    connection.send_result(
        msg["id"],
        {
            "active": info is not None,
            "ends_at": info["ends_at"] if info else None,
            "tested_zones": sorted(info["tested"]) if info else [],
        },
    )


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
        {
            "panels": panels,
            "master": {"state": master_state, "arm_mode": master_mode},
            "presence": hub.presence.phases(),
            "walk_tests": {
                panel_id: {"ends_at": info["ends_at"], "tested": sorted(info["tested"])}
                for panel_id, info in hub.walk_tests.items()
            },
        },
    )

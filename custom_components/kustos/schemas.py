"""Central voluptuous schemas for Kustos.

Single source of truth: the same schemas validate WebSocket payloads,
storage documents on load, and migrations. All numeric defaults live here
exactly once (DEFAULT_SETTINGS) with their reasoning; runtime code reads the
settings store, never these literals.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .const import AlarmType, ArmMode, PanelScope, ZoneRole

# ---------------------------------------------------------------------------
# Settings (seeded into the settings store on first setup; user-editable)
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    "defaults": {
        # Common residential values: long enough to leave/enter calmly.
        "exit_delay_s": 60.0,
        "entry_delay_s": 30.0,
        # trigger_time limits the audible/visible chain only; the alarm
        # instance itself lives until acknowledge/disarm (critique finding 5).
        # 0 means: no automatic end.
        "trigger_time_s": 180.0,
        # Contact debounce to swallow the bounce of a closing door; 0 = off.
        "debounce_s": 0.0,
    },
    "security": {
        # Alarm memory requires an explicit acknowledge by default.
        "require_explicit_ack": True,
        # Whether a disarm implicitly acknowledges the alarm memory.
        "disarm_acknowledges": False,
    },
    "storage": {
        # Non-critical runtime saves are debounced; critical transitions
        # (arming/pending/triggered/disarm) always save immediately.
        "runtime_save_delay_s": 2.0,
    },
}

_NON_NEGATIVE_SECONDS = vol.All(vol.Coerce(float), vol.Range(min=0))

SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Required("defaults"): vol.Schema(
            {
                vol.Required("exit_delay_s"): _NON_NEGATIVE_SECONDS,
                vol.Required("entry_delay_s"): _NON_NEGATIVE_SECONDS,
                vol.Required("trigger_time_s"): _NON_NEGATIVE_SECONDS,
                vol.Required("debounce_s"): _NON_NEGATIVE_SECONDS,
            }
        ),
        vol.Required("security"): vol.Schema(
            {
                vol.Required("require_explicit_ack"): cv.boolean,
                vol.Required("disarm_acknowledges"): cv.boolean,
            }
        ),
        vol.Required("storage"): vol.Schema(
            {
                vol.Required("runtime_save_delay_s"): _NON_NEGATIVE_SECONDS,
            }
        ),
    }
)


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

MODE_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required("enabled", default=False): cv.boolean,
        # Absent values fall back to settings["defaults"] at runtime.
        vol.Optional("exit_delay_s"): _NON_NEGATIVE_SECONDS,
        vol.Optional("entry_delay_s"): _NON_NEGATIVE_SECONDS,
        vol.Optional("trigger_time_s"): _NON_NEGATIVE_SECONDS,
    }
)


def _validate_scope(scope: dict[str, Any]) -> dict[str, Any]:
    """An area panel needs an area_id; the master panel must not have one."""
    if scope["type"] == PanelScope.AREA and not scope.get("area_id"):
        raise vol.Invalid("area panels require area_id")
    if scope["type"] == PanelScope.MASTER and scope.get("area_id"):
        raise vol.Invalid("master panel must not carry an area_id")
    return scope


SCOPE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("type"): vol.Coerce(PanelScope),
            vol.Optional("area_id"): cv.string,
        }
    ),
    _validate_scope,
)

PANEL_OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required("code_arm_required", default=False): cv.boolean,
        vol.Required("code_disarm_required", default=True): cv.boolean,
        # After trigger_time expires: return to the previous armed mode
        # (open zones get auto-bypassed then - critique finding 13).
        vol.Required("rearm_after_trigger", default=True): cv.boolean,
    }
)

MODES_MAP_SCHEMA = vol.Schema({vol.Coerce(ArmMode): MODE_CONFIG_SCHEMA})

# Create: full document with defaults. Update: every field optional; sub-
# objects (scope/modes/options) are replaced as a whole, never merged field-
# wise, so a partial update can never silently reset sibling values.
PANEL_CREATE_FIELDS = {
    vol.Required("scope"): SCOPE_SCHEMA,
    vol.Required("enabled", default=True): cv.boolean,
    vol.Required("modes", default=dict): MODES_MAP_SCHEMA,
    vol.Required("options", default=dict): PANEL_OPTIONS_SCHEMA,
}
PANEL_UPDATE_FIELDS = {
    vol.Optional("scope"): SCOPE_SCHEMA,
    vol.Optional("enabled"): cv.boolean,
    vol.Optional("modes"): MODES_MAP_SCHEMA,
    vol.Optional("options"): PANEL_OPTIONS_SCHEMA,
}
PANEL_FIELDS = vol.Schema(PANEL_CREATE_FIELDS)


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

ZONE_OPTIONS_SCHEMA = vol.Schema(
    {
        # Zone may be open while the exit delay runs (leaving through it).
        vol.Required("use_exit_delay", default=False): cv.boolean,
        # Closing the zone during exit delay arms immediately.
        vol.Required("arm_after_closing", default=False): cv.boolean,
        # Zone may stay open through arming; only a new trip triggers.
        vol.Required("allow_open", default=False): cv.boolean,
        # Open zone is bypassed automatically instead of blocking the arm.
        vol.Required("auto_bypass", default=False): cv.boolean,
        # Treat unavailable as a trip (dead or sabotaged sensor).
        vol.Required("trigger_when_unavailable", default=False): cv.boolean,
        # Invert the on/off semantics of the source entity.
        vol.Required("invert", default=False): cv.boolean,
        # Per-zone debounce override; absent = settings default.
        vol.Optional("debounce_s"): _NON_NEGATIVE_SECONDS,
    }
)

ZONE_MODES_MAP_SCHEMA = vol.Schema({vol.Coerce(ArmMode): vol.Coerce(ZoneRole)})

ZONE_CREATE_FIELDS = {
    vol.Required("entity_id"): cv.entity_id,
    vol.Required("panel_id"): cv.string,
    vol.Optional("name"): cv.string,
    # Which alarm type this zone raises. Types in ALWAYS_ON_ALARM_TYPES
    # are armed 24/7 regardless of panel state (derived, no extra flag).
    vol.Required("alarm_type", default=AlarmType.BURGLARY): vol.Coerce(AlarmType),
    # Role per arm mode; modes not listed fall back to "inactive".
    vol.Required("modes", default=dict): ZONE_MODES_MAP_SCHEMA,
    vol.Required("options", default=dict): ZONE_OPTIONS_SCHEMA,
}
ZONE_UPDATE_FIELDS = {
    vol.Optional("entity_id"): cv.entity_id,
    vol.Optional("panel_id"): cv.string,
    vol.Optional("name"): cv.string,
    vol.Optional("alarm_type"): vol.Coerce(AlarmType),
    vol.Optional("modes"): ZONE_MODES_MAP_SCHEMA,
    vol.Optional("options"): ZONE_OPTIONS_SCHEMA,
}
ZONE_FIELDS = vol.Schema(ZONE_CREATE_FIELDS)


def merge_defaults(defaults: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge stored settings over defaults so new keys appear after updates."""
    result = dict(defaults)
    for key, value in stored.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_defaults(result[key], value)
        else:
            result[key] = value
    return result

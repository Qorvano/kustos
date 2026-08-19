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
        # A forgotten walk test must end itself; 15 min covers a full round
        # through the house comfortably.
        "walk_test_timeout_s": 900.0,
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
    "audit": {
        # How many entries a single audit query returns at most.
        "query_limit": 200,
    },
    "presence": {
        # 500 m stammt aus der bestehenden Proximity-Logik des Users und ist
        # im Panel sichtbar aenderbar; die Rueckkehr-Schwelle wird als
        # Haelfte abgeleitet statt als zweite freie Zahl gepflegt.
        "away_confirm_distance_m": 500.0,
        # Ohne Distanzquelle gilt eine Person erst nach dieser Dauer
        # not_home als bestaetigt abwesend (WLAN-Flattern abfangen).
        "min_away_duration_s": 120.0,
        # Vorwarnzeit vor dem automatischen Scharfschalten.
        "prewarn_s": 120.0,
    },
    "engine": {
        # Entities that came back after being unavailable during an alarm get
        # one late restore attempt within this window.
        "restore_retry_window_s": 300.0,
        # Claim priority when two alarm types fight over the same entity;
        # earlier in the list wins. Life safety outranks burglary; holdup is
        # last because a silent alarm must not touch shared entities anyway.
        "alarm_type_priority": [
            "fire", "co", "water", "tamper", "panic", "burglary",
            "technical", "holdup",
        ],
        # Alarm types that may unlock doors (escape route). Everything else
        # is refused the unlock block outright.
        "life_safety_unlock_types": ["fire", "co"],
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
                vol.Required("walk_test_timeout_s"): _NON_NEGATIVE_SECONDS,
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
        vol.Required("audit"): vol.Schema(
            {vol.Required("query_limit"): vol.All(vol.Coerce(int), vol.Range(min=1, max=5000))}
        ),
        vol.Required("presence"): vol.Schema(
            {
                vol.Required("away_confirm_distance_m"): vol.All(
                    vol.Coerce(float), vol.Range(min=1)
                ),
                vol.Required("min_away_duration_s"): _NON_NEGATIVE_SECONDS,
                vol.Required("prewarn_s"): _NON_NEGATIVE_SECONDS,
            }
        ),
        vol.Required("engine"): vol.Schema(
            {
                vol.Required("restore_retry_window_s"): _NON_NEGATIVE_SECONDS,
                vol.Required("alarm_type_priority"): [vol.Coerce(AlarmType)],
                vol.Required("life_safety_unlock_types"): [vol.Coerce(AlarmType)],
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
    """Area panels need an area_id, custom panels a name, master neither."""
    if scope["type"] == PanelScope.AREA and not scope.get("area_id"):
        raise vol.Invalid("area panels require area_id")
    if scope["type"] == PanelScope.CUSTOM and not scope.get("name"):
        raise vol.Invalid("custom panels require a name")
    if scope["type"] == PanelScope.MASTER and (
        scope.get("area_id") or scope.get("name")
    ):
        raise vol.Invalid("master panel must not carry area_id or name")
    return scope


SCOPE_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("type"): vol.Coerce(PanelScope),
            vol.Optional("area_id"): vol.Any(None, cv.string),
            vol.Optional("name"): vol.Any(None, cv.string),
        }
    ),
    _validate_scope,
)


# Panel groups: any set of Kustos panels, armable/aggregating as one unit.
GROUP_CREATE_FIELDS = {
    vol.Required("name"): cv.string,
    vol.Required("panel_ids", default=list): [cv.string],
}
GROUP_UPDATE_FIELDS = {
    vol.Optional("name"): cv.string,
    vol.Optional("panel_ids"): [cv.string],
}
GROUP_FIELDS = vol.Schema(GROUP_CREATE_FIELDS)

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
ALARM_TYPE_ASSIGNMENT_SCHEMA = vol.Schema(
    {vol.Coerce(AlarmType): vol.Schema({vol.Required("profile_id"): vol.Any(None, cv.string)})}
)

PANEL_CREATE_FIELDS = {
    vol.Required("scope"): SCOPE_SCHEMA,
    vol.Required("enabled", default=True): cv.boolean,
    vol.Required("modes", default=dict): MODES_MAP_SCHEMA,
    vol.Required("options", default=dict): PANEL_OPTIONS_SCHEMA,
    # Which reaction profile runs per alarm type (critique finding 4: the
    # panel document is the single source of this assignment).
    vol.Required("alarm_types", default=dict): ALARM_TYPE_ASSIGNMENT_SCHEMA,
}
PANEL_UPDATE_FIELDS = {
    vol.Optional("scope"): SCOPE_SCHEMA,
    vol.Optional("enabled"): cv.boolean,
    vol.Optional("modes"): MODES_MAP_SCHEMA,
    vol.Optional("options"): PANEL_OPTIONS_SCHEMA,
    vol.Optional("alarm_types"): ALARM_TYPE_ASSIGNMENT_SCHEMA,
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
        # What an unavailable zone does to arming: ignore silently, block the
        # arm attempt, or get bypassed visibly (supervision policy, M4).
        vol.Required("unavailable_policy", default="ignore"): vol.In(
            ["ignore", "block_arm", "auto_bypass"]
        ),
    }
)

ZONE_MODES_MAP_SCHEMA = vol.Schema({vol.Coerce(ArmMode): vol.Coerce(ZoneRole)})

ZONE_CREATE_FIELDS = {
    vol.Required("entity_id"): cv.entity_id,
    vol.Required("panel_id"): cv.string,
    # None is equivalent to absent (update flows write None to clear).
    vol.Optional("name"): vol.Any(None, cv.string),
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
    vol.Optional("name"): vol.Any(None, cv.string),
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


# ---------------------------------------------------------------------------
# Reaction profiles (M2): 1-3 stages as a deterministic timeline from t0
# ---------------------------------------------------------------------------

_PERCENT = vol.All(vol.Coerce(float), vol.Range(min=1, max=100))
_POSITIVE_SECONDS = vol.All(vol.Coerce(float), vol.Range(min=0.1))
_RGB = vol.All([vol.All(vol.Coerce(int), vol.Range(min=0, max=255))], vol.Length(min=3, max=3))

_BLOCK_COMMON = {vol.Required("type"): str}

BLOCK_SCHEMAS: dict[str, vol.Schema] = {
    # Color-capable lights blink; the rest behaves per non_color_behavior.
    "flash_lights": vol.Schema(
        {
            vol.Required("type"): "flash_lights",
            vol.Required("targets"): [cv.entity_id],
            vol.Required("color_rgb", default=[255, 0, 0]): _RGB,
            vol.Required("brightness_pct", default=100.0): _PERCENT,
            # Full blink period (on + off) and fade portion of each half.
            vol.Required("period_s", default=2.0): _POSITIVE_SECONDS,
            vol.Required("fade_s", default=0.4): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Required("non_color_behavior", default="off"): vol.In(
                ["off", "hard_blink", "ignore"]
            ),
        }
    ),
    # Steady on (outdoor lights); refresh re-sends for self-timing floodlights.
    "lights_on": vol.Schema(
        {
            vol.Required("type"): "lights_on",
            vol.Required("targets"): [cv.entity_id],
            vol.Required("brightness_pct", default=100.0): _PERCENT,
            vol.Required("refresh_interval_s", default=0.0): vol.All(
                vol.Coerce(float), vol.Range(min=0)
            ),
        }
    ),
    # Sounders in three flavours, derived from the entity domain:
    # siren -> native; switch/input_boolean -> on/off; button/input_button ->
    # pulse plus retrigger interval (X-Sense fire drill pattern).
    "sound": vol.Schema(
        {
            vol.Required("type"): "sound",
            vol.Required("targets"): [cv.entity_id],
            vol.Required("retrigger_interval_s", default=30.0): _POSITIVE_SECONDS,
            # Deliberately no default: the legal siren-duration limit is the
            # user's call; the engine only enforces that a value exists.
            vol.Required("max_duration_s"): _POSITIVE_SECONDS,
        }
    ),
    # Repeating announcement via a notify service, with optional volume set
    # and per-device fallback for players whose volume cannot be read.
    "announce_loop": vol.Schema(
        {
            vol.Required("type"): "announce_loop",
            vol.Required("notify_service"): cv.string,  # e.g. "notify.alexa_media"
            vol.Required("message"): cv.string,
            vol.Required("interval_s"): _POSITIVE_SECONDS,
            vol.Required("media_targets", default=list): [cv.entity_id],
            vol.Optional("volume_pct"): _PERCENT,
            vol.Optional("volume_fallback_pct"): _PERCENT,
            vol.Optional("data", default=dict): dict,
        }
    ),
    # One-shot notification at stage start.
    "notify": vol.Schema(
        {
            vol.Required("type"): "notify",
            vol.Required("service"): cv.string,
            vol.Required("message"): cv.string,
            vol.Optional("title"): cv.string,
            vol.Optional("data", default=dict): dict,
        }
    ),
    # Lock or unlock; unlock is validated against life_safety_unlock_types.
    "lock": vol.Schema(
        {
            vol.Required("type"): "lock",
            vol.Required("targets"): [cv.entity_id],
            vol.Required("action"): vol.In(["lock", "unlock"]),
        }
    ),
}


def _validate_block(block: dict) -> dict:
    if not isinstance(block, dict) or "type" not in block:
        raise vol.Invalid("block needs a type")
    schema = BLOCK_SCHEMAS.get(block["type"])
    if schema is None:
        raise vol.Invalid(f"unknown block type {block['type']}")
    return schema(block)


STAGE_SCHEMA = vol.Schema(
    {
        # None = stage runs until the alarm ends (only valid for the last stage).
        vol.Required("duration_s", default=None): vol.Any(None, _POSITIVE_SECONDS),
        vol.Required("blocks"): [_validate_block],
    }
)


def _validate_stages(stages: list) -> list:
    if not 1 <= len(stages) <= 3:
        raise vol.Invalid("profiles have 1 to 3 stages")
    for stage in stages[:-1]:
        if stage["duration_s"] is None:
            raise vol.Invalid("only the last stage may have an open duration")
    return stages


PROFILE_CREATE_FIELDS = {
    vol.Required("name"): cv.string,
    vol.Required("stages"): vol.All([STAGE_SCHEMA], _validate_stages),
}
PROFILE_UPDATE_FIELDS = {
    vol.Optional("name"): cv.string,
    vol.Optional("stages"): vol.All([STAGE_SCHEMA], _validate_stages),
}
PROFILE_FIELDS = vol.Schema(PROFILE_CREATE_FIELDS)

# ---------------------------------------------------------------------------
# Users (M3). PINs live in a separate store, never in these documents.
# ---------------------------------------------------------------------------

USER_RIGHTS_SCHEMA = vol.Schema(
    {
        vol.Required("can_arm", default=True): cv.boolean,
        vol.Required("can_disarm", default=True): cv.boolean,
        # None = all panels; otherwise a list of permitted panel_ids.
        vol.Required("panels", default=None): vol.Any(None, [cv.string]),
    }
)

USER_CREATE_FIELDS = {
    vol.Required("name"): cv.string,
    vol.Required("enabled", default=True): cv.boolean,
    vol.Required("rights", default=dict): USER_RIGHTS_SCHEMA,
    # Users are auto-synced from HA persons; this is the link.
    vol.Optional("person_entity"): vol.Any(None, cv.entity_id),
}
USER_UPDATE_FIELDS = {
    vol.Optional("name"): cv.string,
    vol.Optional("enabled"): cv.boolean,
    vol.Optional("rights"): USER_RIGHTS_SCHEMA,
    vol.Optional("person_entity"): vol.Any(None, cv.entity_id),
}
USER_FIELDS = vol.Schema(USER_CREATE_FIELDS)

# Documented baseline, not a magic number: 4 digits is the classic keypad
# minimum; users may set longer PINs. Digits only (keypad compatibility).
PIN_MIN_LENGTH = 4
PIN_SCHEMA = vol.All(cv.string, vol.Match(rf"^\d{{{PIN_MIN_LENGTH},}}$"))


# Blocks that make an alarm locally perceivable; forbidden for silent types
# (critique finding 1: a hold-up alarm must not be observable on site).
PERCEIVABLE_BLOCK_TYPES = frozenset(
    {"flash_lights", "lights_on", "sound", "announce_loop"}
)


# ---------------------------------------------------------------------------
# Presence (M5): tracked persons and auto-arm/disarm rules
# ---------------------------------------------------------------------------

PERSON_CREATE_FIELDS = {
    vol.Required("name"): cv.string,
    # Auto-synced from HA persons; the tracker defaults to the person entity.
    vol.Optional("person_entity"): vol.Any(None, cv.entity_id),
    # person.* or device_tracker.*; home/not_home evidence.
    vol.Required("tracker_entity"): cv.entity_id,
    # Optional distance source (proximity sensor etc.); unit read from the
    # entity (m or km). Without it, time-based away confirmation applies.
    # None is equivalent to absent (update flows write None to clear).
    vol.Optional("distance_entity"): vol.Any(None, cv.entity_id),
    vol.Optional("away_confirm_distance_m"): vol.Any(
        None, vol.All(vol.Coerce(float), vol.Range(min=1))
    ),
}
PERSON_UPDATE_FIELDS = {
    vol.Optional("name"): cv.string,
    vol.Optional("person_entity"): vol.Any(None, cv.entity_id),
    vol.Optional("tracker_entity"): cv.entity_id,
    vol.Optional("distance_entity"): vol.Any(None, cv.entity_id),
    vol.Optional("away_confirm_distance_m"): vol.Any(
        None, vol.All(vol.Coerce(float), vol.Range(min=1))
    ),
}
PERSON_FIELDS = vol.Schema(PERSON_CREATE_FIELDS)

RULE_ARM_SCHEMA = vol.Schema(
    {
        vol.Required("mode", default=ArmMode.AWAY): vol.Coerce(ArmMode),
        # prewarn: announce first, arm after the delay; immediate arms at once.
        vol.Required("execution", default="prewarn"): vol.In(["prewarn", "immediate"]),
        vol.Optional("prewarn_s"): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)

RULE_RETURN_SCHEMA = vol.Schema(
    {
        vol.Required("disarm", default=True): cv.boolean,
        # arrived = physically home; returning would disarm hundreds of
        # meters out and is deliberately not offered in M5.
        vol.Required("fire_on", default="arrived"): vol.In(["arrived"]),
    }
)

RULE_CREATE_FIELDS = {
    vol.Required("name"): cv.string,
    vol.Required("enabled", default=True): cv.boolean,
    # Panel this rule arms/disarms; "master" cascades over all panels.
    vol.Required("panel_id"): cv.string,
    # None = all configured persons; otherwise explicit person ids.
    vol.Required("persons", default=None): vol.Any(None, [cv.string]),
    vol.Required("arm", default=dict): RULE_ARM_SCHEMA,
    vol.Required("return_action", default=dict): RULE_RETURN_SCHEMA,
    # Auto-disarm never runs in these panel states (critique finding 2:
    # pending stays blocked so a burglar-opened door cannot be swallowed
    # by a coincidentally approaching resident).
    vol.Required(
        "blocked_in_alarm_states", default=["triggered", "pending"]
    ): [vol.In(["triggered", "pending", "arming"])],
}
RULE_UPDATE_FIELDS = {
    vol.Optional("name"): cv.string,
    vol.Optional("enabled"): cv.boolean,
    vol.Optional("panel_id"): cv.string,
    vol.Optional("persons"): vol.Any(None, [cv.string]),
    vol.Optional("arm"): RULE_ARM_SCHEMA,
    vol.Optional("return_action"): RULE_RETURN_SCHEMA,
    vol.Optional("blocked_in_alarm_states"): [vol.In(["triggered", "pending", "arming"])],
}
RULE_FIELDS = vol.Schema(RULE_CREATE_FIELDS)

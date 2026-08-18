"""Constants for Kustos.

Single source for the domain, storage keys, enums and event names.
Numeric defaults live in schemas.py (DEFAULT_SETTINGS), never in code paths.
"""
from __future__ import annotations

from enum import StrEnum

DOMAIN = "kustos"

# One store per concern, individually versioned (see storage.py).
STORAGE_VERSION = 1
STORAGE_KEY_SETTINGS = f"{DOMAIN}.settings"
STORAGE_KEY_PANELS = f"{DOMAIN}.panels"
STORAGE_KEY_ZONES = f"{DOMAIN}.zones"
STORAGE_KEY_PROFILES = f"{DOMAIN}.profiles"
STORAGE_KEY_USERS = f"{DOMAIN}.users"
STORAGE_KEY_RUNTIME = f"{DOMAIN}.runtime"
STORAGE_KEY_SNAPSHOTS = f"{DOMAIN}.snapshots"


class AlarmType(StrEnum):
    """First-class alarm event categories.

    HOLDUP is the silent hold-up alarm; "duress" is a PIN kind on a user,
    never an alarm type (architecture decision, critique finding 8).
    """

    BURGLARY = "burglary"
    FIRE = "fire"
    WATER = "water"
    CO = "co"
    TAMPER = "tamper"
    HOLDUP = "holdup"
    PANIC = "panic"
    TECHNICAL = "technical"


# Zones mapped to these alarm types stay armed 24/7 regardless of panel state.
ALWAYS_ON_ALARM_TYPES: frozenset[AlarmType] = frozenset(
    {AlarmType.FIRE, AlarmType.WATER, AlarmType.CO, AlarmType.TAMPER}
)

# Alarm types that must never produce locally perceivable output
# (validated against reaction profiles; critique finding 1).
SILENT_ALARM_TYPES: frozenset[AlarmType] = frozenset({AlarmType.HOLDUP})


class ArmMode(StrEnum):
    """Supported arm modes; a panel enables a subset per configuration."""

    AWAY = "armed_away"
    HOME = "armed_home"
    NIGHT = "armed_night"
    VACATION = "armed_vacation"
    CUSTOM_BYPASS = "armed_custom_bypass"


class ZoneRole(StrEnum):
    """How a zone behaves in a given arm mode."""

    INSTANT = "instant"
    DELAYED = "delayed"
    FOLLOWER = "follower"
    INACTIVE = "inactive"


class PanelScope(StrEnum):
    AREA = "area"
    MASTER = "master"


class ArmFailReason(StrEnum):
    OPEN_ZONES = "open_zones"
    NOT_ALLOWED = "not_allowed"
    INVALID_CODE = "invalid_code"
    MODE_DISABLED = "mode_disabled"


# Bus events (stable contract for user automations).
EVENT_ARMING = f"{DOMAIN}_arming"
EVENT_ARMED = f"{DOMAIN}_armed"
EVENT_PENDING = f"{DOMAIN}_pending"
EVENT_TRIGGERED = f"{DOMAIN}_triggered"
EVENT_DISARMED = f"{DOMAIN}_disarmed"
EVENT_ARM_FAILED = f"{DOMAIN}_arm_failed"
EVENT_ACKNOWLEDGED = f"{DOMAIN}_acknowledged"
EVENT_ZONE_BYPASSED = f"{DOMAIN}_zone_bypassed"

# Event/service payload keys.
ATTR_PANEL_ID = "panel_id"
ATTR_AREA_ID = "area_id"
ATTR_ZONE_ID = "zone_id"
ATTR_ENTITY_ID = "entity_id"
ATTR_ALARM_TYPE = "alarm_type"
ATTR_ARM_MODE = "arm_mode"
ATTR_METHOD = "method"
ATTR_ACTOR = "actor"
ATTR_REASON = "reason"
ATTR_OPEN_ZONES = "open_zones"
ATTR_BYPASSED_ZONES = "bypassed_zones"
ATTR_ENDS_AT = "ends_at"
ATTR_DELAY_TOTAL_S = "delay_total_s"

# Dispatcher signals (internal, not part of the public contract).
SIGNAL_PANEL_STATE = f"{DOMAIN}_panel_state_updated"
SIGNAL_CONFIG_UPDATED = f"{DOMAIN}_config_updated"

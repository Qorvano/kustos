"""Unit tests for the central schemas (no Home Assistant instance needed)."""
import pytest
import voluptuous as vol

from custom_components.kustos.const import AlarmType, ArmMode, ZoneRole
from custom_components.kustos.schemas import (
    DEFAULT_SETTINGS,
    PANEL_FIELDS,
    SETTINGS_SCHEMA,
    ZONE_FIELDS,
    merge_defaults,
)


def test_default_settings_pass_their_own_schema():
    SETTINGS_SCHEMA(DEFAULT_SETTINGS)


def test_merge_defaults_adds_new_keys_and_keeps_user_values():
    stored = {"defaults": {"exit_delay_s": 90.0}}
    merged = merge_defaults(DEFAULT_SETTINGS, stored)
    assert merged["defaults"]["exit_delay_s"] == 90.0
    # Keys the stored document does not know yet come from the defaults.
    assert merged["defaults"]["entry_delay_s"] == DEFAULT_SETTINGS["defaults"]["entry_delay_s"]
    assert merged["security"]["require_explicit_ack"] is True


def test_area_panel_requires_area_id():
    with pytest.raises(vol.Invalid):
        PANEL_FIELDS({"scope": {"type": "area"}})


def test_master_panel_must_not_have_area_id():
    with pytest.raises(vol.Invalid):
        PANEL_FIELDS({"scope": {"type": "master", "area_id": "wohnzimmer"}})


def test_panel_defaults():
    panel = PANEL_FIELDS({"scope": {"type": "area", "area_id": "wohnzimmer"}})
    assert panel["enabled"] is True
    assert panel["options"]["code_disarm_required"] is True
    assert panel["options"]["code_arm_required"] is False
    assert panel["modes"] == {}


def test_zone_defaults_and_enums():
    zone = ZONE_FIELDS(
        {
            "entity_id": "binary_sensor.haustuer",
            "panel_id": "P1",
            "modes": {"armed_away": "delayed"},
        }
    )
    assert zone["alarm_type"] is AlarmType.BURGLARY
    assert zone["modes"][ArmMode.AWAY] is ZoneRole.DELAYED
    assert zone["options"]["auto_bypass"] is False


def test_zone_rejects_invalid_entity_id_and_role():
    with pytest.raises(vol.Invalid):
        ZONE_FIELDS({"entity_id": "not-an-entity", "panel_id": "P1"})
    with pytest.raises(vol.Invalid):
        ZONE_FIELDS(
            {
                "entity_id": "binary_sensor.haustuer",
                "panel_id": "P1",
                "modes": {"armed_away": "sometimes"},
            }
        )

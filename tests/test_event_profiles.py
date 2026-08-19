"""Profiles bound to panel state changes (arming beep, disarm chime)."""
import asyncio

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.kustos.const import DOMAIN


async def _setup(hass, event_profiles_for, stages, exit_s=0.0):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    profile = await storage.profiles.async_create_item({"name": "Quitt", "stages": stages})
    panel = await storage.panels.async_create_item(
        {
            "scope": {"type": "custom", "name": "Haus"},
            "modes": {"armed_away": {"enabled": True, "exit_delay_s": exit_s,
                                     "entry_delay_s": 0.0, "trigger_time_s": 0.0}},
            "event_profiles": {k: {"profile_id": profile["id"]} for k in event_profiles_for},
        }
    )
    await hass.async_block_till_done()
    return entry, panel["id"]


def _panel(hass):
    return next(
        eid for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id"))


async def test_armed_confirmation_beep_runs_and_cleans_up(hass):
    entry, panel_id = await _setup(
        hass, ["armed"],
        [{"duration_s": 0.2, "blocks": [{
            "type": "sound", "targets": ["switch.piepser"],
            "max_duration_s": 0.15, "retrigger_interval_s": 1.0}]}],
    )
    on = async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.piepser", "off")
    panel = _panel(hass)
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": panel}, blocking=True)
    await asyncio.sleep(0.5)
    await hass.async_block_till_done()

    assert on, "Quittierungston muss laufen"
    assert off, "und wieder ausgehen"
    hub = entry.runtime_data.hub
    # Instanz hat sich selbst aufgeraeumt, Panel bleibt scharf.
    assert not any(r["panel_id"] == panel_id for r in hub.engine._records().values())
    assert hass.states.get(panel).state == "armed_away"


async def test_arming_profile_stops_when_armed(hass):
    entry, panel_id = await _setup(
        hass, ["arming"],
        [{"duration_s": None, "blocks": [{
            "type": "flash_lights", "targets": ["light.flur"],
            "period_s": 0.2, "fade_s": 0}]}],
        exit_s=0.4,
    )
    turn_on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    hass.states.async_set("light.flur", "on",
                          {"supported_color_modes": ["hs"], "brightness": 77})
    panel = _panel(hass)
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": panel}, blocking=True)
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert turn_on, "Exit-Countdown-Blinken laeuft"

    await asyncio.sleep(0.5)  # Exit-Delay ablaufen lassen -> armed
    await hass.async_block_till_done()
    hub = entry.runtime_data.hub
    assert not any(r["panel_id"] == panel_id for r in hub.engine._records().values()), \
        "Zustandsprofil endet beim Zustandswechsel"
    # Restore lief: Original-Helligkeit wieder gesetzt.
    restore = [c for c in turn_on if "rgb_color" not in c.data]
    assert restore and restore[-1].data["brightness"] == 77
    assert hass.states.get(panel).state == "armed_away"

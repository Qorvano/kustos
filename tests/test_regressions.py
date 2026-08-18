"""Regression tests.

Convention (see global working rules): every bug found in Kustos gets a test
here FIRST that reproduces it, then the fix. Tests reference the bug (issue
number or a dated description) and stay forever.
"""


import asyncio

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.kustos.const import DOMAIN, STORAGE_KEY_SNAPSHOTS


async def test_rearm_during_downtime_restores_originals_not_alarm_colors(
    hass, hass_storage
):
    """Regression 2026-08-19 (Live-E2E Testinstanz): Nach einem Neustart, bei
    dem die trigger_time waehrend der Downtime ablief, lief ein Race zwischen
    Engine-Stop (Restore) und Engine-Resume. Die wiederbelebte Blink-Schleife
    zog frische Snapshots vom Alarm-Rot; das Entschaerfen restaurierte dann
    Rot statt der Originalzustaende. Boot muss deterministisch sein:
    restore -> resume -> genau eine Reconcile-Passe.
    """
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    storage = entry.runtime_data.storage
    profile = await storage.profiles.async_create_item(
        {
            "name": "Blink",
            "stages": [
                {
                    "duration_s": None,
                    "blocks": [
                        {
                            "type": "flash_lights",
                            "targets": ["light.wz"],
                            "period_s": 0.2,
                            "fade_s": 0,
                        }
                    ],
                }
            ],
        }
    )
    panel = await storage.panels.async_create_item(
        {
            "scope": {"type": "area", "area_id": "wz"},
            "modes": {
                "armed_away": {
                    "enabled": True,
                    "exit_delay_s": 0.0,
                    "entry_delay_s": 0.0,
                    # trigger_time expires while "down" in this test
                    "trigger_time_s": 0.3,
                }
            },
            "alarm_types": {"burglary": {"profile_id": profile["id"]}},
        }
    )
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    await storage.zones.async_create_item(
        {
            "entity_id": "input_boolean.z",
            "panel_id": panel["id"],
            "modes": {"armed_away": "instant"},
        }
    )
    await hass.async_block_till_done()

    turn_on = async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    hass.states.async_set(
        "light.wz", "on", {"supported_color_modes": ["hs"], "brightness": 180}
    )
    hass.states.async_set("input_boolean.z", "off")
    await hass.async_block_till_done()

    panel_entity = next(
        eid
        for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id")
    )
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": panel_entity},
        blocking=True,
    )
    await hass.async_block_till_done()
    hass.states.async_set("input_boolean.z", "on")
    await hass.async_block_till_done()
    assert hass.states.get(panel_entity).state == "triggered"

    # "Downtime": unload (engine cancelled, persistence kept), deadline passes.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await asyncio.sleep(0.4)
    # The light is mid-flash alarm red at the moment of the "restart".
    hass.states.async_set(
        "light.wz",
        "on",
        {"supported_color_modes": ["hs"], "brightness": 255, "hs_color": [0.0, 100.0]},
    )
    turn_on.clear()

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()

    panel_entity = next(
        eid
        for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id")
    )
    # trigger_time expired while down: panel rearmed, effects ended.
    assert hass.states.get(panel_entity).state == "armed_away"
    # Restore wrote the ORIGINAL brightness, never the alarm red.
    restore_calls = [c for c in turn_on if "rgb_color" not in c.data]
    assert restore_calls and restore_calls[-1].data["brightness"] == 180
    assert not any(c.data.get("rgb_color") == [255, 0, 0] for c in turn_on)
    # No zombie instance, no leftover snapshot.
    hub = entry.runtime_data.hub
    assert not hub.engine.has_instances(panel["id"])
    assert hass_storage[STORAGE_KEY_SNAPSHOTS]["data"] == {}

"""Sensor types: tilt classification, tilted-arming policy, vibration filter."""
import asyncio

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kustos.const import DOMAIN

MODES = {"armed_away": {"enabled": True, "exit_delay_s": 0.0,
                        "entry_delay_s": 0.0, "trigger_time_s": 0.0}}


async def _setup(hass, zone_extra):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    panel = await storage.panels.async_create_item(
        {"scope": {"type": "custom", "name": "Test"}, "modes": MODES}
    )
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    await storage.zones.async_create_item(
        {"entity_id": "sensor.fenster", "panel_id": panel["id"],
         "modes": {"armed_away": "instant"}, **zone_extra}
    )
    await hass.async_block_till_done()
    return entry


def _panel(hass):
    return next(
        eid for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id"))


async def _arm(hass, panel):
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": panel}, blocking=True)
    await hass.async_block_till_done()


async def test_tilt_thresholds_and_tilted_arming_allowed(hass):
    await _setup(hass, {
        "sensor_type": "tilt",
        "evaluation": {"tilt_min": 10, "open_min": 60, "arm_allowed_when_tilted": True},
    })
    panel = _panel(hass)
    hass.states.async_set("sensor.fenster", "15")  # gekippt
    await hass.async_block_till_done()
    await _arm(hass, panel)
    assert hass.states.get(panel).state == "armed_away", "gekippt darf scharf"

    hass.states.async_set("sensor.fenster", "75")  # ganz geoeffnet
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "triggered", "voll geoeffnet loest aus"
    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": panel}, blocking=True)
    await hass.async_block_till_done()

    # Gekippt -> noch weiter gekippt loest nicht aus.
    hass.states.async_set("sensor.fenster", "12")
    await _arm(hass, panel)
    hass.states.async_set("sensor.fenster", "20")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away"


async def test_tilted_blocks_arming_when_configured(hass):
    await _setup(hass, {
        "sensor_type": "tilt",
        "evaluation": {"tilt_min": 10, "open_min": 60, "arm_allowed_when_tilted": False},
    })
    panel = _panel(hass)
    hass.states.async_set("sensor.fenster", "15")
    await hass.async_block_till_done()
    await _arm(hass, panel)
    assert hass.states.get(panel).state == "disarmed", "gekippt blockiert hier"


async def test_vibration_needs_n_trips_in_window(hass):
    await _setup(hass, {
        "sensor_type": "vibration",
        "entity_id": "binary_sensor.ruettler",
        "evaluation": {"trip_count": 3, "trip_window_s": 5.0},
    })
    # zone_extra ueberschreibt entity_id oben; Zustand initialisieren:
    hass.states.async_set("binary_sensor.ruettler", "off")
    await hass.async_block_till_done()
    panel = _panel(hass)
    await _arm(hass, panel)
    for n in range(2):
        hass.states.async_set("binary_sensor.ruettler", "on")
        await hass.async_block_till_done()
        hass.states.async_set("binary_sensor.ruettler", "off")
        await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away", "zwei Impulse reichen nicht"
    hass.states.async_set("binary_sensor.ruettler", "on")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "triggered", "dritter Impuls im Fenster"

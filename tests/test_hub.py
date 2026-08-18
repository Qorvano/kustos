"""Integration tests: hub, entities, timers and restart restore."""
from datetime import timedelta

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.kustos.const import DOMAIN

DOOR = "binary_sensor.haustuer"
WINDOW = "binary_sensor.fenster"


async def _setup_with_panel(hass):
    """Set up the hub entry plus one area panel with a door and a window zone."""
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set(DOOR, "off")
    hass.states.async_set(WINDOW, "off")

    storage = entry.runtime_data.storage
    panel = await storage.panels.async_create_item(
        {
            "scope": {"type": "area", "area_id": "erdgeschoss"},
            "modes": {
                "armed_away": {
                    "enabled": True,
                    "exit_delay_s": 0.0,
                    "entry_delay_s": 30.0,
                    "trigger_time_s": 0.0,
                }
            },
        }
    )
    await hass.async_block_till_done()  # panel change reloads the entry

    storage = entry.runtime_data.storage  # fresh after reload
    await storage.zones.async_create_item(
        {
            "entity_id": DOOR,
            "panel_id": panel["id"],
            "modes": {"armed_away": "delayed"},
        }
    )
    await storage.zones.async_create_item(
        {
            "entity_id": WINDOW,
            "panel_id": panel["id"],
            "modes": {"armed_away": "instant"},
        }
    )
    await hass.async_block_till_done()
    return entry, panel["id"]


def _panel_entity(hass):
    entities = [
        eid
        for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id")
    ]
    assert len(entities) == 1
    return entities[0]


def _master_entity(hass):
    entities = [
        eid
        for eid in hass.states.async_entity_ids("alarm_control_panel")
        if not hass.states.get(eid).attributes.get("panel_id")
    ]
    assert len(entities) == 1
    return entities[0]


async def _arm_away(hass, entity_id):
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {"entity_id": entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_entities_are_created(hass):
    await _setup_with_panel(hass)
    assert _panel_entity(hass)
    assert hass.states.get(_master_entity(hass)).state == "disarmed"


async def test_arm_trip_pending_trigger_flow(hass):
    entry, _panel_id = await _setup_with_panel(hass)
    panel = _panel_entity(hass)

    await _arm_away(hass, panel)
    assert hass.states.get(panel).state == "armed_away"
    assert hass.states.get(_master_entity(hass)).state == "armed_away"

    # Door opens: entry delay starts.
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    state = hass.states.get(panel)
    assert state.state == "pending"
    assert state.attributes["ends_at"] is not None

    # Entry delay runs out: alarm.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    state = hass.states.get(panel)
    assert state.state == "triggered"
    assert state.attributes["alarm_memory"][0]["entity_id"] == DOOR
    assert hass.states.get(_master_entity(hass)).state == "triggered"


async def test_instant_zone_triggers_without_delay(hass):
    await _setup_with_panel(hass)
    panel = _panel_entity(hass)
    await _arm_away(hass, panel)

    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "triggered"


async def test_disarm_restores_and_open_zone_blocks_arming(hass):
    await _setup_with_panel(hass)
    panel = _panel_entity(hass)

    # Open window blocks arming (it is instant, not bypassable).
    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    await _arm_away(hass, panel)
    assert hass.states.get(panel).state == "disarmed"

    # Ready sensor mirrors the blocker.
    ready = [
        eid
        for eid in hass.states.async_entity_ids("binary_sensor")
        if "blocking_zones" in hass.states.get(eid).attributes
    ]
    assert len(ready) == 1
    assert hass.states.get(ready[0]).state == "off"

    hass.states.async_set(WINDOW, "off")
    await hass.async_block_till_done()
    assert hass.states.get(ready[0]).state == "on"
    await _arm_away(hass, panel)
    assert hass.states.get(panel).state == "armed_away"

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_disarm",
        {"entity_id": panel},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "disarmed"


async def test_reload_mid_pending_restores_and_catches_up(hass):
    """The M1 core promise: a running entry delay survives a restart."""
    entry, _ = await _setup_with_panel(hass)
    panel = _panel_entity(hass)
    await _arm_away(hass, panel)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "pending"
    ends_at = hass.states.get(panel).attributes["ends_at"]

    # Simulated restart: unload and set up again; runtime store persists.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    panel = _panel_entity(hass)
    state = hass.states.get(panel)
    assert state.state == "pending"
    assert state.attributes["ends_at"] == ends_at  # same absolute deadline

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "triggered"


async def test_acknowledge_service_clears_memory(hass):
    await _setup_with_panel(hass)
    panel = _panel_entity(hass)
    await _arm_away(hass, panel)
    hass.states.async_set(WINDOW, "on")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "triggered"

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_disarm",
        {"entity_id": panel},
        blocking=True,
    )
    await hass.async_block_till_done()
    # Memory survives the disarm until acknowledged (require_explicit_ack).
    assert hass.states.get(panel).attributes["alarm_memory"]

    await hass.services.async_call(
        DOMAIN, "acknowledge", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(panel).attributes["alarm_memory"] == []

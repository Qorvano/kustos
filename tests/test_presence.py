"""M5: presence state machine, away hysteresis, auto-arm/disarm rules."""
import asyncio

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kustos.const import DOMAIN

TRACKER = "device_tracker.dustin_iphone"
DIST = "sensor.dustin_entfernung"


async def _setup(hass, prewarn_s=0.0, min_away_s=None):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    if min_away_s is not None:
        settings = dict(storage.settings)
        settings["presence"] = {**settings["presence"], "min_away_duration_s": min_away_s}
        await storage.async_save_settings(settings)
    panel = await storage.panels.async_create_item(
        {
            "scope": {"type": "area", "area_id": "haus"},
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
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    person = await storage.persons.async_create_item(
        {
            "name": "Dustin",
            "tracker_entity": TRACKER,
            "distance_entity": DIST,
            "away_confirm_distance_m": 500.0,
        }
    )
    rule = await storage.rules.async_create_item(
        {
            "name": "Auto",
            "panel_id": panel["id"],
            "arm": {"mode": "armed_away", "execution": "prewarn", "prewarn_s": prewarn_s},
        }
    )
    await hass.async_block_till_done()
    return entry, panel["id"], person["id"], rule["id"]


def _panel_entity(hass):
    return next(
        eid
        for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id")
    )


async def _set(hass, entity, state, attrs=None):
    hass.states.async_set(entity, state, attrs or {})
    await hass.async_block_till_done()


async def test_away_hysteresis_and_auto_arm_and_return_disarm(hass):
    entry, panel_id, person_id, _ = await _setup(hass)
    panel = _panel_entity(hass)
    await _set(hass, TRACKER, "home")
    await _set(hass, DIST, "0", {"unit_of_measurement": "m"})
    assert hass.states.get(panel).state == "disarmed"

    # Leaving, but under the distance threshold: nothing arms.
    await _set(hass, TRACKER, "not_home")
    await _set(hass, DIST, "120", {"unit_of_measurement": "m"})
    assert hass.states.get(panel).state == "disarmed"

    # Past 500 m: confirmed away, rule arms (prewarn 0 = immediately).
    await _set(hass, DIST, "0.6", {"unit_of_measurement": "km"})
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away"

    # Return: below half the threshold -> returning; home -> arrived -> disarm.
    await _set(hass, DIST, "200", {"unit_of_measurement": "m"})
    await _set(hass, TRACKER, "home")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "disarmed"


async def test_garden_walk_never_disarms(hass):
    """Not-home flap without ever confirming away must not disarm on return."""
    entry, panel_id, _, _ = await _setup(hass)
    panel = _panel_entity(hass)
    await _set(hass, TRACKER, "home")
    await _set(hass, DIST, "0", {"unit_of_measurement": "m"})

    # Arm manually (e.g. for the night).
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()

    # WLAN flap: not_home for a moment, 60 m into the garden, back home.
    await _set(hass, TRACKER, "not_home")
    await _set(hass, DIST, "60", {"unit_of_measurement": "m"})
    await _set(hass, TRACKER, "home")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away", (
        "return without a confirmed trip must never disarm"
    )


async def test_untracked_person_blocks_auto_arm(hass):
    entry, panel_id, _, _ = await _setup(hass)
    panel = _panel_entity(hass)
    await _set(hass, TRACKER, "not_home")
    await _set(hass, DIST, "9999", {"unit_of_measurement": "m"})
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away"
    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()

    # Tracker dies: person untracked; a fresh trip cannot confirm.
    await _set(hass, TRACKER, "unavailable")
    await _set(hass, DIST, "10000", {"unit_of_measurement": "m"})
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "disarmed", (
        "unavailable must never count as away"
    )


async def test_auto_disarm_blocked_during_pending(hass):
    """Critique finding 2: an entry delay must not be swallowed by an
    approaching resident."""
    entry, panel_id, _, _ = await _setup(hass)
    storage = entry.runtime_data.storage
    await storage.zones.async_create_item(
        {
            "entity_id": "input_boolean.haustuer",
            "panel_id": panel_id,
            "modes": {"armed_away": "delayed"},
        }
    )
    await hass.async_block_till_done()
    panel = _panel_entity(hass)
    hass.states.async_set("input_boolean.haustuer", "off")
    await _set(hass, TRACKER, "not_home")
    await _set(hass, DIST, "800", {"unit_of_measurement": "m"})
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away"

    # Burglar opens the door: pending. The resident happens to come home.
    hass.states.async_set("input_boolean.haustuer", "on")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "pending"
    await _set(hass, DIST, "100", {"unit_of_measurement": "m"})
    await _set(hass, TRACKER, "home")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "pending", (
        "auto-disarm must stay blocked while pending"
    )


async def test_manual_disarm_suppresses_rearm_for_same_trip(hass):
    entry, panel_id, _, _ = await _setup(hass)
    panel = _panel_entity(hass)
    await _set(hass, TRACKER, "not_home")
    await _set(hass, DIST, "700", {"unit_of_measurement": "m"})
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away"

    # Neighbor with key disarms manually while everyone is still away.
    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()
    # Distance changes again: same trip, must NOT re-arm.
    await _set(hass, DIST, "900", {"unit_of_measurement": "m"})
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "disarmed"

    # New trip (home and away again) re-enables the rule.
    await _set(hass, TRACKER, "home")
    await _set(hass, DIST, "0", {"unit_of_measurement": "m"})
    await _set(hass, TRACKER, "not_home")
    await _set(hass, DIST, "800", {"unit_of_measurement": "m"})
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away"


async def test_time_based_confirmation_without_distance_source(hass):
    entry, panel_id, person_id, _ = await _setup(hass, min_away_s=0.2)
    storage = entry.runtime_data.storage
    await storage.persons.async_update_item(person_id, {"distance_entity": None})
    await hass.async_block_till_done()
    panel = _panel_entity(hass)
    await _set(hass, TRACKER, "not_home")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "disarmed", "not before min_away_duration"
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "armed_away"

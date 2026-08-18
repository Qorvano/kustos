"""M4: audit log, walk test, unavailable policy."""
import asyncio

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kustos.const import DOMAIN


async def _setup(hass, unavailable_policy="ignore"):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    panel = await storage.panels.async_create_item(
        {
            "scope": {"type": "area", "area_id": "eg"},
            "modes": {
                "armed_away": {
                    "enabled": True,
                    "exit_delay_s": 0.0,
                    "entry_delay_s": 0.0,
                    "trigger_time_s": 0.0,
                }
            },
        }
    )
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    await storage.zones.async_create_item(
        {
            "entity_id": "input_boolean.tuer",
            "panel_id": panel["id"],
            "modes": {"armed_away": "instant"},
            "options": {"unavailable_policy": unavailable_policy},
        }
    )
    await hass.async_block_till_done()
    return entry, panel["id"]


def _panel_entity(hass):
    return next(
        eid
        for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id")
    )


async def _arm(hass, panel):
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()


async def test_audit_log_records_and_queries(hass, hass_ws_client):
    entry, _ = await _setup(hass)
    hass.states.async_set("input_boolean.tuer", "off")
    panel = _panel_entity(hass)
    await _arm(hass, panel)
    hass.states.async_set("input_boolean.tuer", "on")
    await hass.async_block_till_done()
    await asyncio.sleep(0.05)
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/audit/query"})
    resp = await client.receive_json()
    assert resp["success"]
    kinds = [e["kind"] for e in resp["result"]["entries"]]
    assert "armed" in kinds and "triggered" in kinds
    # Newest first.
    assert kinds.index("triggered") < kinds.index("armed")

    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()


async def test_walk_test_suppresses_alarm_and_records_zone(hass, hass_ws_client):
    entry, panel_id = await _setup(hass)
    hass.states.async_set("input_boolean.tuer", "off")
    panel = _panel_entity(hass)
    await _arm(hass, panel)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/walk_test", "panel_id": panel_id, "action": "start"}
    )
    resp = await client.receive_json()
    assert resp["success"] and resp["result"]["active"]

    events = []
    hass.bus.async_listen(f"{DOMAIN}_walk_test_zone", lambda e: events.append(e))
    hass.states.async_set("input_boolean.tuer", "on")
    await hass.async_block_till_done()

    # Armed, tripped, but NOT triggered - and the trip is recorded.
    assert hass.states.get(panel).state == "armed_away"
    assert events and events[0].data["entity_id"] == "input_boolean.tuer"

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/walk_test", "panel_id": panel_id, "action": "stop"}
    )
    resp = await client.receive_json()
    assert resp["success"] and not resp["result"]["active"]

    # After the walk test, trips are real again (fresh edge required).
    hass.states.async_set("input_boolean.tuer", "off")
    await hass.async_block_till_done()
    hass.states.async_set("input_boolean.tuer", "on")
    await hass.async_block_till_done()
    assert hass.states.get(panel).state == "triggered"
    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()


async def test_unavailable_zone_blocks_arm_when_policy_says_so(hass):
    entry, _ = await _setup(hass, unavailable_policy="block_arm")
    # Zone entity never gets a state: unavailable from Kustos' point of view.
    panel = _panel_entity(hass)
    await _arm(hass, panel)
    assert hass.states.get(panel).state == "disarmed", "dead sensor must block"

    ready = next(
        eid
        for eid in hass.states.async_entity_ids("binary_sensor")
        if "blocking_zones" in hass.states.get(eid).attributes
    )
    assert hass.states.get(ready).state == "off"


async def test_unavailable_zone_auto_bypass_policy_arms_visibly(hass):
    entry, _ = await _setup(hass, unavailable_policy="auto_bypass")
    panel = _panel_entity(hass)
    await _arm(hass, panel)
    state = hass.states.get(panel)
    assert state.state == "armed_away"
    assert state.attributes["bypassed_zones"], "bypass must be visible"
    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()

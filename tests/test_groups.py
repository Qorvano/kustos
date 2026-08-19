"""Custom panels and panel groups: union semantics throughout."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kustos.const import DOMAIN

MODES = {
    "armed_away": {
        "enabled": True, "exit_delay_s": 0.0, "entry_delay_s": 0.0, "trigger_time_s": 0.0,
    }
}


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    p1 = await storage.panels.async_create_item(
        {"scope": {"type": "area", "area_id": "erdgeschoss"}, "modes": MODES}
    )
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    p2 = await storage.panels.async_create_item(
        {"scope": {"type": "custom", "name": "Gartenhaus"}, "modes": MODES}
    )
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    group = await storage.groups.async_create_item(
        {"name": "Unten", "panel_ids": [p1["id"], p2["id"]]}
    )
    await hass.async_block_till_done()
    # Shared zone: the same window belongs to BOTH panels (overlap).
    storage = entry.runtime_data.storage
    for pid in (p1["id"], p2["id"]):
        await storage.zones.async_create_item(
            {"entity_id": "input_boolean.fenster", "panel_id": pid,
             "modes": {"armed_away": "instant"}}
        )
    await hass.async_block_till_done()
    hass.states.async_set("input_boolean.fenster", "off")
    await hass.async_block_till_done()
    return entry, p1["id"], p2["id"], group["id"]


def _entity(hass, attr, value):
    return next(
        eid for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get(attr) == value
    )


async def test_custom_panel_gets_named_entity(hass):
    await _setup(hass)
    assert hass.states.get("alarm_control_panel.kustos_gartenhaus") is not None


async def test_group_arm_cascades_and_aggregates(hass):
    entry, p1, p2, gid = await _setup(hass)
    group_entity = _entity(hass, "group_id", gid)
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": group_entity}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(_entity(hass, "panel_id", p1)).state == "armed_away"
    assert hass.states.get(_entity(hass, "panel_id", p2)).state == "armed_away"
    assert hass.states.get(group_entity).state == "armed_away"

    # Shared zone trips: both members trigger, the group shows the union.
    hass.states.async_set("input_boolean.fenster", "on")
    await hass.async_block_till_done()
    assert hass.states.get(group_entity).state == "triggered"

    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": group_entity}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(group_entity).state == "disarmed"
    assert hass.states.get(_entity(hass, "panel_id", p1)).state == "disarmed"


async def test_group_arm_blocks_on_any_open_zone_nothing_arms_halfway(hass):
    """User requirement: bei Überschneidungen zählt die Gesamtheit."""
    entry, p1, p2, gid = await _setup(hass)
    hass.states.async_set("input_boolean.fenster", "on")  # open somewhere
    await hass.async_block_till_done()
    group_entity = _entity(hass, "group_id", gid)
    await hass.services.async_call(
        "alarm_control_panel", "alarm_arm_away", {"entity_id": group_entity}, blocking=True
    )
    await hass.async_block_till_done()
    # Nothing armed, not even partially.
    assert hass.states.get(_entity(hass, "panel_id", p1)).state == "disarmed"
    assert hass.states.get(_entity(hass, "panel_id", p2)).state == "disarmed"
    assert hass.states.get(group_entity).state == "disarmed"

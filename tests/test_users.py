"""M3: users, PIN hashing, code enforcement, rights, duress."""
import asyncio

import pytest

from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.kustos.const import DOMAIN
from custom_components.kustos.core.auth import hash_pin, needs_rehash, verify_pin


def test_pin_hash_roundtrip():
    record = hash_pin("1234")
    assert verify_pin("1234", record)
    assert not verify_pin("4321", record)
    assert not needs_rehash(record)
    # Salted: two hashes of the same PIN differ.
    assert hash_pin("1234")["hash"] != record["hash"]


async def _setup(hass, holdup_profile=False):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage

    alarm_types = {}
    if holdup_profile:
        profile = await storage.profiles.async_create_item(
            {
                "name": "Still",
                "stages": [
                    {
                        "duration_s": None,
                        "blocks": [
                            {
                                "type": "notify",
                                "service": "notify.zweitperson",
                                "message": "Stiller Alarm",
                            }
                        ],
                    }
                ],
            }
        )
        alarm_types = {"holdup": {"profile_id": profile["id"]}}

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
            "alarm_types": alarm_types,
        }
    )
    await hass.async_block_till_done()
    return entry, panel["id"]


async def _add_user(entry, name="Dustin", pin="1234", duress=None, rights=None):
    storage = entry.runtime_data.storage
    user = await storage.users.async_create_item(
        {"name": name, "rights": rights or {}}
    )
    storage.pins[user["id"]] = {"normal": hash_pin(pin)}
    if duress:
        storage.pins[user["id"]]["duress"] = hash_pin(duress)
    await storage.async_save_pins()
    return user


def _panel_entity(hass):
    return next(
        eid
        for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id")
    )


async def _svc(hass, service, entity_id, code=None, expect_error=None):
    data = {"entity_id": entity_id}
    if code is not None:
        data["code"] = code
    if expect_error:
        with pytest.raises(HomeAssistantError, match=expect_error):
            await hass.services.async_call(
                "alarm_control_panel", service, data, blocking=True
            )
    else:
        await hass.services.async_call(
            "alarm_control_panel", service, data, blocking=True
        )
    await hass.async_block_till_done()


async def test_no_users_means_no_lockout(hass):
    entry, _ = await _setup(hass)
    panel = _panel_entity(hass)
    await _svc(hass, "alarm_arm_away", panel)
    assert hass.states.get(panel).state == "armed_away"
    # code_disarm_required is on by default, but without any PIN user the
    # owner must not be locked out.
    await _svc(hass, "alarm_disarm", panel)
    assert hass.states.get(panel).state == "disarmed"


async def test_disarm_requires_valid_code(hass):
    entry, _ = await _setup(hass)
    await _add_user(entry)
    panel = _panel_entity(hass)
    await _svc(hass, "alarm_arm_away", panel)
    assert hass.states.get(panel).state == "armed_away"

    await _svc(hass, "alarm_disarm", panel, expect_error="Code erforderlich")
    assert hass.states.get(panel).state == "armed_away"
    await _svc(hass, "alarm_disarm", panel, code="9999", expect_error="Ungültiger Code")
    assert hass.states.get(panel).state == "armed_away"
    await _svc(hass, "alarm_disarm", panel, code="1234")
    assert hass.states.get(panel).state == "disarmed"


async def test_code_format_is_state_dependent(hass):
    entry, _ = await _setup(hass)
    await _add_user(entry)
    panel = _panel_entity(hass)
    # Disarmed: next action is arm; arming needs no code by default.
    state = hass.states.get(panel)
    assert state.attributes.get("code_format") is None
    await _svc(hass, "alarm_arm_away", panel)
    state = hass.states.get(panel)
    assert state.attributes.get("code_format") == "number"
    await _svc(hass, "alarm_disarm", panel, code="1234")


async def test_rights_are_enforced(hass):
    entry, _ = await _setup(hass)
    await _add_user(
        entry, name="Gast", pin="5555", rights={"can_disarm": False}
    )
    panel = _panel_entity(hass)
    await _svc(hass, "alarm_arm_away", panel)
    await _svc(
        hass, "alarm_disarm", panel, code="5555", expect_error="nicht erlaubt"
    )
    assert hass.states.get(panel).state == "armed_away"


async def test_duress_disarms_normally_but_starts_silent_holdup(hass):
    entry, panel_id = await _setup(hass, holdup_profile=True)
    await _add_user(entry, pin="1234", duress="9111")
    notify = async_mock_service(hass, "notify", "zweitperson")
    panel = _panel_entity(hass)
    await _svc(hass, "alarm_arm_away", panel)

    await _svc(hass, "alarm_disarm", panel, code="9111")
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    # Outwardly a completely normal disarm.
    state = hass.states.get(panel)
    assert state.state == "disarmed"
    assert state.attributes["active_alarm_types"] == []
    assert state.attributes["alarm_memory"] == []
    # But the silent chain runs, detached from the FSM.
    assert notify, "duress must notify the second person"
    hub = entry.runtime_data.hub
    assert not hub.engine.has_instances(panel_id)  # invisible to normal checks

    # Acknowledge (the admin act) ends the silent instance.
    await hass.services.async_call(
        DOMAIN, "acknowledge", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()
    records = hub.engine._records()
    assert not any(r["panel_id"] == panel_id for r in records.values())


async def test_users_ws_list_never_exposes_pins(hass, hass_ws_client):
    entry, _ = await _setup(hass)
    await _add_user(entry)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": f"{DOMAIN}/users/list"})
    resp = await client.receive_json()
    assert resp["success"]
    dump = str(resp["result"])
    assert "pin" not in dump and "hash" not in dump and "salt" not in dump


async def test_set_pin_ws_validates_and_stores_hash_only(hass, hass_ws_client):
    entry, _ = await _setup(hass)
    storage = entry.runtime_data.storage
    user = await storage.users.async_create_item({"name": "Petra"})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/users/set_pin", "user_id": user["id"], "pin": "12"}
    )
    resp = await client.receive_json()
    assert not resp["success"], "too-short PIN must be rejected"

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/users/set_pin", "user_id": user["id"], "pin": "246810"}
    )
    resp = await client.receive_json()
    assert resp["success"]
    record = storage.pins[user["id"]]["normal"]
    assert "246810" not in str(record)
    assert verify_pin("246810", record)

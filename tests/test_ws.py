"""Tests for the WebSocket API (admin-only CRUD, settings, runtime state)."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kustos.const import DOMAIN


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_panel_zone_crud_via_ws(hass, hass_ws_client):
    await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/panels/create",
            "scope": {"type": "area", "area_id": "erdgeschoss"},
            "modes": {"armed_away": {"enabled": True, "exit_delay_s": 0.0}},
        }
    )
    resp = await client.receive_json()
    assert resp["success"], resp
    panel_id = resp["result"]["id"]
    await hass.async_block_till_done()  # panel creation reloads the entry

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/zones/create",
            "entity_id": "binary_sensor.haustuer",
            "panel_id": panel_id,
            "modes": {"armed_away": "delayed"},
        }
    )
    resp = await client.receive_json()
    assert resp["success"], resp
    zone_id = resp["result"]["id"]

    await client.send_json_auto_id({"type": f"{DOMAIN}/zones/list"})
    resp = await client.receive_json()
    assert [z["id"] for z in resp["result"]] == [zone_id]

    # Partial update must not reset sibling fields.
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/zones/update",
            "zone_id": zone_id,
            "name": "Haustuer",
        }
    )
    resp = await client.receive_json()
    assert resp["success"], resp
    assert resp["result"]["entity_id"] == "binary_sensor.haustuer"
    assert resp["result"]["modes"] == {"armed_away": "delayed"}
    assert resp["result"]["name"] == "Haustuer"

    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/zones/delete", "zone_id": zone_id}
    )
    resp = await client.receive_json()
    assert resp["success"], resp


async def test_zone_create_rejects_bad_entity_id(hass, hass_ws_client):
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/zones/create",
            "entity_id": "kein-entity",
            "panel_id": "P1",
        }
    )
    resp = await client.receive_json()
    assert not resp["success"]


async def test_settings_get_and_partial_update(hass, hass_ws_client):
    await _setup(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": f"{DOMAIN}/settings/get"})
    resp = await client.receive_json()
    assert resp["result"]["defaults"]["exit_delay_s"] == 60.0

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/settings/update",
            "settings": {"defaults": {"exit_delay_s": 90.0}},
        }
    )
    resp = await client.receive_json()
    assert resp["success"], resp
    assert resp["result"]["defaults"]["exit_delay_s"] == 90.0
    # Untouched keys survive the partial update.
    assert resp["result"]["defaults"]["entry_delay_s"] == 30.0

    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/settings/update",
            "settings": {"defaults": {"exit_delay_s": -5}},
        }
    )
    resp = await client.receive_json()
    assert not resp["success"]
    assert resp["error"]["code"] == "invalid_format"


async def test_state_list_reports_panels_and_master(hass, hass_ws_client):
    await _setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"{DOMAIN}/panels/create",
            "scope": {"type": "area", "area_id": "erdgeschoss"},
            "modes": {"armed_away": {"enabled": True, "exit_delay_s": 0.0}},
        }
    )
    resp = await client.receive_json()
    assert resp["success"], resp
    await hass.async_block_till_done()

    await client.send_json_auto_id({"type": f"{DOMAIN}/state/list"})
    resp = await client.receive_json()
    assert resp["success"], resp
    assert len(resp["result"]["panels"]) == 1
    assert resp["result"]["panels"][0]["state"] == "disarmed"
    assert resp["result"]["master"]["state"] == "disarmed"


async def test_crud_requires_admin(hass, hass_ws_client, hass_read_only_access_token):
    await _setup(hass)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    await client.send_json_auto_id({"type": f"{DOMAIN}/panels/list"})
    resp = await client.receive_json()
    assert not resp["success"]
    assert resp["error"]["code"] == "unauthorized"

"""M6 preparation: Alarmo import against a synthetic storage blob."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kustos.const import DOMAIN

ALARMO_DATA = {
    "areas": [
        {
            "area_id": "a1",
            "name": "Erdgeschoss",
            "modes": {
                "armed_away": {"enabled": True, "exit_time": 60, "entry_time": 30, "trigger_time": 180},
                "armed_night": {"enabled": True, "exit_time": 0, "entry_time": 15},
                "armed_vacation": {"enabled": False},
            },
        }
    ],
    "sensors": [
        {
            "entity_id": "binary_sensor.haustuer",
            "area": "a1",
            "type": "door",
            "modes": ["armed_away", "armed_night"],
            "use_entry_delay": True,
            "use_exit_delay": True,
            "arm_on_close": True,
        },
        {
            "entity_id": "binary_sensor.fenster_kueche",
            "area": "a1",
            "type": "window",
            "modes": ["armed_away"],
            "auto_bypass": True,
        },
        {
            "entity_id": "binary_sensor.rauch_diele",
            "area": "a1",
            "type": "environmental",
            "modes": [],
            "always_on": True,
        },
        {
            "entity_id": "binary_sensor.verwaist",
            "area": "unbekannt",
            "type": "door",
            "modes": ["armed_away"],
        },
    ],
    "users": [
        {"name": "Dustin", "enabled": True, "can_arm": True, "can_disarm": True, "code": "$2b$..."},
        {"name": "Gast", "enabled": True, "can_arm": True, "can_disarm": False},
    ],
    "automations": [{"id": "x"}],
}


async def test_alarmo_import_maps_areas_sensors_users(hass, hass_ws_client):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Smoke sensor exists with a device_class the importer can use.
    hass.states.async_set(
        "binary_sensor.rauch_diele", "off", {"device_class": "smoke"}
    )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": f"{DOMAIN}/import/alarmo", "data": ALARMO_DATA}
    )
    resp = await client.receive_json()
    assert resp["success"], resp
    result = resp["result"]
    assert result["counts"] == {"panels": 1, "zones": 3, "users": 2}
    await hass.async_block_till_done()

    storage = entry.runtime_data.storage
    panel = storage.panels.async_items()[0]
    assert panel["modes"]["armed_away"]["exit_delay_s"] == 60.0
    assert panel["modes"]["armed_away"]["trigger_time_s"] == 180.0
    assert panel["modes"]["armed_night"]["entry_delay_s"] == 15.0
    assert panel["modes"]["armed_vacation"]["enabled"] is False

    zones = {z["entity_id"]: z for z in storage.zones.async_items()}
    door = zones["binary_sensor.haustuer"]
    assert door["modes"]["armed_away"] == "delayed"
    assert door["modes"]["armed_night"] == "delayed"
    assert door["options"]["use_exit_delay"] is True
    assert door["options"]["arm_after_closing"] is True
    window = zones["binary_sensor.fenster_kueche"]
    assert window["modes"]["armed_away"] == "instant"
    assert window["options"]["auto_bypass"] is True
    smoke = zones["binary_sensor.rauch_diele"]
    assert smoke["alarm_type"] == "fire"  # 24/7 via alarm type
    assert "binary_sensor.verwaist" not in zones

    users = {u["name"]: u for u in storage.users.async_items()}
    assert users["Gast"]["rights"]["can_disarm"] is False
    # No PIN material was imported.
    assert storage.pins == {}

    joined = " ".join(result["report"])
    assert "PIN nicht übernommen" in joined
    assert "Automationen NICHT importiert" in joined
    assert "übersprungen" in joined

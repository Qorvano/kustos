"""Integration tests: the hub entry loads, seeds settings, persists stores."""
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kustos.const import DOMAIN, STORAGE_KEY_SETTINGS


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_seeds_settings(hass, hass_storage):
    entry = await _setup(hass)
    storage = entry.runtime_data.storage
    assert storage.setting("defaults", "exit_delay_s") == 60.0
    # The merged settings document is persisted so it is visible and editable.
    assert hass_storage[STORAGE_KEY_SETTINGS]["data"]["defaults"]["entry_delay_s"] == 30.0


async def test_setup_respects_stored_settings(hass, hass_storage):
    hass_storage[STORAGE_KEY_SETTINGS] = {
        "version": 1,
        "key": STORAGE_KEY_SETTINGS,
        "data": {"defaults": {"exit_delay_s": 120.0}},
    }
    entry = await _setup(hass)
    storage = entry.runtime_data.storage
    assert storage.setting("defaults", "exit_delay_s") == 120.0
    # New keys appear despite the partial stored document.
    assert storage.setting("security", "require_explicit_ack") is True


async def test_panel_and_zone_crud_round_trip(hass, hass_storage):
    entry = await _setup(hass)
    storage = entry.runtime_data.storage

    panel = await storage.panels.async_create_item(
        {"scope": {"type": "area", "area_id": "wohnzimmer"}}
    )
    # ULIDs are 26 chars and collision-free.
    assert len(panel["id"]) == 26

    zone = await storage.zones.async_create_item(
        {
            "entity_id": "binary_sensor.haustuer",
            "panel_id": panel["id"],
            "modes": {"armed_away": "delayed"},
        }
    )
    updated = await storage.zones.async_update_item(
        zone["id"], {"modes": {"armed_away": "instant"}}
    )
    assert updated["id"] == zone["id"]
    # Update kept the unrelated fields intact.
    assert updated["entity_id"] == "binary_sensor.haustuer"

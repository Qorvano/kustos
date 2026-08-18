"""The sidebar panel is registered on setup."""
from homeassistant.components.frontend import DATA_PANELS
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kustos.const import DOMAIN


async def test_sidebar_panel_registered(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    panel = hass.data[DATA_PANELS][DOMAIN]
    assert panel.config["_panel_custom"]["name"] == "kustos-panel"
    assert panel.require_admin is True

"""Kustos: alarm system integration bound to Home Assistant areas."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from . import api
from .const import DOMAIN
from .core.hub import KustosHub
from .storage import KustosStorage

type KustosConfigEntry = ConfigEntry[KustosData]


@dataclass
class KustosData:
    """Runtime objects attached to the single hub config entry."""

    storage: KustosStorage
    hub: KustosHub


PLATFORMS: list[Platform] = [Platform.ALARM_CONTROL_PANEL, Platform.BINARY_SENSOR]


async def _async_get_storage(hass: HomeAssistant) -> KustosStorage:
    """Storage survives entry reloads: collections keep their delayed saves.

    A reload (triggered e.g. by panel add/remove) only rebuilds hub and
    entities; recreating the stores would race their debounced writes.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "storage" not in domain_data:
        storage = KustosStorage(hass)
        await storage.async_load()
        domain_data["storage"] = storage

        async def _panels_changed(
            change_type: str, item_id: str, config: dict[str, Any]
        ) -> None:
            # Panel add/remove means entities appear/disappear: reload.
            for entry in hass.config_entries.async_entries(DOMAIN):
                hass.config_entries.async_schedule_reload(entry.entry_id)

        storage.panels.async_add_listener(_panels_changed)
        api.async_register(hass, storage)
    return domain_data["storage"]


async def async_setup_entry(hass: HomeAssistant, entry: KustosConfigEntry) -> bool:
    storage = await _async_get_storage(hass)
    hub = KustosHub(hass, storage)
    await hub.async_start()
    entry.runtime_data = KustosData(storage=storage, hub=hub)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KustosConfigEntry) -> bool:
    await entry.runtime_data.hub.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

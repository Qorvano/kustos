"""Storage layer: one Store per concern plus dict collections for CRUD.

Deliberately not a single monolithic blob (Alarmo's weak spot): each store is
individually versioned and migratable. Runtime state lives in its own store so
configuration and volatile state never mix.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import collection
from homeassistant.helpers.storage import Store
from homeassistant.util import ulid as ulid_util

from .const import (
    STORAGE_KEY_PANELS,
    STORAGE_KEY_RUNTIME,
    STORAGE_KEY_SETTINGS,
    STORAGE_KEY_ZONES,
    STORAGE_VERSION,
)
from .schemas import (
    DEFAULT_SETTINGS,
    PANEL_FIELDS,
    SETTINGS_SCHEMA,
    ZONE_FIELDS,
    merge_defaults,
)


class _UlidCollection(collection.DictStorageCollection):
    """Dict collection with ULID ids and schema validation on every write."""

    CREATE_UPDATE_SCHEMA: vol.Schema

    async def _process_create_data(self, data: dict[str, Any]) -> dict[str, Any]:
        return self.CREATE_UPDATE_SCHEMA(data)

    @callback
    def _get_suggested_id(self, info: dict[str, Any]) -> str:
        return ulid_util.ulid_now()

    async def _update_data(
        self, item: dict[str, Any], update_data: dict[str, Any]
    ) -> dict[str, Any]:
        merged = {key: value for key, value in item.items() if key != "id"}
        merged.update(update_data)
        return {"id": item["id"], **self.CREATE_UPDATE_SCHEMA(merged)}


class PanelCollection(_UlidCollection):
    CREATE_UPDATE_SCHEMA = PANEL_FIELDS


class ZoneCollection(_UlidCollection):
    CREATE_UPDATE_SCHEMA = ZONE_FIELDS


class KustosStorage:
    """Owns all Kustos stores and collections."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._settings_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_SETTINGS, atomic_writes=True
        )
        self._runtime_store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_RUNTIME, atomic_writes=True
        )
        self.panels = PanelCollection(
            Store(hass, STORAGE_VERSION, STORAGE_KEY_PANELS, atomic_writes=True)
        )
        self.zones = ZoneCollection(
            Store(hass, STORAGE_VERSION, STORAGE_KEY_ZONES, atomic_writes=True)
        )
        self.settings: dict[str, Any] = {}
        self.runtime: dict[str, Any] = {}

    async def async_load(self) -> None:
        stored_settings = await self._settings_store.async_load() or {}
        self.settings = SETTINGS_SCHEMA(merge_defaults(DEFAULT_SETTINGS, stored_settings))
        # Persist the merged document so new default keys become visible/editable.
        await self._settings_store.async_save(self.settings)

        await self.panels.async_load()
        await self.zones.async_load()
        self.runtime = await self._runtime_store.async_load() or {"panels": {}}

    async def async_save_settings(self, settings: dict[str, Any]) -> None:
        self.settings = SETTINGS_SCHEMA(settings)
        await self._settings_store.async_save(self.settings)

    async def async_save_runtime(self) -> None:
        """Immediate save; used for critical FSM transitions."""
        await self._runtime_store.async_save(self.runtime)

    @callback
    def delay_save_runtime(self) -> None:
        """Debounced save for non-critical runtime updates."""
        self._runtime_store.async_delay_save(
            lambda: self.runtime, self.settings["storage"]["runtime_save_delay_s"]
        )

    def setting(self, *path: str) -> Any:
        """Read a settings value by path, e.g. setting('defaults', 'exit_delay_s')."""
        node: Any = self.settings
        for key in path:
            node = node[key]
        return node

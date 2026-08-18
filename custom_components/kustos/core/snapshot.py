"""Write-ahead entity snapshots with group resolution and refcounted restore.

Snapshots are captured lazily right before the first mutating command and
persisted BEFORE that command goes out, so a restart mid-alarm can always
restore exactly. Groups (Hue rooms, light groups) are resolved to members:
snapshot the members, command the group. Locks are deliberately never
snapshotted or auto-restored.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from ..storage import KustosStorage

_LOGGER = logging.getLogger(__name__)

# Attributes worth restoring per domain. Locks intentionally absent.
ATTRIBUTE_MAP: dict[str, tuple[str, ...]] = {
    "light": ("brightness", "hs_color", "color_temp_kelvin", "effect"),
    "switch": (),
    "input_boolean": (),
    "media_player": ("volume_level",),
}


class SnapshotManager:
    def __init__(self, hass: HomeAssistant, storage: KustosStorage) -> None:
        self._hass = hass
        self._storage = storage
        self._late_unsubs: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Group resolution
    # ------------------------------------------------------------------

    def resolve_members(self, entity_id: str, _seen: set[str] | None = None) -> list[str]:
        """Expand group-like entities to their members (cycle-safe)."""
        seen = _seen if _seen is not None else set()
        if entity_id in seen:
            return []
        seen.add(entity_id)
        state = self._hass.states.get(entity_id)
        members = state.attributes.get("entity_id") if state else None
        if not members or not isinstance(members, (list, tuple)):
            return [entity_id]
        resolved: list[str] = []
        for member in members:
            resolved.extend(self.resolve_members(member, seen))
        return resolved

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    async def ensure(self, entity_ids: list[str], owner: str) -> None:
        """Snapshot all (resolved) entities for owner; persist before returning."""
        changed = False
        for target in entity_ids:
            for entity_id in self.resolve_members(target):
                domain = entity_id.split(".")[0]
                if domain not in ATTRIBUTE_MAP:
                    continue
                snap = self._storage.snapshots.get(entity_id)
                if snap is None:
                    snap = self._capture(entity_id, domain)
                    snap["owners"] = [owner]
                    self._storage.snapshots[entity_id] = snap
                    changed = True
                elif owner not in snap["owners"]:
                    snap["owners"].append(owner)
                    changed = True
        if changed:
            await self._storage.async_save_snapshots()

    def _capture(self, entity_id: str, domain: str) -> dict[str, Any]:
        state = self._hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return {"unavailable": True, "captured_at": dt_util.utcnow().isoformat()}
        attrs = {
            attr: state.attributes.get(attr)
            for attr in ATTRIBUTE_MAP[domain]
            if state.attributes.get(attr) is not None
        }
        return {
            "state": state.state,
            "attributes": attrs,
            "captured_at": dt_util.utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    async def release(self, owner: str, restore: bool = True) -> list[str]:
        """Drop owner refs; restore entities whose last owner left. Returns failures."""
        failed: list[str] = []
        # Volumes before lights: an announce restore must not be drowned out
        # by a light transition churning the media player pipeline.
        ordered = sorted(
            self._storage.snapshots.items(),
            key=lambda item: 0 if item[0].startswith("media_player.") else 1,
        )
        for entity_id, snap in ordered:
            if owner not in snap.get("owners", []):
                continue
            snap["owners"].remove(owner)
            if snap["owners"]:
                continue
            if restore and not await self._restore_entity(entity_id, snap):
                failed.append(entity_id)
                snap["restore_failed"] = True
                snap["failed_at"] = dt_util.utcnow().isoformat()
                self._schedule_late_restore(entity_id)
            else:
                del self._storage.snapshots[entity_id]
        await self._storage.async_save_snapshots()
        return failed

    async def _restore_entity(self, entity_id: str, snap: dict[str, Any]) -> bool:
        state = self._hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        if snap.get("unavailable"):
            # Entity was unavailable at capture: nothing trustworthy to write
            # back; neutralize by turning it off (the engine only ever turned
            # things on) except for media players.
            if not entity_id.startswith("media_player."):
                await self._service_for(entity_id, "turn_off", {})
            return True
        domain = entity_id.split(".")[0]
        attrs: dict[str, Any] = snap.get("attributes", {})
        try:
            if domain == "media_player":
                if "volume_level" in attrs:
                    await self._hass.services.async_call(
                        "media_player",
                        "volume_set",
                        {"entity_id": entity_id, "volume_level": attrs["volume_level"]},
                        blocking=True,
                    )
                return True
            if snap["state"] != STATE_ON:
                await self._service_for(entity_id, "turn_off", {})
                return True
            data: dict[str, Any] = {}
            if domain == "light":
                if "brightness" in attrs:
                    data["brightness"] = attrs["brightness"]
                # Restore exactly one color system, preferring color_temp:
                # a light in white mode must not come back colored.
                if "color_temp_kelvin" in attrs:
                    data["color_temp_kelvin"] = attrs["color_temp_kelvin"]
                elif "hs_color" in attrs:
                    data["hs_color"] = attrs["hs_color"]
                if "effect" in attrs:
                    data["effect"] = attrs["effect"]
            await self._service_for(entity_id, "turn_on", data)
        except Exception:  # noqa: BLE001 - restore must keep going
            _LOGGER.exception("Restore failed for %s", entity_id)
            return False
        return True

    async def _service_for(self, entity_id: str, service: str, data: dict[str, Any]) -> None:
        domain = entity_id.split(".")[0]
        service_domain = domain if domain in ("light", "media_player", "input_boolean", "switch") else "homeassistant"
        await self._hass.services.async_call(
            service_domain, service, {"entity_id": entity_id, **data}, blocking=True
        )

    def _schedule_late_restore(self, entity_id: str) -> None:
        """One late restore attempt when the entity comes back in the window."""
        if entity_id in self._late_unsubs:
            return
        window = self._storage.setting("engine", "restore_retry_window_s")

        @callback
        def _give_up(_now) -> None:
            unsub = self._late_unsubs.pop(entity_id, None)
            if unsub:
                unsub[0]()

        async def _on_change(event) -> None:
            new_state = event.data.get("new_state")
            if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                return
            handles = self._late_unsubs.pop(entity_id, None)
            if handles:
                handles[0]()
                handles[1]()
            snap = self._storage.snapshots.get(entity_id)
            if snap is not None and await self._restore_entity(entity_id, snap):
                del self._storage.snapshots[entity_id]
                await self._storage.async_save_snapshots()

        unsub_state = async_track_state_change_event(self._hass, [entity_id], _on_change)
        unsub_timer = async_call_later(self._hass, window, _give_up)
        self._late_unsubs[entity_id] = (unsub_state, unsub_timer)

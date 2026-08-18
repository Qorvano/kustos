"""Reaction engine: runs profiles as deterministic timelines from t0.

Own asyncio executor (not the HA script engine) because we need restart
resume mid-alarm, suspend/resume on claim conflicts and phase-locked loops.
Stage boundaries are computed from t0 by wall clock, so a resume after a
restart continues at the correct point of the timeline.

Deliberate M2 simplification (documented deviation from the architecture):
the instance ends when the panel leaves TRIGGERED (rearm or disarm); push
escalation beyond that point is M4 territory.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util import ulid as ulid_util

from ..const import SILENT_ALARM_TYPES, AlarmType
from ..schemas import PERCEIVABLE_BLOCK_TYPES

if TYPE_CHECKING:
    from ..storage import KustosStorage
    from .snapshot import SnapshotManager

_LOGGER = logging.getLogger(__name__)

_COLOR_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww"}


class ReactionEngine:
    def __init__(
        self, hass: HomeAssistant, storage: KustosStorage, snapshots: SnapshotManager
    ) -> None:
        self._hass = hass
        self._storage = storage
        self._snapshots = snapshots
        self._tasks: dict[str, asyncio.Task] = {}
        self._block_tasks: dict[str, list[asyncio.Task]] = {}
        self._claims: dict[str, str] = {}  # entity_id -> instance_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _records(self) -> dict[str, dict[str, Any]]:
        return self._storage.runtime.setdefault("engine", {}).setdefault("instances", {})

    async def async_start(
        self,
        panel_id: str,
        area_id: str | None,
        alarm_type: str,
        detached: bool = False,
    ) -> None:
        """detached: runs independent of the panel FSM state (silent hold-up
        after a duress disarm); ends only via acknowledge."""
        for record in self._records().values():
            if record["panel_id"] == panel_id and record["alarm_type"] == alarm_type:
                return  # already running
        profile = self._resolve_profile(panel_id, alarm_type)
        if profile is None:
            _LOGGER.info("No reaction profile for %s/%s", panel_id, alarm_type)
            return
        stages = profile["stages"]
        if AlarmType(alarm_type) in SILENT_ALARM_TYPES:
            # A silent alarm must never be locally perceivable; strip instead
            # of refusing so push/lock blocks still run.
            stages = [
                {
                    "duration_s": stage["duration_s"],
                    "blocks": [
                        b for b in stage["blocks"]
                        if b["type"] not in PERCEIVABLE_BLOCK_TYPES
                    ],
                }
                for stage in stages
            ]
        record = {
            "detached": detached,
            "instance_id": ulid_util.ulid_now(),
            "panel_id": panel_id,
            "area_id": area_id,
            "alarm_type": alarm_type,
            "profile_name": profile.get("name"),
            "stages": stages,
            "t0": dt_util.utcnow().isoformat(),
            "stage_index": 0,
        }
        self._records()[record["instance_id"]] = record
        await self._storage.async_save_runtime()
        self._tasks[record["instance_id"]] = self._hass.async_create_background_task(
            self._run(record), name=f"kustos_instance_{record['instance_id']}"
        )

    def _resolve_profile(self, panel_id: str, alarm_type: str) -> dict[str, Any] | None:
        panel = next(
            (p for p in self._storage.panels.async_items() if p["id"] == panel_id), None
        )
        if panel is None:
            return None
        assignment = panel.get("alarm_types", {}).get(alarm_type)
        if not assignment or not assignment.get("profile_id"):
            return None
        return next(
            (
                p
                for p in self._storage.profiles.async_items()
                if p["id"] == assignment["profile_id"]
            ),
            None,
        )

    async def async_resume(self) -> None:
        """Rebuild running instances after a restart; t0 keeps the timeline."""
        for record in list(self._records().values()):
            if record["instance_id"] not in self._tasks:
                self._tasks[record["instance_id"]] = self._hass.async_create_background_task(
                    self._run(record), name=f"kustos_instance_{record['instance_id']}"
                )

    def has_instances(self, panel_id: str) -> bool:
        return any(
            r["panel_id"] == panel_id and not r.get("detached")
            for r in self._records().values()
        )

    async def async_stop_panel(
        self, panel_id: str, restore: bool = True, include_detached: bool = False
    ) -> None:
        for record in [
            r
            for r in self._records().values()
            if r["panel_id"] == panel_id
            and (include_detached or not r.get("detached"))
        ]:
            await self._teardown(record, restore=restore)

    async def async_shutdown(self) -> None:
        """Unload/HA stop: cancel tasks but keep persistence; NO restore now.

        The alarm may still be real; after the restart async_resume continues.
        """
        for task in [*self._tasks.values()]:
            task.cancel()
        for tasks in self._block_tasks.values():
            for task in tasks:
                task.cancel()
        self._tasks.clear()
        self._block_tasks.clear()
        self._claims.clear()

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    async def _run(self, record: dict[str, Any]) -> None:
        try:
            stages: list[dict[str, Any]] = record["stages"]
            t0 = datetime.fromisoformat(record["t0"])
            elapsed = (dt_util.utcnow() - t0).total_seconds()
            acc = 0.0
            start_idx = len(stages) - 1
            for idx, stage in enumerate(stages):
                duration = stage["duration_s"]
                if duration is None or elapsed < acc + duration:
                    start_idx = idx
                    break
                acc += duration
            for idx in range(start_idx, len(stages)):
                record["stage_index"] = idx
                self._storage.delay_save_runtime()
                stage = stages[idx]
                block_tasks = [
                    self._hass.async_create_background_task(
                        self._run_block(record, block),
                        name=f"kustos_block_{block['type']}",
                    )
                    for block in stage["blocks"]
                ]
                self._block_tasks[record["instance_id"]] = block_tasks
                duration = stage["duration_s"]
                if duration is None:
                    await asyncio.Event().wait()  # last stage, runs until stop
                boundary = acc + duration
                remaining = boundary - (dt_util.utcnow() - t0).total_seconds()
                if remaining > 0:
                    await asyncio.sleep(remaining)
                acc = boundary
                for task in block_tasks:
                    task.cancel()
            # Timeline exhausted (all stages finite): stay alive silently
            # until the panel leaves TRIGGERED and tears us down.
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Reaction instance %s crashed", record["instance_id"])

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def _priority(self, alarm_type: str) -> int:
        order = self._storage.setting("engine", "alarm_type_priority")
        try:
            return order.index(AlarmType(alarm_type))
        except ValueError:
            return len(order)

    def _owns(self, entity_id: str, record: dict[str, Any]) -> bool:
        """Claim or verify the claim; higher-priority alarm types take over."""
        holder_id = self._claims.get(entity_id)
        mine = record["instance_id"]
        if holder_id is None or holder_id not in self._records():
            self._claims[entity_id] = mine
            return True
        if holder_id == mine:
            return True
        holder = self._records()[holder_id]
        if self._priority(record["alarm_type"]) < self._priority(holder["alarm_type"]):
            self._claims[entity_id] = mine  # takeover; loser suspends itself
            return True
        return False

    def _release_claims(self, instance_id: str) -> None:
        for entity_id in [e for e, o in self._claims.items() if o == instance_id]:
            del self._claims[entity_id]

    # ------------------------------------------------------------------
    # Blocks
    # ------------------------------------------------------------------

    async def _run_block(self, record: dict[str, Any], block: dict[str, Any]) -> None:
        try:
            runner = getattr(self, f"_block_{block['type']}")
            await runner(record, block)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Block %s of instance %s failed", block["type"], record["instance_id"]
            )

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await self._hass.services.async_call(domain, service, data, blocking=True)
        except Exception:  # noqa: BLE001 - a dead entity must not kill the loop
            _LOGGER.warning("Service %s.%s failed for %s", domain, service, data)

    def _split_targets(self, record: dict[str, Any], targets: list[str]) -> tuple[list[str], list[str]]:
        """Split into color-capable lights and plain on/off targets."""
        color: list[str] = []
        plain: list[str] = []
        for target in targets:
            members = self._snapshots.resolve_members(target)
            is_color = False
            for member in members:
                state = self._hass.states.get(member)
                modes = (state and state.attributes.get("supported_color_modes")) or []
                if member.startswith("light.") and _COLOR_MODES.intersection(modes):
                    is_color = True
                    break
            (color if is_color else plain).append(target)
        return color, plain

    async def _block_flash_lights(self, record: dict[str, Any], block: dict[str, Any]) -> None:
        await self._snapshots.ensure(block["targets"], record["instance_id"])
        color, plain = self._split_targets(record, block["targets"])
        if block["non_color_behavior"] == "off" and plain:
            for target in plain:
                if self._owns(target, record):
                    await self._call("homeassistant", "turn_off", {"entity_id": target})
        half = block["period_s"] / 2
        while True:
            for target in color:
                if self._owns(target, record):
                    await self._call(
                        "light",
                        "turn_on",
                        {
                            "entity_id": target,
                            "rgb_color": block["color_rgb"],
                            "brightness_pct": block["brightness_pct"],
                            "transition": block["fade_s"],
                        },
                    )
            if block["non_color_behavior"] == "hard_blink":
                for target in plain:
                    if self._owns(target, record):
                        await self._call("homeassistant", "turn_on", {"entity_id": target})
            await asyncio.sleep(half)
            for target in color:
                if self._owns(target, record):
                    await self._call(
                        "light",
                        "turn_off",
                        {"entity_id": target, "transition": block["fade_s"]},
                    )
            if block["non_color_behavior"] == "hard_blink":
                for target in plain:
                    if self._owns(target, record):
                        await self._call("homeassistant", "turn_off", {"entity_id": target})
            await asyncio.sleep(half)

    async def _block_lights_on(self, record: dict[str, Any], block: dict[str, Any]) -> None:
        await self._snapshots.ensure(block["targets"], record["instance_id"])

        async def _apply() -> None:
            for target in block["targets"]:
                if not self._owns(target, record):
                    continue
                if target.startswith("light."):
                    await self._call(
                        "light",
                        "turn_on",
                        {"entity_id": target, "brightness_pct": block["brightness_pct"]},
                    )
                else:
                    await self._call("homeassistant", "turn_on", {"entity_id": target})

        await _apply()
        if block["refresh_interval_s"] <= 0:
            return
        while True:
            await asyncio.sleep(block["refresh_interval_s"])
            await _apply()

    async def _block_sound(self, record: dict[str, Any], block: dict[str, Any]) -> None:
        switch_like = [
            t for t in block["targets"] if t.split(".")[0] in ("switch", "input_boolean")
        ]
        await self._snapshots.ensure(switch_like, record["instance_id"])
        started = dt_util.utcnow()

        async def _fire() -> None:
            for target in block["targets"]:
                domain = target.split(".")[0]
                if not self._owns(target, record):
                    continue
                if domain == "siren":
                    await self._call("siren", "turn_on", {"entity_id": target})
                elif domain in ("switch", "input_boolean"):
                    await self._call(domain, "turn_on", {"entity_id": target})
                elif domain in ("button", "input_button"):
                    await self._call(domain, "press", {"entity_id": target})

        await _fire()
        has_buttons = any(
            t.split(".")[0] in ("button", "input_button") for t in block["targets"]
        )
        while True:
            elapsed = (dt_util.utcnow() - started).total_seconds()
            if elapsed >= block["max_duration_s"]:
                await self._sound_off(record, block)
                return
            sleep_for = min(
                block["retrigger_interval_s"] if has_buttons else block["max_duration_s"],
                block["max_duration_s"] - elapsed,
            )
            await asyncio.sleep(sleep_for)
            if (dt_util.utcnow() - started).total_seconds() < block["max_duration_s"]:
                if has_buttons:
                    await _fire()

    async def _sound_off(self, record: dict[str, Any], block: dict[str, Any]) -> None:
        for target in block["targets"]:
            domain = target.split(".")[0]
            if domain == "siren":
                await self._call("siren", "turn_off", {"entity_id": target})
            elif domain in ("switch", "input_boolean"):
                await self._call(domain, "turn_off", {"entity_id": target})
                state = self._hass.states.get(target)
                if state is not None and state.state == "on":
                    await self._call(domain, "turn_off", {"entity_id": target})

    async def _block_announce_loop(self, record: dict[str, Any], block: dict[str, Any]) -> None:
        await self._snapshots.ensure(block["media_targets"], record["instance_id"])
        if block.get("volume_pct") is not None:
            for target in block["media_targets"]:
                await self._call(
                    "media_player",
                    "volume_set",
                    {"entity_id": target, "volume_level": block["volume_pct"] / 100},
                )
        domain, service = block["notify_service"].split(".", 1)
        payload = {"message": block["message"], **block.get("data", {})}
        while True:
            await self._call(domain, service, payload)
            await asyncio.sleep(block["interval_s"])

    async def _block_notify(self, record: dict[str, Any], block: dict[str, Any]) -> None:
        domain, service = block["service"].split(".", 1)
        payload: dict[str, Any] = {"message": block["message"], **block.get("data", {})}
        if block.get("title"):
            payload["title"] = block["title"]
        await self._call(domain, service, payload)

    async def _block_lock(self, record: dict[str, Any], block: dict[str, Any]) -> None:
        if block["action"] == "unlock":
            allowed = self._storage.setting("engine", "life_safety_unlock_types")
            if AlarmType(record["alarm_type"]) not in allowed:
                _LOGGER.error(
                    "Unlock refused: %s is not a life-safety alarm type",
                    record["alarm_type"],
                )
                return
        for target in block["targets"]:
            await self._call("lock", block["action"], {"entity_id": target})

    # ------------------------------------------------------------------
    # Teardown (fixed order; critique-approved sequence)
    # ------------------------------------------------------------------

    async def _teardown(self, record: dict[str, Any], restore: bool) -> None:
        instance_id = record["instance_id"]
        # 1) Freeze: no further commands from this instance.
        task = self._tasks.pop(instance_id, None)
        if task:
            task.cancel()
        for block_task in self._block_tasks.pop(instance_id, []):
            block_task.cancel()
        # 2) Acoustics off, verified.
        for stage in record["stages"]:
            for block in stage["blocks"]:
                if block["type"] == "sound":
                    await self._sound_off(record, block)
        # 3) Announcements: stop playback, apply fallback volumes where the
        #    real volume was never readable (Echo pattern).
        for stage in record["stages"]:
            for block in stage["blocks"]:
                if block["type"] != "announce_loop":
                    continue
                for target in block["media_targets"]:
                    await self._call("media_player", "media_stop", {"entity_id": target})
                    snap = self._storage.snapshots.get(target, {})
                    has_volume = "volume_level" in snap.get("attributes", {})
                    if not has_volume and block.get("volume_fallback_pct") is not None:
                        await self._call(
                            "media_player",
                            "volume_set",
                            {
                                "entity_id": target,
                                "volume_level": block["volume_fallback_pct"] / 100,
                            },
                        )
        # 4) Restore snapshots (volumes before lights inside release; locks never).
        await self._snapshots.release(instance_id, restore=restore)
        # 5) Cleanup.
        self._release_claims(instance_id)
        self._records().pop(instance_id, None)
        await self._storage.async_save_runtime()

"""Append-only audit log: monthly JSONL files, independent of the recorder.

Lives under <config>/kustos/audit/YYYY-MM.jsonl. Writes go through the
executor; every entry carries a timestamp and a per-boot sequence number.
Admin-only access via the WebSocket API.
"""
from __future__ import annotations

import json
import os
from itertools import count
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


class AuditLog:
    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._dir = hass.config.path("kustos", "audit")
        self._seq = count(1)

    def _path_for(self, month: str) -> str:
        return os.path.join(self._dir, f"{month}.jsonl")

    async def async_append(self, kind: str, data: dict[str, Any]) -> None:
        now = dt_util.utcnow()
        entry = {
            "ts": now.isoformat(),
            "seq": next(self._seq),
            "kind": kind,
            **data,
        }
        path = self._path_for(now.strftime("%Y-%m"))

        def _write() -> None:
            os.makedirs(self._dir, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

        await self._hass.async_add_executor_job(_write)

    async def async_query(self, month: str, limit: int) -> list[dict[str, Any]]:
        """Newest entries of a month, newest first."""
        path = self._path_for(month)

        def _read() -> list[dict[str, Any]]:
            if not os.path.exists(path):
                return []
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
            entries = []
            for line in lines[-limit:]:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue
            entries.reverse()
            return entries

        return await self._hass.async_add_executor_job(_read)

"""Alarmo import: translate an alarmo_storage data blob into Kustos objects.

Deliberately tolerant: unknown fields are ignored, every interpretation and
every skipped item lands in the report. PIN hashes are NOT migrated (foreign
format); users arrive without a PIN and get one via users/set_pin.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from ..storage import KustosStorage

# Alarmo sensor "type" -> how we read it when no device_class helps.
_ENVIRONMENTAL_BY_DEVICE_CLASS = {
    "smoke": "fire",
    "heat": "fire",
    "gas": "co",
    "carbon_monoxide": "co",
    "moisture": "water",
}


def _map_modes(alarmo_area: dict[str, Any]) -> dict[str, Any]:
    modes: dict[str, Any] = {}
    for mode_name, cfg in (alarmo_area.get("modes") or {}).items():
        if not mode_name.startswith("armed_"):
            continue
        entry: dict[str, Any] = {"enabled": bool(cfg.get("enabled", False))}
        # Alarmo: exit_time/entry_time/trigger_time (seconds).
        for src, dst in (
            ("exit_time", "exit_delay_s"),
            ("entry_time", "entry_delay_s"),
            ("trigger_time", "trigger_time_s"),
        ):
            if cfg.get(src) is not None:
                entry[dst] = float(cfg[src])
        modes[mode_name] = entry
    return modes


def _zone_for_sensor(
    hass: HomeAssistant,
    sensor: dict[str, Any],
    panel_id: str,
    report: list[str],
) -> dict[str, Any] | None:
    entity_id = sensor.get("entity_id")
    if not entity_id:
        report.append("Sensor ohne entity_id übersprungen")
        return None
    sensor_type = sensor.get("type") or ""
    alarm_type = "burglary"
    if sensor_type == "environmental":
        state = hass.states.get(entity_id)
        device_class = (state and state.attributes.get("device_class")) or ""
        alarm_type = _ENVIRONMENTAL_BY_DEVICE_CLASS.get(device_class)
        if alarm_type is None:
            alarm_type = "technical"
            report.append(
                f"{entity_id}: Umwelt-Sensor ohne bekannte device_class, als 'technical' importiert"
            )
    elif sensor_type == "tamper":
        alarm_type = "tamper"
    elif sensor.get("always_on"):
        # Kustos derives 24/7 from the alarm type; an always-on security
        # sensor becomes a tamper zone, which keeps the 24/7 semantics.
        alarm_type = "tamper"
        report.append(
            f"{entity_id}: always_on-Sicherheitssensor als 'tamper' (24/7) importiert"
        )

    role = "delayed" if sensor.get("use_entry_delay") else "instant"
    modes = {mode: role for mode in (sensor.get("modes") or []) if mode.startswith("armed_")}

    return {
        "entity_id": entity_id,
        "panel_id": panel_id,
        "name": sensor.get("name") or None,
        "alarm_type": alarm_type,
        "modes": modes,
        "options": {
            "use_exit_delay": bool(sensor.get("use_exit_delay")),
            "arm_after_closing": bool(sensor.get("arm_on_close")),
            "allow_open": bool(sensor.get("allow_open")),
            "auto_bypass": bool(sensor.get("auto_bypass")),
            "trigger_when_unavailable": bool(sensor.get("trigger_unavailable")),
        },
    }


async def async_import_alarmo(
    hass: HomeAssistant, storage: KustosStorage, data: dict[str, Any]
) -> dict[str, Any]:
    report: list[str] = []
    panel_by_alarmo_area: dict[str, str] = {}
    counts = {"panels": 0, "zones": 0, "users": 0}

    for area in data.get("areas") or []:
        alarmo_area_id = area.get("area_id") or area.get("id")
        name = area.get("name") or alarmo_area_id or "importiert"
        panel = await storage.panels.async_create_item(
            {
                # Alarmo areas are their own world; we bind to a same-named
                # slug and report it, the user re-maps in the panel later.
                "scope": {"type": "area", "area_id": str(name).lower().replace(" ", "_")},
                "modes": _map_modes(area),
            }
        )
        panel_by_alarmo_area[str(alarmo_area_id)] = panel["id"]
        counts["panels"] += 1
        report.append(
            f"Bereich '{name}': area_id-Zuordnung bitte prüfen (Alarmo führt eigene Bereiche)"
        )

    for sensor in data.get("sensors") or []:
        area_ref = str(sensor.get("area"))
        panel_id = panel_by_alarmo_area.get(area_ref)
        if panel_id is None:
            report.append(
                f"{sensor.get('entity_id')}: Alarmo-Bereich '{area_ref}' unbekannt, übersprungen"
            )
            continue
        zone = _zone_for_sensor(hass, sensor, panel_id, report)
        if zone is not None:
            await storage.zones.async_create_item(zone)
            counts["zones"] += 1

    for user in data.get("users") or []:
        name = user.get("name")
        if not name:
            continue
        await storage.users.async_create_item(
            {
                "name": name,
                "enabled": bool(user.get("enabled", True)),
                "rights": {
                    "can_arm": bool(user.get("can_arm", True)),
                    "can_disarm": bool(user.get("can_disarm", True)),
                    "panels": None,
                },
            }
        )
        counts["users"] += 1
        report.append(f"Benutzer '{name}': PIN nicht übernommen (fremdes Hash-Format), bitte neu setzen")

    if data.get("automations"):
        report.append(
            f"{len(data['automations'])} Alarmo-Automationen NICHT importiert: in Kustos als Reaktionsprofile neu anlegen"
        )

    return {"counts": counts, "report": report}

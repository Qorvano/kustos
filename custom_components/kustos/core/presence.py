"""Presence subsystem: per-person state machine with away hysteresis.

Core requirement (the user's proven home-grown logic, generalized): a panel
only auto-arms after a person was VERIFIABLY away (distance threshold or
sustained not_home), and only a return within the SAME trip disarms again.
unavailable never counts as away; an untracked person blocks auto-arming.
Auto-disarm never runs while the panel is pending or triggered (critique
finding 2: a burglar-opened entry delay must not be swallowed by a
coincidentally approaching resident).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util
from homeassistant.util import ulid as ulid_util

from ..const import (
    EVENT_AUTO_ARM_ABORTED,
    EVENT_AUTO_ARM_PENDING,
    EVENT_AUTO_ARMED,
    EVENT_AUTO_DISARMED,
    EVENT_PRESENCE_PHASE,
    ArmMode,
)
from .fsm import PanelState

if TYPE_CHECKING:
    from ..storage import KustosStorage
    from .hub import KustosHub

_LOGGER = logging.getLogger(__name__)

PHASE_HOME = "home"
PHASE_LEAVING = "leaving"
PHASE_CONFIRMED_AWAY = "confirmed_away"
PHASE_RETURNING = "returning"
PHASE_UNTRACKED = "untracked"
# "arrived" is a transient signal (return within the confirmed trip), the
# stored phase immediately becomes home again.
SIGNAL_ARRIVED = "arrived"

# Sub-keys of runtime["presence"]["persons"][person_id]
_BLOCKED_STATE_NAMES = {
    "triggered": PanelState.TRIGGERED,
    "pending": PanelState.PENDING,
    "arming": PanelState.ARMING,
}


class PresenceManager:
    def __init__(self, hass: HomeAssistant, storage: KustosStorage, hub: KustosHub) -> None:
        self._hass = hass
        self._storage = storage
        self._hub = hub
        self._unsub_state: Any | None = None
        self._unsub_collections: list[Any] = []
        self._confirm_timers: dict[str, Any] = {}
        self._prewarn_timers: dict[str, Any] = {}
        self._suppressed: dict[str, tuple[str, ...]] = {}  # rule_id -> trip key

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        self._resubscribe()
        self._unsub_collections = [
            self._storage.persons.async_add_listener(self._on_config_change),
            self._storage.rules.async_add_listener(self._on_config_change),
        ]
        for person in self._storage.persons.async_items():
            self._evaluate_person(person)
        self._evaluate_rules()

    async def async_stop(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        for unsub in self._unsub_collections:
            unsub()
        self._unsub_collections = []
        for cancel in [*self._confirm_timers.values(), *self._prewarn_timers.values()]:
            cancel()
        self._confirm_timers.clear()
        self._prewarn_timers.clear()

    async def _on_config_change(self, change_type: str, item_id: str, config: dict) -> None:
        self._resubscribe()
        for person in self._storage.persons.async_items():
            self._evaluate_person(person)
        self._evaluate_rules()

    def _resubscribe(self) -> None:
        if self._unsub_state:
            self._unsub_state()
            self._unsub_state = None
        entities: list[str] = []
        for person in self._storage.persons.async_items():
            entities.append(person["tracker_entity"])
            if person.get("distance_entity"):
                entities.append(person["distance_entity"])
        if entities:
            self._unsub_state = async_track_state_change_event(
                self._hass, entities, self._on_entity_change
            )

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    @callback
    def _on_entity_change(self, event) -> None:
        entity_id = event.data["entity_id"]
        for person in self._storage.persons.async_items():
            if entity_id in (person["tracker_entity"], person.get("distance_entity")):
                self._evaluate_person(person)
        self._evaluate_rules()

    def _records(self) -> dict[str, dict[str, Any]]:
        return self._storage.runtime.setdefault("presence", {}).setdefault("persons", {})

    def record(self, person_id: str) -> dict[str, Any]:
        return self._records().setdefault(
            person_id,
            {"phase": PHASE_HOME, "trip_id": None, "confirmed_in_trip": False,
             "not_home_since": None},
        )

    def _distance_m(self, person: dict[str, Any]) -> float | None:
        entity_id = person.get("distance_entity")
        if not entity_id:
            return None
        state = self._hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        unit = (state.attributes.get("unit_of_measurement") or "m").lower()
        return value * 1000 if unit == "km" else value

    def _threshold_m(self, person: dict[str, Any]) -> float:
        return person.get("away_confirm_distance_m") or self._storage.setting(
            "presence", "away_confirm_distance_m"
        )

    # ------------------------------------------------------------------
    # Person state machine
    # ------------------------------------------------------------------

    def _evaluate_person(self, person: dict[str, Any]) -> None:
        rec = self.record(person["id"])
        tracker = self._hass.states.get(person["tracker_entity"])
        old_phase = rec["phase"]
        arrived = False

        if tracker is None or tracker.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            rec["phase"] = PHASE_UNTRACKED
        elif tracker.state == STATE_HOME:
            arrived = rec["confirmed_in_trip"] and old_phase in (
                PHASE_CONFIRMED_AWAY,
                PHASE_RETURNING,
                PHASE_LEAVING,
                PHASE_UNTRACKED,
            )
            rec["phase"] = PHASE_HOME
            rec["not_home_since"] = None
            self._cancel_confirm(person["id"])
        else:
            # Away-ish (not_home or a named zone).
            if old_phase in (PHASE_HOME, PHASE_UNTRACKED):
                rec["phase"] = PHASE_LEAVING
                rec["trip_id"] = ulid_util.ulid_now()
                rec["confirmed_in_trip"] = False
                rec["not_home_since"] = dt_util.utcnow().isoformat()
                self._schedule_confirm(person)
            distance = self._distance_m(person)
            threshold = self._threshold_m(person)
            if distance is not None:
                if distance >= threshold:
                    rec["phase"] = PHASE_CONFIRMED_AWAY
                    rec["confirmed_in_trip"] = True
                elif rec["phase"] == PHASE_CONFIRMED_AWAY and distance <= threshold / 2:
                    # Derived return threshold: half the away distance
                    # (architecture: derived default, not a second free knob).
                    rec["phase"] = PHASE_RETURNING
            elif rec["not_home_since"] is not None and rec["phase"] == PHASE_LEAVING:
                min_away = self._storage.setting("presence", "min_away_duration_s")
                since = dt_util.parse_datetime(rec["not_home_since"])
                if since and (dt_util.utcnow() - since).total_seconds() >= min_away:
                    rec["phase"] = PHASE_CONFIRMED_AWAY
                    rec["confirmed_in_trip"] = True

        if rec["phase"] != old_phase or arrived:
            payload = {
                "person_id": person["id"],
                "name": person["name"],
                "phase": SIGNAL_ARRIVED if arrived else rec["phase"],
                "trip_id": rec["trip_id"],
            }
            self._hass.bus.async_fire(EVENT_PRESENCE_PHASE, payload)
            self._hub._audit("presence_phase", payload)
            self._storage.delay_save_runtime()
            if arrived:
                self._handle_arrival(person, rec)
                rec["confirmed_in_trip"] = False

    def _schedule_confirm(self, person: dict[str, Any]) -> None:
        """Without a distance source, confirmation happens after min_away_duration."""
        if person.get("distance_entity"):
            return
        self._cancel_confirm(person["id"])
        delay = self._storage.setting("presence", "min_away_duration_s")

        @callback
        def _fire(_now) -> None:
            self._confirm_timers.pop(person["id"], None)
            current = next(
                (p for p in self._storage.persons.async_items() if p["id"] == person["id"]),
                None,
            )
            if current:
                self._evaluate_person(current)
                self._evaluate_rules()

        self._confirm_timers[person["id"]] = async_call_later(self._hass, delay, _fire)

    def _cancel_confirm(self, person_id: str) -> None:
        cancel = self._confirm_timers.pop(person_id, None)
        if cancel:
            cancel()

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def _rule_persons(self, rule: dict[str, Any]) -> list[dict[str, Any]]:
        persons = self._storage.persons.async_items()
        if rule["persons"] is None:
            return persons
        return [p for p in persons if p["id"] in rule["persons"]]

    def _condition_active(self, rule: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
        persons = self._rule_persons(rule)
        if not persons:
            return False, ()
        records = [self.record(p["id"]) for p in persons]
        active = all(r["phase"] == PHASE_CONFIRMED_AWAY for r in records)
        trip_key = tuple(sorted(str(r["trip_id"]) for r in records))
        return active, trip_key

    def _panel_states(self, rule: dict[str, Any]) -> dict[str, PanelState]:
        return {
            pid: self._hub.fsms[pid].state
            for pid in self._hub.resolve_target(rule["panel_id"])
        }

    @callback
    def _evaluate_rules(self) -> None:
        for rule in self._storage.rules.async_items():
            if not rule["enabled"]:
                continue
            active, trip_key = self._condition_active(rule)
            if not active:
                self._abort_prewarn(rule, reason="condition_lost")
                continue
            if self._suppressed.get(rule["id"]) == trip_key:
                continue  # manually disarmed during this very trip
            states = self._panel_states(rule)
            if not states or not all(s is PanelState.DISARMED for s in states.values()):
                continue
            if rule["id"] in self._prewarn_timers:
                continue
            prewarn = rule["arm"].get("prewarn_s")
            if prewarn is None:
                prewarn = self._storage.setting("presence", "prewarn_s")
            if rule["arm"]["execution"] == "immediate" or prewarn == 0:
                self._hass.async_create_background_task(
                    self._do_arm(rule), name="kustos_auto_arm"
                )
                continue
            ends_at = dt_util.utcnow() + timedelta(seconds=prewarn)
            self._hass.bus.async_fire(
                EVENT_AUTO_ARM_PENDING,
                {
                    "rule_id": rule["id"],
                    "rule": rule["name"],
                    "panel_id": rule["panel_id"],
                    "ends_at": ends_at.isoformat(),
                },
            )

            @callback
            def _fire(_now, rule=rule) -> None:
                self._prewarn_timers.pop(rule["id"], None)
                active_now, _ = self._condition_active(rule)
                if active_now:
                    self._hass.async_create_background_task(
                        self._do_arm(rule), name="kustos_auto_arm"
                    )

            self._prewarn_timers[rule["id"]] = async_call_later(
                self._hass, prewarn, _fire
            )

    def _abort_prewarn(self, rule: dict[str, Any], reason: str) -> None:
        cancel = self._prewarn_timers.pop(rule["id"], None)
        if cancel:
            cancel()
            self._hass.bus.async_fire(
                EVENT_AUTO_ARM_ABORTED,
                {"rule_id": rule["id"], "rule": rule["name"], "reason": reason},
            )

    @callback
    def abort_prewarn_by_id(self, rule_id: str) -> bool:
        rule = next(
            (r for r in self._storage.rules.async_items() if r["id"] == rule_id), None
        )
        if rule is None or rule_id not in self._prewarn_timers:
            return False
        self._abort_prewarn(rule, reason="user")
        # A manual abort suppresses re-arming for the current trip.
        _, trip_key = self._condition_active(rule)
        self._suppressed[rule_id] = trip_key
        return True

    async def _do_arm(self, rule: dict[str, Any]) -> None:
        mode = ArmMode(rule["arm"]["mode"])
        result = await self._hub.async_arm(
            rule["panel_id"], mode, actor=f"rule:{rule['name']}"
        )
        event = EVENT_AUTO_ARMED if result.ok else EVENT_AUTO_ARM_ABORTED
        self._hass.bus.async_fire(
            event,
            {
                "rule_id": rule["id"],
                "rule": rule["name"],
                "panel_id": rule["panel_id"],
                "reason": None if result.ok else str(result.reason),
                "open_zones": list(result.open_zones),
            },
        )

    def _handle_arrival(self, person: dict[str, Any], rec: dict[str, Any]) -> None:
        for rule in self._storage.rules.async_items():
            if not rule["enabled"] or not rule["return_action"]["disarm"]:
                continue
            if rule["persons"] is not None and person["id"] not in rule["persons"]:
                continue
            self._abort_prewarn(rule, reason="arrival")
            blocked = {
                _BLOCKED_STATE_NAMES[name]
                for name in rule["blocked_in_alarm_states"]
            }
            for panel_id, state in self._panel_states(rule).items():
                if state is PanelState.DISARMED:
                    continue
                if state in blocked:
                    self._hub._audit(
                        "auto_disarm_blocked",
                        {"panel_id": panel_id, "rule": rule["name"],
                         "state": str(state)},
                    )
                    continue
                self._hass.async_create_background_task(
                    self._do_disarm(rule, panel_id, person), name="kustos_auto_disarm"
                )

    async def _do_disarm(
        self, rule: dict[str, Any], panel_id: str, person: dict[str, Any]
    ) -> None:
        await self._hub.async_disarm(panel_id, actor=f"rule:{rule['name']}")
        self._hass.bus.async_fire(
            EVENT_AUTO_DISARMED,
            {
                "rule_id": rule["id"],
                "rule": rule["name"],
                "panel_id": panel_id,
                "person": person["name"],
            },
        )

    # ------------------------------------------------------------------
    # Manual-action interplay
    # ------------------------------------------------------------------

    @callback
    def on_manual_disarm(self, panel_id: str) -> None:
        """A human disarmed: no rule may re-arm during the same trip."""
        for rule in self._storage.rules.async_items():
            if rule["panel_id"] not in (panel_id, "master"):
                continue
            active, trip_key = self._condition_active(rule)
            if active:
                self._suppressed[rule["id"]] = trip_key
            self._abort_prewarn(rule, reason="manual_disarm")

    def phases(self) -> list[dict[str, Any]]:
        return [
            {
                "person_id": p["id"],
                "name": p["name"],
                **{k: v for k, v in self.record(p["id"]).items()},
            }
            for p in self._storage.persons.async_items()
        ]

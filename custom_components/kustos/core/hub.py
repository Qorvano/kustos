"""Hub: adapts the pure panel FSMs to Home Assistant.

Owns timers, zone-entity listeners, event firing, runtime persistence and
master aggregation. Entities and the WebSocket API talk to the hub only;
they never touch an FSM directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import collection
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_added_domain,
    async_track_state_change_event,
)
from datetime import timedelta

from homeassistant.util import dt as dt_util

from ..const import (
    ATTR_ALARM_TYPE,
    ATTR_ENTITY_ID,
    ATTR_ZONE_ID,
    EVENT_TRIGGERED,
    EVENT_WALK_TEST_ZONE,
    ArmMode,
    PanelScope,
    SIGNAL_CONFIG_UPDATED,
    SIGNAL_PANEL_STATE,
    AlarmType,
)
from .audit import AuditLog
from .auth import needs_rehash, verify_pin
from .engine import ReactionEngine
from .fsm import (
    ArmFailReason,
    ArmResult,
    Effects,
    ModeTimes,
    PanelBehavior,
    PanelFsm,
    PanelState,
    ZoneConfig,
)
from .presence import PresenceManager
from .snapshot import SnapshotManager

if TYPE_CHECKING:
    from ..storage import KustosStorage

MASTER_ID = "master"


class KustosHub:
    """Runtime brain: one FSM per area panel plus master aggregation."""

    def __init__(self, hass: HomeAssistant, storage: KustosStorage) -> None:
        self._hass = hass
        self._storage = storage
        self.fsms: dict[str, PanelFsm] = {}
        self._timers: dict[str, Any] = {}
        self._zone_unsub: Any | None = None
        self._config_unsub: Any | None = None
        self._zone_by_entity: dict[str, list[tuple[str, str]]] = {}
        self.snapshots = SnapshotManager(hass, storage)
        self.engine = ReactionEngine(hass, storage, self.snapshots)
        self.audit = AuditLog(hass)
        self.presence = PresenceManager(hass, storage, self)
        self._restoring = False
        # Walk test: panel_id -> {"ends_at", "tested", "cancel"}
        self.walk_tests: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        # Deterministic boot order (regression: boot race re-captured
        # snapshots mid-flash and restore wrote alarm red back): restore the
        # FSMs without engine side effects, resume persisted instances, then
        # reconcile exactly once.
        self._restoring = True
        self._rebuild()
        self._restore_runtime()
        self._restoring = False
        # Tear stale instances down BEFORE resuming: a resumed loop may fire
        # its first command instantly and re-pollute the snapshots.
        for panel_id, fsm in self.fsms.items():
            if fsm.state is not PanelState.TRIGGERED and self.engine.has_instances(panel_id):
                await self.engine.async_stop_panel(panel_id, restore=True)
        await self.engine.async_resume()
        # HA persons ARE the Kustos people: everyone appears automatically,
        # only rights/PINs/presence details get configured (user decision).
        await self.async_sync_ha_persons()
        self._person_added_unsub = async_track_state_added_domain(
            self._hass, "person", self._on_person_added
        )
        await self.presence.async_start()
        # Zone changes rebuild in place; panel add/remove is handled by the
        # config entry (reload) so entities are created/removed cleanly.
        self._config_unsub = self._storage.zones.async_add_listener(
            self._on_config_change
        )

    async def async_stop(self) -> None:
        # No restore here: the alarm may still be real; resume happens on boot.
        await self.presence.async_stop()
        await self.engine.async_shutdown()
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        if self._zone_unsub:
            self._zone_unsub()
            self._zone_unsub = None
        if self._config_unsub:
            self._config_unsub()
            self._config_unsub = None
        if getattr(self, "_person_added_unsub", None):
            self._person_added_unsub()
            self._person_added_unsub = None

    async def _on_person_added(self, event: Event) -> None:
        await self.async_sync_ha_persons()

    async def async_sync_ha_persons(self) -> None:
        """Mirror HA persons into users (access) and persons (presence).

        Create missing records, keep names in sync with the friendly name.
        Records are never deleted here; a vanished HA person just stops
        being listed by the frontend.
        """
        users_by_pe = {
            u.get("person_entity"): u for u in self._storage.users.async_items()
        }
        persons_by_pe = {
            p.get("person_entity"): p for p in self._storage.persons.async_items()
        }
        for state in self._hass.states.async_all("person"):
            name = state.attributes.get("friendly_name") or state.entity_id
            user = users_by_pe.get(state.entity_id)
            if user is None:
                await self._storage.users.async_create_item(
                    {"name": name, "person_entity": state.entity_id}
                )
            elif user["name"] != name:
                await self._storage.users.async_update_item(user["id"], {"name": name})
            person = persons_by_pe.get(state.entity_id)
            if person is None:
                await self._storage.persons.async_create_item(
                    {
                        "name": name,
                        "person_entity": state.entity_id,
                        "tracker_entity": state.entity_id,
                    }
                )
            elif person["name"] != name:
                await self._storage.persons.async_update_item(
                    person["id"], {"name": name}
                )

    async def _on_config_change(
        self, change_type: str, item_id: str, config: dict[str, Any]
    ) -> None:
        """Panel/zone configuration changed: rebuild, keeping runtime state."""
        saved = {panel_id: fsm.to_dict() for panel_id, fsm in self.fsms.items()}
        self._rebuild()
        for panel_id, fsm in self.fsms.items():
            if panel_id in saved:
                fx = fsm.restore(saved[panel_id], self._open_zone_ids(panel_id))
                self._apply_effects(panel_id, fx)
        async_dispatcher_send(self._hass, SIGNAL_CONFIG_UPDATED)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _rebuild(self) -> None:
        settings = self._storage.settings
        defaults = settings["defaults"]
        default_times = ModeTimes(
            exit_delay_s=defaults["exit_delay_s"],
            entry_delay_s=defaults["entry_delay_s"],
            trigger_time_s=defaults["trigger_time_s"],
        )

        zones_by_panel: dict[str, dict[str, ZoneConfig]] = {}
        self._zone_by_entity = {}
        for item in self._storage.zones.async_items():
            zone = ZoneConfig(
                zone_id=item["id"],
                entity_id=item["entity_id"],
                alarm_type=AlarmType(item["alarm_type"]),
                modes={ArmMode(k): v for k, v in item["modes"].items()},
                use_exit_delay=item["options"]["use_exit_delay"],
                arm_after_closing=item["options"]["arm_after_closing"],
                allow_open=item["options"]["allow_open"],
                auto_bypass=item["options"]["auto_bypass"],
                trigger_when_unavailable=item["options"]["trigger_when_unavailable"],
                # .get: zone documents stored before M4 lack the key; the
                # fallback mirrors the schema default.
                unavailable_policy=item["options"].get("unavailable_policy", "ignore"),
            )
            zones_by_panel.setdefault(item["panel_id"], {})[zone.zone_id] = zone
            self._zone_by_entity.setdefault(item["entity_id"], []).append(
                (item["panel_id"], zone.zone_id)
            )

        self.fsms = {}
        for item in self._storage.panels.async_items():
            if item["scope"]["type"] == PanelScope.MASTER or not item["enabled"]:
                continue
            panel_id = item["id"]
            mode_cfg = {ArmMode(k): v for k, v in item["modes"].items()}
            enabled_modes = frozenset(
                mode for mode, cfg in mode_cfg.items() if cfg["enabled"]
            )

            def make_times(cfg_map: dict[ArmMode, dict[str, Any]]):
                def mode_times(mode: ArmMode) -> ModeTimes:
                    cfg = cfg_map.get(mode, {})
                    return ModeTimes(
                        exit_delay_s=cfg.get("exit_delay_s", defaults["exit_delay_s"]),
                        entry_delay_s=cfg.get("entry_delay_s", defaults["entry_delay_s"]),
                        trigger_time_s=cfg.get("trigger_time_s", defaults["trigger_time_s"]),
                    )

                return mode_times

            self.fsms[panel_id] = PanelFsm(
                panel_id=panel_id,
                area_id=item["scope"].get("area_id"),
                zones=zones_by_panel.get(panel_id, {}),
                mode_times=make_times(mode_cfg),
                behavior=PanelBehavior(
                    rearm_after_trigger=item["options"]["rearm_after_trigger"],
                    require_explicit_ack=settings["security"]["require_explicit_ack"],
                    disarm_acknowledges=settings["security"]["disarm_acknowledges"],
                ),
                clock=dt_util.utcnow,
                enabled_modes=enabled_modes,
                default_times=default_times,
            )

        self._resubscribe_zones()

    def _resubscribe_zones(self) -> None:
        if self._zone_unsub:
            self._zone_unsub()
            self._zone_unsub = None
        if self._zone_by_entity:
            self._zone_unsub = async_track_state_change_event(
                self._hass, list(self._zone_by_entity), self._on_zone_state
            )

    def _restore_runtime(self) -> None:
        stored = self._storage.runtime.get("panels", {})
        for panel_id, fsm in self.fsms.items():
            if panel_id in stored:
                fx = fsm.restore(stored[panel_id], self._open_zone_ids(panel_id))
                self._apply_effects(panel_id, fx)

    # ------------------------------------------------------------------
    # Zone state handling
    # ------------------------------------------------------------------

    @callback
    def _on_zone_state(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return
        for panel_id, zone_id in self._zone_by_entity.get(entity_id, []):
            fsm = self.fsms.get(panel_id)
            if fsm is None:
                continue
            zone = fsm.zones.get(zone_id)
            if zone is None:
                continue
            if panel_id in self.walk_tests:
                if new_state.state == STATE_ON and (
                    old_state is None or old_state.state != STATE_ON
                ):
                    self.walk_tests[panel_id]["tested"].add(zone_id)
                    payload = {
                        "panel_id": panel_id,
                        ATTR_ZONE_ID: zone_id,
                        ATTR_ENTITY_ID: entity_id,
                    }
                    self._hass.bus.async_fire(EVENT_WALK_TEST_ZONE, payload)
                    self._audit("walk_test_zone", payload)
                    async_dispatcher_send(self._hass, SIGNAL_PANEL_STATE, panel_id)
                continue
            if new_state.state == STATE_UNAVAILABLE:
                self._apply_effects(panel_id, fsm.zone_unavailable(zone_id))
                continue
            was_open = old_state is not None and self._is_open_state(old_state.state)
            is_open = self._is_open_state(new_state.state)
            if is_open and not was_open:
                self._apply_effects(panel_id, fsm.zone_tripped(zone_id))
            elif was_open and not is_open:
                self._apply_effects(
                    panel_id, fsm.zone_closed(zone_id, self._open_zone_ids(panel_id))
                )

    def _is_open_state(self, state: str) -> bool:
        return state == STATE_ON

    def _zone_open(self, entity_id: str) -> bool:
        state = self._hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False
        return self._is_open_state(state.state)

    def _open_zone_ids(self, panel_id: str) -> set[str]:
        fsm = self.fsms.get(panel_id)
        if fsm is None:
            return set()
        return {
            zone_id
            for zone_id, zone in fsm.zones.items()
            if self._zone_open(zone.entity_id)
        }

    # ------------------------------------------------------------------
    # Code validation (M3)
    # ------------------------------------------------------------------

    def panel_title(self, panel_id: str) -> str:
        doc = self.panel_doc(panel_id)
        if doc is None:
            return panel_id
        scope = doc["scope"]
        if scope["type"] == PanelScope.CUSTOM:
            return scope.get("name") or panel_id
        from homeassistant.helpers import area_registry as ar

        area = ar.async_get(self._hass).async_get_area(scope.get("area_id") or "")
        return (area.name if area else None) or scope.get("area_id") or panel_id

    def panel_doc(self, panel_id: str) -> dict[str, Any] | None:
        return next(
            (p for p in self._storage.panels.async_items() if p["id"] == panel_id), None
        )

    def code_required(self, panel_id: str, action: str) -> bool:
        doc = self.panel_doc(panel_id)
        return bool(doc and doc["options"][f"code_{action}_required"])

    def has_pin_users(self) -> bool:
        return any(
            self._storage.pins.get(user["id"])
            for user in self._storage.users.async_items()
            if user["enabled"]
        )

    def _validate_code(
        self, panel_id: str, code: str | None, action: str
    ) -> tuple[dict[str, Any] | None, bool]:
        """Return (user, is_duress); raise ServiceValidationError on failure."""
        if not self.code_required(panel_id, action):
            return None, False
        if not self.has_pin_users():
            # No users configured yet: do not lock the owner out of their own
            # system; the panel simply is not code-protected until M3 setup.
            return None, False
        if not code:
            raise ServiceValidationError("Code erforderlich")
        for user in self._storage.users.async_items():
            if not user["enabled"]:
                continue
            pins = self._storage.pins.get(user["id"], {})
            for kind in ("normal", "duress"):
                record = pins.get(kind)
                if record is None or not verify_pin(code, record):
                    continue
                rights = user["rights"]
                if action == "arm" and not rights["can_arm"]:
                    raise ServiceValidationError("Scharfschalten nicht erlaubt")
                if action == "disarm" and not rights["can_disarm"]:
                    raise ServiceValidationError("Entschärfen nicht erlaubt")
                if rights["panels"] is not None and panel_id not in rights["panels"]:
                    raise ServiceValidationError("Bereich nicht erlaubt")
                if needs_rehash(record):
                    from .auth import hash_pin  # local import avoids cycle

                    pins[kind] = hash_pin(code)
                    self._hass.async_create_task(self._storage.async_save_pins())
                return user, kind == "duress"
        raise ServiceValidationError("Ungültiger Code")

    # ------------------------------------------------------------------
    # Commands (called by entities, services, WS API)
    # ------------------------------------------------------------------

    async def async_arm(
        self,
        panel_id: str,
        mode: ArmMode,
        actor: str,
        force: bool = False,
        skip_delay: bool = False,
        code: str | None = None,
    ) -> ArmResult:
        members = self.resolve_target(panel_id)
        if len(members) != 1 or members[0] != panel_id:
            # Master or group: the UNION counts (user requirement). Members
            # without this mode are skipped; any blocking zone anywhere
            # blocks the whole target so nothing arms half-way.
            armable = [
                pid for pid in members if mode in self.fsms[pid].enabled_modes
            ]
            if not force:
                blocking_union: list[str] = []
                for pid in armable:
                    blocking_union.extend(self.blocking_zones(pid, mode))
                if blocking_union:
                    return ArmResult(
                        False, ArmFailReason.OPEN_ZONES, tuple(blocking_union)
                    )
            result = ArmResult(True)
            for pid in armable:
                result = await self.async_arm(
                    pid, mode, actor, force=force, skip_delay=skip_delay, code=code
                )
                if not result.ok:
                    return result
            return result
        user, _ = self._validate_code(panel_id, code, "arm")
        if user is not None:
            actor = f"user:{user['name']}"
        fsm = self.fsms[panel_id]
        result, fx = fsm.arm(
            mode,
            self._open_zone_ids(panel_id),
            actor,
            force=force,
            skip_delay=skip_delay,
            unavailable_zones=self._unavailable_zone_ids(panel_id),
        )
        self._apply_effects(panel_id, fx)
        return result

    async def async_disarm(
        self, panel_id: str, actor: str, code: str | None = None
    ) -> None:
        members = self.resolve_target(panel_id)
        if len(members) != 1 or members[0] != panel_id:
            for pid in members:
                await self.async_disarm(pid, actor, code=code)
            return
        user, is_duress = self._validate_code(panel_id, code, "disarm")
        if user is not None:
            # Deliberately identical attribution for normal and duress disarm:
            # nothing observable may differ (critique finding 1).
            actor = f"user:{user['name']}"
        fsm = self.fsms[panel_id]
        self._apply_effects(panel_id, fsm.disarm(actor))
        if not actor.startswith("rule:"):
            # Manual precedence: no rule may re-arm during the same trip.
            self.presence.on_manual_disarm(panel_id)
        if is_duress:
            # Audit only; nothing on the bus, nothing observable (finding 1).
            self._audit(
                "duress_disarm", {"panel_id": panel_id, "user": user["name"]}
            )
            await self.engine.async_start(
                panel_id, fsm.area_id, AlarmType.HOLDUP, detached=True
            )

    async def async_acknowledge(self, panel_id: str, actor: str) -> None:
        members = self.resolve_target(panel_id)
        if len(members) != 1 or members[0] != panel_id:
            for pid in members:
                await self.async_acknowledge(pid, actor)
            return
        fsm = self.fsms[panel_id]
        self._apply_effects(panel_id, fsm.acknowledge(actor))
        # Acknowledge also ends a running silent hold-up instance (admin act).
        await self.engine.async_stop_panel(
            panel_id, restore=True, include_detached=True
        )

    def _audit(self, kind: str, data: dict[str, Any]) -> None:
        self._hass.async_create_background_task(
            self.audit.async_append(kind, data), name="kustos_audit"
        )

    def _unavailable_zone_ids(self, panel_id: str) -> set[str]:
        fsm = self.fsms.get(panel_id)
        if fsm is None:
            return set()
        result = set()
        for zone_id, zone in fsm.zones.items():
            state = self._hass.states.get(zone.entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                result.add(zone_id)
        return result

    def blocking_zones(self, panel_id: str, mode: ArmMode) -> list[str]:
        fsm = self.fsms[panel_id]
        return fsm.blocking_zones(
            mode, self._open_zone_ids(panel_id), self._unavailable_zone_ids(panel_id)
        )

    # ------------------------------------------------------------------
    # Walk test (M4): trips are announced and recorded, never alarmed
    # ------------------------------------------------------------------

    async def async_walk_test_start(self, panel_id: str, actor: str) -> None:
        await self.async_walk_test_stop(panel_id, actor="restart")
        timeout = self._storage.setting("defaults", "walk_test_timeout_s")
        ends_at = dt_util.utcnow() + timedelta(seconds=timeout)

        @callback
        def _timeout(_now) -> None:
            self._hass.async_create_background_task(
                self.async_walk_test_stop(panel_id, actor="timeout"),
                name="kustos_walk_timeout",
            )

        self.walk_tests[panel_id] = {
            "ends_at": ends_at.isoformat(),
            "tested": set(),
            "cancel": async_track_point_in_utc_time(self._hass, _timeout, ends_at),
        }
        self._audit("walk_test_started", {"panel_id": panel_id, "actor": actor})
        async_dispatcher_send(self._hass, SIGNAL_PANEL_STATE, panel_id)

    async def async_walk_test_stop(self, panel_id: str, actor: str) -> None:
        info = self.walk_tests.pop(panel_id, None)
        if info is None:
            return
        info["cancel"]()
        self._audit(
            "walk_test_ended",
            {
                "panel_id": panel_id,
                "actor": actor,
                "tested_zones": sorted(info["tested"]),
            },
        )
        async_dispatcher_send(self._hass, SIGNAL_PANEL_STATE, panel_id)

    def zone_entity_ids(self, panel_id: str) -> list[str]:
        fsm = self.fsms.get(panel_id)
        if fsm is None:
            return []
        return [zone.entity_id for zone in fsm.zones.values()]

    # ------------------------------------------------------------------
    # Aggregation: master and panel groups share the same union semantics
    # ------------------------------------------------------------------

    def resolve_target(self, target_id: str) -> list[str]:
        """Master, group id or panel id -> list of member panel ids."""
        if target_id == MASTER_ID:
            return list(self.fsms)
        group = next(
            (g for g in self._storage.groups.async_items() if g["id"] == target_id),
            None,
        )
        if group is not None:
            return [pid for pid in group["panel_ids"] if pid in self.fsms]
        return [target_id] if target_id in self.fsms else []

    def _aggregate(self, panel_ids: list[str]) -> tuple[PanelState, ArmMode | None]:
        states = [
            (self.fsms[pid].state, self.fsms[pid].arm_mode)
            for pid in panel_ids
            if pid in self.fsms
        ]
        if not states:
            return (PanelState.DISARMED, None)
        for severity in (PanelState.TRIGGERED, PanelState.PENDING, PanelState.ARMING):
            for state, mode in states:
                if state is severity:
                    return (severity, mode)
        armed_modes = {mode for state, mode in states if state is PanelState.ARMED}
        if armed_modes and all(state is PanelState.ARMED for state, _ in states):
            if len(armed_modes) == 1:
                return (PanelState.ARMED, next(iter(armed_modes)))
            # Mixed armed modes: report the most restrictive one.
            return (PanelState.ARMED, ArmMode.AWAY)
        return (PanelState.DISARMED, None)

    @property
    def master_state(self) -> tuple[PanelState, ArmMode | None]:
        return self._aggregate(list(self.fsms))

    def group_state(self, group_id: str) -> tuple[PanelState, ArmMode | None]:
        return self._aggregate(self.resolve_target(group_id))

    # ------------------------------------------------------------------
    # Effects
    # ------------------------------------------------------------------

    def _apply_effects(self, panel_id: str, fx: Effects) -> None:
        for event_name, payload in fx.events:
            self._hass.bus.async_fire(event_name, payload)
            self._audit(event_name.removeprefix("kustos_"), dict(payload))
            if event_name == EVENT_TRIGGERED:
                fsm = self.fsms[panel_id]
                self._hass.async_create_task(
                    self.engine.async_start(
                        panel_id, fsm.area_id, payload[ATTR_ALARM_TYPE]
                    )
                )

        if fx.cancel_timer and panel_id in self._timers:
            self._timers.pop(panel_id)()
        if fx.timer_ends_at is not None:
            if panel_id in self._timers:
                self._timers.pop(panel_id)()

            @callback
            def _expired(_now, panel_id=panel_id) -> None:
                self._timers.pop(panel_id, None)
                fsm = self.fsms.get(panel_id)
                if fsm is not None:
                    self._apply_effects(
                        panel_id, fsm.timer_expired(self._open_zone_ids(panel_id))
                    )

            self._timers[panel_id] = async_track_point_in_utc_time(
                self._hass, _expired, fx.timer_ends_at
            )

        if fx.state_changed or fx.critical_save:
            self._storage.runtime.setdefault("panels", {})[panel_id] = self.fsms[
                panel_id
            ].to_dict()
            if fx.critical_save:
                self._hass.async_create_task(self._storage.async_save_runtime())
            else:
                self._storage.delay_save_runtime()
        if fx.state_changed:
            fsm = self.fsms.get(panel_id)
            if (
                not self._restoring
                and fsm is not None
                and fsm.state is not PanelState.TRIGGERED
                and self.engine.has_instances(panel_id)
            ):
                self._hass.async_create_task(
                    self.engine.async_stop_panel(panel_id, restore=True)
                )
            async_dispatcher_send(self._hass, SIGNAL_PANEL_STATE, panel_id)
            async_dispatcher_send(self._hass, SIGNAL_PANEL_STATE, MASTER_ID)

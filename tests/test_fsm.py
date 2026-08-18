"""Unit tests for the pure panel state machine (no Home Assistant needed)."""
from datetime import UTC, datetime, timedelta

from custom_components.kustos.const import (
    AlarmType,
    ArmFailReason,
    ArmMode,
    ZoneRole,
    EVENT_ACKNOWLEDGED,
    EVENT_ARM_FAILED,
    EVENT_ARMED,
    EVENT_ARMING,
    EVENT_DISARMED,
    EVENT_PENDING,
    EVENT_TRIGGERED,
    EVENT_ZONE_BYPASSED,
)
from custom_components.kustos.core.fsm import (
    Effects,
    ModeTimes,
    PanelBehavior,
    PanelFsm,
    PanelState,
    ZoneConfig,
)

T0 = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


def zone(zone_id, role=ZoneRole.INSTANT, alarm_type=AlarmType.BURGLARY, **options):
    return ZoneConfig(
        zone_id=zone_id,
        entity_id=f"binary_sensor.{zone_id}",
        alarm_type=alarm_type,
        modes={ArmMode.AWAY: role},
        **options,
    )


def make_fsm(
    zones,
    clock,
    exit_s=30.0,
    entry_s=15.0,
    trigger_s=120.0,
    rearm=True,
    require_ack=True,
    disarm_acks=False,
):
    times = ModeTimes(exit_delay_s=exit_s, entry_delay_s=entry_s, trigger_time_s=trigger_s)
    return PanelFsm(
        panel_id="P1",
        area_id="wohnzimmer",
        zones={z.zone_id: z for z in zones},
        mode_times=lambda mode: times,
        behavior=PanelBehavior(
            rearm_after_trigger=rearm,
            require_explicit_ack=require_ack,
            disarm_acknowledges=disarm_acks,
        ),
        clock=clock,
        enabled_modes=frozenset({ArmMode.AWAY}),
        default_times=times,
    )


def event_names(fx: Effects):
    return [name for name, _ in fx.events]


# ---------------------------------------------------------------------------
# Arming
# ---------------------------------------------------------------------------

def test_arm_without_exit_delay_arms_immediately():
    clock = Clock()
    fsm = make_fsm([zone("tuer")], clock, exit_s=0)
    result, fx = fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    assert result.ok
    assert fsm.state is PanelState.ARMED
    assert event_names(fx) == [EVENT_ARMED]
    assert fx.critical_save


def test_arm_with_exit_delay_sets_absolute_deadline():
    clock = Clock()
    fsm = make_fsm([zone("tuer")], clock, exit_s=30)
    result, fx = fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    assert result.ok
    assert fsm.state is PanelState.ARMING
    assert fsm.ends_at == T0 + timedelta(seconds=30)
    assert fx.timer_ends_at == fsm.ends_at
    assert event_names(fx) == [EVENT_ARMING]

    clock.advance(30)
    fx = fsm.timer_expired(open_zones=set())
    assert fsm.state is PanelState.ARMED
    assert event_names(fx) == [EVENT_ARMED]


def test_open_zone_blocks_arming_and_names_the_zone():
    clock = Clock()
    fsm = make_fsm([zone("fenster")], clock)
    result, fx = fsm.arm(ArmMode.AWAY, open_zones={"fenster"}, actor="test")
    assert not result.ok
    assert result.reason is ArmFailReason.OPEN_ZONES
    assert result.open_zones == ("fenster",)
    assert fsm.state is PanelState.DISARMED
    assert event_names(fx) == [EVENT_ARM_FAILED]


def test_auto_bypass_zone_does_not_block_and_is_ignored_afterwards():
    clock = Clock()
    fsm = make_fsm([zone("fenster", auto_bypass=True)], clock, exit_s=0)
    result, fx = fsm.arm(ArmMode.AWAY, open_zones={"fenster"}, actor="test")
    assert result.ok
    assert fsm.bypassed_zones == {"fenster"}
    assert EVENT_ZONE_BYPASSED in event_names(fx)
    # A bypassed zone never triggers.
    fx = fsm.zone_tripped("fenster")
    assert fsm.state is PanelState.ARMED
    assert fx.events == []


def test_force_arm_bypasses_open_zones():
    clock = Clock()
    fsm = make_fsm([zone("fenster")], clock, exit_s=0)
    result, _ = fsm.arm(ArmMode.AWAY, open_zones={"fenster"}, actor="test", force=True)
    assert result.ok
    assert fsm.bypassed_zones == {"fenster"}


def test_allow_open_zone_never_blocks_but_new_trip_triggers():
    clock = Clock()
    fsm = make_fsm([zone("tor", allow_open=True)], clock, exit_s=0)
    result, _ = fsm.arm(ArmMode.AWAY, open_zones={"tor"}, actor="test")
    assert result.ok
    assert fsm.bypassed_zones == set()
    fx = fsm.zone_tripped("tor")
    assert fsm.state is PanelState.TRIGGERED
    assert EVENT_TRIGGERED in event_names(fx)


def test_exit_delay_zone_open_while_leaving_then_still_open_goes_pending():
    clock = Clock()
    fsm = make_fsm(
        [zone("haustuer", role=ZoneRole.DELAYED, use_exit_delay=True)], clock, exit_s=30
    )
    result, _ = fsm.arm(ArmMode.AWAY, open_zones={"haustuer"}, actor="test")
    assert result.ok

    clock.advance(30)
    fx = fsm.timer_expired(open_zones={"haustuer"})
    # Armed first, then the still-open delayed zone starts the entry countdown.
    assert event_names(fx) == [EVENT_ARMED, EVENT_PENDING]
    assert fsm.state is PanelState.PENDING


def test_arm_after_closing_completes_exit_delay_early():
    clock = Clock()
    fsm = make_fsm(
        [zone("haustuer", role=ZoneRole.DELAYED, use_exit_delay=True, arm_after_closing=True)],
        clock,
        exit_s=60,
    )
    fsm.arm(ArmMode.AWAY, open_zones={"haustuer"}, actor="test")
    clock.advance(5)
    fx = fsm.zone_closed("haustuer", open_zones=set())
    assert fsm.state is PanelState.ARMED
    assert EVENT_ARMED in event_names(fx)


def test_arm_rejected_while_pending_and_for_disabled_mode():
    clock = Clock()
    fsm = make_fsm([zone("tuer", role=ZoneRole.DELAYED)], clock, exit_s=0)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("tuer")
    assert fsm.state is PanelState.PENDING
    result, _ = fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    assert result.reason is ArmFailReason.NOT_ALLOWED

    fsm2 = make_fsm([zone("tuer")], clock, exit_s=0)
    result, _ = fsm2.arm(ArmMode.HOME, open_zones=set(), actor="test")
    assert result.reason is ArmFailReason.MODE_DISABLED


# ---------------------------------------------------------------------------
# Trips, entry delay, trigger
# ---------------------------------------------------------------------------

def test_delayed_zone_starts_entry_delay_then_triggers():
    clock = Clock()
    fsm = make_fsm([zone("haustuer", role=ZoneRole.DELAYED)], clock, exit_s=0, entry_s=15)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fx = fsm.zone_tripped("haustuer")
    assert fsm.state is PanelState.PENDING
    assert fsm.ends_at == clock() + timedelta(seconds=15)
    assert event_names(fx) == [EVENT_PENDING]

    clock.advance(15)
    fx = fsm.timer_expired(open_zones=set())
    assert fsm.state is PanelState.TRIGGERED
    assert event_names(fx) == [EVENT_TRIGGERED]
    assert fsm.alarm_memory[0]["zone_id"] == "haustuer"
    assert fsm.active_alarm_types == {AlarmType.BURGLARY}


def test_instant_zone_during_pending_triggers_immediately():
    clock = Clock()
    fsm = make_fsm(
        [zone("haustuer", role=ZoneRole.DELAYED), zone("fenster", role=ZoneRole.INSTANT)],
        clock,
        exit_s=0,
    )
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("haustuer")
    fx = fsm.zone_tripped("fenster")
    assert fsm.state is PanelState.TRIGGERED
    assert EVENT_TRIGGERED in event_names(fx)


def test_follower_triggers_when_armed_but_follows_running_entry_delay():
    clock = Clock()
    fsm = make_fsm(
        [zone("haustuer", role=ZoneRole.DELAYED), zone("flur", role=ZoneRole.FOLLOWER)],
        clock,
        exit_s=0,
    )
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("haustuer")
    fx = fsm.zone_tripped("flur")  # follows, no instant trigger
    assert fsm.state is PanelState.PENDING
    assert fx.events == []

    fsm2 = make_fsm([zone("flur", role=ZoneRole.FOLLOWER)], clock, exit_s=0)
    fsm2.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm2.zone_tripped("flur")  # without entry delay running: instant
    assert fsm2.state is PanelState.TRIGGERED


def test_instant_zone_during_exit_delay_is_a_breach():
    clock = Clock()
    fsm = make_fsm(
        [zone("fenster"), zone("haustuer", role=ZoneRole.DELAYED, use_exit_delay=True)],
        clock,
        exit_s=30,
    )
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("haustuer")  # expected while leaving
    assert fsm.state is PanelState.ARMING
    fsm.zone_tripped("fenster")  # a window opening now is real
    assert fsm.state is PanelState.TRIGGERED


def test_always_on_fire_zone_triggers_while_disarmed():
    clock = Clock()
    fsm = make_fsm([zone("rauch", alarm_type=AlarmType.FIRE)], clock)
    fx = fsm.zone_tripped("rauch")
    assert fsm.state is PanelState.TRIGGERED
    assert fsm.active_alarm_types == {AlarmType.FIRE}
    assert EVENT_TRIGGERED in event_names(fx)


def test_second_trip_while_triggered_lands_in_memory_once():
    clock = Clock()
    fsm = make_fsm([zone("a"), zone("b")], clock, exit_s=0)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("a")
    fsm.zone_tripped("b")
    fsm.zone_tripped("b")
    assert [m["zone_id"] for m in fsm.alarm_memory] == ["a", "b"]


def test_unavailable_zone_triggers_only_with_option():
    clock = Clock()
    fsm = make_fsm(
        [zone("a"), zone("b", trigger_when_unavailable=True)], clock, exit_s=0
    )
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_unavailable("a")
    assert fsm.state is PanelState.ARMED
    fsm.zone_unavailable("b")
    assert fsm.state is PanelState.TRIGGERED


# ---------------------------------------------------------------------------
# Trigger time, rearm, acknowledge, disarm
# ---------------------------------------------------------------------------

def test_trigger_time_expiry_rearms_and_bypasses_still_open_zone():
    clock = Clock()
    fsm = make_fsm([zone("fenster")], clock, exit_s=0, trigger_s=120, rearm=True)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("fenster")
    assert fsm.ends_at == clock() + timedelta(seconds=120)

    clock.advance(120)
    fx = fsm.timer_expired(open_zones={"fenster"})  # window is broken open
    assert fsm.state is PanelState.ARMED
    assert fsm.bypassed_zones == {"fenster"}
    assert event_names(fx) == [EVENT_ZONE_BYPASSED, EVENT_ARMED]
    # Memory stays until acknowledged.
    assert fsm.alarm_memory
    assert fsm.active_alarm_types == set()


def test_trigger_time_expiry_without_rearm_disarms():
    clock = Clock()
    fsm = make_fsm([zone("fenster")], clock, exit_s=0, rearm=False)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("fenster")
    clock.advance(120)
    fx = fsm.timer_expired(open_zones=set())
    assert fsm.state is PanelState.DISARMED
    assert EVENT_DISARMED in event_names(fx)


def test_trigger_time_zero_means_no_automatic_end():
    clock = Clock()
    fsm = make_fsm([zone("fenster")], clock, exit_s=0, trigger_s=0)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fx = fsm.zone_tripped("fenster")
    assert fsm.state is PanelState.TRIGGERED
    assert fsm.ends_at is None
    assert fx.timer_ends_at is None


def test_disarm_keeps_memory_until_acknowledge_by_default():
    clock = Clock()
    fsm = make_fsm([zone("fenster")], clock, exit_s=0)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("fenster")
    fx = fsm.disarm(actor="dustin")
    assert fsm.state is PanelState.DISARMED
    assert fsm.alarm_memory  # still there
    assert fsm.bypassed_zones == set()  # bypass lasts one cycle
    assert EVENT_DISARMED in event_names(fx)

    fx = fsm.acknowledge(actor="dustin")
    assert fsm.alarm_memory == []
    assert EVENT_ACKNOWLEDGED in event_names(fx)


def test_disarm_acknowledges_when_configured():
    clock = Clock()
    fsm = make_fsm([zone("fenster")], clock, exit_s=0, disarm_acks=True)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("fenster")
    fsm.disarm(actor="dustin")
    assert fsm.alarm_memory == []


def test_disarm_during_pending_prevents_alarm():
    clock = Clock()
    fsm = make_fsm([zone("haustuer", role=ZoneRole.DELAYED)], clock, exit_s=0)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("haustuer")
    fsm.disarm(actor="dustin")
    assert fsm.state is PanelState.DISARMED
    assert fsm.alarm_memory == []  # never triggered


# ---------------------------------------------------------------------------
# Restore after restart
# ---------------------------------------------------------------------------

def test_restore_reschedules_remaining_delay():
    clock = Clock()
    fsm = make_fsm([zone("haustuer", role=ZoneRole.DELAYED)], clock, exit_s=0)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("haustuer")
    saved = fsm.to_dict()

    clock2 = Clock()
    clock2.now = T0 + timedelta(seconds=5)  # restart 5 s into the 15 s delay
    fsm2 = make_fsm([zone("haustuer", role=ZoneRole.DELAYED)], clock2, exit_s=0)
    fx = fsm2.restore(saved, open_zones=set())
    assert fsm2.state is PanelState.PENDING
    assert fx.timer_ends_at == fsm.ends_at  # original absolute deadline


def test_restore_catches_up_expired_pending_as_triggered():
    clock = Clock()
    fsm = make_fsm([zone("haustuer", role=ZoneRole.DELAYED)], clock, exit_s=0)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("haustuer")
    saved = fsm.to_dict()

    clock2 = Clock()
    clock2.now = T0 + timedelta(seconds=600)  # HA was down past the deadline
    fsm2 = make_fsm([zone("haustuer", role=ZoneRole.DELAYED)], clock2, exit_s=0)
    fx = fsm2.restore(saved, open_zones=set())
    assert fsm2.state is PanelState.TRIGGERED
    assert EVENT_TRIGGERED in event_names(fx)


def test_runtime_roundtrip_is_lossless():
    clock = Clock()
    fsm = make_fsm([zone("fenster")], clock, exit_s=0)
    fsm.arm(ArmMode.AWAY, open_zones=set(), actor="test")
    fsm.zone_tripped("fenster")
    saved = fsm.to_dict()

    fsm2 = make_fsm([zone("fenster")], clock, exit_s=0)
    fsm2.restore(saved, open_zones=set())
    assert fsm2.to_dict() == saved

"""Reaction engine tests: blocks, snapshots, teardown order, resume, claims."""
import asyncio

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.kustos.const import DOMAIN, STORAGE_KEY_SNAPSHOTS

ZONE = "input_boolean.kustos_zone"
LIGHT = "light.wohnzimmer"


async def _setup(hass, profile_stages, alarm_type="burglary", zone_type="burglary"):
    entry = MockConfigEntry(domain=DOMAIN, title="Kustos")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    storage = entry.runtime_data.storage
    profile = await storage.profiles.async_create_item(
        {"name": "Test", "stages": profile_stages}
    )
    panel = await storage.panels.async_create_item(
        {
            "scope": {"type": "area", "area_id": "test"},
            "modes": {
                "armed_away": {
                    "enabled": True,
                    "exit_delay_s": 0.0,
                    "entry_delay_s": 0.0,
                    "trigger_time_s": 0.0,
                }
            },
            "alarm_types": {alarm_type: {"profile_id": profile["id"]}},
        }
    )
    await hass.async_block_till_done()
    storage = entry.runtime_data.storage
    await storage.zones.async_create_item(
        {
            "entity_id": ZONE,
            "panel_id": panel["id"],
            "alarm_type": zone_type,
            "modes": {"armed_away": "instant"},
        }
    )
    await hass.async_block_till_done()
    return entry, panel["id"]


def _panel_entity(hass):
    return next(
        eid
        for eid in hass.states.async_entity_ids("alarm_control_panel")
        if hass.states.get(eid).attributes.get("panel_id")
    )


async def _arm_and_trip(hass, always_on=False):
    hass.states.async_set(ZONE, "off")
    await hass.async_block_till_done()
    if not always_on:
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_away",
            {"entity_id": _panel_entity(hass)},
            blocking=True,
        )
        await hass.async_block_till_done()
    hass.states.async_set(ZONE, "on")
    await hass.async_block_till_done()


async def _disarm(hass):
    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_disarm",
        {"entity_id": _panel_entity(hass)},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_flash_snapshot_and_exact_restore(hass, hass_storage):
    entry, _ = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {
                        "type": "flash_lights",
                        "targets": [LIGHT],
                        "period_s": 0.2,
                        "fade_s": 0,
                    }
                ],
            }
        ],
    )
    turn_on = async_mock_service(hass, "light", "turn_on")
    turn_off = async_mock_service(hass, "light", "turn_off")
    hass.states.async_set(
        LIGHT,
        "on",
        {"supported_color_modes": ["hs"], "brightness": 120, "hs_color": [30.0, 40.0]},
    )

    await _arm_and_trip(hass)
    await asyncio.sleep(0.25)
    await hass.async_block_till_done()

    # Blink commands went out with the alarm color.
    assert any(c.data.get("rgb_color") == [255, 0, 0] for c in turn_on)
    # Write-ahead: the snapshot is persisted while the alarm runs.
    assert LIGHT in hass_storage[STORAGE_KEY_SNAPSHOTS]["data"]
    snap = hass_storage[STORAGE_KEY_SNAPSHOTS]["data"][LIGHT]
    assert snap["attributes"]["brightness"] == 120

    turn_on.clear()
    await _disarm(hass)
    await hass.async_block_till_done()

    # Exact restore: original brightness and color, no alarm red.
    restore_calls = [c for c in turn_on if "rgb_color" not in c.data]
    assert restore_calls, turn_on
    assert restore_calls[-1].data["brightness"] == 120
    assert restore_calls[-1].data["hs_color"] == [30.0, 40.0]
    # Snapshot fully released.
    assert hass_storage[STORAGE_KEY_SNAPSHOTS]["data"] == {}


async def test_sound_switch_respects_max_duration(hass):
    entry, _ = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {
                        "type": "sound",
                        "targets": ["switch.sirene"],
                        "max_duration_s": 0.2,
                        "retrigger_interval_s": 0.1,
                    }
                ],
            }
        ],
    )
    on = async_mock_service(hass, "switch", "turn_on")
    off = async_mock_service(hass, "switch", "turn_off")
    hass.states.async_set("switch.sirene", "off")

    await _arm_and_trip(hass)
    await asyncio.sleep(0.35)
    await hass.async_block_till_done()
    assert len(on) == 1
    assert off, "max_duration_s must switch the sounder off"
    await _disarm(hass)


async def test_sound_button_retriggers(hass):
    entry, _ = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {
                        "type": "sound",
                        "targets": ["input_button.rauchmelder"],
                        "max_duration_s": 10.0,
                        "retrigger_interval_s": 0.1,
                    }
                ],
            }
        ],
    )
    press = async_mock_service(hass, "input_button", "press")
    await _arm_and_trip(hass)
    await asyncio.sleep(0.35)
    await hass.async_block_till_done()
    assert len(press) >= 3, "button sounder must be retriggered on the interval"
    await _disarm(hass)


async def test_announce_teardown_uses_fallback_volume(hass):
    entry, _ = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {
                        "type": "announce_loop",
                        "notify_service": "notify.testecho",
                        "message": "Achtung",
                        "interval_s": 0.2,
                        "media_targets": ["media_player.echo"],
                        "volume_pct": 100,
                        "volume_fallback_pct": 30,
                    }
                ],
            }
        ],
    )
    notify = async_mock_service(hass, "notify", "testecho")
    volume = async_mock_service(hass, "media_player", "volume_set")
    stop = async_mock_service(hass, "media_player", "media_stop")
    # Echo pattern: volume_level is not readable while idle.
    hass.states.async_set("media_player.echo", "idle", {})

    await _arm_and_trip(hass)
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()
    assert notify, "announcement loop must fire"
    assert volume[0].data["volume_level"] == 1.0  # alarm volume

    await _disarm(hass)
    await hass.async_block_till_done()
    assert stop, "teardown must stop running announcements"
    assert volume[-1].data["volume_level"] == 0.3  # fallback, not 100 %


async def test_silent_holdup_strips_perceivable_blocks(hass):
    entry, _ = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {"type": "flash_lights", "targets": [LIGHT], "period_s": 0.2},
                    {"type": "notify", "service": "notify.still", "message": "Duress"},
                ],
            }
        ],
        alarm_type="holdup",
        zone_type="holdup",
    )
    turn_on = async_mock_service(hass, "light", "turn_on")
    notify = async_mock_service(hass, "notify", "still")
    hass.states.async_set(LIGHT, "on", {"supported_color_modes": ["hs"]})

    await _arm_and_trip(hass)
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()
    assert notify, "silent alarm still notifies"
    assert not turn_on, "silent alarm must never touch lights"
    await _disarm(hass)


async def test_unlock_refused_for_burglary_allowed_for_fire(hass):
    entry, _ = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {"type": "lock", "targets": ["lock.haustuer"], "action": "unlock"}
                ],
            }
        ],
        alarm_type="burglary",
        zone_type="burglary",
    )
    unlock = async_mock_service(hass, "lock", "unlock")
    await _arm_and_trip(hass)
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    assert not unlock, "burglary must never unlock doors"
    await _disarm(hass)


async def test_unlock_allowed_for_fire(hass):
    entry, _ = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {"type": "lock", "targets": ["lock.haustuer"], "action": "unlock"}
                ],
            }
        ],
        alarm_type="fire",
        zone_type="fire",
    )
    unlock = async_mock_service(hass, "lock", "unlock")
    # Fire zones are 24/7: no arming needed.
    await _arm_and_trip(hass, always_on=True)
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()
    assert unlock, "fire must unlock the escape route"
    await _disarm(hass)


async def test_resume_after_reload_continues_and_restores(hass, hass_storage):
    entry, _ = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {
                        "type": "flash_lights",
                        "targets": [LIGHT],
                        "period_s": 0.2,
                        "fade_s": 0,
                    }
                ],
            }
        ],
    )
    turn_on = async_mock_service(hass, "light", "turn_on")
    hass.states.async_set(
        LIGHT, "on", {"supported_color_modes": ["hs"], "brightness": 99}
    )
    await _arm_and_trip(hass)
    await asyncio.sleep(0.25)
    await hass.async_block_till_done()
    assert turn_on

    # Simulated restart mid-alarm.
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    turn_on.clear()
    await asyncio.sleep(0.3)
    await hass.async_block_till_done()
    assert any(
        c.data.get("rgb_color") == [255, 0, 0] for c in turn_on
    ), "flash loop must resume after restart"

    turn_on.clear()
    await _disarm(hass)
    await hass.async_block_till_done()
    restore_calls = [c for c in turn_on if "rgb_color" not in c.data]
    assert restore_calls and restore_calls[-1].data["brightness"] == 99


async def test_notify_multi_target_placeholders_critical_and_ack(hass):
    """Push an mehrere Ziele, Platzhalter gefuellt, kritisch, Quittieren-Knopf."""
    entry, panel_id = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {
                        "type": "notify",
                        "services": ["notify.handy_dustin", "notify.handy_petra"],
                        "title": "Alarm in {bereich}",
                        "message": "{alarmtyp}: {sensoren}",
                        "critical": True,
                        "ack_action": True,
                    }
                ],
            }
        ],
    )
    n1 = async_mock_service(hass, "notify", "handy_dustin")
    n2 = async_mock_service(hass, "notify", "handy_petra")
    await _arm_and_trip(hass)
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    assert n1 and n2, "beide Ziele muessen beliefert werden"
    call = n1[0].data
    assert "Einbruch" in call["message"]
    assert ZONE in call["message"] or "kustos_zone" in call["message"]
    assert "test" in call["title"]  # {bereich} = Panel-Titel (custom/area)
    assert call["data"]["push"]["sound"]["critical"] == 1
    assert call["data"]["priority"] == "high"
    action = call["data"]["actions"][0]
    assert action["title"] == "Quittieren"

    # Quittieren-Knopf gedrueckt: Alarmspeicher wird geleert.
    panel = _panel_entity(hass)
    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {"entity_id": panel}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(panel).attributes["alarm_memory"]
    hass.bus.async_fire("mobile_app_notification_action", {"action": action["action"]})
    await hass.async_block_till_done()
    assert hass.states.get(panel).attributes["alarm_memory"] == []


async def test_script_block_runs_with_context_and_stops_on_disarm(hass):
    entry, panel_id = await _setup(
        hass,
        [
            {
                "duration_s": None,
                "blocks": [
                    {
                        "type": "script",
                        "targets": ["script.alarm_sonderfall"],
                        "stop_on_end": True,
                    }
                ],
            }
        ],
    )
    turn_on = async_mock_service(hass, "script", "turn_on")
    turn_off = async_mock_service(hass, "script", "turn_off")
    await _arm_and_trip(hass)
    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    assert turn_on, "Skript muss gestartet werden"
    variables = turn_on[0].data["variables"]["kustos"]
    assert variables["alarmtyp"] == "burglary"
    assert ZONE in variables["sensoren"]
    assert variables["bereich"]

    await _disarm(hass)
    await hass.async_block_till_done()
    assert turn_off, "stop_on_end muss das Skript beim Entschaerfen abbrechen"

# Kustos

Custom alarm system integration for Home Assistant with its own sidebar panel.

Kustos binds alarm panels directly to Home Assistant areas, treats alarm types
(burglary, fire, water, CO, tamper, hold-up, panic, technical) as first-class
events with their own reaction chains, and persists running alarms across
restarts, including exact snapshot/restore of every entity it touched.

**Status: pre-release (0.5.x). Core, reaction engine, users/PINs, operations
and presence are implemented and tested; UI is a minimal functional panel.**

## What works today

- **Panels bound to HA areas** with per-mode delays, trigger time, master
  aggregation; running delays survive restarts as absolute UTC deadlines and
  missed deadlines are caught up fail-secure after boot.
- **Zones with per-mode roles** (instant/delayed/follower/inactive), exit-delay
  traffic, arm-after-closing, allow-open, auto-bypass, unavailable policies
  (ignore/block/bypass), 24/7 safety zones derived from the alarm type.
- **Reaction engine**: profiles with 1-3 timeline stages; blocks for flashing
  lights (with exact snapshot/restore), steady lights with refresh, three
  sounder flavours (siren, switch, stateless button with retrigger interval),
  repeating announcements with volume fallback, notifications, locks (unlock
  restricted to life-safety alarm types). Write-ahead snapshots make a restart
  mid-alarm fully recoverable; silent alarm types structurally lose every
  locally perceivable block.
- **Users**: scrypt-hashed PINs in a private store, per-user rights, duress
  PIN that disarms normally on the outside and starts a detached silent
  hold-up chain, code enforcement on the panel entities.
- **Operations**: append-only monthly audit log (JSONL) independent of the
  recorder, walk-test mode with timeout, ready sensor with blocking zones.
- **Presence**: per-person state machine with away hysteresis (confirmed away
  by distance or sustained absence, return only counts within the same trip),
  auto-arm with prewarn, auto-disarm blocked during pending/triggered, manual
  disarm suppresses re-arming for the running trip.
- **Alarmo import** (preparation): translates an `alarmo_storage` data blob
  into panels, zones and users with a detailed report; PINs and Alarmo
  automations are deliberately not migrated.

## Development

- Backend: `custom_components/kustos/`; panel: buildless vanilla web component
  (`custom_components/kustos/frontend/`), proper Lit/TS toolchain planned.
- Tests: `tests/` (pytest + pytest-homeassistant-custom-component). Every bug
  fix ships with a regression test. CI runs the suite on every push.

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

Note: keep the venv on a local disk; a network share slows pip down brutally.

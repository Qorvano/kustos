# Kustos

Custom alarm system integration for Home Assistant with its own sidebar panel.

Kustos binds alarm panels directly to Home Assistant areas, treats alarm types
(burglary, fire, water, CO, tamper, hold-up, panic, technical) as first-class
events with their own reaction chains, and persists running alarms across
restarts, including exact snapshot/restore of every entity it touched.

**Status: early development (milestone M1: core state machine). Not ready for use.**

## Development

- Backend: `custom_components/kustos/`
- Tests: `tests/` (pytest + pytest-homeassistant-custom-component). Every bug fix
  ships with a regression test in `tests/test_regressions.py`.

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

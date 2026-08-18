"""Sidebar panel registration.

M1 ships a buildless vanilla-JS web component (no npm toolchain yet); the
Lit + TypeScript + Vite setup from the architecture lands with M2. The
panel is a pure projection of the WebSocket API: deleting this module must
never cost functionality (hard acceptance criterion).
"""
from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN


async def async_register_panel(hass: HomeAssistant) -> None:
    """Register static assets and the sidebar panel (once per HA run)."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}-frontend",
                str(Path(__file__).parent / "frontend"),
                cache_headers=False,  # dev phase; content-hashing comes with the build
            )
        ]
    )
    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="kustos-panel",
        frontend_url_path=DOMAIN,
        module_url=f"/{DOMAIN}-frontend/panel.js?v={integration.version}",
        sidebar_title="Kustos",
        sidebar_icon="mdi:shield-home",
        require_admin=True,
    )

"""Config flow: a single hub instance; configuration happens in the panel."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class KustosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the one Kustos hub entry ("single_config_entry" in manifest)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Kustos", data={})
        return self.async_show_form(step_id="user")

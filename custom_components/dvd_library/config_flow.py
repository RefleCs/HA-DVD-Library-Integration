from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_OMDB_API_KEY

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_OMDB_API_KEY): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the DVD Library integration."""
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=_STEP_USER_SCHEMA)

        # Single instance for now
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title="DVD Library", data=user_input)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for an existing config entry."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_OMDB_API_KEY,
                    default=self._entry.options.get(
                        CONF_OMDB_API_KEY, self._entry.data.get(CONF_OMDB_API_KEY, "")
                    ),
                ): str
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_NAME,
    CONF_BILLING_START_DAY,
    CONF_SITE_ID,
    CONF_SITE_IDS,
    CONF_SUBSCRIPTION,
    CONF_SURCHARGE_CENTS,
    CONF_TOKEN,
    DEFAULT_NAME,
    DEFAULT_SUBSCRIPTION,
    DEFAULT_SURCHARGE_CENTS,
    SURCHARGE_MIN_CENTS,
    SURCHARGE_MAX_CENTS,
    SUBSCRIPTION_MIN,
    SUBSCRIPTION_MAX,
    DEFAULT_BILLING_START_DAY,
    MAX_BILLING_START_DAY,
    MIN_BILLING_START_DAY,
    DOMAIN,
)
from .sensor import AmberApi


async def _discover_sites(hass: HomeAssistant, token: str) -> list[str]:
    session = async_get_clientsession(hass)
    return await AmberApi.discover_sites(session, token)


class AmberBalanceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return AmberBalanceOptionsFlow()

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                site_ids = await _discover_sites(self.hass, user_input[CONF_TOKEN])
                if not site_ids:
                    errors["base"] = "no_site"
                else:
                    user_input[CONF_SITE_IDS] = site_ids
                    user_input[CONF_SITE_ID] = site_ids[0]
            except Exception:
                errors["base"] = "auth"
            else:
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or DEFAULT_NAME, data=user_input
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN): str,
                vol.Optional(CONF_SITE_ID): str,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Optional(
                    CONF_BILLING_START_DAY, default=DEFAULT_BILLING_START_DAY
                ): vol.All(int, vol.Range(min=MIN_BILLING_START_DAY, max=MAX_BILLING_START_DAY)),
                vol.Optional(
                    CONF_SURCHARGE_CENTS, default=DEFAULT_SURCHARGE_CENTS
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=SURCHARGE_MIN_CENTS, max=SURCHARGE_MAX_CENTS),
                ),
                vol.Optional(
                    CONF_SUBSCRIPTION, default=DEFAULT_SUBSCRIPTION
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=SUBSCRIPTION_MIN, max=SUBSCRIPTION_MAX),
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class AmberBalanceOptionsFlow(config_entries.OptionsFlow):

    async def async_step_init(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            # Get current token (from options or data)
            current_token = self.config_entry.options.get(
                CONF_TOKEN, self.config_entry.data.get(CONF_TOKEN, "")
            )
            
            # Validate token if it was changed
            if user_input.get(CONF_TOKEN) != current_token:
                try:
                    site_ids = await _discover_sites(self.hass, user_input[CONF_TOKEN])
                    if not site_ids:
                        errors["base"] = "no_site"
                    else:
                        # Update data with new token
                        new_data = {**self.config_entry.data, CONF_TOKEN: user_input[CONF_TOKEN]}
                        self.hass.config_entries.async_update_entry(
                            self.config_entry, data=new_data
                        )
                except Exception:
                    errors["base"] = "auth"
            
            if not errors:
                # Update options
                return self.async_create_entry(title="", data=user_input)

        # Get current values from options first, then fall back to data
        current_token = self.config_entry.options.get(
            CONF_TOKEN, self.config_entry.data.get(CONF_TOKEN, "")
        )
        current_surcharge = self.config_entry.options.get(
            CONF_SURCHARGE_CENTS, 
            self.config_entry.data.get(CONF_SURCHARGE_CENTS, DEFAULT_SURCHARGE_CENTS)
        )
        current_subscription = self.config_entry.options.get(
            CONF_SUBSCRIPTION,
            self.config_entry.data.get(CONF_SUBSCRIPTION, DEFAULT_SUBSCRIPTION)
        )
        current_billing_start = self.config_entry.options.get(
            CONF_BILLING_START_DAY,
            self.config_entry.data.get(CONF_BILLING_START_DAY, DEFAULT_BILLING_START_DAY),
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_TOKEN, default=current_token): str,
                vol.Optional(
                    CONF_BILLING_START_DAY, default=current_billing_start
                ): vol.All(int, vol.Range(min=MIN_BILLING_START_DAY, max=MAX_BILLING_START_DAY)),
                vol.Optional(
                    CONF_SURCHARGE_CENTS, default=current_surcharge
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=SURCHARGE_MIN_CENTS, max=SURCHARGE_MAX_CENTS),
                ),
                vol.Optional(
                    CONF_SUBSCRIPTION, default=current_subscription
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=SUBSCRIPTION_MIN, max=SUBSCRIPTION_MAX),
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

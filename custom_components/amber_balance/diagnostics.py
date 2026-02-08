"""Diagnostics support for Amber Balance."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_SITE_ID, CONF_SITE_IDS, CONF_TOKEN
from .sensor import AmberApi

TO_REDACT = {
    CONF_TOKEN,
    "id",
    "nmi",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    diagnostics_data = {
        "config_entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": async_redact_data(entry.options, TO_REDACT),
        },
        "sites": [],
    }

    # Get site information from API
    session = async_get_clientsession(hass)
    token = entry.options.get(CONF_TOKEN, entry.data.get(CONF_TOKEN))
    site_ids = entry.data.get(CONF_SITE_IDS) or []
    if not site_ids and entry.data.get(CONF_SITE_ID):
        site_ids = [entry.data[CONF_SITE_ID]]

    for site_id in site_ids:
        try:
            api = AmberApi(session, token, site_id)
            site_info = await api.fetch_site_info()
            diagnostics_data["sites"].append({
                "site_info": async_redact_data(site_info, TO_REDACT)
            })
        except Exception as err:
            diagnostics_data["sites"].append({
                "site_id": site_id[:6] + "...",
                "error": str(err)
            })

    return diagnostics_data

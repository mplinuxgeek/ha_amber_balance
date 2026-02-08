"""Amber Balance custom component."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

PLATFORMS = ["sensor", "number", "button"]


async def async_setup(hass: HomeAssistant, config: dict):
    # Platform setup via config entries or YAML sensor platform
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    # Only add update listener if not already added
    if not entry.update_listeners:
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    # Load sensor platform first so it can populate shared coordinators before dependants
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    # Forward remaining platforms after sensors are initialised
    await hass.config_entries.async_forward_entry_setups(entry, ["number", "button"])
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload the config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data = hass.data.get(DOMAIN)
        if domain_data and entry.entry_id in domain_data:
            domain_data.pop(entry.entry_id)
            if not domain_data:
                hass.data.pop(DOMAIN, None)
    return unload_ok

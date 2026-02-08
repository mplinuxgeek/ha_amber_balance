"""Number platform for Amber Balance."""
from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.components.number import NumberEntity, NumberMode
except ImportError:  # pragma: no cover - older HA versions
    from homeassistant.components.number import NumberEntity

    class NumberMode:  # type: ignore[too-many-ancestors]
        BOX = None
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import (
    CONF_NAME,
    CONF_SUBSCRIPTION,
    CONF_SURCHARGE_CENTS,
    DEFAULT_NAME,
    DEFAULT_SUBSCRIPTION,
    DEFAULT_SURCHARGE_CENTS,
    DOMAIN,
    SUBSCRIPTION_MAX,
    SUBSCRIPTION_MIN,
    SURCHARGE_MAX_CENTS,
    SURCHARGE_MIN_CENTS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Amber Balance number entities."""
    domain_data = hass.data.get(DOMAIN, {})
    entry_bucket = domain_data.get(entry.entry_id)
    if not entry_bucket:
        raise ConfigEntryNotReady("Amber Balance entry not ready")
    sites = entry_bucket.get("sites") or {}
    if not sites:
        raise ConfigEntryNotReady("Amber Balance site map not initialised")

    base_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    device_info = DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_config")},
        manufacturer="Amber",
        model="Amber Balance",
        name=f"{base_name} Settings",
    )

    numbers: list[AmberFeeNumber] = [
        AmberFeeNumber(
            hass,
            entry,
            CONF_SURCHARGE_CENTS,
            default_value=DEFAULT_SURCHARGE_CENTS,
            translation_key="daily_surcharge",
            icon="mdi:cash",
            native_unit="cents",
            native_min=SURCHARGE_MIN_CENTS,
            native_max=SURCHARGE_MAX_CENTS,
            step=0.5,
            device_info=device_info,
        ),
        AmberFeeNumber(
            hass,
            entry,
            CONF_SUBSCRIPTION,
            default_value=DEFAULT_SUBSCRIPTION,
            translation_key="monthly_subscription",
            icon="mdi:cash-multiple",
            native_unit="AUD",
            native_min=SUBSCRIPTION_MIN,
            native_max=SUBSCRIPTION_MAX,
            step=0.5,
            device_info=device_info,
        ),
    ]

    async_add_entities(numbers)


class AmberFeeNumber(NumberEntity):
    """Number entity used to tweak Amber Balance fee inputs."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False
    if hasattr(NumberMode, "BOX"):
        _attr_native_mode = NumberMode.BOX

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        option_key: str,
        *,
        default_value: float,
        translation_key: str,
        icon: str,
        native_unit: str,
        native_min: float,
        native_max: float,
        step: float,
        device_info: DeviceInfo,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._option_key = option_key
        self._default_value = default_value
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_native_unit_of_measurement = native_unit
        self._attr_native_min_value = native_min
        self._attr_native_max_value = native_max
        self._attr_native_step = step
        self._attr_device_info = device_info
        self._attr_unique_id = f"{entry.entry_id}_{option_key}"
        self._attr_name = None
        self._attr_has_entity_name = True
        self._attr_native_value = self._current_value
        self._ready_for_updates = False

    @property
    def _current_value(self) -> float:
        stored = self._entry.options.get(self._option_key)
        if stored is None:
            stored = self._entry.data.get(self._option_key, self._default_value)
        try:
            return float(stored)
        except (TypeError, ValueError):
            _LOGGER.debug(
                "Invalid stored value for %s, falling back to default %s",
                self._option_key,
                self._default_value,
            )
            return float(self._default_value)

    @property
    def native_value(self) -> float:
        return self._attr_native_value

    async def async_set_native_value(self, value: float) -> None:
        value = max(self._attr_native_min_value, min(self._attr_native_max_value, value))
        self._attr_native_value = value
        self.async_write_ha_state()

        if not self._ready_for_updates or not self.hass.is_running:
            _LOGGER.debug(
                "Skipping persisting %s (integration not fully ready)",
                self._option_key,
            )
            return

        # Persist to config entry options so the integration reloads with the new value
        new_options: dict[str, Any] = {**self._entry.options}
        new_options[self._option_key] = value
        _LOGGER.debug(
            "Updating Amber Balance option %s to %s for entry %s",
            self._option_key,
            value,
            self._entry.entry_id,
        )
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

    async def async_added_to_hass(self) -> None:
        self._attr_native_value = self._current_value
        self.async_write_ha_state()
        self._ready_for_updates = True
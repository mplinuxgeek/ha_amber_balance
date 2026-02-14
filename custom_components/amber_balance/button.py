"""Button platform for Amber Balance."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, CONF_SITE_ID, CONF_SITE_IDS, DEFAULT_NAME, DOMAIN
from .sensor import AmberCoordinator

_LOGGER = logging.getLogger(__name__)


def _migrate_entity_ids(hass: HomeAssistant, entities: list["AmberRefreshButton"]) -> None:
    """Rename existing entities in the registry to explicit prefixed IDs."""
    registry = er.async_get(hass)
    for entity in entities:
        unique_id = entity.unique_id
        desired_entity_id = getattr(entity, "_attr_entity_id", None)
        if not unique_id or not desired_entity_id:
            continue
        current_entity_id = registry.async_get_entity_id("button", DOMAIN, unique_id)
        if not current_entity_id or current_entity_id == desired_entity_id:
            continue
        if registry.async_get(desired_entity_id):
            _LOGGER.warning(
                "Cannot migrate button %s to %s because it already exists",
                current_entity_id,
                desired_entity_id,
            )
            continue
        registry.async_update_entity(
            current_entity_id,
            new_entity_id=desired_entity_id,
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up Amber Balance button based on a config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    entry_bucket = domain_data.get(entry.entry_id)
    if not entry_bucket:
        raise ConfigEntryNotReady("Amber Balance coordinators not ready")
    entry_sites = entry_bucket.get("sites") or {}
    if not entry_sites:
        raise ConfigEntryNotReady("Amber Balance site map not initialised")

    # Gather site_ids from entry data or fall back to whatever the sensors provided
    site_ids = entry.data.get(CONF_SITE_IDS) or []
    if not site_ids and entry.data.get(CONF_SITE_ID):
        site_ids = [entry.data[CONF_SITE_ID]]
    if not site_ids:
        site_ids = list(entry_sites.keys())

    device_name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    buttons: list[AmberRefreshButton] = []
    for site_id in site_ids:
        site_data = entry_sites.get(site_id)
        if not site_data:
            _LOGGER.warning("No coordinator found for Amber Balance site %s", site_id)
            continue
        coordinator: AmberCoordinator = site_data["coordinator"]
        site_info = site_data.get("site_info") or {}
        friendly_suffix = (
            site_info.get("nickname")
            or site_info.get("nmi")
            or site_info.get("id")
            or site_id
        )
        if len(site_ids) == 1:
            site_device_name = device_name
        else:
            site_device_name = f"{device_name} ({friendly_suffix})"
        buttons.append(
            AmberRefreshButton(
                coordinator,
                site_id,
                site_device_name,
                friendly_site_name=friendly_suffix,
            )
        )

    if buttons:
        _migrate_entity_ids(hass, buttons)
        async_add_entities(buttons)


class AmberRefreshButton(CoordinatorEntity[AmberCoordinator], ButtonEntity):
    """Button to trigger a manual refresh."""
    
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: AmberCoordinator,
        site_id: str,
        device_name: str,
        friendly_site_name: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._site_id = site_id
        self._device_name = device_name
        self._friendly_site_name = friendly_site_name or site_id
        self._refreshing = False
        site_suffix = site_id.lower()
        self._attr_unique_id = f"{DOMAIN}_{site_suffix}_v2_refresh"
        self._attr_entity_id = f"button.{DOMAIN}_{site_suffix}_v2_refresh"
        self._attr_name = "Refresh"
        self._attr_icon = "mdi:refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, site_id)},
            manufacturer="Amber",
            name=device_name,
            model="Amber Balance",
        )

    @property
    def available(self) -> bool:
        """Return False only while a manual refresh is in progress."""
        return super().available and not self._refreshing

    @property
    def extra_state_attributes(self) -> dict[str, str | bool]:
        return {
            "refreshing": self._refreshing,
            "site_id": self._site_id,
            "site_name": self._friendly_site_name,
        }

    async def async_press(self) -> None:
        """Handle the button press."""
        if self._refreshing:
            _LOGGER.debug(
                "Refresh already in progress for Amber Balance site %s", self._site_id
            )
            return

        self._refreshing = True
        self.async_write_ha_state()
        _LOGGER.debug(
            "Refresh button pressed for site %s, calling coordinator.async_refresh()",
            self._site_id,
        )
        try:
            await self.coordinator.async_refresh()
            _LOGGER.debug("Coordinator refresh completed for site %s", self._site_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Manual refresh failed for site %s: %s", self._site_id, err)
        finally:
            self._refreshing = False
            self.async_write_ha_state()

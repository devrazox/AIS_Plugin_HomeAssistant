"""AIS Ship Tracker integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AISCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "sensor"]

_FRONTEND_URL = "/ais_tracker/ais-map-card.js"
_FRONTEND_FILE = Path(__file__).parent / "frontend" / "ais-map-card.js"


async def _async_register_card(hass: HomeAssistant) -> None:
    """Register the Lovelace card via storage API, fall back to add_extra_js_url."""
    try:
        lovelace_resources = hass.data["lovelace"]["resources"]
        await lovelace_resources.async_load()
        if not any(r.get("url") == _FRONTEND_URL for r in lovelace_resources.async_items()):
            await lovelace_resources.async_create_item(
                {"res_type": "module", "url": _FRONTEND_URL}
            )
        _LOGGER.debug("AIS card registered as Lovelace resource")
    except Exception:
        add_extra_js_url(hass, _FRONTEND_URL)
        _LOGGER.debug("AIS card registered via add_extra_js_url (fallback)")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_FRONTEND_URL, str(_FRONTEND_FILE), cache_headers=False)]
    )
    await _async_register_card(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = AISCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_stop)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False

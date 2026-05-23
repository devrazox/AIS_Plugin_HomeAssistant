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
_CACHE_TAG = int(_FRONTEND_FILE.stat().st_mtime)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    _LOGGER.info("AIS Ship Tracker wird gestartet")
    _base = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths([
        StaticPathConfig(_FRONTEND_URL, str(_FRONTEND_FILE), cache_headers=False),
        StaticPathConfig("/ais_tracker/leaflet.js",  str(_base / "leaflet.js"),  cache_headers=True),
        StaticPathConfig("/ais_tracker/leaflet.css", str(_base / "leaflet.css"), cache_headers=True),
        StaticPathConfig("/ais_tracker/icon.svg",    str(Path(__file__).parent / "icon.svg"), cache_headers=True),
    ])
    add_extra_js_url(hass, f"{_FRONTEND_URL}?v={_CACHE_TAG}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("AIS-Flotte '%s' wird geladen", entry.title)
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

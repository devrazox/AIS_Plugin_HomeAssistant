"""AIS Ship Tracker integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AISCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "sensor"]

_FRONTEND_URL = "/ais_tracker/ais-map-card.js"
_FRONTEND_FILE = Path(__file__).parent / "frontend" / "ais-map-card.js"


async def _async_register_lovelace(hass: HomeAssistant, _event=None) -> None:
    """Register card as Lovelace resource. Called after HA is fully started."""
    try:
        resources = hass.data["lovelace"]["resources"]
        await resources.async_load()
        if not any(r.get("url") == _FRONTEND_URL for r in resources.async_items()):
            await resources.async_create_item({"res_type": "module", "url": _FRONTEND_URL})
            _LOGGER.info("OpenSeaMap-Karte als Lovelace-Ressource registriert — Browser neu laden")
        else:
            _LOGGER.debug("Lovelace-Ressource bereits vorhanden")
    except Exception as err:
        _LOGGER.warning("Lovelace-Ressource konnte nicht registriert werden: %s", err)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    _LOGGER.info("AIS Ship Tracker wird gestartet")
    await hass.http.async_register_static_paths(
        [StaticPathConfig(_FRONTEND_URL, str(_FRONTEND_FILE), cache_headers=False)]
    )

    if hass.is_running:
        await _async_register_lovelace(hass)
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _async_register_lovelace)

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

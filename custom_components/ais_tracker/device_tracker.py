"""Device tracker platform for AIS Ship Tracker."""
from __future__ import annotations

from homeassistant.components.device_tracker import TrackerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AISCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AISCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _check_new_vessels() -> None:
        new = [
            AISTrackerEntity(coordinator, mmsi)
            for mmsi in coordinator.vessels
            if mmsi not in known
        ]
        if new:
            known.update(e.mmsi for e in new)
            async_add_entities(new)

    coordinator.async_add_listener(_check_new_vessels)
    _check_new_vessels()


class AISTrackerEntity(CoordinatorEntity[AISCoordinator], TrackerEntity):
    """Represents a vessel on the HA map."""

    _attr_source_type = SourceType.GPS
    _attr_icon = "mdi:ferry"

    def __init__(self, coordinator: AISCoordinator, mmsi: str) -> None:
        super().__init__(coordinator)
        self.mmsi = mmsi
        self._attr_unique_id = f"ais_{mmsi}_tracker"

    @property
    def _vessel(self) -> dict:
        return self.coordinator.vessels.get(self.mmsi, {})

    @property
    def name(self) -> str:
        return self._vessel.get("name", self.mmsi)

    @property
    def latitude(self) -> float | None:
        return self._vessel.get("latitude")

    @property
    def longitude(self) -> float | None:
        return self._vessel.get("longitude")

    @property
    def extra_state_attributes(self) -> dict:
        v = self._vessel
        return {
            "mmsi": self.mmsi,
            "sog": v.get("sog"),
            "cog": v.get("cog"),
            "true_heading": v.get("true_heading"),
            "nav_status": v.get("nav_status"),
            "ship_type": v.get("ship_type"),
            "flag": v.get("flag"),
            "destination": v.get("destination"),
        }

    @property
    def device_info(self):
        v = self._vessel
        return {
            "identifiers": {(DOMAIN, self.mmsi)},
            "name": v.get("name", self.mmsi),
            "manufacturer": v.get("flag", "Unknown"),
            "model": v.get("ship_type", "Vessel"),
        }

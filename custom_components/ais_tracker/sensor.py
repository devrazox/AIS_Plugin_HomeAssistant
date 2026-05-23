"""Sensor platform for AIS Ship Tracker."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfSpeed, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AISCoordinator


@dataclass(frozen=True)
class AISSensorDescription(SensorEntityDescription):
    vessel_key: str = ""
    icon_override: str | None = None


SENSOR_TYPES: tuple[AISSensorDescription, ...] = (
    AISSensorDescription(key="name",         vessel_key="name",         name="Name",              icon="mdi:ferry"),
    AISSensorDescription(key="mmsi",         vessel_key="mmsi",         name="MMSI",              icon="mdi:identifier"),
    AISSensorDescription(key="imo",          vessel_key="imo",          name="IMO",               icon="mdi:identifier"),
    AISSensorDescription(key="callsign",     vessel_key="callsign",     name="Rufzeichen",        icon="mdi:radio"),
    AISSensorDescription(key="flag",         vessel_key="flag",         name="Flagge",            icon="mdi:flag"),
    AISSensorDescription(key="ship_type",    vessel_key="ship_type",    name="Schiffstyp",        icon="mdi:ship-wheel"),
    AISSensorDescription(key="nav_status",   vessel_key="nav_status",   name="Navigationsstatus", icon="mdi:information"),
    AISSensorDescription(key="destination",  vessel_key="destination",  name="Ziel",              icon="mdi:map-marker"),
    AISSensorDescription(key="eta",          vessel_key="eta",          name="ETA",               icon="mdi:clock-end"),
    AISSensorDescription(
        key="sog", vessel_key="sog", name="Geschwindigkeit (SOG)",
        icon="mdi:speedometer", native_unit_of_measurement="kn",
    ),
    AISSensorDescription(
        key="cog", vessel_key="cog", name="Kurs (COG)",
        icon="mdi:compass", native_unit_of_measurement="°",
    ),
    AISSensorDescription(
        key="true_heading", vessel_key="true_heading", name="Steuerkurs",
        icon="mdi:compass-rose", native_unit_of_measurement="°",
    ),
    AISSensorDescription(
        key="rot", vessel_key="rot", name="Drehrate (ROT)",
        icon="mdi:rotate-right", native_unit_of_measurement="°/min",
    ),
    AISSensorDescription(
        key="draught", vessel_key="draught", name="Tiefgang",
        icon="mdi:waves-arrow-down", native_unit_of_measurement="m",
    ),
    AISSensorDescription(
        key="length", vessel_key="length", name="Länge",
        icon="mdi:arrow-left-right", native_unit_of_measurement="m",
    ),
    AISSensorDescription(
        key="beam", vessel_key="beam", name="Breite",
        icon="mdi:arrow-up-down", native_unit_of_measurement="m",
    ),
    AISSensorDescription(
        key="latitude", vessel_key="latitude", name="Breitengrad",
        icon="mdi:latitude", native_unit_of_measurement="°",
    ),
    AISSensorDescription(
        key="longitude", vessel_key="longitude", name="Längengrad",
        icon="mdi:longitude", native_unit_of_measurement="°",
    ),
)


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
            AISSensorEntity(coordinator, mmsi, desc)
            for mmsi in coordinator.vessels
            if mmsi not in known
            for desc in SENSOR_TYPES
        ]
        if new:
            known.update(coordinator.vessels.keys())
            async_add_entities(new)

    coordinator.async_add_listener(_check_new_vessels)
    _check_new_vessels()


class AISSensorEntity(CoordinatorEntity[AISCoordinator], SensorEntity):
    """One sensor for one AIS field of one vessel."""

    entity_description: AISSensorDescription

    def __init__(
        self,
        coordinator: AISCoordinator,
        mmsi: str,
        description: AISSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.mmsi = mmsi
        self.entity_description = description
        self._attr_unique_id = f"ais_{mmsi}_{description.key}"
        self._attr_has_entity_name = True

    @property
    def _vessel(self) -> dict:
        return self.coordinator.vessels.get(self.mmsi, {})

    @property
    def native_value(self) -> Any:
        return self._vessel.get(self.entity_description.vessel_key)

    @property
    def available(self) -> bool:
        return self.mmsi in self.coordinator.vessels

    @property
    def device_info(self):
        v = self._vessel
        return {
            "identifiers": {(DOMAIN, self.mmsi)},
            "name": v.get("name", self.mmsi),
            "manufacturer": v.get("flag", "Unknown"),
            "model": v.get("ship_type", "Vessel"),
        }

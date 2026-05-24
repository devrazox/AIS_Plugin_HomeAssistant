"""AIS WebSocket coordinator."""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from datetime import timedelta
from typing import Any

import websockets
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AISSTREAM_WS_URL,
    CONF_API_KEY,
    CONF_BOUNDING_BOX,
    CONF_FLEET_MODE,
    CONF_VESSELS,
    DOMAIN,
    FLEET_MODE_GLOBAL,
    FLEET_MODE_LIST,
    FLEET_MODE_REGION,
    NAV_STATUS,
    SHIP_TYPES,
)

_LOGGER = logging.getLogger(__name__)

# How long until a vessel is considered gone (no update received)
VESSEL_TIMEOUT_SECONDS = 600


def _mmsi_to_flag(mmsi: str) -> str:
    """Derive flag/country from MMSI MID (first 3 digits)."""
    mid_to_country = {
        "211": "Germany", "218": "Germany", "219": "Denmark",
        "220": "Denmark", "230": "Finland", "244": "Netherlands",
        "245": "Netherlands", "246": "Netherlands", "247": "Italy",
        "250": "Ireland", "253": "Luxembourg", "255": "Portugal (Azores/Madeira)",
        "257": "Norway", "258": "Norway", "259": "Norway",
        "261": "Poland", "265": "Sweden", "266": "Sweden",
        "269": "Switzerland", "271": "Turkey", "273": "Russia",
        "276": "Estonia", "277": "Latvia", "278": "Lithuania",
        "338": "United States", "339": "United States",
        "366": "United States", "367": "United States",
        "369": "United States",
        "412": "China", "413": "China", "416": "Taiwan",
        "431": "Japan", "432": "Japan",
        "440": "South Korea", "441": "South Korea",
        "477": "Hong Kong",
        "503": "Australia",
        "512": "New Zealand",
        "525": "Indonesia",
        "548": "Philippines",
        "563": "Singapore",
        "574": "Vietnam",
        "636": "Liberia",
        "710": "Brazil",
    }
    mid = mmsi[:3] if len(mmsi) >= 3 else ""
    return mid_to_country.get(mid, f"MID {mid}")


def _parse_ship_type(type_code: int) -> str:
    base = (type_code // 10) * 10
    return SHIP_TYPES.get(type_code) or SHIP_TYPES.get(base) or "Unknown"


def _parse_ais_message(msg: dict) -> dict[str, Any] | None:
    """Parse an AISstream message into a flat vessel dict."""
    msg_type = msg.get("MessageType")
    metadata = msg.get("MetaData", {})
    mmsi = str(metadata.get("MMSI", ""))
    if not mmsi:
        return None

    vessel: dict[str, Any] = {
        "mmsi": mmsi,
        "name": metadata.get("ShipName", "").strip() or mmsi,
        "latitude": metadata.get("latitude"),
        "longitude": metadata.get("longitude"),
        "flag": _mmsi_to_flag(mmsi),
    }

    if msg_type == "PositionReport":
        data = msg.get("Message", {}).get("PositionReport", {})
        heading = data.get("TrueHeading")
        vessel.update({
            "sog": data.get("Sog"),
            "cog": data.get("Cog"),
            "true_heading": heading if heading != 511 else None,
            "rot": data.get("RateOfTurn"),
            "nav_status_code": data.get("NavigationalStatus"),
            "nav_status": NAV_STATUS.get(data.get("NavigationalStatus", 15), "Unknown"),
            "latitude": data.get("Latitude") or vessel["latitude"],
            "longitude": data.get("Longitude") or vessel["longitude"],
        })

    elif msg_type == "ShipStaticData":
        data = msg.get("Message", {}).get("ShipStaticData", {})
        dim = data.get("Dimension", {})
        eta = data.get("Eta", {})
        vessel.update({
            "imo": str(data.get("ImoNumber", "")),
            "callsign": data.get("CallSign", "").strip(),
            "ship_type_code": data.get("Type"),
            "ship_type": _parse_ship_type(data.get("Type", 0)),
            "destination": data.get("Destination", "").strip(),
            "draught": data.get("MaximumStaticDraught"),
            "length": (dim.get("A", 0) or 0) + (dim.get("B", 0) or 0),
            "beam": (dim.get("C", 0) or 0) + (dim.get("D", 0) or 0),
            "eta_month": eta.get("Month"),
            "eta_day": eta.get("Day"),
            "eta_hour": eta.get("Hour"),
            "eta_minute": eta.get("Minute"),
        })
        if all(vessel.get(k) for k in ("eta_month", "eta_day", "eta_hour", "eta_minute")):
            vessel["eta"] = (
                f"{vessel['eta_month']:02d}-{vessel['eta_day']:02d} "
                f"{vessel['eta_hour']:02d}:{vessel['eta_minute']:02d}"
            )

    # Class B transponder (recreational vessels, pleasure craft)
    elif msg_type == "StandardClassBPositionReport":
        data = msg.get("Message", {}).get("StandardClassBPositionReport", {})
        heading = data.get("TrueHeading")
        sog = data.get("Sog")
        cog = data.get("Cog")
        vessel.update({
            "sog": sog if sog != 102.3 else None,
            "cog": cog if cog != 360.0 else None,
            "true_heading": heading if heading != 511 else None,
            "latitude": data.get("Latitude") or vessel["latitude"],
            "longitude": data.get("Longitude") or vessel["longitude"],
        })

    elif msg_type == "StaticDataReport":
        data = msg.get("Message", {}).get("StaticDataReport", {})
        name = data.get("Name", "").strip()
        if name:
            vessel["name"] = name
        callsign = data.get("CallSign", "").strip()
        if callsign:
            vessel["callsign"] = callsign
        type_code = data.get("TypeOfShipAndCargoType")
        if type_code is not None:
            vessel["ship_type_code"] = type_code
            vessel["ship_type"] = _parse_ship_type(type_code)
        dim = data.get("Dimension", {})
        if dim:
            vessel["length"] = (dim.get("A", 0) or 0) + (dim.get("B", 0) or 0)
            vessel["beam"] = (dim.get("C", 0) or 0) + (dim.get("D", 0) or 0)

    # Class B extended (Type 19) — position + static combined
    elif msg_type == "ExtendedClassBPositionReport":
        data = msg.get("Message", {}).get("ExtendedClassBPositionReport", {})
        heading = data.get("TrueHeading")
        sog = data.get("Sog")
        cog = data.get("Cog")
        vessel.update({
            "sog": sog if sog != 102.3 else None,
            "cog": cog if cog != 360.0 else None,
            "true_heading": heading if heading != 511 else None,
            "latitude": data.get("Latitude") or vessel["latitude"],
            "longitude": data.get("Longitude") or vessel["longitude"],
        })
        name = data.get("Name", "").strip()
        if name:
            vessel["name"] = name
        type_code = data.get("TypeOfShipAndCargoType")
        if type_code is not None:
            vessel["ship_type_code"] = type_code
            vessel["ship_type"] = _parse_ship_type(type_code)
        dim = data.get("Dimension", {})
        if dim:
            vessel["length"] = (dim.get("A", 0) or 0) + (dim.get("B", 0) or 0)
            vessel["beam"] = (dim.get("C", 0) or 0) + (dim.get("D", 0) or 0)

    # Long-range AIS broadcast (Type 27) — simplified position
    elif msg_type == "LongRangeAISBroadcastMessage":
        data = msg.get("Message", {}).get("LongRangeAISBroadcastMessage", {})
        sog = data.get("Sog")
        cog = data.get("Cog")
        vessel.update({
            "sog": sog if sog != 63 else None,
            "cog": cog if cog != 511 else None,
            "nav_status_code": data.get("NavigationalStatus"),
            "nav_status": NAV_STATUS.get(data.get("NavigationalStatus", 15), "Unknown"),
            "latitude": data.get("Latitude") or vessel["latitude"],
            "longitude": data.get("Longitude") or vessel["longitude"],
        })

    else:
        return None

    return vessel


class AISCoordinator(DataUpdateCoordinator):
    """Manages the AISstream WebSocket connection and vessel data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.entry = entry
        self.vessels: dict[str, dict[str, Any]] = {}
        self._ws_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._viewport_bbox: list | None = None

    # ------------------------------------------------------------------
    # DataUpdateCoordinator hook — called once on setup and on interval
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, Any]:
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = self.hass.async_create_background_task(
                self._ws_loop(), "ais_tracker_ws"
            )
        now = time.monotonic()
        stale = [m for m, v in self.vessels.items()
                 if now - v.get("last_seen", now) > VESSEL_TIMEOUT_SECONDS]
        for m in stale:
            _LOGGER.debug("Schiff %s entfernt (Timeout)", m)
            del self.vessels[m]
        return self.vessels

    # ------------------------------------------------------------------
    # WebSocket loop
    # ------------------------------------------------------------------
    async def _ws_loop(self) -> None:
        api_key = self.entry.data[CONF_API_KEY]
        subscribe_msg = self._build_subscribe_msg()
        ssl_context = await asyncio.get_event_loop().run_in_executor(
            None, ssl.create_default_context
        )

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(
                    AISSTREAM_WS_URL,
                    ssl=ssl_context,
                    ping_interval=None,
                    ping_timeout=None,
                ) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    _LOGGER.info(
                        "AISstream verbunden — Subscription: %s",
                        {k: v for k, v in subscribe_msg.items() if k != "APIKey"},
                    )
                    async for raw in ws:
                        if self._stop_event.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                            if isinstance(msg, dict) and "error" in msg:
                                _LOGGER.error("AISstream Fehler: %s", msg["error"])
                                break
                            vessel = _parse_ais_message(msg)
                            if vessel:
                                is_new = vessel["mmsi"] not in self.vessels
                                self._merge_vessel(vessel)
                                if is_new:
                                    _LOGGER.info(
                                        "Neues Schiff erkannt: %s (MMSI %s)",
                                        vessel.get("name", vessel["mmsi"]),
                                        vessel["mmsi"],
                                    )
                            else:
                                _LOGGER.debug(
                                    "Unbekannter Nachrichtentyp: %s",
                                    msg.get("MessageType"),
                                )
                        except Exception:
                            _LOGGER.exception("Fehler beim Verarbeiten einer AIS-Nachricht")
            except Exception as exc:
                if not self._stop_event.is_set():
                    _LOGGER.warning("AISstream getrennt: %s — Neuverbindung in 15s", exc)
                    await asyncio.sleep(15)

    def _build_subscribe_msg(self) -> dict:
        api_key = self.entry.data[CONF_API_KEY]
        mode = self.entry.data.get(CONF_FLEET_MODE, FLEET_MODE_GLOBAL)

        if mode == FLEET_MODE_REGION:
            bbox = self.entry.data.get(CONF_BOUNDING_BOX, {})
            bounding_boxes = [[
                [bbox.get("min_lat", -90), bbox.get("min_lon", -180)],
                [bbox.get("max_lat", 90), bbox.get("max_lon", 180)],
            ]]
        elif self._viewport_bbox:
            # Dynamic viewport set by map card
            bounding_boxes = self._viewport_bbox
        else:
            # LIST and GLOBAL without viewport: world-wide
            bounding_boxes = [[[-90, -180], [90, 180]]]

        msg: dict[str, Any] = {
            "APIKey": api_key,
            "BoundingBoxes": bounding_boxes,
            "FilterMessageTypes": [
                "PositionReport",
                "ShipStaticData",
                "StandardClassBPositionReport",
                "ExtendedClassBPositionReport",
                "StaticDataReport",
                "LongRangeAisBroadcastMessage",
            ],
        }

        if mode == FLEET_MODE_LIST:
            vessels = self.entry.data.get(CONF_VESSELS, [])
            msg["FiltersShipMMSI"] = [str(v["mmsi"]) for v in vessels]

        _LOGGER.debug("AISstream subscribe: %s", {k: v for k, v in msg.items() if k != "APIKey"})
        return msg

    def _merge_vessel(self, update: dict[str, Any]) -> None:
        """Merge incoming AIS data into vessel store and notify HA."""
        mmsi = update["mmsi"]

        # In LIST mode, ignore vessels not in the configured fleet
        if self.entry.data.get(CONF_FLEET_MODE) == FLEET_MODE_LIST:
            configured = {str(v["mmsi"]) for v in self.entry.data.get(CONF_VESSELS, [])}
            if mmsi not in configured:
                return

        if mmsi not in self.vessels:
            self.vessels[mmsi] = {}
        self.vessels[mmsi].update({k: v for k, v in update.items() if v is not None})
        self.vessels[mmsi]["last_seen"] = time.monotonic()
        custom = next(
            (v["custom_name"] for v in self.entry.data.get(CONF_VESSELS, [])
             if str(v["mmsi"]) == mmsi and v.get("custom_name")),
            None,
        )
        if custom:
            self.vessels[mmsi]["name"] = custom
        self.async_set_updated_data(self.vessels)

    # ------------------------------------------------------------------
    # Dynamic viewport (called from map card via HA service)
    # ------------------------------------------------------------------
    def update_viewport(self, min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> None:
        """Update subscription bounding box to current map viewport and reconnect."""
        self._viewport_bbox = [[[min_lat, min_lon], [max_lat, max_lon]]]
        _LOGGER.debug("Viewport aktualisiert: %s", self._viewport_bbox)
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
        self._ws_task = self.hass.async_create_background_task(
            self._ws_loop(), "ais_tracker_ws"
        )

    # ------------------------------------------------------------------
    # Fleet management (called from config flow options)
    # ------------------------------------------------------------------
    def get_vessels(self) -> list[dict]:
        return list(self.vessels.values())

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def async_stop(self) -> None:
        self._stop_event.set()
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()

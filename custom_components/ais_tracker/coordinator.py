"""AIS WebSocket coordinator."""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
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
        vessel.update({
            "sog": data.get("Sog"),                          # Speed over Ground (knots)
            "cog": data.get("Cog"),                          # Course over Ground (°)
            "true_heading": data.get("TrueHeading"),         # True Heading (°)
            "rot": data.get("RateOfTurn"),                   # Rate of Turn
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
            "draught": data.get("MaximumStaticDraught"),     # Tiefgang (m)
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

    # ------------------------------------------------------------------
    # DataUpdateCoordinator hook — called once on setup and on interval
    # ------------------------------------------------------------------
    async def _async_update_data(self) -> dict[str, Any]:
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = self.hass.async_create_background_task(
                self._ws_loop(), "ais_tracker_ws"
            )
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
                async with websockets.connect(AISSTREAM_WS_URL, ssl=ssl_context) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    _LOGGER.info("AISstream WebSocket verbunden")
                    async for raw in ws:
                        if self._stop_event.is_set():
                            break
                        try:
                            msg = json.loads(raw)
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
                        except Exception:
                            _LOGGER.exception("Fehler beim Verarbeiten einer AIS-Nachricht")
            except Exception as exc:
                if not self._stop_event.is_set():
                    _LOGGER.warning("AISstream getrennt: %s — Neuverbindung in 15s", exc)
                    await asyncio.sleep(15)

    def _build_subscribe_msg(self) -> dict:
        api_key = self.entry.data[CONF_API_KEY]
        mode = self.entry.data.get(CONF_FLEET_MODE, FLEET_MODE_GLOBAL)

        msg: dict[str, Any] = {
            "APIKey": api_key,
            "MessageTypes": ["PositionReport", "ShipStaticData"],
        }

        if mode == FLEET_MODE_LIST:
            vessels = self.entry.data.get(CONF_VESSELS, [])
            mmsi_list = [v["mmsi"] for v in vessels]
            msg["FilterMessageTypes"] = ["PositionReport", "ShipStaticData"]
            msg["MMSI"] = mmsi_list

        elif mode == FLEET_MODE_REGION:
            bbox = self.entry.data.get(CONF_BOUNDING_BOX, {})
            msg["BoundingBoxes"] = [[
                [bbox.get("min_lat", -90), bbox.get("min_lon", -180)],
                [bbox.get("max_lat", 90), bbox.get("max_lon", 180)],
            ]]

        # FLEET_MODE_GLOBAL: no filter, receive everything

        return msg

    def _merge_vessel(self, update: dict[str, Any]) -> None:
        """Merge incoming AIS data into vessel store and notify HA."""
        mmsi = update["mmsi"]
        if mmsi not in self.vessels:
            self.vessels[mmsi] = {}
        self.vessels[mmsi].update({k: v for k, v in update.items() if v is not None})
        custom = next(
            (v["custom_name"] for v in self.entry.data.get(CONF_VESSELS, [])
             if str(v["mmsi"]) == mmsi and v.get("custom_name")),
            None,
        )
        if custom:
            self.vessels[mmsi]["name"] = custom
        self.async_set_updated_data(self.vessels)

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

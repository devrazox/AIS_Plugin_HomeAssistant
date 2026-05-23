"""Config flow for AIS Ship Tracker."""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .const import (
    AISSTREAM_REST_URL,
    CONF_API_KEY,
    CONF_BOUNDING_BOX,
    CONF_FLEET_MODE,
    CONF_VESSELS,
    DOMAIN,
    FLEET_MODE_GLOBAL,
    FLEET_MODE_LIST,
    FLEET_MODE_REGION,
    FLEET_MODES,
)

_LOGGER = logging.getLogger(__name__)


async def _search_vessels(session: aiohttp.ClientSession, api_key: str, query: str) -> list[dict]:
    """Search vessels by name via AISstream REST API."""
    try:
        async with session.get(
            f"{AISSTREAM_REST_URL}/vessels/search",
            params={"name": query},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("vessels", [])
    except Exception:
        _LOGGER.debug("Vessel search failed", exc_info=True)
    return []


import asyncio


async def _validate_api_key(api_key: str) -> bool:
    """Verify API key by connecting to AISstream and checking for an error response.

    A TimeoutError means the connection worked but no ships were in range —
    that is a valid key. Only an explicit error message or a connection failure
    means the key is wrong.
    """
    import websockets
    try:
        async with websockets.connect(
            "wss://stream.aisstream.io/v0/stream", open_timeout=10
        ) as ws:
            await ws.send(json.dumps({
                "APIKey": api_key,
                "MessageTypes": ["PositionReport"],
                "BoundingBoxes": [[[54.0, 8.0], [55.0, 9.0]]],
            }))
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                msg = json.loads(raw)
                # AISstream sends {"error": "..."} for bad keys
                if isinstance(msg, dict) and "error" in msg:
                    return False
            except asyncio.TimeoutError:
                pass  # No message = no ships in area, key is fine
        return True
    except Exception:
        return False


class AISTrackerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._vessels: list[dict] = []
        self._search_results: list[dict] = []

    # ------------------------------------------------------------------
    # Step 1: API Key
    # ------------------------------------------------------------------
    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            valid = await _validate_api_key(api_key)
            if valid:
                self._data[CONF_API_KEY] = api_key
                return await self.async_step_fleet_mode()
            errors["base"] = "invalid_api_key"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
            }),
            errors=errors,
            description_placeholders={
                "url": "https://aisstream.io"
            },
        )

    # ------------------------------------------------------------------
    # Step 2: Fleet Mode
    # ------------------------------------------------------------------
    async def async_step_fleet_mode(self, user_input: dict | None = None):
        if user_input is not None:
            self._data[CONF_FLEET_MODE] = user_input[CONF_FLEET_MODE]
            mode = user_input[CONF_FLEET_MODE]
            if mode == FLEET_MODE_REGION:
                return await self.async_step_bounding_box()
            if mode == FLEET_MODE_LIST:
                return await self.async_step_vessel_search()
            # Global: done
            return self._create_entry()

        return self.async_show_form(
            step_id="fleet_mode",
            data_schema=vol.Schema({
                vol.Required(CONF_FLEET_MODE, default=FLEET_MODE_LIST): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": FLEET_MODE_LIST, "label": "Eigene Flotte (Liste)"},
                            {"value": FLEET_MODE_REGION, "label": "Region (Bounding Box)"},
                            {"value": FLEET_MODE_GLOBAL, "label": "Global (alle Schiffe)"},
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 3a: Bounding Box (nur für Region-Modus)
    # ------------------------------------------------------------------
    async def async_step_bounding_box(self, user_input: dict | None = None):
        if user_input is not None:
            self._data[CONF_BOUNDING_BOX] = {
                "min_lat": user_input["min_lat"],
                "min_lon": user_input["min_lon"],
                "max_lat": user_input["max_lat"],
                "max_lon": user_input["max_lon"],
            }
            return self._create_entry()

        return self.async_show_form(
            step_id="bounding_box",
            data_schema=vol.Schema({
                vol.Required("min_lat", default=47.0): vol.Coerce(float),
                vol.Required("min_lon", default=5.0): vol.Coerce(float),
                vol.Required("max_lat", default=55.5): vol.Coerce(float),
                vol.Required("max_lon", default=15.5): vol.Coerce(float),
            }),
            description_placeholders={
                "example": "Deutschland: min_lat=47, min_lon=5, max_lat=55.5, max_lon=15.5"
            },
        )

    # ------------------------------------------------------------------
    # Step 3b: Vessel Search (für Listen-Modus)
    # ------------------------------------------------------------------
    async def async_step_vessel_search(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            query = user_input.get("search_query", "").strip()
            mmsi_direct = user_input.get("mmsi_direct", "").strip()

            if mmsi_direct:
                vessel = {"mmsi": mmsi_direct, "name": mmsi_direct}
                self._vessels.append(vessel)
                self._data[CONF_VESSELS] = self._vessels
                # Continue adding or finish
                return await self.async_step_vessel_confirm()

            if query:
                session = async_get_clientsession(self.hass)
                self._search_results = await _search_vessels(
                    session, self._data[CONF_API_KEY], query
                )
                if self._search_results:
                    return await self.async_step_vessel_select()
                errors["base"] = "no_results"

        current = ", ".join(v["name"] for v in self._vessels) if self._vessels else "–"
        return self.async_show_form(
            step_id="vessel_search",
            data_schema=vol.Schema({
                vol.Optional("search_query"): str,
                vol.Optional("mmsi_direct"): str,
            }),
            errors=errors,
            description_placeholders={"current_fleet": current},
        )

    # ------------------------------------------------------------------
    # Step 3c: Select from search results
    # ------------------------------------------------------------------
    async def async_step_vessel_select(self, user_input: dict | None = None):
        if user_input is not None:
            selected_mmsi = user_input.get("selected_vessel")
            vessel = next(
                (v for v in self._search_results if v.get("mmsi") == selected_mmsi), None
            )
            if vessel:
                self._vessels.append({"mmsi": vessel["mmsi"], "name": vessel.get("name", vessel["mmsi"])})
                self._data[CONF_VESSELS] = self._vessels
            return await self.async_step_vessel_confirm()

        options = [
            {
                "value": v.get("mmsi", ""),
                "label": f"{v.get('name', 'Unknown')} — MMSI {v.get('mmsi', '')}",
            }
            for v in self._search_results
        ]

        return self.async_show_form(
            step_id="vessel_select",
            data_schema=vol.Schema({
                vol.Required("selected_vessel"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.LIST)
                ),
            }),
        )

    # ------------------------------------------------------------------
    # Step 3d: Confirm fleet / add more / finish
    # ------------------------------------------------------------------
    async def async_step_vessel_confirm(self, user_input: dict | None = None):
        if user_input is not None:
            action = user_input.get("action", "finish")
            if action == "add_more":
                return await self.async_step_vessel_search()
            return self._create_entry()

        vessel_list = "\n".join(f"• {v['name']} ({v['mmsi']})" for v in self._vessels)
        return self.async_show_form(
            step_id="vessel_confirm",
            data_schema=vol.Schema({
                vol.Required("action", default="finish"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "finish", "label": "Fertig — Integration speichern"},
                            {"value": "add_more", "label": "Weiteres Schiff hinzufügen"},
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
            description_placeholders={"vessel_list": vessel_list or "–"},
        )

    # ------------------------------------------------------------------
    def _create_entry(self):
        mode = self._data.get(CONF_FLEET_MODE, FLEET_MODE_GLOBAL)
        title_map = {
            FLEET_MODE_GLOBAL: "AIS — Global",
            FLEET_MODE_REGION: "AIS — Region",
            FLEET_MODE_LIST: f"AIS — Flotte ({len(self._data.get(CONF_VESSELS, []))} Schiffe)",
        }
        return self.async_create_entry(title=title_map[mode], data=self._data)

    # ------------------------------------------------------------------
    # Options Flow (nachträgliches Hinzufügen/Entfernen von Schiffen)
    # ------------------------------------------------------------------
    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return AISOptionsFlow(entry)


class AISOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._vessels: list[dict] = list(entry.data.get(CONF_VESSELS, []))
        self._search_results: list[dict] = []

    async def async_step_init(self, user_input: dict | None = None):
        """Show current fleet, allow adding/removing vessels."""
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                return await self.async_step_vessel_search()
            if action == "remove":
                return await self.async_step_remove_vessel()
            # save
            new_data = dict(self._entry.data)
            new_data[CONF_VESSELS] = self._vessels
            self.hass.config_entries.async_update_entry(self._entry, data=new_data)
            return self.async_create_entry(title="", data={})

        vessel_list = "\n".join(f"• {v['name']} ({v['mmsi']})" for v in self._vessels) or "–"
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="save"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "save", "label": "Speichern"},
                            {"value": "add", "label": "Schiff hinzufügen"},
                            {"value": "remove", "label": "Schiff entfernen"},
                        ],
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
            description_placeholders={"vessel_list": vessel_list},
        )

    async def async_step_vessel_search(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            mmsi_direct = user_input.get("mmsi_direct", "").strip()
            query = user_input.get("search_query", "").strip()
            if mmsi_direct:
                self._vessels.append({"mmsi": mmsi_direct, "name": mmsi_direct})
                return await self.async_step_init()
            if query:
                session = async_get_clientsession(self.hass)
                self._search_results = await _search_vessels(
                    session, self._entry.data[CONF_API_KEY], query
                )
                if self._search_results:
                    return await self.async_step_vessel_select()
                errors["base"] = "no_results"

        return self.async_show_form(
            step_id="vessel_search",
            data_schema=vol.Schema({
                vol.Optional("search_query"): str,
                vol.Optional("mmsi_direct"): str,
            }),
            errors=errors,
        )

    async def async_step_vessel_select(self, user_input: dict | None = None):
        if user_input is not None:
            selected_mmsi = user_input.get("selected_vessel")
            vessel = next((v for v in self._search_results if v.get("mmsi") == selected_mmsi), None)
            if vessel:
                self._vessels.append({"mmsi": vessel["mmsi"], "name": vessel.get("name", vessel["mmsi"])})
            return await self.async_step_init()

        options = [
            {"value": v.get("mmsi", ""), "label": f"{v.get('name', 'Unknown')} — MMSI {v.get('mmsi', '')}"}
            for v in self._search_results
        ]
        return self.async_show_form(
            step_id="vessel_select",
            data_schema=vol.Schema({
                vol.Required("selected_vessel"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.LIST)
                ),
            }),
        )

    async def async_step_remove_vessel(self, user_input: dict | None = None):
        if user_input is not None:
            mmsi_to_remove = user_input.get("vessel_to_remove")
            self._vessels = [v for v in self._vessels if v["mmsi"] != mmsi_to_remove]
            return await self.async_step_init()

        options = [
            {"value": v["mmsi"], "label": f"{v['name']} ({v['mmsi']})"}
            for v in self._vessels
        ]
        if not options:
            return await self.async_step_init()

        return self.async_show_form(
            step_id="remove_vessel",
            data_schema=vol.Schema({
                vol.Required("vessel_to_remove"): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.LIST)
                ),
            }),
        )

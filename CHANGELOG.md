# Changelog

## v1.0.17
### Fixed
- Send both `MessageTypes` and `FilterMessageTypes` in subscription for maximum API compatibility
- Log full subscription details (INFO) and AISstream error responses on connect
- Log unknown message types at DEBUG level for easier diagnostics

## v1.0.16
### Fixed
- WebSocket connection no longer drops every few minutes: disabled automatic ping/keepalive frames (`ping_interval=None`). AISstream does not respond to WebSocket pings, causing the library to close the connection with code 1011 after each timeout.
- Added global `BoundingBoxes` to LIST and GLOBAL mode subscriptions — AISstream requires this field even when filtering by MMSI.
- Added debug logging of the subscribe message for easier diagnostics.

## v1.0.15
### Fixed
- Integration icon now shows correctly on the HA integrations page. `icon.png` must be located inside the component directory (`custom_components/ais_tracker/`), not only in the repo root.

## v1.0.14
### Added
- **Follow mode** for the map card: set `follow: device_tracker.ais_<mmsi>_tracker` in the card config to keep the map centered on a specific vessel. The map pans to the vessel on every AIS update.

## v1.0.13
### Added
- Support for all maritime AIS message types, including **Class B transponders** (Types 18, 19, 24) and Long Range AIS (Type 27). Fixes missing recreational vessels and pleasure craft that use Class B transponders.
### Fixed
- MMSI values are now sent as integers in LIST mode subscriptions (AISstream API requirement).
- `FilterMessageTypes` is now used consistently across all fleet modes.

## v1.0.12
### Added
- **Vessel rename** in fleet management: new "Schiff umbenennen" action in the options flow. Custom names are stored in the config entry and override AIS-provided names.

## v1.0.11
### Fixed
- Map card no longer shows blank/black after a HACS update: the JS URL now includes the file modification time as a cache-buster so the browser always loads the latest version.
- Leaflet CSS is now injected into the shadow DOM so map tiles and controls render correctly inside the Lovelace card.

## v1.0.10
### Fixed
- Map card config values with trailing commas (`lat: 54.515,`) are now parsed correctly using `parseFloat`/`parseInt`.
- PNG icon added for the HACS store listing.

## v1.0.9
### Added
- Sailboat + buoy SVG icon, served via static path.

## v1.0.8 and earlier
Initial releases.

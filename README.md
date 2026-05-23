# AIS Ship Tracker — Home Assistant Integration

Verfolge Schiffe in Echtzeit via [AISstream.io](https://aisstream.io) direkt in Home Assistant. Alle AIS-Daten als Entitäten, dazu eine Seekarte auf Basis von OpenSeaMap mit Tiefenangaben, Häfen und Betonnung.

## Features

- **Drei Flottenmodi**: Eigene Schiffsliste, Region (Bounding Box) oder global
- **Schiffe per Name suchen** oder direkt per MMSI hinzufügen
- **Pro Schiff ein HA-Device** mit allen AIS-Sensoren:
  - Name, MMSI, IMO, Rufzeichen, Flagge, Schiffstyp
  - Geschwindigkeit (SOG), Kurs (COG), Steuerkurs, Drehrate (ROT)
  - Tiefgang, Länge, Breite
  - Navigationsstatus (Fahrt, Anker, festgemacht, …)
  - Zielhafen, ETA
- **OpenSeaMap Lovelace Card**: Seekarte mit Tiefenangaben, Seezeichen, Häfen — Schiffe als farbige Pfeile (Farbe = Navigationsstatus)

## Installation via HACS

1. HACS → Einstellungen → **Custom Repositories**
2. URL: `https://github.com/devrazox/AIS_Plugin_HomeAssistant`
3. Typ: **Integration** → Hinzufügen
4. HACS → Integrationen → **AIS Ship Tracker** → Installieren
5. HA neu starten

Die OpenSeaMap-Karte wird **automatisch registriert** — kein Eintrag in `configuration.yaml` nötig.

## Karte konfigurieren

```yaml
type: custom:ais-map-card
title: Meine Flotte
lat: 54.0
lon: 10.0
zoom: 8
height: 600px
# entities:           # optional — leer = alle ais_* tracker
#   - device_tracker.ais_123456789_tracker
```

## Kartenfarben (Navigationsstatus)

| Farbe | Status |
|-------|--------|
| Blau  | Fahrt unter Motor |
| Orange | Vor Anker |
| Lila | Festgemacht |
| Rot | Auf Grund |
| Grün | Beim Fischen |

## API-Schlüssel

Kostenlos bei [aisstream.io](https://aisstream.io) registrieren — kein Kreditkarte nötig.

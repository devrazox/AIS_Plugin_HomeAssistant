"""
Lokaler AISstream-Verbindungstest.

Verwendung:
    python test_aisstream.py <API_KEY> [MMSI]

Testet verschiedene Subscription-Formate und zeigt welche funktionieren.
Feldnamen laut offizieller Doku (https://aisstream.io/documentation):
  - FilterMessageTypes  (nicht MessageTypes)
  - FiltersShipMMSI     (nicht MMSI; Strings, nicht Integers)
  - BoundingBoxes       (immer erforderlich)
"""
import asyncio
import json
import ssl
import sys

try:
    import websockets
except ImportError:
    print("websockets nicht installiert. Bitte: pip install websockets")
    sys.exit(1)

WS_URL = "wss://stream.aisstream.io/v0/stream"
TIMEOUT = 8  # Sekunden auf die erste Nachricht warten


async def test_subscription(api_key: str, label: str, msg: dict, timeout: int = TIMEOUT):
    ssl_ctx = ssl.create_default_context()
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    payload = {k: v for k, v in msg.items() if k != "APIKey"}
    print(f"  Payload: {json.dumps(payload, indent=2)}")
    try:
        async with websockets.connect(WS_URL, ssl=ssl_ctx, ping_interval=None, ping_timeout=None, open_timeout=15) as ws:
            await ws.send(json.dumps(msg))
            print(f"  --> Verbunden, Subscribe gesendet")
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                data = json.loads(raw)
                if "error" in data:
                    print(f"  [FEHLER] Server antwortet: {data['error']}")
                else:
                    msg_type = data.get("MessageType", "?")
                    mmsi = data.get("MetaData", {}).get("MMSI", "?")
                    print(f"  [OK] Erste Nachricht empfangen: MessageType={msg_type}, MMSI={mmsi}")
            except asyncio.TimeoutError:
                print(f"  [TIMEOUT] Keine Nachricht in {timeout}s — Verbindung stabil aber kein Schiff in Range")
    except Exception as e:
        print(f"  [DISCONNECT] {type(e).__name__}: {e}")


async def main(api_key: str, mmsi: str | None):
    kiel_bbox  = [[[54.0, 8.0], [55.5, 11.0]]]   # Kieler Bucht
    world_bbox = [[[-90, -180], [90, 180]]]

    tests = [
        (
            "1) FilterMessageTypes + Kieler Bucht",
            {"APIKey": api_key, "FilterMessageTypes": ["PositionReport"], "BoundingBoxes": kiel_bbox},
        ),
        (
            "2) Alle Typen (wie Integration) + Kieler Bucht",
            {"APIKey": api_key, "FilterMessageTypes": [
                "PositionReport", "ShipStaticData",
                "StandardClassBPositionReport", "ExtendedClassBPositionReport",
                "StaticDataReport", "LongRangeAisBroadcastMessage",
            ], "BoundingBoxes": kiel_bbox},
        ),
        (
            "3) Alle Typen + weltweite BoundingBox",
            {"APIKey": api_key, "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"],
             "BoundingBoxes": world_bbox},
        ),
    ]

    if mmsi:
        tests.append((
            f"4) FiltersShipMMSI (String) + weltweite BoundingBox — MMSI {mmsi}",
            {"APIKey": api_key,
             "FilterMessageTypes": ["PositionReport", "ShipStaticData",
                                    "StandardClassBPositionReport", "StaticDataReport"],
             "BoundingBoxes": world_bbox,
             "FiltersShipMMSI": [str(mmsi)]},
        ))

    for label, payload in tests:
        await test_subscription(api_key, label, payload)

    print(f"\n{'='*60}")
    print("Tests abgeschlossen.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    api_key = sys.argv[1]
    mmsi = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(main(api_key, mmsi))

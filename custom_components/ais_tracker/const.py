DOMAIN = "ais_tracker"

CONF_API_KEY = "api_key"
CONF_FLEET_MODE = "fleet_mode"
CONF_VESSELS = "vessels"
CONF_BOUNDING_BOX = "bounding_box"

FLEET_MODE_GLOBAL = "global"
FLEET_MODE_REGION = "region"
FLEET_MODE_LIST = "list"

FLEET_MODES = [FLEET_MODE_GLOBAL, FLEET_MODE_REGION, FLEET_MODE_LIST]

AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"
AISSTREAM_REST_URL = "https://api.aisstream.io/v0"

# AIS navigation status codes
NAV_STATUS = {
    0: "Under way (engine)",
    1: "At anchor",
    2: "Not under command",
    3: "Restricted manoeuvrability",
    4: "Constrained by draught",
    5: "Moored",
    6: "Aground",
    7: "Engaged in fishing",
    8: "Under way (sailing)",
    15: "Undefined",
}

# AIS ship type codes (simplified)
SHIP_TYPES = {
    0: "Unknown",
    20: "WIG",
    30: "Fishing",
    31: "Towing",
    32: "Towing (large)",
    33: "Dredging",
    34: "Diving ops",
    35: "Military ops",
    36: "Sailing",
    37: "Pleasure craft",
    40: "HSC",
    50: "Pilot vessel",
    51: "SAR",
    52: "Tug",
    53: "Port tender",
    55: "Law enforcement",
    60: "Passenger",
    70: "Cargo",
    80: "Tanker",
    90: "Other",
}

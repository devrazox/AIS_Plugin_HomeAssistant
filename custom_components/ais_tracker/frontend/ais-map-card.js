/**
 * AIS Ship Tracker — OpenSeaMap Lovelace Card
 *
 * Zeigt alle device_tracker.ais_* Entitäten als Schiffssymbole auf einer
 * OpenSeaMap-Seekarte (Tiefenangaben, Häfen, Betonnung).
 *
 * Konfiguration (in der Karte):
 *   type: custom:ais-map-card
 *   title: Meine Flotte         (optional)
 *   lat: 54.0                   (Karten-Mittelpunkt, optional)
 *   lon: 10.0
 *   zoom: 8
 *   entities:                   (optional — leer = alle ais_* tracker)
 *     - device_tracker.ais_123456789_tracker
 */

const LEAFLET_CSS = "/ais_tracker/leaflet.css";
const LEAFLET_JS  = "/ais_tracker/leaflet.js";

const OSM_TILE   = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const OSEA_TILE  = "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png";

const OSM_ATTR   = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const OSEA_ATTR  = '&copy; <a href="https://www.openseamap.org">OpenSeaMap</a>';

// Load a script once, return a promise
function loadScript(src) {
  if (document.querySelector(`script[src="${src}"]`)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

function loadCss(href) {
  if (document.querySelector(`link[href="${href}"]`)) return;
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = href;
  document.head.appendChild(l);
}

// SVG ship icon — rotated by heading/COG
function shipIcon(heading, color = "#1565C0") {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="-14 -14 28 28">
      <g transform="rotate(${heading})">
        <polygon points="0,-12 6,10 0,6 -6,10" fill="${color}" stroke="white" stroke-width="1.5"/>
      </g>
    </svg>`;
  return L.divIcon({
    html: svg,
    className: "",
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });
}

function navStatusColor(status) {
  if (!status) return "#1565C0";
  const s = status.toLowerCase();
  if (s.includes("anchor")) return "#FF8F00";
  if (s.includes("moored"))  return "#6A1B9A";
  if (s.includes("aground")) return "#B71C1C";
  if (s.includes("fishing")) return "#1B5E20";
  return "#1565C0";
}

function formatPopup(name, attrs) {
  const rows = [
    ["MMSI",          attrs.mmsi],
    ["Geschw. (SOG)", attrs.sog != null ? `${attrs.sog} kn` : null],
    ["Kurs (COG)",    attrs.cog != null ? `${attrs.cog}°`  : null],
    ["Steuerkurs",    attrs.true_heading != null ? `${attrs.true_heading}°` : null],
    ["Status",        attrs.nav_status],
    ["Schiffstyp",    attrs.ship_type],
    ["Flagge",        attrs.flag],
    ["Ziel",          attrs.destination],
    ["ETA",           attrs.eta],
    ["Tiefgang",      attrs.draught != null ? `${attrs.draught} m` : null],
    ["Länge",         attrs.length  != null ? `${attrs.length} m`  : null],
    ["Breite",        attrs.beam    != null ? `${attrs.beam} m`    : null],
    ["Rufzeichen",    attrs.callsign],
    ["IMO",           attrs.imo],
  ].filter(([, v]) => v != null && v !== "" && v !== "None");

  const tableRows = rows.map(([k, v]) =>
    `<tr><td style="padding:2px 6px;color:#666;white-space:nowrap">${k}</td>
         <td style="padding:2px 6px;font-weight:500">${v}</td></tr>`
  ).join("");

  return `
    <div style="font-family:var(--primary-font-family,sans-serif);min-width:180px">
      <div style="font-size:1.1em;font-weight:700;margin-bottom:6px;color:#1565C0">${name}</div>
      <table style="border-collapse:collapse;font-size:.9em">${tableRows}</table>
    </div>`;
}

class AisMapCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._map = null;
    this._markers = {};
    this._ready = false;
    this._hass = null;
    this._config = {};
  }

  setConfig(config) {
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    if (this._ready) this._updateMarkers();
  }

  connectedCallback() {
    this._init();
  }

  async _init() {
    loadCss(LEAFLET_CSS);
    await loadScript(LEAFLET_JS);

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        #map { width: 100%; height: ${this._config.height || "500px"}; border-radius: var(--ha-card-border-radius,12px); overflow:hidden; }
      </style>
      ${this._config.title ? `<ha-card header="${this._config.title}">` : "<ha-card>"}
        <div id="map"></div>
      </ha-card>`;

    const mapEl = this.shadowRoot.getElementById("map");
    const lat  = parseFloat(this._config.lat  ?? 54.0);
    const lon  = parseFloat(this._config.lon  ?? 10.0);
    const zoom = parseInt(this._config.zoom   ?? 8, 10);

    this._map = L.map(mapEl).setView([lat, lon], zoom);

    L.tileLayer(OSM_TILE,  { attribution: OSM_ATTR,  maxZoom: 19 }).addTo(this._map);
    L.tileLayer(OSEA_TILE, { attribution: OSEA_ATTR, maxZoom: 19, opacity: 1 }).addTo(this._map);

    // Shadow DOM container size is unknown to Leaflet on first render
    setTimeout(() => this._map.invalidateSize(), 100);

    this._ready = true;
    if (this._hass) this._updateMarkers();
  }

  _getTrackerEntities() {
    if (!this._hass) return [];
    const { entities } = this._config;
    if (entities && entities.length) {
      return entities
        .map(id => this._hass.states[id])
        .filter(Boolean);
    }
    // Auto-discover all ais_tracker device_trackers
    return Object.values(this._hass.states).filter(
      s => s.entity_id.startsWith("device_tracker.ais_") && s.entity_id.endsWith("_tracker")
    );
  }

  _updateMarkers() {
    const entities = this._getTrackerEntities();
    const seen = new Set();

    for (const entity of entities) {
      const { attributes, state } = entity;
      const lat = parseFloat(attributes.latitude  ?? attributes.gps?.[0]);
      const lon = parseFloat(attributes.longitude ?? attributes.gps?.[1]);
      if (!lat || !lon || isNaN(lat) || isNaN(lon)) continue;

      const id   = entity.entity_id;
      const name = attributes.friendly_name || entity.entity_id;
      const heading = attributes.true_heading ?? attributes.cog ?? 0;
      const color   = navStatusColor(attributes.nav_status);
      seen.add(id);

      if (this._markers[id]) {
        this._markers[id].setLatLng([lat, lon]);
        this._markers[id].setIcon(shipIcon(heading, color));
        this._markers[id].getPopup()?.setContent(formatPopup(name, attributes));
      } else {
        const marker = L.marker([lat, lon], { icon: shipIcon(heading, color) })
          .bindPopup(formatPopup(name, attributes), { maxWidth: 300 })
          .addTo(this._map);
        this._markers[id] = marker;
      }
    }

    // Remove markers for gone vessels
    for (const id of Object.keys(this._markers)) {
      if (!seen.has(id)) {
        this._markers[id].remove();
        delete this._markers[id];
      }
    }
  }

  getCardSize() {
    return 6;
  }

  static getStubConfig() {
    return { lat: 54.0, lon: 10.0, zoom: 8, height: "500px" };
  }
}

customElements.define("ais-map-card", AisMapCard);

// Register card with HACS Lovelace card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: "ais-map-card",
  name: "AIS OpenSeaMap Card",
  description: "Zeigt AIS-Schiffe auf einer Seekarte (OpenSeaMap) mit Tiefenangaben, Häfen und Betonnung.",
  preview: false,
});

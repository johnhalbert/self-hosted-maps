const fallbackView = {
  center: [-91.56, 31.63],
  zoom: 10,
  bounds: null
};

const FLIGHT_SELECTED_SOURCE_ID = "selected-flight";
const FLIGHT_SELECTED_LAYER_ID = "selected-flight-halo";
const FLIGHT_POLL_INTERVAL_MS = 15000;
const FLIGHT_MAX_PROJECTION_MS = 20000;
const FLIGHT_MAX_POSITION_AGE_MS = 30000;
const FLIGHT_STALE_GRACE_MS = 20000;
const FLIGHT_RENDER_INTERVAL_MS = 1000 / 10;
const FLIGHT_MAX_ANIMATED_FEATURES = 200;
const VESSEL_SOURCE_ID = "aisstream-vessels";
const VESSEL_LAYER_ID = "aisstream-vessel-symbols";
const VESSEL_HIT_LAYER_ID = "aisstream-vessel-hit";
const VESSEL_ICON_IMAGE_ID = "vessel-icon-aisstream";
const VESSEL_POLL_INTERVAL_MS = 30000;
const STREET_IMAGERY_SOURCE_ID = "local-street-imagery";
const STREET_IMAGERY_LAYER_ID = "local-street-imagery-markers";
const STREET_IMAGERY_HIT_LAYER_ID = "local-street-imagery-hit";
const STREET_IMAGERY_DEBOUNCE_MS = 350;
const TRAFFIC_LAYERS = {
  flow: {
    buttonId: "toggleTrafficFlow",
    sourceId: "tomtom-traffic-flow",
    layerId: "tomtom-traffic-flow-layer",
    capabilityKey: "tomTomTrafficFlowEnabled",
    label: "Traffic flow",
    tiles: ["/api/traffic/tomtom/flow/{z}/{x}/{y}.png"],
    opacity: 0.72
  },
  incidents: {
    buttonId: "toggleTrafficIncidents",
    sourceId: "tomtom-traffic-incidents",
    layerId: "tomtom-traffic-incidents-layer",
    capabilityKey: "tomTomTrafficIncidentsEnabled",
    label: "Traffic incidents",
    tiles: ["/api/traffic/tomtom/incidents/{z}/{x}/{y}.png"],
    opacity: 0.9
  }
};
const OSM_OVERLAY_STORAGE_KEY = "shm.osmThemeLayers.v1";
const OPTIONAL_OSM_SOURCE_LAYERS = new Set([
  "boundary",
  "landuse",
  "park",
  "theme_area",
  "theme_line",
  "theme_poi",
  "transportation_name",
  "water_name"
]);
const OSM_OVERLAY_GROUPS = [
  {
    key: "greenSpace",
    buttonId: "toggleOsmGreenSpace",
    label: "Green space",
    layerIds: ["landcover", "landuse", "park", "theme-green-space-area"],
    sourceLayers: ["landcover", "landuse", "park", "theme_area"]
  },
  {
    key: "water",
    buttonId: "toggleOsmWater",
    label: "Water",
    layerIds: ["water", "waterway", "water-label"],
    sourceLayers: ["water", "waterway", "water_name"]
  },
  {
    key: "roads",
    buttonId: "toggleOsmRoads",
    label: "Roads",
    layerIds: ["transportation", "road-label", "theme-mobility-line"],
    sourceLayers: ["transportation", "transportation_name", "theme_line"]
  },
  {
    key: "buildings",
    buttonId: "toggleOsmBuildings",
    label: "Buildings",
    layerIds: ["building"],
    sourceLayers: ["building"]
  },
  {
    key: "boundaries",
    buttonId: "toggleOsmBoundaries",
    label: "Boundaries",
    layerIds: ["boundary"],
    sourceLayers: ["boundary"]
  },
  {
    key: "placesPois",
    buttonId: "toggleOsmPlacesPois",
    label: "Places and POIs",
    layerIds: ["place-label", "theme-poi"],
    sourceLayers: ["place", "theme_poi"]
  }
];
const TERRAIN_SOURCE_ID = "local-terrain-dem";
const TERRAIN_HILLSHADE_LAYER_ID = "local-terrain-hillshade";
const TERRAIN_EXAGGERATION = 1.15;
const FLIGHT_PROVIDER_ALIASES = {
  opensky: "opensky",
  adsbx: "adsbx",
  adsbexchange: "adsbx"
};
const FLIGHT_ICON_SVGS = {
  opensky: `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
      <path
        fill="#f97316"
        stroke="#ffffff"
        stroke-width="0.9"
        stroke-linejoin="round"
        d="M21.44 10.05L13.5 12.18V8.1l3.2-2.28V4.2l-4.7 1.6L9.3 4.2v1.62L12.5 8.1v4.08l-7.94-2.13L3 11.61l9.5 5.16v3.12L10.3 21v1.2l1.7-.42L13.7 22v-1.2l-1.2-1.11v-3.12L22 11.61z"
      />
    </svg>
  `,
  adsbx: `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
      <path
        fill="#7c3aed"
        stroke="#ffffff"
        stroke-width="0.9"
        stroke-linejoin="round"
        d="M12 2.8l2.2 5.3 7 4.3-5.7 1.4 1.9 7.4-5.4-3.5-5.4 3.5 1.9-7.4-5.7-1.4 7-4.3z"
      />
    </svg>
  `
};
const VESSEL_ICON_SVG = `
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
    <path
      fill="#0891b2"
      stroke="#ffffff"
      stroke-width="0.9"
      stroke-linejoin="round"
      d="M12 2.6l5.6 8.8-1.3 8.4L12 21.5l-4.3-1.7-1.3-8.4zM9.1 11.4h5.8L12 6.8z"
    />
  </svg>
`;

function readOsmOverlayVisibility() {
  try {
    const payload = JSON.parse(window.localStorage.getItem(OSM_OVERLAY_STORAGE_KEY) || "{}");
    return payload && typeof payload === "object" && !Array.isArray(payload) ? payload : {};
  } catch (_error) {
    return {};
  }
}

function writeOsmOverlayVisibility() {
  window.localStorage.setItem(OSM_OVERLAY_STORAGE_KEY, JSON.stringify(appState.osmOverlayVisibility));
}

const flightProviders = {
  opensky: {
    buttonId: "toggleOpenSky",
    sourceId: "opensky-flights",
    layerId: "opensky-flight-symbols",
    hitLayerId: "opensky-flight-hit",
    iconImageId: "flight-icon-opensky",
    color: "#f97316",
    minZoom: 4,
    labelPrimaryMinZoom: 6,
    labelFullMinZoom: 8,
    label: "OpenSky",
    capabilityKey: "openSkyEnabled"
  },
  adsbx: {
    buttonId: "toggleAdsbx",
    sourceId: "adsbx-flights",
    layerId: "adsbx-flight-symbols",
    hitLayerId: "adsbx-flight-hit",
    iconImageId: "flight-icon-adsbx",
    color: "#7c3aed",
    minZoom: 6,
    labelPrimaryMinZoom: 8,
    labelFullMinZoom: 10,
    label: "ADS-B Exchange",
    capabilityKey: "adsbExchangeEnabled"
  }
};

function createFlightProviderRuntime() {
  return {
    tracks: new Map(),
    requestSeq: 0,
    abortController: null,
    lastSuccessAtMs: 0,
    lastQueryFootprint: null
  };
}

function reducedMotionEnabled() {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function flightDebugEnabled() {
  const params = new URLSearchParams(window.location.search);
  return params.get("flightDebug") === "1" || window.localStorage.getItem("shm-flight-debug") === "1";
}

const appState = {
  map: null,
  overview: null,
  capabilities: {
    addressSearchEnabled: false,
    openSkyEnabled: false,
    adsbExchangeEnabled: false,
    adsbExchangeConfigured: false,
    aisStreamEnabled: false,
    aisStreamConfigured: false,
    tomTomTrafficEnabled: false,
    tomTomTrafficConfigured: false,
    tomTomTrafficFlowEnabled: false,
    tomTomTrafficIncidentsEnabled: false,
    terrainAvailable: false,
    hillshadeAvailable: false,
    contoursAvailable: false,
    streetImageryEnabled: false,
    streetImageryConfigured: false,
    satelliteCatalogEnabled: false,
    satellitePropagationEnabled: false,
    adminTokenRequired: false
  },
  datasets: [],
  catalog: {
    cachePresent: false,
    items: []
  },
  currentJob: null,
  jobPollHandle: null,
  flightTimers: {},
  flightRuntime: {
    opensky: createFlightProviderRuntime(),
    adsbx: createFlightProviderRuntime()
  },
  flightsEnabled: {
    opensky: false,
    adsbx: false
  },
  flightAnimationFrame: null,
  lastFlightRenderAtMs: 0,
  flightDebug: {
    enabled: flightDebugEnabled(),
    overlay: null,
    tickCount: 0,
    renderCount: 0,
    lastTickAtMs: null,
    lastScheduleAtMs: null,
    lastScheduleDecision: "not-started"
  },
  selectedFlight: null,
  flightPopup: null,
  vesselRuntime: {
    requestSeq: 0,
    abortController: null,
    lastSuccessAtMs: 0,
    features: emptyFeatureCollection()
  },
  vesselsEnabled: false,
  vesselTimer: null,
  selectedVessel: null,
  vesselPopup: null,
  trafficEnabled: {
    flow: false,
    incidents: false
  },
  osmSourceLayers: null,
  osmOverlayVisibility: readOsmOverlayVisibility(),
  imagery: {
    items: [],
    enabled: [],
    activeId: null
  },
  terrainEnabled: false,
  hillshadeEnabled: false,
  streetImagery: {
    enabled: false,
    requestSeq: 0,
    abortController: null,
    refreshTimer: null,
    features: emptyFeatureCollection(),
    selectedItemId: null,
    selectedItem: null
  },
  satelliteCatalogVisible: false,
  suppressFlightPopupClose: false,
  prefersReducedMotion: reducedMotionEnabled(),
  flightMenuOpen: false,
  flightMenuPinned: false,
  flightMenuIgnoreNextFocusOpen: false,
  selectedArea: {
    selectedIds: [],
    availableBoundaryIds: [],
    displayBoundaryIds: [],
    providerFallbackIds: [],
    missingBoundaryIds: [],
    missingItems: [],
    featureCollection: emptyFeatureCollection()
  },
  adminToken: window.localStorage.getItem("shm-admin-token") || "",
  messageTimer: null
};

function emptyFeatureCollection() {
  return { type: "FeatureCollection", features: [] };
}

function showMessage(text, tone = "info") {
  const message = document.getElementById("message");
  if (!message) {
    return;
  }
  clearTimeout(appState.messageTimer);
  message.textContent = text;
  message.className = `message visible ${tone === "info" ? "" : tone}`.trim();
  appState.messageTimer = window.setTimeout(() => {
    message.className = "message";
  }, 5000);
}

function renderViewerNotice(hasInitialBounds) {
  const notice = document.getElementById("viewerNotice");
  if (!notice) {
    return;
  }
  const selectedIds = Array.isArray(appState.selectedArea?.selectedIds)
    ? appState.selectedArea.selectedIds
    : [];
  const displayIds = Array.isArray(appState.selectedArea?.displayBoundaryIds)
    ? appState.selectedArea.displayBoundaryIds
    : [];
  const providerFallbackIds = Array.isArray(appState.selectedArea?.providerFallbackIds)
    ? appState.selectedArea.providerFallbackIds
    : [];
  const missingItems = Array.isArray(appState.selectedArea?.missingItems)
    ? appState.selectedArea.missingItems
    : [];
  let boundaryText = "Selected boundary overlays appear here when available.";
  if (selectedIds.length) {
    const parts = [];
    const missingNames = missingItems
      .map((item) => item?.name || item?.id)
      .filter(Boolean)
      .join(", ");
    if (displayIds.length) {
      parts.push(
        `${displayIds.length} curated display boundar${displayIds.length === 1 ? "y" : "ies"}`
      );
    }
    if (providerFallbackIds.length) {
      parts.push(
        `${providerFallbackIds.length} provider fallback overlay${
          providerFallbackIds.length === 1 ? "" : "s"
        }`
      );
    }
    if (parts.length) {
      boundaryText = `Showing ${parts.join(" and ")} for ${selectedIds.length} selected dataset${
        selectedIds.length === 1 ? "" : "s"
      }.${missingNames ? ` Missing: ${missingNames}.` : ""}`;
    } else {
      boundaryText = missingNames
        ? `No boundary overlays are available yet. Missing: ${missingNames}.`
        : "No boundary overlays are available yet.";
    }
  }
  notice.textContent = hasInitialBounds
    ? `Map framing uses stored data bounds. ${boundaryText}`
    : boundaryText;
  notice.hidden = false;
}

function parseCoordinates(value) {
  const parts = value.split(",").map((part) => Number.parseFloat(part.trim()));
  if (parts.length !== 2 || parts.some((part) => Number.isNaN(part))) {
    return null;
  }
  const [first, second] = parts;
  if (Math.abs(first) <= 90 && Math.abs(second) <= 180) {
    return { lat: first, lng: second };
  }
  if (Math.abs(first) <= 180 && Math.abs(second) <= 90) {
    return { lat: second, lng: first };
  }
  return null;
}

function isValidBounds(bounds) {
  return (
    Array.isArray(bounds) &&
    bounds.length === 2 &&
    bounds.every(
      (corner) =>
        Array.isArray(corner) &&
        corner.length === 2 &&
        corner.every((value) => Number.isFinite(value))
    ) &&
    bounds[0][0] < bounds[1][0] &&
    bounds[0][1] < bounds[1][1]
  );
}

function resolveCurrentAreaBounds(initialBounds) {
  const overviewBounds = appState.overview?.currentBounds;
  if (isValidBounds(overviewBounds)) {
    return overviewBounds;
  }
  return isValidBounds(initialBounds) ? initialBounds : null;
}

function normalizeSelectedAreaData(data) {
  const featureCollection =
    data?.featureCollection && data.featureCollection.type === "FeatureCollection"
      ? data.featureCollection
      : emptyFeatureCollection();
  return {
    selectedIds: Array.isArray(data?.selectedIds) ? data.selectedIds : [],
    availableBoundaryIds: Array.isArray(data?.availableBoundaryIds) ? data.availableBoundaryIds : [],
    displayBoundaryIds: Array.isArray(data?.displayBoundaryIds) ? data.displayBoundaryIds : [],
    providerFallbackIds: Array.isArray(data?.providerFallbackIds) ? data.providerFallbackIds : [],
    missingBoundaryIds: Array.isArray(data?.missingBoundaryIds) ? data.missingBoundaryIds : [],
    missingItems: Array.isArray(data?.missingItems) ? data.missingItems : [],
    featureCollection
  };
}

function applySelectedAreaOverlay() {
  if (!appState.map || !appState.map.isStyleLoaded()) {
    return;
  }
  const source = appState.map.getSource("selectedArea");
  if (source) {
    source.setData(appState.selectedArea.featureCollection);
  }
}

function buildStyle(tilejsonUrl, selectedAreaData, options = {}) {
  const style = {
    version: 8,
    glyphs: "/fonts/{fontstack}/{range}.pbf",
    sources: {
      worldLand: {
        type: "geojson",
        data: "/world-land.geojson"
      },
      selectedArea: {
        type: "geojson",
        data: selectedAreaData
      },
      osm: {
        type: "vector",
        url: tilejsonUrl
      }
    },
    layers: [
      {
        id: "global-ocean",
        type: "background",
        paint: { "background-color": "#c7def2" }
      },
      {
        id: "global-land",
        type: "fill",
        source: "worldLand",
        paint: {
          "fill-color": "#c7ccd3",
          "fill-opacity": 1
        }
      },
      {
        id: "selected-area-fill-provider",
        type: "fill",
        source: "selectedArea",
        filter: ["==", ["get", "overlaySource"], "provider"],
        paint: {
          "fill-color": "#f7f1e5",
          "fill-opacity": 0.74
        }
      },
      {
        id: "selected-area-fill-display",
        type: "fill",
        source: "selectedArea",
        filter: ["==", ["get", "overlaySource"], "display"],
        paint: {
          "fill-color": "#f4efe3",
          "fill-opacity": 1
        }
      },
      {
        id: "landcover",
        type: "fill",
        source: "osm",
        "source-layer": "landcover",
        paint: { "fill-color": "#d8e8c8" }
      },
      {
        id: "landuse",
        type: "fill",
        source: "osm",
        "source-layer": "landuse",
        paint: {
          "fill-color": "#dfe8c8",
          "fill-opacity": 0.55
        }
      },
      {
        id: "park",
        type: "fill",
        source: "osm",
        "source-layer": "park",
        paint: {
          "fill-color": "#cfe6b8",
          "fill-opacity": 0.85
        }
      },
      {
        id: "theme-green-space-area",
        type: "fill",
        source: "osm",
        "source-layer": "theme_area",
        filter: ["==", ["get", "theme"], "green_space"],
        paint: {
          "fill-color": "#b7dc9a",
          "fill-opacity": 0.38
        }
      },
      {
        id: "water",
        type: "fill",
        source: "osm",
        "source-layer": "water",
        paint: { "fill-color": "#9cc7ff" }
      },
      {
        id: "boundary",
        type: "line",
        source: "osm",
        "source-layer": "boundary",
        paint: {
          "line-color": "#6b7280",
          "line-width": 2
        }
      },
      {
        id: "waterway",
        type: "line",
        source: "osm",
        "source-layer": "waterway",
        paint: {
          "line-color": "#76a7ff",
          "line-width": 1.2
        }
      },
      {
        id: "transportation",
        type: "line",
        source: "osm",
        "source-layer": "transportation",
        paint: {
          "line-color": "#666",
          "line-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            6,
            0.5,
            10,
            1.2,
            14,
            2.2
          ]
        }
      },
      {
        id: "theme-mobility-line",
        type: "line",
        source: "osm",
        "source-layer": "theme_line",
        filter: ["==", ["get", "theme"], "mobility"],
        minzoom: 11,
        paint: {
          "line-color": "#0f766e",
          "line-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            11,
            0.7,
            14,
            1.4,
            16,
            2.3
          ],
          "line-dasharray": [1.5, 1]
        }
      },
      {
        id: "building",
        type: "fill",
        source: "osm",
        "source-layer": "building",
        minzoom: 13,
        paint: {
          "fill-color": "#d7c7b5",
          "fill-outline-color": "#b79f8b"
        }
      },
      {
        id: "selected-area-outline-provider",
        type: "line",
        source: "selectedArea",
        filter: ["==", ["get", "overlaySource"], "provider"],
        paint: {
          "line-color": "#d7bb8a",
          "line-width": 2,
          "line-opacity": 0.85,
          "line-dasharray": [2, 1.5]
        }
      },
      {
        id: "selected-area-outline-display",
        type: "line",
        source: "selectedArea",
        filter: ["==", ["get", "overlaySource"], "display"],
        paint: {
          "line-color": "#c4a46d",
          "line-width": 2,
          "line-opacity": 0.8
        }
      },
      {
        id: "water-label",
        type: "symbol",
        source: "osm",
        "source-layer": "water_name",
        layout: {
          "text-field": ["coalesce", ["get", "name:latin"], ["get", "class"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": 12
        },
        paint: {
          "text-color": "#2b6cb0"
        }
      },
      {
        id: "road-label",
        type: "symbol",
        source: "osm",
        "source-layer": "transportation_name",
        minzoom: 10,
        layout: {
          "symbol-placement": "line",
          "text-field": ["coalesce", ["get", "name:latin"], ["get", "ref"], ["get", "class"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11
        },
        paint: {
          "text-color": "#444"
        }
      },
      {
        id: "place-label",
        type: "symbol",
        source: "osm",
        "source-layer": "place",
        layout: {
          "text-field": ["coalesce", ["get", "name:latin"], ["get", "class"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": [
            "interpolate",
            ["linear"],
            ["zoom"],
            4,
            11,
            8,
            13,
            12,
            16
          ]
        },
        paint: {
          "text-color": "#222"
        }
      },
      {
        id: "theme-poi",
        type: "circle",
        source: "osm",
        "source-layer": "theme_poi",
        minzoom: 13,
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            13,
            2.5,
            16,
            5
          ],
          "circle-color": [
            "match",
            ["get", "theme"],
            "food_drink",
            "#f97316",
            "health",
            "#dc2626",
            "education",
            "#2563eb",
            "public_services",
            "#7c3aed",
            "tourism",
            "#0891b2",
            "recreation",
            "#16a34a",
            "#4b5563"
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1
        }
      }
    ]
  };
  return filterUnavailableOsmStyleLayers(style, options.osmSourceLayers);
}

function filterUnavailableOsmStyleLayers(style, osmSourceLayers) {
  if (!(osmSourceLayers instanceof Set)) {
    return style;
  }
  return {
    ...style,
    layers: style.layers.filter((layer) => {
      if (layer.source !== "osm" || !layer["source-layer"]) {
        return true;
      }
      return osmSourceLayers.has(layer["source-layer"]);
    })
  };
}

function extractVectorSourceLayers(tilejson) {
  if (!Array.isArray(tilejson?.vector_layers)) {
    return null;
  }
  return new Set(
    tilejson.vector_layers
      .map((layer) => String(layer?.id || "").trim())
      .filter(Boolean)
  );
}

async function requestJson(url, options = {}, requiresAdmin = false) {
  const headers = {
    Accept: "application/json",
    ...(options.headers || {})
  };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (requiresAdmin && appState.adminToken) {
    headers.Authorization = `Bearer ${appState.adminToken}`;
  }

  const response = await fetch(url, { ...options, headers });
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload || !payload.ok) {
    const error = new Error(payload?.error?.message || `Request failed with status ${response.status}`);
    error.code = payload?.error?.code || "request_failed";
    error.currentJob = payload?.currentJob || null;
    throw error;
  }
  return payload.data;
}

async function requestAdmin(url, options = {}) {
  try {
    return await requestJson(url, options, true);
  } catch (error) {
    if (error.code === "admin_token_required") {
      const token = window.prompt("Enter the Self Hosted Maps admin token.");
      if (token) {
        appState.adminToken = token.trim();
        window.localStorage.setItem("shm-admin-token", appState.adminToken);
        return requestJson(url, options, true);
      }
    }
    throw error;
  }
}

async function safeLoadOverview() {
  try {
    appState.overview = await requestJson("/api/state");
  } catch (error) {
    console.warn("Falling back to default overview data.", error);
    appState.overview = {
      tilejsonUrl: "/data/openmaptiles.json",
      current: {},
      currentBounds: null,
      selected: [],
      currentIds: [],
      selectedIds: [],
      currentIsStale: false,
      missingCurrentDatasetIds: [],
      terrain: {
        terrainAvailable: false,
        hillshadeAvailable: false,
        contoursAvailable: false,
        terrainTileTemplate: null
      }
    };
  }
}

async function safeLoadCapabilities() {
  try {
    appState.capabilities = await requestJson("/api/capabilities");
  } catch (error) {
    console.warn("Falling back to default capabilities.", error);
  }
}

async function safeLoadSelectedArea() {
  try {
    appState.selectedArea = normalizeSelectedAreaData(await requestJson("/api/selected-area"));
  } catch (error) {
    console.warn("Falling back to empty selected-area overlay.", error);
    appState.selectedArea = normalizeSelectedAreaData(null);
  }
}

function chooseInitialImageryId(imageryData) {
  const items = Array.isArray(imageryData?.items) ? imageryData.items.filter((item) => item.available) : [];
  const enabled = Array.isArray(imageryData?.enabled) ? imageryData.enabled : [];
  const enabledMatch = enabled.find((id) => items.some((item) => item.id === id));
  return enabledMatch || null;
}

async function safeLoadImagery() {
  try {
    const imageryData = await requestJson("/api/imagery");
    appState.imagery.items = Array.isArray(imageryData.items) ? imageryData.items : [];
    appState.imagery.enabled = Array.isArray(imageryData.enabled) ? imageryData.enabled : [];
    appState.imagery.activeId = chooseInitialImageryId(imageryData);
  } catch (error) {
    console.warn("Falling back to no offline imagery overlays.", error);
    appState.imagery.items = [];
    appState.imagery.enabled = [];
    appState.imagery.activeId = null;
  }
}

async function loadTileJsonInfo(tilejsonUrl) {
  try {
    const response = await fetch(tilejsonUrl);
    if (!response.ok) {
      throw new Error(`TileJSON request failed with ${response.status}`);
    }
    const tilejson = await response.json();
    const nextView = { ...fallbackView };
    if (Array.isArray(tilejson.center) && tilejson.center.length >= 2) {
      nextView.center = [Number(tilejson.center[0]), Number(tilejson.center[1])];
      if (tilejson.center.length >= 3 && Number.isFinite(Number(tilejson.center[2]))) {
        nextView.zoom = Number(tilejson.center[2]);
      }
    }
    if (Array.isArray(tilejson.bounds) && tilejson.bounds.length === 4) {
      const bounds = tilejson.bounds.map(Number);
      if (bounds.every(Number.isFinite)) {
        nextView.bounds = [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[3]]
        ];
      }
    }
    return {
      view: nextView,
      sourceLayers: extractVectorSourceLayers(tilejson)
    };
  } catch (error) {
    console.warn("Falling back to default map view.", error);
    return {
      view: fallbackView,
      sourceLayers: null
    };
  }
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function toFiniteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizeFlightProviderKey(value) {
  return FLIGHT_PROVIDER_ALIASES[String(value || "").trim().toLowerCase()] || "";
}

function normalizeFlightRecordKey(value) {
  return String(value || "").trim().toLowerCase();
}

function buildFlightEntityKey(providerKey, recordKey) {
  return providerKey && recordKey ? `${providerKey}:${recordKey}` : "";
}

function svgMarkupToImageData(svgMarkup, size = 96) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = size;
      canvas.height = size;
      const context = canvas.getContext("2d");
      context.clearRect(0, 0, size, size);
      context.drawImage(img, 0, 0, size, size);
      resolve(context.getImageData(0, 0, size, size));
    };
    img.onerror = () => reject(new Error("Unable to create aircraft icon."));
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgMarkup.trim())}`;
  });
}

async function registerFlightImages() {
  if (!appState.map) {
    return;
  }
  await Promise.all(
    Object.entries(flightProviders).map(async ([providerKey, provider]) => {
      if (appState.map.hasImage(provider.iconImageId)) {
        return;
      }
      const imageData = await svgMarkupToImageData(FLIGHT_ICON_SVGS[providerKey]);
      appState.map.addImage(provider.iconImageId, imageData, { pixelRatio: 2 });
    })
  );
}

async function registerVesselImage() {
  if (!appState.map || appState.map.hasImage(VESSEL_ICON_IMAGE_ID)) {
    return;
  }
  const imageData = await svgMarkupToImageData(VESSEL_ICON_SVG);
  appState.map.addImage(VESSEL_ICON_IMAGE_ID, imageData, { pixelRatio: 2 });
}

function setFlightSourceData(providerKey, featureCollection) {
  const provider = flightProviders[providerKey];
  const source = appState.map?.getSource(provider.sourceId);
  if (source) {
    source.setData(featureCollection);
  }
}

function setSelectedFlightSource(featureCollection) {
  const source = appState.map?.getSource(FLIGHT_SELECTED_SOURCE_ID);
  if (source) {
    source.setData(featureCollection);
  }
}

function setVesselSourceData(featureCollection) {
  const source = appState.map?.getSource(VESSEL_SOURCE_ID);
  if (source) {
    source.setData(featureCollection);
  }
}

function selectedFlightFeature(lngLat, selectedFlight) {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: lngLat },
    properties: {
      providerColor: flightProviders[selectedFlight.providerKey]?.color || "#2563eb",
      status: selectedFlight.status || "tracked"
    }
  };
}

function ensureFlightLayers() {
  if (!appState.map) {
    return;
  }

  Object.values(flightProviders).forEach((provider) => {
    if (!appState.map.getSource(provider.sourceId)) {
      appState.map.addSource(provider.sourceId, {
        type: "geojson",
        data: emptyFeatureCollection()
      });
    }
  });

  if (!appState.map.getSource(FLIGHT_SELECTED_SOURCE_ID)) {
    appState.map.addSource(FLIGHT_SELECTED_SOURCE_ID, {
      type: "geojson",
      data: emptyFeatureCollection()
    });
  }

  if (!appState.map.getLayer(FLIGHT_SELECTED_LAYER_ID)) {
    appState.map.addLayer({
      id: FLIGHT_SELECTED_LAYER_ID,
      type: "circle",
      source: FLIGHT_SELECTED_SOURCE_ID,
      paint: {
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["zoom"],
          4,
          10,
          8,
          13,
          12,
          17
        ],
        "circle-color": ["coalesce", ["get", "providerColor"], "#2563eb"],
        "circle-opacity": 0.22,
        "circle-stroke-color": ["coalesce", ["get", "providerColor"], "#2563eb"],
        "circle-stroke-width": 2
      }
    });
  }

  Object.values(flightProviders).forEach((provider) => {
    if (!appState.map.getLayer(provider.hitLayerId)) {
      appState.map.addLayer({
        id: provider.hitLayerId,
        type: "circle",
        source: provider.sourceId,
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            provider.minZoom,
            10,
            12,
            16
          ],
          "circle-opacity": 0.01
        }
      });
    }
    if (!appState.map.getLayer(provider.layerId)) {
      appState.map.addLayer({
        id: provider.layerId,
        type: "symbol",
        source: provider.sourceId,
        layout: {
          "icon-image": provider.iconImageId,
          "icon-size": [
            "interpolate",
            ["linear"],
            ["zoom"],
            provider.minZoom,
            0.42,
            10,
            0.55,
            13,
            0.68
          ],
          "icon-rotate": ["+", ["coalesce", ["get", "headingDeg"], 0], 180],
          "icon-rotation-alignment": "map",
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "text-field": [
            "step",
            ["zoom"],
            "",
            provider.labelPrimaryMinZoom,
            ["coalesce", ["get", "labelPrimary"], ""],
            provider.labelFullMinZoom,
            ["coalesce", ["get", "labelFull"], ["get", "labelPrimary"], ""]
          ],
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "text-anchor": "left",
          "text-offset": [1.15, 0],
          "text-optional": true
        },
        paint: {
          "text-color": "#111827",
          "text-halo-color": "rgba(255, 255, 255, 0.96)",
          "text-halo-width": 1.4
        }
      });
    }
  });
}

function ensureVesselLayers() {
  if (!appState.map) {
    return;
  }
  if (!appState.map.getSource(VESSEL_SOURCE_ID)) {
    appState.map.addSource(VESSEL_SOURCE_ID, {
      type: "geojson",
      data: emptyFeatureCollection()
    });
  }
  if (!appState.map.getLayer(VESSEL_HIT_LAYER_ID)) {
    appState.map.addLayer({
      id: VESSEL_HIT_LAYER_ID,
      type: "circle",
      source: VESSEL_SOURCE_ID,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 8, 12, 15],
        "circle-opacity": 0.01
      }
    });
  }
  if (!appState.map.getLayer(VESSEL_LAYER_ID)) {
    appState.map.addLayer({
      id: VESSEL_LAYER_ID,
      type: "symbol",
      source: VESSEL_SOURCE_ID,
      layout: {
        "icon-image": VESSEL_ICON_IMAGE_ID,
        "icon-size": ["interpolate", ["linear"], ["zoom"], 5, 0.42, 10, 0.56, 13, 0.68],
        "icon-rotate": ["coalesce", ["get", "headingDeg"], ["get", "cogDeg"], 0],
        "icon-rotation-alignment": "map",
        "icon-allow-overlap": true,
        "icon-ignore-placement": true,
        "text-field": [
          "step",
          ["zoom"],
          "",
          8,
          ["coalesce", ["get", "labelPrimary"], ""],
          11,
          ["coalesce", ["get", "labelFull"], ["get", "labelPrimary"], ""]
        ],
        "text-font": ["Noto Sans Regular"],
        "text-size": 11,
        "text-anchor": "left",
        "text-offset": [1.15, 0],
        "text-optional": true
      },
      paint: {
        "text-color": "#0f172a",
        "text-halo-color": "rgba(255, 255, 255, 0.96)",
        "text-halo-width": 1.4
      }
    });
  }
}

function ensureTrafficLayer(kind) {
  const config = TRAFFIC_LAYERS[kind];
  if (!appState.map || !config) {
    return;
  }
  if (!appState.map.getSource(config.sourceId)) {
    appState.map.addSource(config.sourceId, {
      type: "raster",
      tiles: config.tiles,
      tileSize: 256,
      minzoom: 0,
      maxzoom: 22,
      attribution: "Traffic data © TomTom"
    });
  }
  if (!appState.map.getLayer(config.layerId)) {
    const beforeId = appState.map.getLayer("water-label") ? "water-label" : undefined;
    appState.map.addLayer(
      {
        id: config.layerId,
        type: "raster",
        source: config.sourceId,
        layout: { visibility: appState.trafficEnabled[kind] ? "visible" : "none" },
        paint: { "raster-opacity": config.opacity }
      },
      beforeId
    );
  }
}

function imagerySourceId(overlayId) {
  return `imagery-${overlayId}`;
}

function imageryLayerId(overlayId) {
  return `imagery-${overlayId}-layer`;
}

function imageryBeforeLayerId() {
  if (!appState.map) {
    return undefined;
  }
  const candidates = [
    "selected-area-outline-provider",
    "selected-area-outline-display",
    "water-label",
    "road-label",
    "place-label"
  ];
  return candidates.find((layerId) => appState.map.getLayer(layerId));
}

function ensureImageryLayer(overlay) {
  if (!appState.map || !overlay?.id || !overlay.available) {
    return;
  }
  const sourceId = imagerySourceId(overlay.id);
  const layerId = imageryLayerId(overlay.id);
  if (!appState.map.getSource(sourceId)) {
    appState.map.addSource(sourceId, {
      type: "raster",
      url: overlay.tilejsonUrl,
      tileSize: overlay.tileSize || 256,
      attribution: overlay.attribution || undefined
    });
  }
  if (!appState.map.getLayer(layerId)) {
    appState.map.addLayer(
      {
        id: layerId,
        type: "raster",
        source: sourceId,
        layout: { visibility: appState.imagery.activeId === overlay.id ? "visible" : "none" },
        paint: { "raster-opacity": overlay.opacity ?? 0.75 }
      },
      imageryBeforeLayerId()
    );
  }
}

function applyImageryOverlays() {
  if (!appState.map || !appState.map.isStyleLoaded()) {
    return;
  }
  appState.imagery.items.forEach((overlay) => {
    ensureImageryLayer(overlay);
    const layerId = imageryLayerId(overlay.id);
    if (appState.map.getLayer(layerId)) {
      appState.map.setLayoutProperty(
        layerId,
        "visibility",
        overlay.id === appState.imagery.activeId ? "visible" : "none"
      );
    }
  });
}

function setTrafficLayerVisibility(kind, visible) {
  const config = TRAFFIC_LAYERS[kind];
  if (!appState.map || !config) {
    return;
  }
  if (visible) {
    ensureTrafficLayer(kind);
  }
  if (appState.map.getLayer(config.layerId)) {
    appState.map.setLayoutProperty(config.layerId, "visibility", visible ? "visible" : "none");
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderImageryControls() {
  const container = document.getElementById("imageryOverlayControls");
  if (!container) {
    return;
  }
  const overlays = appState.imagery.items.filter((item) => item.available);
  if (!overlays.length) {
    container.innerHTML =
      '<button class="flight-button unavailable" type="button" disabled tabindex="-1">Imagery unavailable</button>';
    return;
  }
  container.innerHTML = overlays
    .map((overlay) => {
      const active = overlay.id === appState.imagery.activeId;
      const licenseName = overlay.license?.name || "License details unavailable";
      return `
        <button
          class="flight-button imagery-button ${active ? "active" : ""}"
          type="button"
          data-imagery-id="${escapeHtml(overlay.id)}"
          aria-pressed="${active ? "true" : "false"}"
          tabindex="${appState.flightMenuOpen ? "0" : "-1"}"
          title="${escapeHtml(overlay.usageNotes || overlay.attribution || overlay.name)}"
        >
          ${escapeHtml(overlay.name || overlay.id)}
          <span class="imagery-license">${escapeHtml(licenseName)}</span>
        </button>
      `;
    })
    .join("");
}

function toggleImageryOverlay(overlayId) {
  const overlay = appState.imagery.items.find((item) => item.id === overlayId && item.available);
  if (!overlay) {
    return;
  }
  if (!appState.map || !appState.map.isStyleLoaded()) {
    showMessage("Map is still loading. Try again in a moment.", "warn");
    return;
  }
  appState.imagery.activeId = appState.imagery.activeId === overlayId ? null : overlayId;
  applyImageryOverlays();
  renderImageryControls();
  updateFlightButtons();
}

function terrainMetadata() {
  return appState.overview?.terrain || {};
}

function isTerrainAvailable() {
  return Boolean(appState.capabilities.terrainAvailable && terrainMetadata().terrainAvailable);
}

function isHillshadeAvailable() {
  return Boolean(appState.capabilities.hillshadeAvailable && terrainMetadata().hillshadeAvailable);
}

function ensureTerrainSourceAndLayers() {
  if (!appState.map || !appState.map.isStyleLoaded() || !isTerrainAvailable()) {
    return false;
  }

  const terrain = terrainMetadata();
  if (!terrain.terrainTileTemplate) {
    return false;
  }

  if (!appState.map.getSource(TERRAIN_SOURCE_ID)) {
    appState.map.addSource(TERRAIN_SOURCE_ID, {
      type: "raster-dem",
      tiles: [terrain.terrainTileTemplate],
      tileSize: terrain.tileSize || 256,
      minzoom: terrain.minzoom ?? 0,
      maxzoom: terrain.maxzoom ?? 14,
      encoding: terrain.encoding || "terrarium",
      attribution: terrain.attribution || ""
    });
  }

  if (!appState.map.getLayer(TERRAIN_HILLSHADE_LAYER_ID)) {
    const beforeId = appState.map.getLayer("water-label") ? "water-label" : undefined;
    appState.map.addLayer(
      {
        id: TERRAIN_HILLSHADE_LAYER_ID,
        type: "hillshade",
        source: TERRAIN_SOURCE_ID,
        layout: { visibility: appState.hillshadeEnabled ? "visible" : "none" },
        paint: {
          "hillshade-exaggeration": 0.42,
          "hillshade-shadow-color": "#475569",
          "hillshade-highlight-color": "#f8fafc",
          "hillshade-accent-color": "#94a3b8"
        }
      },
      beforeId
    );
  }
  return true;
}

function setTerrain3dVisibility(visible) {
  if (!appState.map || typeof appState.map.setTerrain !== "function") {
    showMessage("3D terrain is not supported by this MapLibre build.", "warn");
    appState.terrainEnabled = false;
    return;
  }
  if (visible && !ensureTerrainSourceAndLayers()) {
    appState.terrainEnabled = false;
    return;
  }
  appState.map.setTerrain(visible ? { source: TERRAIN_SOURCE_ID, exaggeration: TERRAIN_EXAGGERATION } : null);
}

function setHillshadeVisibility(visible) {
  if (visible && !ensureTerrainSourceAndLayers()) {
    appState.hillshadeEnabled = false;
    return;
  }
  if (appState.map?.getLayer(TERRAIN_HILLSHADE_LAYER_ID)) {
    appState.map.setLayoutProperty(TERRAIN_HILLSHADE_LAYER_ID, "visibility", visible ? "visible" : "none");
  }
}

function isStreetImageryAvailable() {
  return Boolean(appState.capabilities.streetImageryEnabled && appState.capabilities.streetImageryConfigured);
}

function setStreetImagerySourceData(featureCollection) {
  if (!appState.map?.getSource(STREET_IMAGERY_SOURCE_ID)) {
    return;
  }
  appState.map.getSource(STREET_IMAGERY_SOURCE_ID).setData(featureCollection || emptyFeatureCollection());
}

function ensureStreetImageryLayers() {
  if (!appState.map) {
    return;
  }
  if (!appState.map.getSource(STREET_IMAGERY_SOURCE_ID)) {
    appState.map.addSource(STREET_IMAGERY_SOURCE_ID, {
      type: "geojson",
      data: appState.streetImagery.features || emptyFeatureCollection()
    });
  }
  if (!appState.map.getLayer(STREET_IMAGERY_HIT_LAYER_ID)) {
    appState.map.addLayer({
      id: STREET_IMAGERY_HIT_LAYER_ID,
      type: "circle",
      source: STREET_IMAGERY_SOURCE_ID,
      layout: { visibility: appState.streetImagery.enabled ? "visible" : "none" },
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 14, 16, 22],
        "circle-opacity": 0.01
      }
    });
  }
  if (!appState.map.getLayer(STREET_IMAGERY_LAYER_ID)) {
    appState.map.addLayer({
      id: STREET_IMAGERY_LAYER_ID,
      type: "circle",
      source: STREET_IMAGERY_SOURCE_ID,
      layout: { visibility: appState.streetImagery.enabled ? "visible" : "none" },
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 5, 16, 8],
        "circle-color": "#16a34a",
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
        "circle-opacity": 0.92
      }
    });
  }
}

function setStreetImageryLayerVisibility(visible) {
  if (!appState.map) {
    return;
  }
  if (visible) {
    ensureStreetImageryLayers();
  }
  [STREET_IMAGERY_HIT_LAYER_ID, STREET_IMAGERY_LAYER_ID].forEach((layerId) => {
    if (appState.map.getLayer(layerId)) {
      appState.map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
    }
  });
}

function currentStreetImageryQuery() {
  const bounds = appState.map.getBounds();
  return {
    bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]
      .map((value) => value.toFixed(6))
      .join(","),
    limit: appState.capabilities.streetImageryMaxResults || 200
  };
}

async function refreshStreetImagery(suppressErrors = false) {
  if (!appState.streetImagery.enabled || !appState.map || !appState.map.isStyleLoaded()) {
    return;
  }
  appState.streetImagery.abortController?.abort();
  appState.streetImagery.requestSeq += 1;
  const requestSeq = appState.streetImagery.requestSeq;
  const controller = new AbortController();
  appState.streetImagery.abortController = controller;
  try {
    const query = currentStreetImageryQuery();
    const data = await requestJson(`/api/street-imagery/local/coverage?${new URLSearchParams(query).toString()}`, {
      signal: controller.signal
    });
    if (requestSeq !== appState.streetImagery.requestSeq || controller.signal.aborted || !appState.streetImagery.enabled) {
      return;
    }
    appState.streetImagery.features = data || emptyFeatureCollection();
    setStreetImagerySourceData(appState.streetImagery.features);
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    if (!suppressErrors) {
      showMessage(error.message, "warn");
    }
  }
}

function scheduleStreetImageryRefresh(suppressErrors = true) {
  window.clearTimeout(appState.streetImagery.refreshTimer);
  appState.streetImagery.refreshTimer = window.setTimeout(() => {
    refreshStreetImagery(suppressErrors);
  }, STREET_IMAGERY_DEBOUNCE_MS);
}

function closeStreetImageryPanel() {
  appState.streetImagery.selectedItemId = null;
  appState.streetImagery.selectedItem = null;
  const panel = document.getElementById("streetImageryPanel");
  if (panel) {
    panel.hidden = true;
    panel.replaceChildren();
  }
}

function renderStreetImageryPanel() {
  const panel = document.getElementById("streetImageryPanel");
  const item = appState.streetImagery.selectedItem;
  if (!panel || !item) {
    return;
  }
  panel.replaceChildren();
  panel.hidden = false;

  const header = document.createElement("div");
  header.className = "street-imagery-panel-header";
  const titleWrap = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.title || "Street imagery";
  const badge = document.createElement("span");
  badge.className = "street-imagery-badge";
  badge.textContent = "Local owner-controlled";
  titleWrap.append(title, badge);
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "street-imagery-close";
  closeButton.textContent = "Close";
  closeButton.addEventListener("click", closeStreetImageryPanel);
  header.append(titleWrap, closeButton);
  panel.append(header);

  const image = document.createElement("img");
  image.className = "street-imagery-image";
  image.alt = item.title || "Local street imagery";
  image.src = item.imageUrl;
  panel.append(image);

  const details = document.createElement("div");
  details.className = "street-imagery-details";
  [
    popupRow("Captured", item.capturedAt),
    popupRow("Heading", item.headingDeg != null ? `${Math.round(item.headingDeg)} deg` : null),
    popupRow("Attribution", item.attribution),
    popupRow("License", item.license?.name),
    popupRow("Location", item.privacy?.exactLocationAllowed === false ? "Approximate" : "Exact approved"),
    popupRow("Redaction", item.privacy?.redactionState || "Publishable")
  ]
    .filter(Boolean)
    .forEach((row) => details.append(row));
  panel.append(details);

  if (item.prevItemId || item.nextItemId) {
    const nav = document.createElement("div");
    nav.className = "street-imagery-nav";
    [
      ["Previous", item.prevItemId],
      ["Next", item.nextItemId]
    ].forEach(([label, itemId]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.disabled = !itemId;
      if (itemId) {
        button.addEventListener("click", () => loadStreetImageryItem(itemId));
      }
      nav.append(button);
    });
    panel.append(nav);
  }
}

function renderStreetImageryLoading(itemId) {
  const panel = document.getElementById("streetImageryPanel");
  if (!panel) {
    return;
  }
  panel.hidden = false;
  const loading = document.createElement("div");
  loading.className = "street-imagery-empty";
  loading.textContent = `Loading imagery ${itemId}...`;
  panel.replaceChildren(loading);
}

async function loadStreetImageryItem(itemId) {
  if (!itemId) {
    return;
  }
  appState.streetImagery.selectedItemId = itemId;
  appState.streetImagery.selectedItem = null;
  renderStreetImageryLoading(itemId);
  try {
    const detail = await requestJson(`/api/street-imagery/local/items/${encodeURIComponent(itemId)}`);
    if (appState.streetImagery.selectedItemId !== itemId) {
      return;
    }
    appState.streetImagery.selectedItem = detail;
    renderStreetImageryPanel();
  } catch (error) {
    showMessage(error.message, "warn");
    closeStreetImageryPanel();
  }
}

function selectStreetImageryFeature(feature) {
  const itemId = feature?.properties?.id;
  if (itemId) {
    loadStreetImageryItem(itemId);
  }
}

function stopStreetImagery() {
  window.clearTimeout(appState.streetImagery.refreshTimer);
  appState.streetImagery.abortController?.abort();
  appState.streetImagery.features = emptyFeatureCollection();
  setStreetImagerySourceData(emptyFeatureCollection());
  setStreetImageryLayerVisibility(false);
  closeStreetImageryPanel();
}

function toggleStreetImagery() {
  if (!isStreetImageryAvailable()) {
    return;
  }
  if (!appState.map || !appState.map.isStyleLoaded()) {
    showMessage("Map is still loading. Try again in a moment.", "warn");
    return;
  }
  appState.streetImagery.enabled = !appState.streetImagery.enabled;
  setStreetImageryLayerVisibility(appState.streetImagery.enabled);
  updateFlightButtons();
  if (appState.streetImagery.enabled) {
    refreshStreetImagery();
  } else {
    stopStreetImagery();
  }
}

function flightMenuElements() {
  return {
    controls: document.getElementById("flightControls"),
    toggle: document.getElementById("flightMenuToggle"),
    panel: document.getElementById("flightMenuPanel"),
    buttons: {
      opensky: document.getElementById(flightProviders.opensky.buttonId),
      adsbx: document.getElementById(flightProviders.adsbx.buttonId),
      aisstream: document.getElementById("toggleAisVessels"),
      trafficFlow: document.getElementById(TRAFFIC_LAYERS.flow.buttonId),
      trafficIncidents: document.getElementById(TRAFFIC_LAYERS.incidents.buttonId),
      terrain3d: document.getElementById("toggleTerrain3d"),
      hillshade: document.getElementById("toggleHillshade"),
      streetImagery: document.getElementById("toggleStreetImagery"),
      satelliteCatalog: document.getElementById("showSatelliteCatalog")
    }
  };
}

function isFlightProviderAvailable(providerKey) {
  return Boolean(appState.capabilities[flightProviders[providerKey].capabilityKey]);
}

function isVesselProviderAvailable() {
  return Boolean(appState.capabilities.aisStreamEnabled);
}

function isTrafficLayerAvailable(kind) {
  return Boolean(appState.capabilities[TRAFFIC_LAYERS[kind]?.capabilityKey]);
}

function isSatelliteCatalogAvailable() {
  return Boolean(appState.capabilities.satelliteCatalogEnabled);
}

function syncFlightMenuState() {
  const { controls, toggle, panel, buttons } = flightMenuElements();
  if (!controls || !toggle || !panel) {
    return;
  }

  controls.dataset.open = appState.flightMenuOpen ? "true" : "false";
  controls.dataset.pinned = appState.flightMenuPinned ? "true" : "false";
  toggle.setAttribute("aria-expanded", appState.flightMenuOpen ? "true" : "false");
  panel.setAttribute("aria-hidden", appState.flightMenuOpen ? "false" : "true");
  if ("inert" in panel) {
    panel.inert = !appState.flightMenuOpen;
  }
  Object.values(buttons).forEach((button) => {
    if (!button) {
      return;
    }
    button.tabIndex = appState.flightMenuOpen && !button.disabled ? 0 : -1;
  });
  document.querySelectorAll("#imageryOverlayControls button, #flightMenuPanel .osm-layer-button").forEach((button) => {
    button.tabIndex = appState.flightMenuOpen && !button.disabled ? 0 : -1;
  });
}

function setFlightMenuState(open, options = {}) {
  appState.flightMenuOpen = open;
  appState.flightMenuPinned = open ? Boolean(options.pinned) : false;
  syncFlightMenuState();
  if (options.focusToggle) {
    flightMenuElements().toggle?.focus();
  }
}

function openFlightMenu(options = {}) {
  setFlightMenuState(true, { pinned: options.pinned ?? appState.flightMenuPinned });
}

function closeFlightMenu(options = {}) {
  if (options.suppressNextFocusOpen) {
    appState.flightMenuIgnoreNextFocusOpen = true;
  }
  setFlightMenuState(false, { focusToggle: options.focusToggle === true });
}

function updateFlightButtons() {
  const { toggle, buttons } = flightMenuElements();
  Object.entries(flightProviders).forEach(([providerKey, provider]) => {
    const button = buttons[providerKey];
    if (!button) {
      return;
    }

    const available = isFlightProviderAvailable(providerKey);
    const active = appState.flightsEnabled[providerKey];
    button.disabled = !available;
    button.classList.toggle("active", available && active);
    button.classList.toggle("unavailable", !available);
    button.setAttribute("aria-pressed", available && active ? "true" : "false");
    button.textContent = available ? provider.label : `${provider.label} (Unavailable)`;
  });

  if (buttons.aisstream) {
    const available = isVesselProviderAvailable();
    buttons.aisstream.disabled = !available;
    buttons.aisstream.classList.toggle("active", available && appState.vesselsEnabled);
    buttons.aisstream.classList.toggle("unavailable", !available);
    buttons.aisstream.setAttribute("aria-pressed", available && appState.vesselsEnabled ? "true" : "false");
    buttons.aisstream.textContent = available ? "AIS vessels" : "AIS vessels (Unavailable)";
  }

  Object.entries(TRAFFIC_LAYERS).forEach(([kind, config]) => {
    const buttonKey = kind === "flow" ? "trafficFlow" : "trafficIncidents";
    const button = buttons[buttonKey];
    if (!button) {
      return;
    }
    const available = isTrafficLayerAvailable(kind);
    const active = appState.trafficEnabled[kind];
    button.disabled = !available;
    button.classList.toggle("active", available && active);
    button.classList.toggle("unavailable", !available);
    button.setAttribute("aria-pressed", available && active ? "true" : "false");
    button.textContent = available ? config.label : `${config.label} (Unavailable)`;
  });

  renderImageryControls();

  if (buttons.terrain3d) {
    const available = isTerrainAvailable();
    buttons.terrain3d.disabled = !available;
    buttons.terrain3d.classList.toggle("active", available && appState.terrainEnabled);
    buttons.terrain3d.classList.toggle("unavailable", !available);
    buttons.terrain3d.setAttribute("aria-pressed", available && appState.terrainEnabled ? "true" : "false");
    buttons.terrain3d.textContent = available ? "3D terrain" : "3D terrain (Unavailable)";
  }

  if (buttons.hillshade) {
    const available = isHillshadeAvailable();
    buttons.hillshade.disabled = !available;
    buttons.hillshade.classList.toggle("active", available && appState.hillshadeEnabled);
    buttons.hillshade.classList.toggle("unavailable", !available);
    buttons.hillshade.setAttribute("aria-pressed", available && appState.hillshadeEnabled ? "true" : "false");
    buttons.hillshade.textContent = available ? "Hillshade" : "Hillshade (Unavailable)";
  }

  if (buttons.streetImagery) {
    const available = isStreetImageryAvailable();
    buttons.streetImagery.disabled = !available;
    buttons.streetImagery.classList.toggle("active", available && appState.streetImagery.enabled);
    buttons.streetImagery.classList.toggle("unavailable", !available);
    buttons.streetImagery.setAttribute(
      "aria-pressed",
      available && appState.streetImagery.enabled ? "true" : "false"
    );
    buttons.streetImagery.textContent = available ? "Street imagery" : "Street imagery (Unavailable)";
  }

  if (buttons.satelliteCatalog) {
    const available = isSatelliteCatalogAvailable();
    buttons.satelliteCatalog.disabled = !available;
    buttons.satelliteCatalog.classList.toggle("active", available && appState.satelliteCatalogVisible);
    buttons.satelliteCatalog.classList.toggle("unavailable", !available);
    buttons.satelliteCatalog.setAttribute(
      "aria-pressed",
      available && appState.satelliteCatalogVisible ? "true" : "false"
    );
    buttons.satelliteCatalog.textContent = available
      ? "Satellite catalog only"
      : "Satellite catalog only (Unavailable)";
    buttons.satelliteCatalog.title = "Cached orbital elements only; v1 does not calculate or draw positions.";
  }

  if (toggle) {
    const imageryAvailable = appState.imagery.items.some((item) => item.available);
    const terrainAvailable = isTerrainAvailable();
    const hillshadeAvailable = isHillshadeAvailable();
    const anyActive =
      Object.keys(flightProviders).some((providerKey) => appState.flightsEnabled[providerKey]) ||
      appState.vesselsEnabled ||
      Object.values(appState.trafficEnabled).some(Boolean) ||
      Boolean(appState.imagery.activeId) ||
      appState.terrainEnabled ||
      appState.hillshadeEnabled ||
      appState.streetImagery.enabled ||
      appState.satelliteCatalogVisible;
    const anyAvailable = Object.keys(flightProviders).some((providerKey) =>
      isFlightProviderAvailable(providerKey)
    ) || isVesselProviderAvailable() || Object.keys(TRAFFIC_LAYERS).some((kind) => isTrafficLayerAvailable(kind)) ||
      imageryAvailable || terrainAvailable || hillshadeAvailable || isStreetImageryAvailable() || isSatelliteCatalogAvailable();
    toggle.dataset.state = anyActive ? "active" : anyAvailable ? "idle" : "unavailable";
  }

  syncFlightMenuState();
}

function osmMenuElements() {
  return {
    buttons: Object.fromEntries(
      OSM_OVERLAY_GROUPS.map((group) => [group.key, document.getElementById(group.buttonId)])
    )
  };
}

function isOsmSourceLayerAvailable(sourceLayer) {
  return !(appState.osmSourceLayers instanceof Set) || appState.osmSourceLayers.has(sourceLayer);
}

function osmOverlayGroupLayerIds(group) {
  if (!appState.map) {
    return [];
  }
  return group.layerIds.filter((layerId) => appState.map.getLayer(layerId));
}

function isOsmOverlayGroupAvailable(group) {
  return group.sourceLayers.some(isOsmSourceLayerAvailable) && osmOverlayGroupLayerIds(group).length > 0;
}

function getOsmOverlayVisibility(groupKey) {
  const value = appState.osmOverlayVisibility[groupKey];
  return typeof value === "boolean" ? value : true;
}

function setOsmOverlayGroupVisibility(group, visible) {
  osmOverlayGroupLayerIds(group).forEach((layerId) => {
    appState.map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
  });
}

function applyOsmOverlayVisibility() {
  OSM_OVERLAY_GROUPS.forEach((group) => {
    if (isOsmOverlayGroupAvailable(group)) {
      setOsmOverlayGroupVisibility(group, getOsmOverlayVisibility(group.key));
    }
  });
  updateOsmOverlayButtons();
}

function updateOsmMenuState() {
  const { buttons } = osmMenuElements();
  Object.values(buttons).forEach((button) => {
    if (button) {
      button.tabIndex = appState.flightMenuOpen && !button.disabled ? 0 : -1;
    }
  });
}

function updateOsmOverlayButtons() {
  const { buttons } = osmMenuElements();
  OSM_OVERLAY_GROUPS.forEach((group) => {
    const button = buttons[group.key];
    if (!button) {
      return;
    }
    const available = isOsmOverlayGroupAvailable(group);
    const active = available && getOsmOverlayVisibility(group.key);
    button.disabled = !available;
    button.classList.toggle("active", active);
    button.classList.toggle("unavailable", !available);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    button.textContent = available ? group.label : `${group.label} (Unavailable)`;
  });
  updateOsmMenuState();
}

function toggleOsmOverlayGroup(groupKey) {
  const group = OSM_OVERLAY_GROUPS.find((candidate) => candidate.key === groupKey);
  if (!group || !isOsmOverlayGroupAvailable(group)) {
    return;
  }
  const visible = !getOsmOverlayVisibility(group.key);
  appState.osmOverlayVisibility[group.key] = visible;
  writeOsmOverlayVisibility();
  setOsmOverlayGroupVisibility(group, visible);
  updateOsmOverlayButtons();
}

function buildFlightRequest(providerKey) {
  if (providerKey === "opensky") {
    const query = currentBoundsQuery();
    return {
      url: `/api/flights/opensky?${new URLSearchParams(query).toString()}`,
      footprint: {
        type: "bbox",
        south: query.lamin,
        west: query.lomin,
        north: query.lamax,
        east: query.lomax
      }
    };
  }
  const query = currentAdsbQuery();
  return {
    url: `/api/flights/adsbx?${new URLSearchParams(query).toString()}`,
    footprint: {
      type: "radius",
      lat: query.lat,
      lng: query.lng,
      distNm: query.dist
    }
  };
}

function queryFootprintContains(footprint, lngLat) {
  if (!footprint || !Array.isArray(lngLat) || lngLat.length !== 2) {
    return true;
  }
  const [lng, lat] = lngLat;
  if (footprint.type === "bbox") {
    return (
      lng >= footprint.west &&
      lng <= footprint.east &&
      lat >= footprint.south &&
      lat <= footprint.north
    );
  }
  if (footprint.type === "radius") {
    return distanceNm(lat, lng, footprint.lat, footprint.lng) <= footprint.distNm;
  }
  return true;
}

function radians(value) {
  return (value * Math.PI) / 180;
}

function degrees(value) {
  return (value * 180) / Math.PI;
}

function projectLngLat(lngLat, headingDeg, distanceMeters) {
  const [lng, lat] = lngLat;
  const angularDistance = distanceMeters / 6378137;
  const heading = radians(headingDeg);
  const lat1 = radians(lat);
  const lng1 = radians(lng);
  const sinLat1 = Math.sin(lat1);
  const cosLat1 = Math.cos(lat1);
  const sinAngular = Math.sin(angularDistance);
  const cosAngular = Math.cos(angularDistance);
  const sinLat2 = sinLat1 * cosAngular + cosLat1 * sinAngular * Math.cos(heading);
  const lat2 = Math.asin(clamp(sinLat2, -1, 1));
  const lng2 =
    lng1 +
    Math.atan2(
      Math.sin(heading) * sinAngular * cosLat1,
      cosAngular - sinLat1 * Math.sin(lat2)
    );
  return [((degrees(lng2) + 540) % 360) - 180, degrees(lat2)];
}

function flightProjectionBlockReason(track) {
  if (!track) {
    return "missing-track";
  }
  if (track.status !== "tracked") {
    return `status:${track.status || "unknown"}`;
  }
  if (track.properties.onGround) {
    return "on-ground";
  }
  if (toFiniteNumber(track.properties.groundSpeedMps) === null) {
    return "missing-speed";
  }
  if (toFiniteNumber(track.properties.headingDeg) === null) {
    return "missing-heading";
  }
  const positionAgeMsAtFetch = toFiniteNumber(track.properties.positionAgeMsAtFetch);
  if (positionAgeMsAtFetch !== null && positionAgeMsAtFetch > FLIGHT_MAX_POSITION_AGE_MS) {
    return "stale-position";
  }
  if (!Number.isFinite(track.deadReckonStartedAtMs)) {
    return "missing-dead-reckon-start";
  }
  return null;
}

function canProjectTrack(track) {
  return flightProjectionBlockReason(track) === null;
}

function computeTrackTargetLngLat(track, nowMs) {
  if (!canProjectTrack(track)) {
    return track.reportedLngLat;
  }
  const groundSpeedMps = toFiniteNumber(track.properties.groundSpeedMps);
  const headingDeg = toFiniteNumber(track.properties.headingDeg);
  const elapsedMs = clamp(nowMs - track.deadReckonStartedAtMs, 0, FLIGHT_MAX_PROJECTION_MS);
  const distanceMeters = groundSpeedMps * (elapsedMs / 1000);
  return projectLngLat(track.reportedLngLat, headingDeg, distanceMeters);
}

function computeTrackDisplayedLngLat(track, nowMs, allowAnimation) {
  if (!track) {
    return null;
  }
  if (track.status !== "tracked") {
    return track.displayedLngLat || track.reportedLngLat;
  }
  if (!allowAnimation || appState.prefersReducedMotion || track.status !== "tracked") {
    return track.reportedLngLat;
  }
  return computeTrackTargetLngLat(track, nowMs);
}

function currentDisplayedLngLat(track, nowMs, allowAnimation) {
  const lngLat = computeTrackDisplayedLngLat(track, nowMs, allowAnimation);
  if (lngLat) {
    track.displayedLngLat = lngLat;
  }
  return lngLat;
}

function createFlightTrack(providerKey, feature, fetchedAtMs, nowMs) {
  if (!feature || feature.type !== "Feature") {
    return null;
  }
  const coordinates = feature.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) {
    return null;
  }
  const lng = toFiniteNumber(coordinates[0]);
  const lat = toFiniteNumber(coordinates[1]);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) {
    return null;
  }
  const properties = feature.properties || {};
  const recordKey = normalizeFlightRecordKey(properties.recordKey || properties.id);
  if (!recordKey) {
    return null;
  }
  const entityKey = buildFlightEntityKey(providerKey, recordKey);
  return {
    providerKey,
    recordKey,
    entityKey,
    featureId: feature.id || entityKey,
    reportedLngLat: [lng, lat],
    displayedLngLat: [lng, lat],
    deadReckonStartedAtMs: nowMs,
    fetchedAtMs,
    status: "tracked",
    missingSinceMs: null,
    missingInCoverageCount: 0,
    properties: {
      ...properties,
      providerKey,
      recordKey,
      entityKey,
      displayId: properties.displayId || recordKey.toUpperCase()
    }
  };
}

function flightTrackAnimationAllowed(providerKey) {
  const runtime = appState.flightRuntime[providerKey];
  return (
    Boolean(runtime) &&
    appState.flightsEnabled[providerKey] &&
    !appState.prefersReducedMotion &&
    runtime.tracks.size > 0 &&
    runtime.tracks.size <= FLIGHT_MAX_ANIMATED_FEATURES &&
    Array.from(runtime.tracks.values()).some((track) => canProjectTrack(track))
  );
}

function buildSourceFeatureFromTrack(track, nowMs, allowAnimation) {
  const coordinates = currentDisplayedLngLat(track, nowMs, allowAnimation);
  return {
    type: "Feature",
    id: track.featureId,
    geometry: { type: "Point", coordinates },
    properties: track.properties
  };
}

function flightDebugText(value) {
  return value == null || value === "" ? "n/a" : String(value);
}

function flightDebugAge(valueMs, nowMs) {
  const value = toFiniteNumber(valueMs);
  return value === null ? "never" : `${Math.max(0, Math.round((nowMs - value) / 1000))}s ago`;
}

function flightDebugProviderSummary(providerKey, nowMs) {
  const runtime = appState.flightRuntime[providerKey];
  const reasons = {};
  let projectableCount = 0;
  runtime.tracks.forEach((track) => {
    const reason = flightProjectionBlockReason(track);
    if (reason === null) {
      projectableCount += 1;
      return;
    }
    reasons[reason] = (reasons[reason] || 0) + 1;
  });
  const reasonText = Object.entries(reasons)
    .map(([reason, count]) => `${reason}:${count}`)
    .join(", ");
  return [
    `${providerKey}: enabled=${appState.flightsEnabled[providerKey]} available=${isFlightProviderAvailable(providerKey)}`,
    `  tracks=${runtime.tracks.size} projectable=${projectableCount} animAllowed=${flightTrackAnimationAllowed(providerKey)}`,
    `  lastSuccess=${flightDebugAge(runtime.lastSuccessAtMs, nowMs)} requestSeq=${runtime.requestSeq}`,
    `  blocked=${reasonText || "none"}`,
    `  footprint=${flightDebugText(JSON.stringify(runtime.lastQueryFootprint))}`
  ].join("\n");
}

function updateFlightDebugOverlay(nowMs = Date.now()) {
  if (!appState.flightDebug.enabled) {
    return;
  }
  if (!appState.flightDebug.overlay) {
    appState.flightDebug.overlay = document.createElement("pre");
    appState.flightDebug.overlay.className = "flight-debug-overlay";
    document.body.appendChild(appState.flightDebug.overlay);
  }
  const lines = [
    "Flight debug",
    `zoom=${appState.map ? appState.map.getZoom().toFixed(2) : "n/a"} reducedMotion=${appState.prefersReducedMotion}`,
    `rafActive=${Boolean(appState.flightAnimationFrame)} ticks=${appState.flightDebug.tickCount} renders=${appState.flightDebug.renderCount}`,
    `lastTick=${flightDebugAge(appState.flightDebug.lastTickAtMs, nowMs)} lastRender=${flightDebugAge(appState.lastFlightRenderAtMs, nowMs)}`,
    `schedule=${appState.flightDebug.lastScheduleDecision} at ${flightDebugAge(appState.flightDebug.lastScheduleAtMs, nowMs)}`,
    flightDebugProviderSummary("opensky", nowMs),
    flightDebugProviderSummary("adsbx", nowMs)
  ];
  appState.flightDebug.overlay.textContent = lines.join("\n");
}

function renderFlightProvider(providerKey, nowMs = Date.now()) {
  const runtime = appState.flightRuntime[providerKey];
  const animateProvider = flightTrackAnimationAllowed(providerKey);
  const features = [];
  runtime.tracks.forEach((track) => {
    features.push(buildSourceFeatureFromTrack(track, nowMs, animateProvider));
  });
  setFlightSourceData(providerKey, {
    type: "FeatureCollection",
    features,
    meta: {
      providerKey,
      fetchedAtMs: runtime.lastSuccessAtMs
    }
  });
  appState.flightDebug.renderCount += 1;
  updateFlightDebugOverlay(nowMs);
}

function selectedTrack() {
  if (!appState.selectedFlight) {
    return null;
  }
  return appState.flightRuntime[appState.selectedFlight.providerKey]?.tracks.get(
    appState.selectedFlight.entityKey
  );
}

function selectedLngLat(nowMs = Date.now()) {
  if (!appState.selectedFlight) {
    return null;
  }
  const track = selectedTrack();
  if (track) {
    const lngLat = currentDisplayedLngLat(track, nowMs, flightTrackAnimationAllowed(track.providerKey));
    appState.selectedFlight.lastKnownLngLat = lngLat;
    appState.selectedFlight.summary = { ...track.properties };
    appState.selectedFlight.status = track.status;
    return lngLat;
  }
  return appState.selectedFlight.lastKnownLngLat;
}

function updateSelectedFlightSource(nowMs = Date.now()) {
  if (!appState.selectedFlight) {
    setSelectedFlightSource(emptyFeatureCollection());
    return;
  }
  const lngLat = selectedLngLat(nowMs);
  if (!lngLat) {
    setSelectedFlightSource(emptyFeatureCollection());
    return;
  }
  setSelectedFlightSource({
    type: "FeatureCollection",
    features: [selectedFlightFeature(lngLat, appState.selectedFlight)]
  });
  if (appState.flightPopup?.isOpen()) {
    appState.flightPopup.setLngLat(lngLat);
  }
}

function formatFlightValue(value, digits = 0) {
  const number = toFiniteNumber(value);
  if (number === null) {
    return null;
  }
  return digits > 0 ? number.toFixed(digits) : Math.round(number).toString();
}

function formatFlightAge(valueMs) {
  const number = toFiniteNumber(valueMs);
  if (number === null) {
    return null;
  }
  if (number < 1000) {
    return `${Math.round(number)} ms`;
  }
  return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)} s`;
}

function popupRow(label, value, options = {}) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const row = document.createElement("div");
  row.className = "flight-popup-row";
  const term = document.createElement("span");
  term.className = "flight-popup-term";
  term.textContent = label;
  const description = document.createElement("span");
  description.className = "flight-popup-value";
  if (options.tone) {
    description.dataset.tone = options.tone;
  }
  description.textContent = value;
  row.append(term, description);
  return row;
}

function ensureFlightPopup() {
  if (appState.flightPopup) {
    return appState.flightPopup;
  }
  appState.flightPopup = new maplibregl.Popup({
    closeOnClick: false,
    className: "flight-popup",
    maxWidth: "360px"
  });
  appState.flightPopup.on("close", () => {
    if (appState.suppressFlightPopupClose) {
      appState.suppressFlightPopupClose = false;
      return;
    }
    clearSelectedFlight();
  });
  return appState.flightPopup;
}

function buildFlightPopupContent(selectedFlight) {
  const summary = selectedFlight.detail?.summary || selectedFlight.summary || {};
  const liveLngLat = Array.isArray(selectedFlight.lastKnownLngLat) ? selectedFlight.lastKnownLngLat : null;
  const wrapper = document.createElement("div");
  wrapper.className = "flight-popup-card";

  const header = document.createElement("div");
  header.className = "flight-popup-header";
  const titleWrap = document.createElement("div");
  titleWrap.className = "flight-popup-title";
  const title = document.createElement("strong");
  title.textContent =
    summary.labelPrimary || summary.labelFull || summary.callsign || summary.displayId || "Aircraft";
  const subtitle = document.createElement("span");
  subtitle.textContent =
    summary.providerLabel || flightProviders[selectedFlight.providerKey]?.label || selectedFlight.providerKey;
  titleWrap.append(title, subtitle);
  const status = document.createElement("span");
  status.className = "flight-popup-status";
  status.dataset.state = selectedFlight.status || "tracked";
  status.textContent =
    selectedFlight.status === "outside-query"
      ? "Outside active query"
      : selectedFlight.status === "stale"
        ? "Waiting for refresh"
        : "Live";
  header.append(titleWrap, status);
  wrapper.append(header);

  const grid = document.createElement("div");
  grid.className = "flight-popup-grid";
  const rows = [
    popupRow("Flight", summary.flightNumber || summary.callsign),
    popupRow("Craft", summary.craftNumber || summary.registration || summary.displayId),
    popupRow("Type", summary.aircraftType),
    popupRow("Origin", summary.originCountry),
    popupRow("Squawk", summary.squawk),
    popupRow(
      "Altitude",
      summary.baroAltitudeFt != null
        ? `${formatFlightValue(summary.baroAltitudeFt)} ft`
        : summary.baroAltitude != null
          ? String(summary.baroAltitude)
          : null
    ),
    popupRow(
      "Ground speed",
      summary.groundSpeedKts != null
        ? `${formatFlightValue(summary.groundSpeedKts)} kt`
        : summary.groundSpeedMps != null
          ? `${formatFlightValue(summary.groundSpeedMps)} m/s`
          : null
    ),
    popupRow(
      "Heading",
      summary.headingDeg != null ? `${formatFlightValue(summary.headingDeg)} deg` : null
    ),
    popupRow(
      "Vertical rate",
      summary.verticalRateMps != null ? `${formatFlightValue(summary.verticalRateMps, 2)} m/s` : null
    ),
    popupRow("Position age", formatFlightAge(summary.positionAgeMsAtFetch)),
    popupRow("Last contact", formatFlightAge(summary.contactAgeMsAtFetch)),
    popupRow(
      "Coordinates",
      summary.latitude != null && summary.longitude != null
        ? `${formatFlightValue(summary.latitude, 4)}, ${formatFlightValue(summary.longitude, 4)}`
        : liveLngLat
          ? `${formatFlightValue(liveLngLat[1], 4)}, ${formatFlightValue(liveLngLat[0], 4)}`
        : null
    )
  ].filter(Boolean);
  rows.forEach((row) => grid.append(row));
  wrapper.append(grid);

  const detailState = document.createElement("div");
  detailState.className = "flight-popup-detail-state";
  if (selectedFlight.detailLoading) {
    detailState.textContent = "Loading expanded detail...";
  } else if (selectedFlight.detailUnavailable) {
    detailState.textContent = selectedFlight.detailUnavailable;
    detailState.dataset.tone = "warn";
  }
  if (detailState.textContent) {
    wrapper.append(detailState);
  }

  if (selectedFlight.detail?.raw) {
    const details = document.createElement("details");
    details.className = "flight-popup-raw";
    const summaryNode = document.createElement("summary");
    summaryNode.textContent = "All API fields";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(selectedFlight.detail.raw, null, 2);
    details.append(summaryNode, pre);
    wrapper.append(details);
  }

  return wrapper;
}

function renderSelectedFlightPopup() {
  if (!appState.selectedFlight || !appState.map) {
    return;
  }
  const popup = ensureFlightPopup();
  popup.setDOMContent(buildFlightPopupContent(appState.selectedFlight));
  const lngLat = selectedLngLat(Date.now());
  if (lngLat) {
    popup.setLngLat(lngLat);
  }
  if (!popup.isOpen()) {
    popup.addTo(appState.map);
  }
  updateSelectedFlightSource();
}

function clearSelectedFlight(options = {}) {
  const previousSelection = appState.selectedFlight;
  if (!previousSelection) {
    setSelectedFlightSource(emptyFeatureCollection());
    return;
  }
  previousSelection.detailAbortController?.abort();
  appState.selectedFlight = null;
  setSelectedFlightSource(emptyFeatureCollection());
  if (appState.flightPopup?.isOpen()) {
    appState.suppressFlightPopupClose = true;
    appState.flightPopup.remove();
  }
  if (previousSelection.providerKey) {
    const runtime = appState.flightRuntime[previousSelection.providerKey];
    if (runtime?.tracks.has(previousSelection.entityKey)) {
      const track = runtime.tracks.get(previousSelection.entityKey);
      if (track && track.status !== "tracked") {
        runtime.tracks.delete(previousSelection.entityKey);
        renderFlightProvider(previousSelection.providerKey);
      }
    }
  }
  if (options.refreshProvider && previousSelection.providerKey) {
    renderFlightProvider(previousSelection.providerKey);
  }
}

function requestSelectedFlightDetail(force = false) {
  const selected = appState.selectedFlight;
  if (!selected?.recordKey) {
    return;
  }
  const track = selectedTrack();
  const requiredFreshness = track?.fetchedAtMs || 0;
  if (!force && selected.detail && selected.detail.fetchedAtMs >= requiredFreshness) {
    return;
  }
  selected.detailAbortController?.abort();
  selected.detailRequestSeq = (selected.detailRequestSeq || 0) + 1;
  const requestSeq = selected.detailRequestSeq;
  const controller = new AbortController();
  selected.detailAbortController = controller;
  selected.detailLoading = true;
  selected.detailUnavailable = null;
  renderSelectedFlightPopup();
  const params = new URLSearchParams({
    providerKey: selected.providerKey,
    recordKey: selected.recordKey
  });
  requestJson(`/api/flights/detail?${params.toString()}`, { signal: controller.signal })
    .then((detail) => {
      if (
        !appState.selectedFlight ||
        appState.selectedFlight.entityKey !== selected.entityKey ||
        appState.selectedFlight.detailRequestSeq !== requestSeq
      ) {
        return;
      }
      appState.selectedFlight.detail = detail;
      appState.selectedFlight.detailLoading = false;
      appState.selectedFlight.detailUnavailable = null;
      renderSelectedFlightPopup();
    })
    .catch((error) => {
      if (error.name === "AbortError") {
        return;
      }
      if (
        !appState.selectedFlight ||
        appState.selectedFlight.entityKey !== selected.entityKey ||
        appState.selectedFlight.detailRequestSeq !== requestSeq
      ) {
        return;
      }
      appState.selectedFlight.detail = null;
      appState.selectedFlight.detailLoading = false;
      appState.selectedFlight.detailUnavailable = error.message;
      renderSelectedFlightPopup();
    });
}

function selectFlightFeature(feature) {
  const properties = feature?.properties || {};
  const providerKey = normalizeFlightProviderKey(properties.providerKey || properties.provider);
  const recordKey = normalizeFlightRecordKey(properties.recordKey || properties.id);
  if (!providerKey || !recordKey) {
    return;
  }
  if (appState.selectedVessel) {
    clearSelectedVessel();
  }
  const entityKey = buildFlightEntityKey(providerKey, recordKey);
  const track = appState.flightRuntime[providerKey].tracks.get(entityKey);
  if (!track) {
    return;
  }
  if (appState.selectedFlight?.entityKey === entityKey) {
    renderSelectedFlightPopup();
    requestSelectedFlightDetail();
    return;
  }
  clearSelectedFlight();
  appState.selectedFlight = {
    providerKey,
    recordKey,
    entityKey,
    status: "tracked",
    selectedAtMs: Date.now(),
    missingSinceMs: null,
    missingInCoverageCount: 0,
    lastKnownLngLat: track.displayedLngLat || track.reportedLngLat,
    summary: { ...track.properties },
    detail: null,
    detailLoading: false,
    detailUnavailable: null,
    detailRequestSeq: 0,
    detailAbortController: null
  };
  track.status = "tracked";
  track.missingSinceMs = null;
  track.missingInCoverageCount = 0;
  renderSelectedFlightPopup();
  requestSelectedFlightDetail(true);
  scheduleFlightAnimation();
}

function updateSelectedTrackLifecycle(providerKey, queryFootprint, nowMs) {
  const selected = appState.selectedFlight;
  if (!selected || selected.providerKey !== providerKey) {
    return;
  }
  const runtime = appState.flightRuntime[providerKey];
  const track = runtime.tracks.get(selected.entityKey);
  if (!track) {
    clearSelectedFlight({ refreshProvider: true });
    return;
  }
  if (track.status === "tracked") {
    selected.status = "tracked";
    selected.missingSinceMs = null;
    selected.missingInCoverageCount = 0;
    selected.lastKnownLngLat = track.displayedLngLat || track.reportedLngLat;
    selected.summary = { ...track.properties };
    if (!selected.detail || selected.detail.fetchedAtMs < track.fetchedAtMs) {
      requestSelectedFlightDetail();
    }
    return;
  }
  selected.lastKnownLngLat = track.displayedLngLat || track.reportedLngLat || selected.lastKnownLngLat;
  selected.status = track.status;
  selected.summary = { ...track.properties };
  selected.missingSinceMs = track.missingSinceMs;
  selected.missingInCoverageCount = track.missingInCoverageCount;
  const insideCoverage = queryFootprintContains(queryFootprint, selected.lastKnownLngLat);
  const staleTooLong = selected.missingSinceMs && nowMs - selected.missingSinceMs >= FLIGHT_STALE_GRACE_MS;
  const disappearedInCoverage = insideCoverage && selected.missingInCoverageCount >= 2;
  if (staleTooLong || disappearedInCoverage) {
    runtime.tracks.delete(selected.entityKey);
    clearSelectedFlight({ refreshProvider: true });
    return;
  }
  renderSelectedFlightPopup();
}

function ingestFlightResponse(providerKey, featureCollection, queryFootprint) {
  const runtime = appState.flightRuntime[providerKey];
  const nowMs = Date.now();
  const fetchedAtMs =
    toFiniteNumber(featureCollection?.meta?.fetchedAtMs) || toFiniteNumber(featureCollection?.meta?.fetchedAt) || nowMs;
  runtime.lastSuccessAtMs = fetchedAtMs;
  runtime.lastQueryFootprint = queryFootprint;

  runtime.tracks.forEach((track) => {
    track.seenInSnapshot = false;
  });

  const features = Array.isArray(featureCollection?.features) ? featureCollection.features : [];
  features.forEach((feature) => {
    const nextProviderKey = normalizeFlightProviderKey(
      feature?.properties?.providerKey || feature?.properties?.provider || providerKey
    );
    if (nextProviderKey !== providerKey) {
      return;
    }
    const recordKey = normalizeFlightRecordKey(feature?.properties?.recordKey || feature?.properties?.id);
    const entityKey = buildFlightEntityKey(providerKey, recordKey);
    const nextTrack = createFlightTrack(
      providerKey,
      feature,
      fetchedAtMs,
      nowMs
    );
    if (!nextTrack) {
      return;
    }
    nextTrack.seenInSnapshot = true;
    runtime.tracks.set(entityKey, nextTrack);
  });

  runtime.tracks.forEach((track, entityKey) => {
    if (track.seenInSnapshot) {
      track.status = "tracked";
      track.missingSinceMs = null;
      track.missingInCoverageCount = 0;
      return;
    }
    if (appState.selectedFlight?.entityKey === entityKey) {
      const insideCoverage = queryFootprintContains(queryFootprint, track.displayedLngLat || track.reportedLngLat);
      track.status = insideCoverage ? "stale" : "outside-query";
      track.missingSinceMs = track.missingSinceMs || nowMs;
      if (insideCoverage) {
        track.missingInCoverageCount = (track.missingInCoverageCount || 0) + 1;
      }
      return;
    }
    runtime.tracks.delete(entityKey);
  });

  renderFlightProvider(providerKey, nowMs);
  updateSelectedTrackLifecycle(providerKey, queryFootprint, nowMs);
  updateSelectedFlightSource(nowMs);
  scheduleFlightAnimation();
}

function clearFlightProviderState(providerKey, options = {}) {
  const runtime = appState.flightRuntime[providerKey];
  runtime.abortController?.abort();
  runtime.abortController = null;
  runtime.tracks.clear();
  runtime.lastQueryFootprint = null;
  setFlightSourceData(providerKey, emptyFeatureCollection());
  if (appState.selectedFlight?.providerKey === providerKey && options.clearSelection !== false) {
    clearSelectedFlight();
  }
}

function scheduleFlightAnimation() {
  const nowMs = Date.now();
  appState.flightDebug.lastScheduleAtMs = nowMs;
  if (appState.prefersReducedMotion || appState.flightAnimationFrame) {
    appState.flightDebug.lastScheduleDecision = appState.prefersReducedMotion
      ? "skip:reduced-motion"
      : "skip:raf-already-active";
    updateFlightDebugOverlay(nowMs);
    return;
  }
  const hasAnimatedTracks = Object.keys(flightProviders).some((providerKey) =>
    flightTrackAnimationAllowed(providerKey)
  );
  const selectedCanAnimate =
    appState.selectedFlight && flightTrackAnimationAllowed(appState.selectedFlight.providerKey);
  if (!hasAnimatedTracks && !selectedCanAnimate) {
    appState.flightDebug.lastScheduleDecision = "skip:no-animation-eligible-tracks";
    updateFlightDebugOverlay(nowMs);
    return;
  }
  appState.flightDebug.lastScheduleDecision = "start:request-animation-frame";
  updateFlightDebugOverlay(nowMs);
  appState.flightAnimationFrame = window.requestAnimationFrame(tickFlightAnimation);
}

function tickFlightAnimation() {
  appState.flightAnimationFrame = null;
  const nowMs = Date.now();
  appState.flightDebug.tickCount += 1;
  appState.flightDebug.lastTickAtMs = nowMs;
  if (nowMs - appState.lastFlightRenderAtMs >= FLIGHT_RENDER_INTERVAL_MS) {
    Object.keys(flightProviders).forEach((providerKey) => {
      if (appState.flightsEnabled[providerKey]) {
        renderFlightProvider(providerKey, nowMs);
      }
    });
    appState.lastFlightRenderAtMs = nowMs;
  }
  updateSelectedFlightSource(nowMs);
  const shouldContinue =
    !appState.prefersReducedMotion &&
    (Object.keys(flightProviders).some((providerKey) => flightTrackAnimationAllowed(providerKey)) ||
      Boolean(appState.selectedFlight && flightTrackAnimationAllowed(appState.selectedFlight.providerKey)));
  if (shouldContinue) {
    appState.flightAnimationFrame = window.requestAnimationFrame(tickFlightAnimation);
  }
  updateFlightDebugOverlay(nowMs);
}

function bindFlightMapInteractions() {
  const interactionLayers = Object.values(flightProviders).flatMap((provider) => [
    provider.hitLayerId,
    provider.layerId
  ]);
  appState.map.on("click", (event) => {
    const streetImageryLayers = [STREET_IMAGERY_HIT_LAYER_ID, STREET_IMAGERY_LAYER_ID].filter((layerId) =>
      appState.map.getLayer(layerId)
    );
    if (streetImageryLayers.length) {
      const streetFeatures = appState.map.queryRenderedFeatures(event.point, { layers: streetImageryLayers });
      if (streetFeatures.length) {
        selectStreetImageryFeature(streetFeatures[0]);
        return;
      }
    }
    const vesselLayers = [VESSEL_HIT_LAYER_ID, VESSEL_LAYER_ID].filter((layerId) => appState.map.getLayer(layerId));
    if (vesselLayers.length) {
      const vesselFeatures = appState.map.queryRenderedFeatures(event.point, { layers: vesselLayers });
      if (vesselFeatures.length) {
        selectVesselFeature(vesselFeatures[0]);
        return;
      }
    }
    const features = appState.map.queryRenderedFeatures(event.point, {
      layers: interactionLayers.filter((layerId) => appState.map.getLayer(layerId))
    });
    if (features.length) {
      selectFlightFeature(features[0]);
      return;
    }
    if (appState.selectedFlight) {
      clearSelectedFlight();
    }
    if (appState.selectedVessel) {
      clearSelectedVessel();
    }
  });
  [STREET_IMAGERY_HIT_LAYER_ID, STREET_IMAGERY_LAYER_ID].forEach((layerId) => {
    appState.map.on("mouseenter", layerId, () => {
      appState.map.getCanvas().style.cursor = "pointer";
    });
    appState.map.on("mouseleave", layerId, () => {
      appState.map.getCanvas().style.cursor = "";
    });
  });
  Object.values(flightProviders).forEach((provider) => {
    [provider.hitLayerId, provider.layerId].forEach((layerId) => {
      appState.map.on("mouseenter", layerId, () => {
        appState.map.getCanvas().style.cursor = "pointer";
      });
      appState.map.on("mouseleave", layerId, () => {
        appState.map.getCanvas().style.cursor = "";
      });
    });
  });
  [VESSEL_HIT_LAYER_ID, VESSEL_LAYER_ID].forEach((layerId) => {
    appState.map.on("mouseenter", layerId, () => {
      appState.map.getCanvas().style.cursor = "pointer";
    });
    appState.map.on("mouseleave", layerId, () => {
      appState.map.getCanvas().style.cursor = "";
    });
  });
}

function currentBoundsQuery() {
  const bounds = appState.map.getBounds();
  return {
    lamin: bounds.getSouth(),
    lomin: bounds.getWest(),
    lamax: bounds.getNorth(),
    lomax: bounds.getEast()
  };
}

function distanceNm(aLat, aLng, bLat, bLng) {
  const earthRadiusKm = 6371;
  const lat1 = (aLat * Math.PI) / 180;
  const lat2 = (bLat * Math.PI) / 180;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLng = ((bLng - aLng) * Math.PI) / 180;
  const sinLat = Math.sin(dLat / 2);
  const sinLng = Math.sin(dLng / 2);
  const h = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLng * sinLng;
  const km = 2 * earthRadiusKm * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  return km * 0.539957;
}

function currentAdsbQuery() {
  const bounds = appState.map.getBounds();
  const center = bounds.getCenter();
  const radius = Math.ceil(
    distanceNm(center.lat, center.lng, bounds.getNorth(), bounds.getEast())
  );
  return {
    lat: center.lat,
    lng: center.lng,
    dist: Math.max(1, Math.min(radius, 100))
  };
}

async function refreshFlights(providerKey, suppressErrors = false) {
  if (!appState.flightsEnabled[providerKey] || !appState.map || !appState.map.isStyleLoaded()) {
    return;
  }

  const provider = flightProviders[providerKey];
  const runtime = appState.flightRuntime[providerKey];
  if (appState.map.getZoom() < provider.minZoom) {
    clearFlightProviderState(providerKey);
    if (!suppressErrors) {
      showMessage(`Zoom in to load ${providerKey === "opensky" ? "OpenSky" : "ADS-B Exchange"} flights.`, "warn");
    }
    return;
  }

  runtime.abortController?.abort();
  runtime.requestSeq += 1;
  const requestSeq = runtime.requestSeq;
  const controller = new AbortController();
  runtime.abortController = controller;
  const request = buildFlightRequest(providerKey);
  try {
    const data = await requestJson(request.url, { signal: controller.signal });
    if (
      runtime.requestSeq !== requestSeq ||
      controller.signal.aborted ||
      !appState.flightsEnabled[providerKey]
    ) {
      return;
    }
    ingestFlightResponse(providerKey, data, request.footprint);
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    if (runtime.lastSuccessAtMs && Date.now() - runtime.lastSuccessAtMs > 45000) {
      clearFlightProviderState(providerKey);
    }
    if (!suppressErrors) {
      showMessage(error.message, "warn");
    }
  }
}

function stopFlightPolling(providerKey) {
  window.clearInterval(appState.flightTimers[providerKey]);
  appState.flightTimers[providerKey] = null;
  clearFlightProviderState(providerKey);
}

function toggleFlight(providerKey) {
  if (!isFlightProviderAvailable(providerKey)) {
    return;
  }

  appState.flightsEnabled[providerKey] = !appState.flightsEnabled[providerKey];
  updateFlightButtons();
  if (appState.flightsEnabled[providerKey]) {
    refreshFlights(providerKey);
    appState.flightTimers[providerKey] = window.setInterval(() => {
      refreshFlights(providerKey, true);
    }, FLIGHT_POLL_INTERVAL_MS);
  } else {
    stopFlightPolling(providerKey);
  }
}

async function refreshVessels(suppressErrors = false) {
  if (!appState.vesselsEnabled || !appState.map || !appState.map.isStyleLoaded()) {
    return;
  }
  const runtime = appState.vesselRuntime;
  runtime.abortController?.abort();
  runtime.requestSeq += 1;
  const requestSeq = runtime.requestSeq;
  const controller = new AbortController();
  runtime.abortController = controller;
  const query = currentBoundsQuery();
  try {
    const data = await requestJson(`/api/vessels/aisstream?${new URLSearchParams(query).toString()}`, {
      signal: controller.signal
    });
    if (runtime.requestSeq !== requestSeq || controller.signal.aborted || !appState.vesselsEnabled) {
      return;
    }
    runtime.lastSuccessAtMs = Date.now();
    runtime.features = data;
    setVesselSourceData(data);
    if (appState.selectedVessel) {
      renderSelectedVesselPopup();
    }
  } catch (error) {
    if (error.name === "AbortError") {
      return;
    }
    if (!suppressErrors) {
      showMessage(error.message, "warn");
    }
  }
}

function stopVesselPolling() {
  window.clearInterval(appState.vesselTimer);
  appState.vesselTimer = null;
  appState.vesselRuntime.abortController?.abort();
  appState.vesselRuntime.features = emptyFeatureCollection();
  setVesselSourceData(emptyFeatureCollection());
  clearSelectedVessel();
}

function toggleVessels() {
  if (!isVesselProviderAvailable()) {
    return;
  }
  if (!appState.map || !appState.map.isStyleLoaded()) {
    showMessage("Map is still loading. Try again in a moment.", "warn");
    return;
  }
  appState.vesselsEnabled = !appState.vesselsEnabled;
  updateFlightButtons();
  if (appState.vesselsEnabled) {
    ensureVesselLayers();
    refreshVessels();
    appState.vesselTimer = window.setInterval(() => refreshVessels(true), VESSEL_POLL_INTERVAL_MS);
  } else {
    stopVesselPolling();
  }
}

function toggleTrafficLayer(kind) {
  if (!isTrafficLayerAvailable(kind)) {
    return;
  }
  if (!appState.map || !appState.map.isStyleLoaded()) {
    showMessage("Map is still loading. Try again in a moment.", "warn");
    return;
  }
  appState.trafficEnabled[kind] = !appState.trafficEnabled[kind];
  setTrafficLayerVisibility(kind, appState.trafficEnabled[kind]);
  updateFlightButtons();
}

function toggleTerrain3d() {
  if (!isTerrainAvailable()) {
    return;
  }
  if (!appState.map || !appState.map.isStyleLoaded()) {
    showMessage("Map is still loading. Try again in a moment.", "warn");
    return;
  }
  appState.terrainEnabled = !appState.terrainEnabled;
  setTerrain3dVisibility(appState.terrainEnabled);
  updateFlightButtons();
}

function toggleHillshade() {
  if (!isHillshadeAvailable()) {
    return;
  }
  if (!appState.map || !appState.map.isStyleLoaded()) {
    showMessage("Map is still loading. Try again in a moment.", "warn");
    return;
  }
  appState.hillshadeEnabled = !appState.hillshadeEnabled;
  setHillshadeVisibility(appState.hillshadeEnabled);
  updateFlightButtons();
}

async function showSatelliteCatalogStatus() {
  if (!isSatelliteCatalogAvailable()) {
    return;
  }
  appState.satelliteCatalogVisible = true;
  updateFlightButtons();
  try {
    const [catalog, elements] = await Promise.all([
      requestJson("/api/satellites/catalog"),
      requestJson("/api/satellites/elements?limit=1")
    ]);
    if (!catalog.cachePresent) {
      showMessage("Satellite catalog cache only: enabled, but no cached OMM elements are available yet.", "warn");
      return;
    }
    const manifest = catalog.manifest || {};
    const source = manifest.source || {};
    const sourceLabel =
      source.type === "local-import" ? source.label || source.fileName || "local import" : "CelesTrak GP";
    const staleState = manifest.staleness?.state || "unknown";
    showMessage(
      `Satellite catalog only: ${elements.count} cached OMM element${
        elements.count === 1 ? "" : "s"
      } from ${sourceLabel}; staleness ${staleState}. No map positions are calculated in v1.`,
      staleState === "fresh" ? "info" : "warn"
    );
  } catch (error) {
    showMessage(error.message, "warn");
  }
}

function ensureVesselPopup() {
  if (appState.vesselPopup) {
    return appState.vesselPopup;
  }
  appState.vesselPopup = new maplibregl.Popup({
    closeOnClick: false,
    className: "flight-popup",
    maxWidth: "360px"
  });
  appState.vesselPopup.on("close", () => {
    clearSelectedVessel();
  });
  return appState.vesselPopup;
}

function buildVesselPopupContent(selectedVessel) {
  const summary = selectedVessel.detail?.summary || selectedVessel.summary || {};
  const wrapper = document.createElement("div");
  wrapper.className = "flight-popup-card";

  const header = document.createElement("div");
  header.className = "flight-popup-header";
  const titleWrap = document.createElement("div");
  titleWrap.className = "flight-popup-title";
  const title = document.createElement("strong");
  title.textContent = summary.vesselName || summary.labelPrimary || summary.mmsi || "Vessel";
  const subtitle = document.createElement("span");
  subtitle.textContent = summary.providerLabel || "AISStream";
  titleWrap.append(title, subtitle);
  const status = document.createElement("span");
  status.className = "flight-popup-status";
  status.dataset.state = "tracked";
  status.textContent = "Live";
  header.append(titleWrap, status);
  wrapper.append(header);

  const grid = document.createElement("div");
  grid.className = "flight-popup-grid";
  [
    popupRow("MMSI", summary.mmsi || summary.displayId),
    popupRow("Call sign", summary.callsign),
    popupRow("IMO", summary.imo),
    popupRow("Type", summary.shipType),
    popupRow("Navigation", summary.navStatus),
    popupRow("Speed", summary.sogKts != null ? `${formatFlightValue(summary.sogKts, 1)} kt` : null),
    popupRow("Course", summary.cogDeg != null ? `${formatFlightValue(summary.cogDeg)} deg` : null),
    popupRow("Heading", summary.headingDeg != null ? `${formatFlightValue(summary.headingDeg)} deg` : null),
    popupRow("Position age", formatFlightAge(summary.positionAgeMsAtFetch)),
    popupRow(
      "Coordinates",
      summary.latitude != null && summary.longitude != null
        ? `${formatFlightValue(summary.latitude, 4)}, ${formatFlightValue(summary.longitude, 4)}`
        : null
    )
  ]
    .filter(Boolean)
    .forEach((row) => grid.append(row));
  wrapper.append(grid);

  if (selectedVessel.detailLoading || selectedVessel.detailUnavailable) {
    const detailState = document.createElement("div");
    detailState.className = "flight-popup-detail-state";
    detailState.textContent = selectedVessel.detailLoading
      ? "Loading expanded detail..."
      : selectedVessel.detailUnavailable;
    if (selectedVessel.detailUnavailable) {
      detailState.dataset.tone = "warn";
    }
    wrapper.append(detailState);
  }

  if (selectedVessel.detail?.raw) {
    const details = document.createElement("details");
    details.className = "flight-popup-raw";
    const summaryNode = document.createElement("summary");
    summaryNode.textContent = "All API fields";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(selectedVessel.detail.raw, null, 2);
    details.append(summaryNode, pre);
    wrapper.append(details);
  }
  return wrapper;
}

function renderSelectedVesselPopup() {
  if (!appState.selectedVessel || !appState.map) {
    return;
  }
  const popup = ensureVesselPopup();
  popup.setDOMContent(buildVesselPopupContent(appState.selectedVessel));
  popup.setLngLat(appState.selectedVessel.lngLat);
  if (!popup.isOpen()) {
    popup.addTo(appState.map);
  }
}

function clearSelectedVessel() {
  appState.selectedVessel?.detailAbortController?.abort();
  appState.selectedVessel = null;
  if (appState.vesselPopup?.isOpen()) {
    appState.vesselPopup.remove();
  }
}

function requestSelectedVesselDetail() {
  const selected = appState.selectedVessel;
  if (!selected?.recordKey) {
    return;
  }
  selected.detailAbortController?.abort();
  const controller = new AbortController();
  selected.detailAbortController = controller;
  selected.detailLoading = true;
  selected.detailUnavailable = null;
  renderSelectedVesselPopup();
  const params = new URLSearchParams({
    providerKey: "aisstream",
    recordKey: selected.recordKey
  });
  requestJson(`/api/vessels/detail?${params.toString()}`, { signal: controller.signal })
    .then((detail) => {
      if (!appState.selectedVessel || appState.selectedVessel.entityKey !== selected.entityKey) {
        return;
      }
      appState.selectedVessel.detail = detail;
      appState.selectedVessel.detailLoading = false;
      renderSelectedVesselPopup();
    })
    .catch((error) => {
      if (error.name === "AbortError") {
        return;
      }
      if (!appState.selectedVessel || appState.selectedVessel.entityKey !== selected.entityKey) {
        return;
      }
      appState.selectedVessel.detailLoading = false;
      appState.selectedVessel.detailUnavailable = error.message;
      renderSelectedVesselPopup();
    });
}

function selectVesselFeature(feature) {
  const properties = feature?.properties || {};
  const coordinates = feature?.geometry?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2 || !properties.recordKey) {
    return;
  }
  if (appState.selectedFlight) {
    clearSelectedFlight();
  }
  appState.selectedVessel = {
    providerKey: "aisstream",
    recordKey: properties.recordKey,
    entityKey: properties.entityKey,
    summary: { ...properties, latitude: coordinates[1], longitude: coordinates[0] },
    lngLat: [coordinates[0], coordinates[1]],
    detail: null,
    detailLoading: false,
    detailUnavailable: null,
    detailAbortController: null
  };
  renderSelectedVesselPopup();
  requestSelectedVesselDetail();
}

async function runSearch() {
  const input = document.getElementById("searchInput");
  const value = input.value.trim();
  if (!value) {
    return;
  }

  const coords = parseCoordinates(value);
  if (coords) {
    appState.map.flyTo({ center: [coords.lng, coords.lat], zoom: 13 });
    showMessage(`Moved to ${coords.lat.toFixed(5)}, ${coords.lng.toFixed(5)}.`);
    return;
  }

  if (!appState.capabilities.addressSearchEnabled) {
    showMessage("Address lookup is unavailable. Use coordinates such as lat,lng.", "warn");
    return;
  }

  try {
    const data = await requestJson(`/api/search?q=${encodeURIComponent(value)}`);
    const result = data.items && data.items[0];
    if (!result) {
      showMessage("No address matches were found.", "warn");
      return;
    }
    if (Array.isArray(result.bounds) && result.bounds.length === 2) {
      appState.map.fitBounds(result.bounds, { padding: 48, maxZoom: 13 });
    } else {
      appState.map.flyTo({ center: [result.lng, result.lat], zoom: 13 });
    }
    showMessage(`Moved to ${result.displayName}.`);
  } catch (error) {
    showMessage(`${error.message} Use coordinates when offline.`, "warn");
  }
}

function renderOverviewSummary() {
  const container = document.getElementById("mapSummary");
  const overview = appState.overview || {};
  const selectedArea = appState.selectedArea || {};
  const currentIds = overview.currentIds || [];
  const selectedIds = overview.selectedIds || [];
  const staleNote = overview.currentIsStale ? "Pending rebuild" : "In sync";
  const availableBoundaryIds = selectedArea.availableBoundaryIds || [];
  const displayBoundaryIds = selectedArea.displayBoundaryIds || [];
  const providerFallbackIds = selectedArea.providerFallbackIds || [];
  const missingItems = selectedArea.missingItems || [];
  const terrain = overview.terrain || {};
  const terrainSummary = terrain.terrainAvailable
    ? `Terrain and hillshade available (${terrain.encoding || "unknown encoding"}, z${terrain.minzoom}-${terrain.maxzoom})`
    : `Terrain unavailable${terrain.reason ? ` (${terrain.reason})` : ""}`;
  const boundarySummary = selectedIds.length
    ? `${
        availableBoundaryIds.length
      } of ${selectedIds.length} overlays available (${displayBoundaryIds.length} curated, ${
        providerFallbackIds.length
      } provider fallback)${
        missingItems.length
          ? `; missing ${missingItems.map((item) => item.name || item.id).join(", ")}`
          : ""
      }`
    : "No selected boundary overlays";
  container.innerHTML = `
    <div class="summary-row">
      <strong>Loaded now</strong>
      <div>${currentIds.length ? currentIds.join(", ") : "No current build"}</div>
    </div>
    <div class="summary-row">
      <strong>Selected for next rebuild</strong>
      <div>${selectedIds.length ? selectedIds.join(", ") : "Nothing selected"}</div>
    </div>
    <div class="summary-row">
      <strong>Current state</strong>
      <div>${staleNote}${overview.current?.rebuilt_at ? `, rebuilt ${overview.current.rebuilt_at}` : ""}</div>
    </div>
    <div class="summary-row">
      <strong>Selected boundary overlay</strong>
      <div>${boundarySummary}</div>
    </div>
    <div class="summary-row">
      <strong>Terrain</strong>
      <div>${terrainSummary}</div>
    </div>
  `;
}

function datasetBadges(item) {
  const badges = [];
  if (item.current) {
    badges.push('<span class="badge current">Loaded now</span>');
  }
  if (item.selected) {
    badges.push('<span class="badge selected">Selected</span>');
  }
  if (item.bootstrap) {
    badges.push('<span class="badge bootstrap">Bootstrap</span>');
  }
  if (item.overlayBoundarySource === "display") {
    badges.push('<span class="badge boundary">Display boundary</span>');
  } else if (item.overlayBoundarySource === "provider") {
    const reason =
      item.overlayBoundaryReason || "Using a provider footprint because no curated display boundary exists.";
    badges.push(`<span class="badge boundary-provider" title="${reason}">Provider fallback</span>`);
  } else {
    const reason =
      item.overlayBoundaryReason ||
      item.providerBoundaryReason ||
      item.boundaryReason ||
      "No boundary overlay available";
    badges.push(`<span class="badge boundary-missing" title="${reason}">No boundary overlay</span>`);
  }
  return badges.length ? `<div class="badge-row">${badges.join("")}</div>` : "";
}

function renderDownloadedMaps() {
  const container = document.getElementById("downloadedMaps");
  if (!appState.datasets.length) {
    container.innerHTML = '<div class="empty-state">No datasets are installed yet.</div>';
    return;
  }
  container.innerHTML = appState.datasets
    .map(
      (item) => `
        <div class="dataset-item">
          <strong>${item.name}</strong>
          <div class="dataset-meta">${item.id} • ${item.provider} • ${item.datasetSizeHuman}</div>
          ${datasetBadges(item)}
        </div>
      `
    )
    .join("");
}

function renderSelectionList() {
  const container = document.getElementById("selectionList");
  if (!appState.datasets.length) {
    container.innerHTML = '<div class="empty-state">Install a dataset before changing the active map.</div>';
    return;
  }
  container.innerHTML = appState.datasets
    .map(
      (item) => `
        <div class="selection-item">
          <label>
            <input type="checkbox" value="${item.id}" ${item.selected ? "checked" : ""} />
            <span>
              <strong>${item.name}</strong>
              <span class="selection-meta">${item.id} • ${item.provider}</span>
            </span>
          </label>
          ${datasetBadges(item)}
        </div>
      `
    )
    .join("");
}

function renderCatalogResults() {
  const container = document.getElementById("catalogResults");
  if (!appState.catalog.cachePresent) {
    container.innerHTML =
      '<div class="empty-state">No cached catalog is available yet. Use "Refresh catalog" to fetch download options.</div>';
    return;
  }
  if (!appState.catalog.items.length) {
    container.innerHTML = '<div class="empty-state">No catalog entries matched your search.</div>';
    return;
  }
  container.innerHTML = appState.catalog.items
    .map(
      (item) => `
        <div class="catalog-item">
          <strong>${item.name}</strong>
          <div class="catalog-meta">${item.id} • ${item.provider}${item.parent ? ` • ${item.parent}` : ""}</div>
          <div class="badge-row">
            <button class="install-button" type="button" data-install-id="${item.id}">Download map</button>
          </div>
        </div>
      `
    )
    .join("");
}

function renderJob() {
  const status = document.getElementById("jobStatus");
  const body = document.getElementById("jobLogBody");
  if (!appState.currentJob) {
    status.textContent = "No active admin job.";
    body.textContent = "";
    return;
  }
  const job = appState.currentJob;
  status.textContent = `${job.action} • ${job.status}`;
  body.textContent = (job.logTail || []).join("");
}

async function refreshModalData() {
  const [overview, datasets, selectedArea] = await Promise.all([
    requestJson("/api/state"),
    requestJson("/api/datasets"),
    requestJson("/api/selected-area")
  ]);
  appState.overview = overview;
  appState.datasets = datasets.items || [];
  appState.selectedArea = normalizeSelectedAreaData(selectedArea);
  renderOverviewSummary();
  renderDownloadedMaps();
  renderSelectionList();
  renderViewerNotice(Boolean(resolveCurrentAreaBounds(null)));
  applySelectedAreaOverlay();
}

async function searchCatalog() {
  const query = document.getElementById("catalogSearchInput").value.trim();
  appState.catalog = await requestJson(`/api/catalog?q=${encodeURIComponent(query)}`);
  renderCatalogResults();
}

async function loadCurrentJob() {
  try {
    const data = await requestAdmin("/api/admin/jobs/current");
    appState.currentJob = data.job;
    renderJob();
    if (data.job && data.job.status !== "success" && data.job.status !== "error") {
      startJobPolling(data.job.id);
    }
  } catch (error) {
    console.warn("Unable to load current admin job.", error);
  }
}

function stopJobPolling() {
  window.clearInterval(appState.jobPollHandle);
  appState.jobPollHandle = null;
}

function startJobPolling(jobId) {
  stopJobPolling();
  appState.jobPollHandle = window.setInterval(async () => {
    try {
      const data = await requestAdmin(`/api/admin/jobs/${jobId}`);
      appState.currentJob = data.job;
      renderJob();
      if (data.job.status === "success" || data.job.status === "error") {
        stopJobPolling();
        await refreshModalData();
        if (data.job.status === "success") {
          if (data.job.action === "activate_selection") {
            showMessage("Map rebuild finished. Reloading the viewer.");
            window.setTimeout(() => window.location.reload(), 900);
          } else {
            showMessage("Admin job finished successfully.");
          }
        } else {
          showMessage(data.job.error || "Admin job failed.", "error");
        }
      }
    } catch (error) {
      stopJobPolling();
      console.warn("Admin job polling failed.", error);
    }
  }, 2000);
}

async function beginJob(url, body, successMessage) {
  const data = await requestAdmin(url, {
    method: "POST",
    body: body ? JSON.stringify(body) : "{}"
  });
  appState.currentJob = data.job;
  renderJob();
  showMessage(successMessage);
  startJobPolling(data.job.id);
}

async function installDataset(datasetId) {
  await beginJob("/api/admin/install", { datasetId }, `Started download for ${datasetId}.`);
}

async function applyActiveSelection() {
  const ids = Array.from(document.querySelectorAll("#selectionList input:checked")).map((input) => input.value);
  if (!ids.length) {
    showMessage("Select at least one downloaded map before rebuilding.", "warn");
    return;
  }
  await beginJob("/api/admin/activate", { datasetIds: ids }, "Started map rebuild.");
}

async function refreshCatalog() {
  await beginJob("/api/admin/refresh-catalog", {}, "Refreshing the download catalog.");
}

function openModal() {
  document.getElementById("configModal").classList.add("visible");
  refreshModalData().catch((error) => {
    showMessage(error.message, "error");
  });
  searchCatalog().catch((error) => {
    console.warn("Catalog search failed on modal open.", error);
  });
  loadCurrentJob();
}

function closeModal() {
  document.getElementById("configModal").classList.remove("visible");
}

function bindDomEvents() {
  const flightControls = document.getElementById("flightControls");
  const flightMenuToggle = document.getElementById("flightMenuToggle");
  const targetInFlightControls = (target) => Boolean(target && flightControls.contains(target));

  document.getElementById("goBtn").addEventListener("click", () => {
    runSearch();
  });
  document.getElementById("searchInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      runSearch();
    }
  });
  document.getElementById("configBtn").addEventListener("click", openModal);
  document.getElementById("closeConfigBtn").addEventListener("click", closeModal);
  document.getElementById("applySelectionBtn").addEventListener("click", () => {
    applyActiveSelection().catch((error) => {
      showMessage(error.message, "error");
    });
  });
  document.getElementById("refreshCatalogBtn").addEventListener("click", () => {
    refreshCatalog().catch((error) => {
      showMessage(error.message, "error");
    });
  });
  document.getElementById("catalogSearchBtn").addEventListener("click", () => {
    searchCatalog().catch((error) => {
      showMessage(error.message, "error");
    });
  });
  document.getElementById("catalogSearchInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      searchCatalog().catch((error) => {
        showMessage(error.message, "error");
      });
    }
  });
  flightControls.addEventListener("pointerenter", () => {
    openFlightMenu();
  });
  flightControls.addEventListener("pointerleave", () => {
    if (!appState.flightMenuPinned && !targetInFlightControls(document.activeElement)) {
      closeFlightMenu();
    }
  });
  flightControls.addEventListener("focusin", () => {
    if (appState.flightMenuIgnoreNextFocusOpen) {
      appState.flightMenuIgnoreNextFocusOpen = false;
      return;
    }
    openFlightMenu({ pinned: appState.flightMenuPinned });
  });
  flightControls.addEventListener("focusout", (event) => {
    if (targetInFlightControls(event.relatedTarget)) {
      return;
    }
    window.setTimeout(() => {
      if (!appState.flightMenuPinned && !targetInFlightControls(document.activeElement)) {
        closeFlightMenu();
      }
    }, 0);
  });
  flightControls.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeFlightMenu({ focusToggle: true, suppressNextFocusOpen: true });
    }
  });
  flightMenuToggle.addEventListener("click", () => {
    if (appState.flightMenuOpen && appState.flightMenuPinned) {
      closeFlightMenu();
      return;
    }
    openFlightMenu({ pinned: true });
  });
  OSM_OVERLAY_GROUPS.forEach((group) => {
    document.getElementById(group.buttonId).addEventListener("click", () => toggleOsmOverlayGroup(group.key));
  });
  document.getElementById("toggleOpenSky").addEventListener("click", () => toggleFlight("opensky"));
  document.getElementById("toggleAdsbx").addEventListener("click", () => toggleFlight("adsbx"));
  document.getElementById("toggleAisVessels").addEventListener("click", () => toggleVessels());
  document.getElementById("toggleTrafficFlow").addEventListener("click", () => toggleTrafficLayer("flow"));
  document.getElementById("toggleTrafficIncidents").addEventListener("click", () => toggleTrafficLayer("incidents"));
  document.getElementById("imageryOverlayControls").addEventListener("click", (event) => {
    const button = event.target.closest("[data-imagery-id]");
    if (!button) {
      return;
    }
    toggleImageryOverlay(button.dataset.imageryId);
  });
  document.getElementById("toggleTerrain3d").addEventListener("click", () => toggleTerrain3d());
  document.getElementById("toggleHillshade").addEventListener("click", () => toggleHillshade());
  document.getElementById("toggleStreetImagery").addEventListener("click", () => toggleStreetImagery());
  document.getElementById("showSatelliteCatalog").addEventListener("click", () => {
    showSatelliteCatalogStatus();
  });
  document.getElementById("catalogResults").addEventListener("click", (event) => {
    const button = event.target.closest("[data-install-id]");
    if (!button) {
      return;
    }
    installDataset(button.dataset.installId).catch((error) => {
      showMessage(error.message, "error");
    });
  });
  document.getElementById("configModal").addEventListener("click", (event) => {
    if (event.target.id === "configModal") {
      closeModal();
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!targetInFlightControls(event.target)) {
      closeFlightMenu();
    }
  });
  if (typeof window.matchMedia === "function") {
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handleMotionChange = (event) => {
      appState.prefersReducedMotion = event.matches;
      Object.keys(flightProviders).forEach((providerKey) => {
        if (appState.flightsEnabled[providerKey]) {
          renderFlightProvider(providerKey, Date.now());
        }
      });
      updateSelectedFlightSource(Date.now());
      if (appState.prefersReducedMotion && appState.flightAnimationFrame) {
        window.cancelAnimationFrame(appState.flightAnimationFrame);
        appState.flightAnimationFrame = null;
      } else {
        scheduleFlightAnimation();
      }
    };
    if (typeof motionQuery.addEventListener === "function") {
      motionQuery.addEventListener("change", handleMotionChange);
    } else if (typeof motionQuery.addListener === "function") {
      motionQuery.addListener(handleMotionChange);
    }
  }
  syncFlightMenuState();
  updateOsmMenuState();
  updateFlightDebugOverlay();
}

async function initMap() {
  const tilejsonUrl = appState.overview?.tilejsonUrl || "/data/openmaptiles.json";
  const tilejsonInfo = await loadTileJsonInfo(tilejsonUrl);
  appState.osmSourceLayers = tilejsonInfo.sourceLayers;
  const initialView = tilejsonInfo.view;
  const currentAreaBounds = resolveCurrentAreaBounds(initialView.bounds);
  renderViewerNotice(Boolean(currentAreaBounds));
  appState.map = new maplibregl.Map({
    container: "map",
    style: buildStyle(tilejsonUrl, appState.selectedArea.featureCollection, {
      osmSourceLayers: appState.osmSourceLayers
    }),
    center: initialView.center,
    zoom: initialView.zoom
  });
  appState.map.addControl(new maplibregl.NavigationControl(), "top-right");
  appState.map.on("load", async () => {
    await registerFlightImages();
    await registerVesselImage();
    ensureFlightLayers();
    ensureVesselLayers();
    ensureStreetImageryLayers();
    bindFlightMapInteractions();
    applySelectedAreaOverlay();
    applyOsmOverlayVisibility();
    applyImageryOverlays();
    if (currentAreaBounds) {
      appState.map.fitBounds(currentAreaBounds, {
        padding: 40,
        animate: false
      });
    }
    updateFlightButtons();
    updateOsmOverlayButtons();
  });
  appState.map.on("moveend", () => {
    if (appState.flightsEnabled.opensky) {
      refreshFlights("opensky", true);
    }
    if (appState.flightsEnabled.adsbx) {
      refreshFlights("adsbx", true);
    }
    if (appState.vesselsEnabled) {
      refreshVessels(true);
    }
    if (appState.streetImagery.enabled) {
      scheduleStreetImageryRefresh(true);
    }
  });
}

async function init() {
  bindDomEvents();
  await Promise.all([safeLoadOverview(), safeLoadCapabilities(), safeLoadSelectedArea(), safeLoadImagery()]);
  updateFlightButtons();
  updateOsmOverlayButtons();
  await initMap();
}

window.addEventListener("DOMContentLoaded", () => {
  init().catch((error) => {
    console.error(error);
    showMessage(error.message, "error");
  });
});

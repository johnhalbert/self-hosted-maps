const fallbackView = {
  center: [-91.56, 31.63],
  zoom: 10,
  bounds: null
};

const flightProviders = {
  opensky: {
    buttonId: "toggleOpenSky",
    sourceId: "opensky-flights",
    layerId: "opensky-flight-points",
    color: "#f97316",
    minZoom: 4
  },
  adsbx: {
    buttonId: "toggleAdsbx",
    sourceId: "adsbx-flights",
    layerId: "adsbx-flight-points",
    color: "#7c3aed",
    minZoom: 6
  }
};

const appState = {
  map: null,
  overview: null,
  capabilities: {
    addressSearchEnabled: false,
    openSkyEnabled: false,
    adsbExchangeEnabled: false,
    adsbExchangeConfigured: false,
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
  flightsEnabled: {
    opensky: false,
    adsbx: false
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

function buildStyle(tilejsonUrl) {
  return {
    version: 8,
    glyphs: "/fonts/{fontstack}/{range}.pbf",
    sources: {
      worldLand: {
        type: "geojson",
        data: "/world-land.geojson"
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
        paint: { "background-color": "#dceeff" }
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
      }
    ]
  };
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
      selected: [],
      currentIds: [],
      selectedIds: [],
      currentIsStale: false,
      missingCurrentDatasetIds: []
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

async function loadTileJsonView(tilejsonUrl) {
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
    return nextView;
  } catch (error) {
    console.warn("Falling back to default map view.", error);
    return fallbackView;
  }
}

function ensureFlightLayers() {
  Object.values(flightProviders).forEach((provider) => {
    if (!appState.map.getSource(provider.sourceId)) {
      appState.map.addSource(provider.sourceId, {
        type: "geojson",
        data: emptyFeatureCollection()
      });
    }
    if (!appState.map.getLayer(provider.layerId)) {
      appState.map.addLayer({
        id: provider.layerId,
        type: "circle",
        source: provider.sourceId,
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            4,
            3,
            8,
            5,
            12,
            7
          ],
          "circle-color": provider.color,
          "circle-opacity": 0.85,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1
        }
      });
    }
  });
}

function setFlightData(providerKey, featureCollection) {
  const provider = flightProviders[providerKey];
  const source = appState.map.getSource(provider.sourceId);
  if (source) {
    source.setData(featureCollection);
  }
}

function updateFlightButtons() {
  const caps = appState.capabilities;
  const buttons = {
    opensky: document.getElementById(flightProviders.opensky.buttonId),
    adsbx: document.getElementById(flightProviders.adsbx.buttonId)
  };
  if (buttons.opensky) {
    buttons.opensky.disabled = !caps.openSkyEnabled;
    buttons.opensky.classList.toggle("active", appState.flightsEnabled.opensky);
    buttons.opensky.textContent = caps.openSkyEnabled ? "OpenSky" : "OpenSky (Unavailable)";
  }
  if (buttons.adsbx) {
    buttons.adsbx.disabled = !caps.adsbExchangeEnabled;
    buttons.adsbx.classList.toggle("active", appState.flightsEnabled.adsbx);
    buttons.adsbx.textContent = caps.adsbExchangeEnabled ? "ADS-B Exchange" : "ADS-B Exchange (Unavailable)";
  }
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
  if (appState.map.getZoom() < provider.minZoom) {
    setFlightData(providerKey, emptyFeatureCollection());
    if (!suppressErrors) {
      showMessage(`Zoom in to load ${providerKey === "opensky" ? "OpenSky" : "ADS-B Exchange"} flights.`, "warn");
    }
    return;
  }

  try {
    let url = "";
    if (providerKey === "opensky") {
      const query = currentBoundsQuery();
      url = `/api/flights/opensky?${new URLSearchParams(query).toString()}`;
    } else {
      const query = currentAdsbQuery();
      url = `/api/flights/adsbx?${new URLSearchParams(query).toString()}`;
    }
    const data = await requestJson(url);
    setFlightData(providerKey, data);
  } catch (error) {
    setFlightData(providerKey, emptyFeatureCollection());
    if (!suppressErrors) {
      showMessage(error.message, "warn");
    }
  }
}

function stopFlightPolling(providerKey) {
  window.clearInterval(appState.flightTimers[providerKey]);
  appState.flightTimers[providerKey] = null;
  setFlightData(providerKey, emptyFeatureCollection());
}

function toggleFlight(providerKey) {
  if (!appState.capabilities[providerKey === "opensky" ? "openSkyEnabled" : "adsbExchangeEnabled"]) {
    return;
  }

  appState.flightsEnabled[providerKey] = !appState.flightsEnabled[providerKey];
  updateFlightButtons();
  if (appState.flightsEnabled[providerKey]) {
    refreshFlights(providerKey);
    appState.flightTimers[providerKey] = window.setInterval(() => {
      refreshFlights(providerKey, true);
    }, 15000);
  } else {
    stopFlightPolling(providerKey);
  }
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
  const currentIds = overview.currentIds || [];
  const selectedIds = overview.selectedIds || [];
  const staleNote = overview.currentIsStale ? "Pending rebuild" : "In sync";
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
  const [overview, datasets] = await Promise.all([
    requestJson("/api/state"),
    requestJson("/api/datasets")
  ]);
  appState.overview = overview;
  appState.datasets = datasets.items || [];
  renderOverviewSummary();
  renderDownloadedMaps();
  renderSelectionList();
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
  document.getElementById("toggleOpenSky").addEventListener("click", () => toggleFlight("opensky"));
  document.getElementById("toggleAdsbx").addEventListener("click", () => toggleFlight("adsbx"));
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
}

async function initMap() {
  const tilejsonUrl = appState.overview?.tilejsonUrl || "/data/openmaptiles.json";
  const initialView = await loadTileJsonView(tilejsonUrl);
  appState.map = new maplibregl.Map({
    container: "map",
    style: buildStyle(tilejsonUrl),
    center: initialView.center,
    zoom: initialView.zoom
  });
  appState.map.addControl(new maplibregl.NavigationControl(), "top-right");
  appState.map.on("load", () => {
    ensureFlightLayers();
    if (initialView.bounds) {
      appState.map.fitBounds(initialView.bounds, {
        padding: 40,
        animate: false
      });
    }
    updateFlightButtons();
  });
  appState.map.on("moveend", () => {
    if (appState.flightsEnabled.opensky) {
      refreshFlights("opensky", true);
    }
    if (appState.flightsEnabled.adsbx) {
      refreshFlights("adsbx", true);
    }
  });
}

async function init() {
  bindDomEvents();
  await Promise.all([safeLoadOverview(), safeLoadCapabilities()]);
  updateFlightButtons();
  await initMap();
}

window.addEventListener("DOMContentLoaded", () => {
  init().catch((error) => {
    console.error(error);
    showMessage(error.message, "error");
  });
});

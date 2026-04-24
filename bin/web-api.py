#!/usr/bin/env python3
import argparse
import json
import math
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest


SCRIPT_PATH = Path(__file__).resolve()
BIN_DIR = SCRIPT_PATH.parent
INSTALL_ROOT = Path(os.environ.get("SHM_INSTALL_ROOT", str(BIN_DIR.parent)))
DATA_ROOT = Path(os.environ.get("SHM_DATA_ROOT", "/var/lib/self-hosted-maps"))
CONFIG_ROOT = Path(os.environ.get("SHM_CONFIG_ROOT", "/etc/self-hosted-maps"))
LOG_ROOT = Path(os.environ.get("SHM_LOG_ROOT", "/var/log/self-hosted-maps"))
STATE_FILE = Path(os.environ.get("SHM_STATE_FILE", str(CONFIG_ROOT / "datasets.json")))
CATALOG_FILE = Path(
    os.environ.get("SHM_NORMALIZED_CATALOG", str(DATA_ROOT / "cache" / "catalog" / "catalog.json"))
)
BOUNDARY_INDEX_FILE = Path(
    os.environ.get(
        "SHM_CATALOG_BOUNDARY_INDEX",
        str(DATA_ROOT / "cache" / "catalog" / "geofabrik-boundary-index.json"),
    )
)
JOBS_DIR = LOG_ROOT / "api-jobs"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_response(ok: bool, data=None, error=None):
    payload = {"ok": ok}
    if ok:
        payload["data"] = data if data is not None else {}
    else:
        payload["error"] = error or {"code": "unknown_error", "message": "Unknown error"}
    return payload


def default_state():
    return {
        "catalog": {
            "provider": "multi",
            "providers": [],
            "fetched_at": None,
            "cache_path": None,
            "sources": {},
            "installed_boundary_backfill": None,
        },
        "installed": {},
        "selected": [],
        "current": {
            "selected_hash": None,
            "artifact_path": None,
            "rebuilt_at": None,
            "dataset_ids": [],
        },
        "bootstrap": {},
    }


def read_state():
    if not STATE_FILE.exists():
        return default_state(), False
    try:
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default_state(), False

    merged = default_state()
    merged.update({k: v for k, v in state.items() if k not in {"catalog", "current"}})
    merged["catalog"].update(state.get("catalog") or {})
    merged["current"].update(state.get("current") or {})
    return merged, True


def read_catalog_cache():
    if not CATALOG_FILE.exists():
        return [], False
    try:
        with CATALOG_FILE.open("r", encoding="utf-8") as handle:
            return json.load(handle), True
    except (OSError, json.JSONDecodeError):
        return [], False


def read_boundary_index(state=None):
    catalog = (state or {}).get("catalog") or {}
    sources = catalog.get("sources") or {}
    geofabrik = sources.get("geofabrik") or {}
    path = Path(geofabrik.get("boundary_index_path") or BOUNDARY_INDEX_FILE)
    if not path.exists():
        return {}, False
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}, False
    items = payload.get("items") if isinstance(payload, dict) else {}
    if not isinstance(items, dict):
        return {}, False
    return items, True


def empty_feature_collection():
    return {"type": "FeatureCollection", "features": []}


def normalize_bounds(bounds):
    if not isinstance(bounds, list) or len(bounds) != 4:
        return None
    try:
        west, south, east, north = [float(value) for value in bounds]
    except (TypeError, ValueError):
        return None
    if west >= east or south >= north:
        return None
    return [[west, south], [east, north]]


def merge_bounds(left, right):
    if left is None:
        return right
    if right is None:
        return left
    return [
        [min(left[0][0], right[0][0]), min(left[0][1], right[0][1])],
        [max(left[1][0], right[1][0]), max(left[1][1], right[1][1])],
    ]


def compute_bounds_for_dataset_ids(dataset_ids, installed):
    if not dataset_ids:
        return None
    merged = None
    for dataset_id in dataset_ids:
        meta = installed.get(dataset_id) or {}
        bounds = normalize_bounds(meta.get("bounds") or [])
        if not bounds:
            return None
        merged = merge_bounds(merged, bounds)
    return merged


def default_boundary_reason(meta):
    boundary = meta.get("boundary") or {}
    if boundary.get("reason"):
        return str(boundary["reason"])
    provider = str(meta.get("provider") or "unknown")
    if provider in {"custom", "osm"}:
        return "non_catalog_dataset"
    if provider == "bbbike":
        return "provider_boundary_unavailable"
    if provider == "geofabrik":
        if not (meta.get("source_id") or "").strip():
            return "catalog_refresh_required"
        return "catalog_boundary_missing"
    return "boundary_unavailable"


def build_missing_boundary_item(dataset_id, meta=None, reason=None):
    meta = meta or {}
    return {
        "id": dataset_id,
        "name": meta.get("name") or dataset_id,
        "provider": meta.get("provider") or "unknown",
        "reason": reason or default_boundary_reason(meta),
    }


def human_size(size_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{int(size_bytes)}B"


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def read_file_size(path_str: str) -> int:
    if not path_str:
        return 0
    path = Path(path_str)
    if not path.exists() or not path.is_file():
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def compute_stale_flags(state):
    installed_ids = sorted((state.get("installed") or {}).keys())
    selected_ids = sorted(set(state.get("selected") or []))
    current_ids = sorted(set((state.get("current") or {}).get("dataset_ids") or []))
    missing_current = [dataset_id for dataset_id in current_ids if dataset_id not in installed_ids]
    return {
        "selectedIds": selected_ids,
        "currentIds": current_ids,
        "missingCurrentDatasetIds": missing_current,
        "currentIsStale": selected_ids != current_ids or bool(missing_current),
    }


def build_overview():
    state, state_present = read_state()
    stale = compute_stale_flags(state)
    rebuilt_at = (state.get("current") or {}).get("rebuilt_at")
    installed = state.get("installed") or {}
    current_bounds = compute_bounds_for_dataset_ids(stale["currentIds"], installed)
    tilejson_url = "/data/openmaptiles.json"
    if rebuilt_at:
        tilejson_url = f"{tilejson_url}?v={urlparse.quote(rebuilt_at, safe='')}"
    return {
        "statePresent": state_present,
        "catalog": state.get("catalog") or {},
        "selected": state.get("selected") or [],
        "current": state.get("current") or {},
        "bootstrap": state.get("bootstrap") or {},
        "tilejsonUrl": tilejson_url,
        "currentBounds": current_bounds,
        **stale,
    }


def build_dataset_list():
    state, state_present = read_state()
    installed = state.get("installed") or {}
    selected = set(state.get("selected") or [])
    current = set((state.get("current") or {}).get("dataset_ids") or [])
    bootstrap_id = (state.get("bootstrap") or {}).get("dataset_id")
    items = []
    for dataset_id in sorted(installed.keys()):
        meta = installed.get(dataset_id) or {}
        pbf_size_bytes = read_file_size(meta.get("pbf_path", ""))
        dataset_size_bytes = dir_size(Path(meta.get("dataset_dir", ""))) if meta.get("dataset_dir") else 0
        items.append(
            {
                "id": dataset_id,
                "name": meta.get("name") or dataset_id,
                "provider": meta.get("provider") or "unknown",
                "parent": meta.get("parent") or "",
                "downloadUrl": meta.get("download_url") or "",
                "installedAt": meta.get("installed_at") or "",
                "bounds": meta.get("bounds") or [],
                "sourceId": meta.get("source_id") or "",
                "boundaryAvailable": bool((meta.get("boundary") or {}).get("available")),
                "boundaryReason": default_boundary_reason(meta),
                "selected": dataset_id in selected,
                "current": dataset_id in current,
                "bootstrap": dataset_id == bootstrap_id,
                "pbfSizeBytes": pbf_size_bytes,
                "pbfSizeHuman": human_size(pbf_size_bytes),
                "datasetSizeBytes": dataset_size_bytes,
                "datasetSizeHuman": human_size(dataset_size_bytes),
                "updateHistoryCount": len(meta.get("update_history") or []),
            }
        )
    return {"statePresent": state_present, "items": items}


def build_catalog_response(query: str):
    state, state_present = read_state()
    items, cache_present = read_catalog_cache()
    query_lower = query.strip().lower()
    filtered = []
    for item in items:
        name = str(item.get("name") or "")
        dataset_id = str(item.get("id") or "")
        provider = str(item.get("provider") or "")
        parent = str(item.get("parent") or "")
        haystack = " ".join([name, dataset_id, provider, parent]).lower()
        if query_lower and query_lower not in haystack:
            continue
        filtered.append(
            {
                "id": dataset_id,
                "sourceId": str(item.get("source_id") or ""),
                "name": name,
                "provider": provider,
                "parent": parent,
                "downloadUrl": str(item.get("download_url") or ""),
                "bounds": item.get("bounds") or [],
                "boundaryAvailable": bool(item.get("boundary_available")),
            }
        )
    return {
        "statePresent": state_present,
        "cachePresent": cache_present,
        "catalog": state.get("catalog") or {},
        "items": filtered,
    }


def build_selected_area_response():
    state, _ = read_state()
    installed = state.get("installed") or {}
    selected_ids = [str(dataset_id) for dataset_id in (state.get("selected") or []) if str(dataset_id).strip()]
    boundary_index, boundary_index_present = read_boundary_index(state)
    available_ids = []
    missing_ids = []
    missing_items = []
    features = []

    for dataset_id in selected_ids:
        meta = installed.get(dataset_id)
        if not meta:
            missing_ids.append(dataset_id)
            missing_items.append(build_missing_boundary_item(dataset_id, reason="not_installed"))
            continue

        boundary = meta.get("boundary") or {}
        source_id = str(meta.get("source_id") or "").strip()
        if not boundary.get("available"):
            missing_ids.append(dataset_id)
            missing_items.append(build_missing_boundary_item(dataset_id, meta))
            continue

        if not source_id:
            missing_ids.append(dataset_id)
            missing_items.append(build_missing_boundary_item(dataset_id, meta, "catalog_refresh_required"))
            continue

        feature_data = boundary_index.get(source_id) if boundary_index_present else None
        geometry = feature_data.get("geometry") if isinstance(feature_data, dict) else None
        if not geometry:
            missing_ids.append(dataset_id)
            reason = "boundary_index_unavailable" if not boundary_index_present else "catalog_boundary_missing"
            missing_items.append(build_missing_boundary_item(dataset_id, meta, reason))
            continue

        available_ids.append(dataset_id)
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "datasetId": dataset_id,
                    "sourceId": source_id,
                    "name": meta.get("name") or feature_data.get("name") or dataset_id,
                    "provider": meta.get("provider") or feature_data.get("provider") or "unknown",
                    "parent": meta.get("parent") or feature_data.get("parent") or "",
                },
            }
        )

    feature_collection = empty_feature_collection()
    feature_collection["features"] = features
    return {
        "selectedIds": selected_ids,
        "availableBoundaryIds": available_ids,
        "missingBoundaryIds": missing_ids,
        "missingItems": missing_items,
        "featureCollection": feature_collection,
    }


def build_capabilities():
    adsb_key = os.environ.get("SHM_ADSBEXCHANGE_API_KEY", "").strip()
    return {
        "addressSearchEnabled": env_bool("SHM_ADDRESS_SEARCH_ENABLED", True),
        "openSkyEnabled": env_bool("SHM_OPENSKY_ENABLED", True),
        "adsbExchangeEnabled": env_bool("SHM_ADSBEXCHANGE_ENABLED", False) and bool(adsb_key),
        "adsbExchangeConfigured": bool(adsb_key),
        "adminTokenRequired": bool(os.environ.get("SHM_ADMIN_TOKEN", "").strip()),
    }


def http_get_json(url: str, headers=None, timeout: int = 15):
    request = urlrequest.Request(url, headers=headers or {})
    with urlrequest.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def geocode_query(query: str):
    if not env_bool("SHM_ADDRESS_SEARCH_ENABLED", True):
        raise RuntimeError("Address search is disabled.")

    base_url = os.environ.get("SHM_GEOCODER_URL", "https://nominatim.openstreetmap.org/search").strip()
    params = {"format": "jsonv2", "limit": "5", "q": query}
    url = f"{base_url}?{urlparse.urlencode(params)}"
    headers = {
        "Accept": "application/json",
        "User-Agent": os.environ.get("SHM_GEOCODER_USER_AGENT", "self-hosted-maps/1.0"),
    }
    payload = http_get_json(url, headers=headers, timeout=15)
    results = []
    for item in payload:
        lat = item.get("lat")
        lon = item.get("lon")
        if lat is None or lon is None:
            continue
        bounds = item.get("boundingbox") or []
        next_bounds = None
        if len(bounds) == 4:
            try:
                south = float(bounds[0])
                north = float(bounds[1])
                west = float(bounds[2])
                east = float(bounds[3])
                next_bounds = [[west, south], [east, north]]
            except (TypeError, ValueError):
                next_bounds = None
        results.append(
            {
                "displayName": item.get("display_name") or query,
                "lat": float(lat),
                "lng": float(lon),
                "bounds": next_bounds,
            }
        )
    return {"items": results}


def normalize_opensky(payload):
    features = []
    for state in payload.get("states") or []:
        if not isinstance(state, list) or len(state) < 17:
            continue
        lon = state[5]
        lat = state[6]
        if lat is None or lon is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "provider": "opensky",
                    "id": state[0],
                    "callsign": (state[1] or "").strip(),
                    "originCountry": state[2],
                    "baroAltitude": state[7],
                    "onGround": state[8],
                    "velocity": state[9],
                    "track": state[10],
                    "verticalRate": state[11],
                    "geoAltitude": state[13],
                    "squawk": state[14],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def fetch_opensky(query):
    if not env_bool("SHM_OPENSKY_ENABLED", True):
        raise RuntimeError("OpenSky is disabled.")

    try:
        lamin = float(query.get("lamin", [""])[0])
        lomin = float(query.get("lomin", [""])[0])
        lamax = float(query.get("lamax", [""])[0])
        lomax = float(query.get("lomax", [""])[0])
    except (TypeError, ValueError):
        raise ValueError("lamin, lomin, lamax, and lomax are required.")

    area = abs((lamax - lamin) * (lomax - lomin))
    if area > 400:
        raise ValueError("Requested OpenSky area is too large. Zoom in and try again.")

    base_url = os.environ.get("SHM_OPENSKY_API_BASE_URL", "https://opensky-network.org/api").rstrip("/")
    url = (
        f"{base_url}/states/all?lamin={lamin:.6f}&lomin={lomin:.6f}"
        f"&lamax={lamax:.6f}&lomax={lomax:.6f}"
    )
    payload = http_get_json(url, headers={"User-Agent": "self-hosted-maps/1.0"}, timeout=15)
    return normalize_opensky(payload)


def _pick(item, *keys):
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def normalize_adsbx(payload):
    features = []
    aircraft = payload.get("ac") or payload.get("acList") or payload.get("aircraft") or []
    for item in aircraft:
        if not isinstance(item, dict):
            continue
        lat = _pick(item, "lat", "Lat")
        lon = _pick(item, "lon", "Long", "Lng")
        if lat is None or lon is None:
            continue
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "provider": "adsbexchange",
                    "id": _pick(item, "hex", "icao", "Icao"),
                    "callsign": _pick(item, "flight", "call", "Call", "r"),
                    "aircraftType": _pick(item, "t", "type", "Type"),
                    "registration": _pick(item, "r", "reg", "Reg"),
                    "baroAltitude": _pick(item, "alt_baro", "Alt", "altitude"),
                    "onGround": _pick(item, "gnd", "Gnd"),
                    "velocity": _pick(item, "gs", "Spd", "speed"),
                    "track": _pick(item, "track", "Trak"),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def fetch_adsbx(query):
    if not env_bool("SHM_ADSBEXCHANGE_ENABLED", False):
        raise RuntimeError("ADS-B Exchange is disabled.")

    api_key = os.environ.get("SHM_ADSBEXCHANGE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ADS-B Exchange API key is not configured.")

    try:
        lat = float(query.get("lat", [""])[0])
        lng = float(query.get("lng", [""])[0])
        dist = int(float(query.get("dist", [""])[0]))
    except (TypeError, ValueError):
        raise ValueError("lat, lng, and dist are required.")

    dist = max(1, min(dist, 100))
    base_url = os.environ.get("SHM_ADSBEXCHANGE_API_BASE_URL", "https://adsbexchange.com/api").rstrip("/")
    url = f"{base_url}/aircraft/lat/{lat:.5f}/lon/{lng:.5f}/dist/{dist}/"
    payload = http_get_json(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "self-hosted-maps/1.0",
            "api-auth": api_key,
        },
        timeout=15,
    )
    return normalize_adsbx(payload)


class JobStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs = {}
        self._running_job_id = None

    def _serialize_job(self, job):
        result = dict(job)
        log_path = Path(result["logPath"])
        if log_path.exists():
            try:
                with log_path.open("r", encoding="utf-8") as handle:
                    result["logTail"] = handle.readlines()[-40:]
            except OSError:
                result["logTail"] = []
        else:
            result["logTail"] = []
        return result

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return self._serialize_job(job)

    def current(self):
        with self._lock:
            if not self._running_job_id:
                return None
            return self._serialize_job(self._jobs[self._running_job_id])

    def create(self, action, command):
        with self._lock:
            if self._running_job_id:
                current = self._serialize_job(self._jobs[self._running_job_id])
                raise RuntimeError(json.dumps(current))

            job_id = uuid.uuid4().hex
            log_path = JOBS_DIR / f"{job_id}.log"
            JOBS_DIR.mkdir(parents=True, exist_ok=True)
            job = {
                "id": job_id,
                "action": action,
                "command": command,
                "status": "queued",
                "createdAt": iso_now(),
                "startedAt": None,
                "finishedAt": None,
                "error": None,
                "logPath": str(log_path),
            }
            self._jobs[job_id] = job
            self._running_job_id = job_id
            thread = threading.Thread(target=self._run, args=(job_id,), daemon=True)
            thread.start()
            return self._serialize_job(job)

    def _run(self, job_id):
        with self._lock:
            job = self._jobs[job_id]
            job["status"] = "running"
            job["startedAt"] = iso_now()
            command = list(job["command"])
            log_path = Path(job["logPath"])

        env = os.environ.copy()
        with log_path.open("a", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=str(INSTALL_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            assert process.stdout is not None
            for line in process.stdout:
                log_handle.write(line)
                log_handle.flush()
            return_code = process.wait()

        with self._lock:
            job = self._jobs[job_id]
            job["finishedAt"] = iso_now()
            if return_code == 0:
                job["status"] = "success"
            else:
                job["status"] = "error"
                job["error"] = f"Command exited with status {return_code}"
            self._running_job_id = None


JOB_STORE = JobStore()


class Handler(BaseHTTPRequestHandler):
    server_version = "self-hosted-maps-api/1.0"

    def log_message(self, fmt, *args):
        print("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), fmt % args))

    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _require_admin(self):
        token = os.environ.get("SHM_ADMIN_TOKEN", "").strip()
        if not token:
            return True
        auth_header = self.headers.get("Authorization", "").strip()
        token_header = self.headers.get("X-SHM-Admin-Token", "").strip()
        if auth_header == f"Bearer {token}" or token_header == token:
            return True
        self._send_json(
            401,
            json_response(
                False,
                error={"code": "admin_token_required", "message": "Admin token required."},
            ),
        )
        return False

    def do_GET(self):
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        query = urlparse.parse_qs(parsed.query)
        try:
            if path == "/api/health":
                self._send_json(200, json_response(True, {"status": "ok"}))
            elif path == "/api/state":
                self._send_json(200, json_response(True, build_overview()))
            elif path == "/api/datasets":
                self._send_json(200, json_response(True, build_dataset_list()))
            elif path.startswith("/api/datasets/"):
                dataset_id = path.split("/", 3)[3]
                datasets = build_dataset_list()
                dataset = next((item for item in datasets["items"] if item["id"] == dataset_id), None)
                if not dataset:
                    self._send_json(
                        404,
                        json_response(False, error={"code": "dataset_not_found", "message": "Unknown dataset."}),
                    )
                else:
                    self._send_json(200, json_response(True, dataset))
            elif path == "/api/catalog":
                query_text = (query.get("q") or [""])[0]
                self._send_json(200, json_response(True, build_catalog_response(query_text)))
            elif path == "/api/selected-area":
                self._send_json(200, json_response(True, build_selected_area_response()))
            elif path == "/api/capabilities":
                self._send_json(200, json_response(True, build_capabilities()))
            elif path == "/api/search":
                search_query = (query.get("q") or [""])[0].strip()
                if not search_query:
                    self._send_json(
                        400,
                        json_response(False, error={"code": "missing_query", "message": "Missing search query."}),
                    )
                    return
                self._send_json(200, json_response(True, geocode_query(search_query)))
            elif path == "/api/flights/opensky":
                self._send_json(200, json_response(True, fetch_opensky(query)))
            elif path == "/api/flights/adsbx":
                self._send_json(200, json_response(True, fetch_adsbx(query)))
            elif path == "/api/admin/jobs/current":
                if not self._require_admin():
                    return
                self._send_json(200, json_response(True, {"job": JOB_STORE.current()}))
            elif path.startswith("/api/admin/jobs/"):
                if not self._require_admin():
                    return
                job_id = path.rsplit("/", 1)[-1]
                job = JOB_STORE.get(job_id)
                if not job:
                    self._send_json(
                        404,
                        json_response(False, error={"code": "job_not_found", "message": "Unknown job id."}),
                    )
                    return
                self._send_json(200, json_response(True, {"job": job}))
            else:
                self._send_json(404, json_response(False, error={"code": "not_found", "message": "Not found."}))
        except ValueError as exc:
            self._send_json(400, json_response(False, error={"code": "bad_request", "message": str(exc)}))
        except RuntimeError as exc:
            self._send_json(503, json_response(False, error={"code": "unavailable", "message": str(exc)}))
        except urlerror.HTTPError as exc:
            self._send_json(
                502,
                json_response(
                    False,
                    error={"code": "upstream_error", "message": f"Upstream request failed with {exc.code}."},
                ),
            )
        except urlerror.URLError:
            self._send_json(
                502,
                json_response(False, error={"code": "upstream_unavailable", "message": "Upstream request failed."}),
            )

    def do_POST(self):
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/admin/"):
            self._send_json(404, json_response(False, error={"code": "not_found", "message": "Not found."}))
            return
        if not self._require_admin():
            return

        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._send_json(
                400,
                json_response(False, error={"code": "invalid_json", "message": "Request body must be JSON."}),
            )
            return

        try:
            if path == "/api/admin/refresh-catalog":
                job = JOB_STORE.create("refresh_catalog", ["bash", str(BIN_DIR / "refresh-catalog.sh")])
            elif path == "/api/admin/install":
                dataset_id = (payload.get("datasetId") or "").strip()
                if not dataset_id:
                    raise ValueError("datasetId is required.")
                job = JOB_STORE.create(
                    "install_dataset",
                    ["bash", str(BIN_DIR / "install-dataset.sh"), dataset_id],
                )
            elif path == "/api/admin/activate":
                dataset_ids = payload.get("datasetIds") or []
                if not isinstance(dataset_ids, list) or not dataset_ids:
                    raise ValueError("datasetIds must be a non-empty array.")
                dataset_ids = [str(dataset_id).strip() for dataset_id in dataset_ids if str(dataset_id).strip()]
                if not dataset_ids:
                    raise ValueError("datasetIds must contain at least one dataset id.")
                job = JOB_STORE.create(
                    "activate_selection",
                    ["bash", str(BIN_DIR / "activate-selection.sh"), *dataset_ids],
                )
            else:
                self._send_json(404, json_response(False, error={"code": "not_found", "message": "Not found."}))
                return
        except RuntimeError as exc:
            try:
                current = json.loads(str(exc))
            except json.JSONDecodeError:
                current = JOB_STORE.current()
            self._send_json(
                409,
                json_response(
                    False,
                    error={"code": "job_in_progress", "message": "Another administrative job is already running."},
                )
                | {"currentJob": current},
            )
            return
        except ValueError as exc:
            self._send_json(400, json_response(False, error={"code": "bad_request", "message": str(exc)}))
            return

        self._send_json(202, json_response(True, {"job": job}))


def main():
    parser = argparse.ArgumentParser(description="Self Hosted Maps API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SHM_API_PORT", "8090")))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

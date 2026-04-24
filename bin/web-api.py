#!/usr/bin/env python3
import argparse
import json
import math
import os
import subprocess
import sys
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
DISPLAY_BOUNDARY_INDEX_NAME = "us-state-display-boundary-index.json"
DISPLAY_BOUNDARY_INDEX_ENV = "SHM_DISPLAY_BOUNDARY_INDEX_FILE"
JOBS_DIR = LOG_ROOT / "api-jobs"
JSON_FILE_CACHE = {}
OPENSKY_DEFAULT_TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
OPENSKY_TOKEN_REFRESH_SKEW_SECONDS = 60
OPENSKY_TOKEN_FALLBACK_EXPIRES_SECONDS = 1500


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


def read_json_file(path: Path, warn_label: str = ""):
    cache_key = str(path)
    try:
        stat = path.stat()
    except OSError:
        JSON_FILE_CACHE.pop(cache_key, None)
        return None, False

    signature = (stat.st_mtime_ns, stat.st_size)
    cached = JSON_FILE_CACHE.get(cache_key)
    if cached and cached.get("signature") == signature:
        return cached.get("data"), True

    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        JSON_FILE_CACHE.pop(cache_key, None)
        if warn_label:
            print(f"Warning: unable to read {warn_label} at {path}: {exc}", file=sys.stderr, flush=True)
        return None, False

    JSON_FILE_CACHE[cache_key] = {"signature": signature, "data": payload}
    return payload, True


def read_catalog_cache():
    payload, present = read_json_file(CATALOG_FILE)
    if not present or not isinstance(payload, list):
        return [], False
    return payload, True


def read_boundary_index(state=None):
    catalog = (state or {}).get("catalog") or {}
    sources = catalog.get("sources") or {}
    geofabrik = sources.get("geofabrik") or {}
    path = Path(geofabrik.get("boundary_index_path") or BOUNDARY_INDEX_FILE)
    if not path.exists():
        return {}, False
    payload, present = read_json_file(path)
    if not present:
        return {}, False
    items = payload.get("items") if isinstance(payload, dict) else {}
    if not isinstance(items, dict):
        return {}, False
    return items, True


def is_checkout_tree(root: Path) -> bool:
    return (root / "assets" / "app.js").exists() and (root / "scripts" / "install-runtime.sh").exists()


def resolve_display_boundary_index_path(install_root: Path | None = None, env_path: str | None = None):
    root = Path(install_root or INSTALL_ROOT)
    override = env_path if env_path is not None else os.environ.get(DISPLAY_BOUNDARY_INDEX_ENV, "").strip()
    if override:
        return Path(override)

    installed_path = root / "www" / DISPLAY_BOUNDARY_INDEX_NAME
    if installed_path.exists():
        return installed_path

    if is_checkout_tree(root):
        repo_path = root / "assets" / DISPLAY_BOUNDARY_INDEX_NAME
        if repo_path.exists():
            return repo_path

    return None


def read_display_boundary_index():
    path = resolve_display_boundary_index_path()
    if path is None:
        return {}, False
    if not path.exists():
        print(f"Warning: display boundary index not found at {path}", file=sys.stderr, flush=True)
        return {}, False

    payload, present = read_json_file(path, warn_label="display boundary index")
    if not present or not isinstance(payload, dict):
        return {}, False

    items = payload.get("items") if isinstance(payload, dict) else {}
    if not isinstance(items, dict):
        print(f"Warning: invalid display boundary index payload at {path}", file=sys.stderr, flush=True)
        return {}, False
    return items, True


def build_catalog_lookup(items):
    lookup = {"by_id": {}, "by_source_id": {}, "by_download_url": {}}
    for item in items:
        if not isinstance(item, dict):
            continue
        dataset_id = str(item.get("id") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        download_url = str(item.get("download_url") or "").strip()
        if dataset_id and dataset_id not in lookup["by_id"]:
            lookup["by_id"][dataset_id] = item
        if source_id and source_id not in lookup["by_source_id"]:
            lookup["by_source_id"][source_id] = item
        if download_url and download_url not in lookup["by_download_url"]:
            lookup["by_download_url"][download_url] = item
    return lookup


def resolve_catalog_entry_for_installed_dataset(dataset_id, meta, catalog_lookup):
    if not catalog_lookup:
        return None

    source_id = str(meta.get("source_id") or "").strip()
    if source_id:
        match = catalog_lookup["by_source_id"].get(source_id)
        if match:
            return match

    match = catalog_lookup["by_id"].get(str(dataset_id))
    if match:
        return match

    download_url = str(meta.get("download_url") or "").strip()
    if download_url:
        return catalog_lookup["by_download_url"].get(download_url)
    return None


def extract_geometry(entry):
    geometry = entry.get("geometry") if isinstance(entry, dict) else None
    return geometry if isinstance(geometry, dict) else None


def overlay_boundary_label(source: str) -> str:
    if source == "display":
        return "Curated display boundary"
    if source == "provider":
        return "Provider boundary fallback"
    return "No boundary overlay"


def resolve_overlay_state(dataset_id, meta, catalog_lookup, boundary_index, boundary_index_present, display_index):
    meta = meta or {}
    catalog_item = resolve_catalog_entry_for_installed_dataset(dataset_id, meta, catalog_lookup)

    source_id = str((catalog_item or {}).get("source_id") or meta.get("source_id") or "").strip()
    provider = str(meta.get("provider") or (catalog_item or {}).get("provider") or "unknown")
    name = str(meta.get("name") or (catalog_item or {}).get("name") or dataset_id)
    parent = str(meta.get("parent") or (catalog_item or {}).get("parent") or "")

    display_entry = display_index.get(source_id) if provider == "geofabrik" and source_id else None
    display_geometry = extract_geometry(display_entry)

    provider_entry = boundary_index.get(source_id) if provider == "geofabrik" and source_id and boundary_index_present else None
    provider_geometry = extract_geometry(provider_entry)

    provider_reason = ""
    if provider == "geofabrik":
        if not provider_geometry:
            if not source_id:
                provider_reason = "catalog_refresh_required"
            elif not boundary_index_present:
                provider_reason = "boundary_index_unavailable"
            else:
                provider_reason = "catalog_boundary_missing"
    elif not bool((meta.get("boundary") or {}).get("available")):
        provider_reason = default_boundary_reason(meta)

    overlay_source = ""
    overlay_reason = ""
    overlay_geometry = None
    if display_geometry:
        overlay_source = "display"
        overlay_geometry = display_geometry
    elif provider_geometry:
        overlay_source = "provider"
        overlay_geometry = provider_geometry
        overlay_reason = "display_boundary_unavailable"
    else:
        overlay_reason = provider_reason or default_boundary_reason(meta)

    return {
        "datasetId": dataset_id,
        "sourceId": source_id,
        "provider": provider,
        "name": name,
        "parent": parent,
        "geometry": overlay_geometry,
        "overlayBoundaryAvailable": bool(overlay_geometry),
        "overlayBoundarySource": overlay_source,
        "overlayBoundaryLabel": overlay_boundary_label(overlay_source),
        "overlayBoundaryReason": overlay_reason,
        "displayBoundaryAvailable": bool(display_geometry),
        "providerBoundaryAvailable": bool(provider_geometry),
        "providerBoundaryReason": provider_reason,
    }


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
    catalog_items, _ = read_catalog_cache()
    catalog_lookup = build_catalog_lookup(catalog_items)
    boundary_index, boundary_index_present = read_boundary_index(state)
    display_index, _ = read_display_boundary_index()
    items = []
    for dataset_id in sorted(installed.keys()):
        meta = installed.get(dataset_id) or {}
        overlay = resolve_overlay_state(
            dataset_id,
            meta,
            catalog_lookup,
            boundary_index,
            boundary_index_present,
            display_index,
        )
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
                "displayBoundaryAvailable": overlay["displayBoundaryAvailable"],
                "providerBoundaryAvailable": overlay["providerBoundaryAvailable"],
                "providerBoundaryReason": overlay["providerBoundaryReason"],
                "overlayBoundaryAvailable": overlay["overlayBoundaryAvailable"],
                "overlayBoundarySource": overlay["overlayBoundarySource"],
                "overlayBoundaryLabel": overlay["overlayBoundaryLabel"],
                "overlayBoundaryReason": overlay["overlayBoundaryReason"],
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
    catalog_items, _ = read_catalog_cache()
    catalog_lookup = build_catalog_lookup(catalog_items)
    boundary_index, boundary_index_present = read_boundary_index(state)
    display_index, _ = read_display_boundary_index()
    available_ids = []
    display_ids = []
    provider_fallback_ids = []
    missing_ids = []
    missing_items = []
    features = []

    for dataset_id in selected_ids:
        meta = installed.get(dataset_id)
        if not meta:
            missing_ids.append(dataset_id)
            missing_items.append(build_missing_boundary_item(dataset_id, reason="not_installed"))
            continue

        overlay = resolve_overlay_state(
            dataset_id,
            meta,
            catalog_lookup,
            boundary_index,
            boundary_index_present,
            display_index,
        )
        geometry = overlay["geometry"]
        if not geometry:
            missing_ids.append(dataset_id)
            missing_items.append(build_missing_boundary_item(dataset_id, meta, overlay["overlayBoundaryReason"]))
            continue

        available_ids.append(dataset_id)
        if overlay["overlayBoundarySource"] == "display":
            display_ids.append(dataset_id)
        elif overlay["overlayBoundarySource"] == "provider":
            provider_fallback_ids.append(dataset_id)
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "datasetId": dataset_id,
                    "sourceId": overlay["sourceId"],
                    "name": overlay["name"],
                    "provider": overlay["provider"],
                    "parent": overlay["parent"],
                    "overlaySource": overlay["overlayBoundarySource"],
                },
            }
        )

    feature_collection = empty_feature_collection()
    feature_collection["features"] = features
    return {
        "selectedIds": selected_ids,
        "availableBoundaryIds": available_ids,
        "displayBoundaryIds": display_ids,
        "providerFallbackIds": provider_fallback_ids,
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


def http_post_form_json(url: str, form, headers=None, timeout: int = 15):
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        **(headers or {}),
    }
    body = urlparse.urlencode(form).encode("utf-8")
    request = urlrequest.Request(url, data=body, headers=request_headers, method="POST")
    with urlrequest.urlopen(request, timeout=timeout) as response:
        try:
            return json.loads(response.read().decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenSky token response was not valid JSON.") from exc


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


FLIGHT_SNAPSHOT_TTL_MS = 45_000
PROVIDER_LABELS = {"opensky": "OpenSky", "adsbx": "ADS-B Exchange"}
OPENSKY_STATE_FIELDS = [
    "icao24",
    "callsign",
    "origin_country",
    "time_position",
    "last_contact",
    "longitude",
    "latitude",
    "baro_altitude",
    "on_ground",
    "velocity",
    "true_track",
    "vertical_rate",
    "sensors",
    "geo_altitude",
    "squawk",
    "spi",
    "position_source",
    "category",
]


def current_time_ms():
    return int(time.time() * 1000)


def sanitize_json_value(value):
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_json_value(item) for key, item in value.items()}
    return value


def clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def maybe_float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def maybe_bool(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(text)


def normalize_record_key(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def meters_to_feet(value):
    number = maybe_float(value)
    if number is None:
        return None
    return round(number * 3.28084, 1)


def mps_to_knots(value):
    number = maybe_float(value)
    if number is None:
        return None
    return round(number * 1.943844, 1)


def knots_to_mps(value):
    number = maybe_float(value)
    if number is None:
        return None
    return round(number * 0.514444, 2)


def epoch_seconds_to_ms(value):
    number = maybe_float(value)
    if number is None:
        return None
    return int(round(number * 1000))


def age_at_fetch_ms(fetched_at_ms, timestamp_ms):
    if timestamp_ms is None:
        return None
    return max(0, int(fetched_at_ms - timestamp_ms))


def build_label_primary(callsign, craft_number, display_id):
    return callsign or craft_number or display_id or ""


def build_label_full(callsign, craft_number, display_id):
    primary = build_label_primary(callsign, craft_number, display_id)
    secondary = craft_number or display_id
    if callsign and secondary and callsign != secondary:
        return f"{callsign} • {secondary}"
    return primary


class OpenSkyTokenCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._token = None
        self._refresh_after = 0
        self._cache_key = None

    def clear(self):
        with self._lock:
            self._token = None
            self._refresh_after = 0
            self._cache_key = None

    def get_token(self, now=None):
        client_id = os.environ.get("SHM_OPENSKY_CLIENT_ID", "").strip()
        client_secret = os.environ.get("SHM_OPENSKY_CLIENT_SECRET", "").strip()
        if not client_id and not client_secret:
            return None
        if not client_id or not client_secret:
            raise RuntimeError("OpenSky OAuth credentials are incomplete.")

        token_url = os.environ.get("SHM_OPENSKY_TOKEN_URL", OPENSKY_DEFAULT_TOKEN_URL).strip()
        token_url = token_url or OPENSKY_DEFAULT_TOKEN_URL
        now = float(time.time() if now is None else now)
        cache_key = (client_id, client_secret, token_url)
        with self._lock:
            if self._token and self._cache_key == cache_key and now < self._refresh_after:
                return self._token
            token_response = self._request_token(token_url, client_id, client_secret)
            token = clean_text(token_response.get("access_token"))
            if not token:
                raise RuntimeError("OpenSky token response did not include an access token.")
            expires_seconds = maybe_float(token_response.get("expires_in"))
            if expires_seconds is None or expires_seconds <= 0:
                expires_seconds = OPENSKY_TOKEN_FALLBACK_EXPIRES_SECONDS
            refresh_skew = min(OPENSKY_TOKEN_REFRESH_SKEW_SECONDS, max(0, expires_seconds / 2))
            self._token = token
            self._refresh_after = now + max(1, expires_seconds - refresh_skew)
            self._cache_key = cache_key
            return self._token

    def _request_token(self, token_url, client_id, client_secret):
        try:
            token_response = http_post_form_json(
                token_url,
                {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=15,
            )
        except (urlerror.HTTPError, urlerror.URLError):
            raise
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Unable to fetch OpenSky OAuth token.") from exc
        if not isinstance(token_response, dict):
            raise RuntimeError("OpenSky token response was not a JSON object.")
        return token_response


OPENSKY_TOKEN_CACHE = OpenSkyTokenCache()


def require_flight_provider_key(value):
    provider_key = str(value or "").strip().lower()
    if provider_key not in PROVIDER_LABELS:
        raise ValueError("providerKey must be one of opensky or adsbx.")
    return provider_key


def build_detail_summary(provider_key, properties, latitude, longitude):
    return {
        "providerLabel": PROVIDER_LABELS[provider_key],
        "labelPrimary": properties.get("labelPrimary"),
        "labelFull": properties.get("labelFull"),
        "displayId": properties.get("displayId"),
        "callsign": properties.get("callsign"),
        "flightNumber": properties.get("flightNumber"),
        "craftNumber": properties.get("craftNumber"),
        "registration": properties.get("registration"),
        "aircraftType": properties.get("aircraftType"),
        "originCountry": properties.get("originCountry"),
        "squawk": properties.get("squawk"),
        "latitude": latitude,
        "longitude": longitude,
        "baroAltitude": properties.get("baroAltitude"),
        "geoAltitude": properties.get("geoAltitude"),
        "baroAltitudeFt": properties.get("baroAltitudeFt"),
        "geoAltitudeFt": properties.get("geoAltitudeFt"),
        "onGround": properties.get("onGround"),
        "groundSpeedMps": properties.get("groundSpeedMps"),
        "groundSpeedKts": properties.get("groundSpeedKts"),
        "headingDeg": properties.get("headingDeg"),
        "verticalRateMps": properties.get("verticalRateMps"),
        "positionTimestampMs": properties.get("positionTimestampMs"),
        "lastSeenTimestampMs": properties.get("lastSeenTimestampMs"),
        "positionAgeMsAtFetch": properties.get("positionAgeMsAtFetch"),
        "contactAgeMsAtFetch": properties.get("contactAgeMsAtFetch"),
    }


def make_feature_collection(provider_key, fetched_at_ms, features):
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "providerKey": provider_key,
            "providerLabel": PROVIDER_LABELS[provider_key],
            "fetchedAtMs": fetched_at_ms,
        },
    }


def build_opensky_detail_raw(state, response_time):
    mapped = {}
    for index, field in enumerate(OPENSKY_STATE_FIELDS):
        mapped[field] = sanitize_json_value(state[index]) if index < len(state) else None
    return {
        "schema": "opensky.state_vector.v1",
        "data": {
            "time": sanitize_json_value(response_time),
            "state": sanitize_json_value(state),
        },
        "mapped": mapped,
    }


def build_adsbx_detail_raw(item, response_now):
    return {
        "schema": "adsbx.aircraft.v1",
        "data": sanitize_json_value(item),
        "context": {"now": sanitize_json_value(response_now)},
    }


def build_opensky_record(state, fetched_at_ms, response_time):
    if not isinstance(state, list) or len(state) < 17:
        return None

    longitude = maybe_float(state[5])
    latitude = maybe_float(state[6])
    if latitude is None or longitude is None:
        return None

    record_key = normalize_record_key(state[0])
    if not record_key:
        return None

    callsign = clean_text(state[1])
    flight_number = callsign
    craft_number = None
    display_id = record_key.upper()
    baro_altitude = maybe_float(state[7])
    geo_altitude = maybe_float(state[13])
    on_ground = maybe_bool(state[8])
    velocity = maybe_float(state[9])
    track = maybe_float(state[10])
    vertical_rate = maybe_float(state[11])
    position_timestamp_ms = epoch_seconds_to_ms(state[3])
    last_seen_timestamp_ms = epoch_seconds_to_ms(state[4])
    label_primary = build_label_primary(flight_number, craft_number, display_id)
    label_full = build_label_full(flight_number, craft_number, display_id)
    entity_key = f"opensky:{record_key}"
    properties = {
        "provider": "opensky",
        "providerKey": "opensky",
        "providerLabel": PROVIDER_LABELS["opensky"],
        "id": state[0],
        "recordKey": record_key,
        "entityKey": entity_key,
        "displayId": display_id,
        "callsign": callsign,
        "flightNumber": flight_number,
        "craftNumber": craft_number,
        "registration": None,
        "aircraftType": None,
        "originCountry": clean_text(state[2]),
        "baroAltitude": baro_altitude,
        "baroAltitudeFt": meters_to_feet(baro_altitude),
        "geoAltitude": geo_altitude,
        "geoAltitudeFt": meters_to_feet(geo_altitude),
        "onGround": on_ground,
        "velocity": velocity,
        "groundSpeedMps": velocity,
        "groundSpeedKts": mps_to_knots(velocity),
        "track": track,
        "headingDeg": track,
        "verticalRate": vertical_rate,
        "verticalRateMps": vertical_rate,
        "squawk": clean_text(state[14]),
        "positionTimestampMs": position_timestamp_ms,
        "lastSeenTimestampMs": last_seen_timestamp_ms,
        "positionAgeMsAtFetch": age_at_fetch_ms(fetched_at_ms, position_timestamp_ms),
        "contactAgeMsAtFetch": age_at_fetch_ms(fetched_at_ms, last_seen_timestamp_ms),
        "labelPrimary": label_primary,
        "labelFull": label_full,
        "detailAvailable": True,
    }
    feature = {
        "type": "Feature",
        "id": entity_key,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": properties,
    }
    detail_entry = {
        "provider": "opensky",
        "providerKey": "opensky",
        "recordKey": record_key,
        "entityKey": entity_key,
        "fetchedAtMs": fetched_at_ms,
        "summary": build_detail_summary("opensky", properties, latitude, longitude),
        "raw": build_opensky_detail_raw(state, response_time),
    }
    return {"feature": feature, "detail": detail_entry, "recordKey": record_key}


def build_adsbx_record(item, fetched_at_ms, response_now):
    if not isinstance(item, dict):
        return None

    latitude = maybe_float(_pick(item, "lat", "Lat"))
    longitude = maybe_float(_pick(item, "lon", "Long", "Lng"))
    if latitude is None or longitude is None:
        return None

    record_key = normalize_record_key(_pick(item, "hex", "icao", "Icao"))
    if not record_key:
        return None

    flight_number = clean_text(_pick(item, "flight", "call", "Call"))
    registration = clean_text(_pick(item, "r", "reg", "Reg"))
    callsign = clean_text(_pick(item, "flight", "call", "Call", "r"))
    display_id = record_key.upper()
    ground_speed_kts = maybe_float(_pick(item, "gs", "Spd", "speed"))
    track = maybe_float(_pick(item, "track", "Trak"))
    position_age_ms = None
    last_seen_age_ms = None
    seen_pos_seconds = maybe_float(_pick(item, "seen_pos", "SeenPos"))
    seen_seconds = maybe_float(_pick(item, "seen", "Seen"))
    if seen_pos_seconds is not None:
        position_age_ms = max(0, int(round(seen_pos_seconds * 1000)))
    if seen_seconds is not None:
        last_seen_age_ms = max(0, int(round(seen_seconds * 1000)))
    label_primary = build_label_primary(flight_number, registration or display_id, display_id)
    label_full = build_label_full(flight_number, registration or display_id, display_id)
    entity_key = f"adsbx:{record_key}"
    baro_altitude_raw = _pick(item, "alt_baro", "Alt", "altitude")
    geo_altitude_raw = _pick(item, "alt_geom", "geo_altitude")
    baro_altitude = maybe_float(baro_altitude_raw)
    geo_altitude = maybe_float(geo_altitude_raw)
    vertical_rate_fpm = maybe_float(_pick(item, "baro_rate", "roc", "vert_rate"))
    properties = {
        "provider": "adsbexchange",
        "providerKey": "adsbx",
        "providerLabel": PROVIDER_LABELS["adsbx"],
        "id": _pick(item, "hex", "icao", "Icao"),
        "recordKey": record_key,
        "entityKey": entity_key,
        "displayId": display_id,
        "callsign": callsign,
        "flightNumber": flight_number,
        "craftNumber": registration or display_id,
        "registration": registration,
        "aircraftType": clean_text(_pick(item, "t", "type", "Type")),
        "originCountry": clean_text(_pick(item, "country", "country_name")),
        "baroAltitude": baro_altitude_raw,
        "baroAltitudeFt": baro_altitude,
        "geoAltitude": geo_altitude_raw,
        "geoAltitudeFt": geo_altitude,
        "onGround": maybe_bool(_pick(item, "gnd", "Gnd")),
        "velocity": _pick(item, "gs", "Spd", "speed"),
        "groundSpeedMps": knots_to_mps(ground_speed_kts),
        "groundSpeedKts": ground_speed_kts,
        "track": track,
        "headingDeg": track,
        "verticalRate": vertical_rate_fpm,
        "verticalRateMps": round(vertical_rate_fpm * 0.00508, 2) if vertical_rate_fpm is not None else None,
        "squawk": clean_text(_pick(item, "squawk", "Sqk")),
        "positionTimestampMs": fetched_at_ms - position_age_ms if position_age_ms is not None else None,
        "lastSeenTimestampMs": fetched_at_ms - last_seen_age_ms if last_seen_age_ms is not None else None,
        "positionAgeMsAtFetch": position_age_ms,
        "contactAgeMsAtFetch": last_seen_age_ms,
        "labelPrimary": label_primary,
        "labelFull": label_full,
        "detailAvailable": True,
    }
    feature = {
        "type": "Feature",
        "id": entity_key,
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": properties,
    }
    detail_entry = {
        "provider": "adsbexchange",
        "providerKey": "adsbx",
        "recordKey": record_key,
        "entityKey": entity_key,
        "fetchedAtMs": fetched_at_ms,
        "summary": build_detail_summary("adsbx", properties, latitude, longitude),
        "raw": build_adsbx_detail_raw(item, response_now),
    }
    return {"feature": feature, "detail": detail_entry, "recordKey": record_key}


def normalize_opensky(payload, fetched_at_ms=None):
    fetched_at_ms = int(fetched_at_ms or current_time_ms())
    features = []
    detail_entries = {}
    response_time = payload.get("time")
    for state in payload.get("states") or []:
        record = build_opensky_record(state, fetched_at_ms, response_time)
        if not record:
            continue
        features.append(record["feature"])
        detail_entries[record["recordKey"]] = record["detail"]
    return make_feature_collection("opensky", fetched_at_ms, features), detail_entries


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
    generation = FLIGHT_SNAPSHOT_CACHE.begin_request("opensky")
    headers = {"User-Agent": "self-hosted-maps/1.0"}
    token = OPENSKY_TOKEN_CACHE.get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = http_get_json(url, headers=headers, timeout=15)
    fetched_at_ms = current_time_ms()
    feature_collection, detail_entries = normalize_opensky(payload, fetched_at_ms=fetched_at_ms)
    FLIGHT_SNAPSHOT_CACHE.commit("opensky", generation, fetched_at_ms, detail_entries)
    return feature_collection


def _pick(item, *keys):
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def normalize_adsbx(payload, fetched_at_ms=None):
    fetched_at_ms = int(fetched_at_ms or current_time_ms())
    features = []
    detail_entries = {}
    response_now = payload.get("now")
    aircraft = payload.get("ac") or payload.get("acList") or payload.get("aircraft") or []
    for item in aircraft:
        record = build_adsbx_record(item, fetched_at_ms, response_now)
        if not record:
            continue
        features.append(record["feature"])
        detail_entries[record["recordKey"]] = record["detail"]
    return make_feature_collection("adsbx", fetched_at_ms, features), detail_entries


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
    generation = FLIGHT_SNAPSHOT_CACHE.begin_request("adsbx")
    payload = http_get_json(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "self-hosted-maps/1.0",
            "api-auth": api_key,
        },
        timeout=15,
    )
    fetched_at_ms = current_time_ms()
    feature_collection, detail_entries = normalize_adsbx(payload, fetched_at_ms=fetched_at_ms)
    FLIGHT_SNAPSHOT_CACHE.commit("adsbx", generation, fetched_at_ms, detail_entries)
    return feature_collection


class FlightSnapshotCache:
    def __init__(self, ttl_ms=FLIGHT_SNAPSHOT_TTL_MS):
        self._ttl_ms = ttl_ms
        self._lock = threading.Lock()
        self._latest_generation = {"opensky": 0, "adsbx": 0}
        self._committed_generation = {"opensky": 0, "adsbx": 0}
        self._records = {"opensky": {}, "adsbx": {}}

    def clear(self):
        with self._lock:
            self._latest_generation = {"opensky": 0, "adsbx": 0}
            self._committed_generation = {"opensky": 0, "adsbx": 0}
            self._records = {"opensky": {}, "adsbx": {}}

    def begin_request(self, provider_key):
        with self._lock:
            self._latest_generation[provider_key] += 1
            return self._latest_generation[provider_key]

    def commit(self, provider_key, generation, fetched_at_ms, detail_entries):
        expires_at_ms = fetched_at_ms + self._ttl_ms
        with self._lock:
            self._prune_locked(fetched_at_ms)
            if generation < self._committed_generation[provider_key]:
                return False
            self._committed_generation[provider_key] = generation
            provider_records = self._records.setdefault(provider_key, {})
            for record_key, entry in detail_entries.items():
                provider_records[record_key] = {
                    "providerKey": provider_key,
                    "recordKey": record_key,
                    "entityKey": entry["entityKey"],
                    "fetchedAtMs": fetched_at_ms,
                    "expiresAtMs": expires_at_ms,
                    "summary": sanitize_json_value(entry["summary"]),
                    "raw": sanitize_json_value(entry["raw"]),
                    "provider": entry["provider"],
                }
            return True

    def get(self, provider_key, record_key, current_ms=None):
        now_ms = int(current_ms or current_time_ms())
        with self._lock:
            self._prune_locked(now_ms)
            entry = self._records.get(provider_key, {}).get(record_key)
            if not entry:
                return None
            if entry["expiresAtMs"] <= now_ms:
                self._records.get(provider_key, {}).pop(record_key, None)
                return None
            return json.loads(json.dumps(entry))

    def _prune_locked(self, now_ms):
        for provider_key, records in self._records.items():
            expired = [record_key for record_key, entry in records.items() if entry["expiresAtMs"] <= now_ms]
            for record_key in expired:
                records.pop(record_key, None)


FLIGHT_SNAPSHOT_CACHE = FlightSnapshotCache()


def build_flight_detail_response(provider_key, record_key):
    provider_key = require_flight_provider_key(provider_key)
    normalized_record_key = normalize_record_key(record_key)
    if not normalized_record_key:
        raise ValueError("recordKey is required.")
    entry = FLIGHT_SNAPSHOT_CACHE.get(provider_key, normalized_record_key)
    if not entry:
        return None
    return {
        "available": True,
        "provider": entry["provider"],
        "providerKey": provider_key,
        "providerLabel": PROVIDER_LABELS[provider_key],
        "recordKey": normalized_record_key,
        "entityKey": entry["entityKey"],
        "fetchedAtMs": entry["fetchedAtMs"],
        "summary": entry["summary"],
        "raw": entry["raw"],
    }


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
            elif path == "/api/flights/detail":
                provider_key = (query.get("providerKey") or [""])[0]
                record_key = (query.get("recordKey") or [""])[0]
                detail = build_flight_detail_response(provider_key, record_key)
                if not detail:
                    self._send_json(
                        404,
                        json_response(
                            False,
                            error={
                                "code": "flight_detail_not_found",
                                "message": "Flight detail is unavailable for the selected aircraft.",
                            },
                        ),
                    )
                    return
                self._send_json(200, json_response(True, detail))
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

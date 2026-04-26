#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import socket
import subprocess
import ssl
import struct
import sys
import threading
import time
import uuid
from collections import OrderedDict
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
AISSTREAM_DEFAULT_URL = "wss://stream.aisstream.io/v0/stream"
AISSTREAM_MAX_BBOX_AREA = 100
TOMTOM_DEFAULT_BASE_URL = "https://api.tomtom.com"
TOMTOM_TRAFFIC_MAX_ZOOM = 22
TOMTOM_TRAFFIC_MAX_TILE_BYTES = 1_500_000
IMAGERY_ROOT = Path(os.environ.get("SHM_IMAGERY_ROOT", str(DATA_ROOT / "imagery")))
IMAGERY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
IMAGERY_TILE_RE = re.compile(r"^/api/imagery/([^/]+)/([0-9]+)/([0-9]+)/([0-9]+)\.(png|jpg|webp)$")
IMAGERY_TILEJSON_RE = re.compile(r"^/api/imagery/([^/]+)\.json$")
IMAGERY_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class NotFoundError(Exception):
    pass


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


def default_imagery_state():
    return {
        "schema_version": 1,
        "installed": {},
        "order": [],
        "enabled": [],
    }


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
        "imagery": default_imagery_state(),
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
    merged.update({k: v for k, v in state.items() if k not in {"catalog", "current", "imagery"}})
    merged["catalog"].update(state.get("catalog") or {})
    merged["current"].update(state.get("current") or {})
    merged["imagery"].update(state.get("imagery") or {})
    if not isinstance(merged["imagery"].get("installed"), dict):
        merged["imagery"]["installed"] = {}
    if not isinstance(merged["imagery"].get("order"), list):
        merged["imagery"]["order"] = []
    if not isinstance(merged["imagery"].get("enabled"), list):
        merged["imagery"]["enabled"] = []
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


def validate_imagery_id(overlay_id: str) -> str:
    overlay_id = str(overlay_id or "").strip()
    if not IMAGERY_ID_RE.fullmatch(overlay_id):
        raise ValueError("Invalid imagery overlay id.")
    return overlay_id


def normalize_tile_format(value: str) -> str:
    tile_format = str(value or "").strip().lower()
    if tile_format == "jpeg":
        return "jpg"
    if tile_format not in {"png", "jpg", "webp"}:
        raise ValueError("Unsupported imagery tile format.")
    return tile_format


def content_type_for_tile_format(tile_format: str) -> str:
    return IMAGERY_CONTENT_TYPES[normalize_tile_format(tile_format)]


def imagery_root_resolved() -> Path:
    return IMAGERY_ROOT.resolve(strict=False)


def resolve_imagery_mbtiles_path(path_value: str) -> Path:
    if not path_value:
        raise ValueError("Imagery overlay path is missing.")
    path = Path(path_value).expanduser().resolve(strict=False)
    root = imagery_root_resolved()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Imagery overlay path is outside the managed imagery root.") from exc
    return path


def imagery_public_item(overlay_id: str, meta: dict, enabled_ids: set[str]):
    tile_format = normalize_tile_format(meta.get("tile_format") or meta.get("format") or "")
    content_type = meta.get("content_type") or content_type_for_tile_format(tile_format)
    if content_type != content_type_for_tile_format(tile_format):
        raise ValueError("Imagery content type does not match tile format.")
    return {
        "id": overlay_id,
        "name": meta.get("name") or overlay_id,
        "format": meta.get("format") or "mbtiles",
        "tileFormat": tile_format,
        "contentType": content_type,
        "tilejsonUrl": f"/api/imagery/{urlparse.quote(overlay_id, safe='')}.json",
        "bounds": meta.get("bounds") or [-180, -85.0511, 180, 85.0511],
        "minzoom": int(meta.get("minzoom") or 0),
        "maxzoom": int(meta.get("maxzoom") or 22),
        "tileSize": int(meta.get("tile_size") or meta.get("tileSize") or 256),
        "opacity": float(meta.get("opacity") if meta.get("opacity") is not None else 0.75),
        "attribution": meta.get("attribution") or "",
        "license": meta.get("license") or {},
        "usageNotes": meta.get("usage_notes") or meta.get("usageNotes") or "",
        "source": {
            "type": (meta.get("source") or {}).get("type") or "",
            "url": (meta.get("source") or {}).get("url") or "",
            "sha256": (meta.get("source") or {}).get("sha256") or "",
        },
        "enabled": overlay_id in enabled_ids,
        "available": bool(meta.get("available")),
        "bytes": int(meta.get("bytes") or 0),
        "sha256": meta.get("sha256") or "",
        "checkedAt": meta.get("checked_at") or "",
        "installedAt": meta.get("installed_at") or "",
        "updatedAt": meta.get("updated_at") or "",
    }


def ordered_imagery_items(imagery_state: dict):
    installed = imagery_state.get("installed") or {}
    order = [str(item) for item in (imagery_state.get("order") or [])]
    ids = [overlay_id for overlay_id in order if overlay_id in installed]
    ids.extend(sorted(overlay_id for overlay_id in installed if overlay_id not in ids))
    return ids, installed


def build_imagery_response():
    state, state_present = read_state()
    imagery_state = state.get("imagery") or default_imagery_state()
    enabled_ids = {str(overlay_id) for overlay_id in (imagery_state.get("enabled") or [])}
    ids, installed = ordered_imagery_items(imagery_state)
    items = []
    item_ids = []
    for overlay_id in ids:
        try:
            validate_imagery_id(overlay_id)
            meta = installed.get(overlay_id) or {}
            if meta.get("path"):
                resolve_imagery_mbtiles_path(meta.get("path"))
            items.append(imagery_public_item(overlay_id, meta, enabled_ids))
            item_ids.append(overlay_id)
        except (TypeError, ValueError):
            continue
    enabled = [overlay_id for overlay_id in item_ids if overlay_id in enabled_ids]
    return {
        "statePresent": state_present,
        "schemaVersion": int(imagery_state.get("schema_version") or 1),
        "items": items,
        "order": item_ids,
        "enabled": enabled,
    }


def get_imagery_overlay(overlay_id: str):
    overlay_id = validate_imagery_id(overlay_id)
    state, _ = read_state()
    imagery_state = state.get("imagery") or {}
    meta = (imagery_state.get("installed") or {}).get(overlay_id)
    if not isinstance(meta, dict):
        raise NotFoundError("Unknown imagery overlay.")
    path = resolve_imagery_mbtiles_path(meta.get("path") or "")
    tile_format = normalize_tile_format(meta.get("tile_format") or "")
    content_type = meta.get("content_type") or content_type_for_tile_format(tile_format)
    expected_content_type = content_type_for_tile_format(tile_format)
    if content_type != expected_content_type:
        raise ValueError("Imagery content type does not match tile format.")
    return overlay_id, meta, path, tile_format, content_type


def imagery_tilejson(overlay_id: str):
    overlay_id, meta, _path, tile_format, _content_type = get_imagery_overlay(overlay_id)
    return {
        "tilejson": "2.2.0",
        "version": "1.0.0",
        "name": meta.get("name") or overlay_id,
        "scheme": "xyz",
        "tiles": [f"/api/imagery/{urlparse.quote(overlay_id, safe='')}/{{z}}/{{x}}/{{y}}.{tile_format}"],
        "minzoom": int(meta.get("minzoom") or 0),
        "maxzoom": int(meta.get("maxzoom") or 22),
        "bounds": meta.get("bounds") or [-180, -85.0511, 180, 85.0511],
        "tileSize": int(meta.get("tile_size") or meta.get("tileSize") or 256),
        "attribution": meta.get("attribution") or "",
    }


def parse_imagery_tilejson_path(path: str):
    match = IMAGERY_TILEJSON_RE.fullmatch(path)
    if not match:
        return None
    return validate_imagery_id(match.group(1))


def parse_imagery_tile_path(path: str):
    match = IMAGERY_TILE_RE.fullmatch(path)
    if not match:
        return None
    overlay_id = validate_imagery_id(match.group(1))
    z = int(match.group(2))
    x = int(match.group(3))
    y = int(match.group(4))
    extension = match.group(5)
    return overlay_id, z, x, y, extension


def xyz_to_tms_row(z: int, y: int) -> int:
    return (1 << z) - 1 - y


def validate_xyz_coordinate(z: int, x: int, y: int, minzoom: int, maxzoom: int):
    if z < minzoom or z > maxzoom:
        raise ValueError("Imagery tile zoom is outside the overlay zoom range.")
    if z < 0 or z > 30:
        raise ValueError("Imagery tile zoom is invalid.")
    limit = 1 << z
    if x < 0 or y < 0 or x >= limit or y >= limit:
        raise ValueError("Imagery tile coordinates are invalid.")


def open_mbtiles_readonly(path: Path):
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def read_mbtiles_metadata(path: Path):
    conn = open_mbtiles_readonly(path)
    try:
        required_tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table' and name in ('metadata', 'tiles')"
            )
        }
        if required_tables != {"metadata", "tiles"}:
            raise ValueError("MBTiles file must contain metadata and tiles tables.")
        metadata = {str(name): str(value) for name, value in conn.execute("select name, value from metadata")}
        tile_rows = list(conn.execute("select min(zoom_level), max(zoom_level) from tiles"))[0]
    finally:
        conn.close()
    return metadata, tile_rows


def validate_tile_magic(body: bytes, tile_format: str) -> bool:
    tile_format = normalize_tile_format(tile_format)
    if tile_format == "png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    if tile_format == "jpg":
        return body.startswith(b"\xff\xd8\xff")
    if tile_format == "webp":
        return len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP"
    return False


def fetch_imagery_tile(overlay_id: str, z: int, x: int, y: int, extension: str):
    overlay_id, meta, path, tile_format, content_type = get_imagery_overlay(overlay_id)
    if extension != tile_format:
        raise ValueError("Imagery tile extension does not match the registered tile format.")
    validate_xyz_coordinate(z, x, y, int(meta.get("minzoom") or 0), int(meta.get("maxzoom") or 22))
    if not path.is_file():
        raise NotFoundError("Imagery MBTiles file is unavailable.")
    tile_row = xyz_to_tms_row(z, y)
    conn = open_mbtiles_readonly(path)
    try:
        row = conn.execute(
            """
            select tile_data
            from tiles
            where zoom_level = ? and tile_column = ? and tile_row = ?
            """,
            (z, x, tile_row),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise NotFoundError("Imagery tile not found.")
    body = row[0]
    if not validate_tile_magic(body, tile_format):
        raise ValueError("Imagery tile bytes do not match the registered tile format.")
    fingerprint = meta.get("sha256") or f"{path.stat().st_size:x}-{int(path.stat().st_mtime):x}"
    etag = f'"imagery-{overlay_id}-{fingerprint}-{z}-{x}-{y}"'
    return {
        "body": body,
        "contentType": content_type,
        "etag": etag,
        "cacheControl": "public, max-age=3600, immutable",
    }


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
    ais_key = os.environ.get("SHM_AISSTREAM_API_KEY", "").strip()
    tomtom_key = tomtom_api_key()
    tomtom_enabled = env_bool("SHM_TOMTOM_TRAFFIC_ENABLED", False) and bool(tomtom_key)
    return {
        "addressSearchEnabled": env_bool("SHM_ADDRESS_SEARCH_ENABLED", True),
        "openSkyEnabled": env_bool("SHM_OPENSKY_ENABLED", True),
        "adsbExchangeEnabled": env_bool("SHM_ADSBEXCHANGE_ENABLED", False) and bool(adsb_key),
        "adsbExchangeConfigured": bool(adsb_key),
        "aisStreamEnabled": env_bool("SHM_AISSTREAM_ENABLED", False) and bool(ais_key),
        "aisStreamConfigured": bool(ais_key),
        "tomTomTrafficEnabled": tomtom_enabled,
        "tomTomTrafficConfigured": bool(tomtom_key),
        "tomTomTrafficFlowEnabled": tomtom_enabled and env_bool("SHM_TOMTOM_TRAFFIC_FLOW_ENABLED", True),
        "tomTomTrafficIncidentsEnabled": tomtom_enabled and env_bool("SHM_TOMTOM_TRAFFIC_INCIDENTS_ENABLED", True),
        "adminTokenRequired": bool(os.environ.get("SHM_ADMIN_TOKEN", "").strip()),
    }


def http_get_json(url: str, headers=None, timeout: int = 15):
    request = urlrequest.Request(url, headers=headers or {})
    with urlrequest.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_get_bytes(url: str, headers=None, timeout: int = 15, max_bytes=None):
    request = urlrequest.Request(url, headers=headers or {})
    with urlrequest.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if max_bytes is None:
            body = response.read()
        else:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise RuntimeError("Upstream response exceeded the configured size limit.")
        return body, content_type


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


def tomtom_api_key():
    return (
        os.environ.get("SHM_TOMTOM_TRAFFIC_API_KEY", "").strip()
        or os.environ.get("SHM_TOMTOM_API_KEY", "").strip()
    )


def env_int(name, default, minimum=None, maximum=None):
    try:
        value = int(os.environ.get(name, str(default)).strip())
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def validate_tile_coord(z, x, y):
    try:
        z = int(z)
        x = int(x)
        y = int(y)
    except (TypeError, ValueError):
        raise ValueError("Traffic tile coordinates must be integers.")
    if z < 0 or z > TOMTOM_TRAFFIC_MAX_ZOOM:
        raise ValueError(f"Traffic tile zoom must be between 0 and {TOMTOM_TRAFFIC_MAX_ZOOM}.")
    tile_limit = 2**z
    if x < 0 or y < 0 or x >= tile_limit or y >= tile_limit:
        raise ValueError("Traffic tile coordinates are outside the zoom grid.")
    return z, x, y


def parse_tomtom_tile_path(path):
    parts = path.strip("/").split("/")
    if len(parts) != 7 or parts[:3] != ["api", "traffic", "tomtom"]:
        return None
    kind = parts[3]
    if kind not in {"flow", "incidents"}:
        raise ValueError("Traffic tile kind must be flow or incidents.")
    y_part = parts[6]
    if not y_part.endswith(".png"):
        raise ValueError("Traffic tile requests must end in .png.")
    z, x, y = validate_tile_coord(parts[4], parts[5], y_part[:-4])
    return kind, z, x, y


def tomtom_traffic_style(kind):
    if kind == "flow":
        value = os.environ.get("SHM_TOMTOM_TRAFFIC_FLOW_STYLE", "relative0").strip() or "relative0"
        allowed = {"absolute", "relative", "relative0", "relative0-dark"}
    else:
        value = os.environ.get("SHM_TOMTOM_TRAFFIC_INCIDENT_STYLE", "s3").strip() or "s3"
        allowed = {"s0", "s0-dark", "s1", "s2", "s3"}
    if value not in allowed:
        raise ValueError(f"Unsupported TomTom traffic {kind} style.")
    return value


def build_tomtom_traffic_tile_url(kind, z, x, y):
    api_key = tomtom_api_key()
    if not env_bool("SHM_TOMTOM_TRAFFIC_ENABLED", False):
        raise RuntimeError("TomTom traffic is disabled.")
    if not api_key:
        raise RuntimeError("TomTom traffic API key is not configured.")
    if kind == "flow" and not env_bool("SHM_TOMTOM_TRAFFIC_FLOW_ENABLED", True):
        raise RuntimeError("TomTom traffic flow is disabled.")
    if kind == "incidents" and not env_bool("SHM_TOMTOM_TRAFFIC_INCIDENTS_ENABLED", True):
        raise RuntimeError("TomTom traffic incidents are disabled.")
    style = tomtom_traffic_style(kind)
    base_url = (
        os.environ.get("SHM_TOMTOM_TRAFFIC_API_BASE_URL", "").strip()
        or os.environ.get("SHM_TOMTOM_API_BASE_URL", TOMTOM_DEFAULT_BASE_URL).strip()
        or TOMTOM_DEFAULT_BASE_URL
    ).rstrip("/")
    path_kind = "flow" if kind == "flow" else "incidents"
    query = urlparse.urlencode({"key": api_key, "tileSize": "256"})
    return f"{base_url}/traffic/map/4/tile/{path_kind}/{style}/{z}/{x}/{y}.png?{query}"


class TrafficTileCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries = OrderedDict()

    def clear(self):
        with self._lock:
            self._entries.clear()

    def get(self, key, now=None):
        now = float(time.time() if now is None else now)
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            if entry["expires_at"] <= now:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return entry["body"], entry["content_type"]

    def put(self, key, body, content_type, now=None):
        if not body or len(body) > TOMTOM_TRAFFIC_MAX_TILE_BYTES:
            raise RuntimeError("Traffic tile response is too large.")
        now = float(time.time() if now is None else now)
        ttl = env_int("SHM_TOMTOM_TRAFFIC_TILE_TTL_SECONDS", 30, minimum=1, maximum=600)
        max_entries = env_int("SHM_TOMTOM_TRAFFIC_CACHE_MAX_ENTRIES", 512, minimum=16, maximum=4096)
        with self._lock:
            self._entries[key] = {
                "body": body,
                "content_type": content_type,
                "expires_at": now + ttl,
            }
            self._entries.move_to_end(key)
            while len(self._entries) > max_entries:
                self._entries.popitem(last=False)


TOMTOM_TRAFFIC_TILE_CACHE = TrafficTileCache()


def fetch_tomtom_traffic_tile(kind, z, x, y):
    z, x, y = validate_tile_coord(z, x, y)
    style = tomtom_traffic_style(kind)
    url = build_tomtom_traffic_tile_url(kind, z, x, y)
    cache_key = (kind, style, z, x, y)
    cached = TOMTOM_TRAFFIC_TILE_CACHE.get(cache_key)
    if cached:
        body, content_type = cached
        return {"body": body, "contentType": content_type, "cache": "hit"}

    body, content_type = http_get_bytes(
        url,
        headers={"User-Agent": "self-hosted-maps/1.0", "Accept": "image/png"},
        timeout=15,
        max_bytes=TOMTOM_TRAFFIC_MAX_TILE_BYTES,
    )
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type != "image/png":
        raise RuntimeError("TomTom traffic tile response was not a PNG image.")
    TOMTOM_TRAFFIC_TILE_CACHE.put(cache_key, body, "image/png")
    return {"body": body, "contentType": "image/png", "cache": "miss"}


def require_aisstream_enabled():
    if not env_bool("SHM_AISSTREAM_ENABLED", False):
        raise RuntimeError("AISStream is disabled.")
    api_key = os.environ.get("SHM_AISSTREAM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AISStream API key is not configured.")
    return api_key


def validate_ais_bbox(query):
    try:
        south = float(query.get("lamin", [""])[0])
        west = float(query.get("lomin", [""])[0])
        north = float(query.get("lamax", [""])[0])
        east = float(query.get("lomax", [""])[0])
    except (TypeError, ValueError):
        raise ValueError("lamin, lomin, lamax, and lomax are required.")
    if not (-90 <= south <= 90 and -90 <= north <= 90 and -180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError("AIS bounding box coordinates are outside valid latitude/longitude ranges.")
    if south >= north or west >= east:
        raise ValueError("AIS bounding boxes must not cross the antimeridian and must have positive area.")
    area = abs((north - south) * (east - west))
    if area > AISSTREAM_MAX_BBOX_AREA:
        raise ValueError("Requested AIS area is too large. Zoom in and try again.")
    return {"south": south, "west": west, "north": north, "east": east}


def ais_subscription_key(bounds):
    quantum = 0.01
    south = max(-90, math.floor(bounds["south"] / quantum) * quantum)
    west = max(-180, math.floor(bounds["west"] / quantum) * quantum)
    north = min(90, math.ceil(bounds["north"] / quantum) * quantum)
    east = min(180, math.ceil(bounds["east"] / quantum) * quantum)
    if south >= north:
        south = max(-90, bounds["south"] - quantum)
        north = min(90, bounds["north"] + quantum)
    if west >= east:
        west = max(-180, bounds["west"] - quantum)
        east = min(180, bounds["east"] + quantum)
    return tuple(round(value, 2) for value in (south, west, north, east))


def build_aisstream_subscription(api_key, bounds):
    return {
        "APIKey": api_key,
        "BoundingBoxes": [[[bounds["south"], bounds["west"]], [bounds["north"], bounds["east"]]]],
        "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"],
    }


def parse_wss_url(url):
    parsed = urlparse.urlparse(url)
    if parsed.scheme != "wss" or not parsed.hostname:
        raise ValueError("AISStream URL must be a wss:// URL.")
    return parsed.hostname, parsed.port or 443, parsed.path or "/", parsed.query


def websocket_accept_key(client_key):
    digest = hashlib.sha1((client_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def websocket_encode_frame(payload, opcode=1):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length <= 0xFFFF:
        header.extend([0x80 | 126])
        header.extend(struct.pack("!H", length))
    else:
        header.extend([0x80 | 127])
        header.extend(struct.pack("!Q", length))
    mask = secrets.token_bytes(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + mask + masked


def _recv_exact(sock, length):
    chunks = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("WebSocket connection closed unexpectedly.")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def websocket_read_frame(sock):
    header = _recv_exact(sock, 2)
    fin = bool(header[0] & 0x80)
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    mask = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length) if length else b""
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return {"fin": fin, "opcode": opcode, "payload": payload}


def websocket_connect(url, timeout=20):
    host, port, path, query = parse_wss_url(url)
    request_path = path + (f"?{query}" if query else "")
    raw = socket.create_connection((host, port), timeout=timeout)
    context = ssl.create_default_context()
    tls_sock = context.wrap_socket(raw, server_hostname=host)
    tls_sock.settimeout(timeout)
    client_key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    request = (
        f"GET {request_path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {client_key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "User-Agent: self-hosted-maps/1.0\r\n"
        "\r\n"
    )
    tls_sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = tls_sock.recv(4096)
        if not chunk:
            tls_sock.close()
            raise RuntimeError("AISStream WebSocket handshake closed before headers were received.")
        response += chunk
        if len(response) > 32768:
            tls_sock.close()
            raise RuntimeError("AISStream WebSocket handshake response was too large.")
    header_text = response.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
    lines = header_text.split("\r\n")
    if not lines or " 101 " not in lines[0]:
        tls_sock.close()
        raise RuntimeError("AISStream WebSocket handshake was rejected.")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    if headers.get("sec-websocket-accept") != websocket_accept_key(client_key):
        tls_sock.close()
        raise RuntimeError("AISStream WebSocket handshake accept key was invalid.")
    return tls_sock


def _pick_nested(mapping, *paths):
    for path in paths:
        cursor = mapping
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor[key]
        if cursor not in (None, ""):
            return cursor
    return None


def normalize_ais_nav_status(value):
    status_map = {
        0: "Under way using engine",
        1: "At anchor",
        2: "Not under command",
        3: "Restricted manoeuverability",
        4: "Constrained by draft",
        5: "Moored",
        6: "Aground",
        7: "Fishing",
        8: "Sailing",
        15: "Undefined",
    }
    number = maybe_float(value)
    if number is None:
        return clean_text(value)
    return status_map.get(int(number), str(int(number)))


def normalize_aisstream_message(payload, fetched_at_ms=None):
    if not isinstance(payload, dict):
        return None
    fetched_at_ms = int(fetched_at_ms or current_time_ms())
    message = payload.get("Message") or {}
    position = (
        message.get("PositionReport")
        or message.get("StandardClassBPositionReport")
        or message.get("ExtendedClassBPositionReport")
        or {}
    )
    metadata = payload.get("MetaData") or {}
    mmsi = clean_text(
        _pick_nested(payload, ("MMSI",), ("mmsi",))
        or _pick_nested(metadata, ("MMSI",), ("Mmsi",), ("mmsi",))
        or _pick_nested(position, ("UserID",), ("UserId",), ("MMSI",), ("Mmsi",))
    )
    if not mmsi:
        return None
    latitude = maybe_float(
        _pick_nested(position, ("Latitude",), ("latitude",)) or _pick_nested(metadata, ("latitude",), ("Latitude",))
    )
    longitude = maybe_float(
        _pick_nested(position, ("Longitude",), ("longitude",)) or _pick_nested(metadata, ("longitude",), ("Longitude",))
    )
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    record_key = normalize_record_key(mmsi)
    entity_key = f"aisstream:{record_key}"
    vessel_name = clean_text(_pick_nested(metadata, ("ShipName",), ("shipName",)) or _pick_nested(position, ("ShipName",)))
    callsign = clean_text(_pick_nested(metadata, ("CallSign",), ("callsign",)) or _pick_nested(position, ("CallSign",)))
    imo = clean_text(_pick_nested(metadata, ("IMO",), ("imo",)) or _pick_nested(position, ("IMO",)))
    ship_type = clean_text(_pick_nested(metadata, ("ShipType",), ("shipType",)) or _pick_nested(position, ("ShipType",)))
    sog_kts = maybe_float(_pick_nested(position, ("Sog",), ("SOG",), ("SpeedOverGround",)))
    cog_deg = maybe_float(_pick_nested(position, ("Cog",), ("COG",), ("CourseOverGround",)))
    heading_deg = maybe_float(_pick_nested(position, ("TrueHeading",), ("Heading",)))
    if heading_deg == 511:
        heading_deg = None
    nav_status = normalize_ais_nav_status(_pick_nested(position, ("NavigationalStatus",), ("NavStatus",)))
    label_primary = vessel_name or callsign or mmsi
    label_full = f"{label_primary} • {mmsi}" if label_primary != mmsi else mmsi
    properties = {
        "provider": "aisstream",
        "providerKey": "aisstream",
        "providerLabel": "AISStream",
        "id": mmsi,
        "recordKey": record_key,
        "entityKey": entity_key,
        "displayId": mmsi,
        "mmsi": mmsi,
        "imo": imo,
        "callsign": callsign,
        "vesselName": vessel_name,
        "shipType": ship_type,
        "navStatus": nav_status,
        "sogKts": sog_kts,
        "groundSpeedKts": sog_kts,
        "cogDeg": cog_deg,
        "headingDeg": heading_deg if heading_deg is not None else cog_deg,
        "positionTimestampMs": fetched_at_ms,
        "lastSeenTimestampMs": fetched_at_ms,
        "positionAgeMsAtFetch": 0,
        "contactAgeMsAtFetch": 0,
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
    detail = {
        "provider": "aisstream",
        "providerKey": "aisstream",
        "recordKey": record_key,
        "entityKey": entity_key,
        "fetchedAtMs": fetched_at_ms,
        "summary": {
            "providerLabel": "AISStream",
            "labelPrimary": label_primary,
            "labelFull": label_full,
            "displayId": mmsi,
            "mmsi": mmsi,
            "imo": imo,
            "callsign": callsign,
            "vesselName": vessel_name,
            "shipType": ship_type,
            "navStatus": nav_status,
            "latitude": latitude,
            "longitude": longitude,
            "sogKts": sog_kts,
            "cogDeg": cog_deg,
            "headingDeg": heading_deg,
            "positionTimestampMs": fetched_at_ms,
            "lastSeenTimestampMs": fetched_at_ms,
            "positionAgeMsAtFetch": 0,
            "contactAgeMsAtFetch": 0,
        },
        "raw": {"schema": "aisstream.message.v1", "data": sanitize_json_value(payload)},
    }
    return {"feature": feature, "detail": detail, "recordKey": record_key}


class AisSnapshotCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._records = {}

    def clear(self):
        with self._lock:
            self._records.clear()

    def update(self, payload, fetched_at_ms=None):
        fetched_at_ms = int(fetched_at_ms or current_time_ms())
        record = normalize_aisstream_message(payload, fetched_at_ms=fetched_at_ms)
        if not record:
            return False
        ttl_ms = env_int("SHM_AISSTREAM_CACHE_TTL_SECONDS", 120, minimum=10, maximum=1800) * 1000
        with self._lock:
            self._records[record["recordKey"]] = {
                "feature": record["feature"],
                "detail": record["detail"],
                "expiresAtMs": fetched_at_ms + ttl_ms,
            }
            self._prune_locked(fetched_at_ms)
        return True

    def snapshot(self, bounds=None, now_ms=None):
        now_ms = int(now_ms or current_time_ms())
        with self._lock:
            self._prune_locked(now_ms)
            features = []
            for entry in self._records.values():
                feature = json.loads(json.dumps(entry["feature"]))
                coords = feature.get("geometry", {}).get("coordinates") or []
                if bounds and len(coords) >= 2:
                    lng, lat = coords[0], coords[1]
                    if not (bounds["west"] <= lng <= bounds["east"] and bounds["south"] <= lat <= bounds["north"]):
                        continue
                props = feature.setdefault("properties", {})
                last_seen = maybe_float(props.get("lastSeenTimestampMs"))
                age = max(0, now_ms - int(last_seen)) if last_seen is not None else None
                props["positionAgeMsAtFetch"] = age
                props["contactAgeMsAtFetch"] = age
                features.append(feature)
            return features

    def get(self, record_key, now_ms=None):
        now_ms = int(now_ms or current_time_ms())
        normalized = normalize_record_key(record_key)
        with self._lock:
            self._prune_locked(now_ms)
            entry = self._records.get(normalized)
            if not entry:
                return None
            return json.loads(json.dumps(entry["detail"]))

    def _prune_locked(self, now_ms):
        expired = [record_key for record_key, entry in self._records.items() if entry["expiresAtMs"] <= now_ms]
        for record_key in expired:
            self._records.pop(record_key, None)


AIS_SNAPSHOT_CACHE = AisSnapshotCache()


class AisStreamService:
    def __init__(self, cache):
        self._cache = cache
        self._lock = threading.Lock()
        self._thread = None
        self._stop_event = None
        self._subscription_key = None
        self._status = "idle"
        self._last_error = None
        self._started_at_ms = None

    def ensure_subscription(self, bounds):
        api_key = require_aisstream_enabled()
        key = ais_subscription_key(bounds)
        with self._lock:
            if self._thread and self._thread.is_alive() and self._subscription_key == key:
                return
            if self._stop_event:
                self._stop_event.set()
            stop_event = threading.Event()
            self._stop_event = stop_event
            self._subscription_key = key
            self._status = "connecting"
            self._last_error = None
            self._started_at_ms = current_time_ms()
            subscription_bounds = {
                "south": key[0],
                "west": key[1],
                "north": key[2],
                "east": key[3],
            }
            self._thread = threading.Thread(
                target=self._run,
                args=(api_key, subscription_bounds, stop_event),
                daemon=True,
            )
            self._thread.start()

    def meta(self):
        with self._lock:
            return {
                "status": self._status,
                "lastError": self._last_error,
                "subscriptionKey": list(self._subscription_key) if self._subscription_key else None,
                "startedAtMs": self._started_at_ms,
            }

    def _set_status(self, status, error=None):
        with self._lock:
            self._status = status
            self._last_error = str(error) if error else None

    def _run(self, api_key, bounds, stop_event):
        url = os.environ.get("SHM_AISSTREAM_URL", AISSTREAM_DEFAULT_URL).strip() or AISSTREAM_DEFAULT_URL
        subscription = build_aisstream_subscription(api_key, bounds)
        backoff_seconds = 2
        while not stop_event.is_set():
            sock = None
            try:
                sock = websocket_connect(url, timeout=20)
                sock.sendall(websocket_encode_frame(json.dumps(subscription), opcode=1))
                self._set_status("streaming")
                backoff_seconds = 2
                while not stop_event.is_set():
                    frame = websocket_read_frame(sock)
                    opcode = frame["opcode"]
                    if opcode == 1:
                        payload = json.loads(frame["payload"].decode("utf-8"))
                        self._cache.update(payload)
                    elif opcode == 8:
                        break
                    elif opcode == 9:
                        sock.sendall(websocket_encode_frame(frame["payload"], opcode=10))
            except Exception as exc:
                if not stop_event.is_set():
                    self._set_status("error", exc)
                    stop_event.wait(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 60)
            finally:
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
        self._set_status("stopped")


AIS_STREAM_SERVICE = AisStreamService(AIS_SNAPSHOT_CACHE)


def fetch_aisstream_vessels(query):
    bounds = validate_ais_bbox(query)
    AIS_STREAM_SERVICE.ensure_subscription(bounds)
    now_ms = current_time_ms()
    return {
        "type": "FeatureCollection",
        "features": AIS_SNAPSHOT_CACHE.snapshot(bounds=bounds, now_ms=now_ms),
        "meta": {
            "providerKey": "aisstream",
            "providerLabel": "AISStream",
            "fetchedAtMs": now_ms,
            "bounds": bounds,
            **AIS_STREAM_SERVICE.meta(),
        },
    }


def build_vessel_detail_response(provider_key, record_key):
    provider_key = str(provider_key or "").strip().lower()
    if provider_key != "aisstream":
        raise ValueError("providerKey must be aisstream.")
    normalized_record_key = normalize_record_key(record_key)
    if not normalized_record_key:
        raise ValueError("recordKey is required.")
    detail = AIS_SNAPSHOT_CACHE.get(normalized_record_key)
    if not detail:
        return None
    return {
        "available": True,
        "provider": "aisstream",
        "providerKey": "aisstream",
        "providerLabel": "AISStream",
        "recordKey": normalized_record_key,
        "entityKey": detail["entityKey"],
        "fetchedAtMs": detail["fetchedAtMs"],
        "summary": detail["summary"],
        "raw": detail["raw"],
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

    def _send_bytes(self, status_code, body, content_type, headers=None):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_not_modified(self, headers=None):
        self.send_response(304)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

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
            elif path == "/api/imagery":
                self._send_json(200, json_response(True, build_imagery_response()))
            elif path.startswith("/api/imagery/"):
                tilejson_id = parse_imagery_tilejson_path(path)
                parsed_tile = None if tilejson_id else parse_imagery_tile_path(path)
                if tilejson_id:
                    self._send_json(200, imagery_tilejson(tilejson_id))
                elif parsed_tile:
                    overlay_id, z, x, y, extension = parsed_tile
                    tile = fetch_imagery_tile(overlay_id, z, x, y, extension)
                    headers = {
                        "Cache-Control": tile["cacheControl"],
                        "ETag": tile["etag"],
                    }
                    if self.headers.get("If-None-Match") == tile["etag"]:
                        self._send_not_modified(headers)
                        return
                    self._send_bytes(200, tile["body"], tile["contentType"], headers)
                else:
                    self._send_json(404, json_response(False, error={"code": "not_found", "message": "Not found."}))
            elif path == "/api/vessels/aisstream" or path == "/api/ais":
                self._send_json(200, json_response(True, fetch_aisstream_vessels(query)))
            elif path == "/api/vessels/detail":
                provider_key = (query.get("providerKey") or [""])[0]
                record_key = (query.get("recordKey") or [""])[0]
                detail = build_vessel_detail_response(provider_key, record_key)
                if not detail:
                    self._send_json(
                        404,
                        json_response(
                            False,
                            error={
                                "code": "vessel_detail_not_found",
                                "message": "Vessel detail is unavailable for the selected vessel.",
                            },
                        ),
                    )
                    return
                self._send_json(200, json_response(True, detail))
            elif path.startswith("/api/traffic/tomtom/"):
                parsed_tile = parse_tomtom_tile_path(path)
                if not parsed_tile:
                    self._send_json(404, json_response(False, error={"code": "not_found", "message": "Not found."}))
                    return
                kind, z, x, y = parsed_tile
                tile = fetch_tomtom_traffic_tile(kind, z, x, y)
                self._send_bytes(
                    200,
                    tile["body"],
                    tile["contentType"],
                    {
                        "Cache-Control": "private, max-age=30",
                        "X-SHM-Cache": tile["cache"],
                    },
                )
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
        except NotFoundError as exc:
            self._send_json(404, json_response(False, error={"code": "not_found", "message": str(exc)}))
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

#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import parse as urlparse
from urllib import request as urlrequest


SCHEMA_VERSION = 1
PROVIDER_KEY = "celestrak-gp"
PROVIDER_LABEL = "CelesTrak GP"
SOURCE_FORMAT = "omm-json"
ACTIVE_CACHE_NAME = "celestrak-gp.json"
PREVIOUS_CACHE_NAME = "previous-celestrak-gp.json"
MANIFEST_NAME = "manifest.json"
DEFAULT_GROUP = "active"
DEFAULT_STALE_HOURS = 48
DEFAULT_EXPIRED_HOURS = 168
DEFAULT_MAX_SOURCE_BYTES = 25_000_000
DEFAULT_REFRESH_TIMEOUT_SECONDS = 30
GROUP_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SatelliteCacheError(RuntimeError):
    pass


def iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def current_time_ms():
    return int(time.time() * 1000)


def env_int(name, default):
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def cache_root(data_root=None):
    override = os.environ.get("SHM_SATELLITES_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    root = Path(data_root or os.environ.get("SHM_DATA_ROOT", "/var/lib/self-hosted-maps"))
    return root / "cache" / "satellites"


def cache_paths(data_root=None):
    root = cache_root(data_root)
    return {
        "root": root,
        "manifest": root / MANIFEST_NAME,
        "active": root / ACTIVE_CACHE_NAME,
        "previous": root / PREVIOUS_CACHE_NAME,
    }


def validate_group(group):
    normalized = (group or DEFAULT_GROUP).strip()
    if not GROUP_RE.match(normalized):
        raise SatelliteCacheError("Satellite group must contain only letters, numbers, underscores, or hyphens.")
    return normalized


def celestrak_group_url(group):
    query = urlparse.urlencode({"GROUP": validate_group(group), "FORMAT": "json"})
    return f"https://celestrak.org/NORAD/elements/gp.php?{query}"


def parse_utc_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{text}+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_from_datetime(value):
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def epoch_ms(value):
    parsed = parse_utc_datetime(value)
    if parsed is None:
        return None, None
    return iso_from_datetime(parsed), int(parsed.timestamp() * 1000)


def maybe_float(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def maybe_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not number.is_integer():
            return None
        return int(number)


def first_value(record, *keys):
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def staleness_for_epoch(epoch_ms_value, now_ms=None, stale_hours=None, expired_hours=None):
    if epoch_ms_value is None:
        return {"state": "unknown", "stale": True, "expired": False, "ageHours": None}
    now = current_time_ms() if now_ms is None else int(now_ms)
    stale_threshold = env_int("SHM_SATELLITES_STALE_AFTER_HOURS", DEFAULT_STALE_HOURS) if stale_hours is None else stale_hours
    expired_threshold = (
        env_int("SHM_SATELLITES_EXPIRED_AFTER_HOURS", DEFAULT_EXPIRED_HOURS) if expired_hours is None else expired_hours
    )
    age_hours = max(0, (now - int(epoch_ms_value)) / 3_600_000)
    if age_hours >= expired_threshold:
        state = "expired"
    elif age_hours >= stale_threshold:
        state = "stale"
    else:
        state = "fresh"
    return {
        "state": state,
        "stale": state in {"stale", "expired"},
        "expired": state == "expired",
        "ageHours": round(age_hours, 3),
    }


def normalize_omm_record(record, provenance, now_ms=None, stale_hours=None, expired_hours=None):
    if not isinstance(record, dict):
        raise ValueError("Record is not an object.")

    norad = maybe_int(first_value(record, "NORAD_CAT_ID", "noradCatalogNumber", "norad_cat_id", "NORADCatalogNumber"))
    epoch_iso, epoch_ms_value = epoch_ms(first_value(record, "EPOCH", "epoch", "epochIso"))
    mean_motion = maybe_float(first_value(record, "MEAN_MOTION", "meanMotion"))
    eccentricity = maybe_float(first_value(record, "ECCENTRICITY", "eccentricity"))
    inclination = maybe_float(first_value(record, "INCLINATION", "inclination"))
    raan = maybe_float(first_value(record, "RA_OF_ASC_NODE", "raan", "rightAscensionOfAscendingNode"))
    arg_pericenter = maybe_float(first_value(record, "ARG_OF_PERICENTER", "argumentOfPericenter", "argPericenter"))
    mean_anomaly = maybe_float(first_value(record, "MEAN_ANOMALY", "meanAnomaly"))

    required = [norad, epoch_ms_value, mean_motion, eccentricity, inclination, raan, arg_pericenter, mean_anomaly]
    if any(value is None for value in required):
        raise ValueError("Record is missing required OMM orbital fields.")

    object_name = str(first_value(record, "OBJECT_NAME", "objectName") or f"NORAD {norad}").strip()
    object_id = first_value(record, "OBJECT_ID", "objectId")
    normalized = {
        "recordKey": f"norad:{norad}",
        "noradCatalogNumber": norad,
        "objectName": object_name,
        "objectId": str(object_id).strip() if object_id is not None else None,
        "epochIso": epoch_iso,
        "epochMs": epoch_ms_value,
        "meanMotion": mean_motion,
        "eccentricity": eccentricity,
        "inclination": inclination,
        "raan": raan,
        "argumentOfPericenter": arg_pericenter,
        "meanAnomaly": mean_anomaly,
        "bstar": maybe_float(first_value(record, "BSTAR", "bstar")),
        "meanMotionDot": maybe_float(first_value(record, "MEAN_MOTION_DOT", "meanMotionDot")),
        "meanMotionDdot": maybe_float(first_value(record, "MEAN_MOTION_DDOT", "meanMotionDdot")),
        "ephemerisType": first_value(record, "EPHEMERIS_TYPE", "ephemerisType"),
        "classificationType": first_value(record, "CLASSIFICATION_TYPE", "classificationType"),
        "revAtEpoch": maybe_int(first_value(record, "REV_AT_EPOCH", "revAtEpoch")),
        "raw": record,
        "provenance": dict(provenance),
        "staleness": staleness_for_epoch(epoch_ms_value, now_ms, stale_hours, expired_hours),
    }
    return normalized


def extract_records(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("records", "elements", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise SatelliteCacheError("OMM JSON must be a list or contain a records/elements/items array.")


def normalize_omm_payload(payload, provenance, now_ms=None, stale_hours=None, expired_hours=None):
    records = extract_records(payload)
    normalized = []
    invalid_count = 0
    for record in records:
        try:
            normalized.append(normalize_omm_record(record, provenance, now_ms, stale_hours, expired_hours))
        except ValueError:
            invalid_count += 1
    if not normalized:
        raise SatelliteCacheError("OMM JSON did not contain any valid orbital element records.")
    normalized.sort(key=lambda item: (str(item.get("objectName") or "").lower(), item.get("noradCatalogNumber") or 0))
    return normalized, invalid_count


def read_source_json(path):
    source_path = Path(path)
    with source_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def source_sha256(path):
    import hashlib

    digest = hashlib.sha256()
    source_path = Path(path)
    with source_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_omm_json(url, timeout=None, max_bytes=None):
    timeout_seconds = timeout if timeout is not None else env_int("SHM_SATELLITES_REFRESH_TIMEOUT_SECONDS", DEFAULT_REFRESH_TIMEOUT_SECONDS)
    byte_limit = max_bytes if max_bytes is not None else env_int("SHM_SATELLITES_MAX_SOURCE_BYTES", DEFAULT_MAX_SOURCE_BYTES)
    request = urlrequest.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "self-hosted-maps/1.0 satellite-cache"},
    )
    with urlrequest.urlopen(request, timeout=timeout_seconds) as response:
        body = response.read(byte_limit + 1)
        if len(body) > byte_limit:
            raise SatelliteCacheError("CelesTrak response exceeded the configured size limit.")
        payload = json.loads(body.decode("utf-8"))
        return payload, {
            "url": url,
            "etag": response.headers.get("ETag"),
            "lastModified": response.headers.get("Last-Modified"),
        }


def write_json_atomic(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(target.parent), delete=False) as handle:
            tmp_name = handle.name
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, target)
    finally:
        if tmp_name and Path(tmp_name).exists():
            try:
                Path(tmp_name).unlink()
            except OSError:
                pass


def preserve_previous(active_path, previous_path):
    if not active_path.exists():
        return False
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=str(previous_path.parent), delete=False) as handle:
        tmp_name = handle.name
    try:
        shutil.copy2(active_path, tmp_name)
        os.replace(tmp_name, previous_path)
        return True
    finally:
        if Path(tmp_name).exists():
            try:
                Path(tmp_name).unlink()
            except OSError:
                pass


def cache_staleness(last_success_at, now_ms=None, stale_hours=None, expired_hours=None):
    parsed = parse_utc_datetime(last_success_at)
    if parsed is None:
        return {"state": "missing", "stale": True, "expired": False, "ageHours": None}
    return staleness_for_epoch(int(parsed.timestamp() * 1000), now_ms, stale_hours, expired_hours)


def build_manifest(source, group, records, invalid_count, fetched_at=None, imported_at=None, now_ms=None):
    stale_hours = env_int("SHM_SATELLITES_STALE_AFTER_HOURS", DEFAULT_STALE_HOURS)
    expired_hours = env_int("SHM_SATELLITES_EXPIRED_AFTER_HOURS", DEFAULT_EXPIRED_HOURS)
    success_at = fetched_at or imported_at or iso_now()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provider": {"key": PROVIDER_KEY, "label": PROVIDER_LABEL},
        "source": {"format": SOURCE_FORMAT, **source},
        "groups": [group],
        "fetchedAt": fetched_at,
        "importedAt": imported_at,
        "lastSuccessAt": success_at,
        "recordCount": len(records),
        "invalidRecordCount": invalid_count,
        "staleAfterHours": stale_hours,
        "expiredAfterHours": expired_hours,
        "staleness": cache_staleness(success_at, now_ms, stale_hours, expired_hours),
        "refresh": {"status": "success", "error": None},
        "propagation": {
            "available": False,
            "provider": None,
            "reason": "not_implemented_v1_cache_catalog_only",
        },
        "cacheCatalogOnly": True,
    }


def promote_cache(records, manifest, data_root=None):
    paths = cache_paths(data_root)
    paths["root"].mkdir(parents=True, exist_ok=True)
    previous_preserved = preserve_previous(paths["active"], paths["previous"])
    write_json_atomic(paths["active"], {"schemaVersion": SCHEMA_VERSION, "records": records})
    manifest = dict(manifest)
    manifest["cache"] = {
        "activeFile": ACTIVE_CACHE_NAME,
        "previousFile": PREVIOUS_CACHE_NAME if previous_preserved else None,
    }
    write_json_atomic(paths["manifest"], manifest)
    return manifest


def refresh_from_celestrak(group=None, data_root=None, now_ms=None):
    normalized_group = validate_group(group or os.environ.get("SHM_SATELLITES_CELESTRAK_GROUP", DEFAULT_GROUP))
    url = celestrak_group_url(normalized_group)
    fetched_at = iso_now()
    payload, source_metadata = fetch_omm_json(url)
    provenance = {
        "providerKey": PROVIDER_KEY,
        "providerLabel": PROVIDER_LABEL,
        "sourceFormat": SOURCE_FORMAT,
        "sourceType": "celestrak",
        "sourceUrl": url,
        "group": normalized_group,
        "fetchedAt": fetched_at,
    }
    records, invalid_count = normalize_omm_payload(payload, provenance, now_ms=now_ms)
    manifest = build_manifest(
        {
            "type": "celestrak",
            "url": url,
            "group": normalized_group,
            "etag": source_metadata.get("etag"),
            "lastModified": source_metadata.get("lastModified"),
        },
        normalized_group,
        records,
        invalid_count,
        fetched_at=fetched_at,
        now_ms=now_ms,
    )
    return promote_cache(records, manifest, data_root)


def import_omm_file(source_file, group=None, source_label=None, data_root=None, now_ms=None):
    source_path = Path(source_file)
    if not source_path.exists() or not source_path.is_file():
        raise SatelliteCacheError("Local OMM import file does not exist.")
    normalized_group = validate_group(group or "local")
    imported_at = iso_now()
    payload = read_source_json(source_path)
    provenance = {
        "providerKey": PROVIDER_KEY,
        "providerLabel": PROVIDER_LABEL,
        "sourceFormat": SOURCE_FORMAT,
        "sourceType": "local-import",
        "sourceFileName": source_path.name,
        "sourceLabel": source_label or source_path.name,
        "group": normalized_group,
        "importedAt": imported_at,
    }
    records, invalid_count = normalize_omm_payload(payload, provenance, now_ms=now_ms)
    manifest = build_manifest(
        {
            "type": "local-import",
            "fileName": source_path.name,
            "label": source_label or source_path.name,
            "sha256": source_sha256(source_path),
            "group": normalized_group,
        },
        normalized_group,
        records,
        invalid_count,
        imported_at=imported_at,
        now_ms=now_ms,
    )
    return promote_cache(records, manifest, data_root)


def read_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle), True
    except (OSError, json.JSONDecodeError):
        return None, False


def load_manifest(data_root=None):
    payload, present = read_json(cache_paths(data_root)["manifest"])
    if not present or not isinstance(payload, dict):
        return {}, False
    return payload, True


def load_records(data_root=None):
    payload, present = read_json(cache_paths(data_root)["active"])
    if not present:
        return [], False
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return payload["records"], True
    if isinstance(payload, list):
        return payload, True
    return [], False


def public_manifest(manifest):
    if not manifest:
        return {}
    source = dict(manifest.get("source") or {})
    source.pop("file", None)
    source.pop("path", None)
    cache = dict(manifest.get("cache") or {})
    cache.pop("activePath", None)
    cache.pop("previousPath", None)
    public = {
        "schemaVersion": manifest.get("schemaVersion"),
        "provider": manifest.get("provider"),
        "source": source,
        "groups": manifest.get("groups") or [],
        "fetchedAt": manifest.get("fetchedAt"),
        "importedAt": manifest.get("importedAt"),
        "lastSuccessAt": manifest.get("lastSuccessAt"),
        "recordCount": manifest.get("recordCount") or 0,
        "invalidRecordCount": manifest.get("invalidRecordCount") or 0,
        "staleAfterHours": manifest.get("staleAfterHours"),
        "expiredAfterHours": manifest.get("expiredAfterHours"),
        "staleness": manifest.get("staleness") or {},
        "refresh": manifest.get("refresh") or {},
        "propagation": manifest.get("propagation") or {"available": False},
        "cacheCatalogOnly": True,
        "cache": cache,
    }
    return public


def catalog_response(enabled, data_root=None):
    manifest, manifest_present = load_manifest(data_root)
    records, records_present = load_records(data_root)
    public = public_manifest(manifest) if enabled else {}
    return {
        "enabled": bool(enabled),
        "cachePresent": bool(enabled and manifest_present and records_present),
        "cacheCatalogOnly": True,
        "note": "Satellite orbital elements cache/catalog only; map positions are not calculated in v1.",
        "manifest": public,
        "recordCount": len(records) if enabled and records_present else 0,
        "propagation": {"available": False, "reason": "not_implemented_v1_cache_catalog_only"},
    }


def elements_response(enabled, query=None, data_root=None):
    query = query or {}
    manifest, manifest_present = load_manifest(data_root)
    records, records_present = load_records(data_root)
    max_limit = max(1, env_int("SHM_SATELLITES_MAX_API_LIMIT", 1000))
    default_limit = max(1, min(max_limit, env_int("SHM_SATELLITES_DEFAULT_API_LIMIT", 250)))
    raw_limit = (query.get("limit") or [default_limit])[0]
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer.")
    limit = max(1, min(limit, max_limit))
    group = str((query.get("group") or [""])[0]).strip()

    if not enabled or not manifest_present or not records_present:
        return {
            "enabled": bool(enabled),
            "cachePresent": False,
            "records": [],
            "count": 0,
            "returned": 0,
            "limit": limit,
            "capped": False,
            "group": group or None,
            "manifest": public_manifest(manifest) if enabled and manifest_present else {},
            "cacheCatalogOnly": True,
            "note": "Satellite orbital elements cache/catalog only; map positions are not calculated in v1.",
        }

    filtered = records
    if group:
        filtered = [record for record in records if (record.get("provenance") or {}).get("group") == group]
    capped = len(filtered) > limit
    selected = filtered[:limit]
    return {
        "enabled": True,
        "cachePresent": True,
        "records": selected,
        "count": len(filtered),
        "returned": len(selected),
        "limit": limit,
        "capped": capped,
        "group": group or None,
        "manifest": public_manifest(manifest),
        "cacheCatalogOnly": True,
        "note": "Satellite orbital elements cache/catalog only; map positions are not calculated in v1.",
    }


def main():
    parser = argparse.ArgumentParser(description="Refresh or import cached satellite orbital elements.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_parser = subparsers.add_parser("refresh", help="Fetch CelesTrak GP OMM JSON into the local cache.")
    refresh_parser.add_argument("--group", default=None, help="CelesTrak GROUP value, default active.")

    import_parser = subparsers.add_parser("import", help="Import a local OMM JSON file into the local cache.")
    import_parser.add_argument("--file", required=True, help="Path to a local OMM JSON file.")
    import_parser.add_argument("--group", default="local", help="Group label to attach to imported records.")
    import_parser.add_argument("--source-label", default=None, help="Human-readable source label.")

    args = parser.parse_args()
    if args.command == "refresh":
        manifest = refresh_from_celestrak(group=args.group)
    else:
        manifest = import_omm_file(args.file, group=args.group, source_label=args.source_label)
    print(json.dumps(public_manifest(manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

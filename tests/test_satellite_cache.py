import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SATELLITE_MODULE_PATH = REPO_ROOT / "bin" / "satellite_cache.py"
SATELLITE_SPEC = importlib.util.spec_from_file_location("satellite_cache", SATELLITE_MODULE_PATH)
satellite_cache = importlib.util.module_from_spec(SATELLITE_SPEC)
sys.modules["satellite_cache"] = satellite_cache
SATELLITE_SPEC.loader.exec_module(satellite_cache)

WEB_API_PATH = REPO_ROOT / "bin" / "web-api.py"
WEB_API_SPEC = importlib.util.spec_from_file_location("web_api_satellites", WEB_API_PATH)
web_api = importlib.util.module_from_spec(WEB_API_SPEC)
WEB_API_SPEC.loader.exec_module(web_api)


class temporary_env:
    def __init__(self, **updates):
        self.updates = updates
        self.previous = {}

    def __enter__(self):
        for key, value in self.updates.items():
            self.previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        return self

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def omm_record(norad=25544, name="ISS (ZARYA)", epoch="2026-04-26T00:00:00"):
    return {
        "OBJECT_NAME": name,
        "OBJECT_ID": "1998-067A",
        "NORAD_CAT_ID": norad,
        "EPOCH": epoch,
        "MEAN_MOTION": 15.491,
        "ECCENTRICITY": 0.00041,
        "INCLINATION": 51.64,
        "RA_OF_ASC_NODE": 180.2,
        "ARG_OF_PERICENTER": 55.1,
        "MEAN_ANOMALY": 305.2,
        "BSTAR": 0.00018,
    }


def write_json(path, payload):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)


class SatelliteCacheTests(unittest.TestCase):
    def test_omm_normalization_skips_invalid_records_and_sets_staleness(self):
        provenance = {"providerKey": "celestrak-gp", "group": "stations"}
        valid = omm_record(epoch="2026-04-24T00:00:00Z")
        invalid = {"OBJECT_NAME": "BROKEN"}

        records, invalid_count = satellite_cache.normalize_omm_payload(
            [valid, invalid],
            provenance,
            now_ms=satellite_cache.parse_utc_datetime("2026-04-26T01:00:00Z").timestamp() * 1000,
            stale_hours=48,
            expired_hours=168,
        )

        self.assertEqual(invalid_count, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["recordKey"], "norad:25544")
        self.assertEqual(records[0]["objectName"], "ISS (ZARYA)")
        self.assertEqual(records[0]["staleness"]["state"], "stale")
        self.assertEqual(records[0]["provenance"]["group"], "stations")

    def test_celestrak_refresh_normalizes_payload_and_writes_manifest(self):
        original_fetch = satellite_cache.fetch_omm_json
        try:
            calls = []

            def fake_fetch(url):
                calls.append(url)
                return [omm_record(norad=25544)], {"etag": "test-etag", "lastModified": "Sun, 26 Apr 2026 00:00:00 GMT"}

            satellite_cache.fetch_omm_json = fake_fetch
            with tempfile.TemporaryDirectory() as tmpdir:
                manifest = satellite_cache.refresh_from_celestrak(group="stations", data_root=tmpdir)
                records, present = satellite_cache.load_records(data_root=tmpdir)

            self.assertTrue(calls)
            self.assertIn("GROUP=stations", calls[0])
            self.assertEqual(manifest["recordCount"], 1)
            self.assertEqual(manifest["invalidRecordCount"], 0)
            self.assertEqual(manifest["source"]["etag"], "test-etag")
            self.assertTrue(present)
            self.assertEqual(records[0]["noradCatalogNumber"], 25544)
        finally:
            satellite_cache.fetch_omm_json = original_fetch

    def test_local_import_preserves_active_cache_on_failure_and_previous_on_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_one = Path(tmpdir) / "one.json"
            source_two = Path(tmpdir) / "two.json"
            invalid_source = Path(tmpdir) / "invalid.json"
            write_json(source_one, [omm_record(norad=1, name="ONE")])
            write_json(source_two, [omm_record(norad=2, name="TWO")])
            write_json(invalid_source, [{"OBJECT_NAME": "BROKEN"}])

            satellite_cache.import_omm_file(source_one, group="local", data_root=tmpdir)
            records, present = satellite_cache.load_records(data_root=tmpdir)
            self.assertTrue(present)
            self.assertEqual(records[0]["objectName"], "ONE")

            with self.assertRaises(satellite_cache.SatelliteCacheError):
                satellite_cache.import_omm_file(invalid_source, group="local", data_root=tmpdir)
            records, present = satellite_cache.load_records(data_root=tmpdir)
            self.assertTrue(present)
            self.assertEqual(records[0]["objectName"], "ONE")

            satellite_cache.import_omm_file(source_two, group="local", data_root=tmpdir)
            paths = satellite_cache.cache_paths(tmpdir)
            active_payload, active_present = satellite_cache.read_json(paths["active"])
            previous_payload, previous_present = satellite_cache.read_json(paths["previous"])

            self.assertTrue(active_present)
            self.assertTrue(previous_present)
            self.assertEqual(active_payload["records"][0]["objectName"], "TWO")
            self.assertEqual(previous_payload["records"][0]["objectName"], "ONE")

    def test_staleness_classification_uses_epoch_thresholds(self):
        epoch = int(satellite_cache.parse_utc_datetime("2026-04-26T00:00:00Z").timestamp() * 1000)
        hour_ms = 3_600_000

        fresh = satellite_cache.staleness_for_epoch(epoch, now_ms=epoch + 47 * hour_ms, stale_hours=48, expired_hours=168)
        stale = satellite_cache.staleness_for_epoch(epoch, now_ms=epoch + 49 * hour_ms, stale_hours=48, expired_hours=168)
        expired = satellite_cache.staleness_for_epoch(epoch, now_ms=epoch + 169 * hour_ms, stale_hours=48, expired_hours=168)

        self.assertEqual(fresh["state"], "fresh")
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(expired["state"], "expired")

    def test_satellite_api_defaults_disabled_and_missing_cache_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmpdir, temporary_env(
            SHM_SATELLITES_CACHE_DIR=str(Path(tmpdir) / "cache"),
            SHM_SATELLITES_ENABLED=None,
        ):
            capabilities = web_api.build_capabilities()
            catalog = web_api.build_satellite_catalog_response()
            elements = web_api.build_satellite_elements_response({"limit": ["10"]})

        self.assertFalse(capabilities["satelliteCatalogEnabled"])
        self.assertFalse(capabilities["satellitePropagationEnabled"])
        self.assertFalse(catalog["enabled"])
        self.assertFalse(catalog["cachePresent"])
        self.assertEqual(elements["records"], [])
        self.assertTrue(elements["cacheCatalogOnly"])

    def test_satellite_elements_response_filters_and_caps_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "many.json"
            write_json(
                source,
                [
                    omm_record(norad=1, name="A"),
                    omm_record(norad=2, name="B"),
                    {**omm_record(norad=3, name="C"), "OBJECT_NAME": "C"},
                ],
            )
            satellite_cache.import_omm_file(source, group="local", data_root=tmpdir)
            with temporary_env(
                SHM_SATELLITES_CACHE_DIR=str(Path(tmpdir) / "cache" / "satellites"),
                SHM_SATELLITES_ENABLED="1",
                SHM_SATELLITES_MAX_API_LIMIT="2",
            ):
                response = web_api.build_satellite_elements_response({"group": ["local"], "limit": ["99"]})

        self.assertTrue(response["enabled"])
        self.assertTrue(response["cachePresent"])
        self.assertEqual(response["count"], 3)
        self.assertEqual(response["returned"], 2)
        self.assertTrue(response["capped"])
        self.assertEqual(response["limit"], 2)


if __name__ == "__main__":
    unittest.main()

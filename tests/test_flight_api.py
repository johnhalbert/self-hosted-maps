import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "bin" / "web-api.py"
MODULE_SPEC = importlib.util.spec_from_file_location("web_api", MODULE_PATH)
web_api = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(web_api)


class FlightApiTests(unittest.TestCase):
    def test_normalize_opensky_adds_canonical_identity_and_detail_shape(self):
        payload = {
            "time": 1_700_000_000,
            "states": [
                [
                    "abc123",
                    "DAL123 ",
                    "United States",
                    1_699_999_995,
                    1_699_999_998,
                    -91.1,
                    30.2,
                    9144,
                    False,
                    205.0,
                    180.0,
                    4.1,
                    None,
                    9450,
                    "1200",
                    False,
                    0,
                    None,
                ]
            ],
        }

        feature_collection, detail_entries = web_api.normalize_opensky(payload, fetched_at_ms=1_700_000_010_000)

        feature = feature_collection["features"][0]
        props = feature["properties"]
        self.assertEqual(props["provider"], "opensky")
        self.assertEqual(props["providerKey"], "opensky")
        self.assertEqual(props["recordKey"], "abc123")
        self.assertEqual(props["entityKey"], "opensky:abc123")
        self.assertEqual(props["labelPrimary"], "DAL123")
        self.assertAlmostEqual(props["groundSpeedKts"], 398.5, places=1)
        self.assertEqual(props["positionAgeMsAtFetch"], 15_000)
        self.assertEqual(feature_collection["meta"]["providerKey"], "opensky")

        detail = detail_entries["abc123"]
        self.assertEqual(detail["entityKey"], "opensky:abc123")
        self.assertEqual(detail["raw"]["schema"], "opensky.state_vector.v1")
        self.assertEqual(detail["raw"]["data"]["time"], 1_700_000_000)
        self.assertEqual(detail["raw"]["mapped"]["icao24"], "abc123")

    def test_normalize_adsbx_preserves_tilde_ids_and_provider_alias(self):
        payload = {
            "now": 1_700_000_100,
            "ac": [
                {
                    "hex": "~abcd12",
                    "flight": "RCH321 ",
                    "r": "N12345",
                    "t": "C17",
                    "lat": 30.5,
                    "lon": -90.25,
                    "gs": 240,
                    "track": 270,
                    "seen_pos": 3,
                    "seen": 1,
                    "alt_baro": 12000,
                    "baro_rate": 600,
                }
            ],
        }

        feature_collection, detail_entries = web_api.normalize_adsbx(payload, fetched_at_ms=1_700_000_101_000)

        feature = feature_collection["features"][0]
        props = feature["properties"]
        self.assertEqual(props["provider"], "adsbexchange")
        self.assertEqual(props["providerKey"], "adsbx")
        self.assertEqual(props["recordKey"], "~abcd12")
        self.assertEqual(props["entityKey"], "adsbx:~abcd12")
        self.assertEqual(props["labelPrimary"], "RCH321")
        self.assertEqual(props["craftNumber"], "N12345")
        self.assertAlmostEqual(props["groundSpeedMps"], 123.47, places=2)
        self.assertEqual(props["positionAgeMsAtFetch"], 3000)

        detail = detail_entries["~abcd12"]
        self.assertEqual(detail["raw"]["schema"], "adsbx.aircraft.v1")
        self.assertEqual(detail["raw"]["data"]["hex"], "~abcd12")
        self.assertEqual(detail["summary"]["registration"], "N12345")

    def test_snapshot_cache_rejects_older_generations_and_expires_entries(self):
        cache = web_api.FlightSnapshotCache(ttl_ms=1000)
        older = cache.begin_request("opensky")
        newer = cache.begin_request("opensky")
        older_entries = {
            "abc123": {
                "provider": "opensky",
                "entityKey": "opensky:abc123",
                "summary": {"labelPrimary": "OLD"},
                "raw": {"schema": "opensky.state_vector.v1", "data": {"state": ["abc123"]}},
            }
        }
        newer_entries = {
            "abc123": {
                "provider": "opensky",
                "entityKey": "opensky:abc123",
                "summary": {"labelPrimary": "NEW"},
                "raw": {"schema": "opensky.state_vector.v1", "data": {"state": ["abc123"]}},
            }
        }

        self.assertTrue(cache.commit("opensky", newer, 2000, newer_entries))
        self.assertFalse(cache.commit("opensky", older, 1500, older_entries))
        self.assertEqual(cache.get("opensky", "abc123", current_ms=2500)["summary"]["labelPrimary"], "NEW")
        self.assertIsNone(cache.get("opensky", "abc123", current_ms=3001))

    def test_build_flight_detail_response_reads_cache_entry(self):
        original_cache = web_api.FLIGHT_SNAPSHOT_CACHE
        cache = web_api.FlightSnapshotCache(ttl_ms=10_000)
        try:
            web_api.FLIGHT_SNAPSHOT_CACHE = cache
            now_ms = web_api.current_time_ms()
            generation = cache.begin_request("adsbx")
            cache.commit(
                "adsbx",
                generation,
                now_ms,
                {
                    "~abcd12": {
                        "provider": "adsbexchange",
                        "entityKey": "adsbx:~abcd12",
                        "summary": {"labelPrimary": "RCH321", "providerLabel": "ADS-B Exchange"},
                        "raw": {"schema": "adsbx.aircraft.v1", "data": {"hex": "~abcd12"}},
                    }
                },
            )

            detail = web_api.build_flight_detail_response("adsbx", "~abcd12")

            self.assertEqual(detail["provider"], "adsbexchange")
            self.assertEqual(detail["providerKey"], "adsbx")
            self.assertEqual(detail["recordKey"], "~abcd12")
            self.assertEqual(detail["entityKey"], "adsbx:~abcd12")
            self.assertEqual(detail["summary"]["labelPrimary"], "RCH321")
            self.assertEqual(detail["raw"]["schema"], "adsbx.aircraft.v1")
        finally:
            web_api.FLIGHT_SNAPSHOT_CACHE = original_cache


if __name__ == "__main__":
    unittest.main()

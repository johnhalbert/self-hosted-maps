import importlib.util
import os
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "bin" / "web-api.py"
MODULE_SPEC = importlib.util.spec_from_file_location("web_api_live", MODULE_PATH)
web_api = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(web_api)


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


class LiveLayersApiTests(unittest.TestCase):
    def setUp(self):
        web_api.TOMTOM_TRAFFIC_TILE_CACHE.clear()
        web_api.AIS_SNAPSHOT_CACHE.clear()

    def test_capabilities_default_live_layers_disabled(self):
        with temporary_env(
            SHM_AISSTREAM_ENABLED=None,
            SHM_AISSTREAM_API_KEY=None,
            SHM_TOMTOM_TRAFFIC_ENABLED=None,
            SHM_TOMTOM_API_KEY=None,
            SHM_TOMTOM_TRAFFIC_API_KEY=None,
        ):
            capabilities = web_api.build_capabilities()

        self.assertFalse(capabilities["aisStreamEnabled"])
        self.assertFalse(capabilities["aisStreamConfigured"])
        self.assertFalse(capabilities["tomTomTrafficEnabled"])
        self.assertFalse(capabilities["tomTomTrafficConfigured"])

    def test_capabilities_live_layers_enabled_when_configured(self):
        with temporary_env(
            SHM_AISSTREAM_ENABLED="1",
            SHM_AISSTREAM_API_KEY="ais-key",
            SHM_TOMTOM_TRAFFIC_ENABLED="1",
            SHM_TOMTOM_API_KEY="tomtom-key",
        ):
            capabilities = web_api.build_capabilities()

        self.assertTrue(capabilities["aisStreamEnabled"])
        self.assertTrue(capabilities["aisStreamConfigured"])
        self.assertTrue(capabilities["tomTomTrafficEnabled"])
        self.assertTrue(capabilities["tomTomTrafficFlowEnabled"])
        self.assertTrue(capabilities["tomTomTrafficIncidentsEnabled"])

    def test_tomtom_tile_path_validation_and_url_hides_key_from_client_contract(self):
        kind, z, x, y = web_api.parse_tomtom_tile_path("/api/traffic/tomtom/flow/3/4/5.png")
        self.assertEqual((kind, z, x, y), ("flow", 3, 4, 5))

        with temporary_env(
            SHM_TOMTOM_TRAFFIC_ENABLED="1",
            SHM_TOMTOM_API_KEY="secret-key",
            SHM_TOMTOM_API_BASE_URL="https://example.test",
        ):
            url = web_api.build_tomtom_traffic_tile_url("flow", 3, 4, 5)

        self.assertEqual(
            url,
            "https://example.test/traffic/map/4/tile/flow/relative0/3/4/5.png?key=secret-key&tileSize=256",
        )
        with self.assertRaises(ValueError):
            web_api.parse_tomtom_tile_path("/api/traffic/tomtom/flow/3/4/99.png")

    def test_tomtom_tile_cache_uses_png_only_and_reuses_cached_bytes(self):
        calls = []
        original_get = web_api.http_get_bytes
        try:
            def fake_get(url, headers=None, timeout=15, max_bytes=None):
                calls.append(url)
                return b"\x89PNG\r\n\x1a\nfake", "image/png"

            web_api.http_get_bytes = fake_get
            with temporary_env(
                SHM_TOMTOM_TRAFFIC_ENABLED="1",
                SHM_TOMTOM_API_KEY="secret-key",
                SHM_TOMTOM_TRAFFIC_TILE_TTL_SECONDS="30",
            ):
                first = web_api.fetch_tomtom_traffic_tile("incidents", 1, 0, 0)
                second = web_api.fetch_tomtom_traffic_tile("incidents", 1, 0, 0)

            self.assertEqual(first["cache"], "miss")
            self.assertEqual(second["cache"], "hit")
            self.assertEqual(first["body"], second["body"])
            self.assertEqual(len(calls), 1)
        finally:
            web_api.http_get_bytes = original_get

    def test_tomtom_tile_rejects_non_png_upstream_response(self):
        original_get = web_api.http_get_bytes
        try:
            web_api.http_get_bytes = lambda *_args, **_kwargs: (b"{\"error\":true}", "application/json")
            with temporary_env(SHM_TOMTOM_TRAFFIC_ENABLED="1", SHM_TOMTOM_API_KEY="secret-key"):
                with self.assertRaises(RuntimeError):
                    web_api.fetch_tomtom_traffic_tile("flow", 1, 0, 0)
        finally:
            web_api.http_get_bytes = original_get

    def test_tomtom_tile_respects_per_layer_enabled_flags_before_cache(self):
        web_api.TOMTOM_TRAFFIC_TILE_CACHE.put(("flow", "relative0", 1, 0, 0), b"\x89PNG\r\n\x1a\nfake", "image/png")
        with temporary_env(
            SHM_TOMTOM_TRAFFIC_ENABLED="1",
            SHM_TOMTOM_TRAFFIC_FLOW_ENABLED="0",
            SHM_TOMTOM_API_KEY="secret-key",
        ):
            with self.assertRaises(RuntimeError):
                web_api.fetch_tomtom_traffic_tile("flow", 1, 0, 0)

    def test_ais_bbox_validation_and_subscription_payload(self):
        bounds = web_api.validate_ais_bbox(
            {"lamin": ["29.1"], "lomin": ["-91.2"], "lamax": ["30.2"], "lomax": ["-90.1"]}
        )
        subscription = web_api.build_aisstream_subscription("ais-key", bounds)

        self.assertEqual(subscription["APIKey"], "ais-key")
        self.assertEqual(subscription["BoundingBoxes"], [[[29.1, -91.2], [30.2, -90.1]]])
        self.assertIn("PositionReport", subscription["FilterMessageTypes"])
        with self.assertRaises(ValueError):
            web_api.validate_ais_bbox({"lamin": ["-90"], "lomin": ["-180"], "lamax": ["90"], "lomax": ["180"]})

    def test_ais_subscription_key_expands_tiny_valid_bbox(self):
        key = web_api.ais_subscription_key({"south": 30.001, "west": -90.001, "north": 30.002, "east": -90.0005})
        self.assertLess(key[0], key[2])
        self.assertLess(key[1], key[3])

    def test_aisstream_message_normalization_and_detail_cache(self):
        payload = {
            "MessageType": "PositionReport",
            "MetaData": {
                "MMSI": 368207620,
                "ShipName": "TEST VESSEL",
                "latitude": 30.12,
                "longitude": -90.34,
            },
            "Message": {
                "PositionReport": {
                    "UserID": 368207620,
                    "Latitude": 30.12,
                    "Longitude": -90.34,
                    "Sog": 12.3,
                    "Cog": 87.0,
                    "TrueHeading": 88,
                    "NavigationalStatus": 0,
                }
            },
        }

        record = web_api.normalize_aisstream_message(payload, fetched_at_ms=1_700_000_000_000)

        self.assertEqual(record["recordKey"], "368207620")
        feature = record["feature"]
        self.assertEqual(feature["geometry"]["coordinates"], [-90.34, 30.12])
        self.assertEqual(feature["properties"]["vesselName"], "TEST VESSEL")
        self.assertEqual(feature["properties"]["sogKts"], 12.3)

        self.assertTrue(web_api.AIS_SNAPSHOT_CACHE.update(payload, fetched_at_ms=1_700_000_000_000))
        detail = web_api.AIS_SNAPSHOT_CACHE.get("368207620", now_ms=1_700_000_001_000)
        self.assertEqual(detail["summary"]["vesselName"], "TEST VESSEL")

    def test_websocket_accept_and_frame_helpers(self):
        self.assertEqual(
            web_api.websocket_accept_key("dGhlIHNhbXBsZSBub25jZQ=="),
            "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=",
        )
        frame = web_api.websocket_encode_frame("hello", opcode=1)
        self.assertEqual(frame[0], 0x81)
        self.assertTrue(frame[1] & 0x80)
        self.assertEqual(frame[1] & 0x7F, 5)


if __name__ == "__main__":
    unittest.main()

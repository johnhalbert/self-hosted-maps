import importlib.util
import os
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "bin" / "web-api.py"
MODULE_SPEC = importlib.util.spec_from_file_location("web_api", MODULE_PATH)
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

    def test_opensky_fetch_stays_anonymous_without_credentials(self):
        captured = {}
        original_get = web_api.http_get_json
        original_post = web_api.http_post_form_json
        try:
            web_api.OPENSKY_TOKEN_CACHE.clear()

            def fake_get(url, headers=None, timeout=15):
                captured["url"] = url
                captured["headers"] = headers or {}
                return {"time": 1_700_000_000, "states": []}

            def fake_post(*_args, **_kwargs):
                raise AssertionError("Token endpoint should not be called without credentials.")

            web_api.http_get_json = fake_get
            web_api.http_post_form_json = fake_post
            with temporary_env(
                SHM_OPENSKY_CLIENT_ID="",
                SHM_OPENSKY_CLIENT_SECRET="",
                SHM_OPENSKY_TOKEN_URL=None,
            ):
                web_api.fetch_opensky({"lamin": ["30"], "lomin": ["-91"], "lamax": ["31"], "lomax": ["-90"]})

            self.assertNotIn("Authorization", captured["headers"])
            self.assertIn("/states/all?", captured["url"])
        finally:
            web_api.http_get_json = original_get
            web_api.http_post_form_json = original_post
            web_api.OPENSKY_TOKEN_CACHE.clear()

    def test_opensky_fetch_uses_bearer_token_with_credentials(self):
        captured_posts = []
        captured_gets = []
        original_get = web_api.http_get_json
        original_post = web_api.http_post_form_json
        try:
            web_api.OPENSKY_TOKEN_CACHE.clear()

            def fake_post(url, form, headers=None, timeout=15):
                captured_posts.append((url, dict(form)))
                return {"access_token": "token-123", "expires_in": 1800}

            def fake_get(url, headers=None, timeout=15):
                captured_gets.append((url, headers or {}))
                return {"time": 1_700_000_000, "states": []}

            web_api.http_post_form_json = fake_post
            web_api.http_get_json = fake_get
            with temporary_env(
                SHM_OPENSKY_CLIENT_ID="client-id",
                SHM_OPENSKY_CLIENT_SECRET="client-secret",
                SHM_OPENSKY_TOKEN_URL="https://auth.example/token",
            ):
                query = {"lamin": ["30"], "lomin": ["-91"], "lamax": ["31"], "lomax": ["-90"]}
                web_api.fetch_opensky(query)
                web_api.fetch_opensky(query)

            self.assertEqual(len(captured_posts), 1)
            self.assertEqual(captured_posts[0][0], "https://auth.example/token")
            self.assertEqual(captured_posts[0][1]["grant_type"], "client_credentials")
            self.assertEqual(captured_posts[0][1]["client_id"], "client-id")
            self.assertEqual(captured_posts[0][1]["client_secret"], "client-secret")
            self.assertEqual(captured_gets[0][1]["Authorization"], "Bearer token-123")
            self.assertEqual(captured_gets[1][1]["Authorization"], "Bearer token-123")
        finally:
            web_api.http_get_json = original_get
            web_api.http_post_form_json = original_post
            web_api.OPENSKY_TOKEN_CACHE.clear()

    def test_opensky_token_cache_refreshes_after_expiry(self):
        cache = web_api.OpenSkyTokenCache()
        tokens = iter(["first-token", "second-token"])
        original_post = web_api.http_post_form_json
        try:
            calls = []

            def fake_post(url, form, headers=None, timeout=15):
                calls.append(url)
                return {"access_token": next(tokens), "expires_in": 120}

            web_api.http_post_form_json = fake_post
            with temporary_env(
                SHM_OPENSKY_CLIENT_ID="client-id",
                SHM_OPENSKY_CLIENT_SECRET="client-secret",
                SHM_OPENSKY_TOKEN_URL="https://auth.example/token",
            ):
                self.assertEqual(cache.get_token(now=1000), "first-token")
                self.assertEqual(cache.get_token(now=1059), "first-token")
                self.assertEqual(cache.get_token(now=1061), "second-token")

            self.assertEqual(len(calls), 2)
        finally:
            web_api.http_post_form_json = original_post

    def test_opensky_token_uses_default_endpoint(self):
        cache = web_api.OpenSkyTokenCache()
        original_post = web_api.http_post_form_json
        try:
            calls = []

            def fake_post(url, form, headers=None, timeout=15):
                calls.append(url)
                return {"access_token": "token-123", "expires_in": 1800}

            web_api.http_post_form_json = fake_post
            with temporary_env(
                SHM_OPENSKY_CLIENT_ID="client-id",
                SHM_OPENSKY_CLIENT_SECRET="client-secret",
                SHM_OPENSKY_TOKEN_URL=None,
            ):
                self.assertEqual(cache.get_token(now=1000), "token-123")

            self.assertEqual(calls, [web_api.OPENSKY_DEFAULT_TOKEN_URL])
        finally:
            web_api.http_post_form_json = original_post

    def test_opensky_partial_credentials_raise_runtime_error(self):
        cache = web_api.OpenSkyTokenCache()
        with temporary_env(SHM_OPENSKY_CLIENT_ID="client-id", SHM_OPENSKY_CLIENT_SECRET=""):
            with self.assertRaises(RuntimeError):
                cache.get_token()
        with temporary_env(SHM_OPENSKY_CLIENT_ID="", SHM_OPENSKY_CLIENT_SECRET="client-secret"):
            with self.assertRaises(RuntimeError):
                cache.get_token()

    def test_opensky_malformed_token_response_raises_runtime_error(self):
        cache = web_api.OpenSkyTokenCache()
        original_post = web_api.http_post_form_json
        try:
            web_api.http_post_form_json = lambda *_args, **_kwargs: ["not", "an", "object"]
            with temporary_env(SHM_OPENSKY_CLIENT_ID="client-id", SHM_OPENSKY_CLIENT_SECRET="client-secret"):
                with self.assertRaises(RuntimeError):
                    cache.get_token()

            web_api.http_post_form_json = lambda *_args, **_kwargs: {"expires_in": 1800}
            with temporary_env(SHM_OPENSKY_CLIENT_ID="client-id", SHM_OPENSKY_CLIENT_SECRET="client-secret"):
                with self.assertRaises(RuntimeError):
                    cache.get_token()

            web_api.http_post_form_json = lambda *_args, **_kwargs: {"access_token": "token-123", "expires_in": "bad"}
            with temporary_env(SHM_OPENSKY_CLIENT_ID="client-id", SHM_OPENSKY_CLIENT_SECRET="client-secret"):
                self.assertEqual(cache.get_token(now=1000), "token-123")
                self.assertEqual(cache.get_token(now=2000), "token-123")
        finally:
            web_api.http_post_form_json = original_post

    def test_opensky_token_url_and_upstream_errors_do_not_become_value_errors(self):
        cache = web_api.OpenSkyTokenCache()
        with temporary_env(
            SHM_OPENSKY_CLIENT_ID="client-id",
            SHM_OPENSKY_CLIENT_SECRET="client-secret",
            SHM_OPENSKY_TOKEN_URL="not-a-url",
        ):
            with self.assertRaises(RuntimeError):
                cache.get_token()

        original_post = web_api.http_post_form_json
        try:
            web_api.http_post_form_json = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                web_api.urlerror.URLError("unavailable")
            )
            with temporary_env(SHM_OPENSKY_CLIENT_ID="client-id", SHM_OPENSKY_CLIENT_SECRET="client-secret"):
                with self.assertRaises(web_api.urlerror.URLError):
                    cache.get_token()
        finally:
            web_api.http_post_form_json = original_post


if __name__ == "__main__":
    unittest.main()

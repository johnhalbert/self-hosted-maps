import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "bin" / "web-api.py"
MODULE_SPEC = importlib.util.spec_from_file_location("web_api_street_imagery", MODULE_PATH)
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


JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"local street imagery test jpeg"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"local street imagery test png"


def write_index(root: Path, items):
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.json").write_text(json.dumps({"schema_version": 1, "items": items}), encoding="utf-8")
    web_api.JSON_FILE_CACHE.clear()


def public_item(item_id="item-1", **updates):
    item = {
        "id": item_id,
        "title": "Owner image",
        "lat": 30.1,
        "lon": -90.2,
        "heading": 180,
        "captured_at": "2026-04-01T12:00:00Z",
        "publish_state": "published",
        "review_state": "approved",
        "redaction_required": True,
        "redaction_state": "redacted",
        "exif_stripped": True,
        "exact_location_allowed": True,
        "attribution": "Local owner",
        "license": {"name": "Owner controlled", "url": "https://example.test/license"},
        "source": {"type": "local", "label": "Operator import"},
        "media": {"image": "assets/photo.jpg", "thumbnail": "assets/thumb.png"},
    }
    item.update(updates)
    return item


def street_env(root: Path, **updates):
    values = {
        "SHM_DATA_ROOT": str(root.parent),
        "SHM_STREET_IMAGERY_ENABLED": "1",
        "SHM_STREET_IMAGERY_ROOT": str(root),
    }
    values.update(updates)
    return values


class StreetImageryApiTests(unittest.TestCase):
    def setUp(self):
        web_api.JSON_FILE_CACHE.clear()

    def test_capabilities_default_disabled_and_panoramax_deferred(self):
        with temporary_env(SHM_STREET_IMAGERY_ENABLED=None, SHM_PANORAMAX_ENABLED="1"):
            capabilities = web_api.street_imagery_capabilities()
            app_capabilities = web_api.build_capabilities()

        self.assertFalse(capabilities["enabled"])
        self.assertFalse(capabilities["panoramax"]["enabled"])
        self.assertEqual(capabilities["panoramax"]["mode"], "deferred-third-party-only")
        self.assertFalse(app_capabilities["panoramaxEnabled"])

    def test_coverage_filters_publish_redaction_takedown_and_private_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_index(
                root,
                [
                    public_item("visible"),
                    public_item("private", private=True),
                    public_item("takedown", takedown_state="active"),
                    public_item("unredacted", redaction_required=True, redaction_state="pending"),
                    public_item("draft", publish_state="draft", review_state="pending", publishable=False, approved=False),
                ],
            )
            with temporary_env(**street_env(root)):
                coverage = web_api.build_street_imagery_coverage({"bbox": ["-91,29,-89,31"], "limit": ["100"]})

        self.assertEqual([feature["properties"]["id"] for feature in coverage["features"]], ["visible"])

    def test_bbox_and_limit_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_index(root, [public_item("visible")])
            with temporary_env(
                **street_env(root),
                SHM_STREET_IMAGERY_MAX_BBOX_AREA="1",
            ):
                with self.assertRaises(ValueError):
                    web_api.build_street_imagery_coverage({"bbox": ["-91,29,-89,31"], "limit": ["10"]})
                with self.assertRaises(ValueError):
                    web_api.build_street_imagery_coverage({"bbox": ["not-a-bbox"], "limit": ["10"]})

    def test_public_item_does_not_leak_absolute_or_relative_media_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_index(root, [public_item("visible")])
            with temporary_env(**street_env(root)):
                detail = web_api.build_street_imagery_item_response("visible")

        payload = json.dumps(detail)
        self.assertNotIn(str(root), payload)
        self.assertNotIn("assets/photo.jpg", payload)
        self.assertEqual(detail["imageUrl"], "/api/street-imagery/local/items/visible/image")

    def test_configured_root_must_remain_under_data_root(self):
        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(outside_dir)
            write_index(root, [public_item("visible")])
            with temporary_env(
                SHM_DATA_ROOT=data_dir,
                SHM_STREET_IMAGERY_ENABLED="1",
                SHM_STREET_IMAGERY_ROOT=str(root),
            ):
                capabilities = web_api.street_imagery_capabilities()
                self.assertFalse(capabilities["rootAllowed"])
                self.assertFalse(capabilities["configured"])
                with self.assertRaises(RuntimeError):
                    web_api.build_street_imagery_coverage({"bbox": ["-91,29,-89,31"], "limit": ["10"]})

    def test_media_serving_checks_paths_mime_magic_and_byte_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets = root / "assets"
            assets.mkdir()
            (assets / "photo.jpg").write_bytes(JPEG_BYTES)
            (assets / "thumb.png").write_bytes(PNG_BYTES)
            write_index(root, [public_item("visible")])
            with temporary_env(**street_env(root)):
                media = web_api.fetch_street_imagery_media("visible", "image")

            self.assertEqual(media["body"], JPEG_BYTES)
            self.assertEqual(media["contentType"], "image/jpeg")

            write_index(root, [public_item("traversal", media={"image": "../outside.jpg"})])
            with temporary_env(**street_env(root)):
                with self.assertRaises(ValueError):
                    web_api.fetch_street_imagery_media("traversal", "image")

            (assets / "bad.jpg").write_bytes(b"not a jpeg")
            write_index(root, [public_item("bad-magic", media={"image": "assets/bad.jpg"})])
            with temporary_env(**street_env(root)):
                with self.assertRaises(ValueError):
                    web_api.fetch_street_imagery_media("bad-magic", "image")

            write_index(root, [public_item("too-large")])
            with temporary_env(
                **street_env(root),
                SHM_STREET_IMAGERY_MAX_IMAGE_BYTES="4",
            ):
                with self.assertRaises(RuntimeError):
                    web_api.fetch_street_imagery_media("too-large", "image")

    def test_symlink_media_is_rejected_when_platform_allows_symlinks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets = root / "assets"
            assets.mkdir()
            target = assets / "target.jpg"
            target.write_bytes(JPEG_BYTES)
            link = assets / "link.jpg"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is not available in this environment")
            write_index(root, [public_item("link", media={"image": "assets/link.jpg"})])
            with temporary_env(**street_env(root)):
                with self.assertRaises(ValueError):
                    web_api.fetch_street_imagery_media("link", "image")

    def test_original_media_is_denied_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets = root / "assets"
            assets.mkdir()
            (assets / "original.jpg").write_bytes(JPEG_BYTES)
            write_index(root, [public_item("original-only", media={"original": "assets/original.jpg"})])
            with temporary_env(**street_env(root)):
                with self.assertRaises(RuntimeError):
                    web_api.fetch_street_imagery_media("original-only", "image")

    def test_owner_admin_auth_requires_configured_token(self):
        with temporary_env(SHM_ADMIN_TOKEN=None):
            ok, status, error = web_api.authorize_owner_admin({})
        self.assertFalse(ok)
        self.assertEqual(status, 403)
        self.assertEqual(error["code"], "owner_auth_required")

        with temporary_env(SHM_ADMIN_TOKEN="secret"):
            ok, status, error = web_api.authorize_owner_admin({"Authorization": "Bearer wrong"})
            self.assertFalse(ok)
            self.assertEqual(status, 401)
            self.assertEqual(error["code"], "admin_token_required")

            ok, status, error = web_api.authorize_owner_admin({"Authorization": "Bearer secret"})
            self.assertTrue(ok)
            self.assertEqual(status, 200)
            self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()

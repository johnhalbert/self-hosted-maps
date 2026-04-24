import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "bin" / "web-api.py"
MODULE_SPEC = importlib.util.spec_from_file_location("web_api", MODULE_PATH)
web_api = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(web_api)


def sample_geometry():
    return {
        "type": "Polygon",
        "coordinates": [[[-91.0, 30.0], [-90.0, 30.0], [-90.0, 31.0], [-91.0, 30.0]]],
    }


class DisplayBoundaryResolutionTests(unittest.TestCase):
    def test_env_override_wins_for_display_boundary_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            custom_path = root / "custom-display-boundaries.json"
            resolved = web_api.resolve_display_boundary_index_path(
                install_root=root,
                env_path=str(custom_path),
            )
            self.assertEqual(resolved, custom_path)

    def test_installed_display_boundary_path_beats_repo_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installed_path = root / "www" / web_api.DISPLAY_BOUNDARY_INDEX_NAME
            installed_path.parent.mkdir(parents=True)
            installed_path.write_text("{}", encoding="utf-8")

            (root / "assets").mkdir()
            (root / "assets" / "app.js").write_text("", encoding="utf-8")
            (root / "scripts").mkdir()
            (root / "scripts" / "install-runtime.sh").write_text("", encoding="utf-8")
            (root / "assets" / web_api.DISPLAY_BOUNDARY_INDEX_NAME).write_text("{}", encoding="utf-8")

            resolved = web_api.resolve_display_boundary_index_path(install_root=root, env_path="")
            self.assertEqual(resolved, installed_path)

    def test_repo_checkout_fallback_requires_checkout_markers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "assets").mkdir()
            asset_path = root / "assets" / web_api.DISPLAY_BOUNDARY_INDEX_NAME
            asset_path.write_text("{}", encoding="utf-8")
            (root / "scripts").mkdir()
            (root / "scripts" / "install-runtime.sh").write_text("", encoding="utf-8")
            (root / "assets" / "app.js").write_text("", encoding="utf-8")

            resolved = web_api.resolve_display_boundary_index_path(install_root=root, env_path="")
            self.assertEqual(resolved, asset_path)

    def test_resolve_overlay_state_prefers_display_geometry(self):
        meta = {"provider": "geofabrik", "download_url": "https://example.com/louisiana.osm.pbf"}
        catalog_lookup = web_api.build_catalog_lookup(
            [
                {
                    "id": "louisiana",
                    "source_id": "us/louisiana",
                    "provider": "geofabrik",
                    "download_url": "https://example.com/louisiana.osm.pbf",
                }
            ]
        )
        boundary_index = {"us/louisiana": {"geometry": sample_geometry()}}
        display_index = {"us/louisiana": {"geometry": sample_geometry()}}

        result = web_api.resolve_overlay_state(
            "louisiana",
            meta,
            catalog_lookup,
            boundary_index,
            True,
            display_index,
        )

        self.assertTrue(result["overlayBoundaryAvailable"])
        self.assertEqual(result["overlayBoundarySource"], "display")
        self.assertTrue(result["displayBoundaryAvailable"])

    def test_resolve_overlay_state_uses_provider_fallback_when_display_missing(self):
        meta = {"provider": "geofabrik", "source_id": "us/texas", "name": "Texas"}
        result = web_api.resolve_overlay_state(
            "texas",
            meta,
            web_api.build_catalog_lookup([]),
            {"us/texas": {"geometry": sample_geometry()}},
            True,
            {},
        )

        self.assertTrue(result["overlayBoundaryAvailable"])
        self.assertEqual(result["overlayBoundarySource"], "provider")
        self.assertEqual(result["overlayBoundaryLabel"], "Provider boundary fallback")

    def test_resolve_overlay_state_uses_catalog_match_for_legacy_download_url(self):
        meta = {
            "provider": "geofabrik",
            "download_url": "https://example.com/louisiana.osm.pbf",
            "name": "Louisiana",
        }
        catalog_lookup = web_api.build_catalog_lookup(
            [
                {
                    "id": "louisiana",
                    "source_id": "us/louisiana",
                    "provider": "geofabrik",
                    "download_url": "https://example.com/louisiana.osm.pbf",
                }
            ]
        )

        result = web_api.resolve_overlay_state(
            "legacy-louisiana",
            meta,
            catalog_lookup,
            {"us/louisiana": {"geometry": sample_geometry()}},
            True,
            {"us/louisiana": {"geometry": sample_geometry()}},
        )

        self.assertEqual(result["sourceId"], "us/louisiana")
        self.assertEqual(result["overlayBoundarySource"], "display")


if __name__ == "__main__":
    unittest.main()

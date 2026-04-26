import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "bin" / "web-api.py"
MODULE_SPEC = importlib.util.spec_from_file_location("web_api_terrain", MODULE_PATH)
web_api = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(web_api)


class TerrainApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_root = self.root / "data"
        self.config_root = self.root / "config"
        self.state_file = self.config_root / "datasets.json"
        self.config_root.mkdir(parents=True)
        (self.data_root / "current").mkdir(parents=True)
        web_api.DATA_ROOT = self.data_root
        web_api.CONFIG_ROOT = self.config_root
        web_api.STATE_FILE = self.state_file
        web_api.JSON_FILE_CACHE.clear()
        self.write_state()

    def tearDown(self):
        self.tmp.cleanup()

    def write_state(self, *, selected_hash="hash-1", dataset_ids=None):
        dataset_ids = dataset_ids or ["dataset-a", "dataset-b"]
        state = web_api.default_state()
        state["installed"] = {
            "dataset-a": {"bounds": [-92, 30, -91, 31]},
            "dataset-b": {"bounds": [-91, 31, -90, 32]},
        }
        state["selected"] = dataset_ids
        state["current"].update(
            {
                "selected_hash": selected_hash,
                "artifact_path": str(self.data_root / "current" / "openmaptiles.mbtiles"),
                "rebuilt_at": "2026-04-26T12:00:00Z",
                "dataset_ids": dataset_ids,
            }
        )
        self.state_file.write_text(json.dumps(state), encoding="utf-8")
        web_api.JSON_FILE_CACHE.clear()

    def write_manifest(self, **updates):
        terrain_dir = self.data_root / "current" / "terrain"
        (terrain_dir / "dem" / "0" / "0").mkdir(parents=True, exist_ok=True)
        (terrain_dir / "dem" / "0" / "0" / "0.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        manifest = {
            "schema_version": 1,
            "source": {
                "provider": "Test DEM",
                "product": "Fixture DEM",
                "license": {"name": "fixture"},
                "attribution": "Terrain fixture",
            },
            "attribution": "Terrain fixture",
            "horizontal_datum": "WGS84",
            "vertical_datum": "EGM96",
            "units": "meters",
            "bounds": [-92, 30, -90, 32],
            "selected_hash": "hash-1",
            "dataset_ids": ["dataset-a", "dataset-b"],
            "encoding": "terrarium",
            "tile_size": 256,
            "minzoom": 0,
            "maxzoom": 12,
            "built_at": "2026-04-26T12:30:00Z",
            "checksums": {"file": "checksums.sha256", "tile_count": 1},
            "contours": {"available": False, "enabled": False, "reason": "deferred"},
        }
        manifest.update(updates)
        path = terrain_dir / "terrain-manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        web_api.JSON_FILE_CACHE.clear()
        return path

    def test_missing_terrain_does_not_disable_base_map_state(self):
        overview = web_api.build_overview()
        capabilities = web_api.build_capabilities()

        self.assertEqual(overview["tilejsonUrl"], "/data/openmaptiles.json?v=2026-04-26T12%3A00%3A00Z")
        self.assertFalse(overview["terrainAvailable"])
        self.assertFalse(capabilities["terrainAvailable"])
        self.assertEqual(overview["terrain"]["reason"], "not_installed")

    def test_valid_manifest_advertises_terrain_and_hillshade(self):
        self.write_manifest(encoding="mapbox-terrain-rgb")

        overview = web_api.build_overview()
        capabilities = web_api.build_capabilities()

        self.assertTrue(overview["terrainAvailable"])
        self.assertTrue(overview["terrain"]["hillshadeAvailable"])
        self.assertTrue(capabilities["terrainAvailable"])
        self.assertTrue(capabilities["hillshadeAvailable"])
        self.assertEqual(overview["terrain"]["encoding"], "mapbox")
        self.assertEqual(overview["terrain"]["terrainTileTemplate"], "/terrain/dem/{z}/{x}/{y}.png?v=2026-04-26T12%3A30%3A00Z")
        self.assertEqual(overview["terrain"]["datasetIds"], ["dataset-a", "dataset-b"])

    def test_stale_hash_or_dataset_ids_are_rejected(self):
        self.write_manifest(selected_hash="old-hash")
        self.assertEqual(web_api.build_overview()["terrain"]["reason"], "stale_selected_hash")

        self.write_manifest(dataset_ids=["dataset-a"])
        self.assertEqual(web_api.build_overview()["terrain"]["reason"], "stale_dataset_ids")

    def test_invalid_tile_template_is_not_exposed(self):
        self.write_manifest(tile_template="https://example.test/{z}/{x}/{y}.png")

        terrain = web_api.build_overview()["terrain"]

        self.assertFalse(terrain["terrainAvailable"])
        self.assertIsNone(terrain["terrainTileTemplate"])
        self.assertEqual(terrain["reason"], "invalid_tile_template")

    def test_contours_remain_deferred_even_if_manifest_mentions_them(self):
        self.write_manifest(contours={"available": True, "enabled": False, "reason": "future"})

        terrain = web_api.build_overview()["terrain"]

        self.assertTrue(terrain["terrainAvailable"])
        self.assertFalse(terrain["contoursAvailable"])
        self.assertFalse(terrain["contoursEnabled"])
        self.assertEqual(terrain["contoursReason"], "deferred")


if __name__ == "__main__":
    unittest.main()

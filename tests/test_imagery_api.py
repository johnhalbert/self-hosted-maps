import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "bin" / "web-api.py"
MODULE_SPEC = importlib.util.spec_from_file_location("web_api_imagery", MODULE_PATH)
web_api = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(web_api)

PNG_TILE = b"\x89PNG\r\n\x1a\nfake-png"


class temporary_api_paths:
    def __init__(self, root: Path):
        self.root = root
        self.previous = {}

    def __enter__(self):
        self.previous = {
            "STATE_FILE": web_api.STATE_FILE,
            "IMAGERY_ROOT": web_api.IMAGERY_ROOT,
        }
        web_api.STATE_FILE = self.root / "datasets.json"
        web_api.IMAGERY_ROOT = self.root / "imagery"
        web_api.JSON_FILE_CACHE.clear()
        web_api.IMAGERY_ROOT.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, exc_type, exc, tb):
        web_api.STATE_FILE = self.previous["STATE_FILE"]
        web_api.IMAGERY_ROOT = self.previous["IMAGERY_ROOT"]
        web_api.JSON_FILE_CACHE.clear()


def write_mbtiles(path: Path, tile_data: bytes = PNG_TILE, include_tile: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("create table metadata (name text, value text)")
        conn.execute("create table tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)")
        conn.executemany(
            "insert into metadata (name, value) values (?, ?)",
            [
                ("name", "Sample imagery"),
                ("format", "png"),
                ("bounds", "-91,30,-90,31"),
                ("minzoom", "1"),
                ("maxzoom", "1"),
                ("tile_size", "256"),
            ],
        )
        if include_tile:
            conn.execute(
                "insert into tiles (zoom_level, tile_column, tile_row, tile_data) values (?, ?, ?, ?)",
                (1, 0, 0, tile_data),
            )
        conn.commit()
    finally:
        conn.close()


def write_imagery_state(root: Path, mbtiles_path: Path, overlay_id: str = "sample"):
    state = web_api.default_state()
    state["imagery"]["installed"][overlay_id] = {
        "id": overlay_id,
        "name": "Sample Imagery",
        "format": "mbtiles",
        "tile_format": "png",
        "content_type": "image/png",
        "path": str(mbtiles_path),
        "bounds": [-91, 30, -90, 31],
        "minzoom": 1,
        "maxzoom": 1,
        "tile_size": 256,
        "opacity": 0.75,
        "attribution": "Imagery provider",
        "license": {"name": "Test License", "url": "https://example.test/license"},
        "source": {"type": "local_mbtiles", "url": "", "sha256": "abc123"},
        "available": True,
        "bytes": 12,
        "sha256": "abc123",
        "checked_at": "2026-01-01T00:00:00Z",
        "installed_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    state["imagery"]["order"] = [overlay_id]
    state["imagery"]["enabled"] = [overlay_id]
    (root / "datasets.json").write_text(json.dumps(state), encoding="utf-8")


class ImageryApiTests(unittest.TestCase):
    def test_default_state_merge_adds_imagery_namespace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with temporary_api_paths(root):
                (root / "datasets.json").write_text(json.dumps({"installed": {}, "selected": []}), encoding="utf-8")
                state, present = web_api.read_state()

        self.assertTrue(present)
        self.assertEqual(state["imagery"]["schema_version"], 1)
        self.assertEqual(state["imagery"]["installed"], {})
        self.assertEqual(state["imagery"]["order"], [])
        self.assertEqual(state["imagery"]["enabled"], [])

    def test_mbtiles_metadata_parsing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mbtiles_path = Path(temp_dir) / "sample.mbtiles"
            write_mbtiles(mbtiles_path)

            metadata, tile_rows = web_api.read_mbtiles_metadata(mbtiles_path)

        self.assertEqual(metadata["format"], "png")
        self.assertEqual(metadata["bounds"], "-91,30,-90,31")
        self.assertEqual(tile_rows, (1, 1))

    def test_xyz_to_tms_conversion(self):
        self.assertEqual(web_api.xyz_to_tms_row(1, 1), 0)
        self.assertEqual(web_api.xyz_to_tms_row(3, 2), 5)

    def test_tile_content_type_and_magic_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with temporary_api_paths(root):
                mbtiles_path = web_api.IMAGERY_ROOT / "sample" / "tiles.mbtiles"
                write_mbtiles(mbtiles_path)
                write_imagery_state(root, mbtiles_path)

                tile = web_api.fetch_imagery_tile("sample", 1, 0, 1, "png")

        self.assertEqual(tile["contentType"], "image/png")
        self.assertEqual(tile["body"], PNG_TILE)
        self.assertIn("ETag", {"ETag": tile["etag"]})

    def test_tile_magic_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with temporary_api_paths(root):
                mbtiles_path = web_api.IMAGERY_ROOT / "sample" / "tiles.mbtiles"
                write_mbtiles(mbtiles_path, tile_data=b"not-a-png")
                write_imagery_state(root, mbtiles_path)

                with self.assertRaises(ValueError):
                    web_api.fetch_imagery_tile("sample", 1, 0, 1, "png")

    def test_invalid_id_and_path_rejection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with temporary_api_paths(root):
                outside_path = root / "outside.mbtiles"
                write_mbtiles(outside_path)
                write_imagery_state(root, outside_path)

                with self.assertRaises(ValueError):
                    web_api.validate_imagery_id("../bad")
                with self.assertRaises(ValueError):
                    web_api.get_imagery_overlay("sample")

    def test_missing_tile_raises_not_found(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with temporary_api_paths(root):
                mbtiles_path = web_api.IMAGERY_ROOT / "sample" / "tiles.mbtiles"
                write_mbtiles(mbtiles_path)
                write_imagery_state(root, mbtiles_path)

                with self.assertRaises(web_api.NotFoundError):
                    web_api.fetch_imagery_tile("sample", 1, 1, 1, "png")

    def test_imagery_list_and_raw_tilejson_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with temporary_api_paths(root):
                mbtiles_path = web_api.IMAGERY_ROOT / "sample" / "tiles.mbtiles"
                write_mbtiles(mbtiles_path)
                write_imagery_state(root, mbtiles_path)

                listing = web_api.build_imagery_response()
                tilejson = web_api.imagery_tilejson("sample")

        self.assertEqual(listing["items"][0]["id"], "sample")
        self.assertTrue(listing["items"][0]["enabled"])
        self.assertNotIn("path", listing["items"][0])
        self.assertEqual(tilejson["tilejson"], "2.2.0")
        self.assertEqual(tilejson["tiles"], ["/api/imagery/sample/{z}/{x}/{y}.png"])

    @unittest.skipIf(os.name == "nt", "Bash integration test uses POSIX paths.")
    def test_install_failure_leaves_no_imagery_state_mutation(self):
        if not shutil.which("bash") or not shutil.which("jq"):
            self.skipTest("bash and jq are required for shell script integration coverage.")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_root = root / "config"
            data_root = root / "data"
            state_file = config_root / "datasets.json"
            invalid_mbtiles = root / "invalid.mbtiles"
            config_root.mkdir()
            data_root.mkdir()
            invalid_mbtiles.write_bytes(b"not sqlite")
            state_file.write_text(json.dumps(web_api.default_state()), encoding="utf-8")

            env = {
                **os.environ,
                "SHM_CONFIG_ROOT": str(config_root),
                "SHM_DATA_ROOT": str(data_root),
                "SHM_STATE_FILE": str(state_file),
                "SHM_IMAGERY_ROOT": str(data_root / "imagery"),
                "SHM_PYTHON_BIN": sys.executable,
            }
            result = subprocess.run(
                [
                    "bash",
                    str(REPO_ROOT / "bin" / "install-imagery-mbtiles.sh"),
                    "bad",
                    "Bad Imagery",
                    str(invalid_mbtiles),
                    "--attribution",
                    "Provider",
                    "--license-name",
                    "License",
                ],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            state = json.loads(state_file.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state["imagery"]["installed"], {})
        self.assertEqual(state["imagery"]["order"], [])
        self.assertEqual(state["imagery"]["enabled"], [])


if __name__ == "__main__":
    unittest.main()

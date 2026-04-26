import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
APP_JS = REPO_ROOT / "assets" / "app.js"
TILEMAKER_CONFIG = REPO_ROOT / "config" / "tilemaker" / "config.json"
TILEMAKER_PROCESS = REPO_ROOT / "config" / "tilemaker" / "process.lua"


def read_text(path):
    return path.read_text(encoding="utf-8")


def quoted_values(payload):
    return set(re.findall(r'"([^"]+)"', payload))


class OsmOverlayContractTests(unittest.TestCase):
    def setUp(self):
        self.app_js = read_text(APP_JS)
        self.process_lua = read_text(TILEMAKER_PROCESS)
        self.config = json.loads(TILEMAKER_CONFIG.read_text(encoding="utf-8"))
        self.config_layers = set((self.config.get("layers") or {}).keys())

    def test_viewer_source_layers_are_schema_backed_or_optional(self):
        source_layers = set(re.findall(r'"source-layer"\s*:\s*"([^"]+)"', self.app_js))
        optional_match = re.search(
            r"OPTIONAL_OSM_SOURCE_LAYERS\s*=\s*new Set\(\s*\[(.*?)\]\s*\)",
            self.app_js,
            re.S,
        )
        self.assertIsNotNone(optional_match, "OPTIONAL_OSM_SOURCE_LAYERS is missing")
        optional_layers = quoted_values(optional_match.group(1))

        missing = source_layers - self.config_layers - optional_layers
        self.assertEqual(missing, set())

    def test_tilemaker_emitted_layers_exist_in_config(self):
        emitted_layers = set(re.findall(r":Layer\(\s*\"([^\"]+)\"", self.process_lua))
        self.assertTrue(emitted_layers)
        self.assertEqual(emitted_layers - self.config_layers, set())

    def test_openmaptiles_layer_names_are_preserved(self):
        expected_layers = {
            "boundary",
            "building",
            "landcover",
            "landuse",
            "park",
            "place",
            "transportation",
            "transportation_name",
            "water",
            "water_name",
            "waterway",
        }
        self.assertEqual(expected_layers - self.config_layers, set())

    def test_overlay_groups_reference_known_style_layers_and_schema_layers(self):
        style_layer_ids = set(re.findall(r"\bid\s*:\s*\"([^\"]+)\"", self.app_js))
        grouped_layer_ids = set()
        grouped_source_layers = set()

        for match in re.finditer(r"layerIds\s*:\s*\[(.*?)\]", self.app_js, re.S):
            grouped_layer_ids.update(quoted_values(match.group(1)))
        for match in re.finditer(r"sourceLayers\s*:\s*\[(.*?)\]", self.app_js, re.S):
            grouped_source_layers.update(quoted_values(match.group(1)))

        self.assertTrue(grouped_layer_ids)
        self.assertEqual(grouped_layer_ids - style_layer_ids, set())
        self.assertEqual(grouped_source_layers - self.config_layers, set())

    def test_install_and_update_deploy_repo_tilemaker_profile(self):
        install_runtime = read_text(REPO_ROOT / "scripts" / "install-runtime.sh")
        update_app = read_text(REPO_ROOT / "bin" / "update-app.sh")

        self.assertIn("${SHM_REPO_ROOT}/config/tilemaker", install_runtime)
        self.assertIn("config/tilemaker/config.json", update_app)
        self.assertIn("$stage/install/config/tilemaker", update_app)
        self.assertIn("$SHM_INSTALL_ROOT/config/tilemaker", update_app)


if __name__ == "__main__":
    unittest.main()

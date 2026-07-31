from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import arcgis_rest, emilia_romagna_moka


class EmiliaRomagnaMokaTests(unittest.TestCase):
    def test_context_routes_arcgis_calls_and_restores_original_getter(self) -> None:
        source = {"moka_app_url": "https://example.test/apps/PUG/index.html"}
        original = arcgis_rest._get_json

        with patch.object(emilia_romagna_moka, "_MokaSession") as session_class:
            proxied = session_class.return_value.get_json
            with emilia_romagna_moka._moka_requests(source):
                self.assertIs(arcgis_rest._get_json, proxied)

        self.assertIs(arcgis_rest._get_json, original)

    def test_discover_marks_manifest_with_moka_access_mode(self) -> None:
        source = {
            "key": "r_emilia_test",
            "moka_app_url": "https://example.test/apps/PUG/index.html",
        }
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "catalog" / "manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text('{"source":"r_emilia_test"}', "utf-8")
            delegated = {
                "status": "completed",
                "manifest": str(manifest_path),
                "services": 1,
                "layers": 2,
            }

            with patch.object(
                emilia_romagna_moka, "_moka_requests"
            ), patch.object(
                arcgis_rest, "discover", return_value=delegated
            ):
                result = emilia_romagna_moka.discover(
                    source, None, Path(temporary)
                )

            manifest = json.loads(manifest_path.read_text("utf-8"))

        self.assertEqual(manifest["adapter"], "emilia_romagna_moka")
        self.assertEqual(manifest["moka_app_url"], source["moka_app_url"])
        self.assertIn("proxy pubblico Moka", manifest["access_mode"])
        self.assertIn("2 layer interrogabili", result["message"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import arcgis_rest


class ArcGisRestTests(unittest.TestCase):
    def test_esri_clockwise_outer_ring_and_hole_become_polygon(self) -> None:
        outer_clockwise = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]
        hole_counter_clockwise = [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]

        geometry = arcgis_rest._esri_to_geojson_geometry(
            {"rings": [outer_clockwise, hole_counter_clockwise]}
        )

        self.assertEqual(geometry["type"], "Polygon")
        self.assertEqual(geometry["coordinates"], [outer_clockwise, hole_counter_clockwise])

    def test_layer_meta_finds_oid_by_field_type_when_metadata_is_null(self) -> None:
        def fake_get_json(url: str, **_kwargs):
            if "returnCountOnly" in url:
                return {"count": 1546}
            return {
                "objectIdField": None,
                "fields": [
                    {"name": "OBJECTID", "type": "esriFieldTypeGeometry"},
                    {"name": "SHAPE", "type": "esriFieldTypeOID"},
                ],
            }

        with patch.object(arcgis_rest, "_get_json", side_effect=fake_get_json):
            self.assertEqual(
                arcgis_rest._layer_meta("https://example.test/MapServer", 1),
                ("SHAPE", 1546),
            )

    def test_collection_keeps_same_layer_id_distinct_between_services(self) -> None:
        source = {
            "key": "r_test",
            "livello": "regione",
            "arcgis_services": [
                {
                    "key": "first",
                    "service": "https://example.test/first/MapServer",
                    "layers": [{"id": 1, "name": "Primo"}],
                },
                {
                    "key": "second",
                    "service": "https://example.test/second/MapServer",
                    "layers": [{"id": 1, "name": "Secondo"}],
                },
            ],
        }

        remote = {"layers": [{"id": 1, "name": "Layer", "type": "Feature Layer"}]}
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            arcgis_rest, "_get_json", return_value=remote
        ):
            summary = arcgis_rest.discover(source, None, Path(temporary))
            manifest = json.loads(
                (Path(temporary) / "catalog" / "r_test_services.json").read_text("utf-8")
            )
            with (Path(temporary) / "catalog" / "r_test.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(summary["status"], "completed")
        self.assertEqual([item["layer_key"] for item in manifest["layers"]], ["first:1", "second:1"])
        self.assertEqual([item["uuid"] for item in rows], ["r_test:first:1", "r_test:second:1"])

    def test_always_refresh_is_pending_even_if_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "catalog.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "source": "r_test",
                        "livello": "regione",
                        "arcgis_service": "https://example.test/MapServer",
                        "layers": [
                            {
                                "id": 1,
                                "name": "Stato",
                                "always_refresh": True,
                                "downloadable": True,
                            }
                        ],
                    }
                ),
                "utf-8",
            )
            local = root / "raw" / "regione" / "r_test" / "L1_stato.geojson"
            local.parent.mkdir(parents=True)
            local.write_text('{"type":"FeatureCollection","features":[]}', "utf-8")

            result = arcgis_rest.download(manifest_path, root / "raw", dry_run=True)

        self.assertEqual(result["layers"], 1)

    def test_layer_id_range_excludes_duplicate_scale_branches(self) -> None:
        remote = {
            "layers": [
                {"id": 82, "name": "Gruppo", "type": "Group Layer"},
                {"id": 83, "name": "Dettaglio A", "type": "Feature Layer"},
                {"id": 122, "name": "Dettaglio B", "type": "Feature Layer"},
                {"id": 123, "name": "Fuori intervallo", "type": "Feature Layer"},
            ]
        }
        with patch.object(arcgis_rest, "_get_json", return_value=remote):
            layers = arcgis_rest._source_layers(
                {"layer_id_range": [83, 122]},
                "https://example.test/MapServer",
            )

        self.assertEqual(
            [(layer["id"], layer["name"]) for layer in layers],
            [(83, "Dettaglio A"), (122, "Dettaglio B")],
        )


if __name__ == "__main__":
    unittest.main()

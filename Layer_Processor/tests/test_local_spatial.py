from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import shapefile

from lib import compose_engine, local_spatial


class LocalSpatialTests(unittest.TestCase):
    def test_discover_and_download_link_geojson_and_shapefile_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            points = root / "hotosm_points.geojson"
            points.write_text(
                '{"type":"FeatureCollection","features":[]}', "utf-8"
            )
            polygons = root / "hotosm_polygons.shp"
            writer = shapefile.Writer(str(polygons))
            writer.field("amenity", "C")
            writer.poly([[[9, 45], [10, 45], [10, 46], [9, 45]]])
            writer.record("school")
            writer.close()
            source = {
                "key": "n_test_poi",
                "url": "https://example.test/poi",
                "local_datasets": [
                    {
                        "key": "points",
                        "title": "Punti",
                        "path": str(points),
                        "feature_count": 0,
                    },
                    {
                        "key": "polygons",
                        "title": "Poligoni",
                        "path": str(polygons),
                        "feature_count": 1,
                    },
                ],
            }

            result = local_spatial.discover(source, None, root / "work")
            download = local_spatial.download(
                Path(result["manifest"]), root / "raw"
            )

            output = root / "raw" / "nazionale" / "n_test_poi"
            self.assertTrue((output / "points" / points.name).is_symlink())
            self.assertTrue((output / "polygons" / polygons.name).is_symlink())
            self.assertTrue((output / "polygons" / "hotosm_polygons.dbf").is_symlink())
            self.assertEqual(download["layers_downloaded"], 2)
            self.assertEqual(download["layers_failed"], 0)

    def test_hotosm_geojson_is_read_incrementally_and_filtered_by_bbox(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hotosm_sample.geojson"
            path.write_text(
                '{\n"type":"FeatureCollection",\n"features":[\n'
                '{ "type": "Feature", "properties": {"amenity":"school"}, '
                '"geometry": {"type":"Point","coordinates":[9.2,45.4]} },\n'
                '{ "type": "Feature", "properties": {"shop":"bakery"}, '
                '"geometry": {"type":"Point","coordinates":[14.0,40.0]} }\n]}\n',
                "utf-8",
            )

            features = list(
                compose_engine._iter_source_features(
                    path, (9.0, 45.0, 10.0, 46.0)
                )
            )

        self.assertEqual(len(features), 1)
        self.assertEqual(
            compose_engine._poi_class(features[0]["properties"]),
            ("amenity", "school"),
        )


if __name__ == "__main__":
    unittest.main()

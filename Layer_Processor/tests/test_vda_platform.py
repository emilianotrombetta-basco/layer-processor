import unittest
from unittest.mock import patch

from lib import vda_platform


class VdaPlatformTests(unittest.TestCase):
    @patch.object(vda_platform, "_get")
    def test_layer_rows_keeps_raster_as_metadata_only(self, get):
        get.return_value = {
            "layers": [
                {
                    "id": 0,
                    "name": "Gruppo",
                    "type": "Group Layer",
                    "subLayerIds": [1, 2],
                },
                {
                    "id": 1,
                    "name": "Aree alluvionate",
                    "type": "Feature Layer",
                    "geometryType": "esriGeometryPolygon",
                    "subLayerIds": None,
                },
                {
                    "id": 2,
                    "name": "Ortofoto.tif",
                    "type": "Raster Layer",
                    "subLayerIds": None,
                },
            ]
        }

        rows = vda_platform._layer_rows("Alluvione2024")

        self.assertEqual([row["layer_id"] for row in rows], [1, 2])
        self.assertTrue(rows[0]["downloadable"])
        self.assertEqual(rows[0]["geometry_type"], "esriGeometryPolygon")
        self.assertFalse(rows[1]["downloadable"])
        self.assertEqual(rows[1]["layer_type"], "Raster Layer")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lib import piemonte_catalog


class PiemonteCatalogResumeTests(unittest.TestCase):
    def test_same_legacy_uuid_does_not_merge_distinct_formats(self) -> None:
        common = {
            "title": "Biblioteche",
            "topic": "society",
            "legacy_uuid": "c_l219:38d0528b-e27f-417a-8f30-a8d696a652eb",
        }
        geo = {
            **common,
            "uuid": "c_001272:geo",
            "url": "https://example.test/biblioteche_geo.zip",
        }
        csv = {
            **common,
            "uuid": "c_001272:csv",
            "url": "https://example.test/biblioteche_csv.zip",
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = piemonte_catalog._dataset_dir(root, geo)
            directory.mkdir(parents=True)
            downloaded = directory / "biblioteche_geo.zip"
            downloaded.write_bytes(b"geo")

            self.assertEqual(piemonte_catalog._existing_file(root, geo), downloaded)
            self.assertIsNone(piemonte_catalog._existing_file(root, csv))

    def test_url_disambiguates_reused_legacy_uuid(self) -> None:
        legacy = "c_l219:38d0528b-e27f-417a-8f30-a8d696a652eb"
        first = piemonte_catalog._dataset_uuid(
            "c_001272", legacy, "https://example.test/a.zip"
        )
        second = piemonte_catalog._dataset_uuid(
            "c_001272", legacy, "https://example.test/b.zip"
        )
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()

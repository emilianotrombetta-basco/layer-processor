from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import socrata


class SocrataTests(unittest.TestCase):
    def test_discover_writes_one_downloadable_dataset(self) -> None:
        source = {
            "key": "r_test",
            "livello": "regione",
            "ente": "Inventario test",
            "socrata_dataset": "abcd-1234",
            "socrata_endpoint": "https://example.test/resource/abcd-1234.json",
            "updated_field": "updated_at",
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            socrata,
            "_remote_signature",
            return_value={"count": 3, "max_update": "2026-01-01"},
        ):
            result = socrata.discover(source, None, Path(directory))
            manifest = json.loads(
                (Path(directory) / "catalog" / "r_test_services.json").read_text()
            )
        self.assertEqual(result["records"], 3)
        self.assertEqual(manifest["downloadable_count"], 1)
        self.assertEqual(manifest["layers"][0]["id"], "abcd-1234")

    def test_download_paginates_and_then_skips_same_signature(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "catalog.json"
            manifest.write_text(
                json.dumps(
                    {
                        "source": "r_test",
                        "livello": "regione",
                        "socrata_endpoint": "https://example.test/data.json",
                        "updated_field": "updated_at",
                        "page_size": 2,
                        "layers": [{
                            "id": "abcd-1234",
                            "name": "Inventario test",
                        }],
                    }
                )
            )
            signature = {"count": 3, "max_update": "2026-01-01"}

            def query(_endpoint: str, params: dict) -> list[dict]:
                return (
                    [{"id": 1}, {"id": 2}]
                    if int(params["$offset"]) == 0
                    else [{"id": 3}]
                )

            with patch.object(socrata, "_remote_signature", return_value=signature), patch.object(
                socrata, "_query", side_effect=query
            ) as mocked_query:
                first = socrata.download(manifest, root / "raw")
                second = socrata.download(manifest, root / "raw")
            self.assertEqual(first["layers_downloaded"], 1)
            self.assertEqual(first["results"][0]["features"], 3)
            self.assertEqual(second["status"], "completed")
            self.assertEqual(mocked_query.call_count, 2)


if __name__ == "__main__":
    unittest.main()

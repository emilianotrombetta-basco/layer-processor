import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import sparql_source


class SparqlSourceTests(unittest.TestCase):
    def test_paged_query_normalizes_semicolon_and_existing_pagination(self):
        query = "SELECT * WHERE { ?s ?p ?o } LIMIT 999 OFFSET 999;"
        paged = sparql_source._paged_query(query, 100, 200)
        self.assertEqual(paged.count("LIMIT"), 1)
        self.assertEqual(paged.count("OFFSET"), 1)
        self.assertTrue(paged.endswith("LIMIT 100 OFFSET 200"))
        self.assertNotIn(";;", paged)

    def test_feature_validates_coordinates_and_keeps_properties(self):
        feature = sparql_source._feature(
            {"lat": {"value": "44.5"}, "long": {"value": "11.3"}, "name": {"value": "Museo"}},
            "lat",
            "long",
        )
        self.assertEqual(feature["geometry"]["coordinates"], [11.3, 44.5])
        self.assertEqual(feature["properties"], {"name": "Museo"})

    def test_discover_preserves_provenance(self):
        source = {
            "key": "n_test",
            "ente": "Ente test",
            "url": "https://example.test/source",
            "sparql_endpoint": "https://example.test/sparql",
            "license": "CC BY 4.0",
            "attribution": "Ente test",
            "sparql_datasets": [{"key": "places", "query": "SELECT * WHERE {?s ?p ?o}"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = sparql_source.discover(source, None, Path(tmp))
            manifest = json.loads(Path(result["manifest"]).read_text("utf-8"))
        self.assertEqual(manifest["license"], "CC BY 4.0")
        self.assertEqual(manifest["attribution"], "Ente test")

    def test_download_streams_and_replaces_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "source": "n_test",
                "endpoint": "https://example.test/sparql",
                "source_url": "https://example.test/source",
                "license": "CC BY 4.0",
                "attribution": "Ente test",
                "datasets": [{
                    "uuid": "n_test:places", "key": "places", "title": "Places",
                    "query": "SELECT * WHERE {?s ?p ?o;}", "page_size": 1, "max_rows": 10,
                }],
            }), "utf-8")
            responses = [
                [{"lat": {"value": "44"}, "long": {"value": "11"}}],
                [],
            ]
            with patch("lib.sparql_source.run_query", side_effect=responses) as mocked:
                result = sparql_source.download(manifest_path, root / "raw")
            destination = root / "raw" / "nazionale" / "n_test" / "places" / "places.geojson"
            payload = json.loads(destination.read_text("utf-8"))
            self.assertEqual(result["results"][0]["features"], 1)
            self.assertEqual(len(payload["features"]), 1)
            self.assertEqual(mocked.call_count, 2)
            self.assertIn("LIMIT 1 OFFSET 0", mocked.call_args_list[0].args[1])
            self.assertNotIn(";\nLIMIT", mocked.call_args_list[0].args[1])
            raw_manifest = json.loads((destination.parents[1] / "_manifest.json").read_text("utf-8"))
            self.assertEqual(raw_manifest["attribution"], "Ente test")

    def test_download_failure_keeps_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({
                "source": "n_test", "endpoint": "https://example.test/sparql",
                "datasets": [{"uuid": "n_test:places", "key": "places", "query": "SELECT *", "page_size": 1}],
            }), "utf-8")
            destination = root / "raw" / "nazionale" / "n_test" / "places" / "places.geojson"
            destination.parent.mkdir(parents=True)
            destination.write_text("sentinel", "utf-8")
            with patch("lib.sparql_source.run_query", side_effect=RuntimeError("endpoint down")):
                result = sparql_source.download(manifest_path, root / "raw", refresh=True)
            self.assertEqual(result["results"][0]["status"], "failed")
            self.assertEqual(destination.read_text("utf-8"), "sentinel")


if __name__ == "__main__":
    unittest.main()

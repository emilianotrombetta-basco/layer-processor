from __future__ import annotations

import unittest

from lib import websit_xml


class WebSitXmlTests(unittest.TestCase):
    def test_catalog_deduplicates_same_archive_across_ptm_tables(self) -> None:
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <dataroot generated="2026-01-01">
          <servizi_banchedati_PTM>
            <ID>1</ID><SERVIZIO>Rete stradale</SERVIZIO>
            <DESCRIZIONE>Strade</DESCRIZIONE><CATEGORIA>MOBILITA</CATEGORIA>
            <TAVOLA>PTM 2021 - TAVOLA 1</TAVOLA>
            <METADATO>strade.pdf</METADATO><DATO>strade.zip</DATO>
            <WMS>https://example.test/wms/1</WMS><AGGIORNAMENTO>01/2026</AGGIORNAMENTO>
          </servizi_banchedati_PTM>
          <servizi_banchedati_PTM>
            <ID>2</ID><SERVIZIO>Rete stradale</SERVIZIO>
            <DESCRIZIONE>Strade</DESCRIZIONE><CATEGORIA>INFRASTRUTTURE</CATEGORIA>
            <TAVOLA>PTM 2021 - TAVOLA 2</TAVOLA>
            <METADATO>strade.pdf</METADATO><DATO>strade.zip</DATO>
            <WMS>https://example.test/wms/2</WMS><AGGIORNAMENTO>01/2026</AGGIORNAMENTO>
          </servizi_banchedati_PTM>
        </dataroot>"""
        source = {
            "entry_tag": "servizi_banchedati_PTM",
            "data_base_url": "https://example.test/data/",
            "metadata_base_url": "https://example.test/meta/",
        }

        datasets = websit_xml._parse_catalog(xml, source)

        self.assertEqual(len(datasets), 1)
        self.assertEqual(datasets[0]["url"], "https://example.test/data/strade.zip")
        self.assertEqual(
            datasets[0]["tables"],
            ["PTM 2021 - TAVOLA 1", "PTM 2021 - TAVOLA 2"],
        )
        self.assertEqual(len(datasets[0]["wms"]), 2)
        self.assertEqual(datasets[0]["topic"], "transportation")
        self.assertEqual(
            datasets[0]["metadata"],
            ["https://example.test/meta/strade.pdf"],
        )


if __name__ == "__main__":
    unittest.main()

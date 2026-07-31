from __future__ import annotations

import unittest

from lib import veneto_webgis


class VenetoWebgisTests(unittest.TestCase):
    def test_municipal_viewer_keeps_only_current_planning_layers(self) -> None:
        payload = {
            "result": {
                "maps": [
                    {
                        "groups": [
                            {"id": 1, "name": "Limiti Amministrativi"},
                            {"id": 2, "name": "Stato LR 11/2004 e LR 14/2017 (AUC)"},
                        ],
                        "layers": [
                            {
                                "name": "rv:c0104011_comuni",
                                "title": "Limiti Amministrativi poligonali dei comuni",
                                "groupId": 1,
                            },
                            {
                                "name": "rv:auc_lr14_2017_gbo_082025",
                                "title": "Perimetri AUC lr14_2017",
                                "groupId": 2,
                            },
                            {
                                "name": "rv:zonizzazione_072026",
                                "title": "Zonizzazione_P.R.C.",
                                "groupId": 2,
                            },
                            {
                                "name": "rv:ortofoto_agea_2024",
                                "title": "Ortofoto 2024",
                                "groupId": 1,
                            },
                        ],
                    }
                ]
            }
        }
        available = {
            "rv:c0104011_comuni",
            "rv:auc_lr14_2017_gbo_082025",
            "rv:zonizzazione_072026",
            "rv:ortofoto_agea_2024",
        }

        layers = veneto_webgis._layers_from_config(
            payload,
            viewer_id=213,
            role="municipal_planning",
            available=available,
        )

        self.assertEqual(
            [layer["name"] for layer in layers],
            [
                "rv:c0104011_comuni",
                "rv:auc_lr14_2017_gbo_082025",
                "rv:zonizzazione_072026",
            ],
        )
        self.assertEqual(layers[0]["topic"], "boundaries")
        self.assertTrue(all(layer["viewer_id"] == "213" for layer in layers))

    def test_ptrc_group_assigns_domain_topic_and_skips_non_wfs(self) -> None:
        payload = {
            "result": {
                "maps": [
                    {
                        "groups": [{"id": 7, "name": "TAV. 04 - Mobilità"}],
                        "layers": [
                            {
                                "name": "rv:ferrovia",
                                "title": "Ferrovia. PTRC 2020",
                                "groupId": 7,
                            },
                            {
                                "name": "external:not_downloadable",
                                "title": "Servizio esterno",
                                "groupId": 7,
                            },
                        ],
                    }
                ]
            }
        }

        layers = veneto_webgis._layers_from_config(
            payload,
            viewer_id=191,
            role="ptrc_2020",
            available={"rv:ferrovia"},
        )

        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0]["topic"], "transportation")
        self.assertEqual(layers[0]["group"], "TAV. 04 - Mobilità")


if __name__ == "__main__":
    unittest.main()

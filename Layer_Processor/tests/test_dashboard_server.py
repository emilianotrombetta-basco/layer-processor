from __future__ import annotations

import unittest

import dashboard_server


class DashboardServerTests(unittest.TestCase):
    def test_manifest_errors_reports_failed_results(self) -> None:
        errors = dashboard_server._manifest_errors({
            "results": [
                {
                    "layer_name": "Layer prova",
                    "status": "failed",
                    "error": "HTTP 500",
                },
                {"layer_name": "Layer ok", "status": "completed"},
            ]
        })

        self.assertEqual(errors, ["Layer prova: HTTP 500"])

    def test_dashboard_exposes_running_job_even_for_another_scope(self) -> None:
        fake = {
            "id": "running-test",
            "stage": "download",
            "label": "Download · Piemonte",
            "scope": {"level": "region", "key": "01", "name": "Piemonte"},
            "status": "running",
            "progress": 42,
            "current": 42,
            "total": 100,
            "logs": [],
            "started_at_epoch": 0,
        }
        with dashboard_server.JOBS.lock:
            previous = dashboard_server.JOBS.current
            dashboard_server.JOBS.current = fake
        try:
            payload = dashboard_server.dashboard_payload({
                "level": "region",
                "key": "08",
                "name": "Emilia-Romagna",
            })
        finally:
            with dashboard_server.JOBS.lock:
                dashboard_server.JOBS.current = previous

        self.assertEqual(payload["active_job"]["id"], "running-test")
        self.assertNotEqual(payload["scope"]["key"], payload["active_job"]["scope"]["key"])


if __name__ == "__main__":
    unittest.main()

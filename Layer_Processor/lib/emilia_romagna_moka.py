"""Adapter ArcGIS per le banche dati urbanistiche Moka dell'Emilia-Romagna.

I viewer pubblici PUG e PSC espongono normali MapServer ArcGIS, ma i servizi
vivono su host interni ``*.ente.regione.emr.it``. L'applicazione li raggiunge
attraverso ``/mokaApp/Proxy`` dopo avere inizializzato una sessione HTTP.

Questo adapter conserva il downloader ArcGIS generico e si limita ad aprire la
sessione Moka e a instradare, per la durata della singola operazione, le richieste
REST attraverso il proxy pubblico ufficiale.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from lib import arcgis_rest

Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
USER_AGENT = "LayerProcessor/1.0 (+local territorial data pipeline)"


class _MokaSession:
    def __init__(self, source: dict[str, Any]) -> None:
        self.proxy_url = str(
            source.get("moka_proxy_url")
            or "https://servizimoka.regione.emilia-romagna.it/mokaApp/Proxy?"
        )
        self.request_url = str(
            source.get("moka_request_url")
            or "https://servizimoka.regione.emilia-romagna.it/mokaApp/MokaRequest"
        )
        self.referer = str(source["moka_app_url"])
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Referer": self.referer,
            "X-Requested-With": "XMLHttpRequest",
        }
        self._bootstrap()

    def _bootstrap(self) -> None:
        command = json.dumps(
            {
                "functionClass": (
                    "it.semenda.moka.functionshtml5.attributetable.AttributeTable"
                ),
                "method": "init",
                "parameters": "",
            },
            separators=(",", ":"),
        )
        target = f"{self.request_url}?{urlencode({'cmd': command, '_': str(time.time_ns())})}"
        request = Request(target, headers=self._headers)
        with self._opener.open(request, timeout=120) as response:
            # La risposta elenca gli id Moka scaricabili. È sufficiente leggerla:
            # il cookie JSESSIONID ottenuto abilita il proxy per l'app corrente.
            # Alcuni viewer PTCP senza export configurato rispondono con corpo
            # vuoto: anche in quel caso il cookie di sessione è stato creato.
            response.read()

    def get_json(
        self,
        url: str,
        *,
        attempts: int = 6,
        timeout: int = 300,
    ) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                request = Request(f"{self.proxy_url}{url}", headers=self._headers)
                with self._opener.open(request, timeout=timeout) as response:
                    payload = response.read().decode("utf-8")
                value = json.loads(payload)
                if isinstance(value, dict):
                    return value
                raise ValueError("risposta Moka non oggetto JSON")
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError,
                    ConnectionError, ValueError) as exc:
                last = exc
                if attempt + 1 < attempts:
                    # Una sessione Moka può scadere durante download lunghi.
                    self._bootstrap()
                    time.sleep(min(2.0 * (attempt + 1), 10.0))
        raise RuntimeError(f"Proxy Moka non raggiungibile per {url}: {last}")


@contextmanager
def _moka_requests(source: dict[str, Any]) -> Iterator[None]:
    """Instrada temporaneamente le richieste ArcGIS nel proxy Moka ufficiale."""
    session = _MokaSession(source)
    original = arcgis_rest._get_json
    arcgis_rest._get_json = session.get_json
    try:
        yield
    finally:
        arcgis_rest._get_json = original


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    with _moka_requests(source):
        result = arcgis_rest.discover(source, status_source, work_dir, progress)
    manifest_path = Path(result["manifest"])
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest.update(
        {
            "adapter": "emilia_romagna_moka",
            "moka_app_url": str(source["moka_app_url"]),
            "access_mode": "ArcGIS REST via proxy pubblico Moka con sessione",
        }
    )
    arcgis_rest._atomic_json(manifest_path, manifest)
    result["message"] = (
        f"Scoperta Moka Emilia-Romagna completata: {result['services']} servizi, "
        f"{result['layers']} layer interrogabili."
    )
    return result


def download(
    source: dict[str, Any],
    manifest_path: Path,
    raw_dir: Path,
    *,
    service_filter: str | None = None,
    max_services: int | None = None,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Progress | None = None,
    call_event: CallEvent | None = None,
) -> dict[str, Any]:
    with _moka_requests(source):
        return arcgis_rest.download(
            manifest_path,
            raw_dir,
            service_filter=service_filter,
            max_services=max_services,
            dry_run=dry_run,
            refresh=refresh,
            progress=progress,
            call_event=call_event,
        )

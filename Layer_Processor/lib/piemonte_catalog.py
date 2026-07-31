"""Adapter riproducibile per il catalogo pilota Piemonte/Torino.

Il primo atlante Piemonte è stato costruito scaricando risorse pubbliche da
Regione Piemonte, Città metropolitana/ARPA e Comune di Torino. L'inventario di
quelle risorse è conservato nel registry (solo metadati e URL, non i 24 GB di
file) e costituisce il golden set che una installazione vuota deve poter
ricreare.

``discover`` separa l'inventario per ente e produce il normale catalogo di
stadio 01. ``download`` scarica i file in ``raw/<livello>/<ente>`` con:

- percorso deterministico e compatibile con i nomi del vecchio archivio;
- scrittura atomica ``.part``;
- batch, ripresa e refresh;
- manifest completo per dataset e tracciabilità del vecchio UUID;
- più download concorrenti, mantenuti volutamente pochi per non sovraccaricare
  i portali pubblici.

L'inventario è una baseline riproducibile, non una copia dei dati. I file
cartografici continuano a provenire dagli URL ufficiali al momento del click.
"""
from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 LayerProcessor/1.0"
)
CATALOG_COLUMNS = [
    "uuid",
    "title",
    "topic",
    "url",
    "local_path_or_status",
    "bytes",
    "format",
    "legacy_uuid",
    "source_namespace",
    "downloadable",
    "reference_status",
]


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    temporary.replace(path)


def _atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CATALOG_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _inventory_path(source: dict[str, Any]) -> Path:
    configured = Path(str(source.get("inventory_file") or ""))
    path = configured if configured.is_absolute() else ROOT / "registry" / configured
    if not path.exists():
        raise RuntimeError(f"Inventario Piemonte non trovato: {path}")
    return path


def _inventory_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    owner = str(source["key"])
    with _inventory_path(source).open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("owner_key") == owner]
    if not rows:
        raise RuntimeError(f"L'inventario non contiene risorse per {owner}.")
    return rows


def _bool(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "si", "sì"}


def _format(url: str) -> str:
    suffix = Path(unquote(urlsplit(url).path)).suffix.lstrip(".").upper()
    return suffix or "BIN"


def _dataset_uuid(source_key: str, legacy_uuid: str, url: str) -> str:
    # Il vecchio catalogo contiene più risorse (es. SHP e CSV) con lo stesso UUID.
    # La componente URL rende la chiave naturale univoca senza perdere il riferimento.
    digest = hashlib.sha1(f"{legacy_uuid}\0{url}".encode("utf-8")).hexdigest()[:16]
    return f"{source_key}:{digest}"


def _catalog_row(source: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    legacy_uuid = str(row.get("legacy_uuid") or "")
    namespace = legacy_uuid.split(":", 1)[0] if ":" in legacy_uuid else source["key"]
    downloadable = _bool(row.get("downloadable"))
    return {
        "uuid": _dataset_uuid(str(source["key"]), legacy_uuid, str(row.get("url") or "")),
        "title": str(row.get("title") or ""),
        "topic": str(row.get("topic") or ""),
        "url": str(row.get("url") or ""),
        "local_path_or_status": "discovered" if downloadable else "view_only",
        "bytes": int(row.get("expected_bytes") or 0),
        "format": _format(str(row.get("url") or "")),
        "legacy_uuid": legacy_uuid,
        "source_namespace": namespace,
        "downloadable": "true" if downloadable else "false",
        "reference_status": str(row.get("reference_status") or ""),
    }


def discover(
    source: dict[str, Any],
    _status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    rows = [_catalog_row(source, row) for row in _inventory_rows(source)]
    expected = int(source.get("expected_dataset_count") or 0)
    mismatch = bool(expected and expected != len(rows))
    catalog_path = work_dir / "catalog" / f"{source['key']}.csv"
    manifest_path = work_dir / "catalog" / f"{source['key']}_services.json"
    _atomic_csv(catalog_path, rows)
    downloadable = sum(_bool(row["downloadable"]) for row in rows)
    manifest = {
        "source": source["key"],
        "adapter": "piemonte_catalog",
        "inventory_file": str(_inventory_path(source)),
        "inventory_version": source.get("inventory_version", 1),
        "inventory_count": len(rows),
        "services_count": len(rows),
        "downloadable_count": downloadable,
        "view_only_count": len(rows) - downloadable,
        "expected_dataset_count": expected,
        "count_mismatch": mismatch,
        "services": rows,
        "datasets": rows,
        "failures": [],
        "missing_services": (
            [{"expected": expected, "actual": len(rows)}] if mismatch else []
        ),
    }
    _atomic_json(manifest_path, manifest)
    if progress:
        progress(len(rows), len(rows))
    status = "partial" if mismatch else "completed"
    return {
        "status": status,
        "message": (
            f"Scoperta completata: {len(rows)} risorse, "
            f"{downloadable} scaricabili, {len(rows) - downloadable} solo metadati."
        ),
        "catalog": str(catalog_path),
        "manifest": str(manifest_path),
        "services": len(rows),
        "layers": len(rows),
        "downloadable_layers": downloadable,
        "view_only_layers": len(rows) - downloadable,
        "missing_services": manifest["missing_services"],
        "failures": [],
    }


def _safe(value: str, *, max_length: int = 120) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return (value[:max_length] or "dataset").rstrip("._")


def _legacy_suffix(row: dict[str, Any]) -> str:
    legacy = str(row.get("legacy_uuid") or row.get("uuid") or "")
    identifier = legacy.split(":", 1)[-1]
    return _safe(identifier, max_length=8)


def _normalized_url(url: str) -> str:
    parts = urlsplit(url)
    # urllib richiede un URL ASCII; i vecchi cataloghi contengono alcuni nomi
    # file con lettere accentate non percent-encoded.
    path = quote(unquote(parts.path), safe="/:@%+~!$&'()*;,=-._")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _filename(row: dict[str, Any], headers: Any | None = None) -> str:
    candidate = ""
    if headers is not None:
        disposition = str(headers.get("Content-Disposition") or "")
        encoded = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
        plain = re.search(r'filename="?([^";]+)"?', disposition, re.I)
        if encoded:
            candidate = unquote(encoded.group(1))
        elif plain:
            candidate = plain.group(1).strip()
    if not candidate:
        candidate = Path(unquote(urlsplit(str(row.get("url") or "")).path)).name
    if not candidate:
        extension = mimetypes.guess_extension(
            str(headers.get_content_type()) if headers is not None else ""
        ) or ".bin"
        candidate = f"{row['uuid'].split(':')[-1]}{extension}"
    return _safe(candidate, max_length=180)


def _dataset_dir(root: Path, row: dict[str, Any]) -> Path:
    return (
        root
        / _safe(str(row.get("topic") or "senza_categoria"), max_length=80)
        / f"{_safe(str(row.get('title') or 'dataset'))}__{_legacy_suffix(row)}"
    )


def _existing_file(root: Path, row: dict[str, Any]) -> Path | None:
    directory = _dataset_dir(root, row)
    if not directory.exists():
        return None
    files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and not path.name.endswith((".part", ".tmp"))
    )
    expected_name = _filename(row)
    # Più formati dello stesso dataset possono condividere titolo e legacy UUID
    # (es. biblioteche_geo.zip e biblioteche_csv.zip). Non basta quindi trovare
    # "un file" nella cartella: deve essere proprio quello indicato dall'URL.
    # Gli endpoint che rinominano via Content-Disposition vengono riconosciuti
    # dal percorso salvato nel manifest tramite ``_recorded_file``; dopo un crash
    # tra rename e scrittura manifest è più sicuro riscaricarli che produrre un
    # falso positivo.
    return next((path for path in files if path.name == expected_name), None)


def _recorded_file(root: Path, state: dict[str, Any] | None) -> Path | None:
    if not state or not state.get("local_path"):
        return None
    candidate = root / str(state["local_path"])
    return candidate if candidate.exists() and candidate.is_file() else None


def _download_one(root: Path, row: dict[str, Any], *, attempts: int = 3) -> dict[str, Any]:
    url = _normalized_url(str(row["url"]))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        temporary: Path | None = None
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                },
            )
            with urlopen(request, timeout=180) as response:
                destination = _dataset_dir(root, row) / _filename(row, response.headers)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix + ".part")
                with temporary.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        output.write(chunk)
                if not temporary.stat().st_size:
                    raise OSError("risposta vuota")
                temporary.replace(destination)
            return {
                "uuid": row["uuid"],
                "legacy_uuid": row.get("legacy_uuid"),
                "title": row.get("title"),
                "url": row.get("url"),
                "status": "downloaded",
                "local_path": str(destination.relative_to(root)),
                "bytes": destination.stat().st_size,
            }
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if temporary and temporary.exists():
                temporary.unlink(missing_ok=True)
            retryable = not isinstance(exc, HTTPError) or exc.code in {
                408,
                429,
                500,
                502,
                503,
                504,
            }
            if attempt < attempts and retryable:
                time.sleep(0.6 * attempt)
                continue
            break
    return {
        "uuid": row["uuid"],
        "legacy_uuid": row.get("legacy_uuid"),
        "title": row.get("title"),
        "url": row.get("url"),
        "status": "failed",
        "reason": str(last_error),
    }


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
    if not manifest_path.exists():
        raise RuntimeError(f"Manifest di scoperta non trovato: {manifest_path}")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    rows = [
        row
        for row in manifest.get("datasets", manifest.get("services", []))
        if _bool(row.get("downloadable"))
    ]
    needle = str(service_filter or "").casefold().strip()
    if needle:
        rows = [
            row
            for row in rows
            if needle
            in " ".join(
                str(row.get(field) or "")
                for field in ("uuid", "legacy_uuid", "title", "topic")
            ).casefold()
        ]

    level = str(source.get("livello") or "regione")
    output_root = raw_dir / level / str(source["key"])
    output_root.mkdir(parents=True, exist_ok=True)
    output_manifest = output_root / "_manifest.json"
    previous = (
        json.loads(output_manifest.read_text("utf-8"))
        if output_manifest.exists()
        else {}
    )
    previous_by_uuid = {
        str(item.get("uuid")): item for item in previous.get("datasets", [])
    }

    available_before: dict[str, Path] = {}
    for row in rows:
        existing = (
            _recorded_file(output_root, previous_by_uuid.get(str(row["uuid"])))
            or _existing_file(output_root, row)
        )
        if existing and existing.stat().st_size:
            available_before[str(row["uuid"])] = existing
    todo = rows if refresh else [
        row for row in rows if str(row["uuid"]) not in available_before
    ]
    if max_services is not None and max_services > 0:
        todo = todo[:max_services]

    if dry_run:
        return {
            "status": "dry_run",
            "source": source["key"],
            "layers": len(rows),
            "layers_downloaded": len(available_before),
            "to_download": len(todo),
            "pending_after_batch": max(0, len(rows) - len(available_before) - len(todo)),
            "message": (
                f"{source['key']}: {len(todo)} risorse nel prossimo batch; "
                f"{len(available_before)}/{len(rows)} già presenti."
            ),
        }

    workers = max(1, min(int(source.get("download_workers") or 3), 6))
    current_results: list[dict[str, Any]] = []
    total = len(todo)
    if progress:
        progress(0, total)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_download_one, output_root, row): row for row in todo
        }
        for current, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            result = future.result()
            current_results.append(result)
            if call_event:
                call_event(
                    {
                        "id": row["uuid"],
                        "label": str(row.get("title") or "")[:90],
                        "status": result["status"],
                        "current": current,
                        "total": total,
                        "message": str(result.get("reason") or ""),
                    }
                )
            if progress:
                progress(current, total)

    result_by_uuid = {str(item["uuid"]): item for item in current_results}
    dataset_states: list[dict[str, Any]] = []
    downloaded = 0
    failed_current = 0
    for row in rows:
        key = str(row["uuid"])
        current = result_by_uuid.get(key)
        existing = (
            _recorded_file(output_root, current)
            or _recorded_file(output_root, previous_by_uuid.get(key))
            or _existing_file(output_root, row)
        )
        if current and current.get("status") == "failed":
            failed_current += 1
            state = {**row, **current}
        elif existing and existing.stat().st_size:
            downloaded += 1
            state = {
                **row,
                "status": "downloaded",
                "local_path": str(existing.relative_to(output_root)),
                "bytes": existing.stat().st_size,
            }
        else:
            state = {
                **row,
                **previous_by_uuid.get(key, {}),
                "status": "pending",
            }
        dataset_states.append(state)

    pending = len(rows) - downloaded
    if failed_current:
        status = "partial"
    elif pending:
        status = "batch_completed"
    else:
        status = "completed"
    summary = {
        "status": status,
        "mode": "piemonte_catalog",
        "source": source["key"],
        "layers": len(rows),
        "layers_downloaded": downloaded,
        "layers_failed": failed_current,
        "layers_pending": pending,
        "view_only_layers": int(manifest.get("view_only_count") or 0),
        "batch_requested": len(todo),
        "workers": workers,
        "datasets": dataset_states,
        "results": current_results,
        "message": (
            f"Download {source['key']}: {downloaded}/{len(rows)} risorse presenti, "
            f"{failed_current} errori nella run, {pending} pendenti."
        ),
    }
    _atomic_json(output_manifest, summary)
    failures_path = output_root / "_non_recuperati.csv"
    failed_rows = [row for row in dataset_states if row.get("status") == "failed"]
    if failed_rows:
        temporary = failures_path.with_suffix(".csv.tmp")
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["uuid", "legacy_uuid", "title", "topic", "url", "reason"],
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(failed_rows)
        temporary.replace(failures_path)
    elif failures_path.exists():
        failures_path.unlink()
    return summary

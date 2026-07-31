"""Adapter per i cataloghi XML WebSIT della Città metropolitana di Milano.

Il catalogo PTM ripete lo stesso shapefile in più tavole. La discovery
deduplica i record per nome del pacchetto ``DATO`` e conserva comunque tutte
le tavole, categorie e URL WMS in cui il dataset compare. Il download lavora
per piccoli batch e usa file temporanei, quindi una run interrotta riparte
dall'ultimo archivio concluso.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

Progress = Callable[[int, int], None]
CallEvent = Callable[[dict[str, Any]], None]
USER_AGENT = "LayerProcessor/1.0 (+local territorial data pipeline)"


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _slug(value: str) -> str:
    return _norm(value).replace(" ", "_") or "dataset"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    temporary.replace(path)


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _topic_for(record: dict[str, Any], default: str) -> str:
    """Traduce le categorie editoriali PTM nei topic usati dal riconoscitore."""
    title = _norm(record.get("title", ""))
    categories = {_norm(value) for value in record.get("categories") or []}
    if any(
        token in title
        for token in ("alluvion", "pai", "rischio idrogeologico", "dissesto")
    ):
        return "geoscientificInformation"
    if any(
        token in title
        for token in (
            "ferrovie",
            "metrotramvie",
            "rete stradale",
            "strade",
            "rete ciclabile",
        )
    ):
        return "transportation"
    if any(
        token in title
        for token in (
            "corsi d acqua",
            "fontanili",
            "idraul",
            "piezometr",
            "pozzi pubblici",
            "stato qualitativo",
            "zona di ricarica",
            "stagni",
            "lanche",
            "zone umide",
        )
    ):
        return "inlandWaters"
    if "agricol" in title or "marcite" in title:
        return "farming"
    if any(
        token in title
        for token in ("ambiti trasformazione", "aree dismesse", "accordi di programma")
    ):
        return "planningCadastre"
    if "strutture di vendita" in title:
        return "economy"
    if "sanitar" in title:
        return "health"
    if "infrastrutture" in categories:
        return "transportation"
    if "acque" in categories:
        return "inlandWaters"
    if categories & {"ecologia", "rete verde", "verde", "ambiente", "paesaggio", "vincoli"}:
        return "environment"
    if "servizi" in categories:
        return "society"
    if "limiti amministrativi" in categories:
        return "boundaries"
    if "grafica" in categories:
        return "imageryBaseMapsEarthCover"
    return default


def _parse_catalog(xml_data: bytes, source: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalizza e deduplica le righe XML per archivio scaricabile."""
    root = ET.fromstring(xml_data)
    entry_tag = str(source.get("entry_tag") or "servizi_banchedati_PTM")
    data_base = str(source["data_base_url"])
    metadata_base = str(source.get("metadata_base_url") or "")
    by_archive: dict[str, dict[str, Any]] = {}
    for node in root.findall(f".//{entry_tag}"):
        archive = _text(node, "DATO")
        if not archive or archive.casefold() == "dato":
            continue
        record = by_archive.setdefault(
            archive,
            {
                "id": _text(node, "ID") or _slug(archive),
                "title": _text(node, "SERVIZIO") or archive,
                "description": _text(node, "DESCRIZIONE"),
                "archive": archive,
                "url": urljoin(data_base, archive),
                "updated": _text(node, "AGGIORNAMENTO"),
                "tables": [],
                "categories": [],
                "wms": [],
                "metadata": [],
            },
        )
        for field, target in (
            ("TAVOLA", "tables"),
            ("CATEGORIA", "categories"),
            ("WMS", "wms"),
        ):
            value = _text(node, field)
            if value and value.casefold() not in {field.casefold(), "wms"}:
                record[target].append(value)
        metadata = _text(node, "METADATO")
        if metadata and metadata.casefold() != "metadato":
            record["metadata"].append(urljoin(metadata_base, metadata))
    for record in by_archive.values():
        for field in ("tables", "categories", "wms", "metadata"):
            record[field] = sorted(set(record[field]))
        record["topic"] = _topic_for(
            record,
            str(source.get("topic") or "planningCadastre"),
        )
    return sorted(by_archive.values(), key=lambda row: (_norm(row["title"]), row["archive"]))


def discover(
    source: dict[str, Any],
    _status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    key = str(source["key"])
    catalog_url = str(source["catalog_xml"])
    request = Request(
        catalog_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml"},
    )
    with urlopen(request, timeout=90) as response:
        xml_data = response.read()
    datasets = _parse_catalog(xml_data, source)

    catalog_path = work_dir / "catalog" / f"{key}.csv"
    manifest_path = work_dir / "catalog" / f"{key}_services.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "uuid",
        "title",
        "topic",
        "url",
        "local_path_or_status",
        "bytes",
        "format",
    ]
    temporary = catalog_path.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index, dataset in enumerate(datasets, start=1):
            writer.writerow(
                {
                    "uuid": f"{key}:{dataset['archive']}",
                    "title": dataset["title"],
                    "topic": dataset["topic"],
                    "url": dataset["url"],
                    "local_path_or_status": "discovered",
                    "bytes": 0,
                    "format": "SHP/ZIP",
                }
            )
            if progress:
                progress(index, len(datasets))
    temporary.replace(catalog_path)
    _atomic_json(
        manifest_path,
        {
            "source": key,
            "adapter": "websit_xml",
            "livello": str(source.get("livello") or "provincia"),
            "catalog_url": catalog_url,
            "catalog_sha256": hashlib.sha256(xml_data).hexdigest(),
            "catalog_generated": ET.fromstring(xml_data).attrib.get("generated"),
            "services_count": 1,
            "downloadable_count": len(datasets),
            "datasets": datasets,
        },
    )
    return {
        "status": "completed",
        "message": (
            f"Scoperta WebSIT completata: {len(datasets)} pacchetti unici "
            "deduplicati tra le tavole PTM."
        ),
        "catalog": str(catalog_path),
        "manifest": str(manifest_path),
        "services": 1,
        "layers": len(datasets),
        "downloadable_layers": len(datasets),
        "view_only_layers": 0,
        "missing_services": [],
        "failures": [],
    }


def download(
    manifest_path: Path,
    raw_dir: Path,
    *,
    token_env: str | None = None,
    service_filter: str | None = None,
    max_services: int | None = None,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Progress | None = None,
    call_event: CallEvent | None = None,
) -> dict[str, Any]:
    del token_env
    manifest = json.loads(manifest_path.read_text("utf-8"))
    key = str(manifest["source"])
    livello = str(manifest.get("livello") or "provincia")
    all_datasets = list(manifest.get("datasets") or [])
    datasets = all_datasets
    if service_filter:
        query = _norm(service_filter)
        datasets = [
            row
            for row in datasets
            if query
            in _norm(
                " ".join(
                    [
                        row.get("title", ""),
                        row.get("description", ""),
                        " ".join(row.get("tables") or []),
                        " ".join(row.get("categories") or []),
                    ]
                )
            )
        ]
    output_root = raw_dir / livello / key

    def destination(row: dict[str, Any]) -> Path:
        return output_root / str(row["archive"])

    pending = datasets if refresh else [row for row in datasets if not destination(row).exists()]
    if max_services is not None and max_services > 0:
        pending = pending[:max_services]
    if dry_run:
        return {
            "status": "dry_run",
            "message": f"Download simulato: {len(pending)} pacchetti, {len(datasets)} totali.",
            "layers": len(datasets),
            "layers_downloaded": sum(destination(row).exists() for row in datasets),
        }

    results: list[dict[str, Any]] = []
    output_root.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(pending, start=1):
        target = destination(row)
        temporary = target.with_suffix(target.suffix + ".part")
        call_id = f"{key}:{row['archive']}"
        if call_event:
            call_event(
                {
                    "id": call_id,
                    "label": row["title"],
                    "status": "running",
                    "current": index - 1,
                    "total": len(pending),
                }
            )
        try:
            request = Request(row["url"], headers={"User-Agent": USER_AGENT})
            digest = hashlib.sha256()
            with urlopen(request, timeout=300) as response:
                with temporary.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
            if temporary.stat().st_size == 0:
                raise RuntimeError("archivio vuoto")
            temporary.replace(target)
            size = target.stat().st_size
            result = {
                "archive": row["archive"],
                "title": row["title"],
                "local_path": str(target.relative_to(output_root)),
                "status": "downloaded",
                "bytes": size,
                "sha256": digest.hexdigest(),
            }
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            result = {
                "archive": row["archive"],
                "title": row["title"],
                "status": "failed",
                "reason": str(exc),
            }
        results.append(result)
        if call_event:
            call_event(
                {
                    "id": call_id,
                    "label": row["title"],
                    "status": "completed" if result["status"] == "downloaded" else "failed",
                    "current": index,
                    "total": len(pending),
                    **({"error": result.get("reason")} if result.get("reason") else {}),
                }
            )
        if progress:
            progress(index, len(pending))

    downloaded = sum(destination(row).exists() for row in all_datasets)
    failed = sum(row["status"] == "failed" for row in results)
    status = (
        "partial"
        if failed
        else "completed"
        if downloaded >= len(all_datasets)
        else "batch_completed"
    )
    summary = {
        "status": status,
        "message": (
            f"WebSIT PTM: {len(results)} pacchetti elaborati; "
            f"{downloaded}/{len(all_datasets)} disponibili, {failed} errori."
        ),
        "layers": len(all_datasets),
        "layers_downloaded": downloaded,
        "layers_failed": failed,
        "results": results,
    }
    _atomic_json(output_root / "_manifest.json", summary)
    return summary

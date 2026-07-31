"""Adapter per dataset spaziali locali registrati come fonti nazionali.

Non duplica file molto grandi: discovery crea catalogo e manifest, download
organizza i file in ``raw/nazionale/<source>/`` tramite symlink. Per gli
Shapefile vengono collegati anche DBF/SHX/PRJ/CPG, mantenendo il dataset integro.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
Progress = Callable[[int, int], None]
CSV_COLUMNS = [
    "uuid", "title", "topic", "url", "local_path_or_status", "bytes",
    "source_service", "layer_key", "metadata_url", "download_mode",
    "download_url", "objectid",
]


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    del status_source
    source_key = str(source["key"])
    datasets = list(source.get("local_datasets") or [])
    if not datasets:
        raise ValueError(f"{source_key}: local_datasets non configurato")

    rows: list[dict[str, Any]] = []
    manifest_datasets: list[dict[str, Any]] = []
    total = len(datasets)
    for index, dataset in enumerate(datasets, start=1):
        dataset_key = str(dataset["key"])
        path = _resolve(str(dataset["path"]))
        if not path.exists():
            raise FileNotFoundError(f"Dataset locale non trovato: {path}")
        feature_count = int(dataset.get("feature_count") or 0)
        row = {
            "uuid": f"{source_key}:{dataset_key}",
            "title": str(dataset["title"]),
            "topic": str(dataset.get("topic") or "society"),
            "url": str(source.get("url") or path),
            "local_path_or_status": f"local:{feature_count}",
            "bytes": path.stat().st_size,
            "source_service": str(dataset.get("geometry") or path.suffix.lstrip(".")),
            "layer_key": dataset_key,
            "metadata_url": str(source.get("url") or ""),
            "download_mode": "local_file",
            "download_url": str(path),
            "objectid": index,
        }
        rows.append(row)
        manifest_datasets.append({
            "uuid": row["uuid"],
            "key": dataset_key,
            "title": row["title"],
            "path": str(path),
            "format": str(dataset.get("format") or path.suffix.lstrip(".")),
            "geometry": dataset.get("geometry"),
            "feature_count": feature_count,
            "bytes": path.stat().st_size,
            "downloadable": True,
        })
        if progress:
            progress(index, total)

    catalog = work_dir / "catalog" / f"{source_key}.csv"
    manifest = work_dir / "catalog" / f"{source_key}_services.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    with catalog.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    manifest.write_text(json.dumps({
        "source": source_key,
        "adapter": "local_spatial",
        "inventory_count": total,
        "downloadable_count": total,
        "total_features": sum(item["feature_count"] for item in manifest_datasets),
        "source_url": source.get("url"),
        "license": source.get("license"),
        "attribution": source.get("attribution"),
        "exported_at": source.get("exported_at"),
        "datasets": manifest_datasets,
        "services": [
            {"id": item["uuid"], "name": item["title"]}
            for item in manifest_datasets
        ],
    }, ensure_ascii=False, indent=2), "utf-8")
    return {
        "status": "completed",
        "catalog": str(catalog),
        "manifest": str(manifest),
        "services": total,
        "layers": total,
        "total_features": sum(item["feature_count"] for item in manifest_datasets),
        "missing_services": [],
    }


def download(
    manifest_path: Path,
    raw_dir: Path,
    *,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Progress | None = None,
    call_event: Callable[[dict[str, Any]], None] | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text("utf-8"))
    source_key = str(manifest["source"])
    output_root = raw_dir / "nazionale" / source_key
    datasets = list(manifest.get("datasets") or [])
    if dry_run:
        return {"status": "dry_run", "layers": len(datasets)}

    results: list[dict[str, Any]] = []
    for index, dataset in enumerate(datasets, start=1):
        src = Path(str(dataset["path"]))
        dataset_dir = output_root / str(dataset["key"])
        status = "skipped"
        error = None
        linked: list[Path] = []
        try:
            inputs = (
                sorted(src.parent.glob(f"{src.stem}.*"))
                if src.suffix.lower() == ".shp"
                else [src]
            )
            dataset_dir.mkdir(parents=True, exist_ok=True)
            for item in inputs:
                destination = dataset_dir / item.name
                if destination.exists() or destination.is_symlink():
                    if refresh:
                        destination.unlink()
                        destination.symlink_to(item)
                        status = "downloaded"
                else:
                    destination.symlink_to(item)
                    status = "downloaded"
                linked.append(destination)
            main = dataset_dir / src.name
        except OSError as exc:
            main = dataset_dir / src.name
            status = "failed"
            error = str(exc)
        result = {
            "uuid": dataset["uuid"],
            "dataset": dataset["key"],
            "layer_name": dataset["title"],
            "status": status,
            "local_path": str(main.relative_to(output_root)),
            "linked_files": [str(path.relative_to(output_root)) for path in linked],
        }
        if error:
            result["error"] = error
        results.append(result)
        if call_event:
            call_event({
                "id": str(dataset["uuid"]),
                "label": str(dataset["title"]),
                "status": status,
                **({"error": error} if error else {}),
            })
        if progress:
            progress(index, len(datasets))

    downloaded = sum(item["status"] in {"downloaded", "skipped"} for item in results)
    failed = sum(item["status"] == "failed" for item in results)
    summary = {
        "status": "completed" if not failed else "partial",
        "mode": "local_ingest",
        "layers": len(datasets),
        "layers_downloaded": downloaded,
        "layers_failed": failed,
        "license": manifest.get("license"),
        "attribution": manifest.get("attribution"),
        "exported_at": manifest.get("exported_at"),
        "results": results,
        "message": (
            f"Fonte locale organizzata: {downloaded}/{len(datasets)} dataset "
            f"disponibili, {failed} errori."
        ),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8"
    )
    return summary

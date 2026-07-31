"""Adapter Valle d'Aosta da FILE LOCALI (nessuna autenticazione).

I dati SCT professionali richiedono un token ArcGIS, ma i piani regolatori VdA
sono già stati scaricati gratuitamente e vivono su disco come GeoJSON WGS84 in
``Nord/Valle d'aosta/`` (PRG prescrittiva/motivazionale + PTP). Questo adapter li
cataloga e li ingerisce direttamente: nessuna rete, nessun token, niente
``authentication_required``. Sostituisce ``vda_sct`` come percorso di default per
``r_vda``; l'adapter ArcGIS resta disponibile se in futuro si fornisce un token.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
Progress = Callable[[int, int], None]

# file combinati (unione di tutti i layer): saltati, teniamo i per-tema
_COMBINED = {"prg-prescrittiva.geojson", "prg-motivazionale.geojson", "ptp.geojson"}
_CSV_COLUMNS = [
    "uuid", "title", "topic", "url", "local_path_or_status", "bytes",
    "source_service", "layer_key", "metadata_url", "download_mode",
    "download_url", "objectid",
]


def _slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return "_".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split()) or "layer"


def _humanize(filename: str) -> str:
    stem = re.sub(r"\.geojson$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"^\d+[_-]", "", stem)  # toglie il prefisso numerico
    stem = re.sub(r"^[pm]\d+[_-]", "", stem)  # toglie il prefisso p1/m5
    return stem.replace("-", " ").replace("_", " ").strip().capitalize()


def _resolve_root(source: dict[str, Any]) -> Path:
    raw = source.get("local_root") or "../Nord/Valle d'aosta"
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p).resolve()


def _manifest_index(local_root: Path) -> dict[str, dict[str, Any]]:
    """basename file -> {name, count, geometry, section} da tutti i _manifest.json."""
    index: dict[str, dict[str, Any]] = {}
    for manifest in local_root.rglob("_manifest.json"):
        try:
            data = json.loads(manifest.read_text("utf-8"))
        except Exception:
            continue
        for section, value in data.items():
            layers = value.get("layers", []) if isinstance(value, dict) else []
            for layer in layers:
                fname = layer.get("file")
                if fname:
                    index[fname] = {
                        "name": layer.get("name") or _humanize(fname),
                        "count": layer.get("count"),
                        "geometry": layer.get("geometry"),
                        "section": section,
                    }
    return index


def _count_features(path: Path) -> int:
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return 0
    return len(data.get("features", [])) if isinstance(data, dict) else 0


def _layer_files(local_root: Path) -> list[Path]:
    """Tutti i .geojson per-tema (dentro le cartelle *_layers), esclusi i combinati."""
    files = [
        p for p in local_root.rglob("*.geojson")
        if p.name not in _COMBINED and "_layers" in p.parent.name
    ]
    return sorted(files)


def discover(
    source: dict[str, Any],
    status_source: dict[str, Any] | None,
    work_dir: Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    local_root = _resolve_root(source)
    if not local_root.exists():
        raise FileNotFoundError(f"Cartella dati VdA non trovata: {local_root}")
    index = _manifest_index(local_root)
    files = _layer_files(local_root)
    if not files:
        raise FileNotFoundError(f"Nessun GeoJSON per-tema in {local_root}")

    raw_vda = ROOT / "raw" / "regione" / "r_vda"
    rows: list[dict[str, Any]] = []
    counts: list[int] = []
    total = len(files)
    for i, path in enumerate(files, start=1):
        meta = index.get(path.name, {})
        section = meta.get("section") or _humanize(path.parent.name)
        # conteggio feature: dal manifest se presente, altrimenti letto dal file (PTP)
        n = meta.get("count")
        if n is None:
            n = _count_features(path)
        counts.append(int(n or 0))
        # cartella download ordinata per sezione: raw/regione/r_vda/<sezione>/<file>.geojson
        target = raw_vda / _slug(section) / path.name
        rows.append({
            "uuid": f"r_vda:{_slug(section)}:{_slug(path.stem)}",
            "title": meta.get("name") or _humanize(path.name),
            "topic": "",  # ignoto: il matcher usa solo le keyword (nessun gate errato)
            "url": str(target),           # posizione organizzata (creata nello stadio download)
            "local_path_or_status": f"local:{n}",
            "bytes": path.stat().st_size,
            "source_service": section,
            "layer_key": str(meta.get("geometry") or ""),
            "metadata_url": "",
            "download_mode": "local_file",
            "download_url": str(path),     # sorgente reale in Nord/ (target del symlink)
            "objectid": i,
        })
        if progress and (i == total or i % 10 == 0):
            progress(i, total)

    catalog_path = work_dir / "catalog" / "r_vda.csv"
    manifest_path = work_dir / "catalog" / "r_vda_services.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with catalog_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    sections = sorted({r["source_service"] for r in rows})
    section_stats = {
        s: {
            "layers": sum(r["source_service"] == s for r in rows),
            "features": sum(c for r, c in zip(rows, counts) if r["source_service"] == s),
        }
        for s in sections
    }
    manifest_path.write_text(json.dumps({
        "source": "r_vda",
        "adapter": "vda_local",
        "local_root": str(local_root),
        "layers": len(rows),
        "inventory_count": len(rows),
        "total_features": sum(counts),
        "sections": section_stats,
        # una voce per layer: la dashboard conta i download su len(services)
        "services": [{"id": r["uuid"], "name": r["title"], "section": r["source_service"]}
                     for r in rows],
        "auth_required": False,
    }, ensure_ascii=False, indent=2), "utf-8")

    return {
        "status": "completed",
        "catalog": str(catalog_path),
        "manifest": str(manifest_path),
        "services": len(sections),
        "layers": len(rows),
        "total_features": sum(counts),
        "sections": {s: v["features"] for s, v in section_stats.items()},
        "missing_services": [],
        "unexpected_services": [],
    }


def download(
    manifest_path: Path,
    raw_dir: Path,
    *,
    dry_run: bool = False,
    refresh: bool = False,
    progress: Progress | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Organizza i dati VdA (già locali) nella cartella download via symlink.

    Nessuna rete, nessun token: crea raw/regione/r_vda/<sezione>/<file>.geojson che
    punta al file reale in Nord/, così la fase successiva (recognize/compose) trova
    tutto in una cartella ordinata e uniforme con le altre regioni.
    """
    services = json.loads(Path(manifest_path).read_text("utf-8"))
    output_root = raw_dir / "regione" / "r_vda"
    output_root.mkdir(parents=True, exist_ok=True)
    stale = output_root / "_auth_required.json"  # stato di auth ormai superato
    if stale.exists():
        stale.unlink()

    catalog = manifest_path.parent / "r_vda.csv"
    rows = list(csv.DictReader(catalog.open(encoding="utf-8"))) if catalog.exists() else []
    total = len(rows)
    if dry_run:
        return {"status": "dry_run", "layers": total, "token_required": False}

    results: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        src = Path(row["download_url"])          # sorgente reale in Nord/
        dst = Path(row["url"])                    # posizione organizzata in raw/
        if not src.exists():
            results.append({"layer_name": row["title"], "section": row["source_service"],
                            "status": "failed", "reason": "sorgente mancante"})
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            if refresh:
                dst.unlink()
                dst.symlink_to(src)
            status = "downloaded" if refresh else "skipped"
        else:
            dst.symlink_to(src)
            status = "downloaded"
        results.append({"layer_name": row["title"], "section": row["source_service"],
                        "local_path": str(dst.relative_to(output_root)), "status": status})
        if progress and (i == total or i % 20 == 0):
            progress(i, total)

    available = sum(1 for r in rows if Path(r["url"]).exists() or Path(r["url"]).is_symlink())
    summary = {
        "status": "completed",
        "mode": "local_ingest",
        "auth_required": False,
        "layers": total,
        "layers_downloaded": available,
        "layers_failed": total - available,
        "local_root": services.get("local_root"),
        "note": "Dati VdA collegati da file locali già scaricati; nessuna autenticazione.",
        "results": results,
    }
    (output_root / "_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    return summary

import csv
import json
from pathlib import Path


ROOT = Path("/Users/emilianotrombetta/Desktop/espansione del dominio")
SOURCE_DIR = ROOT / "Sources" / "OpenCUP"
PROJECT_DIR = SOURCE_DIR / "OpendataProgetti"
LOCALIZATION_CSV = SOURCE_DIR / "OpenCup_Localizzazione.csv"
OUTPUT_DIR = ROOT / "opencup Regionale"
COUNTS_CSV = OUTPUT_DIR / "conteggio_progetti_per_regione.csv"
NORD_CSV = OUTPUT_DIR / "opencup Nord.csv"
SUMMARY_JSON = OUTPUT_DIR / "opencup_regionale_summary.json"

NORTH_REGION_CODES = {"01", "02", "03", "04", "05", "06", "07", "08"}


def build_region_sets() -> tuple[int, dict[str, str], dict[str, set[str]], set[str]]:
    total_rows = 0
    region_names: dict[str, str] = {}
    region_cups: dict[str, set[str]] = {}
    north_cups: set[str] = set()

    with LOCALIZATION_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            total_rows += 1
            cup = (row.get("CUP") or "").strip()
            codice_regione = (row.get("CODICE_REGIONE") or "").strip()
            regione = (row.get("REGIONE") or "").strip()
            if not cup or not codice_regione:
                continue
            region_names.setdefault(codice_regione, regione)
            region_cups.setdefault(codice_regione, set()).add(cup)
            if codice_regione in NORTH_REGION_CODES:
                north_cups.add(cup)

    return total_rows, region_names, region_cups, north_cups


def write_counts(
    region_names: dict[str, str], region_cups: dict[str, set[str]]
) -> list[dict[str, object]]:
    rows = [
        (codice_regione, region_names.get(codice_regione, ""), len(cups))
        for codice_regione, cups in region_cups.items()
    ]
    rows.sort(key=lambda item: item[0])
    with COUNTS_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["CODICE_REGIONE", "REGIONE", "PROGETTI_DISTINTI"])
        writer.writerows(rows)
    return [
        {
            "codice_regione": codice_regione,
            "regione": regione,
            "progetti_distinti": progetti,
        }
        for codice_regione, regione, progetti in rows
    ]


def write_north_projects(nord_cups: set[str]) -> tuple[int, int]:
    project_files = sorted(PROJECT_DIR.glob("OpenCup_Progetti*.csv"))
    written_rows = 0
    total_rows = 0
    header = None

    with NORD_CSV.open("w", encoding="utf-8", newline="") as out:
        writer = None
        for path in project_files:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter=";")
                file_header = next(reader)
                if header is None:
                    header = file_header
                    writer = csv.writer(out, delimiter=";", quoting=csv.QUOTE_MINIMAL)
                    writer.writerow(header)
                elif file_header != header:
                    raise ValueError(f"Header mismatch in {path}")

                cup_index = header.index("CUP")
                for row in reader:
                    total_rows += 1
                    if row and row[cup_index] in nord_cups:
                        writer.writerow(row)
                        written_rows += 1

    return total_rows, written_rows


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    localization_rows, region_names, region_cups, north_cups = build_region_sets()
    counts = write_counts(region_names, region_cups)
    project_rows, nord_project_rows = write_north_projects(north_cups)
    summary = {
        "localization_rows_read": localization_rows,
        "project_rows_read": project_rows,
        "nord_project_rows_written": nord_project_rows,
        "nord_distinct_cups": len(north_cups),
        "counts": counts,
        "outputs": {
            "counts_csv": str(COUNTS_CSV),
            "nord_csv": str(NORD_CSV),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

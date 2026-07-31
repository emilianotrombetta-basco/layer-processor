import csv
import json
from pathlib import Path


ROOT = Path("/Users/emilianotrombetta/Desktop/espansione del dominio")
SOURCE_DIR = ROOT / "Sources" / "OpenCUP"
PROJECT_DIR = SOURCE_DIR / "OpendataProgetti"
LOCALIZATION_CSV = SOURCE_DIR / "OpenCup_Localizzazione.csv"
OUTPUT_DIR = ROOT / "opencup Regionale"
SUMMARY_JSON = OUTPUT_DIR / "opencup_macroaree_summary.json"

MACROAREAS = {
    "Centro": {
        "codes": {"09", "10", "11", "12"},
        "output": OUTPUT_DIR / "opencup Centro.csv",
    },
    "Sud e Isole": {
        "codes": {"13", "14", "15", "16", "17", "18", "19", "20"},
        "output": OUTPUT_DIR / "opencup Sud e Isole.csv",
    },
}


def build_macroarea_sets() -> tuple[int, dict[str, set[str]]]:
    total_rows = 0
    cup_sets = {name: set() for name in MACROAREAS}

    with LOCALIZATION_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            total_rows += 1
            cup = (row.get("CUP") or "").strip()
            codice_regione = (row.get("CODICE_REGIONE") or "").strip()
            if not cup or not codice_regione:
                continue
            for name, config in MACROAREAS.items():
                if codice_regione in config["codes"]:
                    cup_sets[name].add(cup)
                    break

    return total_rows, cup_sets


def write_project_files(cup_sets: dict[str, set[str]]) -> tuple[int, dict[str, int]]:
    project_files = sorted(PROJECT_DIR.glob("OpenCup_Progetti*.csv"))
    writers = {}
    handles = {}
    written = {name: 0 for name in MACROAREAS}
    total_rows = 0
    header = None

    try:
        for name, config in MACROAREAS.items():
            handle = config["output"].open("w", encoding="utf-8", newline="")
            handles[name] = handle
            writers[name] = None

        for path in project_files:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter=";")
                file_header = next(reader)
                if header is None:
                    header = file_header
                    for name in MACROAREAS:
                        writers[name] = csv.writer(
                            handles[name], delimiter=";", quoting=csv.QUOTE_MINIMAL
                        )
                        writers[name].writerow(header)
                elif file_header != header:
                    raise ValueError(f"Header mismatch in {path}")

                cup_index = header.index("CUP")
                for row in reader:
                    total_rows += 1
                    if not row:
                        continue
                    cup = row[cup_index]
                    for name, cup_set in cup_sets.items():
                        if cup in cup_set:
                            writers[name].writerow(row)
                            written[name] += 1
                            break
    finally:
        for handle in handles.values():
            handle.close()

    return total_rows, written


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    localization_rows, cup_sets = build_macroarea_sets()
    project_rows, written = write_project_files(cup_sets)

    summary = {
        "localization_rows_read": localization_rows,
        "project_rows_read": project_rows,
        "macroareas": {
            name: {
                "region_codes": sorted(config["codes"]),
                "distinct_cups": len(cup_sets[name]),
                "rows_written": written[name],
                "output": str(config["output"]),
            }
            for name, config in MACROAREAS.items()
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

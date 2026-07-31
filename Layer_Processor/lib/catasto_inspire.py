"""Motore catasto INSPIRE (Agenzia delle Entrate) dai file locali in ``ITALIA/``.

Struttura annidata: ``ITALIA/<REGIONE>.zip → <PROV>.zip → <BELFIORE>_<COMUNE>.zip
→ {_map.gml = CP:CadastralZoning (fogli), _ple.gml = CP:CadastralParcel (particelle)}``.
CRS EPSG:6706 (RDN2008 geografico, ordine lat/lon nel posList). Il parser è in
streaming (iterparse) perché una regione ha milioni di particelle.

Uso tipico: ``iter_parcels(region_zip, belfiore=...)`` per le particelle di un
comune → GeoJSON, base geometrica del semaforo di edificabilità per-lotto.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
ITALIA = ROOT / "ITALIA"
_CP = "{http://mapserver.gis.umn.edu/mapserver}"
_GML = "{http://www.opengis.net/gml/3.2}"

# Nome zip regione → codice ISTAT regione (le 19 presenti; manca il 04 TN-AA).
REGION_ZIP = {
    "ABRUZZO": "13", "BASILICATA": "17", "CALABRIA": "18", "CAMPANIA": "15",
    "EMILIA-ROMAGNA": "08", "FRIULI-VENEZIA-GIULIA": "06", "LAZIO": "12",
    "LIGURIA": "07", "LOMBARDIA": "03", "MARCHE": "11", "MOLISE": "14",
    "PIEMONTE": "01", "PUGLIA": "16", "SARDEGNA": "20", "SICILIA": "19",
    "TOSCANA": "09", "UMBRIA": "10", "VALLE-AOSTA": "02", "VENETO": "05",
}


def regions_present(base: Path = ITALIA) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for name, istat in sorted(REGION_ZIP.items(), key=lambda kv: kv[1]):
        path = base / f"{name}.zip"
        if path.exists():
            out.append({"region_zip": name, "region_istat": istat, "path": str(path)})
    return out


def _ring(poslist: str) -> list[list[float]]:
    """posList "lat lon lat lon…" → [[lon,lat],…] (GeoJSON vuole lon,lat)."""
    nums = poslist.split()
    return [[float(nums[i + 1]), float(nums[i])] for i in range(0, len(nums) - 1, 2)]


def _polygon_coords(poly: ET.Element) -> list[list[list[float]]]:
    rings: list[list[list[float]]] = []
    ext = poly.find(f"{_GML}exterior/{_GML}LinearRing/{_GML}posList")
    if ext is not None and ext.text:
        rings.append(_ring(ext.text))
    for interior in poly.findall(f"{_GML}interior/{_GML}LinearRing/{_GML}posList"):
        if interior.text:
            rings.append(_ring(interior.text))
    return rings


def parse_parcels(source: Any) -> Iterator[dict[str, Any]]:
    """Streaming dei ``CP:CadastralParcel`` da un _ple.gml (path o file-like) →
    feature GeoJSON con geometria (Polygon/MultiPolygon) e riferimenti catastali."""
    context = ET.iterparse(source, events=("end",))
    for _event, elem in context:
        if elem.tag != f"{_CP}CadastralParcel":
            continue
        geom_wrap = elem.find(f"{_CP}msGeometry")
        polygons: list[list[list[list[float]]]] = []
        if geom_wrap is not None:
            for poly in geom_wrap.iter(f"{_GML}Polygon"):
                coords = _polygon_coords(poly)
                if coords:
                    polygons.append(coords)
        ref = elem.findtext(f"{_CP}NATIONALCADASTRALREFERENCE") or ""
        foglio = particella = ""
        if "_" in ref and "." in ref:
            body = ref.split("_", 1)[1]
            foglio, _, particella = body.partition(".")
        props = {
            "riferimento_catastale": ref,
            "foglio": foglio,
            "particella": particella,
            "label": elem.findtext(f"{_CP}LABEL") or "",
            "comune_catastale": elem.findtext(f"{_CP}ADMINISTRATIVEUNIT") or "",
            "inspire_id": elem.findtext(f"{_CP}INSPIREID_LOCALID") or "",
        }
        elem.clear()
        if not polygons:
            continue
        if len(polygons) == 1:
            geometry = {"type": "Polygon", "coordinates": polygons[0]}
        else:
            geometry = {"type": "MultiPolygon", "coordinates": polygons}
        yield {"type": "Feature", "geometry": geometry, "properties": props}


def iter_comune_ple(region_zip: Path, belfiore: str | None = None) -> Iterator[tuple[str, bytes]]:
    """Naviga gli zip annidati della regione e restituisce (nome_zip_comune,
    bytes del _ple.gml). Se ``belfiore`` è dato, filtra a quel comune (prefisso)."""
    with zipfile.ZipFile(region_zip) as region:
        for prov_name in region.namelist():
            if not prov_name.lower().endswith(".zip"):
                continue
            with zipfile.ZipFile(io.BytesIO(region.read(prov_name))) as prov:
                for com_name in prov.namelist():
                    if not com_name.lower().endswith(".zip"):
                        continue
                    if belfiore and not com_name.upper().startswith(f"{belfiore.upper()}_"):
                        continue
                    with zipfile.ZipFile(io.BytesIO(prov.read(com_name))) as com:
                        for entry in com.namelist():
                            if entry.lower().endswith("_ple.gml"):
                                yield com_name, com.read(entry)


def iter_parcels(
    region_zip: Path, belfiore: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Tutte le particelle di una regione (o del solo comune ``belfiore``) come
    feature GeoJSON, in streaming."""
    for _com_name, ple_bytes in iter_comune_ple(region_zip, belfiore=belfiore):
        yield from parse_parcels(io.BytesIO(ple_bytes))


def list_comuni(region_zip: Path) -> list[str]:
    """Elenco dei comuni (nomi zip <BELFIORE>_<NOME>) presenti nella regione."""
    names: list[str] = []
    with zipfile.ZipFile(region_zip) as region:
        for prov_name in region.namelist():
            if not prov_name.lower().endswith(".zip"):
                continue
            with zipfile.ZipFile(io.BytesIO(region.read(prov_name))) as prov:
                names.extend(
                    n for n in prov.namelist() if n.lower().endswith(".zip")
                )
    return sorted(names)

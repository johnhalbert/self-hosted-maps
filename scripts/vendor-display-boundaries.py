#!/usr/bin/env python3
import argparse
import hashlib
import io
import json
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path


SOURCE_URL = "https://www2.census.gov/geo/tiger/GENZ2024/kml/cb_2024_us_state_500k.zip"
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "assets" / "us-state-display-boundary-index.json"

SUPPORTED_UNITS = {
    "AL": "us/alabama",
    "AK": "us/alaska",
    "AZ": "us/arizona",
    "AR": "us/arkansas",
    "CA": "us/california",
    "CO": "us/colorado",
    "CT": "us/connecticut",
    "DE": "us/delaware",
    "DC": "us/district-of-columbia",
    "FL": "us/florida",
    "GA": "us/georgia",
    "HI": "us/hawaii",
    "ID": "us/idaho",
    "IL": "us/illinois",
    "IN": "us/indiana",
    "IA": "us/iowa",
    "KS": "us/kansas",
    "KY": "us/kentucky",
    "LA": "us/louisiana",
    "ME": "us/maine",
    "MD": "us/maryland",
    "MA": "us/massachusetts",
    "MI": "us/michigan",
    "MN": "us/minnesota",
    "MS": "us/mississippi",
    "MO": "us/missouri",
    "MT": "us/montana",
    "NE": "us/nebraska",
    "NV": "us/nevada",
    "NH": "us/new-hampshire",
    "NJ": "us/new-jersey",
    "NM": "us/new-mexico",
    "NY": "us/new-york",
    "NC": "us/north-carolina",
    "ND": "us/north-dakota",
    "OH": "us/ohio",
    "OK": "us/oklahoma",
    "OR": "us/oregon",
    "PA": "us/pennsylvania",
    "PR": "us/puerto-rico",
    "RI": "us/rhode-island",
    "SC": "us/south-carolina",
    "SD": "us/south-dakota",
    "TN": "us/tennessee",
    "TX": "us/texas",
    "VI": "us/us-virgin-islands",
    "UT": "us/utah",
    "VT": "us/vermont",
    "VA": "us/virginia",
    "WA": "us/washington",
    "WV": "us/west-virginia",
    "WI": "us/wisconsin",
    "WY": "us/wyoming",
}

KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_ring(text: str):
    points = []
    for chunk in text.split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        lon = round(float(parts[0]), 5)
        lat = round(float(parts[1]), 5)
        points.append([lon, lat])
    if len(points) < 3:
        return None
    if points[0] != points[-1]:
        points.append(points[0])
    if len(points) < 4:
        return None
    return points


def parse_polygon(polygon: ET.Element):
    outer_text = polygon.findtext(".//kml:outerBoundaryIs/kml:LinearRing/kml:coordinates", "", KML_NS)
    outer_ring = normalize_ring(outer_text)
    if not outer_ring:
        return None

    rings = [outer_ring]
    for inner in polygon.findall(".//kml:innerBoundaryIs/kml:LinearRing/kml:coordinates", KML_NS):
        inner_ring = normalize_ring(inner.text or "")
        if inner_ring:
            rings.append(inner_ring)
    return rings


def parse_geometry(placemark: ET.Element):
    polygons = []
    for polygon in placemark.findall(".//kml:Polygon", KML_NS):
        polygon_coords = parse_polygon(polygon)
        if polygon_coords:
            polygons.append(polygon_coords)

    if not polygons:
        return None
    if len(polygons) == 1:
        return {"type": "Polygon", "coordinates": polygons[0]}
    return {"type": "MultiPolygon", "coordinates": polygons}


def parse_placemark_fields(placemark: ET.Element):
    return {
        field.attrib.get("name", ""): field.text or ""
        for field in placemark.findall(".//kml:SimpleData", KML_NS)
    }


def build_items(kml_bytes: bytes):
    root = ET.fromstring(kml_bytes)
    items = {}
    seen_codes = set()

    for placemark in root.findall(".//kml:Placemark", KML_NS):
        fields = parse_placemark_fields(placemark)
        state_code = fields.get("STUSPS", "").strip()
        source_id = SUPPORTED_UNITS.get(state_code)
        if not source_id:
            continue

        geometry = parse_geometry(placemark)
        if not geometry:
            raise ValueError(f"Missing geometry for Census unit {state_code}")

        items[source_id] = {
            "source_id": source_id,
            "name": fields.get("NAME", source_id),
            "state_code": state_code,
            "geoid": fields.get("GEOID", ""),
            "overlay_source": "us_census_cb_2024_us_state_500k",
            "geometry": geometry,
        }
        seen_codes.add(state_code)

    missing_codes = sorted(set(SUPPORTED_UNITS) - seen_codes)
    if missing_codes:
        raise ValueError(f"Missing Census units in KML: {', '.join(missing_codes)}")

    return {key: items[key] for key in sorted(items)}


def load_source_archive(input_zip: Path | None):
    if input_zip:
        archive_bytes = input_zip.read_bytes()
        archive_url = str(input_zip)
    else:
        with urllib.request.urlopen(SOURCE_URL) as response:
            archive_bytes = response.read()
        archive_url = SOURCE_URL
    return archive_url, archive_bytes


def extract_kml(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        kml_names = [name for name in archive.namelist() if name.lower().endswith(".kml")]
        if not kml_names:
            raise ValueError("The source archive does not contain a KML file")
        kml_name = kml_names[0]
        return kml_name, archive.read(kml_name)


def main():
    parser = argparse.ArgumentParser(description="Vendor U.S. state display boundaries for self-hosted-maps.")
    parser.add_argument("--input-zip", type=Path, help="Use a previously downloaded Census zip instead of fetching live data.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON index path.")
    args = parser.parse_args()

    source_url, archive_bytes = load_source_archive(args.input_zip)
    archive_sha256 = sha256_bytes(archive_bytes)
    kml_name, kml_bytes = extract_kml(archive_bytes)
    kml_sha256 = sha256_bytes(kml_bytes)
    items = build_items(kml_bytes)

    payload = {
        "generated_at": iso_now(),
        "source": {
            "provider": "us-census",
            "dataset": kml_name,
            "archive_url": source_url,
            "archive_sha256": archive_sha256,
            "kml_sha256": kml_sha256,
            "transform": "KML -> compact JSON index, properties stripped, coordinates rounded to 5 decimals",
        },
        "items": items,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
    args.output.write_text(content, encoding="utf-8")

    print(f"Wrote {args.output}")
    print(f"Archive SHA256: {archive_sha256}")
    print(f"KML SHA256: {kml_sha256}")
    print(f"Output SHA256: {sha256_bytes(content.encode('utf-8'))}")
    print(f"Entries: {len(items)}")


if __name__ == "__main__":
    main()

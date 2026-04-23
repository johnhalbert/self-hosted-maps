# Static World Basemap

`assets/world-land.geojson` is a vendored Natural Earth land-only fallback layer for the global map background.

## Current source

- Theme: Natural Earth physical `ne_50m_land`
- Natural Earth theme version: `4.0.0`
- Upstream repo snapshot: `nvkelso/natural-earth-vector` tag `v4.1.0`
- Raw GeoJSON URL: `https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v4.1.0/geojson/ne_50m_land.geojson`
- Vendored on: `2026-04-22`

## Checksums

- Downloaded upstream SHA256: `36c2b381f25c3e55d7e24b4f633b89168a3d37a6fdc048f9852a049b30468abd`
- Vendored `assets/world-land.geojson` SHA256: `521a7b42c1137e53498ffd54e6b7ad9db1dd23e1ee1ba6f1fc88f678882ff1a8`

## Vendoring flow

This is a one-time asset generation step. It is not part of the repo build or runtime.

```bash
curl -L -o /tmp/ne_50m_land.geojson \
  https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v4.1.0/geojson/ne_50m_land.geojson

python - <<'PY'
import json
from pathlib import Path

src = Path("/tmp/ne_50m_land.geojson")
dst = Path("assets/world-land.geojson")

data = json.loads(src.read_text(encoding="utf-8"))
out = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {},
            "geometry": feature["geometry"],
        }
        for feature in data["features"]
    ],
}

dst.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
PY
```

## Notes

- All feature properties are stripped because the viewer only uses geometry for the `global-land` fill.
- The vendored file size is `1,498,885` bytes.
- If this asset ever proves too heavy in real usage, regenerate from the corresponding `ne_110m_land` source and update this document with the new source, checksums, and size.

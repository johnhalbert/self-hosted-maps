# U.S. State Display Boundaries

`assets/us-state-display-boundary-index.json` is a vendored display-only boundary index used to tighten selected overlays for supported Geofabrik U.S. state extracts.

## Current source

- Source: U.S. Census Bureau cartographic boundary KML
- Dataset: `cb_2024_us_state_500k.kml`
- Archive URL: `https://www2.census.gov/geo/tiger/GENZ2024/kml/cb_2024_us_state_500k.zip`
- Vendored on: `2026-04-22`
- Coverage in this repo: 50 states, District of Columbia, Puerto Rico, and U.S. Virgin Islands

## Checksums

- Downloaded archive SHA256: `70c21b67144e5005254dac6784236d2f5cb3a5f4e769234c4d4e79647f37f639`
- Extracted KML SHA256: `7ef5fc511d8359cac32fe37bfde4dccb0f4412d781d062b38dddda4eb9285c1b`
- Vendored asset SHA256: `ffd421b3b8f8a43d228b701d944e54a14522b4081e9e1f19020f2e9aba2c1872`

## Vendoring flow

This is a one-time asset generation step. It is not part of the repo build or runtime.

```bash
python scripts/vendor-display-boundaries.py
```

To regenerate from a previously downloaded archive:

```bash
python scripts/vendor-display-boundaries.py \
  --input-zip /path/to/cb_2024_us_state_500k.zip
```

## Notes

- The generated index is keyed by Geofabrik `source_id`.
- The transform strips nonessential properties and rounds coordinates to 5 decimal places.
- `bin/web-api.py` prefers this curated display geometry before falling back to provider boundary geometry.
- This asset is display-only. It does not change rebuild inputs, extract semantics, or initial map framing.
- Vendored file size: `6,032,785` bytes.

# Offline OSM Overlays

The viewer includes a separate **Offline OSM layers** control for local vector tiles. It only toggles layers already present in the current OpenMapTiles-compatible MBTiles; it does not call remote providers or request new data.

## Availability

At startup the viewer reads `/data/openmaptiles.json` and checks `vector_layers`. Source layers that are absent from the current tileset are filtered from the style before MapLibre loads it, and overlay buttons with no available layers are disabled. If TileJSON does not expose `vector_layers`, the viewer keeps the existing layers enabled to preserve compatibility with older TileServer responses.

The checked source-layer references are:

- `landcover`, `landuse`, `park`
- `water`, `waterway`, `water_name`
- `transportation`, `transportation_name`
- `building`
- `boundary`
- `place`
- additive optional layers: `theme_area`, `theme_line`, `theme_poi`

## Tilemaker Profile

`config/tilemaker` is repo-owned and is installed to `/opt/self-hosted-maps/config/tilemaker` during fresh installs and application updates. The profile preserves the OpenMapTiles layer names used by the viewer while keeping additive thematic output allowlisted:

- `theme_area` for green-space and selected recreation polygons
- `theme_line` for trails, paths, cycleways, and related mobility lines
- `theme_poi` for selected civic, food/drink, health, education, public-service, tourism, and recreation POIs

The profile does not pass raw tags through and does not emit broad `landuse=*` overlays. Dense POIs are high-zoom only.

After changing `config/tilemaker`, rebuild the active map selection. Application updates copy the profile but do not rebuild existing MBTiles.

## Audit Commands

Inspect generated source layers in the current MBTiles:

```sh
sqlite3 /var/lib/self-hosted-maps/current/openmaptiles.mbtiles \
  "select value from metadata where name = 'json';" | jq '.vector_layers[].id'
```

Preview source layers from TileServer TileJSON:

```sh
curl -s http://127.0.0.1/data/openmaptiles.json | jq '.vector_layers[].id'
```

Static contract tests cover viewer `source-layer` references, emitted Tilemaker layers, overlay group layer ids, and deployment references.

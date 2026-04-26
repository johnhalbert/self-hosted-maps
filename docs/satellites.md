# Cached Satellite Orbital Elements

Satellite support is disabled by default and is cache/catalog only in v1. The app can store OMM JSON orbital elements locally and expose their provenance and staleness, but it does not propagate positions, draw satellite points, generate ground tracks, or claim live tracking.

## Configuration

Add these values to `/etc/self-hosted-maps/self-hosted-maps.runtime.conf` and restart `self-hosted-maps-api`:

```sh
SHM_SATELLITES_ENABLED="1"
SHM_SATELLITES_CELESTRAK_GROUP="active"
SHM_SATELLITES_STALE_AFTER_HOURS="48"
SHM_SATELLITES_EXPIRED_AFTER_HOURS="168"
SHM_SATELLITES_DEFAULT_API_LIMIT="250"
SHM_SATELLITES_MAX_API_LIMIT="1000"
SHM_ADMIN_TOKEN="set-a-token-before-refresh-or-import"
```

The cache lives under `${SHM_DATA_ROOT}/cache/satellites/`:

```text
manifest.json
celestrak-gp.json
previous-celestrak-gp.json
```

`previous-celestrak-gp.json` is preserved from the last successful active cache before a new successful refresh/import is promoted. Failed refreshes or imports leave the active cache untouched.

## Refresh And Import

CelesTrak GP OMM JSON refresh uses the configured CelesTrak group and does not use Space-Track:

```sh
python3 /opt/self-hosted-maps/bin/satellite_cache.py refresh --group active
```

Local OMM JSON import normalizes records into the same internal schema:

```sh
python3 /opt/self-hosted-maps/bin/satellite_cache.py import --file /path/to/omm.json --group local --source-label "local OMM import"
```

The local API also exposes admin job routes:

- `POST /api/admin/satellites/refresh` with optional JSON body `{"group":"active"}`
- `POST /api/admin/satellites/import` with JSON body `{"sourceFile":"/path/to/omm.json","group":"local","sourceLabel":"local OMM import"}`

These routes require `SHM_ADMIN_TOKEN` to be set and supplied as `Authorization: Bearer <token>` or `X-SHM-Admin-Token: <token>`.

## Read-Only API

Browser and integration clients should only use the read-only local API:

- `GET /api/satellites/catalog`
- `GET /api/satellites/elements?group=local&limit=250`

Responses are wrapped in the normal `{ "ok": true, "data": ... }` shape. They include provider/source metadata, fetch/import time, record counts, stale/expired thresholds, staleness state, and `cacheCatalogOnly: true`.

The public API does not fetch CelesTrak from the browser and does not expose local absolute cache paths.

## Data Notes

Each normalized element includes the NORAD catalog number, object name/id, epoch, mean motion, eccentricity, inclination, RAAN, argument of pericenter, mean anomaly, BSTAR when available, the raw source record, provenance, and per-record staleness.

Staleness is a cache quality signal, not an operational validity guarantee. Cached elements may be unsuitable for precise or safety-critical use even when marked fresh.

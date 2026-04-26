# self-hosted-maps

## Notes

- Static world land fallback data is vendored in `assets/world-land.geojson`. Source and regeneration details live in `docs/world-land.md`.
- Curated U.S. state display-boundary overrides are vendored in `assets/us-state-display-boundary-index.json`. Source and regeneration details live in `docs/us-state-display-boundaries.md`.
- Offline OSM layer controls and the repo-owned Tilemaker profile are documented in `docs/offline-osm-overlays.md`.
- Offline raster imagery overlays can be installed from licensed raster MBTiles. Usage and licensing requirements live in `docs/imagery-overlays.md`.
- This repo expects LF line endings. Avoid switching the same checkout back and forth between Windows Git and WSL Git; if you need both, use separate clones or worktrees.

## Runtime Configuration

OpenSky can run anonymously, but authenticated REST API access is supported by setting these server-side values in `/etc/self-hosted-maps/self-hosted-maps.runtime.conf`:

```sh
SHM_OPENSKY_CLIENT_ID="your-api-client-id"
SHM_OPENSKY_CLIENT_SECRET="your-api-client-secret"
```

The optional `SHM_OPENSKY_TOKEN_URL` defaults to OpenSky's OAuth2 client-credentials token endpoint. Restart `self-hosted-maps-api` after changing runtime credentials.

Live vessel and road-traffic overlays are disabled by default and keep provider keys server-side in the local API. To enable AIS vessel positions from AISStream:

```sh
SHM_AISSTREAM_ENABLED="1"
SHM_AISSTREAM_API_KEY="your-aisstream-key"
```

To enable TomTom traffic flow and incident raster overlays:

```sh
SHM_TOMTOM_TRAFFIC_ENABLED="1"
SHM_TOMTOM_API_KEY="your-tomtom-key"
```

TomTom tiles are proxied through `/api/traffic/tomtom/...` so the browser never receives the API key. Restart `self-hosted-maps-api` after changing these runtime settings.

Offline raster imagery overlays are served from locally managed MBTiles under `/var/lib/self-hosted-maps/imagery`. Install only imagery that permits local storage and serving:

```sh
self-hosted-maps-install-imagery <id> "<name>" /path/to/tiles.mbtiles --attribution "<text>" --license-name "<license>"
self-hosted-maps-list-imagery
self-hosted-maps-remove-imagery <id>
```

## Application Updates

Installed systems include a local updater so you do not need to recreate the Debian host for application changes. Update your source checkout first, then run:

```sh
self-hosted-maps-manager
```

Choose `Update application`, review the preview, and confirm the update. You can also run the updater directly:

```sh
self-hosted-maps-update-app --source /path/to/self-hosted-maps --preview
self-hosted-maps-update-app --source /path/to/self-hosted-maps --apply
```

The updater applies a local checkout into `/opt/self-hosted-maps`; it does not run `git pull`, update datasets, rebuild maps, install packages, or change runtime secrets. Default updates refresh installed scripts, viewer assets, the repo-owned Tilemaker profile, manager docs, and command shortcuts while preserving downloaded datasets, current map tiles, runtime credentials, dataset state, and `/opt/self-hosted-maps/www/vendor`. Rebuild the active map selection after Tilemaker profile changes.

Use `--refresh-system-config` only when you want to update systemd, nginx, or TileServer config from the checkout. App update metadata is stored in `/etc/self-hosted-maps/app-manifest.json`, with backups under `/var/lib/self-hosted-maps/backups/app-update`.

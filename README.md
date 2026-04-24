# self-hosted-maps

## Notes

- Static world land fallback data is vendored in `assets/world-land.geojson`. Source and regeneration details live in `docs/world-land.md`.
- Curated U.S. state display-boundary overrides are vendored in `assets/us-state-display-boundary-index.json`. Source and regeneration details live in `docs/us-state-display-boundaries.md`.
- This repo expects LF line endings. Avoid switching the same checkout back and forth between Windows Git and WSL Git; if you need both, use separate clones or worktrees.

## Runtime Configuration

OpenSky can run anonymously, but authenticated REST API access is supported by setting these server-side values in `/etc/self-hosted-maps/self-hosted-maps.runtime.conf`:

```sh
SHM_OPENSKY_CLIENT_ID="your-api-client-id"
SHM_OPENSKY_CLIENT_SECRET="your-api-client-secret"
```

The optional `SHM_OPENSKY_TOKEN_URL` defaults to OpenSky's OAuth2 client-credentials token endpoint. Restart `self-hosted-maps-api` after changing runtime credentials.
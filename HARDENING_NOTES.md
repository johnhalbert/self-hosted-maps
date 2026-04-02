# Hardening notes

A first-pass native scaffold was committed quickly to get the repository moving. The following hardened V2 components were added afterward:

- `installer/lib/ui-v2.sh`
- `scripts/install-runtime-v2.sh`
- `scripts/configure-system-v2.sh`
- `config/nginx-viewer-v2.conf`
- `assets/index-v2.html`

## Why V2 exists

The original scaffold had a few inconsistencies that were easier to address by adding a cleaner path instead of partially rewriting files in place through the connector.

## Main improvements in V2

- warns when the user selects a world import on a small machine
- serves the viewer on port 80 while proxying tile requests through `/tiles/`
- keeps the browser viewer and the tile server on the same origin from the browser's point of view
- points the viewer at `/tiles/data/openmaptiles.json` instead of hard-coding port 8080
- uses a slightly more complete base style with background and water layers

## Suggested install path

Use the existing installer as a base reference, but prefer the V2 runtime/config pair:

- `scripts/install-runtime-v2.sh`
- `scripts/configure-system-v2.sh`
- `installer/lib/ui-v2.sh`

If you want a single fully switched-over V2 entrypoint, the next step is to replace `install.sh` with a V2 version once direct in-place updates are convenient.

# Map Manager Plan

This document turns the dataset-catalog and map-manager idea into a concrete implementation plan for `self-hosted-maps`.

## Goals

- Fetch a live dataset catalog at install time instead of relying only on a hardcoded short list.
- Allow additive dataset installation over time.
- Keep a persistent state file for installed and selected datasets.
- Provide an ncurses map manager for browsing, installing, selecting, rebuilding, and removing datasets.
- Preserve the current simple browser/viewer architecture by rebuilding a single `current` tileset from the selected datasets.

## Recommended model

Use a hybrid model:

1. Install datasets separately.
2. Persist a selected set.
3. Rebuild one merged `current` artifact from the selected datasets.

This keeps the browser simple while allowing additive installs over time.

## Files to add

### Top-level user entrypoints

- `bin/map-manager.sh`
- `bin/rebuild-selected.sh`

### Catalog scripts

- `scripts/catalog/fetch-catalog.sh`
- `scripts/catalog/cache-catalog.sh`
- `scripts/catalog/list-catalog.sh`
- `scripts/catalog/find-dataset.sh`

### Dataset management scripts

- `scripts/datasets/install-dataset.sh`
- `scripts/datasets/remove-dataset.sh`
- `scripts/datasets/list-installed.sh`
- `scripts/datasets/select-datasets.sh`
- `scripts/datasets/set-active-dataset.sh`

### Build scripts

- `scripts/build/merge-pbfs.sh`
- `scripts/build/rebuild-selected.sh`
- `scripts/build/promote-current.sh`

### UI helpers

- `installer/lib/catalog-ui.sh`
- `installer/lib/manager-ui.sh`

### State and templates

- `state/datasets.example.json`
- `state/providers/geofabrik.json`

### Optional docs

- `MAP_MANAGER_PLAN.md`
- `docs/datasets.md`

## Persistent state schema

Recommended live state file:

- `/etc/self-hosted-maps/datasets.json`

Example structure:

```json
{
  "catalog": {
    "provider": "geofabrik",
    "fetched_at": "2026-04-02T21:00:00Z"
  },
  "installed": {
    "louisiana": {
      "id": "louisiana",
      "name": "Louisiana",
      "provider": "geofabrik",
      "download_url": "https://download.geofabrik.de/north-america/us/louisiana-latest.osm.pbf",
      "bounds": [-94.05, 28.14, -88.75, 33.03],
      "pbf_path": "/var/lib/self-hosted-maps/datasets/louisiana/source.osm.pbf",
      "mbtiles_path": "/var/lib/self-hosted-maps/datasets/louisiana/tiles.mbtiles",
      "installed_at": "2026-04-02T21:15:00Z",
      "last_built_at": "2026-04-02T21:20:00Z"
    }
  },
  "selected": [
    "louisiana"
  ],
  "current": {
    "selected_hash": "sha256:example",
    "artifact_path": "/var/lib/self-hosted-maps/current/openmaptiles.mbtiles",
    "rebuilt_at": "2026-04-02T21:20:00Z"
  }
}
```

## Provider catalog shape

Normalize provider entries into a shared shape:

```json
{
  "id": "louisiana",
  "name": "Louisiana",
  "provider": "geofabrik",
  "parent": "us",
  "download_url": "https://download.geofabrik.de/north-america/us/louisiana-latest.osm.pbf",
  "bounds": [-94.05, 28.14, -88.75, 33.03],
  "size_bytes": null
}
```

## Directory layout for additive datasets

```text
/var/lib/self-hosted-maps/
  datasets/
    louisiana/
      source.osm.pbf
      tiles.mbtiles
      metadata.json
    texas/
      source.osm.pbf
      tiles.mbtiles
      metadata.json
  builds/
    merged/
      selected-<hash>/
        merged.osm.pbf
        openmaptiles.mbtiles
  current/
    openmaptiles.mbtiles
```

## Ncurses menu structure

`bin/map-manager.sh` should present this menu:

```text
Self Hosted Maps Manager

1. Browse catalog
2. Install dataset
3. Show installed datasets
4. Select active datasets
5. Rebuild current map
6. Remove dataset
7. Refresh catalog
8. Exit
```

### Menu behaviors

#### 1. Browse catalog
- Show provider datasets in a searchable list.
- Display provider, dataset name, and whether already installed.
- Allow drilling into details.

#### 2. Install dataset
- Select one dataset from the catalog.
- Download its PBF into `/var/lib/self-hosted-maps/datasets/<id>/source.osm.pbf`.
- Update `datasets.json`.
- Optionally prompt to build immediately.

#### 3. Show installed datasets
- Show installed dataset ids, names, sizes, and last build timestamps.

#### 4. Select active datasets
- Use a checklist UI.
- Persist the selected ids to `datasets.json`.
- Do not automatically rebuild unless the user confirms.

#### 5. Rebuild current map
- Merge the selected dataset PBFs.
- Build a new MBTiles artifact.
- Promote atomically into `/var/lib/self-hosted-maps/current/openmaptiles.mbtiles`.
- Restart the tile server.

#### 6. Remove dataset
- Remove one installed dataset from disk and state.
- If it was selected, remove it from `selected`.
- Prompt to rebuild current map.

#### 7. Refresh catalog
- Re-fetch and normalize the provider catalog.
- Update a cached catalog file and timestamp.

## Install-time catalog integration

Replace the current install-time dataset choice flow with:

- `World`
- `Browse provider catalog`
- `Custom PBF URL`

Suggested installer sequence:

1. User chooses world / catalog / custom URL.
2. If catalog, fetch catalog and render a whiptail menu.
3. Resolve selection to a normalized dataset entry.
4. Store that dataset as both installed and selected after bootstrap.

## Implementation notes

### Catalog source
Start with Geofabrik as the first provider. The provider adapter should:

- fetch provider metadata
- normalize it into the shared dataset shape
- cache it locally

### Merge strategy
For the first pass, rebuild from selected PBFs explicitly. Do not rebuild automatically every time a dataset is installed or selected.

### Viewer behavior
Keep the viewer simple. It should continue to read the single `current` MBTiles artifact instead of managing multiple live dataset sources.

## Suggested implementation order

### Phase 1
- Add state file support.
- Add catalog fetch + cache scripts.
- Add map manager UI shell.
- Add dataset install/remove/list flows.

### Phase 2
- Add selected-datasets checklist.
- Add rebuild-current flow.
- Add atomic promotion into `current/`.

### Phase 3
- Hook the installer into the live catalog.
- Add provider abstraction for more than one catalog source.
- Add update checks for installed datasets.

## Minimum viable first implementation

If keeping scope tight, implement these first:

- `bin/map-manager.sh`
- `scripts/catalog/fetch-catalog.sh`
- `scripts/datasets/install-dataset.sh`
- `scripts/datasets/list-installed.sh`
- `scripts/datasets/select-datasets.sh`
- `scripts/build/rebuild-selected.sh`
- `/etc/self-hosted-maps/datasets.json`

That is enough to support:

- browsing a real catalog
- installing multiple datasets over time
- selecting which datasets are active
- rebuilding one current map artifact from those selections

# Datasets

This document describes the dataset lifecycle in `self-hosted-maps`.

## Lifecycle

1. A dataset is discovered from a catalog provider or entered as a custom PBF URL.
2. The dataset is downloaded into:
   - `/var/lib/self-hosted-maps/datasets/<dataset-id>/source.osm.pbf`
3. Metadata is recorded in:
   - `/etc/self-hosted-maps/datasets.json`
4. One or more installed datasets are marked as selected.
5. A rebuild merges the selected dataset inputs and produces the currently served map.
6. The current map is promoted into:
   - `/var/lib/self-hosted-maps/current/openmaptiles.mbtiles`

## Additive installs

Datasets are stored separately so more regions can be added over time.
Installing a dataset does not automatically make it part of the served map unless it is selected and a rebuild is performed.

## Selected vs current

- `selected`: datasets chosen for the next rebuild
- `current.dataset_ids`: datasets that were actually part of the last successful rebuild

This distinction matters because the selected set may change after a rebuild. The served artifact reflects `current.dataset_ids`, not merely the current `selected` list.

## State file structure

Main state file:

- `/etc/self-hosted-maps/datasets.json`

Important sections:

### `.catalog`
Tracks provider catalog cache information.

### `.installed`
Object keyed by dataset id.
Each entry stores fields such as:
- `id`
- `name`
- `provider`
- `parent`
- `download_url`
- `pbf_path`
- `dataset_dir`
- `installed_at`
- `bounds`
- `update_history` (when available)

### `.selected`
Array of dataset ids chosen for the next rebuild.

### `.current`
Tracks the currently served artifact.
Typical fields:
- `selected_hash`
- `artifact_path`
- `rebuilt_at`
- `dataset_ids`

### `.bootstrap`
Tracks the initial installer bootstrap choice.
Typical fields:
- `mode`
- `dataset_id`
- `dataset_name`
- `provider`
- `download_url`
- `completed_at`

### `.ui`
Stores manager UI state such as whether first-run guidance has already been shown.

## Manager commands

Installed launcher commands include:
- `self-hosted-maps-manager`
- `self-hosted-maps-rebuild`
- `self-hosted-maps-refresh-catalog`
- `self-hosted-maps-list-installed`

## Updating datasets

The manager can:
- check for dataset updates
- redownload a dataset
- optionally rebuild if the dataset is selected

Update checks currently use remote metadata such as `Last-Modified` and `Content-Length` when available.

## Rebuild behavior

Rebuilds are explicit.
This keeps additive installs lightweight and avoids rebuilding the served map every time a dataset is added or selected.

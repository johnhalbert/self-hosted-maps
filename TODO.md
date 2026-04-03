# TODO

## Correctness

- Fix installed dataset `current` status reporting in `bin/list-installed.sh` and `bin/show-installed-details.sh`.
  - Right now `current` is inferred from `selected` plus the existence of a current artifact.
  - That can over-report `current` when the selected set changes after the last rebuild.
  - The status should instead be derived from whether the dataset participated in the last successful rebuild.

## Dataset state and rebuild tracking

- Record the exact dataset IDs included in the last successful rebuild in `/etc/self-hosted-maps/datasets.json`.
- Record per-dataset participation in the current served artifact so UI status is precise.
- Consider storing a sorted selected-set snapshot alongside `current.selected_hash` for easier debugging.

## Map manager UX

- Add an installed-dataset update action, not just update checks.
- Add a rebuild confirmation screen that summarizes the selected datasets before rebuild.
- Add a post-install first-run hint inside the manager when only one bootstrap dataset exists.
- Add filtering/search for installed datasets in addition to catalog search.

## Catalog and providers

- Add provider abstraction beyond Geofabrik.
- Normalize provider metadata into a provider-independent schema.
- Consider optional provider-specific dataset size metadata in the catalog cache.

## Documentation

- Add `docs/datasets.md` describing dataset lifecycle, additive installs, selection, rebuilds, and updates.
- Document the stable launcher commands installed by `post-install-discoverability.sh`.
- Document the structure of `/etc/self-hosted-maps/datasets.json` including `.bootstrap`, `.selected`, and `.current`.

## Installer polish

- Add a final install summary that shows the bootstrap dataset by name and id.
- Optionally offer to launch `self-hosted-maps-manager` immediately after install on interactive terminals.
- Consider validating required commands used by the enhanced manager (`column`, `numfmt`, `stat`, `du`) during install.

# TODO

## Initial backlog status

All items from the initial map-manager and installer backlog have been implemented on the `backlog-all-in-one` branch.

Completed areas:

- precise `current` dataset status based on last successful rebuild membership
- recording `current.dataset_ids` in `/etc/self-hosted-maps/datasets.json`
- dataset update action in the manager
- rebuild confirmation summary
- installed-dataset filtering/search
- first-run hint inside the manager
- provider abstraction beyond Geofabrik
- normalized provider-independent catalog entries
- `docs/datasets.md`
- documented launcher commands and state file structure
- final install summary showing bootstrap dataset details
- optional manager launch after install
- install-time validation for manager runtime commands

## Future ideas

These are not blockers for the current implementation, but may be useful later:

- provider-specific dataset size metadata in the normalized catalog cache when reliable size information is available
- richer provider metadata such as display labels or region hierarchy depth
- catalog paging or lazy loading if additional providers make the merged catalog very large

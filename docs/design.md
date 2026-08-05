# YT PocketTube Design

## Current architecture

The standalone, integrity-checked database is the source of the plugin's
bounded playlist-group projection. The separately installed package registers a
YT Library entry point, but YT Library loads it only when explicitly enabled.

## Ownership and source of truth

PocketTube Playlist Manager exports are source artifacts owned by this project.
The SQLite database is the normalized local current-state catalog used by later
integration work. YT Library remains unaware of this schema and will eventually
consume only bounded read-only projections joined by YouTube playlist ID.

## Import model

An import has two phases:

1. Read, hash, parse, normalize, and validate the complete export without
   changing current catalog rows.
2. In one SQLite transaction, replace groups, playlist references, and group
   memberships; record issues and mark the import complete.

The import-run row is created before parsing. A parse or write failure marks the
run failed in a separate transaction while leaving the previous current-state
rows intact.

PocketTube group names are the only stable group identifiers in the observed
export format, so `group_key` retains the exact source name. Parent-child
relationships are validated as a tree. A playlist may belong to multiple
groups; duplicate references within one group keep their first position and
are recorded as import issues.

## Schema

- `schema_migrations` records the standalone schema version.
- `import_runs` records source revision, outcome, counts, and error text.
- `groups` stores the current hierarchy, ordering, and icon values.
- `playlist_references` stores the current distinct YouTube playlist IDs.
- `group_playlists` stores ordered current group membership.
- `import_issues` records skipped or duplicate source values for diagnosis.

Every current-state row points to the successful import that produced it.
SQLite foreign keys and integrity checks are mandatory.

## YT Library integration

The plugin advertises the generic `playlist_groups` capability and implements
`project_playlist_groups()`. The projection contains only:

- a database revision marker;
- ordered groups with plugin-local keys, names, parent keys, and optional icons;
- ordered memberships joined to YT Library by YouTube playlist ID.

The projection is capped at 10,000 groups and 250,000 memberships. Every call
opens and closes its own SQLite connection, and frequent status checks avoid a
full integrity scan. The plugin remains ready against the last successful
catalog if a later import attempt fails, while reporting that failure in its
status.

YT Library validates and namespaces every projected group key before merging
groups into browser bootstrap data. It filters navigation counts to canonical
playlist IDs already in YT Library and uses an explicit ID set for group search.
Unknown playlist references stay visible in this database and are not
fabricated as YT Library rows.

The plugin also exposes bounded, read-only namespaced `status` and `groups`
routes for diagnosis. It provides no browser assets or background workers. It
must never attach this database to YT Library, create cross-database foreign
keys, import YT Library modules, or allow YT Library to migrate or write this
schema.

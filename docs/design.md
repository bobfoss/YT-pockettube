# YT PocketTube Design

## Current milestone

The first milestone ends with a populated, integrity-checked standalone
database. It does not register a YT Library plugin, expose an HTTP API, or add
browser assets.

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

## Deferred integration

The later plugin milestone will define bounded read projections and failure
containment against YT Library's generic plugin contract. It must not attach
this database to YT Library, create cross-database foreign keys, or allow YT
Library to migrate or write this schema.

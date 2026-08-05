# YT PocketTube Design

## Current architecture

The standalone, integrity-checked database is the source of the plugin's
bounded organization projections. The separately installed package registers a
YT Library entry point, but YT Library loads it only when explicitly enabled.

## Ownership and source of truth

PocketTube Playlist Manager and Subscription Manager exports are source
artifacts owned by this project. The SQLite database contains separate
normalized local current-state catalogs for each export type. YT Library remains
unaware of this schema and consumes only bounded read-only projections. The
playlist join key is YouTube playlist ID; the subscription join key is canonical
YouTube channel ID.

## Import model

An import has two phases:

1. Read, hash, parse, normalize, and validate the complete export without
   changing current catalog rows.
2. In one SQLite transaction, replace that source type's groups, canonical
   references, and group memberships; record issues and mark the import
   complete.

The import-run row is created before parsing. A parse or write failure marks the
run failed in a separate transaction while leaving the previous current-state
rows intact.

PocketTube group names are the only stable group identifiers in the observed
formats, so `group_key` retains the exact source name. Parent-child relationships
are validated as a tree. The Subscription Manager's recursively nested
`ysc_settings.sub_groups` structure is preserved, and its split `ysc_meta*`
sections are combined. A playlist or channel may belong to multiple groups;
duplicate references within one group keep their first position and are
recorded as import issues.

## Schema

- `schema_migrations` records the standalone schema version.
- `import_runs` records source revision, outcome, counts, and error text.
- `groups` stores the current hierarchy, ordering, and icon values.
- `playlist_references` stores the current distinct YouTube playlist IDs.
- `group_playlists` stores ordered current group membership.
- `import_issues` records skipped or duplicate source values for diagnosis.
- `subscription_import_runs` independently records Subscription Manager import
  provenance, outcome, counts, and errors.
- `subscription_groups` stores the current nested subscription hierarchy.
- `subscription_channels` stores distinct canonical YouTube channel IDs.
- `subscription_group_channels` stores ordered current channel membership.
- `subscription_import_issues` records skipped or duplicate subscription values.

Every current-state row points to the successful import that produced it.
SQLite foreign keys and integrity checks are mandatory. Schema version 2 adds
the subscription catalog through an in-place migration that preserves all
version 1 playlist data.

## YT Library integration

The plugin advertises the generic `playlist_groups` and `channel_groups`
capabilities and implements `project_playlist_groups()` and
`project_channel_groups()`. Each projection contains only:

- a database revision marker;
- ordered groups with plugin-local keys, names, parent keys, and optional icons;
- ordered memberships joined to YT Library by YouTube playlist or channel ID.

The projection is capped at 10,000 groups and 250,000 memberships. Every call
opens and closes its own SQLite connection, and frequent status checks avoid a
full integrity scan. The plugin remains ready against the last successful
catalog if a later import attempt fails, while reporting that failure in its
status.

YT Library validates and namespaces every projected group key before merging
groups into browser bootstrap data. It filters navigation counts to canonical
playlist IDs already in YT Library and uses an explicit ID set for group search.
Unknown playlist and channel references stay visible in this database and are
not fabricated as YT Library rows.

The plugin also exposes bounded, read-only namespaced `status`, `groups`, and
`channel-groups` routes for diagnosis. It provides no browser assets or
background workers. It
must never attach this database to YT Library, create cross-database foreign
keys, import YT Library modules, or allow YT Library to migrate or write this
schema.

Subscription groups are projected through the host's domain-neutral channel
group contract and join only by canonical channel ID. Playlist and subscription
catalog readiness is independent, so a missing or failed first import for one
domain does not disable the other.

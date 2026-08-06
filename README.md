# YT PocketTube

YT PocketTube is a standalone local catalog and optional YT Library plugin for
PocketTube Playlist Manager and Subscription Manager exports. It owns the
SQLite database and atomic import paths, then exposes bounded, read-only
playlist-group and channel-group projections to YT Library.

## Data ownership

PocketTube exports and `yt_pockettube.sqlite3` are private runtime data and are
ignored by Git. The database stores independent normalized current catalogs for
playlist groups and subscription groups, plus separate audit trails of import
attempts. A failed parse or database write does not replace the last successful
catalog of either type.

## Configuration

Copy `yt_pockettube.config.example.json` to the ignored
`yt_pockettube.config.json`, set `export` to a PocketTube Playlist Manager JSON
export, and set `subscription_export` to a PocketTube Subscription Manager JSON
export. `exports_directory` is the local directory scanned by the YT Library
Admin action. Relative paths are resolved from the configuration file's
directory.

```json
{
  "database": "yt_pockettube.sqlite3",
  "exports_directory": "exports",
  "export": "exports/youtube_playlist_manager.json",
  "subscription_export": "exports/youtube_subscription_manager.json"
}
```

## Commands

Use the YT Library virtual environment:

```powershell
$python = "C:\Users\michael.keenan\personal\YT Library\.venv\Scripts\python.exe"
& $python -m yt_pockettube init
& $python -m yt_pockettube import
& $python -m yt_pockettube import-subscriptions
& $python -m yt_pockettube status
```

`import` reads and validates the complete export before opening the replacement
transaction. It reports normalized group, membership, playlist, and issue
counts as JSON.

`import-subscriptions` independently replaces subscription groups, canonical
channel references, and group memberships. It supports the Subscription
Manager's nested group hierarchy and split metadata sections. Playlist catalog
rows are not changed by a subscription import.

## YT Library plugin

Install this project into the YT Library virtual environment, then add an
explicit activation entry to YT Library's ignored local configuration:

```powershell
$python = "C:\Users\michael.keenan\personal\YT Library\.venv\Scripts\python.exe"
& $python -m pip install -e "C:\Users\michael.keenan\personal\YT PocketTube"
```

```json
{
  "plugins": {
    "pockettube": {
      "enabled": true,
      "config": "../YT PocketTube/yt_pockettube.config.json"
    }
  }
}
```

When the plugin is ready, PocketTube groups appear in YT Library's playlist and
channel navigation. YT Library namespaces the group keys and resolves membership
only against canonical playlists and channels already in its own database.
References that are not in YT Library remain in this catalog; the plugin does
not fabricate or import YT Library rows.

The playlist projection also declares a derived `Uncategorized` root. YT
Library's generic plugin host places canonical playlists there only when no
explicit PocketTube group contains their IDs. The rule and label are owned by
this plugin, so the root appears beneath the collapsible `PocketTube` parent and
disappears entirely when the plugin is disabled. YT PocketTube still receives
only the canonical ID set supplied through the versioned host contract and
never opens the YT Library database.

The plugin advertises the generic `playlist_groups` and `channel_groups`
capabilities. Each catalog remains independently usable when the other has no
successful import. Its **Fetch PocketTube exports** Advanced Admin
action scans `exports_directory` for standard Playlist Manager and Subscription
Manager JSON filenames and imports content hashes not already present in the
corresponding successful PocketTube import history. Failed imports remain
eligible for a later retry. This is a local filesystem operation; it does not
download exports from PocketTube or YouTube. Multiple new snapshots of one type
are applied oldest to newest so the newest snapshot becomes current.

The plugin has no browser asset, never opens the YT Library database, and does
not expose export paths or source hashes through status. Its
namespaced `status`, `groups`, and `channel-groups` API routes are read-only
diagnostics.

## Development

```powershell
$python = "C:\Users\michael.keenan\personal\YT Library\.venv\Scripts\python.exe"
& $python -m py_compile (Get-ChildItem yt_pockettube,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
& $python -m unittest discover -s tests -v
& $python -m ruff check .
git diff --check
```

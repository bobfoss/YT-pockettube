# YT PocketTube

YT PocketTube is a standalone local catalog and optional YT Library plugin for
PocketTube Playlist Manager exports. It owns the SQLite database and atomic
import path, then exposes a bounded, read-only playlist-group projection to YT
Library.

## Data ownership

PocketTube exports and `yt_pockettube.sqlite3` are private runtime data and are
ignored by Git. The database stores normalized current group organization plus
an audit trail of import attempts. A failed parse or database write does not
replace the last successful catalog.

## Configuration

Copy `yt_pockettube.config.example.json` to the ignored
`yt_pockettube.config.json` and set `export` to a PocketTube Playlist Manager
JSON export. Relative paths are resolved from the configuration file's
directory.

```json
{
  "database": "yt_pockettube.sqlite3",
  "export": "exports/youtube_playlist_manager.json"
}
```

## Commands

Use the YT Library virtual environment:

```powershell
$python = "C:\Users\michael.keenan\personal\YT Library\.venv\Scripts\python.exe"
& $python -m yt_pockettube init
& $python -m yt_pockettube import
& $python -m yt_pockettube status
```

`import` reads and validates the complete export before opening the replacement
transaction. It reports normalized group, membership, playlist, and issue
counts as JSON.

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

When the plugin is ready, PocketTube groups appear in YT Library's playlist
navigation. YT Library namespaces the group keys and resolves membership only
against canonical playlists already in its own database. Playlist references
that are not in YT Library remain in this catalog; the plugin does not fabricate
or import YT Library rows.

The plugin advertises only the generic `playlist_groups` capability. It has no
browser asset or worker process, never opens the YT Library database, and does
not expose export paths or source hashes through status. Its namespaced
`status` and `groups` API routes are read-only diagnostics.

## Development

```powershell
$python = "C:\Users\michael.keenan\personal\YT Library\.venv\Scripts\python.exe"
& $python -m py_compile (Get-ChildItem yt_pockettube,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
& $python -m unittest discover -s tests -v
& $python -m ruff check .
git diff --check
```

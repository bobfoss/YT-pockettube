# YT PocketTube

YT PocketTube is a standalone local catalog for PocketTube Playlist Manager
exports. The current milestone establishes the plugin-owned SQLite database and
an atomic import path. YT Library plugin entry points, APIs, and browser UI are
deliberately out of scope until the imported data has been validated.

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

## Development

```powershell
$python = "C:\Users\michael.keenan\personal\YT Library\.venv\Scripts\python.exe"
& $python -m py_compile (Get-ChildItem yt_pockettube,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
& $python -m unittest discover -s tests -v
& $python -m ruff check .
git diff --check
```

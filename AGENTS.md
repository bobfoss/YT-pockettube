# Repository Guidelines

Read this file at the start of every chat in this repository. This is the
standalone PocketTube data project intended to become an optional YT Library
plugin after its storage and import behavior are proven.

## Working Agreement

- Prefer Python and the standard library where practical.
- Inspect `git status` before editing and preserve unrelated work.
- Keep PocketTube exports, the local database, local configuration, logs, and
  backups out of Git. Test fixtures must be anonymized.
- This project owns its data model, schema, migrations, configuration, caches,
  and source artifacts. It must not import YT Library modules, access the YT
  Library database, or add PocketTube domain tables to YT Library.
- Imports are current-state replacements. Parse and validate the entire source
  before replacing rows, perform replacement atomically, and preserve the last
  successful catalog if a later import fails.
- Store exact timestamps in UTC using ISO 8601 with `Z`.
- Treat playlist IDs, group names, filenames, and URLs as shell-hostile.
- Commit each coherent, verified change with a substantive body. Push only when
  explicitly requested.

## Verification

Reuse the YT Library virtual environment; do not create a separate environment
or invoke bare `python`:

```powershell
$python = "C:\Users\michael.keenan\personal\YT Library\.venv\Scripts\python.exe"
& $python -m py_compile (Get-ChildItem yt_pockettube,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
& $python -m unittest discover -s tests -v
& $python -m ruff check .
git diff --check
```

This project has no `ENVIRONMENT.md`.

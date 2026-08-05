PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_runs (
  import_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_path TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_mtime_ns INTEGER,
  source_size INTEGER,
  source_sha256 TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
  group_count INTEGER NOT NULL DEFAULT 0 CHECK (group_count >= 0),
  membership_count INTEGER NOT NULL DEFAULT 0 CHECK (membership_count >= 0),
  playlist_count INTEGER NOT NULL DEFAULT 0 CHECK (playlist_count >= 0),
  issue_count INTEGER NOT NULL DEFAULT 0 CHECK (issue_count >= 0),
  error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS groups (
  group_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  parent_key TEXT REFERENCES groups(group_key) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK (position >= 0),
  icon TEXT NOT NULL DEFAULT '',
  import_id INTEGER NOT NULL REFERENCES import_runs(import_id)
);

CREATE TABLE IF NOT EXISTS playlist_references (
  playlist_id TEXT PRIMARY KEY,
  import_id INTEGER NOT NULL REFERENCES import_runs(import_id)
);

CREATE TABLE IF NOT EXISTS group_playlists (
  group_key TEXT NOT NULL REFERENCES groups(group_key) ON DELETE CASCADE,
  playlist_id TEXT NOT NULL REFERENCES playlist_references(playlist_id) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK (position >= 0),
  source_value TEXT NOT NULL,
  import_id INTEGER NOT NULL REFERENCES import_runs(import_id),
  PRIMARY KEY (group_key, playlist_id)
);

CREATE TABLE IF NOT EXISTS import_issues (
  issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_id INTEGER NOT NULL REFERENCES import_runs(import_id) ON DELETE CASCADE,
  severity TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
  kind TEXT NOT NULL,
  group_key TEXT NOT NULL DEFAULT '',
  source_position INTEGER,
  source_value TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscription_import_runs (
  import_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_path TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_mtime_ns INTEGER,
  source_size INTEGER,
  source_sha256 TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
  group_count INTEGER NOT NULL DEFAULT 0 CHECK (group_count >= 0),
  membership_count INTEGER NOT NULL DEFAULT 0 CHECK (membership_count >= 0),
  channel_count INTEGER NOT NULL DEFAULT 0 CHECK (channel_count >= 0),
  issue_count INTEGER NOT NULL DEFAULT 0 CHECK (issue_count >= 0),
  error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS subscription_groups (
  group_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  parent_key TEXT REFERENCES subscription_groups(group_key) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK (position >= 0),
  icon TEXT NOT NULL DEFAULT '',
  import_id INTEGER NOT NULL REFERENCES subscription_import_runs(import_id)
);

CREATE TABLE IF NOT EXISTS subscription_channels (
  channel_id TEXT PRIMARY KEY,
  import_id INTEGER NOT NULL REFERENCES subscription_import_runs(import_id)
);

CREATE TABLE IF NOT EXISTS subscription_group_channels (
  group_key TEXT NOT NULL REFERENCES subscription_groups(group_key) ON DELETE CASCADE,
  channel_id TEXT NOT NULL REFERENCES subscription_channels(channel_id) ON DELETE CASCADE,
  position INTEGER NOT NULL CHECK (position >= 0),
  source_value TEXT NOT NULL,
  import_id INTEGER NOT NULL REFERENCES subscription_import_runs(import_id),
  PRIMARY KEY (group_key, channel_id)
);

CREATE TABLE IF NOT EXISTS subscription_import_issues (
  issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_id INTEGER NOT NULL REFERENCES subscription_import_runs(import_id) ON DELETE CASCADE,
  severity TEXT NOT NULL CHECK (severity IN ('warning', 'error')),
  kind TEXT NOT NULL,
  group_key TEXT NOT NULL DEFAULT '',
  source_position INTEGER,
  source_value TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_groups_parent_position
  ON groups(parent_key, position, group_key);
CREATE INDEX IF NOT EXISTS idx_group_playlists_group_position
  ON group_playlists(group_key, position, playlist_id);
CREATE INDEX IF NOT EXISTS idx_group_playlists_playlist
  ON group_playlists(playlist_id, group_key);
CREATE INDEX IF NOT EXISTS idx_import_runs_started
  ON import_runs(started_at DESC, import_id DESC);
CREATE INDEX IF NOT EXISTS idx_import_issues_import
  ON import_issues(import_id, issue_id);
CREATE INDEX IF NOT EXISTS idx_subscription_groups_parent_position
  ON subscription_groups(parent_key, position, group_key);
CREATE INDEX IF NOT EXISTS idx_subscription_group_channels_group_position
  ON subscription_group_channels(group_key, position, channel_id);
CREATE INDEX IF NOT EXISTS idx_subscription_group_channels_channel
  ON subscription_group_channels(channel_id, group_key);
CREATE INDEX IF NOT EXISTS idx_subscription_import_runs_started
  ON subscription_import_runs(started_at DESC, import_id DESC);
CREATE INDEX IF NOT EXISTS idx_subscription_import_issues_import
  ON subscription_import_issues(import_id, issue_id);

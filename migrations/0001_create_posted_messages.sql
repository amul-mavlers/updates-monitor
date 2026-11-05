-- Messages the bot has posted to Google Chat. Written through the Worker's /api/events endpoint,
-- read by the landing page ("Recent activity"). Rows older than 90 days are removed by the Worker.
CREATE TABLE IF NOT EXISTS posted_messages (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  item_key  TEXT NOT NULL UNIQUE,       -- feed name | item key: makes a resent batch harmless
  posted_at TEXT NOT NULL,              -- ISO 8601, UTC
  source    TEXT NOT NULL,
  kind      TEXT NOT NULL,              -- e.g. "Resolved after 41 min", "New post"
  category  TEXT NOT NULL,              -- incidents, maintenance, security, news
  title     TEXT NOT NULL,
  spaces    TEXT NOT NULL,              -- comma separated: News, Downtime, WordPress & PHP
  text      TEXT NOT NULL,              -- the full message as sent to Chat
  link      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_posted_messages_posted_at ON posted_messages (posted_at DESC);

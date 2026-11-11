-- Task owners come from the app's config (AOS_OWNERS, see lib/config.ts) instead of a fixed list in the database.
-- Any lowercase slug is allowed, the same rule as lib/config.ts OWNER_RE; the app checks the configured list.
-- Existing rows keep their owners (every earlier owner value matches the new rule). The column default is left as it
-- is, so a database created before this migration keeps behaving the same; the app always sets owner explicitly.
alter table tasks drop constraint if exists tasks_owner_check;
alter table tasks add constraint tasks_owner_check check (owner ~ '^[a-z][a-z0-9_-]{0,39}$');

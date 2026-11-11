-- Registry of live sandboxes. `id` is the sandbox id (sha256 of the session
-- token, equal to the session-store key). A future sweeper purges sandboxes
-- whose last_seen is older than the absolute session lifetime.
create table sandboxes (
  id text primary key,
  created_at timestamptz not null default now(),
  last_seen timestamptz not null default now()
);

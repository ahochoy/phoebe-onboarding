-- Chat history per sandbox (session_id is the sandbox id) and app-level metadata.
create table chat_turns (
  id uuid primary key default gen_random_uuid(),
  session_id text not null,
  created_at timestamptz not null default now(),
  role text not null check (role in ('user', 'assistant')),
  text text not null,
  citations jsonb not null default '[]',
  refused boolean not null default false
);
create index chat_turns_session_idx on chat_turns (session_id, created_at);

create table app_meta (
  key text primary key,
  value text not null
);

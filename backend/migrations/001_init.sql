create extension if not exists vector;
create table schema_migrations (name text primary key, applied_at timestamptz not null default now());
create table groups (
  id text primary key, name text not null,
  kind text not null check (kind in ('company','department','team')),
  parent_id text references groups(id), session_id text,
  check ((kind = 'company') = (parent_id is null)));
create table people (
  id text primary key, name text not null, team_id text not null references groups(id),
  start_date date not null, manager text, buddy text);
create table documents (
  id uuid primary key default gen_random_uuid(), session_id text,
  title text not null, purpose text not null default '', last_updated date,
  doc_type text not null check (doc_type in ('pdf','markdown','csv','web','google_doc')),
  group_id text not null references groups(id), source_uri text not null,
  public_url text,
  status text not null default 'processing' check (status in ('processing','indexed','failed')),
  failure_reason text, full_text text, sections jsonb, created_at timestamptz not null default now());
create table chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references documents(id) on delete cascade,
  ordinal int not null, heading_path text not null, text text not null,
  start_offset int not null, end_offset int not null, embedding vector(1024) not null,
  tsv tsvector generated always as (to_tsvector('english', heading_path || ' ' || text)) stored);
create index chunks_tsv_idx on chunks using gin (tsv);
create index chunks_doc_idx on chunks (document_id);
create table tasks (
  id uuid primary key default gen_random_uuid(), session_id text,
  title text not null, description text not null default '', link text,
  group_id text not null references groups(id), position int not null default 0);
create table task_completions (
  person_id text not null references people(id), task_id uuid not null references tasks(id) on delete cascade,
  session_id text not null default '', done boolean not null, at timestamptz not null default now(),
  primary key (person_id, task_id, session_id));  -- '' = seed
create table overrides (
  session_id text not null, entity_kind text not null check (entity_kind in ('document','task','group')),
  entity_id text not null, hidden boolean not null default false, patch jsonb not null default '{}',
  primary key (session_id, entity_kind, entity_id));
create index documents_session_idx on documents (session_id);
create index tasks_session_idx on tasks (session_id);

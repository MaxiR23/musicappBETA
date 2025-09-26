-- 1) Enums
create type app_event_type  as enum ('search','play','like','unlike');
create type app_entity_type as enum ('query','track','album','artist','playlist');

-- 2) Tabla
create table public.user_activity (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  event_type    app_event_type  not null,
  entity_type   app_entity_type not null,
  entity_id     text,                 -- id interno o YT id; null para 'query'
  context_type  app_entity_type,      -- p.ej. 'album' si el play viene desde un álbum
  context_id    text,
  metadata      jsonb not null default '{}'::jsonb, -- { "query": "...", "track_title": "...", ... }
  occurred_at   timestamptz not null default now()
);

-- 3) Índices útiles
create index ua_user_time_idx   on public.user_activity (user_id, occurred_at desc);
create index ua_user_entity_idx on public.user_activity (user_id, entity_type, occurred_at desc);
create index ua_user_event_idx  on public.user_activity (user_id, event_type, occurred_at desc);

-- 4) RLS
alter table public.user_activity enable row level security;

-- Sólo el dueño lee sus filas
create policy "ua_select_own"
on public.user_activity
for select
using (auth.uid() = user_id);

-- Sólo el dueño inserta sus filas
create policy "ua_insert_own"
on public.user_activity
for insert
with check (auth.uid() = user_id);

-- (opcional) permitir update/delete propias
create policy "ua_update_own"
on public.user_activity
for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "ua_delete_own"
on public.user_activity
for delete
using (auth.uid() = user_id);
create table public.user_activity (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  event_type public.app_event_type not null,
  entity_type public.app_entity_type not null,
  entity_id text null,
  context_type public.app_entity_type null,
  context_id text null,
  metadata jsonb not null default '{}'::jsonb,
  occurred_at timestamp with time zone not null default now(),
  play_count integer not null default 1,
  constraint user_activity_pkey primary key (id),
  constraint user_activity_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists ua_user_time_idx on public.user_activity using btree (user_id, occurred_at desc) TABLESPACE pg_default;

create index IF not exists ua_user_event_idx on public.user_activity using btree (user_id, event_type, occurred_at desc) TABLESPACE pg_default;

create index IF not exists ua_user_entity_idx on public.user_activity using btree (user_id, entity_type, occurred_at desc) TABLESPACE pg_default;
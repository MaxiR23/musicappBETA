create table public.user_weekly_stats (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  week_start date not null,
  entity_type public.app_entity_type not null,
  stats jsonb not null default '[]'::jsonb,
  created_at timestamp with time zone not null default now(),
  constraint user_weekly_stats_pkey primary key (id),
  constraint user_weekly_stats_unique unique (user_id, week_start, entity_type),
  constraint user_weekly_stats_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists uws_user_week_idx on public.user_weekly_stats using btree (user_id, week_start desc) TABLESPACE pg_default;

create index IF not exists uws_user_type_idx on public.user_weekly_stats using btree (user_id, entity_type, week_start desc) TABLESPACE pg_default;
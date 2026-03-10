create table public.user_monthly_stats (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  month date not null,
  entity_type public.app_entity_type not null,
  stats jsonb not null default '[]'::jsonb,
  created_at timestamp with time zone not null default now(),
  constraint user_monthly_stats_pkey primary key (id),
  constraint user_monthly_stats_unique unique (user_id, month, entity_type),
  constraint user_monthly_stats_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists ums_user_month_idx on public.user_monthly_stats using btree (user_id, month desc) TABLESPACE pg_default;

create index IF not exists ums_user_type_idx on public.user_monthly_stats using btree (user_id, entity_type, month desc) TABLESPACE pg_default;
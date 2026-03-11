create table public.user_recommendations (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  bucket text not null,
  item_type public.app_entity_type not null,
  item_id text not null,
  rank smallint not null,
  seed_type public.app_entity_type null,
  seed_id text null,
  seed_name text null,
  seed_thumb text null,
  payload jsonb not null default '{}'::jsonb,
  source text null,
  generated_at timestamp with time zone not null default now(),
  valid_until timestamp with time zone null,
  constraint user_recommendations_pkey primary key (id),
  constraint user_recommendations_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists user_recommendations_list_idx on public.user_recommendations using btree (user_id, bucket, rank) TABLESPACE pg_default;

create index IF not exists user_recommendations_valid_idx on public.user_recommendations using btree (valid_until) TABLESPACE pg_default;

create unique INDEX IF not exists user_recommendations_unique on public.user_recommendations using btree (user_id, bucket, item_type, item_id) TABLESPACE pg_default;

create index IF not exists user_recommendations_type_idx on public.user_recommendations using btree (user_id, bucket, item_type, rank) TABLESPACE pg_default;
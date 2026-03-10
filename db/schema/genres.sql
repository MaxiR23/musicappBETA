create table public.genres (
  id uuid not null default gen_random_uuid (),
  name text not null,
  slug text not null,
  description text null,
  sort_order integer not null default 0,
  created_at timestamp with time zone null default now(),
  constraint genres_pkey primary key (id),
  constraint genres_name_key unique (name),
  constraint genres_slug_key unique (slug)
) TABLESPACE pg_default;
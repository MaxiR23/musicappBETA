create table public.upcoming_releases (
  id uuid not null default gen_random_uuid (),
  artist_name text not null,
  artist_id text null,
  album_name text not null,
  release_date date null,
  is_tba boolean null default false,
  label text null,
  thumbnail_url text null,
  track_count integer null,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint upcoming_releases_pkey primary key (id)
) TABLESPACE pg_default;

create index IF not exists idx_upcoming_releases_date on public.upcoming_releases using btree (release_date) TABLESPACE pg_default
where
  (release_date is not null);

create index IF not exists idx_upcoming_releases_tba on public.upcoming_releases using btree (is_tba) TABLESPACE pg_default
where
  (is_tba = true);

create index IF not exists idx_upcoming_releases_artist_name on public.upcoming_releases using btree (artist_name) TABLESPACE pg_default;

create trigger releases_updated_at BEFORE
update on upcoming_releases for EACH row
execute FUNCTION update_updated_at ();
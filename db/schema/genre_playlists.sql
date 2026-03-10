create table public.genre_playlists (
  id uuid not null default gen_random_uuid (),
  genre_id uuid not null,
  title text not null,
  description text null,
  thumbnail_url text null,
  sort_order integer not null default 0,
  track_count integer null default 0,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  category text null,
  constraint genre_playlists_pkey primary key (id),
  constraint genre_playlists_genre_id_fkey foreign KEY (genre_id) references genres (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_genre_playlists_genre_id on public.genre_playlists using btree (genre_id) TABLESPACE pg_default;

create index IF not exists idx_genre_playlists_sort_order on public.genre_playlists using btree (sort_order) TABLESPACE pg_default;

create trigger update_genre_playlists_updated_at BEFORE
update on genre_playlists for EACH row
execute FUNCTION update_updated_at_column ();
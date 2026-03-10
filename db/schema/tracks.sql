create table public.tracks (
  id uuid not null default gen_random_uuid (),
  track_id text not null,
  title text null,
  artist text null,
  album text null,
  duration_seconds integer null,
  thumbnail_url text null,
  extra jsonb null,
  artist_id text null,
  album_id text null,
  constraint tracks_pkey primary key (id),
  constraint tracks_track_id_key unique (track_id)
) TABLESPACE pg_default;
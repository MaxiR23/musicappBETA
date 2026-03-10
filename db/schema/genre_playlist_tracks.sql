create table public.genre_playlist_tracks (
  id uuid not null default gen_random_uuid (),
  playlist_id uuid not null,
  track_id text not null,
  position integer not null,
  added_at timestamp with time zone null default now(),
  constraint genre_playlist_tracks_pkey primary key (id),
  constraint unique_playlist_position unique (playlist_id, "position"),
  constraint unique_playlist_track unique (playlist_id, track_id),
  constraint genre_playlist_tracks_playlist_id_fkey foreign KEY (playlist_id) references genre_playlists (id) on delete CASCADE,
  constraint genre_playlist_tracks_track_id_fkey foreign KEY (track_id) references tracks (track_id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists idx_genre_playlist_tracks_playlist_id on public.genre_playlist_tracks using btree (playlist_id) TABLESPACE pg_default;

create index IF not exists idx_genre_playlist_tracks_track_id on public.genre_playlist_tracks using btree (track_id) TABLESPACE pg_default;

create index IF not exists idx_genre_playlist_tracks_position on public.genre_playlist_tracks using btree (playlist_id, "position") TABLESPACE pg_default;

create trigger trigger_update_genre_playlist_track_count
after INSERT
or DELETE on genre_playlist_tracks for EACH row
execute FUNCTION update_genre_playlist_track_count ();
create table public.playlist_tracks (
  playlist_id uuid not null,
  track_id uuid not null,
  position integer not null,
  added_by uuid null,
  added_at timestamp with time zone null default now(),
  id uuid not null default gen_random_uuid (),
  constraint playlist_tracks_pkey primary key (id),
  constraint ux_playlist_pos unique (playlist_id, "position") deferrable initially DEFERRED,
  constraint playlist_tracks_added_by_fkey foreign KEY (added_by) references auth.users (id),
  constraint playlist_tracks_playlist_id_fkey foreign KEY (playlist_id) references playlists (id) on delete CASCADE,
  constraint playlist_tracks_track_id_fkey foreign KEY (track_id) references tracks (id) on delete RESTRICT
) TABLESPACE pg_default;

create index IF not exists idx_playlisttracks_playlist_pos on public.playlist_tracks using btree (playlist_id, "position") TABLESPACE pg_default;

create trigger trg_playlist_tracks_reorder BEFORE INSERT
or DELETE
or
update on playlist_tracks for EACH row
execute FUNCTION playlist_tracks_reorder ();
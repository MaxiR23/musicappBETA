create table public.play_events (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  track_id text not null,
  played_at timestamp with time zone not null default now(),
  metadata jsonb not null default '{}'::jsonb,
  constraint play_events_pkey primary key (id),
  constraint play_events_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;

create index IF not exists pe_user_time_idx on public.play_events using btree (user_id, played_at desc) TABLESPACE pg_default;

create index IF not exists pe_user_track_idx on public.play_events using btree (user_id, track_id) TABLESPACE pg_default;
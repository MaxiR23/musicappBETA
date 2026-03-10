create table public.playlists (
  id uuid not null default gen_random_uuid (),
  owner_id uuid not null,
  title text not null,
  description text null,
  is_public boolean null default false,
  created_at timestamp with time zone null default now(),
  updated_at timestamp with time zone null default now(),
  constraint playlists_pkey primary key (id),
  constraint playlists_owner_id_fkey foreign KEY (owner_id) references auth.users (id) on delete CASCADE
) TABLESPACE pg_default;
create table public.recent_activity (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  entity_type text not null,
  entity_id text not null,
  metadata jsonb not null default '{}'::jsonb,
  played_at timestamp with time zone not null default now(),
  constraint recent_activity_pkey primary key (id),
  constraint recent_activity_unique unique (user_id, entity_type, entity_id),
  constraint recent_activity_user_id_fkey foreign KEY (user_id) references auth.users (id) on delete CASCADE,
  constraint recent_activity_entity_type_check check (
    (
      entity_type = any (
        array['album'::text, 'artist'::text, 'playlist'::text]
      )
    )
  )
) TABLESPACE pg_default;

create index IF not exists ra_user_recent_idx on public.recent_activity using btree (user_id, played_at desc) TABLESPACE pg_default;
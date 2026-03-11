create table public.feed_current (
  uid uuid not null default gen_random_uuid (),
  kind public.feed_kind not null,
  type public.media_type not null,
  id text not null,
  title text not null,
  artist text not null,
  artist_id text null,
  album text null,
  album_id text null,
  duration_seconds integer null,
  year text null,
  thumb text null,
  url text null,
  release_date text null,
  constraint feed_current_pkey primary key (uid)
) TABLESPACE pg_default;

create unique INDEX IF not exists uniq_feed_current_kind_type_id on public.feed_current using btree (kind, type, id) TABLESPACE pg_default;

create index IF not exists idx_feed_current_kind_type on public.feed_current using btree (kind, type) TABLESPACE pg_default;

create index IF not exists idx_feed_current_release on public.feed_current using btree (release_date desc) TABLESPACE pg_default;
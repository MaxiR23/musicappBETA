-- Reutilizamos tus enums existentes
-- app_entity_type ya contiene 'artist' y 'album' (entre otros)

-- Tabla única y genérica para recomendaciones por usuario
create table if not exists public.user_recommendations (
  id            uuid primary key default gen_random_uuid(),

  -- Quién
  user_id       uuid not null
                  references auth.users(id) on delete cascade,

  -- Bucket/segmento (p.ej. 'seed_recos_v1', 'weekly_2025w41')
  bucket        text not null,

  -- Ítem recomendado
  item_type     public.app_entity_type not null,  -- 'artist' | 'album'
  item_id       text not null,
  rank          smallint not null,                -- orden 1..N

  -- “Similar to …” (opcional; útil para front)
  seed_type     public.app_entity_type null,      -- normalmente 'artist'
  seed_id       text null,
  seed_name     text null,
  seed_thumb    text null,

  -- Metadatos flexibles (name/title/subtitle/thumbnails/artistName/etc.)
  payload       jsonb not null default '{}'::jsonb,

  -- Auditoría / vigencia
  source        text null,                        -- ej: 'seed_recos_v1'
  generated_at  timestamptz not null default now(),
  valid_until   timestamptz null                  -- ej: now() + interval '7 days'
);

-- Unicidad por usuario + bucket + item → perfecto para upsert/replace
create unique index if not exists user_recommendations_unique
  on public.user_recommendations (user_id, bucket, item_type, item_id);

-- Listado ordenado por bucket
create index if not exists user_recommendations_list_idx
  on public.user_recommendations (user_id, bucket, rank asc);

-- Filtrado por tipo dentro del bucket
create index if not exists user_recommendations_type_idx
  on public.user_recommendations (user_id, bucket, item_type, rank asc);

-- Limpieza por vencimiento
create index if not exists user_recommendations_valid_idx
  on public.user_recommendations (valid_until);

Notas rápidas
DRY: una sola tabla para artistas y álbumes; el payload guarda lo que venga (p. ej. {"name": "...", "thumbnails": [...], "artistName": "..."}).

“Similar to …” listo para el front: seed_name y seed_thumb están en columnas planas (no necesitas abrir JSON).

Bucket te deja versionar/rotar: por ejemplo seed_recos_v1 semanal; cuando refrescás, hacés un DELETE + INSERT por (user_id, bucket) o UPSERT por la unique.

Orden con rank (1..N).

valid_until te permite expirar semanalmente y limpiar fácil.

Si querés, en el próximo paso te paso un replace_user_recommendations(user_id, bucket, items) en Python que haga delete → insert de forma idempotente.
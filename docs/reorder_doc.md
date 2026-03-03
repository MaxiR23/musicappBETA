# Playlist Track Reorder - Documentacion Tecnica

## Resumen

Sistema de reordenamiento de tracks en playlists usando una funcion RPC de PostgreSQL con constraints deferrable para evitar violaciones de unicidad durante el reorden.

---

## Cambios en Base de Datos (Supabase)

### 1. Constraint Eliminado

Se elimino el constraint NOT deferrable que causaba violaciones de unicidad:

```sql
ALTER TABLE playlist_tracks DROP CONSTRAINT playlist_tracks_unique_pos;
```

### 2. Constraint Activo

Queda activo el constraint deferrable que permite posiciones duplicadas temporalmente dentro de una transaccion:

```sql
CONSTRAINT ux_playlist_pos UNIQUE (playlist_id, "position") DEFERRABLE INITIALLY DEFERRED
```

### 3. Funcion RPC: `move_playlist_track`

```sql
CREATE OR REPLACE FUNCTION move_playlist_track(
  p_playlist_id UUID,
  p_old_index INT,
  p_new_index INT
)
RETURNS JSON
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_total INT;
  v_rows JSON;
  v_row RECORD;
  v_idx INT;
BEGIN
  -- Defer constraint para permitir posiciones temporales duplicadas
  SET CONSTRAINTS ux_playlist_pos DEFERRED;

  -- Contar tracks
  SELECT COUNT(*) INTO v_total
  FROM playlist_tracks
  WHERE playlist_id = p_playlist_id;

  IF v_total = 0 THEN
    RETURN json_build_object('ok', false, 'error', 'empty_playlist');
  END IF;

  -- Clamp indices
  IF p_old_index < 1 THEN p_old_index := 1; END IF;
  IF p_old_index > v_total THEN p_old_index := v_total; END IF;
  IF p_new_index < 1 THEN p_new_index := 1; END IF;
  IF p_new_index > v_total THEN p_new_index := v_total; END IF;

  -- Noop
  IF p_old_index = p_new_index THEN
    SELECT json_agg(row_to_json(t) ORDER BY t.position)
    INTO v_rows
    FROM (
      SELECT id AS "internalId", track_id AS "track_id", position
      FROM playlist_tracks
      WHERE playlist_id = p_playlist_id
      ORDER BY position
    ) t;
    
    RETURN json_build_object('ok', true, 'noop', true, 'order', v_rows);
  END IF;

  -- Crear tabla temporal con el orden actual
  CREATE TEMP TABLE tmp_reorder AS
  SELECT id, track_id, ROW_NUMBER() OVER (ORDER BY position) AS rn
  FROM playlist_tracks
  WHERE playlist_id = p_playlist_id;

  -- Mover a posiciones negativas temporales (basadas en el nuevo orden)
  IF p_new_index < p_old_index THEN
    -- Mover hacia arriba: el movido va a new_index, los demas bajan
    UPDATE playlist_tracks pt
    SET position = CASE
      WHEN t.rn = p_old_index THEN -p_new_index
      WHEN t.rn >= p_new_index AND t.rn < p_old_index THEN -(t.rn + 1)
      ELSE -t.rn
    END
    FROM tmp_reorder t
    WHERE pt.id = t.id;
  ELSE
    -- Mover hacia abajo: el movido va a new_index, los demas suben
    UPDATE playlist_tracks pt
    SET position = CASE
      WHEN t.rn = p_old_index THEN -p_new_index
      WHEN t.rn > p_old_index AND t.rn <= p_new_index THEN -(t.rn - 1)
      ELSE -t.rn
    END
    FROM tmp_reorder t
    WHERE pt.id = t.id;
  END IF;

  -- Convertir posiciones negativas a positivas
  UPDATE playlist_tracks
  SET position = -position
  WHERE playlist_id = p_playlist_id AND position < 0;

  -- Limpiar
  DROP TABLE tmp_reorder;

  -- Devolver orden final
  SELECT json_agg(row_to_json(t) ORDER BY t.position)
  INTO v_rows
  FROM (
    SELECT id AS "internalId", track_id AS "track_id", position
    FROM playlist_tracks
    WHERE playlist_id = p_playlist_id
    ORDER BY position
  ) t;

  RETURN json_build_object('ok', true, 'order', v_rows);

EXCEPTION WHEN OTHERS THEN
  RETURN json_build_object('ok', false, 'error', SQLERRM);
END;
$$;
```

---

## Backend (FastAPI)

### Endpoint: `POST /api/playlists/{playlist_id}/move-track`

Ubicacion: `routes/playlists.py`

```python
@router.post("/{playlist_id}/move-track")
def move_playlist_track(
    request: Request,
    playlist_id: str = Path(...),
    body: dict = Body(...),
):
    auth = (request.headers.get("Authorization") or "").strip()
    jwt = auth.replace("Bearer ", "").strip()
    if not jwt:
        return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})

    old_index = body.get("old_position")
    new_index = body.get("new_position")
    
    if not isinstance(old_index, int) or not isinstance(new_index, int) \
       or old_index < 1 or new_index < 1:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_params"})

    try:
        db = db_as_user(jwt)

        # Llamar a la funcion RPC
        result = db.rpc("move_playlist_track", {
            "p_playlist_id": playlist_id,
            "p_old_index": old_index,
            "p_new_index": new_index,
        }).execute()

        data = result.data
        if not data or not data.get("ok"):
            return JSONResponse(status_code=400, content=data or {"ok": False, "error": "rpc_failed"})

        # Invalidar cache
        owner_id = _get_user_id(request)
        if owner_id:
            invalidate(CacheType.USER_PLAYLISTS, suffix=owner_id)
            invalidate(CacheType.USER_PLAYLISTS, suffix=f"{playlist_id}:{owner_id}")

        return data

    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": "move_failed", "detail": str(e)})
```

### Request

```json
{
  "old_position": 4,
  "new_position": 1
}
```

Nota: Las posiciones son 1-based (el primer track es posicion 1, no 0).

### Response

```json
{
  "ok": true,
  "order": [
    {"internalId": "uuid-playlist-track", "track_id": "uuid-track", "position": 1},
    {"internalId": "uuid-playlist-track", "track_id": "uuid-track", "position": 2},
    ...
  ]
}
```

---

## Frontend

### Archivos Relevantes

- `services/musicService.ts` - Funcion `moveTrackInPlaylist`
- `hooks/use-playlist-editor.ts` - Hook que maneja el estado de edicion
- `utils/reorder-logger.ts` - Funcion `applyServerOrder` para reconciliar UI con backend

### Flujo

1. Usuario arrastra un track (drag & drop)
2. `handleReorder` aplica update optimista en memoria
3. Se llama a `moveTrackInPlaylist` que hace POST al backend
4. Backend ejecuta la RPC y devuelve el orden final
5. `applyServerOrder` reconcilia el orden optimista con el orden del servidor
6. Se invalida el cache de playlists

### Mapeo de IDs

- `song.internalId` (frontend) = `order.track_id` (backend) = `tracks.id` (DB)
- `order.internalId` (backend) = `playlist_tracks.id` (DB)

---

## Troubleshooting

### Error: duplicate key value violates unique constraint

Causa: El constraint `playlist_tracks_unique_pos` no fue eliminado.

Solucion:
```sql
ALTER TABLE playlist_tracks DROP CONSTRAINT playlist_tracks_unique_pos;
```

### Posiciones con huecos (ej: 1, 2, 5, 8)

La funcion RPC usa `ROW_NUMBER()` para trabajar con indices secuenciales, ignorando las posiciones reales. Despues del reorder, las posiciones quedan normalizadas (1, 2, 3, 4...).

Para normalizar manualmente una playlist:
```sql
WITH ordered AS (
  SELECT id, ROW_NUMBER() OVER (ORDER BY position) AS new_pos
  FROM playlist_tracks
  WHERE playlist_id = 'UUID-DE-LA-PLAYLIST'
)
UPDATE playlist_tracks pt
SET position = o.new_pos
FROM ordered o
WHERE pt.id = o.id;
```

### Cache desactualizado

El endpoint invalida el cache del backend. El frontend tambien invalida su cache local en `musicService.ts`:

```typescript
await cacheClearPrefix(`playlist:${playlistId}`);
await cacheClearPrefix('playlists:list');
emitPlaylistChange();
```

---

## Performance

- La funcion RPC hace 2 UPDATEs (uno a negativo, otro a positivo) que afectan a todos los tracks de la playlist
- Complejidad: O(n) donde n es el numero de tracks
- Para playlists grandes (1000+ tracks) puede tomar 1-2 segundos

---

## Esquema de Tabla

```sql
CREATE TABLE public.playlist_tracks (
  playlist_id uuid NOT NULL,
  track_id uuid NOT NULL,
  position integer NOT NULL,
  added_by uuid NULL,
  added_at timestamp with time zone NULL DEFAULT now(),
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  CONSTRAINT playlist_tracks_pkey PRIMARY KEY (id),
  CONSTRAINT ux_playlist_pos UNIQUE (playlist_id, "position") DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT playlist_tracks_added_by_fkey FOREIGN KEY (added_by) REFERENCES auth.users (id),
  CONSTRAINT playlist_tracks_playlist_id_fkey FOREIGN KEY (playlist_id) REFERENCES playlists (id) ON DELETE CASCADE,
  CONSTRAINT playlist_tracks_track_id_fkey FOREIGN KEY (track_id) REFERENCES tracks (id) ON DELETE RESTRICT
);

CREATE INDEX idx_playlisttracks_playlist_pos ON public.playlist_tracks (playlist_id, "position");
```
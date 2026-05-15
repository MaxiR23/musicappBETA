"""
Playlist service: lógica de negocio para playlists de usuario.
"""
from services.db_protocol import DBClient
from services.cache_service import get_cached, set_cached, invalidate
from services.cache_config import CacheType
from services.track_service import ensure_duration_seconds
from services.library_view_cache import invalidate_library_view

# ── CACHE ─────────────────────────────────────────────────────────────────────
def _invalidate_playlist_cache(owner_id: str, playlist_id: str | None = None) -> None:
    invalidate_library_view(owner_id)
    if playlist_id:
        invalidate(CacheType.USER_PLAYLISTS, suffix=f"{playlist_id}:{owner_id}")

# ── PLAYLISTS ─────────────────────────────────────────────────────────────────
def create_playlist(db: DBClient, user_id: str, title: str, description: str | None, is_public: bool) -> dict:
    resp = db.table("playlists").insert({
        "title": title,
        "description": description,
        "is_public": is_public,
        "owner_id": user_id,
    }).execute()
    _invalidate_playlist_cache(user_id)
    return resp.data[0]

def get_playlists(db: DBClient, user_id: str) -> list:
    resp = db.table("playlists").select(
        "id,title,description,is_public,created_at,"
        "playlist_tracks(position,tracks(thumbnail_url))"
    ).eq("owner_id", user_id).order("created_at", desc=True).execute()

    payload = resp.data or []
    for pl in payload:
        if pl.get("playlist_tracks"):
            pl["playlist_tracks"].sort(key=lambda t: t.get("position") or 0)
    return payload

def get_playlist_by_id(db: DBClient, user_id: str, playlist_id: str) -> dict | None:
    cache_suffix = f"{playlist_id}:{user_id}"
    cached = get_cached(CacheType.USER_PLAYLISTS, suffix=cache_suffix)
    if cached is not None:
        return cached

    playlist_resp = db.table("playlists").select("*").eq("id", playlist_id).maybe_single().execute()
    if not playlist_resp.data:
        return None

    ptracks_resp = (
        db.table("playlist_tracks")
        .select("position,added_at,tracks(*)")
        .eq("playlist_id", playlist_id)
        .order("position")
        .execute()
    )

    payload = {
        **(playlist_resp.data or {}),
        "tracks": [
            {"position": row["position"], "added_at": row["added_at"], **row["tracks"]}
            for row in (ptracks_resp.data or [])
            if row.get("tracks")
        ],
    }
    set_cached(CacheType.USER_PLAYLISTS, payload, suffix=cache_suffix)
    return payload

def delete_playlist(db: DBClient, user_id: str, playlist_id: str) -> list:
    resp = db.table("playlists").delete().eq("id", playlist_id).eq("owner_id", user_id).execute()
    _invalidate_playlist_cache(user_id, playlist_id)
    return resp.data or []

def update_playlist(db: DBClient, user_id: str, playlist_id: str, title: str, description: str | None, is_public: bool) -> dict:
    resp = (
        db.table("playlists")
        .update({"title": title, "description": description, "is_public": is_public})
        .eq("id", playlist_id)
        .eq("owner_id", user_id)
        .execute()
    )
    _invalidate_playlist_cache(user_id, playlist_id)
    return resp.data[0]

# ── TRACKS ─────────────────────────────────────────────────────────────────────
def add_track(
    db: DBClient,
    service_db: DBClient,
    user_id: str,
    playlist_id: str,
    track_id: str,
    body: dict,
) -> dict:
    # 1. Buscar si el track ya existe en public.tracks
    existing_resp = (
        service_db.table("tracks")
        .select("id")
        .eq("track_id", track_id)
        .maybe_single()
        .execute()
    )

    if existing_resp and existing_resp.data:
        track_row = existing_resp.data
    else:
        duration_seconds = ensure_duration_seconds(
            track_id=track_id,
            duration_seconds=body.get("duration_seconds"),
        )
        insert_payload = {
            "track_id": track_id,
            "title": body.get("title"),
            "artists": body.get("artists") or [],
            "album": body.get("album"),
            "album_id": body.get("album_id"),
            "duration_seconds": duration_seconds,
            "thumbnail_url": body.get("thumbnail_url"),
        }
        try:
            track_resp = service_db.table("tracks").insert(insert_payload).execute()
            track_row = track_resp.data[0]
        except Exception:
            # Race condition: otro request inserto el mismo track_id entre
            # el select y el insert. Re-leemos con maybe_single (no single)
            # para no tirar PGRST116 si por alguna razon sigue sin estar.
            reread = (
                service_db.table("tracks")
                .select("id")
                .eq("track_id", track_id)
                .maybe_single()
                .execute()
            )
            if not (reread and reread.data):
                raise
            track_row = reread.data

    internal_id = track_row["id"]

    # 2. Chequear duplicado en la playlist
    existing_link = (
        db.table("playlist_tracks")
        .select("id")
        .eq("playlist_id", playlist_id)
        .eq("track_id", internal_id)
        .limit(1)
        .execute()
    )
    if existing_link.data:
        raise ValueError("track_already_in_playlist")

    # 3. Calcular siguiente posicion
    max_pos_resp = (
        db.table("playlist_tracks")
        .select("position")
        .eq("playlist_id", playlist_id)
        .order("position", desc=True)
        .limit(1)
        .execute()
    )
    last_pos = (max_pos_resp.data or [{}])[0].get("position") or 0

    # 4. Insertar la referencia
    link_resp = db.table("playlist_tracks").insert({
        "playlist_id": playlist_id,
        "track_id": internal_id,
        "position": last_pos + 1,
        "added_by": user_id,
    }).execute()

    _invalidate_playlist_cache(user_id, playlist_id)
    return {"track": track_row, "link": link_resp.data[0]}

def add_tracks_bulk(
    db: DBClient,
    service_db: DBClient,
    user_id: str,
    playlist_id: str,
    tracks: list[dict],
) -> dict:
    if not tracks:
        return {"added": 0, "skipped": 0, "skipped_track_ids": []}

    if len(tracks) > 200:
        raise ValueError("too_many_tracks")

    # Deduplicar por track_id dentro del batch (mismo id repetido en el array)
    seen: set[str] = set()
    unique_tracks: list[dict] = []
    for t in tracks:
        tid = t.get("track_id")
        if tid and tid not in seen:
            seen.add(tid)
            unique_tracks.append(t)

    track_ids = [t["track_id"] for t in unique_tracks]

    # 1. Buscar cuales ya existen en public.tracks
    existing_resp = (
        service_db.table("tracks")
        .select("id, track_id")
        .in_("track_id", track_ids)
        .execute()
    )
    existing_map: dict[str, str] = {
        row["track_id"]: row["id"] for row in (existing_resp.data or [])
    }

    # 2. Insertar bulk los que faltan en public.tracks
    missing = [t for t in unique_tracks if t["track_id"] not in existing_map]
    if missing:
        insert_payload = [
            {
                "track_id": t["track_id"],
                "title": t.get("title"),
                "artists": t.get("artists") or [],
                "album": t.get("album"),
                "album_id": t.get("album_id"),
                "duration_seconds": t.get("duration_seconds"),
                "thumbnail_url": t.get("thumbnail_url"),
            }
            for t in missing
        ]
        try:
            insert_resp = service_db.table("tracks").insert(insert_payload).execute()
            for row in (insert_resp.data or []):
                existing_map[row["track_id"]] = row["id"]
        except Exception:
            # Race: otro request insertó algunos entre el select y el insert.
            # Re-leemos para recuperar los IDs sin tirar el batch entero.
            reread = (
                service_db.table("tracks")
                .select("id, track_id")
                .in_("track_id", [t["track_id"] for t in missing])
                .execute()
            )
            for row in (reread.data or []):
                existing_map[row["track_id"]] = row["id"]

    # internal_ids respetando el orden del batch
    internal_ids = [
        existing_map[t["track_id"]]
        for t in unique_tracks
        if t["track_id"] in existing_map
    ]

    # 3. Chequear cuales ya estan linkeados a esta playlist
    linked_resp = (
        db.table("playlist_tracks")
        .select("track_id")
        .eq("playlist_id", playlist_id)
        .in_("track_id", internal_ids)
        .execute()
    )
    already_linked = {row["track_id"] for row in (linked_resp.data or [])}

    internal_to_external = {v: k for k, v in existing_map.items()}
    skipped_track_ids = [
        internal_to_external[iid] for iid in internal_ids if iid in already_linked
    ]
    new_internal_ids = [iid for iid in internal_ids if iid not in already_linked]

    if not new_internal_ids:
        return {
            "added": 0,
            "skipped": len(skipped_track_ids),
            "skipped_track_ids": skipped_track_ids,
        }

    # 4. Calcular siguiente posicion
    max_pos_resp = (
        db.table("playlist_tracks")
        .select("position")
        .eq("playlist_id", playlist_id)
        .order("position", desc=True)
        .limit(1)
        .execute()
    )
    last_pos = (max_pos_resp.data or [{}])[0].get("position") or 0

    # 5. Insertar links bulk con posiciones consecutivas
    link_payload = [
        {
            "playlist_id": playlist_id,
            "track_id": iid,
            "position": last_pos + i + 1,
            "added_by": user_id,
        }
        for i, iid in enumerate(new_internal_ids)
    ]
    db.table("playlist_tracks").insert(link_payload).execute()

    _invalidate_playlist_cache(user_id, playlist_id)

    return {
        "added": len(new_internal_ids),
        "skipped": len(skipped_track_ids),
        "skipped_track_ids": skipped_track_ids,
    }

def remove_track(db: DBClient, user_id: str, playlist_id: str, track_id: str) -> None:
    db.table("playlist_tracks").delete().eq("playlist_id", playlist_id).eq("track_id", track_id).execute()
    _invalidate_playlist_cache(user_id, playlist_id)

def move_track(db: DBClient, user_id: str, playlist_id: str, old_index: int, new_index: int) -> dict:
    result = db.rpc("move_playlist_track", {
        "p_playlist_id": playlist_id,
        "p_old_index": old_index,
        "p_new_index": new_index,
    }).execute()

    data = result.data
    if not data or not data.get("ok"):
        raise ValueError(data or "rpc_failed")

    _invalidate_playlist_cache(user_id, playlist_id)
    return data
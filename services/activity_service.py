# services/activity_service.py
from __future__ import annotations
from typing import Any, Optional, Dict
from datetime import datetime, timezone

from services.supabase_service import db_as_user
from services.jwt_utils import decode_jwt

# --- enums simples para validar (evita typos) ---
EVENT_TYPES = {"play", "like", "unlike"}
ENTITY_TYPES = {"track", "album", "artist", "playlist"}

def _utc_now_iso() -> str:
    # ISO con timezone Z, compatible con timestamptz
    return datetime.now(timezone.utc).isoformat()

def _get_user_id_from_request(request) -> Optional[str]:
    """
    Intenta obtener el user_id del middleware (request.state.user)
    y si no existe, lo saca del JWT del header Authorization: Bearer <token>.
    """
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("id"):
        print(f"[activity] user desde middleware → {user['id']}")
        return user["id"]

    token = (request.headers.get("Authorization") or "").replace("Bearer ", "")
    print(f"[activity] token recibido? → {'sí' if token else 'NO'} len={len(token) if token else 0}")
    if not token:
        return None

    claims = decode_jwt(token) or {}
    uid = claims.get("sub") or claims.get("user_id")
    print(f"[activity] claims decodificados → keys={list(claims.keys()) if isinstance(claims, dict) else type(claims)}  uid={uid}")
    return uid


def _db_for_request(request):
    """Devuelve un supabase client 'como usuario' respetando RLS."""
    jwt = (request.headers.get("Authorization") or "").replace("Bearer ", "")
    print(f"[activity] construyendo db_as_user → jwt_len={len(jwt) if jwt else 0}")
    return db_as_user(jwt)


def _upsert_album_artist_play(
    db,
    *,
    user_id: str,
    event_type: str,          # siempre 'play' si nos llaman
    entity_type: str,         # 'album' | 'artist'
    entity_id: Optional[str],
    context_type: Optional[str],
    context_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Para plays de ALBUM/ARTIST:
      - si existe (user_id, event_type='play', entity_type, entity_id) → UPDATE occurred_at = now()
      - si no, INSERT.
    No duplica filas por cada clic; solo refresca el 'último ingreso'.
    """
    if not entity_id:
        # Si no tenemos entity_id no podemos “colapsar”, insert normal
        print("[activity][UPSERT] entity_id vacío → fallback a INSERT")
        return _insert_activity(
            db,
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=None,
            context_type=context_type,
            context_id=context_id,
            metadata=metadata,
        )

    try:
        print(f"[activity][UPSERT] lookup existente → user={user_id} {entity_type}={entity_id}")
        # Busco 1 existente para esa combinación
        sel = (
            db.table("user_activity")
            .select("id, occurred_at, play_count")
            .eq("user_id", user_id)
            .eq("event_type", "play")
            .eq("entity_type", entity_type)
            .eq("entity_id", entity_id)
            .order("occurred_at", desc=True)
            .limit(1)
            .execute()
        )

        existing = (sel.data or [])
        if existing:
            row_id = existing[0]["id"]
            new_time = _utc_now_iso()
            print(f"[activity][UPSERT] encontrado id={row_id} → UPDATE occurred_at={new_time}")

            # Si querés refrescar contexto/metadatos, lo hacemos acá (no pisamos si vienen None)
            update_payload: Dict[str, Any] = {
                "occurred_at": new_time,
                "play_count": existing[0].get("play_count", 1) + 1
            }
            if context_type is not None:
                update_payload["context_type"] = context_type
            if context_id is not None:
                update_payload["context_id"] = context_id
            if metadata is not None:
                update_payload["metadata"] = metadata

            # UPDATE por id
            upd = (
                db.table("user_activity")
                .update(update_payload)
                .eq("id", row_id)
                .execute()
            )
            row = (upd.data or [{}])[0]
            print(f"[activity][UPSERT] OK (update) id={row.get('id')} at={row.get('occurred_at')}")
            return {"ok": True, "id": row.get("id"), "occurred_at": row.get("occurred_at")}
        else:
            print("[activity][UPSERT] no existe → INSERT")
            return _insert_activity(
                db,
                user_id=user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                context_type=context_type,
                context_id=context_id,
                metadata=metadata,
            )
    except Exception as e:
        print(f"[activity][UPSERT][ERROR] {e} → fallback a INSERT")
        # En error de lookup/update, no rompemos el flujo: insertamos
        return _insert_activity(
            db,
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            context_type=context_type,
            context_id=context_id,
            metadata=metadata,
        )


def _upsert_like_unlike(
    db,
    *,
    user_id: str,
    event_type: str,          # 'like' | 'unlike'
    entity_type: str,         # 'track' | 'album' | 'artist' | 'playlist' | 'query'
    entity_id: Optional[str],
    context_type: Optional[str],
    context_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Para LIKE/UNLIKE:
      - clave: (user_id, event_type, entity_type, entity_id)
      - si existe → UPDATE occurred_at (y opcionalmente context*/metadata)
      - si no → INSERT
    """
    if not entity_id:
        print("[activity][UPSERT-LIKE] entity_id vacío → fallback a INSERT")
        return _insert_activity(
            db,
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=None,
            context_type=context_type,
            context_id=context_id,
            metadata=metadata,
        )

    try:
        print(f"[activity][UPSERT-LIKE] lookup → user={user_id} {event_type} {entity_type}={entity_id}")
        sel = (
            db.table("user_activity")
            .select("id, occurred_at, play_count")
            .eq("user_id", user_id)
            .eq("event_type", event_type)        # like o unlike
            .eq("entity_type", entity_type)
            .eq("entity_id", entity_id)
            .order("occurred_at", desc=True)
            .limit(1)
            .execute()
        )

        existing = (sel.data or [])
        if existing:
            row_id = existing[0]["id"]
            new_time = _utc_now_iso()
            update_payload: Dict[str, Any] = {"occurred_at": new_time}
            if context_type is not None:
                update_payload["context_type"] = context_type
            if context_id is not None:
                update_payload["context_id"] = context_id
            if metadata is not None:
                update_payload["metadata"] = metadata

            upd = (
                db.table("user_activity")
                .update(update_payload)
                .eq("id", row_id)
                .execute()
            )
            row = (upd.data or [{}])[0]
            print(f"[activity][UPSERT-LIKE] OK (update) id={row.get('id')} at={row.get('occurred_at')}")
            return {"ok": True, "id": row.get("id"), "occurred_at": row.get("occurred_at")}
        else:
            print("[activity][UPSERT-LIKE] no existe → INSERT")
            return _insert_activity(
                db,
                user_id=user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                context_type=context_type,
                context_id=context_id,
                metadata=metadata,
            )
    except Exception as e:
        print(f"[activity][UPSERT-LIKE][ERROR] {e} → fallback a INSERT")
        return _insert_activity(
            db,
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            context_type=context_type,
            context_id=context_id,
            metadata=metadata,
        )


def _insert_activity(
    db,
    *,
    user_id: str,
    event_type: str,
    entity_type: str,
    entity_id: Optional[str],
    context_type: Optional[str],
    context_id: Optional[str],
    metadata: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = {
        "user_id": user_id,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "context_type": context_type,
        "context_id": context_id,
        "metadata": metadata or {},
        # occurred_at usa default now() en INSERT; si quisieras forzar ahora:
        # "occurred_at": _utc_now_iso(),
    }
    try:
        print(f"[activity] INSERT → {payload}")
        resp = db.table("user_activity").insert(payload).execute()
        row = (resp.data or [{}])[0]
        print(f"[activity] OK id={row.get('id')} at={row.get('occurred_at')}")
        return {"ok": True, "id": row.get("id"), "occurred_at": row.get("occurred_at")}
    except Exception as e:
        print(f"[activity][DB_ERROR] {e}")
        return {"ok": False, "error": "db_error", "detail": str(e)}


def log_activity(
    db,
    user_id: str,
    *,
    event_type: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    context_type: Optional[str] = None,
    context_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Inserta/actualiza una fila en public.user_activity. Debe llamarse con un client 'db'
    generado con db_as_user(jwt) para respetar RLS.

    REGLA:
      - Si event_type='play' y entity_type ∈ {'album','artist'} → UPSERT por (user_id, entity_type, entity_id)
        (UPDATE occurred_at si existe; INSERT si no)
      - Si event_type ∈ {'like','unlike'} → UPSERT por (user_id, event_type, entity_type, entity_id)
      - En cualquier otro caso → INSERT normal.
    """
    if event_type not in EVENT_TYPES:
        print(f"[activity][ERROR] invalid_event_type: {event_type}")
        return {"ok": False, "error": f"invalid_event_type '{event_type}'"}
    if entity_type not in ENTITY_TYPES:
        print(f"[activity][ERROR] invalid_entity_type: {entity_type}")
        return {"ok": False, "error": f"invalid_entity_type '{entity_type}'"}

    # Nueva rama: plays de álbum/artista → no duplicar filas, refrescar timestamp.
    if event_type == "play" and entity_type in {"album", "artist", "track"}:
        return _upsert_album_artist_play(
            db,
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            context_type=context_type,
            context_id=context_id,
            metadata=metadata,
        )

    # Nueva rama: like/unlike → no duplicar filas, refrescar timestamp.
    if event_type in {"like", "unlike"}:
        return _upsert_like_unlike(
            db,
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            context_type=context_type,
            context_id=context_id,
            metadata=metadata,
        )

    # Resto: comportamiento anterior (INSERT)
    return _insert_activity(
        db,
        user_id=user_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        context_type=context_type,
        context_id=context_id,
        metadata=metadata,
    )


def log_activity_from_request(
    request,
    *,
    event_type: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    context_type: Optional[str] = None,
    context_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Versión conveniente: resuelve user_id y db desde el request.
    """
    user_id = _get_user_id_from_request(request)
    if not user_id:
        print(f"[activity][UNAUTHORIZED] no se pudo resolver user_id")
        return {"ok": False, "error": "unauthorized"}

    db = _db_for_request(request)
    return log_activity(
        db,
        user_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        context_type=context_type,
        context_id=context_id,
        metadata=metadata,
    )


def try_log_activity_from_request(request, **kwargs) -> None:
    """
    Igual que log_activity_from_request pero 'fire-and-forget':
    jamás levanta excepción ni rompe el flujo. Loguea el resultado.
    """
    try:
        r = log_activity_from_request(request, **kwargs)
        print(f"[activity] try_log result → {r}")
    except Exception as e:
        print(f"[activity][FATAL] {e}")
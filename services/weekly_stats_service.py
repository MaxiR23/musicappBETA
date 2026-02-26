from datetime import date, timedelta

def _get_week_start(d: date = None) -> date:
    """Lunes de la semana PASADA (la última cerrada)."""
    d = d or date.today()
    current_monday = d - timedelta(days=d.weekday())
    return current_monday - timedelta(days=7)

def get_weekly_stats(db, user_id: str, entity_type: str, limit: int = None) -> list:
    """Base: trae stats de la semana actual para un entity_type."""
    week = _get_week_start()
    
    resp = db.table("user_weekly_stats") \
        .select("stats") \
        .eq("user_id", user_id) \
        .eq("entity_type", entity_type) \
        .eq("week_start", week.isoformat()) \
        .maybe_single() \
        .execute()

    if not resp:
        return []    
    
    stats = (resp.data or {}).get("stats") or []
    return stats[:limit] if limit else stats

def get_weekly_artists(db, user_id: str, limit: int = None) -> list:
    return get_weekly_stats(db, user_id, "artist", limit=limit)

def get_weekly_albums(db, user_id: str, limit: int = None) -> list:
    return get_weekly_stats(db, user_id, "album", limit=limit)

def get_weekly_tracks(db, user_id: str, limit: int = None) -> list:
    return get_weekly_stats(db, user_id, "track", limit=limit)

def get_weekly_summary(db, user_id: str, preview: bool = False) -> dict:
    """preview=True → top 3 para el home card."""
    limit = 3 if preview else None
    return {
        "week_start": _get_week_start().isoformat(),
        "artists": get_weekly_artists(db, user_id, limit),
        "albums": get_weekly_albums(db, user_id, limit),
        "tracks": get_weekly_tracks(db, user_id, limit),
    }
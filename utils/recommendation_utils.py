# utils/recommendation_utils.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

def now_utc() -> datetime:
    return datetime.utcnow()

def calc_valid_until(days: int | None) -> Optional[str]:
    if not days or days <= 0:
        return None
    return (now_utc() + timedelta(days=days)).isoformat() + "Z"

def id_any(it: Dict[str, Any]) -> Optional[str]:
    v = it.get("id") or it.get("browse_id") or it.get("browseId") or it.get("playlistId")
    return v.strip() if isinstance(v, str) and v.strip() else None

def thumbnails(it: Dict[str, Any]) -> List[Dict[str, Any]]:
    th = it.get("thumbnails") or it.get("thumbs") or []
    return th if isinstance(th, list) else []

def artist_name(it: Dict[str, Any]) -> Optional[str]:
    # algunos parsers ponen "name", otros "title"
    return (it.get("name") or it.get("title")) or None

def album_title(it: Dict[str, Any]) -> Optional[str]:
    return (it.get("title") or it.get("name")) or None
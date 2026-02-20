# routes/music.py
from fastapi import APIRouter, Path, Body, Request
from fastapi.responses import JSONResponse
import time
import random

from services.supabase_service import db_as_user

router = APIRouter()

@router.post("/playlists/{playlist_id}/move-track")
def move_playlist_track(
    request: Request,
    playlist_id: str = Path(...),
    body: dict = Body(...),
):
    # ── auth ─────────────────────────────────────────────
    auth = (request.headers.get("Authorization") or "").strip()
    jwt  = auth.replace("Bearer ", "").strip()
    if not jwt:
        return JSONResponse(status_code=401, content={"ok": False, "error": "unauthorized"})

    # ── body ─────────────────────────────────────────────
    old_position = body.get("old_position")
    new_position = body.get("new_position")
    if not isinstance(old_position, int) or not isinstance(new_position, int) \
       or old_position < 1 or new_position < 1:
        return JSONResponse(status_code=400, content={"ok": False, "error": "invalid_params"})

    try:
        db = db_as_user(jwt)

        # snapshot pre (para log y fallback visual)
        pre = (
            db.table("playlist_tracks")
              .select("id,position")
              .eq("playlist_id", playlist_id)
              .order("position", desc=False)
              .execute()
        ).data or []
        print(f"[reorder][pre] n={len(pre)} first20={pre[:20]}")

        # fila a mover por position exacta
        row = (
            db.table("playlist_tracks")
              .select("id,position")
              .eq("playlist_id", playlist_id)
              .eq("position", old_position)
              .limit(1)
              .execute()
        )

        # fallback si hay huecos: usar ordinal del snapshot (1-based)
        if not row.data:
            if 1 <= old_position <= len(pre):
                track_row_id = pre[old_position - 1]["id"]
                print(f"[reorder] fallback ordinal -> id={track_row_id} (old_position={old_position})")
            else:
                return JSONResponse(status_code=404, content={"ok": False, "error": "track_not_found"})
        else:
            track_row_id = row.data[0]["id"]

        # clamp destino usando snapshot (consistente con UI)
        total = len(pre)
        if new_position > total: new_position = total
        if new_position < 1:     new_position = 1
        if new_position == old_position:
            ordered_now = (
                db.table("playlist_tracks")
                  .select("id,track_id,position")
                  .eq("playlist_id", playlist_id)
                  .order("position", desc=False)
                  .execute()
            ).data or []
            return {"ok": True, "noop": True, "order": [
                {"internalId": r["id"], "trackId": r["track_id"], "position": r["position"]}
                for r in ordered_now
            ]}

        print(f"[reorder] move old={old_position} -> new={new_position} id={track_row_id}")

        # ── SENTINEL SEGURO (int32 negativo) + reintento ──
        base = int(time.time()) ^ random.randint(1, 1_000_000)
        candidate = - (1 + (abs(base) % 999_999))
        parked = False
        for attempt in range(6):
            try:
                (
                    db.table("playlist_tracks")
                      .update({"position": candidate})
                      .eq("id", track_row_id)
                      .execute()
                )
                parked = True
                print(f"[reorder] parked id={track_row_id} -> {candidate} (attempt={attempt})")
                break
            except Exception as e:
                candidate -= 1
                if candidate < -2_000_000:
                    candidate = -1
                print(f"[reorder] park retry due to {type(e).__name__}: {e}")
        if not parked:
            return JSONResponse(status_code=500, content={"ok": False, "error": "sentinel_failed"})

        # ── SHIFTS UNITARIOS EN ORDEN SEGURO ──
        if new_position < old_position:
            for pos in range(old_position - 1, new_position - 1, -1):
                resp = (
                    db.table("playlist_tracks")
                      .update({"position": pos + 1})
                      .eq("playlist_id", playlist_id)
                      .eq("position", pos)
                      .execute()
                )
                print(f"[reorder] shift_up {pos} -> {pos+1} rows={len(resp.data or [])}")
        else:
            for pos in range(old_position + 1, new_position + 1):
                resp = (
                    db.table("playlist_tracks")
                      .update({"position": pos - 1})
                      .eq("playlist_id", playlist_id)
                      .eq("position", pos)
                      .execute()
                )
                print(f"[reorder] shift_down {pos} -> {pos-1} rows={len(resp.data or [])}")

        # ── colocar el track movido en su destino ──
        fin = (
            db.table("playlist_tracks")
              .update({"position": new_position})
              .eq("id", track_row_id)
              .execute()
        )
        print(f"[reorder] set_final id={track_row_id} -> {new_position} ok_rows={len(fin.data or [])}")

        # snapshot post
        post = (
            db.table("playlist_tracks")
              .select("id,position")
              .eq("playlist_id", playlist_id)
              .order("position", desc=False)
              .execute()
        ).data or []
        print(f"[reorder][post] n={len(post)} first20={post[:20]}")

        # verificación 1..N sin huecos/duplicados
        gaps, dups, seen = [], [], set()
        expected = 1
        for r in post:
            p = int(r["position"])
            if p in seen: dups.append(p)
            seen.add(p)
            if p != expected:
                gaps.append({"expected": expected, "found": p})
                expected = p
            expected += 1
        if dups or gaps:
            print(f"[reorder][WARN] dups={dups} gaps={gaps}")

        # orden completo
        ordered = (
            db.table("playlist_tracks")
              .select("id,track_id,position")
              .eq("playlist_id", playlist_id)
              .order("position", desc=False)
              .execute()
        ).data or []

        return {
            "ok": True,
            "order": [{"internalId": r["id"], "trackId": r["track_id"], "position": r["position"]} for r in ordered],
            "positions_sample": [r["position"] for r in post[:30]],
            "dups": dups,
            "gaps": gaps
        }

    except Exception as e:
        print(f"[reorder][EXC] {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={
            "ok": False,
            "error": "move_failed",
            "detail": f"{type(e).__name__}: {e}"
        })
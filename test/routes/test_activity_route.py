# test/routes/test_activity_routes.py
#
# Testeamos: routes/activity.py
# Contrato HTTP: status code, shape del response, params a services.
#
# NO testeamos lógica interna → eso está en test/services/.
#
# Herramienta: FastAPI TestClient (Starlette)
# SEE: https://fastapi.tiangolo.com/tutorial/testing/
#

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import patch, MagicMock

from routes.activity import router
from core.dependencies import get_db, get_current_user_id

# ════════════════════════════════════════════════════════
# APP DE TEST
# ════════════════════════════════════════════════════════
def make_app(user_id: str = "user-test") -> FastAPI:
    """App mínima con el router y dependencias overrideadas."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return app

@pytest.fixture
def client():
    return TestClient(make_app())

# ════════════════════════════════════════════════════════
# _extract_display_meta (helper puro del router)
# ════════════════════════════════════════════════════════
class TestExtractDisplayMeta:
    """Testeamos el helper directamente sin HTTP."""
    def test_extracts_display_name_from_display_name(self):
        from routes.activity import _extract_display_meta
        result = _extract_display_meta({"display_name": "OK Computer"})
        assert result["display_name"] == "OK Computer"

    def test_falls_back_to_name(self):
        from routes.activity import _extract_display_meta
        result = _extract_display_meta({"name": "OK Computer"})
        assert result["display_name"] == "OK Computer"

    def test_falls_back_to_title(self):
        from routes.activity import _extract_display_meta
        result = _extract_display_meta({"title": "OK Computer"})
        assert result["display_name"] == "OK Computer"

    def test_extracts_thumbnail_url(self):
        from routes.activity import _extract_display_meta
        result = _extract_display_meta({"thumbnail_url": "http://img.jpg"})
        assert result["thumbnail_url"] == "http://img.jpg"

    def test_falls_back_to_thumbnail(self):
        from routes.activity import _extract_display_meta
        result = _extract_display_meta({"thumbnail": "http://img.jpg"})
        assert result["thumbnail_url"] == "http://img.jpg"

    def test_empty_body_returns_empty_dict(self):
        from routes.activity import _extract_display_meta
        assert _extract_display_meta({}) == {}

    def test_display_name_takes_priority_over_name(self):
        from routes.activity import _extract_display_meta
        result = _extract_display_meta({"display_name": "Primary", "name": "Secondary"})
        assert result["display_name"] == "Primary"

# ════════════════════════════════════════════════════════
# POST /plays/tracks/{track_id}
# ════════════════════════════════════════════════════════
class TestLogPlayTrack:
    def test_returns_ok_true(self, client):
        with patch("routes.activity.log_play", return_value={"ok": True}), \
             patch("routes.activity.ensure_duration_seconds", return_value=230):
            r = client.post("/plays/tracks/dQw4w9", json={"duration_seconds": 230})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_returns_ok_false_when_service_fails(self, client):
        with patch("routes.activity.log_play", return_value={"ok": False}), \
             patch("routes.activity.ensure_duration_seconds", return_value=None):
            r = client.post("/plays/tracks/dQw4w9", json={})
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_passes_track_id_to_service(self, client):
        with patch("routes.activity.log_play", return_value={"ok": True}) as mock_log, \
             patch("routes.activity.ensure_duration_seconds", return_value=None):
            client.post("/plays/tracks/my-track-id", json={})
        assert mock_log.call_args[1]["track_id"] == "my-track-id"

    def test_passes_user_id_to_service(self, client):
        with patch("routes.activity.log_play", return_value={"ok": True}) as mock_log, \
             patch("routes.activity.ensure_duration_seconds", return_value=None):
            client.post("/plays/tracks/t1", json={})
        assert mock_log.call_args[1]["user_id"] == "user-test"

    def test_passes_metadata_fields(self, client):
        body = {
            "album_id": "al1", "album_name": "OK Computer",
            "artist_id": "ar1", "artist_name": "Radiohead",
            "track_name": "Creep", "thumbnail_url": "http://img.jpg",
            "duration_seconds": 238,
        }
        with patch("routes.activity.log_play", return_value={"ok": True}) as mock_log, \
             patch("routes.activity.ensure_duration_seconds", return_value=238):
            client.post("/plays/tracks/t1", json=body)
        metadata = mock_log.call_args[1]["metadata"]
        assert metadata["album_id"] == "al1"
        assert metadata["artist_name"] == "Radiohead"
        assert metadata["duration_seconds"] == 238

    def test_accepts_empty_body(self, client):
        with patch("routes.activity.log_play", return_value={"ok": True}), \
             patch("routes.activity.ensure_duration_seconds", return_value=None):
            r = client.post("/plays/tracks/t1")
        assert r.status_code == 200

    def test_skips_missing_metadata_fields(self, client):
        with patch("routes.activity.log_play", return_value={"ok": True}) as mock_log, \
             patch("routes.activity.ensure_duration_seconds", return_value=None):
            client.post("/plays/tracks/t1", json={})
        metadata = mock_log.call_args[1]["metadata"]
        assert "album_id" not in metadata
        assert "artist_id" not in metadata

# ════════════════════════════════════════════════════════
# POST /plays/albums/{album_id}
# ════════════════════════════════════════════════════════
class TestLogPlayAlbum:
    def test_returns_ok_true(self, client):
        with patch("routes.activity.upsert_recent"):
            r = client.post("/plays/albums/al1", json={"display_name": "OK Computer"})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_passes_entity_type_album(self, client):
        with patch("routes.activity.upsert_recent") as mock_upsert:
            client.post("/plays/albums/al1", json={})
        assert mock_upsert.call_args[1]["entity_type"] == "album"

    def test_passes_album_id(self, client):
        with patch("routes.activity.upsert_recent") as mock_upsert:
            client.post("/plays/albums/my-album-id", json={})
        assert mock_upsert.call_args[1]["entity_id"] == "my-album-id"

    def test_passes_display_meta(self, client):
        with patch("routes.activity.upsert_recent") as mock_upsert:
            client.post("/plays/albums/al1", json={"display_name": "OK Computer", "thumbnail_url": "http://img.jpg"})
        metadata = mock_upsert.call_args[1]["metadata"]
        assert metadata["display_name"] == "OK Computer"
        assert metadata["thumbnail_url"] == "http://img.jpg"

    def test_accepts_empty_body(self, client):
        with patch("routes.activity.upsert_recent"):
            r = client.post("/plays/albums/al1")
        assert r.status_code == 200

# ════════════════════════════════════════════════════════
# POST /plays/artists/{artist_id}
# ════════════════════════════════════════════════════════
class TestLogPlayArtist:
    def test_returns_ok_true(self, client):
        with patch("routes.activity.upsert_recent"):
            r = client.post("/plays/artists/ar1", json={})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_passes_entity_type_artist(self, client):
        with patch("routes.activity.upsert_recent") as mock_upsert:
            client.post("/plays/artists/ar1", json={})
        assert mock_upsert.call_args[1]["entity_type"] == "artist"

    def test_passes_artist_id(self, client):
        with patch("routes.activity.upsert_recent") as mock_upsert:
            client.post("/plays/artists/my-artist-id", json={})
        assert mock_upsert.call_args[1]["entity_id"] == "my-artist-id"

# ════════════════════════════════════════════════════════
# POST /plays/playlists/{playlist_id}
# ════════════════════════════════════════════════════════
class TestLogPlayPlaylist:
    def test_returns_ok_true(self, client):
        with patch("routes.activity.upsert_recent"):
            r = client.post("/plays/playlists/pl1", json={})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_passes_entity_type_playlist(self, client):
        with patch("routes.activity.upsert_recent") as mock_upsert:
            client.post("/plays/playlists/pl1", json={})
        assert mock_upsert.call_args[1]["entity_type"] == "playlist"

    def test_passes_playlist_id(self, client):
        with patch("routes.activity.upsert_recent") as mock_upsert:
            client.post("/plays/playlists/my-playlist-id", json={})
        assert mock_upsert.call_args[1]["entity_id"] == "my-playlist-id"

# ════════════════════════════════════════════════════════
# GET /me/recent
# ════════════════════════════════════════════════════════
class TestGetRecent:
    def _make_recent_row(self, entity_type="track", entity_id="t1", display_name="Creep", thumbnail="http://img.jpg"):
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "played_at": "2024-03-15T10:00:00",
            "metadata": {"display_name": display_name, "thumbnail_url": thumbnail},
        }

    def test_returns_items_list(self, client):
        rows = [self._make_recent_row()]
        with patch("routes.activity.get_recents", return_value=rows):
            r = client.get("/me/recent")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_response_shape(self, client):
        rows = [self._make_recent_row()]
        with patch("routes.activity.get_recents", return_value=rows):
            r = client.get("/me/recent")
        item = r.json()["items"][0]
        assert item["type"] == "track"
        assert item["id"] == "t1"
        assert item["played_at"] == "2024-03-15T10:00:00"
        assert item["name"] == "Creep"
        assert item["thumbnail_url"] == "http://img.jpg"

    def test_empty_recents_returns_empty_list(self, client):
        with patch("routes.activity.get_recents", return_value=[]):
            r = client.get("/me/recent")
        assert r.json() == {"items": []}

    def test_passes_user_id_to_service(self, client):
        with patch("routes.activity.get_recents", return_value=[]) as mock_get:
            client.get("/me/recent")
        assert mock_get.call_args[1]["user_id"] == "user-test"

    def test_default_limit_is_30(self, client):
        with patch("routes.activity.get_recents", return_value=[]) as mock_get:
            client.get("/me/recent")
        assert mock_get.call_args[1]["limit"] == 30

    def test_custom_limit(self, client):
        with patch("routes.activity.get_recents", return_value=[]) as mock_get:
            client.get("/me/recent?limit=10")
        assert mock_get.call_args[1]["limit"] == 10

    def test_handles_none_metadata(self, client):
        rows = [{"entity_type": "track", "entity_id": "t1", "played_at": "2024-01-01", "metadata": None}]
        with patch("routes.activity.get_recents", return_value=rows):
            r = client.get("/me/recent")
        item = r.json()["items"][0]
        assert item["name"] is None
        assert item["thumbnail_url"] is None

    def test_multiple_items_all_mapped(self, client):
        rows = [
            self._make_recent_row("track", "t1"),
            self._make_recent_row("album", "al1"),
            self._make_recent_row("artist", "ar1"),
        ]
        with patch("routes.activity.get_recents", return_value=rows):
            r = client.get("/me/recent")
        items = r.json()["items"]
        assert len(items) == 3
        assert items[0]["type"] == "track"
        assert items[1]["type"] == "album"
        assert items[2]["type"] == "artist"
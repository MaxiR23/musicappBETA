# test/routes/test_genres_routes.py
#
# Testeamos: routes/genres.py
# Dos routers: router (géneros) y playlists_router (playlists)
#
# GET /                          → lista géneros
# GET /{slug}/playlists          → playlists de un género
# GET /{slug}/categories         → categorías de un género
# GET /playlists/{id}/tracks     → tracks de una playlist
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routes.genres import router, playlists_router
from core.dependencies import get_db

# ════════════════════════════════════════════════════════
# APP DE TEST
# Montamos ambos routers con sus prefijos reales
# ════════════════════════════════════════════════════════
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/genres")
    app.include_router(playlists_router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)

# ════════════════════════════════════════════════════════
# GET /genres/
# ════════════════════════════════════════════════════════
class TestListGenres:
    def test_returns_ok_with_genres(self, client):
        genres = [{"id": "g1", "name": "Rock"}, {"id": "g2", "name": "Jazz"}]
        with patch("routes.genres.get_all_genres", return_value=genres):
            r = client.get("/genres/")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "genres": genres}

    def test_returns_empty_list_when_no_genres(self, client):
        with patch("routes.genres.get_all_genres", return_value=[]):
            r = client.get("/genres/")
        assert r.status_code == 200
        assert r.json()["genres"] == []

    def test_returns_502_on_exception(self, client):
        with patch("routes.genres.get_all_genres", side_effect=Exception("db error")):
            r = client.get("/genres/")
        assert r.status_code == 502
        assert r.json()["ok"] is False
        assert r.json()["error"] == "service_unavailable"

# ════════════════════════════════════════════════════════
# GET /genres/{slug}/playlists
# ════════════════════════════════════════════════════════
class TestListGenrePlaylists:
    def _genre(self):
        return {"id": "g1", "name": "Rock", "slug": "rock"}

    def test_returns_ok_with_playlists(self, client):
        playlists = [{"id": "pl1", "title": "Rock Classics"}]
        with patch("routes.genres.get_genre_by_slug", return_value=self._genre()), \
             patch("routes.genres.get_playlists_by_genre", return_value=playlists):
            r = client.get("/genres/rock/playlists")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["genre"] == self._genre()
        assert r.json()["playlists"] == playlists

    def test_returns_404_when_genre_not_found(self, client):
        with patch("routes.genres.get_genre_by_slug", return_value=None):
            r = client.get("/genres/unknown-slug/playlists")
        assert r.status_code == 404
        assert r.json()["error"] == "genre_not_found"

    def test_passes_slug_to_service(self, client):
        with patch("routes.genres.get_genre_by_slug", return_value=None) as mock_get:
            client.get("/genres/jazz/playlists")
        assert mock_get.call_args[0][1] == "jazz"

    def test_passes_category_filter(self, client):
        with patch("routes.genres.get_genre_by_slug", return_value=self._genre()), \
             patch("routes.genres.get_playlists_by_genre", return_value=[]) as mock_get:
            client.get("/genres/rock/playlists?category=classics")
        assert mock_get.call_args[1]["category"] == "classics"

    def test_category_is_none_by_default(self, client):
        with patch("routes.genres.get_genre_by_slug", return_value=self._genre()), \
             patch("routes.genres.get_playlists_by_genre", return_value=[]) as mock_get:
            client.get("/genres/rock/playlists")
        assert mock_get.call_args[1]["category"] is None

    def test_returns_502_on_exception(self, client):
        with patch("routes.genres.get_genre_by_slug", side_effect=Exception("db error")):
            r = client.get("/genres/rock/playlists")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /genres/{slug}/categories
# ════════════════════════════════════════════════════════
class TestGetCategories:
    def _genre(self):
        return {"id": "g1", "name": "Rock", "slug": "rock"}

    def test_returns_ok_with_categories(self, client):
        categories = ["classics", "indie", "metal"]
        with patch("routes.genres.get_genre_by_slug", return_value=self._genre()), \
             patch("routes.genres.get_genre_categories", return_value=categories):
            r = client.get("/genres/rock/categories")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["categories"] == categories
        assert r.json()["genre"] == self._genre()

    def test_returns_404_when_genre_not_found(self, client):
        with patch("routes.genres.get_genre_by_slug", return_value=None):
            r = client.get("/genres/unknown/categories")
        assert r.status_code == 404
        assert r.json()["error"] == "genre_not_found"

    def test_passes_genre_id_to_categories_service(self, client):
        with patch("routes.genres.get_genre_by_slug", return_value=self._genre()), \
             patch("routes.genres.get_genre_categories", return_value=[]) as mock_cat:
            client.get("/genres/rock/categories")
        assert mock_cat.call_args[0][1] == "g1"

    def test_returns_502_on_exception(self, client):
        with patch("routes.genres.get_genre_by_slug", side_effect=Exception("fail")):
            r = client.get("/genres/rock/categories")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /playlists/{playlist_id}/tracks
# ════════════════════════════════════════════════════════
class TestGetPlaylistTracks:
    def _playlist(self):
        return {"id": "pl1", "title": "Rock Classics", "track_count": 50}

    def test_returns_ok_with_tracks(self, client):
        tracks = [{"id": "t1", "title": "Bohemian Rhapsody"}]
        with patch("routes.genres.get_playlist_by_id", return_value=self._playlist()), \
             patch("routes.genres.get_playlist_tracks", return_value=tracks):
            r = client.get("/playlists/pl1/tracks")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["tracks"] == tracks

    def test_response_playlist_shape(self, client):
        with patch("routes.genres.get_playlist_by_id", return_value=self._playlist()), \
             patch("routes.genres.get_playlist_tracks", return_value=[]):
            r = client.get("/playlists/pl1/tracks")
        playlist = r.json()["playlist"]
        assert playlist["id"] == "pl1"
        assert playlist["title"] == "Rock Classics"
        assert playlist["track_count"] == 50

    def test_returns_404_when_playlist_not_found(self, client):
        with patch("routes.genres.get_playlist_by_id", return_value=None):
            r = client.get("/playlists/bad-id/tracks")
        assert r.status_code == 404
        assert r.json()["error"] == "playlist_not_found"

    def test_passes_playlist_id_to_service(self, client):
        with patch("routes.genres.get_playlist_by_id", return_value=None) as mock_get:
            client.get("/playlists/my-playlist-id/tracks")
        assert mock_get.call_args[0][1] == "my-playlist-id"

    def test_default_limit_is_100(self, client):
        with patch("routes.genres.get_playlist_by_id", return_value=self._playlist()), \
             patch("routes.genres.get_playlist_tracks", return_value=[]) as mock_tracks:
            client.get("/playlists/pl1/tracks")
        assert mock_tracks.call_args[1]["limit"] == 100

    def test_custom_limit(self, client):
        with patch("routes.genres.get_playlist_by_id", return_value=self._playlist()), \
             patch("routes.genres.get_playlist_tracks", return_value=[]) as mock_tracks:
            client.get("/playlists/pl1/tracks?limit=20")
        assert mock_tracks.call_args[1]["limit"] == 20

    def test_returns_502_on_exception(self, client):
        with patch("routes.genres.get_playlist_by_id", side_effect=Exception("fail")):
            r = client.get("/playlists/pl1/tracks")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"
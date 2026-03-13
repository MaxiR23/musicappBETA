# test/routes/test_playlists_routes.py
#
# Testeamos: routes/playlists.py
# Contrato HTTP: status code, shape del response, delegación al service.
#
# Los route tests patchean el SERVICE completo — no la implementación interna.
# Si el service cambia internamente, estos tests no se tocan.
#
# POST   /                              → create_playlist
# GET    /                              → get_playlists
# GET    /{playlist_id}                 → get_playlist_by_id
# DELETE /{playlist_id}                 → delete_playlist
# POST   /{playlist_id}/tracks          → add_track
# DELETE /{playlist_id}/tracks/{id}     → remove_track
# POST   /{playlist_id}/move-track      → move_track
#
# SEE: https://fastapi.tiangolo.com/tutorial/testing/
# SEE: https://docs.pytest.org/en/stable/reference/fixtures.html
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routes.playlists import router
from core.dependencies import get_user_db, get_service_db, get_current_user_id

FAKE_USER_ID = "user-test"

# ════════════════════════════════════════════════════════
# APP DE TEST
# ════════════════════════════════════════════════════════
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/playlists")
    app.dependency_overrides[get_user_db] = lambda: MagicMock()
    app.dependency_overrides[get_service_db] = lambda: MagicMock()
    app.dependency_overrides[get_current_user_id] = lambda: FAKE_USER_ID
    return TestClient(app)

# ════════════════════════════════════════════════════════
# POST /playlists/
# ════════════════════════════════════════════════════════
class TestCreatePlaylist:
    def test_returns_400_when_no_title(self, client):
        r = client.post("/playlists/", json={"description": "x"})
        assert r.status_code == 400
        assert r.json()["error"] == "title_required"

    def test_returns_playlist_on_success(self, client):
        result = {"id": "pl1", "title": "My Playlist", "owner_id": FAKE_USER_ID}
        with patch("routes.playlists.create_playlist", return_value=result):
            r = client.post("/playlists/", json={"title": "My Playlist"})
        assert r.status_code == 200
        assert r.json()["id"] == "pl1"

    def test_passes_correct_args_to_service(self, client):
        with patch("routes.playlists.create_playlist", return_value={"id": "pl1"}) as mock:
            client.post("/playlists/", json={"title": "My Playlist", "description": "desc", "is_public": True})
        mock.assert_called_once()
        _, user_id, title, description, is_public = mock.call_args[0]
        assert user_id == FAKE_USER_ID
        assert title == "My Playlist"
        assert description == "desc"
        assert is_public is True

    def test_is_public_defaults_to_false(self, client):
        with patch("routes.playlists.create_playlist", return_value={"id": "pl1"}) as mock:
            client.post("/playlists/", json={"title": "x"})
        _, _, _, _, is_public = mock.call_args[0]
        assert is_public is False

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.create_playlist", side_effect=Exception("db error")):
            r = client.post("/playlists/", json={"title": "x"})
        assert r.status_code == 500
        assert r.json()["error"] == "db_error"

# ════════════════════════════════════════════════════════
# GET /playlists/
# ════════════════════════════════════════════════════════
class TestGetPlaylists:
    def test_returns_list_on_success(self, client):
        result = [{"id": "pl1"}, {"id": "pl2"}]
        with patch("routes.playlists.get_playlists", return_value=result):
            r = client.get("/playlists/")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_passes_user_id_to_service(self, client):
        with patch("routes.playlists.get_playlists", return_value=[]) as mock:
            client.get("/playlists/")
        _, user_id = mock.call_args[0]
        assert user_id == FAKE_USER_ID

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.get_playlists", side_effect=Exception("fail")):
            r = client.get("/playlists/")
        assert r.status_code == 500
        assert r.json()["error"] == "db_error"

# ════════════════════════════════════════════════════════
# GET /playlists/{playlist_id}
# ════════════════════════════════════════════════════════
class TestGetPlaylistById:
    def test_returns_playlist_on_success(self, client):
        result = {"id": "pl1", "title": "x", "tracks": []}
        with patch("routes.playlists.get_playlist_by_id", return_value=result):
            r = client.get("/playlists/pl1")
        assert r.status_code == 200
        assert r.json()["id"] == "pl1"

    def test_passes_correct_args_to_service(self, client):
        with patch("routes.playlists.get_playlist_by_id", return_value={"id": "pl1"}) as mock:
            client.get("/playlists/pl1")
        _, user_id, playlist_id = mock.call_args[0]
        assert user_id == FAKE_USER_ID
        assert playlist_id == "pl1"

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.get_playlist_by_id", side_effect=Exception("fail")):
            r = client.get("/playlists/pl1")
        assert r.status_code == 500
        assert r.json()["error"] == "db_error"

# ════════════════════════════════════════════════════════
# DELETE /playlists/{playlist_id}
# ════════════════════════════════════════════════════════
class TestDeletePlaylist:
    def test_returns_ok_true(self, client):
        with patch("routes.playlists.delete_playlist", return_value=[{"id": "pl1"}]):
            r = client.delete("/playlists/pl1")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_passes_correct_args_to_service(self, client):
        with patch("routes.playlists.delete_playlist", return_value=[]) as mock:
            client.delete("/playlists/pl1")
        _, user_id, playlist_id = mock.call_args[0]
        assert user_id == FAKE_USER_ID
        assert playlist_id == "pl1"

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.delete_playlist", side_effect=Exception("fail")):
            r = client.delete("/playlists/pl1")
        assert r.status_code == 500
        assert r.json()["error"] == "db_error"

# ════════════════════════════════════════════════════════
# POST /playlists/{playlist_id}/tracks
# ════════════════════════════════════════════════════════
class TestAddTrack:
    def test_returns_400_when_no_track_id(self, client):
        r = client.post("/playlists/pl1/tracks", json={"title": "x"})
        assert r.status_code == 400
        assert r.json()["error"] == "track_id_required"

    def test_returns_ok_true_on_success(self, client):
        result = {"track": {"id": "db-t1"}, "link": {"position": 1}}
        with patch("routes.playlists.add_track", return_value=result):
            r = client.post("/playlists/pl1/tracks", json={"track_id": "vid1"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_passes_correct_args_to_service(self, client):
        result = {"track": {"id": "db-t1"}, "link": {"position": 1}}
        with patch("routes.playlists.add_track", return_value=result) as mock:
            client.post("/playlists/pl1/tracks", json={"track_id": "vid1", "title": "Creep"})
        _, _, user_id, playlist_id, track_id, body = mock.call_args[0]
        assert user_id == FAKE_USER_ID
        assert playlist_id == "pl1"
        assert track_id == "vid1"
        assert body["title"] == "Creep"

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.add_track", side_effect=Exception("fail")):
            r = client.post("/playlists/pl1/tracks", json={"track_id": "vid1"})
        assert r.status_code == 500
        assert r.json()["error"] == "db_error"

# ════════════════════════════════════════════════════════
# DELETE /playlists/{playlist_id}/tracks/{track_id}
# ════════════════════════════════════════════════════════
class TestRemoveTrack:
    def test_returns_ok_true(self, client):
        with patch("routes.playlists.remove_track"):
            r = client.delete("/playlists/pl1/tracks/t1")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_passes_correct_args_to_service(self, client):
        with patch("routes.playlists.remove_track") as mock:
            client.delete("/playlists/pl1/tracks/t1")
        _, user_id, playlist_id, track_id = mock.call_args[0]
        assert user_id == FAKE_USER_ID
        assert playlist_id == "pl1"
        assert track_id == "t1"

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.remove_track", side_effect=Exception("fail")):
            r = client.delete("/playlists/pl1/tracks/t1")
        assert r.status_code == 500
        assert r.json()["error"] == "db_error"

# ════════════════════════════════════════════════════════
# POST /playlists/{playlist_id}/move-track
# ════════════════════════════════════════════════════════
class TestMoveTrack:
    def test_returns_400_when_positions_not_int(self, client):
        r = client.post("/playlists/pl1/move-track", json={"old_position": "x", "new_position": 2})
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_params"

    def test_returns_400_when_position_less_than_1(self, client):
        r = client.post("/playlists/pl1/move-track", json={"old_position": 0, "new_position": 2})
        assert r.status_code == 400

    def test_returns_400_when_positions_missing(self, client):
        r = client.post("/playlists/pl1/move-track", json={})
        assert r.status_code == 400

    def test_returns_result_on_success(self, client):
        with patch("routes.playlists.move_track", return_value={"ok": True}):
            r = client.post("/playlists/pl1/move-track", json={"old_position": 1, "new_position": 3})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_passes_correct_args_to_service(self, client):
        with patch("routes.playlists.move_track", return_value={"ok": True}) as mock:
            client.post("/playlists/pl1/move-track", json={"old_position": 2, "new_position": 4})
        _, user_id, playlist_id, old_index, new_index = mock.call_args[0]
        assert user_id == FAKE_USER_ID
        assert playlist_id == "pl1"
        assert old_index == 2
        assert new_index == 4

    def test_returns_400_when_service_raises_value_error(self, client):
        with patch("routes.playlists.move_track", side_effect=ValueError("rpc_failed")):
            r = client.post("/playlists/pl1/move-track", json={"old_position": 1, "new_position": 2})
        assert r.status_code == 400
        assert r.json()["error"] == "rpc_failed"

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.move_track", side_effect=Exception("fail")):
            r = client.post("/playlists/pl1/move-track", json={"old_position": 1, "new_position": 2})
        assert r.status_code == 500
        assert r.json()["error"] == "move_failed"
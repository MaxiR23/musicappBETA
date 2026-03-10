# test/routes/test_playlists_routes.py
#
# Testeamos: routes/playlists.py
# Contrato HTTP: status code, shape del response, cache, invalidación.
#
# _invalidate_playlist_cache     → invalida por owner y por playlist+owner
# POST   /                       → crear playlist
# GET    /                       → listar playlists (cache)
# GET    /{playlist_id}          → detalle playlist (cache)
# POST   /{playlist_id}/tracks   → agregar track (upsert + link)
# DELETE /{playlist_id}/tracks/{track_id} → remover track
# DELETE /{playlist_id}          → borrar playlist
# POST   /{playlist_id}/move-track → reordenar track (rpc)
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, call

from routes.playlists import router, _invalidate_playlist_cache
from core.dependencies import get_user_db, get_service_db, get_current_user_id

# ════════════════════════════════════════════════════════
# APP DE TEST
# ════════════════════════════════════════════════════════

def make_db():
    db = MagicMock()
    table = MagicMock()
    db.table.return_value = table
    table.select.return_value = table
    table.insert.return_value = table
    table.upsert.return_value = table
    table.delete.return_value = table
    table.eq.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    table.single.return_value = table
    res = MagicMock()
    res.data = []
    table.execute.return_value = res
    return db, table, res

@pytest.fixture
def client():
    user_db, _, _ = make_db()
    service_db, _, _ = make_db()
    app = FastAPI()
    app.include_router(router, prefix="/playlists")
    app.dependency_overrides[get_user_db] = lambda: user_db
    app.dependency_overrides[get_service_db] = lambda: service_db
    app.dependency_overrides[get_current_user_id] = lambda: "user-test"
    return TestClient(app)

@pytest.fixture
def dbs():
    user_db, user_table, user_res = make_db()
    service_db, service_table, service_res = make_db()
    return user_db, user_table, user_res, service_db, service_table, service_res

def make_client(user_db, service_db, user_id="user-test"):
    app = FastAPI()
    app.include_router(router, prefix="/playlists")
    app.dependency_overrides[get_user_db] = lambda: user_db
    app.dependency_overrides[get_service_db] = lambda: service_db
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    return TestClient(app)

# ════════════════════════════════════════════════════════
# _invalidate_playlist_cache
# ════════════════════════════════════════════════════════
class TestInvalidatePlaylistCache:
    def test_invalidates_owner_cache(self):
        with patch("routes.playlists.invalidate") as mock_inv:
            _invalidate_playlist_cache("user-1")
        calls = [str(c) for c in mock_inv.call_args_list]
        assert any("user-1" in c for c in calls)

    def test_invalidates_playlist_cache_when_id_provided(self):
        with patch("routes.playlists.invalidate") as mock_inv:
            _invalidate_playlist_cache("user-1", "pl-1")
        assert mock_inv.call_count == 2

    def test_does_not_invalidate_playlist_when_id_is_none(self):
        with patch("routes.playlists.invalidate") as mock_inv:
            _invalidate_playlist_cache("user-1", None)
        assert mock_inv.call_count == 1

# ════════════════════════════════════════════════════════
# POST /playlists/
# ════════════════════════════════════════════════════════
class TestCreatePlaylist:
    def test_returns_400_when_no_title(self, client):
        r = client.post("/playlists/", json={"description": "x"})
        assert r.status_code == 400
        assert r.json()["error"] == "title_required"

    def test_creates_playlist_and_returns_data(self):
        user_db, user_table, user_res = make_db()
        service_db, _, _ = make_db()
        user_res.data = [{"id": "pl1", "title": "My Playlist", "owner_id": "user-test"}]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.invalidate"):
            r = c.post("/playlists/", json={"title": "My Playlist"})
        assert r.status_code == 200
        assert r.json()["id"] == "pl1"

    def test_inserts_correct_fields(self):
        user_db, user_table, user_res = make_db()
        service_db, _, _ = make_db()
        user_res.data = [{"id": "pl1", "title": "My Playlist"}]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.invalidate"):
            c.post("/playlists/", json={"title": "My Playlist", "is_public": True, "description": "desc"})
        insert_call = user_table.insert.call_args[0][0]
        assert insert_call["title"] == "My Playlist"
        assert insert_call["owner_id"] == "user-test"
        assert insert_call["is_public"] is True

    def test_invalidates_cache_after_create(self):
        user_db, user_table, user_res = make_db()
        service_db, _, _ = make_db()
        user_res.data = [{"id": "pl1"}]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.invalidate") as mock_inv:
            c.post("/playlists/", json={"title": "x"})
        mock_inv.assert_called()

    def test_returns_500_on_exception(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        user_table.execute.side_effect = Exception("db error")
        c = make_client(user_db, service_db)
        r = c.post("/playlists/", json={"title": "x"})
        assert r.status_code == 500
        assert r.json()["error"] == "db_error"

# ════════════════════════════════════════════════════════
# GET /playlists/
# ════════════════════════════════════════════════════════
class TestGetPlaylists:
    def test_returns_cached_when_available(self, client):
        cached = [{"id": "pl1", "title": "My Playlist"}]
        with patch("routes.playlists.get_cached", return_value=cached):
            r = client.get("/playlists/")
        assert r.status_code == 200
        assert r.json() == cached

    def test_fetches_from_db_on_cache_miss(self):
        user_db, user_table, user_res = make_db()
        service_db, _, _ = make_db()
        user_res.data = [{"id": "pl1", "title": "x", "playlist_tracks": []}]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.get_cached", return_value=None), \
             patch("routes.playlists.set_cached"):
            r = c.get("/playlists/")
        assert r.status_code == 200

    def test_sorts_playlist_tracks_by_position(self):
        user_db, user_table, user_res = make_db()
        service_db, _, _ = make_db()
        user_res.data = [{
            "id": "pl1",
            "playlist_tracks": [{"position": 3}, {"position": 1}, {"position": 2}]
        }]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.get_cached", return_value=None), \
             patch("routes.playlists.set_cached"):
            r = c.get("/playlists/")
        tracks = r.json()[0]["playlist_tracks"]
        assert tracks[0]["position"] == 1
        assert tracks[1]["position"] == 2

    def test_caches_result(self):
        user_db, user_table, user_res = make_db()
        service_db, _, _ = make_db()
        user_res.data = []
        c = make_client(user_db, service_db)
        with patch("routes.playlists.get_cached", return_value=None), \
             patch("routes.playlists.set_cached") as mock_set:
            c.get("/playlists/")
        mock_set.assert_called_once()

    def test_returns_500_on_exception(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        user_table.execute.side_effect = Exception("fail")
        c = make_client(user_db, service_db)
        with patch("routes.playlists.get_cached", return_value=None):
            r = c.get("/playlists/")
        assert r.status_code == 500

# ════════════════════════════════════════════════════════
# GET /playlists/{playlist_id}
# ════════════════════════════════════════════════════════
class TestGetPlaylistById:
    def test_returns_cached_when_available(self, client):
        cached = {"id": "pl1", "title": "x", "tracks": []}
        with patch("routes.playlists.get_cached", return_value=cached):
            r = client.get("/playlists/pl1")
        assert r.status_code == 200
        assert r.json() == cached

    def test_fetches_playlist_and_tracks_on_miss(self):
        user_db, user_table, user_res = make_db()
        service_db, _, _ = make_db()
        playlist_res = MagicMock()
        playlist_res.data = {"id": "pl1", "title": "My Playlist"}
        ptracks_res = MagicMock()
        ptracks_res.data = [{"position": 1, "added_at": "2024-01-01", "tracks": {"id": "t1", "title": "Creep"}}]
        user_table.execute.side_effect = [playlist_res, ptracks_res]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.get_cached", return_value=None), \
             patch("routes.playlists.set_cached"):
            r = c.get("/playlists/pl1")
        assert r.status_code == 200
        assert r.json()["title"] == "My Playlist"
        assert r.json()["tracks"][0]["title"] == "Creep"
        assert r.json()["tracks"][0]["position"] == 1

    def test_caches_result(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        playlist_res = MagicMock()
        playlist_res.data = {"id": "pl1"}
        ptracks_res = MagicMock()
        ptracks_res.data = []
        user_table.execute.side_effect = [playlist_res, ptracks_res]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.get_cached", return_value=None), \
             patch("routes.playlists.set_cached") as mock_set:
            c.get("/playlists/pl1")
        mock_set.assert_called_once()

    def test_returns_500_on_exception(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        user_table.execute.side_effect = Exception("fail")
        c = make_client(user_db, service_db)
        with patch("routes.playlists.get_cached", return_value=None):
            r = c.get("/playlists/pl1")
        assert r.status_code == 500

# ════════════════════════════════════════════════════════
# POST /playlists/{playlist_id}/tracks
# ════════════════════════════════════════════════════════
class TestAddTrackToPlaylist:
    def test_returns_400_when_no_track_id(self, client):
        r = client.post("/playlists/pl1/tracks", json={"title": "x"})
        assert r.status_code == 400
        assert r.json()["error"] == "track_id_required"

    def test_upserts_track_and_inserts_link(self):
        user_db, user_table, user_res = make_db()
        service_db, service_table, service_res = make_db()
        service_res.data = [{"id": "db-track-id", "track_id": "vid1"}]
        max_pos_res = MagicMock()
        max_pos_res.data = [{"position": 3}]
        link_res = MagicMock()
        link_res.data = [{"playlist_id": "pl1", "track_id": "db-track-id", "position": 4}]
        user_table.execute.side_effect = [max_pos_res, link_res]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.ensure_duration_seconds", return_value=230), \
             patch("routes.playlists.invalidate"):
            r = c.post("/playlists/pl1/tracks", json={"track_id": "vid1", "title": "Creep"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_position_is_last_plus_one(self):
        user_db, user_table, _ = make_db()
        service_db, service_table, service_res = make_db()
        service_res.data = [{"id": "db-t1"}]
        max_pos_res = MagicMock()
        max_pos_res.data = [{"position": 5}]
        link_res = MagicMock()
        link_res.data = [{"position": 6}]
        user_table.execute.side_effect = [max_pos_res, link_res]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.ensure_duration_seconds", return_value=None), \
             patch("routes.playlists.invalidate"):
            c.post("/playlists/pl1/tracks", json={"track_id": "vid1"})
        insert_call = user_table.insert.call_args[0][0]
        assert insert_call["position"] == 6

    def test_position_is_1_when_no_existing_tracks(self):
        user_db, user_table, _ = make_db()
        service_db, service_table, service_res = make_db()
        service_res.data = [{"id": "db-t1"}]
        max_pos_res = MagicMock()
        max_pos_res.data = []
        link_res = MagicMock()
        link_res.data = [{"position": 1}]
        user_table.execute.side_effect = [max_pos_res, link_res]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.ensure_duration_seconds", return_value=None), \
             patch("routes.playlists.invalidate"):
            c.post("/playlists/pl1/tracks", json={"track_id": "vid1"})
        insert_call = user_table.insert.call_args[0][0]
        assert insert_call["position"] == 1

    def test_invalidates_cache(self):
        user_db, user_table, _ = make_db()
        service_db, service_table, service_res = make_db()
        service_res.data = [{"id": "db-t1"}]
        max_pos_res = MagicMock()
        max_pos_res.data = []
        link_res = MagicMock()
        link_res.data = [{"position": 1}]
        user_table.execute.side_effect = [max_pos_res, link_res]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.ensure_duration_seconds", return_value=None), \
             patch("routes.playlists.invalidate") as mock_inv:
            c.post("/playlists/pl1/tracks", json={"track_id": "vid1"})
        mock_inv.assert_called()

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.ensure_duration_seconds", side_effect=Exception("fail")):
            r = client.post("/playlists/pl1/tracks", json={"track_id": "vid1"})
        assert r.status_code == 500

# ════════════════════════════════════════════════════════
# DELETE /playlists/{playlist_id}/tracks/{track_id}
# ════════════════════════════════════════════════════════
class TestRemoveTrackFromPlaylist:
    def test_returns_ok_true(self, client):
        with patch("routes.playlists.invalidate"):
            r = client.delete("/playlists/pl1/tracks/t1")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_invalidates_cache(self, client):
        with patch("routes.playlists.invalidate") as mock_inv:
            client.delete("/playlists/pl1/tracks/t1")
        mock_inv.assert_called()

    def test_returns_500_on_exception(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        user_table.execute.side_effect = Exception("fail")
        c = make_client(user_db, service_db)
        r = c.delete("/playlists/pl1/tracks/t1")
        assert r.status_code == 500

# ════════════════════════════════════════════════════════
# DELETE /playlists/{playlist_id}
# ════════════════════════════════════════════════════════
class TestDeletePlaylist:
    def test_returns_ok_true(self):
        user_db, user_table, user_res = make_db()
        service_db, _, _ = make_db()
        deleted_res = MagicMock()
        deleted_res.data = [{"id": "pl1"}]
        user_table.execute.side_effect = [MagicMock(), deleted_res]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.invalidate"):
            r = c.delete("/playlists/pl1")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_deletes_tracks_then_playlist(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        tracks_res = MagicMock()
        tracks_res.data = []
        pl_res = MagicMock()
        pl_res.data = [{"id": "pl1"}]
        user_table.execute.side_effect = [tracks_res, pl_res]
        c = make_client(user_db, service_db)
        with patch("routes.playlists.invalidate"):
            c.delete("/playlists/pl1")
        calls = [c[0][0] for c in user_db.table.call_args_list]
        assert calls[0] == "playlist_tracks"
        assert calls[1] == "playlists"

    def test_invalidates_cache(self, client):
        with patch("routes.playlists.invalidate") as mock_inv:
            client.delete("/playlists/pl1")
        mock_inv.assert_called()

    def test_returns_500_on_exception(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        user_table.execute.side_effect = Exception("fail")
        c = make_client(user_db, service_db)
        r = c.delete("/playlists/pl1")
        assert r.status_code == 500

# ════════════════════════════════════════════════════════
# POST /playlists/{playlist_id}/move-track
# ════════════════════════════════════════════════════════
class TestMovePlaylistTrack:
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

    def test_calls_rpc_with_correct_params(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = {"ok": True}
        rpc_mock.execute.return_value = rpc_res
        user_db.rpc.return_value = rpc_mock
        c = make_client(user_db, service_db)
        with patch("routes.playlists.invalidate"):
            r = c.post("/playlists/pl1/move-track", json={"old_position": 2, "new_position": 4})
        assert r.status_code == 200
        call_args = user_db.rpc.call_args
        assert call_args[0][0] == "move_playlist_track"
        assert call_args[0][1]["p_old_index"] == 2
        assert call_args[0][1]["p_new_index"] == 4

    def test_returns_400_when_rpc_returns_not_ok(self):
        user_db, user_table, _ = make_db()
        service_db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = {"ok": False, "error": "rpc_failed"}
        rpc_mock.execute.return_value = rpc_res
        user_db.rpc.return_value = rpc_mock
        c = make_client(user_db, service_db)
        r = c.post("/playlists/pl1/move-track", json={"old_position": 1, "new_position": 3})
        assert r.status_code == 400

    def test_invalidates_cache_on_success(self):
        user_db, _, _ = make_db()
        service_db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = {"ok": True}
        rpc_mock.execute.return_value = rpc_res
        user_db.rpc.return_value = rpc_mock
        c = make_client(user_db, service_db)
        with patch("routes.playlists.invalidate") as mock_inv:
            c.post("/playlists/pl1/move-track", json={"old_position": 1, "new_position": 2})
        mock_inv.assert_called()

    def test_returns_500_on_exception(self, client):
        with patch("routes.playlists.get_current_user_id", side_effect=Exception("fail")):
            pass
        user_db, _, _ = make_db()
        service_db, _, _ = make_db()
        user_db.rpc.side_effect = Exception("rpc error")
        c = make_client(user_db, service_db)
        r = c.post("/playlists/pl1/move-track", json={"old_position": 1, "new_position": 2})
        assert r.status_code == 500
        assert r.json()["error"] == "move_failed"
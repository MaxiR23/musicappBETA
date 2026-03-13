# test/services/test_playlist_service.py
#
# Testeamos: services/playlist_service.py
# - _invalidate_playlist_cache  → invalida por owner y por playlist+owner
# - create_playlist             → insert + invalidate cache
# - get_playlists               → cache → fetch → sort → cache
# - get_playlist_by_id          → cache → fetch playlist + tracks → cache
# - delete_playlist             → delete tracks + playlist + invalidate
# - add_track                   → upsert track + calcular posición + link + invalidate
# - remove_track                → delete link + invalidate
# - move_track                  → rpc + invalidate / raises ValueError cuando falla
#
# SEE: https://docs.pytest.org/en/stable/reference/fixtures.html
#

import pytest
from unittest.mock import patch, MagicMock, call

from services.playlist_service import (
    _invalidate_playlist_cache,
    create_playlist,
    get_playlists,
    get_playlist_by_id,
    delete_playlist,
    add_track,
    remove_track,
    move_track,
)
from services.cache_config import CacheType

# ════════════════════════════════════════════════════════
# HELPERS
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

# ════════════════════════════════════════════════════════
# _invalidate_playlist_cache
# ════════════════════════════════════════════════════════
class TestInvalidatePlaylistCache:
    def test_invalidates_owner_cache(self):
        with patch("services.playlist_service.invalidate") as mock_inv:
            _invalidate_playlist_cache("user-1")
        mock_inv.assert_called_once_with(CacheType.USER_PLAYLISTS, suffix="user-1")

    def test_invalidates_both_when_playlist_id_given(self):
        with patch("services.playlist_service.invalidate") as mock_inv:
            _invalidate_playlist_cache("user-1", "pl-1")
        assert mock_inv.call_count == 2
        mock_inv.assert_any_call(CacheType.USER_PLAYLISTS, suffix="user-1")
        mock_inv.assert_any_call(CacheType.USER_PLAYLISTS, suffix="pl-1:user-1")

    def test_does_not_invalidate_playlist_when_id_is_none(self):
        with patch("services.playlist_service.invalidate") as mock_inv:
            _invalidate_playlist_cache("user-1", None)
        assert mock_inv.call_count == 1

# ════════════════════════════════════════════════════════
# create_playlist
# ════════════════════════════════════════════════════════
class TestCreatePlaylist:
    def test_returns_first_row(self):
        db, table, res = make_db()
        res.data = [{"id": "pl1", "title": "My Playlist"}]
        with patch("services.playlist_service.invalidate"):
            result = create_playlist(db, "user-1", "My Playlist", None, False)
        assert result["id"] == "pl1"

    def test_inserts_correct_fields(self):
        db, table, res = make_db()
        res.data = [{"id": "pl1"}]
        with patch("services.playlist_service.invalidate"):
            create_playlist(db, "user-1", "My Playlist", "desc", True)
        insert_call = table.insert.call_args[0][0]
        assert insert_call["title"] == "My Playlist"
        assert insert_call["description"] == "desc"
        assert insert_call["is_public"] is True
        assert insert_call["owner_id"] == "user-1"

    def test_invalidates_owner_cache(self):
        db, table, res = make_db()
        res.data = [{"id": "pl1"}]
        with patch("services.playlist_service.invalidate") as mock_inv:
            create_playlist(db, "user-1", "My Playlist", None, False)
        mock_inv.assert_called_once_with(CacheType.USER_PLAYLISTS, suffix="user-1")

# ════════════════════════════════════════════════════════
# get_playlists
# ════════════════════════════════════════════════════════
class TestGetPlaylists:
    def test_returns_cached_when_available(self):
        db, _, _ = make_db()
        cached = [{"id": "pl1"}]
        with patch("services.playlist_service.get_cached", return_value=cached):
            result = get_playlists(db, "user-1")
        assert result == cached

    def test_queries_db_on_cache_miss(self):
        db, table, res = make_db()
        res.data = [{"id": "pl1", "playlist_tracks": []}]
        with patch("services.playlist_service.get_cached", return_value=None), \
             patch("services.playlist_service.set_cached"):
            result = get_playlists(db, "user-1")
        assert result[0]["id"] == "pl1"

    def test_sorts_tracks_by_position(self):
        db, table, res = make_db()
        res.data = [{
            "id": "pl1",
            "playlist_tracks": [{"position": 3}, {"position": 1}, {"position": 2}]
        }]
        with patch("services.playlist_service.get_cached", return_value=None), \
             patch("services.playlist_service.set_cached"):
            result = get_playlists(db, "user-1")
        tracks = result[0]["playlist_tracks"]
        assert tracks[0]["position"] == 1
        assert tracks[1]["position"] == 2
        assert tracks[2]["position"] == 3

    def test_does_not_sort_when_no_tracks(self):
        db, table, res = make_db()
        res.data = [{"id": "pl1", "playlist_tracks": []}]
        with patch("services.playlist_service.get_cached", return_value=None), \
             patch("services.playlist_service.set_cached"):
            result = get_playlists(db, "user-1")
        assert result[0]["playlist_tracks"] == []

    def test_caches_result_with_user_suffix(self):
        db, table, res = make_db()
        res.data = []
        with patch("services.playlist_service.get_cached", return_value=None), \
             patch("services.playlist_service.set_cached") as mock_set:
            get_playlists(db, "user-1")
        mock_set.assert_called_once_with(CacheType.USER_PLAYLISTS, [], suffix="user-1")

    def test_skips_db_when_cached(self):
        db, table, res = make_db()
        with patch("services.playlist_service.get_cached", return_value=[{"id": "pl1"}]):
            get_playlists(db, "user-1")
        table.execute.assert_not_called()

# ════════════════════════════════════════════════════════
# get_playlist_by_id
# ════════════════════════════════════════════════════════
class TestGetPlaylistById:
    def test_returns_cached_when_available(self):
        db, _, _ = make_db()
        cached = {"id": "pl1", "tracks": []}
        with patch("services.playlist_service.get_cached", return_value=cached):
            result = get_playlist_by_id(db, "user-1", "pl1")
        assert result == cached

    def test_builds_payload_with_tracks(self):
        db, table, _ = make_db()
        playlist_res = MagicMock()
        playlist_res.data = {"id": "pl1", "title": "My Playlist"}
        ptracks_res = MagicMock()
        ptracks_res.data = [
            {"position": 1, "added_at": "2024-01-01", "tracks": {"id": "t1", "title": "Creep"}}
        ]
        table.execute.side_effect = [playlist_res, ptracks_res]
        with patch("services.playlist_service.get_cached", return_value=None), \
             patch("services.playlist_service.set_cached"):
            result = get_playlist_by_id(db, "user-1", "pl1")
        assert result["title"] == "My Playlist"
        assert result["tracks"][0]["title"] == "Creep"
        assert result["tracks"][0]["position"] == 1
        assert result["tracks"][0]["added_at"] == "2024-01-01"

    def test_uses_correct_cache_suffix(self):
        db, table, _ = make_db()
        playlist_res = MagicMock()
        playlist_res.data = {"id": "pl1"}
        ptracks_res = MagicMock()
        ptracks_res.data = []
        table.execute.side_effect = [playlist_res, ptracks_res]
        with patch("services.playlist_service.get_cached", return_value=None) as mock_get, \
             patch("services.playlist_service.set_cached") as mock_set:
            get_playlist_by_id(db, "user-1", "pl1")
        mock_get.assert_called_once_with(CacheType.USER_PLAYLISTS, suffix="pl1:user-1")
        mock_set.assert_called_once()
        assert mock_set.call_args[1]["suffix"] == "pl1:user-1"

    def test_empty_ptracks_returns_empty_tracks(self):
        db, table, _ = make_db()
        playlist_res = MagicMock()
        playlist_res.data = {"id": "pl1"}
        ptracks_res = MagicMock()
        ptracks_res.data = []
        table.execute.side_effect = [playlist_res, ptracks_res]
        with patch("services.playlist_service.get_cached", return_value=None), \
             patch("services.playlist_service.set_cached"):
            result = get_playlist_by_id(db, "user-1", "pl1")
        assert result["tracks"] == []

# ════════════════════════════════════════════════════════
# delete_playlist
# ════════════════════════════════════════════════════════
class TestDeletePlaylist:
    def test_returns_deleted_data(self):
        db, table, res = make_db()
        res.data = [{"id": "pl1"}]
        with patch("services.playlist_service.invalidate"):
            result = delete_playlist(db, "user-1", "pl1")
        assert result == [{"id": "pl1"}]

    def test_deletes_only_playlist(self):
        db, table, res = make_db()
        res.data = []
        with patch("services.playlist_service.invalidate"):
            delete_playlist(db, "user-1", "pl1")
        calls = [c[0][0] for c in db.table.call_args_list]
        assert calls == ["playlists"]

    def test_invalidates_cache(self):
        db, table, res = make_db()
        res.data = []
        with patch("services.playlist_service.invalidate") as mock_inv:
            delete_playlist(db, "user-1", "pl1")
        assert mock_inv.call_count == 2

    def test_returns_empty_list_when_no_data(self):
        db, table, res = make_db()
        res.data = None
        with patch("services.playlist_service.invalidate"):
            result = delete_playlist(db, "user-1", "pl1")
        assert result == []

# ════════════════════════════════════════════════════════
# add_track
# ════════════════════════════════════════════════════════
class TestAddTrack:
    def _setup(self, last_position=3):
        db, table, _ = make_db()
        service_db, service_table, service_res = make_db()
        service_res.data = [{"id": "db-track-id", "track_id": "vid1"}]
        max_pos_res = MagicMock()
        max_pos_res.data = [{"position": last_position}] if last_position else []
        link_res = MagicMock()
        link_res.data = [{"playlist_id": "pl1", "track_id": "db-track-id", "position": last_position + 1}]
        table.execute.side_effect = [max_pos_res, link_res]
        return db, table, service_db, service_table, service_res

    def test_returns_track_and_link(self):
        db, table, service_db, service_table, service_res = self._setup()
        with patch("services.playlist_service.ensure_duration_seconds", return_value=230), \
             patch("services.playlist_service.invalidate"):
            result = add_track(db, service_db, "user-1", "pl1", "vid1", {})
        assert "track" in result
        assert "link" in result

    def test_upserts_track_with_correct_fields(self):
        db, _, service_db, service_table, service_res = self._setup()
        body = {"title": "Creep", "artist": "Radiohead", "artist_id": "ar1",
                "album": "Pablo Honey", "album_id": "al1", "thumbnail_url": "http://img.jpg"}
        with patch("services.playlist_service.ensure_duration_seconds", return_value=210), \
             patch("services.playlist_service.invalidate"):
            add_track(db, service_db, "user-1", "pl1", "vid1", body)
        upsert_call = service_table.upsert.call_args[0][0]
        assert upsert_call["track_id"] == "vid1"
        assert upsert_call["title"] == "Creep"
        assert upsert_call["artist_id"] == "ar1"
        assert upsert_call["duration_seconds"] == 210

    def test_position_is_last_plus_one(self):
        db, table, service_db, _, service_res = self._setup(last_position=5)
        with patch("services.playlist_service.ensure_duration_seconds", return_value=None), \
             patch("services.playlist_service.invalidate"):
            add_track(db, service_db, "user-1", "pl1", "vid1", {})
        insert_call = table.insert.call_args[0][0]
        assert insert_call["position"] == 6

    def test_position_is_1_when_no_existing_tracks(self):
        db, table, _ = make_db()
        service_db, service_table, service_res = make_db()
        service_res.data = [{"id": "db-t1"}]
        max_pos_res = MagicMock()
        max_pos_res.data = []
        link_res = MagicMock()
        link_res.data = [{"position": 1}]
        table.execute.side_effect = [max_pos_res, link_res]
        with patch("services.playlist_service.ensure_duration_seconds", return_value=None), \
             patch("services.playlist_service.invalidate"):
            add_track(db, service_db, "user-1", "pl1", "vid1", {})
        insert_call = table.insert.call_args[0][0]
        assert insert_call["position"] == 1

    def test_added_by_is_user_id(self):
        db, table, service_db, _, service_res = self._setup()
        with patch("services.playlist_service.ensure_duration_seconds", return_value=None), \
             patch("services.playlist_service.invalidate"):
            add_track(db, service_db, "user-1", "pl1", "vid1", {})
        insert_call = table.insert.call_args[0][0]
        assert insert_call["added_by"] == "user-1"

    def test_invalidates_cache(self):
        db, _, service_db, _, _ = self._setup()
        with patch("services.playlist_service.ensure_duration_seconds", return_value=None), \
             patch("services.playlist_service.invalidate") as mock_inv:
            add_track(db, service_db, "user-1", "pl1", "vid1", {})
        assert mock_inv.call_count == 2

# ════════════════════════════════════════════════════════
# remove_track
# ════════════════════════════════════════════════════════
class TestRemoveTrack:
    def test_deletes_correct_link(self):
        db, table, res = make_db()
        with patch("services.playlist_service.invalidate"):
            remove_track(db, "user-1", "pl1", "t1")
        table.delete.assert_called_once()
        eq_calls = table.eq.call_args_list
        assert any("pl1" in str(c) for c in eq_calls)
        assert any("t1" in str(c) for c in eq_calls)

    def test_invalidates_cache(self):
        db, _, _ = make_db()
        with patch("services.playlist_service.invalidate") as mock_inv:
            remove_track(db, "user-1", "pl1", "t1")
        assert mock_inv.call_count == 2

# ════════════════════════════════════════════════════════
# move_track
# ════════════════════════════════════════════════════════
class TestMoveTrack:
    def test_returns_rpc_data_on_success(self):
        db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = {"ok": True}
        rpc_mock.execute.return_value = rpc_res
        db.rpc.return_value = rpc_mock
        with patch("services.playlist_service.invalidate"):
            result = move_track(db, "user-1", "pl1", 2, 4)
        assert result == {"ok": True}

    def test_calls_rpc_with_correct_params(self):
        db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = {"ok": True}
        rpc_mock.execute.return_value = rpc_res
        db.rpc.return_value = rpc_mock
        with patch("services.playlist_service.invalidate"):
            move_track(db, "user-1", "pl1", 2, 4)
        call_args = db.rpc.call_args
        assert call_args[0][0] == "move_playlist_track"
        assert call_args[0][1]["p_playlist_id"] == "pl1"
        assert call_args[0][1]["p_old_index"] == 2
        assert call_args[0][1]["p_new_index"] == 4

    def test_raises_value_error_when_rpc_returns_not_ok(self):
        db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = {"ok": False, "error": "out_of_range"}
        rpc_mock.execute.return_value = rpc_res
        db.rpc.return_value = rpc_mock
        with pytest.raises(ValueError):
            move_track(db, "user-1", "pl1", 99, 1)

    def test_raises_value_error_when_rpc_returns_none(self):
        db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = None
        rpc_mock.execute.return_value = rpc_res
        db.rpc.return_value = rpc_mock
        with pytest.raises(ValueError):
            move_track(db, "user-1", "pl1", 1, 2)

    def test_invalidates_cache_on_success(self):
        db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = {"ok": True}
        rpc_mock.execute.return_value = rpc_res
        db.rpc.return_value = rpc_mock
        with patch("services.playlist_service.invalidate") as mock_inv:
            move_track(db, "user-1", "pl1", 1, 3)
        assert mock_inv.call_count == 2

    def test_does_not_invalidate_when_rpc_fails(self):
        db, _, _ = make_db()
        rpc_mock = MagicMock()
        rpc_res = MagicMock()
        rpc_res.data = {"ok": False}
        rpc_mock.execute.return_value = rpc_res
        db.rpc.return_value = rpc_mock
        with patch("services.playlist_service.invalidate") as mock_inv:
            with pytest.raises(ValueError):
                move_track(db, "user-1", "pl1", 1, 2)
        mock_inv.assert_not_called()
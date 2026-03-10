# test/services/test_genre_repo.py
#
# Testeamos: services/genre_repo.py
# - build_genre_data                → construye dict de género
# - build_playlist_data             → construye dict de playlist
# - build_track_data                → construye dict de track (id o track_id, thumb o thumbnail_url)
# - build_playlist_track_item       → construye item de track en playlist
# - extract_unique_categories       → categorías únicas ordenadas
# - build_thumbnails_map            → agrupa thumbnails por playlist_id
# - upsert_genre                    → insert/update género, retorna id
# - upsert_genre_playlist           → insert/update playlist, retorna id
# - upsert_track                    → insert/update track
# - insert_genre_playlist_tracks    → DELETE + INSERT tracks por posición
# - get_all_genres                  → SELECT ordenado
# - get_genre_by_slug               → SELECT por slug
# - get_playlists_by_genre          → SELECT + rpc thumbnails
# - get_playlist_by_id              → SELECT por id
# - get_playlist_tracks             → SELECT join tracks por posición
# - get_genre_categories            → categorías únicas de un género
#

import pytest
from unittest.mock import MagicMock, call, patch
from services.genre_repo import (
    build_genre_data,
    build_playlist_data,
    build_track_data,
    build_playlist_track_item,
    extract_unique_categories,
    build_thumbnails_map,
    upsert_genre,
    upsert_genre_playlist,
    upsert_track,
    insert_genre_playlist_tracks,
    get_all_genres,
    get_genre_by_slug,
    get_playlists_by_genre,
    get_playlist_by_id,
    get_playlist_tracks,
    get_genre_categories,
)

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
    table.update.return_value = table
    table.delete.return_value = table
    table.eq.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    table.in_.return_value = table
    table.not_ = table
    table.is_.return_value = table
    res = MagicMock()
    res.data = []
    table.execute.return_value = res
    db.rpc.return_value = table
    return db, table, res

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestBuildGenreData:
    def test_builds_correct_structure(self):
        result = build_genre_data("Rock", "rock", 1, "Guitar music")
        assert result == {
            "name": "Rock",
            "slug": "rock",
            "sort_order": 1,
            "description": "Guitar music",
        }

    def test_description_defaults_to_none(self):
        result = build_genre_data("Rock", "rock", 1)
        assert result["description"] is None

class TestBuildPlaylistData:
    def test_builds_correct_structure(self):
        result = build_playlist_data("g1", "Best of Rock", "classics", 2, "Great songs", "http://img.jpg")
        assert result["genre_id"] == "g1"
        assert result["title"] == "Best of Rock"
        assert result["category"] == "classics"
        assert result["sort_order"] == 2
        assert result["description"] == "Great songs"
        assert result["thumbnail_url"] == "http://img.jpg"
        assert result["track_count"] == 0

    def test_defaults(self):
        result = build_playlist_data("g1", "Rock Mix")
        assert result["category"] is None
        assert result["sort_order"] == 0
        assert result["description"] is None
        assert result["thumbnail_url"] is None
        assert result["track_count"] == 0

class TestBuildTrackData:
    def test_uses_id_field(self):
        track = {"id": "t1", "title": "Creep", "artist": "Radiohead"}
        result = build_track_data(track)
        assert result["track_id"] == "t1"

    def test_falls_back_to_track_id_field(self):
        track = {"track_id": "t2", "title": "Karma Police"}
        result = build_track_data(track)
        assert result["track_id"] == "t2"

    def test_id_takes_priority_over_track_id(self):
        track = {"id": "primary", "track_id": "fallback"}
        result = build_track_data(track)
        assert result["track_id"] == "primary"

    def test_uses_thumbnail_url(self):
        track = {"id": "t1", "thumbnail_url": "http://thumb.jpg"}
        result = build_track_data(track)
        assert result["thumbnail_url"] == "http://thumb.jpg"

    def test_falls_back_to_thumb(self):
        track = {"id": "t1", "thumb": "http://thumb2.jpg"}
        result = build_track_data(track)
        assert result["thumbnail_url"] == "http://thumb2.jpg"

    def test_thumbnail_url_takes_priority_over_thumb(self):
        track = {"id": "t1", "thumbnail_url": "http://primary.jpg", "thumb": "http://fallback.jpg"}
        result = build_track_data(track)
        assert result["thumbnail_url"] == "http://primary.jpg"

    def test_all_fields_mapped(self):
        track = {
            "id": "t1", "title": "Song", "artist": "Artist",
            "artist_id": "ar1", "album": "Album", "album_id": "al1",
            "duration_seconds": 180, "thumbnail_url": "http://img.jpg"
        }
        result = build_track_data(track)
        assert result["title"] == "Song"
        assert result["artist"] == "Artist"
        assert result["artist_id"] == "ar1"
        assert result["album"] == "Album"
        assert result["album_id"] == "al1"
        assert result["duration_seconds"] == 180

    def test_empty_track_returns_nones(self):
        result = build_track_data({})
        assert result["track_id"] is None
        assert result["title"] is None

class TestBuildPlaylistTrackItem:
    def test_builds_correct_structure(self):
        track_data = {
            "title": "Creep", "artist": "Radiohead", "album": "Pablo Honey",
            "duration_seconds": 238, "thumbnail_url": "http://img.jpg", "artist_id": "ar1"
        }
        result = build_playlist_track_item(1, "t1", track_data)
        assert result["position"] == 1
        assert result["track_id"] == "t1"
        assert result["title"] == "Creep"
        assert result["artist"] == "Radiohead"
        assert result["artist_id"] == "ar1"

    def test_missing_track_data_returns_nones(self):
        result = build_playlist_track_item(1, "t1", {})
        assert result["title"] is None
        assert result["artist"] is None

class TestExtractUniqueCategories:
    def test_returns_sorted_unique_categories(self):
        rows = [
            {"category": "rock"},
            {"category": "jazz"},
            {"category": "rock"},
            {"category": "pop"},
        ]
        result = extract_unique_categories(rows)
        assert result == ["jazz", "pop", "rock"]

    def test_skips_none_categories(self):
        rows = [{"category": None}, {"category": "rock"}]
        result = extract_unique_categories(rows)
        assert result == ["rock"]

    def test_skips_missing_category_key(self):
        rows = [{"other": "x"}, {"category": "jazz"}]
        result = extract_unique_categories(rows)
        assert result == ["jazz"]

    def test_empty_list_returns_empty(self):
        assert extract_unique_categories([]) == []

    def test_all_none_returns_empty(self):
        rows = [{"category": None}, {"category": None}]
        assert extract_unique_categories(rows) == []

class TestBuildThumbnailsMap:
    def test_groups_thumbnails_by_playlist_id(self):
        rows = [
            {"playlist_id": "p1", "thumbnail_url": "http://a.jpg"},
            {"playlist_id": "p1", "thumbnail_url": "http://b.jpg"},
            {"playlist_id": "p2", "thumbnail_url": "http://c.jpg"},
        ]
        result = build_thumbnails_map(rows)
        assert len(result["p1"]) == 2
        assert len(result["p2"]) == 1

    def test_skips_rows_without_thumbnail_url(self):
        rows = [
            {"playlist_id": "p1", "thumbnail_url": None},
            {"playlist_id": "p1", "thumbnail_url": "http://a.jpg"},
        ]
        result = build_thumbnails_map(rows)
        assert result["p1"] == ["http://a.jpg"]

    def test_includes_playlist_id_with_no_thumbnails(self):
        rows = [{"playlist_id": "p1", "thumbnail_url": None}]
        result = build_thumbnails_map(rows)
        assert "p1" in result
        assert result["p1"] == []

    def test_empty_rows_returns_empty_map(self):
        assert build_thumbnails_map([]) == {}

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestUpsertGenre:
    def test_returns_id_on_success(self):
        db, table, res = make_db()
        res.data = [{"id": "genre-1"}]
        result = upsert_genre(db, "Rock", "rock", 1)
        assert result == "genre-1"

    def test_raises_when_no_data(self):
        db, table, res = make_db()
        res.data = []
        with pytest.raises(RuntimeError):
            upsert_genre(db, "Rock", "rock", 1)

    def test_calls_upsert_with_correct_conflict(self):
        db, table, res = make_db()
        res.data = [{"id": "g1"}]
        upsert_genre(db, "Rock", "rock", 1)
        table.upsert.assert_called_once()
        call_kwargs = table.upsert.call_args
        assert "slug" in str(call_kwargs)

class TestUpsertGenrePlaylist:
    def test_updates_existing_playlist(self):
        db, table, res = make_db()
        res.data = [{"id": "p1"}]
        result = upsert_genre_playlist(db, "g1", "Rock Mix")
        assert result == "p1"
        table.update.assert_called_once()

    def test_inserts_new_playlist(self):
        db, table, res = make_db()
        # Primera llamada (select) retorna vacío, segunda (insert) retorna id
        res.data = []
        insert_res = MagicMock()
        insert_res.data = [{"id": "p-new"}]
        table.execute.side_effect = [res, insert_res]
        result = upsert_genre_playlist(db, "g1", "Rock Mix")
        assert result == "p-new"

    def test_raises_when_insert_returns_no_data(self):
        db, table, res = make_db()
        res.data = []
        table.execute.return_value = res  # siempre vacío
        with pytest.raises(RuntimeError):
            upsert_genre_playlist(db, "g1", "Rock Mix")

class TestUpsertTrack:
    def test_calls_upsert_on_tracks_table(self):
        db, table, res = make_db()
        track = {"id": "t1", "title": "Creep"}
        upsert_track(db, track)
        db.table.assert_called_with("tracks")
        table.upsert.assert_called_once()

class TestInsertGenrePlaylistTracks:
    def test_deletes_existing_and_inserts(self):
        db, table, res = make_db()
        tracks = [{"id": "t1", "title": "Song 1"}, {"id": "t2", "title": "Song 2"}]
        count = insert_genre_playlist_tracks(db, "p1", tracks)
        table.delete.assert_called()
        assert count == 2

    def test_skips_tracks_without_id(self):
        db, table, res = make_db()
        tracks = [{"title": "No ID"}, {"id": "t1", "title": "Has ID"}]
        count = insert_genre_playlist_tracks(db, "p1", tracks)
        assert count == 1

    def test_empty_tracks_returns_zero(self):
        db, table, res = make_db()
        count = insert_genre_playlist_tracks(db, "p1", [])
        assert count == 0

    def test_continues_on_exception(self):
        db, table, res = make_db()
        # upsert falla en el primer track, continúa con el segundo
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("upsert failed")
            return table
        table.upsert.side_effect = side_effect
        tracks = [{"id": "t1"}, {"id": "t2"}]
        count = insert_genre_playlist_tracks(db, "p1", tracks)
        assert count == 1

    def test_positions_start_at_one(self):
        db, table, res = make_db()
        tracks = [{"id": "t1"}]
        insert_genre_playlist_tracks(db, "p1", tracks)
        insert_calls = [str(c) for c in table.insert.call_args_list]
        assert any("'position': 1" in c for c in insert_calls)

class TestGetAllGenres:
    def test_returns_data(self):
        db, table, res = make_db()
        res.data = [{"id": "g1", "name": "Rock"}]
        result = get_all_genres(db)
        assert result == [{"id": "g1", "name": "Rock"}]

    def test_returns_empty_when_no_data(self):
        db, table, res = make_db()
        res.data = None
        result = get_all_genres(db)
        assert result == []

class TestGetGenreBySlug:
    def test_returns_first_row(self):
        db, table, res = make_db()
        res.data = [{"id": "g1", "slug": "rock"}]
        result = get_genre_by_slug(db, "rock")
        assert result == {"id": "g1", "slug": "rock"}

    def test_returns_none_when_not_found(self):
        db, table, res = make_db()
        res.data = []
        result = get_genre_by_slug(db, "nonexistent")
        assert result is None

class TestGetPlaylistsByGenre:
    def test_returns_playlists_with_thumbnails(self):
        db, table, res = make_db()
        playlists_res = MagicMock()
        playlists_res.data = [{"id": "p1", "title": "Rock Mix"}]
        thumbs_res = MagicMock()
        thumbs_res.data = [{"playlist_id": "p1", "thumbnail_url": "http://img.jpg"}]
        table.execute.side_effect = [playlists_res, thumbs_res]
        result = get_playlists_by_genre(db, "g1")
        assert len(result) == 1
        assert result[0]["thumbnails"] == ["http://img.jpg"]

    def test_returns_empty_when_no_playlists(self):
        db, table, res = make_db()
        res.data = []
        result = get_playlists_by_genre(db, "g1")
        assert result == []

    def test_thumbnails_empty_on_rpc_error(self):
        db, table, res = make_db()
        playlists_res = MagicMock()
        playlists_res.data = [{"id": "p1", "title": "Rock Mix"}]
        table.execute.return_value = playlists_res
        rpc_mock = MagicMock()
        rpc_mock.execute.side_effect = Exception("rpc failed")
        db.rpc.return_value = rpc_mock
        result = get_playlists_by_genre(db, "g1")
        assert result[0]["thumbnails"] == []

class TestGetPlaylistById:
    def test_returns_playlist(self):
        db, table, res = make_db()
        res.data = [{"id": "p1", "title": "Rock Mix"}]
        result = get_playlist_by_id(db, "p1")
        assert result == {"id": "p1", "title": "Rock Mix"}

    def test_returns_none_when_not_found(self):
        db, table, res = make_db()
        res.data = []
        result = get_playlist_by_id(db, "nonexistent")
        assert result is None

class TestGetPlaylistTracks:
    def test_returns_tracks_in_order(self):
        db, table, res = make_db()
        positions_res = MagicMock()
        positions_res.data = [{"position": 1, "track_id": "t1"}, {"position": 2, "track_id": "t2"}]
        tracks_res = MagicMock()
        tracks_res.data = [
            {"track_id": "t1", "title": "Song 1", "artist": "A", "album": None,
             "duration_seconds": 180, "thumbnail_url": None, "artist_id": None},
            {"track_id": "t2", "title": "Song 2", "artist": "B", "album": None,
             "duration_seconds": 200, "thumbnail_url": None, "artist_id": None},
        ]
        table.execute.side_effect = [positions_res, tracks_res]
        result = get_playlist_tracks(db, "p1")
        assert len(result) == 2
        assert result[0]["title"] == "Song 1"
        assert result[1]["title"] == "Song 2"

    def test_returns_empty_when_no_positions(self):
        db, table, res = make_db()
        res.data = []
        result = get_playlist_tracks(db, "p1")
        assert result == []

    def test_returns_empty_when_no_track_ids(self):
        db, table, res = make_db()
        positions_res = MagicMock()
        positions_res.data = [{"position": 1, "track_id": None}]
        table.execute.return_value = positions_res
        result = get_playlist_tracks(db, "p1")
        assert result == []

    def test_missing_track_data_uses_empty_dict(self):
        db, table, res = make_db()
        positions_res = MagicMock()
        positions_res.data = [{"position": 1, "track_id": "t_missing"}]
        tracks_res = MagicMock()
        tracks_res.data = []  # track no encontrado en la tabla
        table.execute.side_effect = [positions_res, tracks_res]
        result = get_playlist_tracks(db, "p1")
        assert len(result) == 1
        assert result[0]["title"] is None

class TestGetGenreCategories:
    def test_returns_sorted_categories(self):
        db, table, res = make_db()
        res.data = [{"category": "rock"}, {"category": "jazz"}, {"category": "rock"}]
        result = get_genre_categories(db, "g1")
        assert result == ["jazz", "rock"]

    def test_returns_empty_when_no_data(self):
        db, table, res = make_db()
        res.data = []
        result = get_genre_categories(db, "g1")
        assert result == []
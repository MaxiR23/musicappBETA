# test/services/test_feed_repo.py
#
# Testeamos: services/feed_repo.py
# - _to_int                     → conversión segura a int
# - _row_from_album             → construye row desde album dict
# - _row_from_track             → construye row desde track dict
# - build_rows                  → mapea items según media_type
# - dedupe_rows                 → deduplica por id, mantiene el último
# - replace_feed                → DELETE + UPSERT con db mock
# - list_feed                   → SELECT con orden según kind/media_type
# - list_new_releases_for_artist → SELECT filtrado por artist_id
#

import pytest
from unittest.mock import MagicMock, patch, call
from services.feed_repo import (
    _to_int,
    _row_from_album,
    _row_from_track,
    build_rows,
    dedupe_rows,
    replace_feed,
    list_feed,
    list_new_releases_for_artist,
)

# ════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════
def make_db():
    """Crea un mock de DBClient con cadena fluente."""
    db = MagicMock()
    # Hace que cada llamada encadenada retorne el mismo mock
    table = MagicMock()
    db.table.return_value = table
    table.delete.return_value = table
    table.upsert.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.order.return_value = table
    table.limit.return_value = table
    res = MagicMock()
    res.count = 3
    res.data = []
    table.execute.return_value = res
    return db, table, res

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestToInt:
    def test_converts_int(self):
        assert _to_int(42) == 42

    def test_converts_string_int(self):
        assert _to_int("1997") == 1997

    def test_returns_none_on_none(self):
        assert _to_int(None) is None

    def test_returns_none_on_empty_string(self):
        assert _to_int("") is None

    def test_returns_none_on_non_numeric_string(self):
        assert _to_int("abc") is None

    def test_converts_float_truncating(self):
        assert _to_int(3.9) == 3

    def test_returns_none_on_list(self):
        assert _to_int([]) is None

    def test_converts_zero(self):
        assert _to_int(0) == 0

    def test_converts_zero_string(self):
        assert _to_int("0") == 0

class TestRowFromAlbum:
    def _album(self, **kwargs):
        base = {
            "id": "MPREb_abc",
            "title": "OK Computer",
            "artist": "Radiohead",
            "artist_id": "UCar1",
            "thumbnail": "http://img.jpg",
            "year": "1997",
            "release_date": "1997-05-21",
        }
        return {**base, **kwargs}

    def test_builds_correct_structure(self):
        row = _row_from_album("new_releases", self._album())
        assert row["kind"] == "new_releases"
        assert row["type"] == "album"
        assert row["id"] == "MPREb_abc"
        assert row["title"] == "OK Computer"
        assert row["artist"] == "Radiohead"
        assert row["artist_id"] == "UCar1"
        assert row["thumb"] == "http://img.jpg"
        assert row["year"] == 1997
        assert row["release_date"] == "1997-05-21"

    def test_url_uses_id(self):
        row = _row_from_album("new_releases", self._album(id="MPREb_xyz"))
        assert row["url"] == "/browse/MPREb_xyz"

    def test_url_is_none_when_no_id(self):
        row = _row_from_album("new_releases", self._album(id=None))
        assert row["url"] is None

    def test_album_and_album_id_are_none(self):
        row = _row_from_album("new_releases", self._album())
        assert row["album"] is None
        assert row["album_id"] is None

    def test_duration_seconds_is_none(self):
        row = _row_from_album("new_releases", self._album())
        assert row["duration_seconds"] is None

    def test_year_converted_to_int(self):
        row = _row_from_album("new_releases", self._album(year="2003"))
        assert row["year"] == 2003

    def test_year_none_when_missing(self):
        row = _row_from_album("new_releases", self._album(year=None))
        assert row["year"] is None

    def test_missing_fields_return_none(self):
        row = _row_from_album("trending", {})
        assert row["id"] is None
        assert row["title"] is None
        assert row["url"] is None

class TestRowFromTrack:
    def _track(self, **kwargs):
        base = {
            "id": "dQw4w9WgXcQ",
            "title": "Creep",
            "artist": "Radiohead",
            "artist_id": "UCar1",
            "thumbnail_url": "http://img.jpg",
            "album": "Pablo Honey",
            "album_id": "MPREb_album",
            "duration_seconds": "230",
            "release_date": "1992-09-21",
        }
        return {**base, **kwargs}

    def test_builds_correct_structure(self):
        row = _row_from_track("trending", self._track())
        assert row["kind"] == "trending"
        assert row["type"] == "track"
        assert row["id"] == "dQw4w9WgXcQ"
        assert row["title"] == "Creep"
        assert row["album"] == "Pablo Honey"
        assert row["album_id"] == "MPREb_album"
        assert row["duration_seconds"] == 230

    def test_url_uses_id(self):
        row = _row_from_track("trending", self._track(id="abc123"))
        assert row["url"] == "/watch/abc123"

    def test_url_is_none_when_no_id(self):
        row = _row_from_track("trending", self._track(id=None))
        assert row["url"] is None

    def test_year_is_none(self):
        row = _row_from_track("trending", self._track())
        assert row["year"] is None

    def test_duration_seconds_converted_to_int(self):
        row = _row_from_track("trending", self._track(duration_seconds="180"))
        assert row["duration_seconds"] == 180

    def test_duration_seconds_none_when_missing(self):
        row = _row_from_track("trending", self._track(duration_seconds=None))
        assert row["duration_seconds"] is None

    def test_thumb_from_thumbnail_url(self):
        row = _row_from_track("trending", self._track(thumbnail_url="http://thumb.jpg"))
        assert row["thumb"] == "http://thumb.jpg"

class TestBuildRows:
    def test_builds_album_rows(self):
        items = [{"id": "a1", "title": "Album 1", "year": "2020"}]
        rows = build_rows("new_releases", "album", items)
        assert len(rows) == 1
        assert rows[0]["type"] == "album"

    def test_builds_track_rows(self):
        items = [{"id": "t1", "title": "Track 1"}]
        rows = build_rows("trending", "track", items)
        assert len(rows) == 1
        assert rows[0]["type"] == "track"

    def test_non_album_media_type_uses_track_mapper(self):
        items = [{"id": "t1"}]
        rows = build_rows("trending", "something_else", items)
        assert rows[0]["type"] == "track"

    def test_empty_items_returns_empty_list(self):
        assert build_rows("new_releases", "album", []) == []

    def test_kind_propagated_to_all_rows(self):
        items = [{"id": f"a{i}"} for i in range(3)]
        rows = build_rows("trending", "album", items)
        assert all(r["kind"] == "trending" for r in rows)

    def test_accepts_generator(self):
        items = ({"id": f"a{i}"} for i in range(3))
        rows = build_rows("new_releases", "album", items)
        assert len(rows) == 3

class TestDedupeRows:
    def test_keeps_last_occurrence_of_duplicate_id(self):
        rows = [
            {"id": "a1", "title": "First"},
            {"id": "a1", "title": "Second"},
        ]
        result = dedupe_rows(rows)
        assert len(result) == 1
        assert result[0]["title"] == "Second"

    def test_preserves_unique_rows(self):
        rows = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        assert len(dedupe_rows(rows)) == 3

    def test_skips_rows_without_id(self):
        rows = [{"id": None, "title": "No ID"}, {"id": "a1", "title": "Has ID"}]
        result = dedupe_rows(rows)
        assert len(result) == 1
        assert result[0]["id"] == "a1"

    def test_empty_list_returns_empty(self):
        assert dedupe_rows([]) == []

    def test_all_rows_without_id_returns_empty(self):
        rows = [{"title": "A"}, {"title": "B"}]
        assert dedupe_rows(rows) == []

    def test_order_reflects_insertion_order(self):
        # dict mantiene insertion order: a1 se sobreescribe en su posición original
        rows = [{"id": "a1", "title": "First"}, {"id": "a2"}, {"id": "a1", "title": "Last"}]
        result = dedupe_rows(rows)
        ids = [r["id"] for r in result]
        assert ids == ["a1", "a2"]
        assert result[0]["title"] == "Last"  # valor es el último

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestReplaceFeed:
    def test_deletes_and_upserts(self):
        db, table, res = make_db()
        items = [{"id": "a1", "title": "X", "year": "2020"}]
        deleted, upserted = replace_feed(db, "new_releases", "album", items)
        table.delete.assert_called_once()
        table.upsert.assert_called_once()
        assert upserted == 1

    def test_returns_zero_upserted_when_no_items(self):
        db, table, res = make_db()
        deleted, upserted = replace_feed(db, "new_releases", "album", [])
        table.upsert.assert_not_called()
        assert upserted == 0

    def test_deduplicates_before_upsert(self):
        db, table, res = make_db()
        items = [{"id": "a1"}, {"id": "a1"}]  # duplicado
        _, upserted = replace_feed(db, "trending", "album", items)
        assert upserted == 1

    def test_returns_deleted_count(self):
        db, table, res = make_db()
        res.count = 5
        deleted, _ = replace_feed(db, "new_releases", "album", [])
        assert deleted == 5

    def test_handles_delete_exception(self):
        db, table, res = make_db()
        table.delete.return_value.eq.side_effect = Exception("DB error")
        # no debe lanzar
        deleted, upserted = replace_feed(db, "new_releases", "album", [])
        assert deleted is None

    def test_handles_upsert_exception(self):
        db, table, res = make_db()
        table.upsert.return_value.execute.side_effect = Exception("upsert error")
        items = [{"id": "a1"}]
        deleted, upserted = replace_feed(db, "new_releases", "album", items)
        assert upserted == 0


class TestListFeed:
    def test_returns_data_from_db(self):
        db, table, res = make_db()
        res.data = [{"id": "a1"}, {"id": "a2"}]
        result = list_feed(db, "new_releases", "album")
        assert result == [{"id": "a1"}, {"id": "a2"}]

    def test_orders_by_release_date_for_new_releases_album(self):
        db, table, res = make_db()
        res.data = []
        list_feed(db, "new_releases", "album")
        order_calls = [str(c) for c in table.order.call_args_list]
        assert any("release_date" in c for c in order_calls)

    def test_orders_by_id_for_other_kinds(self):
        db, table, res = make_db()
        res.data = []
        list_feed(db, "trending", "track")
        order_calls = [str(c) for c in table.order.call_args_list]
        assert any("id" in c for c in order_calls)

    def test_returns_empty_list_on_exception(self):
        db, table, res = make_db()
        table.execute.side_effect = Exception("db error")
        result = list_feed(db, "new_releases", "album")
        assert result == []

    def test_returns_empty_when_data_is_none(self):
        db, table, res = make_db()
        res.data = None
        result = list_feed(db, "new_releases", "album")
        assert result == []

    def test_respects_limit(self):
        db, table, res = make_db()
        res.data = []
        list_feed(db, "new_releases", "album", limit=5)
        table.limit.assert_called_with(5)

class TestListNewReleasesForArtist:
    def test_returns_releases_for_artist(self):
        db, table, res = make_db()
        res.data = [{"id": "a1", "artist_id": "UCar1"}]
        result = list_new_releases_for_artist(db, "UCar1")
        assert result == [{"id": "a1", "artist_id": "UCar1"}]

    def test_returns_empty_list_on_exception(self):
        db, table, res = make_db()
        table.execute.side_effect = Exception("db error")
        result = list_new_releases_for_artist(db, "UCar1")
        assert result == []

    def test_returns_empty_when_data_is_none(self):
        db, table, res = make_db()
        res.data = None
        result = list_new_releases_for_artist(db, "UCar1")
        assert result == []

    def test_respects_limit(self):
        db, table, res = make_db()
        res.data = []
        list_new_releases_for_artist(db, "UCar1", limit=4)
        table.limit.assert_called_with(4)

    def test_filters_by_artist_id(self):
        db, table, res = make_db()
        res.data = []
        list_new_releases_for_artist(db, "UCar1")
        eq_calls = [str(c) for c in table.eq.call_args_list]
        assert any("UCar1" in c for c in eq_calls)
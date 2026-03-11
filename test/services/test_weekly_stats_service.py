# test/services/test_weekly_stats_service.py
#
# Testeamos: services/weekly_stats_service.py
# - get_week_start          → lunes de la semana PASADA
# - build_cache_suffix      → user_id:entity_type
# - extract_stats_from_response → extrae lista stats de resp
# - slice_stats             → aplica limit opcional
# - parse_include_types     → parsea string CSV o default
# - get_weekly_stats        → cache → db → set_cached
# - get_weekly_artists/albums/tracks → wrappers
# - get_weekly_summary      → orquesta según include
#

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from services.weekly_stats_service import (
    get_week_start,
    build_cache_suffix,
    extract_stats_from_response,
    slice_stats,
    parse_include_types,
    get_weekly_stats,
    get_weekly_artists,
    get_weekly_albums,
    get_weekly_tracks,
    get_weekly_summary,
)

# ════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════
def make_db():
    db = MagicMock()
    table = MagicMock()
    db.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.maybe_single.return_value = table
    res = MagicMock()
    res.data = {"stats": []}
    table.execute.return_value = res
    return db, table, res

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestGetWeekStart:
    def test_returns_a_monday(self):
        result = get_week_start()
        assert result.weekday() == 0  # 0 = lunes

    def test_is_last_week_monday(self):
        today = date.today()
        current_monday = today - timedelta(days=today.weekday())
        expected = current_monday - timedelta(days=7)
        assert get_week_start() == expected

    def test_is_before_this_monday(self):
        today = date.today()
        this_monday = today - timedelta(days=today.weekday())
        assert get_week_start() < this_monday

    def test_accepts_explicit_date(self):
        # miércoles 2024-03-13 → lunes semana anterior = 2024-03-04
        d = date(2024, 3, 13)
        assert get_week_start(d) == date(2024, 3, 4)

    def test_explicit_monday_returns_previous_monday(self):
        # lunes 2024-03-11 → lunes semana anterior = 2024-03-04
        d = date(2024, 3, 11)
        assert get_week_start(d) == date(2024, 3, 4)

    def test_explicit_sunday_returns_correct_monday(self):
        # domingo 2024-03-10 → su lunes es 2024-03-04 → semana anterior = 2024-02-26
        d = date(2024, 3, 10)
        assert get_week_start(d) == date(2024, 2, 26)

    def test_returns_date_object(self):
        assert isinstance(get_week_start(), date)

class TestBuildCacheSuffix:
    def test_builds_correct_format(self):
        assert build_cache_suffix("user-1", "artist") == "user-1:artist"

    def test_unique_per_user_and_type(self):
        assert build_cache_suffix("u1", "artist") != build_cache_suffix("u2", "artist")
        assert build_cache_suffix("u1", "artist") != build_cache_suffix("u1", "album")

class TestExtractStatsFromResponse:
    def test_extracts_stats_list(self):
        resp = MagicMock()
        resp.data = {"stats": [{"id": "a1"}]}
        assert extract_stats_from_response(resp) == [{"id": "a1"}]

    def test_returns_empty_when_resp_is_none(self):
        assert extract_stats_from_response(None) == []

    def test_returns_empty_when_data_is_none(self):
        resp = MagicMock()
        resp.data = None
        assert extract_stats_from_response(resp) == []

    def test_returns_empty_when_stats_key_missing(self):
        resp = MagicMock()
        resp.data = {"other": "x"}
        assert extract_stats_from_response(resp) == []

    def test_returns_empty_when_stats_is_none(self):
        resp = MagicMock()
        resp.data = {"stats": None}
        assert extract_stats_from_response(resp) == []

    def test_returns_empty_when_resp_falsy(self):
        assert extract_stats_from_response(False) == []
        assert extract_stats_from_response(0) == []


class TestSliceStats:
    def test_slices_to_limit(self):
        stats = [{"id": f"a{i}"} for i in range(10)]
        assert len(slice_stats(stats, 3)) == 3

    def test_none_limit_returns_all(self):
        stats = [{"id": f"a{i}"} for i in range(10)]
        assert len(slice_stats(stats, None)) == 10

    def test_limit_larger_than_list_returns_all(self):
        assert len(slice_stats([{"id": "a1"}], 100)) == 1

    def test_empty_stats_returns_empty(self):
        assert slice_stats([], 5) == []

    def test_limit_zero_returns_all(self):
        # 0 es falsy → if limit es False → retorna todo
        stats = [{"id": "a1"}]
        assert slice_stats(stats, 0) == stats

class TestParseIncludeTypes:
    def test_none_returns_all_defaults(self):
        assert parse_include_types(None) == ["artists", "albums", "tracks"]

    def test_empty_string_returns_all_defaults(self):
        assert parse_include_types("") == ["artists", "albums", "tracks"]

    def test_single_type(self):
        assert parse_include_types("artists") == ["artists"]

    def test_multiple_types(self):
        assert parse_include_types("artists,tracks") == ["artists", "tracks"]

    def test_strips_whitespace(self):
        assert parse_include_types("artists, albums") == ["artists", "albums"]

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestGetWeeklyStats:
    def test_returns_cached_when_available(self):
        db, _, _ = make_db()
        cached = [{"id": "a1"}]
        with patch("services.weekly_stats_service.get_cached", return_value=cached):
            result = get_weekly_stats(db, "u1", "artist")
        assert result == cached

    def test_cached_empty_list_does_not_fetch(self):
        db, table, _ = make_db()
        with patch("services.weekly_stats_service.get_cached", return_value=[]):
            get_weekly_stats(db, "u1", "artist")
        table.execute.assert_not_called()

    def test_fetches_from_db_on_cache_miss(self):
        db, table, res = make_db()
        res.data = {"stats": [{"id": "a1"}]}
        with patch("services.weekly_stats_service.get_cached", return_value=None), \
             patch("services.weekly_stats_service.set_cached"):
            result = get_weekly_stats(db, "u1", "artist")
        assert result == [{"id": "a1"}]

    def test_caches_result_after_fetch(self):
        db, table, res = make_db()
        res.data = {"stats": [{"id": "a1"}]}
        with patch("services.weekly_stats_service.get_cached", return_value=None), \
             patch("services.weekly_stats_service.set_cached") as mock_set:
            get_weekly_stats(db, "u1", "artist")
        mock_set.assert_called_once()

    def test_applies_limit_on_cached(self):
        db, _, _ = make_db()
        cached = [{"id": f"a{i}"} for i in range(10)]
        with patch("services.weekly_stats_service.get_cached", return_value=cached):
            result = get_weekly_stats(db, "u1", "artist", limit=3)
        assert len(result) == 3

    def test_applies_limit_on_fetched(self):
        db, table, res = make_db()
        res.data = {"stats": [{"id": f"a{i}"} for i in range(10)]}
        with patch("services.weekly_stats_service.get_cached", return_value=None), \
             patch("services.weekly_stats_service.set_cached"):
            result = get_weekly_stats(db, "u1", "artist", limit=4)
        assert len(result) == 4

    def test_returns_empty_on_exception(self):
        db, table, _ = make_db()
        table.execute.side_effect = Exception("db error")
        with patch("services.weekly_stats_service.get_cached", return_value=None), \
             patch("services.weekly_stats_service.set_cached"):
            result = get_weekly_stats(db, "u1", "artist")
        assert result == []

    def test_uses_correct_cache_suffix(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_cached") as mock_get:
            mock_get.return_value = []
            get_weekly_stats(db, "user-42", "track")
        assert "user-42:track" in str(mock_get.call_args)

    def test_queries_correct_entity_type(self):
        db, table, res = make_db()
        res.data = {"stats": []}
        with patch("services.weekly_stats_service.get_cached", return_value=None), \
             patch("services.weekly_stats_service.set_cached"):
            get_weekly_stats(db, "u1", "album")
        eq_calls = [str(c) for c in table.eq.call_args_list]
        assert any("album" in c for c in eq_calls)

class TestGetWeeklyArtistsAlbumsTracks:
    def test_get_weekly_artists_calls_correct_type(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats") as mock:
            mock.return_value = []
            get_weekly_artists(db, "u1")
        assert mock.call_args[0][2] == "artist"

    def test_get_weekly_albums_calls_correct_type(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats") as mock:
            mock.return_value = []
            get_weekly_albums(db, "u1")
        assert mock.call_args[0][2] == "album"

    def test_get_weekly_tracks_calls_correct_type(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats") as mock:
            mock.return_value = []
            get_weekly_tracks(db, "u1")
        assert mock.call_args[0][2] == "track"

    def test_passes_limit(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats") as mock:
            mock.return_value = []
            get_weekly_artists(db, "u1", limit=5)
        assert mock.call_args[1]["limit"] == 5

class TestGetWeeklySummary:
    def test_returns_all_types_by_default(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats", return_value=[]):
            result = get_weekly_summary(db, "u1")
        assert "artists" in result
        assert "albums" in result
        assert "tracks" in result

    def test_includes_week_start(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats", return_value=[]):
            result = get_weekly_summary(db, "u1")
        assert "week_start" in result
        assert result["week_start"] == get_week_start().isoformat()

    def test_respects_include_filter(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats", return_value=[]):
            result = get_weekly_summary(db, "u1", include="artists")
        assert "artists" in result
        assert "albums" not in result
        assert "tracks" not in result

    def test_include_multiple_types(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats", return_value=[]):
            result = get_weekly_summary(db, "u1", include="albums,tracks")
        assert "albums" in result
        assert "tracks" in result
        assert "artists" not in result

    def test_passes_limit_to_each_type(self):
        db, _, _ = make_db()
        with patch("services.weekly_stats_service.get_weekly_stats") as mock:
            mock.return_value = []
            get_weekly_summary(db, "u1", limit=5)
        for c in mock.call_args_list:
            assert c[1]["limit"] == 5
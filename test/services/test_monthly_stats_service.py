# test/services/test_monthly_stats_service.py
#
# Testeamos: services/monthly_stats_service.py
# - get_last_month_start        → fecha del primer día del mes anterior
# - build_cache_suffix          → construye suffix user_id:entity_type
# - extract_stats_from_response → extrae lista stats de resp
# - slice_stats                 → aplica limit opcional
# - parse_include_types         → parsea string CSV o default
# - _get_monthly_stats          → cache → db → set_cached
# - get_monthly_artists/albums/tracks → wrappers de _get_monthly_stats
# - get_monthly_summary         → orquesta según include
#

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch, call
from services.monthly_stats_service import (
    get_last_month_start,
    build_cache_suffix,
    extract_stats_from_response,
    slice_stats,
    parse_include_types,
    get_monthly_artists,
    get_monthly_albums,
    get_monthly_tracks,
    get_monthly_summary,
    _get_monthly_stats,
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
class TestGetLastMonthStart:
    def test_returns_first_day_of_previous_month(self):
        result = get_last_month_start()
        assert result.day == 1

    def test_is_before_today(self):
        assert get_last_month_start() < date.today()

    def test_is_last_month(self):
        today = date.today()
        first_of_current = today.replace(day=1)
        expected = (first_of_current - timedelta(days=1)).replace(day=1)
        assert get_last_month_start() == expected

    def test_returns_date_object(self):
        assert isinstance(get_last_month_start(), date)

class TestBuildCacheSuffix:
    def test_builds_correct_format(self):
        assert build_cache_suffix("user-1", "artist") == "user-1:artist"

    def test_different_entity_types(self):
        assert build_cache_suffix("u1", "album") == "u1:album"
        assert build_cache_suffix("u1", "track") == "u1:track"

    def test_suffix_is_unique_per_user_and_type(self):
        s1 = build_cache_suffix("user-1", "artist")
        s2 = build_cache_suffix("user-2", "artist")
        s3 = build_cache_suffix("user-1", "album")
        assert s1 != s2
        assert s1 != s3

class TestExtractStatsFromResponse:
    def test_extracts_stats_list(self):
        resp = MagicMock()
        resp.data = {"stats": [{"id": "a1"}, {"id": "a2"}]}
        result = extract_stats_from_response(resp)
        assert result == [{"id": "a1"}, {"id": "a2"}]

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

    def test_returns_empty_when_resp_is_falsy(self):
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
        stats = [{"id": "a1"}]
        assert len(slice_stats(stats, 100)) == 1

    def test_empty_stats_returns_empty(self):
        assert slice_stats([], 5) == []

    def test_limit_zero_returns_empty(self):
        stats = [{"id": "a1"}]
        assert slice_stats(stats, 0) == [{"id": "a1"}]

class TestParseIncludeTypes:
    def test_none_returns_all_defaults(self):
        assert parse_include_types(None) == ["artists", "albums", "tracks"]

    def test_empty_string_returns_all_defaults(self):
        assert parse_include_types("") == ["artists", "albums", "tracks"]

    def test_single_type(self):
        assert parse_include_types("artists") == ["artists"]

    def test_multiple_types(self):
        result = parse_include_types("artists,tracks")
        assert result == ["artists", "tracks"]

    def test_strips_whitespace(self):
        result = parse_include_types("artists, albums, tracks")
        assert result == ["artists", "albums", "tracks"]

    def test_preserves_custom_types(self):
        result = parse_include_types("artists,custom_type")
        assert "custom_type" in result

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestGetMonthlyStats:
    def test_returns_cached_when_available(self):
        db, _, _ = make_db()
        cached = [{"id": "a1"}]
        with patch("services.monthly_stats_service.get_cached", return_value=cached):
            result = _get_monthly_stats(db, "u1", "artist")
        assert result == cached

    def test_fetches_from_db_on_cache_miss(self):
        db, table, res = make_db()
        res.data = {"stats": [{"id": "a1"}]}
        with patch("services.monthly_stats_service.get_cached", return_value=None), \
             patch("services.monthly_stats_service.set_cached"):
            result = _get_monthly_stats(db, "u1", "artist")
        assert result == [{"id": "a1"}]

    def test_caches_result_after_fetch(self):
        db, table, res = make_db()
        res.data = {"stats": [{"id": "a1"}]}
        with patch("services.monthly_stats_service.get_cached", return_value=None), \
             patch("services.monthly_stats_service.set_cached") as mock_set:
            _get_monthly_stats(db, "u1", "artist")
        mock_set.assert_called_once()

    def test_applies_limit_on_cached(self):
        db, _, _ = make_db()
        cached = [{"id": f"a{i}"} for i in range(10)]
        with patch("services.monthly_stats_service.get_cached", return_value=cached):
            result = _get_monthly_stats(db, "u1", "artist", limit=3)
        assert len(result) == 3

    def test_applies_limit_on_fetched(self):
        db, table, res = make_db()
        res.data = {"stats": [{"id": f"a{i}"} for i in range(10)]}
        with patch("services.monthly_stats_service.get_cached", return_value=None), \
             patch("services.monthly_stats_service.set_cached"):
            result = _get_monthly_stats(db, "u1", "artist", limit=4)
        assert len(result) == 4

    def test_returns_empty_on_exception(self):
        db, table, _ = make_db()
        table.execute.side_effect = Exception("db error")
        with patch("services.monthly_stats_service.get_cached", return_value=None), \
             patch("services.monthly_stats_service.set_cached"):
            result = _get_monthly_stats(db, "u1", "artist")
        assert result == []

    def test_uses_correct_cache_suffix(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service.get_cached") as mock_get:
            mock_get.return_value = []
            _get_monthly_stats(db, "user-42", "album")
        suffix_used = str(mock_get.call_args)
        assert "user-42:album" in suffix_used

    def test_queries_correct_entity_type(self):
        db, table, res = make_db()
        res.data = {"stats": []}
        with patch("services.monthly_stats_service.get_cached", return_value=None), \
             patch("services.monthly_stats_service.set_cached"):
            _get_monthly_stats(db, "u1", "track")
        eq_calls = [str(c) for c in table.eq.call_args_list]
        assert any("track" in c for c in eq_calls)

class TestGetMonthlyArtistsAlbumsTracks:
    def test_get_monthly_artists_calls_correct_type(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats") as mock:
            mock.return_value = []
            get_monthly_artists(db, "u1")
        assert mock.call_args[0][2] == "artist"

    def test_get_monthly_albums_calls_correct_type(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats") as mock:
            mock.return_value = []
            get_monthly_albums(db, "u1")
        assert mock.call_args[0][2] == "album"

    def test_get_monthly_tracks_calls_correct_type(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats") as mock:
            mock.return_value = []
            get_monthly_tracks(db, "u1")
        assert mock.call_args[0][2] == "track"

    def test_passes_limit(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats") as mock:
            mock.return_value = []
            get_monthly_artists(db, "u1", limit=5)
        assert mock.call_args[1]["limit"] == 5

class TestGetMonthlySummary:
    def test_returns_all_types_by_default(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats", return_value=[]):
            result = get_monthly_summary(db, "u1")
        assert "artists" in result
        assert "albums" in result
        assert "tracks" in result

    def test_includes_month_start(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats", return_value=[]):
            result = get_monthly_summary(db, "u1")
        assert "month_start" in result
        assert result["month_start"] == get_last_month_start().isoformat()

    def test_respects_include_filter(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats", return_value=[]):
            result = get_monthly_summary(db, "u1", include="artists")
        assert "artists" in result
        assert "albums" not in result
        assert "tracks" not in result

    def test_include_multiple_types(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats", return_value=[]):
            result = get_monthly_summary(db, "u1", include="artists,tracks")
        assert "artists" in result
        assert "tracks" in result
        assert "albums" not in result

    def test_passes_limit_to_each_type(self):
        db, _, _ = make_db()
        with patch("services.monthly_stats_service._get_monthly_stats") as mock:
            mock.return_value = []
            get_monthly_summary(db, "u1", limit=5)
        for c in mock.call_args_list:
            assert c[1]["limit"] == 5
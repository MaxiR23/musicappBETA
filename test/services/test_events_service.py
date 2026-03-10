# test/services/test_events_service.py
#
# Testeamos: services/events_service.py
# - normalize_artist_name       → normaliza nombre para cache key
# - extract_events_from_cache   → extrae eventos de resultado cacheado
# - extract_events_from_result  → extrae eventos de resultado de fetch
# - get_events_by_artist_name   → cache → fetch → set_cached
# - get_events_cached_only      → solo cache, nunca fetch
# - schedule_events_refresh     → encola bg task, no bloquea
#

import pytest
from unittest.mock import patch, MagicMock, call
from services.events_service import (
    normalize_artist_name,
    extract_events_from_cache,
    extract_events_from_result,
    get_events_by_artist_name,
    get_events_cached_only,
    schedule_events_refresh,
)

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestNormalizeArtistName:
    def test_lowercases_name(self):
        assert normalize_artist_name("Radiohead") == "radiohead"

    def test_strips_whitespace(self):
        assert normalize_artist_name("  Tame Impala  ") == "tame impala"

    def test_lowercase_and_strip_combined(self):
        assert normalize_artist_name("  Pink Floyd  ") == "pink floyd"

    def test_returns_none_on_none(self):
        assert normalize_artist_name(None) is None

    def test_returns_none_on_empty_string(self):
        assert normalize_artist_name("") is None

    def test_returns_none_on_whitespace_only(self):
        assert normalize_artist_name("   ") is None

    def test_preserves_internal_spaces(self):
        assert normalize_artist_name("The Beatles") == "the beatles"

class TestExtractEventsFromCache:
    def test_returns_events_from_valid_cache(self):
        cached = {"events": [{"id": "e1"}, {"id": "e2"}]}
        assert extract_events_from_cache(cached, 10) == [{"id": "e1"}, {"id": "e2"}]

    def test_respects_limit(self):
        cached = {"events": [{"id": f"e{i}"} for i in range(10)]}
        result = extract_events_from_cache(cached, 3)
        assert len(result) == 3

    def test_returns_empty_when_cache_is_none(self):
        assert extract_events_from_cache(None, 10) == []

    def test_returns_empty_when_cache_is_not_dict(self):
        assert extract_events_from_cache("string", 10) == []
        assert extract_events_from_cache([], 10) == []
        assert extract_events_from_cache(42, 10) == []

    def test_returns_empty_when_events_key_missing(self):
        assert extract_events_from_cache({"other": "data"}, 10) == []

    def test_returns_empty_when_events_is_none(self):
        assert extract_events_from_cache({"events": None}, 10) == []

    def test_returns_empty_when_events_is_empty_list(self):
        assert extract_events_from_cache({"events": []}, 10) == []

    def test_limit_zero_returns_empty(self):
        cached = {"events": [{"id": "e1"}]}
        assert extract_events_from_cache(cached, 0) == []

class TestExtractEventsFromResult:
    def test_returns_events_from_valid_result(self):
        result = {"events": [{"id": "e1"}]}
        assert extract_events_from_result(result, 10) == [{"id": "e1"}]

    def test_respects_limit(self):
        result = {"events": [{"id": f"e{i}"} for i in range(10)]}
        assert len(extract_events_from_result(result, 4)) == 4

    def test_returns_empty_when_result_is_none(self):
        assert extract_events_from_result(None, 10) == []

    def test_returns_empty_when_result_is_not_dict(self):
        assert extract_events_from_result("string", 10) == []

    def test_returns_empty_when_events_key_missing(self):
        assert extract_events_from_result({}, 10) == []

    def test_returns_empty_when_events_is_none(self):
        assert extract_events_from_result({"events": None}, 10) == []

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestGetEventsByArtistName:
    def test_returns_cached_events_when_available(self):
        cached = {"events": [{"id": "e1"}]}
        with patch("services.events_service.get_cached", return_value=cached):
            result = get_events_by_artist_name("Radiohead")
        assert result == [{"id": "e1"}]

    def test_fetches_when_cache_miss(self):
        fetch_result = {"events": [{"id": "e2"}], "attractionId": None}
        with patch("services.events_service.get_cached", return_value=None), \
             patch("services.events_service.fetch_upcoming_events_by_artist", return_value=fetch_result), \
             patch("services.events_service.set_cached"):
            result = get_events_by_artist_name("Radiohead")
        assert result == [{"id": "e2"}]

    def test_caches_result_after_fetch(self):
        fetch_result = {"events": [{"id": "e1"}], "attractionId": None}
        with patch("services.events_service.get_cached", return_value=None), \
             patch("services.events_service.fetch_upcoming_events_by_artist", return_value=fetch_result), \
             patch("services.events_service.set_cached") as mock_set:
            get_events_by_artist_name("Radiohead")
        mock_set.assert_called_once()

    def test_caches_by_attraction_id_when_present(self):
        fetch_result = {"events": [{"id": "e1"}], "attractionId": "K8vZ123"}
        with patch("services.events_service.get_cached", return_value=None), \
             patch("services.events_service.fetch_upcoming_events_by_artist", return_value=fetch_result), \
             patch("services.events_service.set_cached") as mock_set:
            get_events_by_artist_name("Radiohead")
        assert mock_set.call_count == 2
        calls_suffixes = [c.kwargs.get("suffix") or c.args[2] for c in mock_set.call_args_list]
        assert any("aid:K8vZ123" in str(s) for s in calls_suffixes)

    def test_skips_cache_when_use_cache_false(self):
        fetch_result = {"events": [], "attractionId": None}
        with patch("services.events_service.get_cached") as mock_get, \
             patch("services.events_service.fetch_upcoming_events_by_artist", return_value=fetch_result), \
             patch("services.events_service.set_cached"):
            get_events_by_artist_name("Radiohead", use_cache=False)
        mock_get.assert_not_called()

    def test_returns_empty_on_invalid_artist_name(self):
        assert get_events_by_artist_name("") == []
        assert get_events_by_artist_name("   ") == []

    def test_returns_empty_when_fetch_returns_non_dict(self):
        with patch("services.events_service.get_cached", return_value=None), \
             patch("services.events_service.fetch_upcoming_events_by_artist", return_value=None):
            assert get_events_by_artist_name("Radiohead") == []

    def test_returns_empty_on_fetch_exception(self):
        with patch("services.events_service.get_cached", return_value=None), \
             patch("services.events_service.fetch_upcoming_events_by_artist", side_effect=Exception("timeout")):
            assert get_events_by_artist_name("Radiohead") == []

    def test_respects_limit(self):
        cached = {"events": [{"id": f"e{i}"} for i in range(10)]}
        with patch("services.events_service.get_cached", return_value=cached):
            result = get_events_by_artist_name("Radiohead", limit=3)
        assert len(result) == 3

    def test_fetches_when_cache_has_no_events(self):
        fetch_result = {"events": [{"id": "fresh"}], "attractionId": None}
        with patch("services.events_service.get_cached", return_value={"events": []}), \
             patch("services.events_service.fetch_upcoming_events_by_artist", return_value=fetch_result) as mock_fetch, \
             patch("services.events_service.set_cached"):
            result = get_events_by_artist_name("Radiohead")
        mock_fetch.assert_called_once()
        assert result == [{"id": "fresh"}]

class TestGetEventsCachedOnly:
    def test_returns_cached_events(self):
        cached = {"events": [{"id": "e1"}]}
        with patch("services.events_service.get_cached", return_value=cached):
            result = get_events_cached_only("Radiohead")
        assert result == [{"id": "e1"}]

    def test_never_calls_fetch(self):
        with patch("services.events_service.get_cached", return_value=None), \
             patch("services.events_service.fetch_upcoming_events_by_artist") as mock_fetch:
            result = get_events_cached_only("Radiohead")
        mock_fetch.assert_not_called()
        assert result == []

    def test_returns_empty_on_invalid_artist_name(self):
        assert get_events_cached_only("") == []
        assert get_events_cached_only("   ") == []

    def test_respects_limit(self):
        cached = {"events": [{"id": f"e{i}"} for i in range(10)]}
        with patch("services.events_service.get_cached", return_value=cached):
            result = get_events_cached_only("Radiohead", limit=2)
        assert len(result) == 2

    def test_uses_normalized_name_as_cache_key(self):
        with patch("services.events_service.get_cached", return_value=None) as mock_get:
            get_events_cached_only("  Radiohead  ")
        call_kwargs = mock_get.call_args
        assert "radiohead" in str(call_kwargs)

class TestScheduleEventsRefresh:
    def test_submits_background_task(self):
        mock_executor = MagicMock()
        with patch("services.executor._EXECUTOR", mock_executor):
            schedule_events_refresh("Radiohead")
        mock_executor.submit.assert_called_once()

    def test_does_nothing_on_empty_name(self):
        mock_executor = MagicMock()
        with patch("services.executor._EXECUTOR", mock_executor):
            schedule_events_refresh("")
            schedule_events_refresh("   ")
        mock_executor.submit.assert_not_called()

    def test_does_nothing_on_none_name(self):
        mock_executor = MagicMock()
        with patch("services.executor._EXECUTOR", mock_executor):
            schedule_events_refresh(None)
        mock_executor.submit.assert_not_called()

    def test_does_not_raise_when_executor_fails(self):
        mock_executor = MagicMock()
        mock_executor.submit.side_effect = Exception("executor down")
        with patch("services.executor._EXECUTOR", mock_executor):
            schedule_events_refresh("Radiohead")  # no debe lanzar
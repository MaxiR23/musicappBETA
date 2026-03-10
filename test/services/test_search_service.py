# test/services/test_search_service.py
#
# Testeamos: services/search_service.py
# - build_cache_key         → lowercase + trunca a 100 chars
# - build_search_payload    → construye dict final
# - build_error_payload     → construye dict de error
# - has_valid_data          → verifica si hay datos útiles
# - get_warm_ids            → extrae video_ids para warming
# - search                  → cache → fetch → build → cache
#

import pytest
from unittest.mock import patch, MagicMock
from services.search_service import (
    build_cache_key,
    build_search_payload,
    build_error_payload,
    has_valid_data,
    get_warm_ids,
    search,
)

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestBuildCacheKey:
    def test_lowercases_query(self):
        assert build_cache_key("Radiohead") == "radiohead"

    def test_truncates_to_100_chars(self):
        long_query = "a" * 150
        assert len(build_cache_key(long_query)) == 100

    def test_short_query_unchanged_except_lowercase(self):
        assert build_cache_key("OK Computer") == "ok computer"

    def test_exactly_100_chars_not_truncated(self):
        query = "a" * 100
        assert build_cache_key(query) == query

    def test_101_chars_truncated(self):
        query = "a" * 101
        assert len(build_cache_key(query)) == 100

    def test_empty_string(self):
        assert build_cache_key("") == ""

class TestBuildSearchPayload:
    def test_builds_correct_structure(self):
        result = build_search_payload(
            query="radiohead",
            artist={"name": "Radiohead"},
            artist_songs=[{"id": "s1"}],
            artist_albums=[{"id": "a1"}],
            general={"songs": [], "albums": []},
        )
        assert result["query"] == "radiohead"
        assert result["artist"] == {"name": "Radiohead"}
        assert result["artist_songs"] == [{"id": "s1"}]
        assert result["artist_albums"] == [{"id": "a1"}]
        assert result["search"] == {"songs": [], "albums": []}

    def test_none_artist_included(self):
        result = build_search_payload("query", None, [], [], {})
        assert result["artist"] is None

class TestBuildErrorPayload:
    def test_default_error(self):
        result = build_error_payload("radiohead")
        assert result == {"query": "radiohead", "error": "service_unavailable"}

    def test_custom_error(self):
        result = build_error_payload("radiohead", "fetch_failed")
        assert result["error"] == "fetch_failed"

class TestHasValidData:
    def test_true_when_artist_present(self):
        assert has_valid_data({"artist": {"name": "Radiohead"}}) is True

    def test_true_when_artist_songs(self):
        assert has_valid_data({"artist_songs": [{"id": "s1"}]}) is True

    def test_true_when_artist_albums(self):
        assert has_valid_data({"artist_albums": [{"id": "a1"}]}) is True

    def test_true_when_search_songs(self):
        assert has_valid_data({"search": {"songs": [{"id": "s1"}]}}) is True

    def test_true_when_search_albums(self):
        assert has_valid_data({"search": {"albums": [{"id": "a1"}]}}) is True

    def test_false_when_all_empty(self):
        assert has_valid_data({}) is False

    def test_false_when_all_none_or_empty(self):
        result = {
            "artist": None,
            "artist_songs": [],
            "artist_albums": [],
            "search": {"songs": [], "albums": []},
        }
        assert has_valid_data(result) is False

    def test_false_when_search_is_none(self):
        assert has_valid_data({"search": None}) is False

    def test_false_when_search_keys_missing(self):
        assert has_valid_data({"search": {}}) is False

class TestGetWarmIds:
    def test_extracts_artist_song_ids(self):
        result = {
            "artist": {"name": "Radiohead"},
            "artist_songs": [{"video_id": "vid1"}, {"video_id": "vid2"}],
        }
        ids = get_warm_ids(result)
        assert "vid1" in ids
        assert "vid2" in ids

    def test_includes_general_songs_when_no_artist(self):
        result = {
            "artist": None,
            "artist_songs": [],
            "search": {"songs": [{"video_id": "gen1"}]},
        }
        ids = get_warm_ids(result)
        assert "gen1" in ids

    def test_excludes_general_songs_when_artist_present(self):
        result = {
            "artist": {"name": "Radiohead"},
            "artist_songs": [{"video_id": "art1"}],
            "search": {"songs": [{"video_id": "gen1"}]},
        }
        ids = get_warm_ids(result)
        assert "art1" in ids
        assert "gen1" not in ids

    def test_deduplicates_ids(self):
        result = {
            "artist": None,
            "artist_songs": [{"video_id": "vid1"}, {"video_id": "vid1"}],
            "search": {"songs": [{"video_id": "vid1"}]},
        }
        ids = get_warm_ids(result)
        assert ids.count("vid1") == 1

    def test_caps_at_24_ids(self):
        songs = [{"video_id": f"v{i}"} for i in range(30)]
        result = {"artist": None, "artist_songs": songs, "search": {}}
        ids = get_warm_ids(result)
        assert len(ids) <= 24

    def test_skips_songs_without_video_id(self):
        result = {
            "artist": None,
            "artist_songs": [{"video_id": None}, {"title": "no id"}, {"video_id": "v1"}],
        }
        ids = get_warm_ids(result)
        assert ids == ["v1"]

    def test_empty_result_returns_empty(self):
        assert get_warm_ids({}) == []

    def test_artist_songs_before_general_in_order(self):
        result = {
            "artist": None,
            "artist_songs": [{"video_id": "art1"}],
            "search": {"songs": [{"video_id": "gen1"}]},
        }
        ids = get_warm_ids(result)
        assert ids.index("art1") < ids.index("gen1")

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestSearch:
    def _base_patches(self):
        yt = MagicMock()
        yt.search.return_value = [{"some": "response"}]
        yt_api = MagicMock()
        return yt, yt_api

    def test_returns_cached_when_available(self):
        cached = {"query": "radiohead", "artist": {"name": "Radiohead"}}
        with patch("services.search_service.get_cached", return_value=cached):
            result = search("Radiohead")
        assert result == cached

    def test_skips_cache_when_use_cache_false(self):
        yt, yt_api = self._base_patches()
        with patch("services.search_service.get_cached") as mock_get, \
             patch("services.search_service._ytm", return_value=yt), \
             patch("services.search_service._ytmusic_client", return_value=yt_api), \
             patch("services.search_service.parse_artist_card_info", return_value=None), \
             patch("services.search_service.parse_artist_card_songs", return_value=[]), \
             patch("services.search_service.parse_artist_card_albums", return_value=[]), \
             patch("services.search_service.parse_search_albums_and_songs", return_value={"songs": [{"video_id": "v1"}], "albums": []}), \
             patch("services.search_service.set_cached"):
            search("Radiohead", use_cache=False)
        mock_get.assert_not_called()

    def test_returns_error_when_response_empty(self):
        yt, yt_api = self._base_patches()
        yt.search.return_value = None
        with patch("services.search_service.get_cached", return_value=None), \
             patch("services.search_service._ytm", return_value=yt), \
             patch("services.search_service._ytmusic_client", return_value=yt_api):
            result = search("Radiohead")
        assert "error" in result

    def test_returns_error_when_no_valid_data(self):
        yt, yt_api = self._base_patches()
        with patch("services.search_service.get_cached", return_value=None), \
             patch("services.search_service._ytm", return_value=yt), \
             patch("services.search_service._ytmusic_client", return_value=yt_api), \
             patch("services.search_service.parse_artist_card_info", return_value=None), \
             patch("services.search_service.parse_artist_card_songs", return_value=[]), \
             patch("services.search_service.parse_artist_card_albums", return_value=[]), \
             patch("services.search_service.parse_search_albums_and_songs", return_value={"songs": [], "albums": []}):
            result = search("xyzxyzxyz")
        assert "error" in result

    def test_builds_and_caches_valid_result(self):
        yt, yt_api = self._base_patches()
        with patch("services.search_service.get_cached", return_value=None), \
             patch("services.search_service._ytm", return_value=yt), \
             patch("services.search_service._ytmusic_client", return_value=yt_api), \
             patch("services.search_service.parse_artist_card_info", return_value={"name": "Radiohead"}), \
             patch("services.search_service.parse_artist_card_songs", return_value=[{"video_id": "v1"}]), \
             patch("services.search_service.parse_artist_card_albums", return_value=[]), \
             patch("services.search_service.parse_search_albums_and_songs", return_value={"songs": [], "albums": []}), \
             patch("services.search_service.set_cached") as mock_set:
            result = search("Radiohead")
        assert result["query"] == "Radiohead"
        assert result["artist"] == {"name": "Radiohead"}
        mock_set.assert_called_once()

    def test_skips_general_song_limit_when_artist_found(self):
        yt, yt_api = self._base_patches()
        with patch("services.search_service.get_cached", return_value=None), \
             patch("services.search_service._ytm", return_value=yt), \
             patch("services.search_service._ytmusic_client", return_value=yt_api), \
             patch("services.search_service.parse_artist_card_info", return_value={"name": "Radiohead"}), \
             patch("services.search_service.parse_artist_card_songs", return_value=[]), \
             patch("services.search_service.parse_artist_card_albums", return_value=[{"id": "a1"}]), \
             patch("services.search_service.parse_search_albums_and_songs", return_value={"songs": [], "albums": [{"id": "a1"}]}) as mock_parse, \
             patch("services.search_service.set_cached"):
            search("Radiohead")
        call_kwargs = mock_parse.call_args
        assert call_kwargs[1].get("song_limit") == 0 or call_kwargs[0][1] == 0

    def test_returns_error_on_exception(self):
        with patch("services.search_service.get_cached", return_value=None), \
             patch("services.search_service._ytm", side_effect=Exception("network error")):
            result = search("Radiohead")
        assert "error" in result
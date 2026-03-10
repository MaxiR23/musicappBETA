# test/services/test_album_service.py
#
# Testeamos: services/album_service.py
# - extract_artist_name     → extracción de nombre de artista desde album info
# - enrich_album_tracks     → agrega album_id y album_name a cada track
# - build_album_payload     → construcción de payload final de album
# - build_error_payload     → construcción de payload de error
# - should_cache_album      → decide si el album es válido para cachear
# - get_album               → orquestación: cache → fetch → build → cache
#

import pytest
from unittest.mock import patch, MagicMock
from services.album_service import (
    extract_artist_name,
    enrich_album_tracks,
    build_album_payload,
    build_error_payload,
    should_cache_album,
    get_album,
)

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════

class TestExtractArtistName:
    def test_from_artists_list(self):
        info = {"artists": [{"name": "Radiohead"}]}
        assert extract_artist_name(info) == "Radiohead"

    def test_from_artist_name_field(self):
        info = {"artist_name": "Tame Impala"}
        assert extract_artist_name(info) == "Tame Impala"

    def test_from_artist_field(self):
        info = {"artist": "Pink Floyd"}
        assert extract_artist_name(info) == "Pink Floyd"

    def test_from_subtitle_strips_bullet(self):
        info = {"subtitle": "Radiohead • 2003"}
        assert extract_artist_name(info) == "Radiohead"

    def test_artist_name_takes_priority_over_artists_list(self):
        info = {"artist_name": "Override", "artists": [{"name": "Ignored"}]}
        assert extract_artist_name(info) == "Override"

    def test_empty_info_returns_none(self):
        assert extract_artist_name({}) is None

    def test_empty_artists_list_falls_through(self):
        info = {"artists": [], "artist": "Fallback"}
        assert extract_artist_name(info) == "Fallback"

class TestEnrichAlbumTracks:
    def test_adds_album_id_and_name(self):
        tracks = [{"id": "t1", "title": "Song"}]
        info = {"title": "OK Computer"}
        result = enrich_album_tracks(tracks, "album-1", info)
        assert result[0]["album_id"] == "album-1"
        assert result[0]["album_name"] == "OK Computer"

    def test_preserves_original_track_fields(self):
        tracks = [{"id": "t1", "title": "Song", "artist": "Radiohead"}]
        result = enrich_album_tracks(tracks, "album-1", {})
        assert result[0]["id"] == "t1"
        assert result[0]["artist"] == "Radiohead"

    def test_none_tracks_returns_empty_list(self):
        assert enrich_album_tracks(None, "album-1") == []

    def test_empty_tracks_returns_empty_list(self):
        assert enrich_album_tracks([], "album-1") == []

    def test_no_info_album_name_is_none(self):
        tracks = [{"id": "t1"}]
        result = enrich_album_tracks(tracks, "album-1")
        assert result[0]["album_name"] is None

    def test_multiple_tracks_all_enriched(self):
        tracks = [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]
        result = enrich_album_tracks(tracks, "album-1", {"title": "Abbey Road"})
        assert all(t["album_id"] == "album-1" for t in result)
        assert all(t["album_name"] == "Abbey Road" for t in result)

class TestBuildAlbumPayload:
    def test_builds_correct_structure(self):
        result = build_album_payload(
            album_id="a1",
            raw={},
            info={"title": "OK Computer"},
            tracks=[{"id": "t1"}],
            more_from_artist=[{"id": "a2"}],
            events=[],
        )
        assert result["id"] == "a1"
        assert result["info"] == {"title": "OK Computer"}
        assert result["tracks"] == [{"id": "t1"}]
        assert result["more_from_artist"] == [{"id": "a2"}]
        assert result["upcoming_events"] == []

    def test_none_fields_default_to_empty_lists(self):
        result = build_album_payload("a1", {}, {})
        assert result["tracks"] == []
        assert result["more_from_artist"] == []
        assert result["upcoming_events"] == []
        assert result["other_versions"] == []
        assert result["releases_for_you"] == []

class TestBuildErrorPayload:
    def test_default_error(self):
        result = build_error_payload("a1")
        assert result == {"id": "a1", "error": "service_unavailable"}

    def test_custom_error(self):
        result = build_error_payload("a1", "fetch_failed")
        assert result["error"] == "fetch_failed"

class TestShouldCacheAlbum:
    def test_true_when_title_and_tracks(self):
        assert should_cache_album({"title": "OK Computer"}, [{"id": "t1"}]) is True

    def test_false_when_no_title(self):
        assert should_cache_album({}, [{"id": "t1"}]) is False

    def test_false_when_no_tracks(self):
        assert should_cache_album({"title": "OK Computer"}, []) is False

    def test_false_when_both_empty(self):
        assert should_cache_album({}, []) is False

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestGetAlbum:
    def test_returns_cached_when_available(self):
        cached_data = {"id": "a1", "info": {"title": "Cached"}}
        with patch("services.album_service.get_cached", return_value=cached_data):
            result = get_album("a1")
        assert result == cached_data

    def test_returns_error_when_browse_returns_none(self):
        with patch("services.album_service.get_cached", return_value=None), \
             patch("services.album_service.music_client.browse", return_value=None):
            result = get_album("a1")
        assert result["error"] == "fetch_failed"

    def test_returns_error_when_info_has_no_title(self):
        with patch("services.album_service.get_cached", return_value=None), \
             patch("services.album_service.music_client.browse", return_value={"some": "data"}), \
             patch("services.album_service.parse_album_info", return_value={}):
            result = get_album("a1")
        assert "error" in result

    def test_builds_and_caches_valid_album(self):
        raw = {"some": "raw"}
        info = {"title": "OK Computer", "artist_id": "ar1", "audio_playlist_id": "ap1"}
        tracks = [{"id": "t1"}, {"id": "t2"}]

        with patch("services.album_service.get_cached", return_value=None), \
             patch("services.album_service.music_client.browse", return_value=raw), \
             patch("services.album_service.parse_album_info", return_value=info), \
             patch("services.album_service.gather", return_value={"tracks": tracks, "more_from": []}), \
             patch("services.album_service.get_events_cached_only", return_value=[]), \
             patch("services.album_service.schedule_events_refresh"), \
             patch("services.album_service.set_cached") as mock_set_cached, \
             patch("services.album_service.parse_album_other_versions", return_value=[]), \
             patch("services.album_service.parse_album_releases_for_you", return_value=[]):
            result = get_album("a1")

        assert result["id"] == "a1"
        assert result["info"] == info
        assert len(result["tracks"]) == 2
        mock_set_cached.assert_called_once()

    def test_does_not_cache_when_no_tracks(self):
        raw = {"some": "raw"}
        info = {"title": "OK Computer", "artist_id": "ar1", "audio_playlist_id": "ap1"}

        with patch("services.album_service.get_cached", return_value=None), \
             patch("services.album_service.music_client.browse", return_value=raw), \
             patch("services.album_service.parse_album_info", return_value=info), \
             patch("services.album_service.gather", return_value={"tracks": [], "more_from": []}), \
             patch("services.album_service.get_events_cached_only", return_value=[]), \
             patch("services.album_service.schedule_events_refresh"), \
             patch("services.album_service.set_cached") as mock_set_cached, \
             patch("services.album_service.parse_album_other_versions", return_value=[]), \
             patch("services.album_service.parse_album_releases_for_you", return_value=[]):
            result = get_album("a1")

        mock_set_cached.assert_not_called()

    def test_returns_error_on_exception(self):
        with patch("services.album_service.get_cached", return_value=None), \
             patch("services.album_service.music_client.browse", side_effect=Exception("network error")):
            result = get_album("a1")
        assert "error" in result

    def test_skips_cache_when_use_cache_false(self):
        raw = {"some": "raw"}
        info = {"title": "OK Computer", "audio_playlist_id": "ap1"}

        with patch("services.album_service.get_cached") as mock_get_cached, \
             patch("services.album_service.music_client.browse", return_value=raw), \
             patch("services.album_service.parse_album_info", return_value=info), \
             patch("services.album_service.gather", return_value={"tracks": [], "more_from": []}), \
             patch("services.album_service.get_events_cached_only", return_value=[]), \
             patch("services.album_service.schedule_events_refresh"), \
             patch("services.album_service.set_cached"), \
             patch("services.album_service.parse_album_other_versions", return_value=[]), \
             patch("services.album_service.parse_album_releases_for_you", return_value=[]):
            get_album("a1", use_cache=False)

        mock_get_cached.assert_not_called()
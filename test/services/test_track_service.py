# test/services/test_track_service.py
#
# Testeamos: services/track_service.py
# - duration_to_seconds         → parsea MM:SS, HH:MM:SS, SS
# - best_thumb_url              → extrae mejor thumbnail de múltiples formatos
# - extract_artist_info         → artist_name, artist_id, artist_ids
# - extract_album_info          → album_id, album_name
# - extract_duration_seconds    → extrae seconds desde varios campos
# - normalize_track_item        → normaliza track completo
# - filter_related_sections     → filtra secciones excluidas
# - build_lyrics_result         → construye resultado de lyrics
# - build_error_result          → construye resultado de error
# - get_lyrics                  → cache → fetch → set_cached
# - get_related                 → cache → fetch → set_cached
# - get_up_next                 → cache → fetch → set_cached
#

import pytest
from unittest.mock import patch, MagicMock
from services.track_service import (
    duration_to_seconds,
    best_thumb_url,
    extract_artist_info,
    extract_album_info,
    extract_duration_seconds,
    normalize_track_item,
    filter_related_sections,
    build_lyrics_result,
    build_error_result,
    get_lyrics,
    get_related,
    get_up_next,
    EXCLUDED_RELATED_SECTIONS,
)

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestDurationToSeconds:
    def test_mm_ss(self):
        assert duration_to_seconds("3:45") == 225

    def test_hh_mm_ss(self):
        assert duration_to_seconds("1:02:03") == 3723

    def test_single_seconds(self):
        assert duration_to_seconds("42") == 42

    def test_none_returns_none(self):
        assert duration_to_seconds(None) is None

    def test_empty_string_returns_none(self):
        assert duration_to_seconds("") is None

    def test_whitespace_only_returns_none(self):
        assert duration_to_seconds("   ") is None

    def test_non_string_returns_none(self):
        assert duration_to_seconds(123) is None

    def test_invalid_format_returns_none(self):
        assert duration_to_seconds("abc:def") is None

    def test_too_many_parts_returns_none(self):
        assert duration_to_seconds("1:2:3:4") is None

    def test_strips_whitespace(self):
        assert duration_to_seconds("  3:45  ") == 225

    def test_zero_duration(self):
        assert duration_to_seconds("0:00") == 0

class TestBestThumbUrl:
    def test_returns_url_from_list_reversed(self):
        track = {"thumbnail": [{"url": "low.jpg"}, {"url": "high.jpg"}]}
        assert best_thumb_url(track) == "high.jpg"

    def test_returns_url_from_dict(self):
        track = {"thumbnail": {"url": "http://img.jpg"}}
        assert best_thumb_url(track) == "http://img.jpg"

    def test_returns_string_thumbnail_directly(self):
        track = {"thumbnail": "http://img.jpg"}
        assert best_thumb_url(track) == "http://img.jpg"

    def test_falls_back_to_thumbnails_key(self):
        track = {"thumbnails": [{"url": "http://img.jpg"}]}
        assert best_thumb_url(track) == "http://img.jpg"

    def test_returns_none_when_no_thumbnail(self):
        assert best_thumb_url({}) is None

    def test_returns_none_when_list_empty(self):
        assert best_thumb_url({"thumbnail": []}) is None

    def test_returns_none_when_url_empty_string(self):
        assert best_thumb_url({"thumbnail": {"url": ""}}) is None

    def test_returns_none_when_thumbnail_is_empty_string(self):
        assert best_thumb_url({"thumbnail": ""}) is None

    def test_handles_list_of_strings(self):
        track = {"thumbnail": ["http://low.jpg", "http://high.jpg"]}
        assert best_thumb_url(track) == "http://high.jpg"

    def test_skips_list_items_without_url(self):
        track = {"thumbnail": [{"no_url": "x"}, {"url": "http://img.jpg"}]}
        assert best_thumb_url(track) == "http://img.jpg"

    def test_strips_whitespace_from_url(self):
        track = {"thumbnail": {"url": "  http://img.jpg  "}}
        assert best_thumb_url(track) == "http://img.jpg"

class TestExtractArtistInfo:
    def test_extracts_from_artists_list(self):
        track = {"artists": [{"name": "Radiohead", "id": "UCar1"}]}
        name, aid, ids = extract_artist_info(track)
        assert name == "Radiohead"
        assert aid == "UCar1"
        assert ids == ["UCar1"]

    def test_joins_multiple_artists(self):
        track = {"artists": [{"name": "Jay-Z", "id": "id1"}, {"name": "Kanye", "id": "id2"}]}
        name, _, ids = extract_artist_info(track)
        assert name == "Jay-Z, Kanye"
        assert ids == ["id1", "id2"]

    def test_artist_name_field_takes_priority(self):
        track = {"artist_name": "Override", "artists": [{"name": "Ignored", "id": "id1"}]}
        name, _, _ = extract_artist_info(track)
        assert name == "Override"

    def test_artist_id_field_takes_priority(self):
        track = {"artist_id": "override-id", "artists": [{"name": "X", "id": "list-id"}]}
        _, aid, _ = extract_artist_info(track)
        assert aid == "override-id"

    def test_falls_back_to_author_field(self):
        track = {"author": "Thom Yorke"}
        name, _, _ = extract_artist_info(track)
        assert name == "Thom Yorke"

    def test_returns_none_when_no_artist(self):
        name, aid, ids = extract_artist_info({})
        assert name is None
        assert aid is None
        assert ids == []

    def test_deduplicates_artist_ids(self):
        track = {"artists": [{"name": "A", "id": "id1"}, {"name": "B", "id": "id1"}]}
        _, _, ids = extract_artist_info(track)
        assert ids == ["id1"]

    def test_skips_non_dict_artists(self):
        track = {"artists": ["not_a_dict", {"name": "Radiohead", "id": "id1"}]}
        name, _, _ = extract_artist_info(track)
        assert name == "Radiohead"

    def test_artists_not_list_treated_as_empty(self):
        track = {"artists": "not_a_list"}
        name, aid, ids = extract_artist_info(track)
        assert ids == []

class TestExtractAlbumInfo:
    def test_extracts_from_top_level_fields(self):
        track = {"album_id": "al1", "album_name": "OK Computer"}
        aid, name = extract_album_info(track)
        assert aid == "al1"
        assert name == "OK Computer"

    def test_extracts_from_album_dict(self):
        track = {"album": {"id": "al1", "name": "OK Computer"}}
        aid, name = extract_album_info(track)
        assert aid == "al1"
        assert name == "OK Computer"

    def test_top_level_takes_priority_over_album_dict(self):
        track = {"album_id": "top-id", "album": {"id": "nested-id"}}
        aid, _ = extract_album_info(track)
        assert aid == "top-id"

    def test_returns_none_when_no_album(self):
        aid, name = extract_album_info({})
        assert aid is None
        assert name is None

    def test_album_not_dict_treated_as_empty(self):
        track = {"album": "not_a_dict"}
        aid, name = extract_album_info(track)
        assert aid is None
        assert name is None

class TestExtractDurationSeconds:
    def test_from_length_seconds_int(self):
        assert extract_duration_seconds({"lengthSeconds": 180}) == 180

    def test_from_duration_seconds_int(self):
        assert extract_duration_seconds({"duration_seconds": 240}) == 240

    def test_from_length_seconds_string(self):
        assert extract_duration_seconds({"lengthSeconds": "180"}) == 180

    def test_from_duration_string_mm_ss(self):
        assert extract_duration_seconds({"duration": "3:00"}) == 180

    def test_from_length_string_mm_ss(self):
        assert extract_duration_seconds({"length": "4:30"}) == 270

    def test_returns_none_when_no_duration(self):
        assert extract_duration_seconds({}) is None

    def test_length_seconds_takes_priority_over_duration(self):
        track = {"lengthSeconds": 100, "duration": "99:99"}
        assert extract_duration_seconds(track) == 100

    def test_non_numeric_string_falls_through(self):
        assert extract_duration_seconds({"lengthSeconds": "abc"}) is None

class TestNormalizeTrackItem:
    def test_normalizes_complete_track(self):
        track = {
            "videoId": "dQw4w9",
            "title": "Creep",
            "artists": [{"name": "Radiohead", "id": "UCar1"}],
            "album": {"id": "al1", "name": "Pablo Honey"},
            "thumbnail": [{"url": "http://img.jpg"}],
            "duration": "3:58",
        }
        result = normalize_track_item(track)
        assert result["id"] == "dQw4w9"
        assert result["title"] == "Creep"
        assert result["artist_name"] == "Radiohead"
        assert result["artist_id"] == "UCar1"
        assert result["album_id"] == "al1"
        assert result["album_name"] == "Pablo Honey"
        assert result["thumbnail"] == "http://img.jpg"
        assert result["duration_seconds"] == 238

    def test_falls_back_to_id_field(self):
        track = {"id": "abc123"}
        result = normalize_track_item(track)
        assert result["id"] == "abc123"

    def test_non_dict_input_returns_empty_normalized(self):
        result = normalize_track_item("not_a_dict")
        assert result["id"] is None
        assert result["title"] is None

    def test_empty_dict_returns_none_fields(self):
        result = normalize_track_item({})
        assert result["id"] is None
        assert result["artist_name"] is None

class TestFilterRelatedSections:
    def test_removes_excluded_sections(self):
        sections = [
            {"title": "Recommended playlists", "items": []},
            {"title": "Fans might also like", "items": []},
            {"title": "Other performances", "items": []},
        ]
        result = filter_related_sections(sections)
        assert len(result) == 1
        assert result[0]["title"] == "Fans might also like"

    def test_all_excluded_returns_empty(self):
        sections = [{"title": t} for t in EXCLUDED_RELATED_SECTIONS]
        assert filter_related_sections(sections) == []

    def test_skips_non_dict_items(self):
        sections = ["not_a_dict", {"title": "Fans might also like"}]
        result = filter_related_sections(sections)
        assert len(result) == 1

    def test_empty_list_returns_empty(self):
        assert filter_related_sections([]) == []

    def test_keeps_sections_without_title(self):
        sections = [{"items": []}]
        result = filter_related_sections(sections)
        assert len(result) == 1

class TestBuildLyricsResult:
    def test_ok_true_includes_lyrics_and_source(self):
        result = build_lyrics_result(True, lyrics="Hello world", source="Musixmatch")
        assert result == {"ok": True, "lyrics": "Hello world", "source": "Musixmatch"}

    def test_ok_false_includes_reason(self):
        result = build_lyrics_result(False, reason="no_lyrics")
        assert result == {"ok": False, "reason": "no_lyrics"}

    def test_ok_false_excludes_lyrics_and_source(self):
        result = build_lyrics_result(False, reason="no_lyrics")
        assert "lyrics" not in result
        assert "source" not in result


class TestBuildErrorResult:
    def test_builds_basic_error(self):
        result = build_error_result("error")
        assert result == {"ok": False, "reason": "error"}

    def test_includes_detail_when_provided(self):
        result = build_error_result("error", "timeout")
        assert result["detail"] == "timeout"

    def test_excludes_detail_when_none(self):
        result = build_error_result("error")
        assert "detail" not in result

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestGetLyrics:
    def test_returns_cached_when_available(self):
        cached = {"ok": True, "lyrics": "Hello"}
        with patch("services.track_service.get_cached_legacy", return_value=cached):
            result = get_lyrics("vid1")
        assert result == cached

    def test_returns_no_lyrics_when_no_browse_id(self):
        yt = MagicMock()
        yt.get_watch_playlist.return_value = {"lyrics": None}
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt), \
             patch("services.track_service.set_cached_legacy"):
            result = get_lyrics("vid1")
        assert result["ok"] is False
        assert result["reason"] == "no_lyrics"

    def test_extracts_browse_id_from_dict(self):
        yt = MagicMock()
        yt.get_watch_playlist.return_value = {"lyrics": {"browseId": "LY123"}}
        yt.get_lyrics.return_value = {"lyrics": "Hello world", "source": "Musixmatch"}
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt), \
             patch("services.track_service.set_cached_legacy"):
            result = get_lyrics("vid1")
        assert result["ok"] is True
        assert result["lyrics"] == "Hello world"

    def test_extracts_browse_id_from_string(self):
        yt = MagicMock()
        yt.get_watch_playlist.return_value = {"lyrics": "LY456"}
        yt.get_lyrics.return_value = {"lyrics": "Some lyrics", "source": "x"}
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt), \
             patch("services.track_service.set_cached_legacy"):
            result = get_lyrics("vid1")
        assert result["ok"] is True

    def test_caches_result(self):
        yt = MagicMock()
        yt.get_watch_playlist.return_value = {"lyrics": {"browseId": "LY123"}}
        yt.get_lyrics.return_value = {"lyrics": "x", "source": "y"}
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt), \
             patch("services.track_service.set_cached_legacy") as mock_set:
            get_lyrics("vid1")
        mock_set.assert_called_once()

    def test_returns_error_on_exception(self):
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", side_effect=Exception("fail")):
            result = get_lyrics("vid1")
        assert result["ok"] is False
        assert result["reason"] == "error"

class TestGetRelated:
    def test_returns_cached_when_available(self):
        cached = {"ok": True, "related": []}
        with patch("services.track_service.get_cached_legacy", return_value=cached):
            result = get_related("vid1")
        assert result == cached

    def test_returns_error_when_no_watch_playlist(self):
        yt = MagicMock()
        yt.get_watch_playlist.return_value = None
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt):
            result = get_related("vid1")
        assert result["ok"] is False
        assert result["reason"] == "no_watch_playlist"

    def test_returns_error_when_no_browse_id(self):
        yt = MagicMock()
        yt.get_watch_playlist.return_value = {"related": None}
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt):
            result = get_related("vid1")
        assert result["ok"] is False
        assert result["reason"] == "no_browse_id"

    def test_fetches_and_caches_related(self):
        yt = MagicMock()
        yt.get_watch_playlist.return_value = {"related": {"browseId": "RB123"}}
        yt.get_song_related.return_value = [{"title": "Fans might also like", "items": []}]
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt), \
             patch("services.track_service.parse_related_sections", return_value=[]), \
             patch("services.track_service.set_cached_legacy") as mock_set:
            result = get_related("vid1")
        assert result["ok"] is True
        mock_set.assert_called_once()

    def test_returns_error_on_exception(self):
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", side_effect=Exception("fail")):
            result = get_related("vid1")
        assert result["ok"] is False

class TestGetUpNext:
    def test_returns_cached_when_available(self):
        cached = {"ok": True, "current": {}, "up_next": []}
        with patch("services.track_service.get_cached_legacy", return_value=cached):
            result = get_up_next("vid1")
        assert result == cached

    def test_returns_error_when_no_tracks(self):
        yt = MagicMock()
        yt.get_song.return_value = {}
        yt.get_watch_playlist.return_value = {"tracks": []}
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt):
            result = get_up_next("vid1")
        assert result["ok"] is False
        assert result["reason"] == "no_tracks"

    def test_builds_current_and_up_next(self):
        yt = MagicMock()
        yt.get_song.return_value = {
            "videoDetails": {"videoId": "vid1", "title": "Creep", "author": "Radiohead", "lengthSeconds": 238}
        }
        yt.get_watch_playlist.return_value = {
            "tracks": [{"videoId": "vid2", "title": "Karma Police"}],
            "autoplay": None,
        }
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt), \
             patch("services.track_service.set_cached_legacy"):
            result = get_up_next("vid1")
        assert result["ok"] is True
        assert result["current"]["id"] == "vid1"
        assert result["current"]["title"] == "Creep"
        assert len(result["up_next"]) == 1

    def test_caches_result(self):
        yt = MagicMock()
        yt.get_song.return_value = {"videoDetails": {}}
        yt.get_watch_playlist.return_value = {"tracks": [{"videoId": "v2", "title": "x"}]}
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", return_value=yt), \
             patch("services.track_service.set_cached_legacy") as mock_set:
            get_up_next("vid1")
        mock_set.assert_called_once()

    def test_returns_error_on_exception(self):
        with patch("services.track_service.get_cached_legacy", return_value=None), \
             patch("services.track_service._ytmusic_client", side_effect=Exception("fail")):
            result = get_up_next("vid1")
        assert result["ok"] is False
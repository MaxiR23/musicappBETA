# test/services/test_artist_service.py
#
# Testeamos: services/artist_service.py
# - parse_header                → extrae nombre, descripción y thumbnails
# - parse_contents              → navega la estructura de tabs del raw
# - find_albums_section         → busca sección de albums en contents
# - find_singles_section        → busca sección de singles/EPs en contents
# - build_error_payload         → payload de error
# - build_has_more              → paginación de albums/singles
# - build_artist_payload        → payload final del artista
# - build_album_item            → item de album normalizado
# - build_single_item           → item de single normalizado
# - build_all_albums_result     → resultado paginado de albums
# - build_all_singles_result    → resultado paginado de singles
# - should_cache_artist         → decide si el artista es válido para cachear
# - get_artist                  → orquestación: cache → fetch → build → cache
# - get_all_albums              → cache → fetch → build → cache
# - get_all_singles             → cache → fetch → build → cache
# - get_more_from_artist        → albums filtrando el album actual
#

import pytest
from unittest.mock import patch, MagicMock
from services.artist_service import (
    parse_header,
    parse_contents,
    find_albums_section,
    find_singles_section,
    build_error_payload,
    build_has_more,
    build_artist_payload,
    build_album_item,
    build_single_item,
    build_all_albums_result,
    build_all_singles_result,
    should_cache_artist,
    get_artist,
    get_all_albums,
    get_all_singles,
    get_more_from_artist,
)

# ════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════

def make_raw_with_header(name="Radiohead", description="A band", thumbs=None):
    return {
        "header": {
            "musicImmersiveHeaderRenderer": {
                "title": {"runs": [{"text": name}]},
                "description": {"runs": [{"text": description}]},
                "thumbnail": {
                    "musicThumbnailRenderer": {
                        "thumbnail": {"thumbnails": thumbs or [{"url": "http://img.jpg"}]}
                    }
                },
            }
        }
    }

def make_shelf(title: str, items: list = None) -> dict:
    return {
        "musicCarouselShelfRenderer": {
            "header": {
                "musicCarouselShelfBasicHeaderRenderer": {
                    "title": {"runs": [{"text": title}]}
                }
            },
            "contents": items or [],
        }
    }

def make_contents_raw(sections: list) -> dict:
    return {
        "contents": {
            "singleColumnBrowseResultsRenderer": {
                "tabs": [
                    {
                        "tabRenderer": {
                            "content": {
                                "sectionListRenderer": {
                                    "contents": sections
                                }
                            }
                        }
                    }
                ]
            }
        }
    }

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestParseHeader:
    def test_extracts_name(self):
        raw = make_raw_with_header(name="Radiohead")
        result = parse_header(raw)
        assert result["name"] == "Radiohead"

    def test_extracts_description(self):
        raw = make_raw_with_header(description="A rock band from Oxford")
        result = parse_header(raw)
        assert result["description"] == "A rock band from Oxford"

    def test_extracts_thumbnails(self):
        thumbs = [{"url": "http://img.jpg", "width": 226}]
        raw = make_raw_with_header(thumbs=thumbs)
        result = parse_header(raw)
        assert result["thumbnails"] == thumbs

    def test_empty_raw_returns_none_name(self):
        result = parse_header({})
        assert result["name"] is None

    def test_empty_raw_returns_empty_description(self):
        result = parse_header({})
        assert result["description"] == ""

    def test_empty_raw_returns_empty_thumbnails(self):
        result = parse_header({})
        assert result["thumbnails"] == []

    def test_multiple_description_runs_are_joined(self):
        raw = {
            "header": {
                "musicImmersiveHeaderRenderer": {
                    "title": {"runs": [{"text": "Artist"}]},
                    "description": {"runs": [{"text": "Part 1"}, {"text": " Part 2"}]},
                    "thumbnail": {"musicThumbnailRenderer": {"thumbnail": {"thumbnails": []}}},
                }
            }
        }
        result = parse_header(raw)
        assert result["description"] == "Part 1 Part 2"

class TestParseContents:
    def test_returns_sections_from_first_tab(self):
        sections = [make_shelf("Albums"), make_shelf("Singles")]
        raw = make_contents_raw(sections)
        result = parse_contents(raw)
        assert len(result) == 2

    def test_empty_raw_returns_empty_list(self):
        assert parse_contents({}) == []

    def test_no_tabs_returns_empty_list(self):
        raw = {"contents": {"singleColumnBrowseResultsRenderer": {"tabs": []}}}
        assert parse_contents(raw) == []

class TestFindAlbumsSection:
    def test_finds_albums_section(self):
        sections = [make_shelf("Albums"), make_shelf("Singles")]
        result = find_albums_section(sections)
        assert result == sections[0]

    def test_returns_none_when_no_albums(self):
        sections = [make_shelf("Singles"), make_shelf("Related artists")]
        result = find_albums_section(sections)
        assert result is None

    def test_does_not_match_singles(self):
        sections = [make_shelf("Singles & Albums")]
        result = find_albums_section(sections)
        # título contiene "single", no debe matchear
        assert result is None

    def test_returns_none_on_empty_list(self):
        assert find_albums_section([]) is None

    def test_ignores_sections_without_shelf(self):
        sections = [{"otherRenderer": {}}, make_shelf("Albums")]
        result = find_albums_section(sections)
        assert result == sections[1]

class TestFindSinglesSection:
    def test_finds_singles_section(self):
        sections = [make_shelf("Albums"), make_shelf("Singles")]
        result = find_singles_section(sections)
        assert result == sections[1]

    def test_finds_ep_section(self):
        sections = [make_shelf("EPs")]
        result = find_singles_section(sections)
        assert result == sections[0]

    def test_returns_none_when_not_found(self):
        sections = [make_shelf("Albums"), make_shelf("Related")]
        result = find_singles_section(sections)
        assert result is None

    def test_returns_none_on_empty_list(self):
        assert find_singles_section([]) is None

class TestBuildErrorPayload:
    def test_default_error(self):
        result = build_error_payload("ar1")
        assert result == {"id": "ar1", "error": "service_unavailable"}

    def test_custom_error(self):
        result = build_error_payload("ar1", "fetch_failed")
        assert result["error"] == "fetch_failed"

class TestBuildHasMore:
    def test_true_when_browse_id_and_10_results(self):
        artist_data = {
            "albums": {"browseId": "MPADx", "results": [{}] * 10},
            "singles": {"browseId": "MPADy", "results": [{}] * 10},
        }
        result = build_has_more(artist_data)
        assert result["albums"] is True
        assert result["singles"] is True

    def test_false_when_no_browse_id(self):
        artist_data = {
            "albums": {"results": [{}] * 10},
            "singles": {"results": [{}] * 10},
        }
        result = build_has_more(artist_data)
        assert result["albums"] is False
        assert result["singles"] is False

    def test_false_when_fewer_than_10_results(self):
        artist_data = {
            "albums": {"browseId": "MPADx", "results": [{}] * 5},
            "singles": {"browseId": "MPADy", "results": [{}] * 3},
        }
        result = build_has_more(artist_data)
        assert result["albums"] is False
        assert result["singles"] is False

    def test_empty_artist_data(self):
        result = build_has_more({})
        assert result["albums"] is False
        assert result["singles"] is False

class TestBuildArtistPayload:
    def test_builds_correct_keys(self):
        result = build_artist_payload(
            header={"name": "Radiohead"},
            top_songs=[{"id": "s1"}],
            albums=[{"id": "a1"}],
            singles=[{"id": "si1"}],
            related=[{"id": "r1"}],
            has_more={"albums": False, "singles": False},
        )
        assert result["header"] == {"name": "Radiohead"}
        assert result["top_songs"] == [{"id": "s1"}]
        assert result["albums"] == [{"id": "a1"}]
        assert result["singles_eps"] == [{"id": "si1"}]
        assert result["related"] == [{"id": "r1"}]

    def test_omits_albums_when_empty(self):
        result = build_artist_payload({"name": "X"}, [], [], [], [], {})
        assert "albums" not in result

    def test_omits_singles_when_empty(self):
        result = build_artist_payload({"name": "X"}, [], [], [], [], {})
        assert "singles_eps" not in result

    def test_omits_top_songs_when_empty(self):
        result = build_artist_payload({"name": "X"}, [], [], [], [], {})
        assert "top_songs" not in result

    def test_events_default_to_empty_list(self):
        result = build_artist_payload({"name": "X"}, [], [], [], [], {})
        assert result["upcoming_events"] == []

    def test_events_included_when_provided(self):
        events = [{"id": "e1"}]
        result = build_artist_payload({"name": "X"}, [], [], [], [], {}, events=events)
        assert result["upcoming_events"] == events

    def test_new_releases_included_only_when_provided(self):
        result_without = build_artist_payload({"name": "X"}, [], [], [], [], {})
        assert "new_releases" not in result_without

        result_with = build_artist_payload({"name": "X"}, [], [], [], [], {}, new_releases=[{"id": "r1"}])
        assert result_with["new_releases"] == [{"id": "r1"}]

    def test_presenting_id_included_when_provided(self):
        result = build_artist_payload({"name": "X"}, [], [], [], [], {}, presenting_id="PLXXX")
        assert result["presenting"] == {"playlistId": "PLXXX"}

    def test_presenting_id_absent_when_not_provided(self):
        result = build_artist_payload({"name": "X"}, [], [], [], [], {})
        assert "presenting" not in result

class TestBuildAlbumItem:
    def test_builds_correct_fields(self):
        album = {
            "browseId": "MPREb_abc",
            "title": "OK Computer",
            "year": "1997",
            "thumbnails": [{"url": "http://img.jpg"}],
        }
        result = build_album_item(album)
        assert result["id"] == "MPREb_abc"
        assert result["title"] == "OK Computer"
        assert result["year"] == "1997"
        assert result["thumbnails"] == [{"url": "http://img.jpg"}]

    def test_missing_fields_return_none(self):
        result = build_album_item({})
        assert result["id"] is None
        assert result["title"] is None
        assert result["year"] is None
        assert result["thumbnails"] == []

class TestBuildSingleItem:
    def test_builds_correct_fields(self):
        single = {
            "browseId": "MPREb_single",
            "title": "Creep",
            "thumbnails": [{"url": "http://img.jpg"}],
        }
        album_info = {"type": "Single", "year": "1992", "trackCount": 1}
        result = build_single_item(single, album_info)
        assert result["id"] == "MPREb_single"
        assert result["title"] == "Creep"
        assert result["type"] == "Single"
        assert result["year"] == "1992"
        assert result["trackCount"] == 1

    def test_falls_back_to_single_type_when_album_info_empty(self):
        single = {"browseId": "x", "title": "Song", "type": "EP", "thumbnails": []}
        result = build_single_item(single, {})
        assert result["type"] == "EP"

    def test_default_type_when_both_missing(self):
        result = build_single_item({}, {})
        assert result["type"] == "Single"

class TestBuildAllAlbumsResult:
    def test_builds_correct_structure(self):
        albums = [{"id": "a1"}, {"id": "a2"}]
        result = build_all_albums_result("ar1", albums)
        assert result["artist_id"] == "ar1"
        assert result["total"] == 2
        assert result["albums"] == albums

    def test_empty_albums(self):
        result = build_all_albums_result("ar1", [])
        assert result["total"] == 0
        assert result["albums"] == []

class TestBuildAllSinglesResult:
    def test_builds_correct_structure(self):
        singles = [{"id": "s1"}]
        result = build_all_singles_result("ar1", singles)
        assert result["artist_id"] == "ar1"
        assert result["total"] == 1
        assert result["singles"] == singles

class TestShouldCacheArtist:
    def test_true_when_has_name(self):
        assert should_cache_artist({"name": "Radiohead"}) is True

    def test_false_when_no_name(self):
        assert should_cache_artist({}) is False

    def test_false_when_name_is_none(self):
        assert should_cache_artist({"name": None}) is False

# ════════════════════════════════════════════════════════
# IO (con mocks)
# ════════════════════════════════════════════════════════
class TestGetArtist:
    def _base_patches(self):
        """Contexto base: browse + get_artist retornan datos válidos."""
        raw = make_raw_with_header(name="Radiohead")
        raw.update(make_contents_raw([]))
        return raw

    def test_returns_cached_when_available(self):
        cached = {"id": "ar1", "header": {"name": "Cached"}}
        with patch("services.artist_service.get_cached", return_value=cached):
            result = get_artist(MagicMock(), "ar1")
        assert result == cached

    def test_returns_error_when_browse_returns_empty(self):
        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.gather", return_value={"raw": None, "artist_data": {}}):
            result = get_artist(MagicMock(), "ar1")
        assert result["error"] == "fetch_failed"

    def test_returns_error_when_header_has_no_name(self):
        raw = make_raw_with_header(name=None)
        raw.update(make_contents_raw([]))
        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.gather", return_value={"raw": raw, "artist_data": {}}):
            result = get_artist(MagicMock(), "ar1")
        assert "error" in result

    def test_builds_and_caches_valid_artist(self):
        raw = make_raw_with_header(name="Radiohead")
        raw.update(make_contents_raw([]))
        artist_data = {"albums": {}, "singles": {}}

        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.gather", return_value={"raw": raw, "artist_data": artist_data}), \
             patch("services.artist_service.parse_top_songs_v2", return_value=[]), \
             patch("services.artist_service._ytmusic_client", return_value=MagicMock()), \
             patch("services.artist_service.get_events_cached_only", return_value=[]), \
             patch("services.artist_service.schedule_events_refresh"), \
             patch("services.artist_service.list_new_releases_for_artist", return_value=[]), \
             patch("services.artist_service.set_cached") as mock_set_cached:
            result = get_artist(MagicMock(), "ar1")

        assert result["header"]["name"] == "Radiohead"
        mock_set_cached.assert_called_once()

    def test_skips_cache_when_use_cache_false(self):
        raw = make_raw_with_header(name="Radiohead")
        raw.update(make_contents_raw([]))
        artist_data = {"albums": {}, "singles": {}}

        with patch("services.artist_service.get_cached") as mock_get_cached, \
             patch("services.artist_service.gather", return_value={"raw": raw, "artist_data": artist_data}), \
             patch("services.artist_service.parse_top_songs_v2", return_value=[]), \
             patch("services.artist_service._ytmusic_client", return_value=MagicMock()), \
             patch("services.artist_service.get_events_cached_only", return_value=[]), \
             patch("services.artist_service.schedule_events_refresh"), \
             patch("services.artist_service.list_new_releases_for_artist", return_value=[]), \
             patch("services.artist_service.set_cached"):
            get_artist(MagicMock(), "ar1", use_cache=False)

        mock_get_cached.assert_not_called()

    def test_returns_error_on_exception(self):
        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.gather", side_effect=Exception("network error")):
            result = get_artist(MagicMock(), "ar1")
        assert "error" in result

    def test_schedules_events_refresh_when_no_events(self):
        raw = make_raw_with_header(name="Radiohead")
        raw.update(make_contents_raw([]))
        artist_data = {"albums": {}, "singles": {}}

        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.gather", return_value={"raw": raw, "artist_data": artist_data}), \
             patch("services.artist_service.parse_top_songs_v2", return_value=[]), \
             patch("services.artist_service._ytmusic_client", return_value=MagicMock()), \
             patch("services.artist_service.get_events_cached_only", return_value=[]), \
             patch("services.artist_service.schedule_events_refresh") as mock_schedule, \
             patch("services.artist_service.list_new_releases_for_artist", return_value=[]), \
             patch("services.artist_service.set_cached"):
            get_artist(MagicMock(), "ar1")

        mock_schedule.assert_called_once_with("Radiohead")

    def test_does_not_schedule_events_when_events_exist(self):
        raw = make_raw_with_header(name="Radiohead")
        raw.update(make_contents_raw([]))
        artist_data = {"albums": {}, "singles": {}}

        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.gather", return_value={"raw": raw, "artist_data": artist_data}), \
             patch("services.artist_service.parse_top_songs_v2", return_value=[]), \
             patch("services.artist_service._ytmusic_client", return_value=MagicMock()), \
             patch("services.artist_service.get_events_cached_only", return_value=[{"id": "e1"}]), \
             patch("services.artist_service.schedule_events_refresh") as mock_schedule, \
             patch("services.artist_service.list_new_releases_for_artist", return_value=[]), \
             patch("services.artist_service.set_cached"):
            get_artist(MagicMock(), "ar1")

        mock_schedule.assert_not_called()

class TestGetAllAlbums:
    def test_returns_cached_when_available(self):
        cached = {"artist_id": "ar1", "albums": []}
        with patch("services.artist_service.get_cached", return_value=cached):
            result = get_all_albums("ar1")
        assert result == cached

    def test_fetches_from_browse_id_when_available(self):
        artist_data = {
            "albums": {"browseId": "MPADx", "params": "abc", "results": []}
        }
        albums_raw = [{"browseId": "a1", "title": "OK Computer", "year": "1997", "thumbnails": []}]

        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.music_client.get_artist", return_value=artist_data), \
             patch("services.artist_service.music_client.get_artist_albums", return_value=albums_raw), \
             patch("services.artist_service.set_cached") as mock_set:
            result = get_all_albums("ar1")

        assert result["total"] == 1
        assert result["albums"][0]["id"] == "a1"
        mock_set.assert_called_once()

    def test_falls_back_to_results_when_no_browse_id(self):
        artist_data = {
            "albums": {"results": [{"browseId": "a1", "title": "X", "year": "2020", "thumbnails": []}]}
        }

        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.music_client.get_artist", return_value=artist_data), \
             patch("services.artist_service.set_cached"):
            result = get_all_albums("ar1")

        assert result["total"] == 1

    def test_returns_error_on_exception(self):
        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.music_client.get_artist", side_effect=Exception("fail")):
            result = get_all_albums("ar1")
        assert "error" in result

    def test_skips_cache_when_use_cache_false(self):
        artist_data = {"albums": {"results": []}}
        with patch("services.artist_service.get_cached") as mock_get, \
             patch("services.artist_service.music_client.get_artist", return_value=artist_data), \
             patch("services.artist_service.set_cached"):
            get_all_albums("ar1", use_cache=False)
        mock_get.assert_not_called()

class TestGetAllSingles:
    def test_returns_cached_when_available(self):
        cached = {"artist_id": "ar1", "singles": []}
        with patch("services.artist_service.get_cached", return_value=cached):
            result = get_all_singles("ar1")
        assert result == cached

    def test_fetches_and_builds_singles(self):
        artist_data = {
            "singles": {"browseId": "MPADy", "params": "xyz", "results": []}
        }
        singles_raw = [{"browseId": "s1", "title": "Creep", "thumbnails": []}]

        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.music_client.get_artist", return_value=artist_data), \
             patch("services.artist_service.music_client.get_artist_albums", return_value=singles_raw), \
             patch("services.artist_service.music_client.get_album", return_value={"type": "Single", "year": "1992", "trackCount": 1}), \
             patch("services.artist_service.set_cached") as mock_set:
            result = get_all_singles("ar1")

        assert result["total"] == 1
        assert result["singles"][0]["id"] == "s1"
        mock_set.assert_called_once()

    def test_returns_error_on_exception(self):
        with patch("services.artist_service.get_cached", return_value=None), \
             patch("services.artist_service.music_client.get_artist", side_effect=Exception("fail")):
            result = get_all_singles("ar1")
        assert "error" in result

    def test_skips_cache_when_use_cache_false(self):
        artist_data = {"singles": {"results": []}}
        with patch("services.artist_service.get_cached") as mock_get, \
             patch("services.artist_service.music_client.get_artist", return_value=artist_data), \
             patch("services.artist_service.set_cached"):
            get_all_singles("ar1", use_cache=False)
        mock_get.assert_not_called()

class TestGetMoreFromArtist:
    def test_returns_albums_excluding_current(self):
        albums = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        with patch("services.artist_service.get_albums", return_value=albums):
            result = get_more_from_artist("ar1", exclude_album_id="a1")
        assert all(a["id"] != "a1" for a in result)

    def test_returns_up_to_limit(self):
        albums = [{"id": f"a{i}"} for i in range(15)]
        with patch("services.artist_service.get_albums", return_value=albums):
            result = get_more_from_artist("ar1", limit=10)
        assert len(result) <= 10

    def test_no_exclusion_returns_all(self):
        albums = [{"id": "a1"}, {"id": "a2"}]
        with patch("services.artist_service.get_albums", return_value=albums):
            result = get_more_from_artist("ar1")
        assert len(result) == 2

    def test_empty_albums_returns_empty(self):
        with patch("services.artist_service.get_albums", return_value=[]):
            result = get_more_from_artist("ar1", exclude_album_id="a1")
        assert result == []
# test/services/test_feed_fetcher.py
#
# Testeamos: services/feed_fetcher.py (funciones puras)
# - _resolve                    → sustituye {store} en URL template
# - _parse_date                 → parsea fecha según precision
# - _extract_artist_name        → join de artistas desde lista
# - _is_recent                  → compara fecha con cutoff
# - _build_pair_key             → construye key normalizada artist|title
# - _album_to_pair              → extrae (artist, title) de album item
# - build_pairs_from_albums     → construye pairs + metadata desde albums
# - filter_albums_by_type_and_date → filtra por tipo y fecha
# - dedupe_tracks               → deduplica tracks por id
#
# Las funciones IO (fetch_*) usan requests y APIs externas → no testeamos acá.
#

import datetime
import pytest
from unittest.mock import patch, MagicMock
from services.feed_source import (
    _resolve,
    _parse_date,
    _extract_artist_name,
    _is_recent,
    _build_pair_key,
    _album_to_pair, 
    build_pairs_from_albums,
    filter_albums_by_type_and_date,
    dedupe_tracks,
)

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestResolve:
    def test_substitutes_store(self):
        assert _resolve("https://api.example.com/{store}/feed", "us") == "https://api.example.com/us/feed"

    def test_empty_template_returns_empty(self):
        assert _resolve("", "us") == ""

    def test_no_placeholder_returns_template_unchanged(self):
        assert _resolve("https://api.example.com/feed", "us") == "https://api.example.com/feed"

class TestParseDate:
    def test_parses_day_precision(self):
        assert _parse_date("2024-03-15", "day") == datetime.date(2024, 3, 15)

    def test_parses_month_precision(self):
        assert _parse_date("2024-03", "month") == datetime.date(2024, 3, 1)

    def test_parses_year_precision(self):
        assert _parse_date("2024", "year") == datetime.date(2024, 1, 1)

    def test_returns_none_on_invalid_date(self):
        assert _parse_date("not-a-date", "day") is None

    def test_returns_none_on_unknown_precision(self):
        assert _parse_date("2024-03-15", "unknown") is None

    def test_returns_none_on_empty_string(self):
        assert _parse_date("", "day") is None

    def test_returns_none_on_malformed_month(self):
        assert _parse_date("2024", "month") is None  # falta el mes

class TestExtractArtistName:
    def test_single_artist(self):
        artists = [{"name": "Radiohead"}]
        assert _extract_artist_name(artists) == "Radiohead"

    def test_multiple_artists_joined(self):
        artists = [{"name": "Jay-Z"}, {"name": "Kanye West"}]
        assert _extract_artist_name(artists) == "Jay-Z, Kanye West"

    def test_skips_non_dict_items(self):
        artists = [{"name": "Radiohead"}, "not_a_dict", None]
        assert _extract_artist_name(artists) == "Radiohead"

    def test_empty_list_returns_empty_string(self):
        assert _extract_artist_name([]) == ""

    def test_artist_with_none_name_excluded(self):
        artists = [{"name": None}, {"name": "Thom Yorke"}]
        assert _extract_artist_name(artists) == ", Thom Yorke"

    def test_strips_result(self):
        artists = [{"name": "  Radiohead  "}]
        # join de "  Radiohead  " → strip al final
        assert _extract_artist_name(artists) == "Radiohead"

class TestIsRecent:
    def _cutoff(self, days_ago: int = 14) -> datetime.date:
        return datetime.date.today() - datetime.timedelta(days=days_ago)

    def test_recent_date_returns_true(self):
        cutoff = self._cutoff(14)
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        assert _is_recent(yesterday, "day", cutoff) is True

    def test_old_date_returns_false(self):
        cutoff = self._cutoff(14)
        old = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        assert _is_recent(old, "day", cutoff) is False

    def test_date_equal_to_cutoff_returns_true(self):
        cutoff = self._cutoff(14)
        assert _is_recent(cutoff.isoformat(), "day", cutoff) is True

    def test_unparseable_date_returns_true(self):
        # Si no puede parsear, incluye por defecto
        cutoff = self._cutoff(14)
        assert _is_recent("", "day", cutoff) is True
        assert _is_recent("bad-date", "day", cutoff) is True

    def test_month_precision_recent(self):
        cutoff = datetime.date.today() - datetime.timedelta(days=14)
        this_month = datetime.date.today().strftime("%Y-%m")
        assert _is_recent(this_month, "month", cutoff) is True

    def test_year_precision_old_returns_false(self):
        cutoff = datetime.date(2024, 1, 1)
        assert _is_recent("2020", "year", cutoff) is False

class TestBuildPairKey:
    def test_builds_key_with_pipe(self):
        key = _build_pair_key("Radiohead", "Creep")
        assert "|" in key

    def test_normalizes_artist_and_title(self):
        # norm() debería lowercase/strip — el resultado debe ser consistente
        k1 = _build_pair_key("Radiohead", "Creep")
        k2 = _build_pair_key("radiohead", "creep")
        assert k1 == k2

    def test_different_pairs_produce_different_keys(self):
        k1 = _build_pair_key("Radiohead", "Creep")
        k2 = _build_pair_key("Radiohead", "Karma Police")
        assert k1 != k2

class TestAlbumToPair:
    def _album(self, name="OK Computer", artists=None):
        return {
            "name": name,
            "artists": artists if artists is not None else [{"name": "Radiohead"}],
        }

    def test_returns_artist_title_tuple(self):
        result = _album_to_pair(self._album())
        assert result == ("Radiohead", "OK Computer")

    def test_returns_none_when_no_title(self):
        assert _album_to_pair(self._album(name="")) is None
        assert _album_to_pair(self._album(name=None)) is None

    def test_returns_none_when_no_artist(self):
        assert _album_to_pair({"name": "OK Computer", "artists": []}) is None
        assert _album_to_pair({"name": "OK Computer", "artists": [{"name": ""}]}) is None

    def test_strips_whitespace(self):
        result = _album_to_pair(self._album(name="  OK Computer  "))
        assert result[1] == "OK Computer"

    def test_empty_dict_returns_none(self):
        assert _album_to_pair({}) is None

class TestBuildPairsFromAlbums:
    def _album(self, name, artist, release_date=None, total_tracks=None):
        return {
            "name": name,
            "artists": [{"name": artist}],
            "release_date": release_date,
            "total_tracks": total_tracks,
        }

    def test_returns_pairs(self):
        albums = [self._album("OK Computer", "Radiohead")]
        pairs, _, _ = build_pairs_from_albums(albums)
        assert ("Radiohead", "OK Computer") in pairs

    def test_skips_albums_without_title_or_artist(self):
        albums = [
            self._album("", "Radiohead"),
            self._album("OK Computer", ""),
            self._album("Kid A", "Radiohead"),
        ]
        pairs, _, _ = build_pairs_from_albums(albums)
        assert len(pairs) == 1

    def test_collects_release_dates(self):
        albums = [self._album("OK Computer", "Radiohead", release_date="1997-05-21")]
        _, release_by_key, _ = build_pairs_from_albums(albums)
        assert len(release_by_key) == 1
        assert "1997-05-21" in release_by_key.values()

    def test_skips_empty_release_date(self):
        albums = [self._album("OK Computer", "Radiohead", release_date="")]
        _, release_by_key, _ = build_pairs_from_albums(albums)
        assert release_by_key == {}

    def test_collects_track_counts(self):
        albums = [self._album("OK Computer", "Radiohead", total_tracks=12)]
        _, _, tracks_by_key = build_pairs_from_albums(albums)
        assert 12 in tracks_by_key.values()

    def test_skips_zero_track_count(self):
        albums = [self._album("OK Computer", "Radiohead", total_tracks=0)]
        _, _, tracks_by_key = build_pairs_from_albums(albums)
        assert tracks_by_key == {}

    def test_skips_non_int_track_count(self):
        albums = [self._album("OK Computer", "Radiohead", total_tracks="12")]
        _, _, tracks_by_key = build_pairs_from_albums(albums)
        assert tracks_by_key == {}

    def test_empty_albums_returns_empty(self):
        pairs, release_by_key, tracks_by_key = build_pairs_from_albums([])
        assert pairs == []
        assert release_by_key == {}
        assert tracks_by_key == {}

class TestFilterAlbumsByTypeAndDate:
    def _album(self, album_type="album", release_date="2024-01-15", precision="day"):
        return {
            "album_type": album_type,
            "release_date": release_date,
            "release_date_precision": precision,
        }

    def _cutoff(self, days_ago=30):
        return datetime.date.today() - datetime.timedelta(days=days_ago)

    def test_keeps_recent_albums(self):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        items = [self._album(release_date=yesterday)]
        result = filter_albums_by_type_and_date(items, self._cutoff(14))
        assert len(result) == 1

    def test_filters_old_albums(self):
        old = "2020-01-01"
        items = [self._album(release_date=old)]
        result = filter_albums_by_type_and_date(items, self._cutoff(14))
        assert len(result) == 0

    def test_filters_non_album_types(self):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        items = [self._album(album_type="single", release_date=yesterday)]
        result = filter_albums_by_type_and_date(items, self._cutoff(14))
        assert len(result) == 0

    def test_custom_album_type(self):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        items = [self._album(album_type="single", release_date=yesterday)]
        result = filter_albums_by_type_and_date(items, self._cutoff(14), album_type="single")
        assert len(result) == 1

    def test_case_insensitive_album_type(self):
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        items = [self._album(album_type="ALBUM", release_date=yesterday)]
        result = filter_albums_by_type_and_date(items, self._cutoff(14))
        assert len(result) == 1

    def test_unparseable_date_included(self):
        items = [self._album(release_date="bad-date")]
        result = filter_albums_by_type_and_date(items, self._cutoff(14))
        assert len(result) == 1

    def test_empty_list_returns_empty(self):
        assert filter_albums_by_type_and_date([], self._cutoff(14)) == []

class TestDedupeTracks:
    def test_removes_duplicate_ids(self):
        tracks = [{"id": "t1"}, {"id": "t1"}, {"id": "t2"}]
        result = dedupe_tracks(tracks)
        assert len(result) == 2

    def test_preserves_first_occurrence(self):
        tracks = [{"id": "t1", "title": "First"}, {"id": "t1", "title": "Second"}]
        result = dedupe_tracks(tracks)
        assert result[0]["title"] == "First"

    def test_keeps_tracks_without_id(self):
        # tracks sin id no se deduplan pero tampoco se agregan al seen
        tracks = [{"title": "No ID"}, {"title": "Also No ID"}]
        result = dedupe_tracks(tracks)
        assert len(result) == 0

    def test_empty_list_returns_empty(self):
        assert dedupe_tracks([]) == []

    def test_preserves_order(self):
        tracks = [{"id": "t3"}, {"id": "t1"}, {"id": "t2"}]
        result = dedupe_tracks(tracks)
        assert [t["id"] for t in result] == ["t3", "t1", "t2"]

    def test_all_unique_returns_all(self):
        tracks = [{"id": f"t{i}"} for i in range(5)]
        assert len(dedupe_tracks(tracks)) == 5
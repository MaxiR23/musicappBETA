# test/routes/test_artist_routes.py
#
# Testeamos: routes/artist.py
# Contrato HTTP: status code, shape del response, params a services.
#
# _enrich_artist_payload     → agrega eventos y upcoming_album
# _schedule_warm_for_top_songs → warm de top songs
# _handle_artist_request     → 502 en error, enrich, warm
# GET /artist?id=            → query param
# GET /artist/{id}           → path param
# GET /artist/{id}/albums    → albums paginados
# GET /artist/{id}/singles   → singles paginados
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routes.artists import router, _enrich_artist_payload, _schedule_warm_for_top_songs
from core.dependencies import get_db

# ════════════════════════════════════════════════════════
# APP DE TEST
# ════════════════════════════════════════════════════════
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    return TestClient(app)


# ════════════════════════════════════════════════════════
# _enrich_artist_payload
# ════════════════════════════════════════════════════════
class TestEnrichArtistPayload:
    def _db(self):
        return MagicMock()

    def test_fetches_events_when_upcoming_events_empty(self):
        payload = {"header": {"name": "Radiohead"}, "upcoming_events": []}
        with patch("routes.artists.get_events_cached_only", return_value=[{"id": "e1"}]) as mock_events, \
             patch("routes.artists.get_upcoming_by_artist_id_cached", return_value=None):
            result = _enrich_artist_payload(self._db(), payload, "ar1")
        mock_events.assert_called_once_with("Radiohead", limit=10)
        assert result["upcoming_events"] == [{"id": "e1"}]

    def test_skips_events_when_already_present(self):
        payload = {"header": {"name": "Radiohead"}, "upcoming_events": [{"id": "e1"}]}
        with patch("routes.artists.get_events_cached_only") as mock_events, \
             patch("routes.artists.get_upcoming_by_artist_id_cached", return_value=None):
            _enrich_artist_payload(self._db(), payload, "ar1")
        mock_events.assert_not_called()

    def test_skips_events_when_no_artist_name(self):
        payload = {"header": {}, "upcoming_events": []}
        with patch("routes.artists.get_events_cached_only") as mock_events, \
             patch("routes.artists.get_upcoming_by_artist_id_cached", return_value=None):
            _enrich_artist_payload(self._db(), payload, "ar1")
        mock_events.assert_not_called()

    def test_adds_upcoming_album(self):
        payload = {"upcoming_events": [{"id": "e1"}]}
        upcoming = {"id": "al1", "title": "New Album"}
        with patch("routes.artists.get_upcoming_by_artist_id_cached", return_value=upcoming):
            result = _enrich_artist_payload(self._db(), payload, "ar1")
        assert result["upcoming_album"] == upcoming

    def test_upcoming_album_none_on_exception(self):
        payload = {"upcoming_events": []}
        with patch("routes.artists.get_events_cached_only", return_value=[]), \
             patch("routes.artists.get_upcoming_by_artist_id_cached", side_effect=Exception("db error")):
            result = _enrich_artist_payload(self._db(), payload, "ar1")
        assert result["upcoming_album"] is None

# ════════════════════════════════════════════════════════
# _schedule_warm_for_top_songs
# ════════════════════════════════════════════════════════
class TestScheduleWarmForTopSongs:
    def test_schedules_top_song_ids(self):
        payload = {"top_songs": [{"id": "v1"}, {"id": "v2"}]}
        with patch("routes.artists.schedule_warm") as mock_warm, \
             patch("routes.artists.get_warm_burst", return_value=20):
            _schedule_warm_for_top_songs(payload)
        mock_warm.assert_called_once_with(["v1", "v2"])

    def test_capped_by_warm_burst(self):
        payload = {"top_songs": [{"id": f"v{i}"} for i in range(30)]}
        with patch("routes.artists.schedule_warm") as mock_warm, \
             patch("routes.artists.get_warm_burst", return_value=5):
            _schedule_warm_for_top_songs(payload)
        assert len(mock_warm.call_args[0][0]) == 5

    def test_skips_songs_without_id(self):
        payload = {"top_songs": [{"title": "no id"}, {"id": None}, {"id": "v1"}]}
        with patch("routes.artists.schedule_warm") as mock_warm, \
             patch("routes.artists.get_warm_burst", return_value=20):
            _schedule_warm_for_top_songs(payload)
        mock_warm.assert_called_once_with(["v1"])

    def test_empty_top_songs(self):
        with patch("routes.artists.schedule_warm") as mock_warm, \
             patch("routes.artists.get_warm_burst", return_value=20):
            _schedule_warm_for_top_songs({})
        mock_warm.assert_called_once_with([])

    def test_skips_non_dict_items(self):
        payload = {"top_songs": ["not_a_dict", {"id": "v1"}]}
        with patch("routes.artists.schedule_warm") as mock_warm, \
             patch("routes.artists.get_warm_burst", return_value=20):
            _schedule_warm_for_top_songs(payload)
        mock_warm.assert_called_once_with(["v1"])

# ════════════════════════════════════════════════════════
# GET /artist?id=
# ════════════════════════════════════════════════════════
class TestGetArtistQuery:
    def _valid_payload(self):
        return {"id": "ar1", "header": {"name": "Radiohead"}, "top_songs": [], "upcoming_events": []}

    def test_returns_200_on_valid_payload(self, client):
        with patch("routes.artists.get_artist", return_value=self._valid_payload()), \
             patch("routes.artists.get_events_cached_only", return_value=[]), \
             patch("routes.artists.get_upcoming_by_artist_id_cached", return_value=None), \
             patch("routes.artists.schedule_warm"), \
             patch("routes.artists.get_warm_burst", return_value=20):
            r = client.get("/artist?id=ar1")
        assert r.status_code == 200

    def test_passes_id_to_service(self, client):
        with patch("routes.artists.get_artist", return_value=self._valid_payload()) as mock_get, \
             patch("routes.artists.get_events_cached_only", return_value=[]), \
             patch("routes.artists.get_upcoming_by_artist_id_cached", return_value=None), \
             patch("routes.artists.schedule_warm"), \
             patch("routes.artists.get_warm_burst", return_value=20):
            client.get("/artist?id=ar1")
        assert mock_get.call_args[0][1] == "ar1"

    def test_missing_query_param_returns_422(self, client):
        r = client.get("/artist")
        assert r.status_code == 422

    def test_returns_502_when_error_in_payload(self, client):
        with patch("routes.artists.get_artist", return_value={"error": "fetch_failed"}), \
             patch("routes.artists.schedule_warm"), \
             patch("routes.artists.get_warm_burst", return_value=20):
            r = client.get("/artist?id=ar1")
        assert r.status_code == 502
        assert r.json()["error"] == "fetch_failed"

    def test_returns_502_on_exception(self, client):
        with patch("routes.artists.get_artist", side_effect=Exception("network error")):
            r = client.get("/artist?id=ar1")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

# ════════════════════════════════════════════════════════
# GET /artist/{id}
# ════════════════════════════════════════════════════════
class TestGetArtistPath:
    def _valid_payload(self):
        return {"id": "ar1", "header": {"name": "Radiohead"}, "top_songs": [], "upcoming_events": []}

    def test_returns_200_on_valid_payload(self, client):
        with patch("routes.artists.get_artist", return_value=self._valid_payload()), \
             patch("routes.artists.get_events_cached_only", return_value=[]), \
             patch("routes.artists.get_upcoming_by_artist_id_cached", return_value=None), \
             patch("routes.artists.schedule_warm"), \
             patch("routes.artists.get_warm_burst", return_value=20):
            r = client.get("/artist/ar1")
        assert r.status_code == 200

    def test_passes_correct_id(self, client):
        with patch("routes.artists.get_artist", return_value=self._valid_payload()) as mock_get, \
             patch("routes.artists.get_events_cached_only", return_value=[]), \
             patch("routes.artists.get_upcoming_by_artist_id_cached", return_value=None), \
             patch("routes.artists.schedule_warm"), \
             patch("routes.artists.get_warm_burst", return_value=20):
            client.get("/artist/UCar_xyz")
        assert mock_get.call_args[0][1] == "UCar_xyz"

    def test_returns_502_when_error(self, client):
        with patch("routes.artists.get_artist", return_value={"error": "service_unavailable"}), \
             patch("routes.artists.schedule_warm"), \
             patch("routes.artists.get_warm_burst", return_value=20):
            r = client.get("/artist/ar1")
        assert r.status_code == 502

    def test_enriches_payload(self, client):
        payload = self._valid_payload()
        with patch("routes.artists.get_artist", return_value=payload), \
             patch("routes.artists.get_events_cached_only", return_value=[]), \
             patch("routes.artists.get_upcoming_by_artist_id_cached", return_value={"id": "al-upcoming"}), \
             patch("routes.artists.schedule_warm"), \
             patch("routes.artists.get_warm_burst", return_value=20):
            r = client.get("/artist/ar1")
        assert r.json()["upcoming_album"] == {"id": "al-upcoming"}

# ════════════════════════════════════════════════════════
# GET /artist/{id}/albums
# ════════════════════════════════════════════════════════
class TestGetArtistAllAlbums:
    def test_returns_200_with_albums(self, client):
        payload = {"artist_id": "ar1", "total": 2, "albums": [{"id": "a1"}, {"id": "a2"}]}
        with patch("routes.artists.get_all_albums", return_value=payload):
            r = client.get("/artist/ar1/albums")
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_passes_artist_id(self, client):
        with patch("routes.artists.get_all_albums", return_value={}) as mock_get:
            client.get("/artist/UCar_xyz/albums")
        mock_get.assert_called_once_with("UCar_xyz")

    def test_returns_502_when_error(self, client):
        with patch("routes.artists.get_all_albums", return_value={"error": "fetch_failed"}):
            r = client.get("/artist/ar1/albums")
        assert r.status_code == 502

    def test_returns_502_on_exception(self, client):
        with patch("routes.artists.get_all_albums", side_effect=Exception("fail")):
            r = client.get("/artist/ar1/albums")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

# ════════════════════════════════════════════════════════
# GET /artist/{id}/singles
# ════════════════════════════════════════════════════════
class TestGetArtistAllSingles:
    def test_returns_200_with_singles(self, client):
        payload = {"artist_id": "ar1", "total": 1, "singles": [{"id": "s1"}]}
        with patch("routes.artists.get_all_singles", return_value=payload):
            r = client.get("/artist/ar1/singles")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_passes_artist_id(self, client):
        with patch("routes.artists.get_all_singles", return_value={}) as mock_get:
            client.get("/artist/UCar_xyz/singles")
        mock_get.assert_called_once_with("UCar_xyz")

    def test_returns_502_when_error(self, client):
        with patch("routes.artists.get_all_singles", return_value={"error": "fetch_failed"}):
            r = client.get("/artist/ar1/singles")
        assert r.status_code == 502

    def test_returns_502_on_exception(self, client):
        with patch("routes.artists.get_all_singles", side_effect=Exception("fail")):
            r = client.get("/artist/ar1/singles")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"
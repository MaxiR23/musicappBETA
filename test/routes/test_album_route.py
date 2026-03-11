# test/routes/test_album_routes.py
#
# Testeamos: routes/album.py
# Contrato HTTP: status code, shape del response, params a services.
#
# _handle_album_request  → lógica común (error 502, warm scheduling)
# GET /album?id=         → query param
# GET /album/{id}        → path param
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routes.album import router

# ════════════════════════════════════════════════════════
# APP DE TEST
# ════════════════════════════════════════════════════════
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

# ════════════════════════════════════════════════════════
# _handle_album_request (helper del router)
# ════════════════════════════════════════════════════════
class TestHandleAlbumRequest:
    def test_returns_502_when_payload_has_error(self, client):
        with patch("routes.album.get_album", return_value={"error": "fetch_failed"}), \
             patch("routes.album.schedule_warm"), \
             patch("routes.album.get_warm_burst", return_value=20):
            r = client.get("/album/al1")
        assert r.status_code == 502
        assert r.json()["error"] == "fetch_failed"

    def test_returns_200_on_valid_payload(self, client):
        payload = {"id": "al1", "info": {"title": "OK Computer"}, "tracks": []}
        with patch("routes.album.get_album", return_value=payload), \
             patch("routes.album.schedule_warm"), \
             patch("routes.album.get_warm_burst", return_value=20):
            r = client.get("/album/al1")
        assert r.status_code == 200

    def test_schedules_warm_with_track_video_ids(self, client):
        payload = {
            "id": "al1",
            "tracks": [{"videoId": "v1"}, {"videoId": "v2"}, {"title": "no id"}]
        }
        with patch("routes.album.get_album", return_value=payload), \
             patch("routes.album.schedule_warm") as mock_warm, \
             patch("routes.album.get_warm_burst", return_value=20):
            client.get("/album/al1")
        mock_warm.assert_called_once_with(["v1", "v2"])

    def test_warm_capped_by_warm_burst(self, client):
        tracks = [{"videoId": f"v{i}"} for i in range(30)]
        payload = {"id": "al1", "tracks": tracks}
        with patch("routes.album.get_album", return_value=payload), \
             patch("routes.album.schedule_warm") as mock_warm, \
             patch("routes.album.get_warm_burst", return_value=5):
            client.get("/album/al1")
        ids_sent = mock_warm.call_args[0][0]
        assert len(ids_sent) == 5

    def test_skips_tracks_without_video_id(self, client):
        payload = {"id": "al1", "tracks": [{"title": "no id"}, {"videoId": None}]}
        with patch("routes.album.get_album", return_value=payload), \
             patch("routes.album.schedule_warm") as mock_warm, \
             patch("routes.album.get_warm_burst", return_value=20):
            client.get("/album/al1")
        mock_warm.assert_called_once_with([])

    def test_returns_502_on_exception(self, client):
        with patch("routes.album.get_album", side_effect=Exception("network error")):
            r = client.get("/album/al1")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

    def test_502_includes_detail_on_exception(self, client):
        with patch("routes.album.get_album", side_effect=Exception("timeout")):
            r = client.get("/album/al1")
        assert "detail" in r.json()

# ════════════════════════════════════════════════════════
# GET /album?id=
# ════════════════════════════════════════════════════════
class TestGetAlbumQuery:
    def test_returns_album_by_query_param(self, client):
        payload = {"id": "al1", "info": {"title": "OK Computer"}, "tracks": []}
        with patch("routes.album.get_album", return_value=payload) as mock_get, \
             patch("routes.album.schedule_warm"), \
             patch("routes.album.get_warm_burst", return_value=20):
            r = client.get("/album?id=al1")
        assert r.status_code == 200
        mock_get.assert_called_once_with("al1")

    def test_missing_query_param_returns_422(self, client):
        r = client.get("/album")
        assert r.status_code == 422

    def test_response_contains_payload(self, client):
        payload = {"id": "al1", "info": {"title": "OK Computer"}, "tracks": []}
        with patch("routes.album.get_album", return_value=payload), \
             patch("routes.album.schedule_warm"), \
             patch("routes.album.get_warm_burst", return_value=20):
            r = client.get("/album?id=al1")
        assert r.json()["id"] == "al1"

# ════════════════════════════════════════════════════════
# GET /album/{id}
# ════════════════════════════════════════════════════════
class TestGetAlbumPath:
    def test_returns_album_by_path_param(self, client):
        payload = {"id": "al1", "info": {"title": "Kid A"}, "tracks": []}
        with patch("routes.album.get_album", return_value=payload) as mock_get, \
             patch("routes.album.schedule_warm"), \
             patch("routes.album.get_warm_burst", return_value=20):
            r = client.get("/album/al1")
        assert r.status_code == 200
        mock_get.assert_called_once_with("al1")

    def test_passes_correct_id(self, client):
        payload = {"id": "MPREb_xyz", "tracks": []}
        with patch("routes.album.get_album", return_value=payload) as mock_get, \
             patch("routes.album.schedule_warm"), \
             patch("routes.album.get_warm_burst", return_value=20):
            client.get("/album/MPREb_xyz")
        mock_get.assert_called_once_with("MPREb_xyz")

    def test_error_payload_returns_502(self, client):
        with patch("routes.album.get_album", return_value={"error": "service_unavailable"}), \
             patch("routes.album.schedule_warm"), \
             patch("routes.album.get_warm_burst", return_value=20):
            r = client.get("/album/bad-id")
        assert r.status_code == 502
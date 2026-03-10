# test/routes/test_tracks_routes.py
#
# Testeamos: routes/tracks.py
# GET /tracks/{id}/lyrics      → 200 ok, 404 sin lyrics, 502 en error
# GET /tracks/{id}/related     → 200 ok, 404 sin related, 502 en error
# GET /tracks/{id}/related-raw → 200 ok, 404 sin data, 502 en error
# GET /tracks/{id}/upnext      → 200 ok, 404 sin upnext, 502 en error
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from routes.tracks import router

TRACK_ID = "abc123"

LYRICS_OK    = {"ok": True, "lyrics": "Some lyrics here", "source": "YouTube"}
RELATED_OK   = {"ok": True, "related": [{"title": "Section"}]}
UPNEXT_OK    = {"ok": True, "current": {"id": TRACK_ID}, "up_next": []}
NOT_OK       = {"ok": False, "reason": "no_lyrics"}

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

# ════════════════════════════════════════════════════════
# GET /tracks/{id}/lyrics
# ════════════════════════════════════════════════════════
class TestGetTrackLyrics:
    def test_returns_200_when_ok(self, client):
        with patch("routes.tracks.get_lyrics", return_value=LYRICS_OK):
            r = client.get(f"/tracks/{TRACK_ID}/lyrics")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["lyrics"] == "Some lyrics here"

    def test_returns_404_when_not_ok(self, client):
        with patch("routes.tracks.get_lyrics", return_value=NOT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/lyrics")
        assert r.status_code == 404
        assert r.json()["ok"] is False

    def test_passes_track_id_to_service(self, client):
        with patch("routes.tracks.get_lyrics", return_value=LYRICS_OK) as mock:
            client.get(f"/tracks/{TRACK_ID}/lyrics")
        mock.assert_called_once_with(TRACK_ID)

    def test_returns_502_on_exception(self, client):
        with patch("routes.tracks.get_lyrics", side_effect=Exception("ytm down")):
            r = client.get(f"/tracks/{TRACK_ID}/lyrics")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

# ════════════════════════════════════════════════════════
# GET /tracks/{id}/related
# ════════════════════════════════════════════════════════
class TestGetTrackRelated:
    def test_returns_200_when_ok(self, client):
        with patch("routes.tracks.get_related", return_value=RELATED_OK):
            r = client.get(f"/tracks/{TRACK_ID}/related")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_returns_404_when_not_ok(self, client):
        with patch("routes.tracks.get_related", return_value=NOT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/related")
        assert r.status_code == 404

    def test_passes_track_id_to_service(self, client):
        with patch("routes.tracks.get_related", return_value=RELATED_OK) as mock:
            client.get(f"/tracks/{TRACK_ID}/related")
        mock.assert_called_once_with(TRACK_ID)

    def test_returns_502_on_exception(self, client):
        with patch("routes.tracks.get_related", side_effect=Exception("ytm down")):
            r = client.get(f"/tracks/{TRACK_ID}/related")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

# ════════════════════════════════════════════════════════
# GET /tracks/{id}/related-raw
# ════════════════════════════════════════════════════════
class TestGetTrackRelatedRaw:
    def test_returns_200_when_ok(self, client):
        raw_ok = {"ok": True, "related_raw": [], "browse_id": "br1"}
        with patch("routes.tracks.get_related_raw", return_value=raw_ok):
            r = client.get(f"/tracks/{TRACK_ID}/related-raw")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_returns_404_when_not_ok(self, client):
        with patch("routes.tracks.get_related_raw", return_value=NOT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/related-raw")
        assert r.status_code == 404

    def test_passes_track_id_to_service(self, client):
        raw_ok = {"ok": True, "related_raw": []}
        with patch("routes.tracks.get_related_raw", return_value=raw_ok) as mock:
            client.get(f"/tracks/{TRACK_ID}/related-raw")
        mock.assert_called_once_with(TRACK_ID)

    def test_returns_502_on_exception(self, client):
        with patch("routes.tracks.get_related_raw", side_effect=Exception("ytm down")):
            r = client.get(f"/tracks/{TRACK_ID}/related-raw")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /tracks/{id}/upnext
# ════════════════════════════════════════════════════════
class TestGetTrackUpnext:
    def test_returns_200_when_ok(self, client):
        with patch("routes.tracks.get_up_next", return_value=UPNEXT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/upnext")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["current"]["id"] == TRACK_ID

    def test_returns_404_when_not_ok(self, client):
        with patch("routes.tracks.get_up_next", return_value=NOT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/upnext")
        assert r.status_code == 404

    def test_passes_track_id_to_service(self, client):
        with patch("routes.tracks.get_up_next", return_value=UPNEXT_OK) as mock:
            client.get(f"/tracks/{TRACK_ID}/upnext")
        mock.assert_called_once_with(TRACK_ID)

    def test_returns_502_on_exception(self, client):
        with patch("routes.tracks.get_up_next", side_effect=Exception("ytm down")):
            r = client.get(f"/tracks/{TRACK_ID}/upnext")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"
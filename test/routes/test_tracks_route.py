# test/routes/test_tracks_routes.py
#
# Testeamos: routes/tracks.py
# GET /tracks/{id}/lyrics      → 200 ok, 200 sin lyrics, 502 en service error, 502 en exception
# GET /tracks/{id}/related     → 200 ok, 200 sin related, 502 en service error, 502 en exception
# GET /tracks/{id}/related-raw → 200 ok, 200 sin data, 502 en service error, 502 en exception
# GET /tracks/{id}/upnext      → 200 ok, 200 sin upnext, 502 en service error, 502 en exception
# GET /tracks/{id}/credits     → 200 ok, 200 sin credits, 502 en service error, 502 en exception
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
CREDITS_OK   = {"ok": True, "credits": [{"title": "Produced by", "artists": []}]}
NOT_OK       = {"ok": False, "reason": "no_lyrics"}
NOT_OK_ERROR = {"ok": False, "reason": "error", "detail": "ytm failed"}
NOT_OK_INVALID_ID      = {"ok": False, "reason": "invalid_id"}
NOT_OK_NO_WATCH        = {"ok": False, "reason": "no_watch_playlist"}
NOT_OK_NO_BROWSE       = {"ok": False, "reason": "no_browse_id"}
NOT_OK_NO_TRACKS       = {"ok": False, "reason": "no_tracks"}

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

    def test_returns_200_when_data_not_found(self, client):
        with patch("routes.tracks.get_lyrics", return_value=NOT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/lyrics")
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_returns_502_when_service_error(self, client):
        with patch("routes.tracks.get_lyrics", return_value=NOT_OK_ERROR):
            r = client.get(f"/tracks/{TRACK_ID}/lyrics")
        assert r.status_code == 502

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

    def test_returns_200_when_data_not_found(self, client):
        with patch("routes.tracks.get_related", return_value=NOT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/related")
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_returns_502_when_service_error(self, client):
        with patch("routes.tracks.get_related", return_value=NOT_OK_ERROR):
            r = client.get(f"/tracks/{TRACK_ID}/related")
        assert r.status_code == 502

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

    def test_returns_200_when_data_not_found(self, client):
        with patch("routes.tracks.get_related_raw", return_value=NOT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/related-raw")
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_returns_502_when_service_error(self, client):
        with patch("routes.tracks.get_related_raw", return_value=NOT_OK_ERROR):
            r = client.get(f"/tracks/{TRACK_ID}/related-raw")
        assert r.status_code == 502

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

    def test_returns_200_when_data_not_found(self, client):
        with patch("routes.tracks.get_up_next", return_value=NOT_OK):
            r = client.get(f"/tracks/{TRACK_ID}/upnext")
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_returns_502_when_service_error(self, client):
        with patch("routes.tracks.get_up_next", return_value=NOT_OK_ERROR):
            r = client.get(f"/tracks/{TRACK_ID}/upnext")
        assert r.status_code == 502

    def test_passes_track_id_to_service(self, client):
        with patch("routes.tracks.get_up_next", return_value=UPNEXT_OK) as mock:
            client.get(f"/tracks/{TRACK_ID}/upnext")
        mock.assert_called_once_with(TRACK_ID)

    def test_returns_502_on_exception(self, client):
        with patch("routes.tracks.get_up_next", side_effect=Exception("ytm down")):
            r = client.get(f"/tracks/{TRACK_ID}/upnext")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

# ════════════════════════════════════════════════════════
# GET /tracks/{id}/credits
# ════════════════════════════════════════════════════════
class TestGetTrackCredits:
    def test_returns_200_when_ok(self, client):
        with patch("routes.tracks.get_credits", return_value=CREDITS_OK):
            r = client.get(f"/tracks/{TRACK_ID}/credits")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_returns_200_when_data_not_found(self, client):
        not_ok_credits = {"ok": False, "reason": "no_credits"}
        with patch("routes.tracks.get_credits", return_value=not_ok_credits):
            r = client.get(f"/tracks/{TRACK_ID}/credits")
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_returns_502_when_service_error(self, client):
        with patch("routes.tracks.get_credits", return_value=NOT_OK_ERROR):
            r = client.get(f"/tracks/{TRACK_ID}/credits")
        assert r.status_code == 502

    def test_passes_track_id_to_service(self, client):
        with patch("routes.tracks.get_credits", return_value=CREDITS_OK) as mock:
            client.get(f"/tracks/{TRACK_ID}/credits")
        mock.assert_called_once_with(TRACK_ID)

    def test_returns_422_when_invalid_id(self, client):
        with patch("routes.tracks.get_credits", return_value=NOT_OK_INVALID_ID):
            r = client.get(f"/tracks/{TRACK_ID}/credits")
        assert r.status_code == 422

    def test_returns_502_on_exception(self, client):
        with patch("routes.tracks.get_credits", side_effect=Exception("ytm down")):
            r = client.get(f"/tracks/{TRACK_ID}/credits")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

# ════════════════════════════════════════════════════════
# Reason-to-status contract: ambiguous reasons → 200
# Documents the intended mapping for reasons that could signal
# either a bad track ID or a legitimate no-data case.
# ════════════════════════════════════════════════════════
class TestReasonStatusContract:
    def test_no_watch_playlist_returns_200(self, client):
        with patch("routes.tracks.get_related", return_value=NOT_OK_NO_WATCH):
            r = client.get(f"/tracks/{TRACK_ID}/related")
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_no_browse_id_returns_200(self, client):
        with patch("routes.tracks.get_related", return_value=NOT_OK_NO_BROWSE):
            r = client.get(f"/tracks/{TRACK_ID}/related")
        assert r.status_code == 200

    def test_no_tracks_returns_200(self, client):
        with patch("routes.tracks.get_up_next", return_value=NOT_OK_NO_TRACKS):
            r = client.get(f"/tracks/{TRACK_ID}/upnext")
        assert r.status_code == 200

    def test_unknown_reason_returns_502(self, client):
        with patch("routes.tracks.get_related", return_value={"ok": False, "reason": "unexpected_failure"}):
            r = client.get(f"/tracks/{TRACK_ID}/related")
        assert r.status_code == 502
# test/routes/test_station_route.py
#
# Testeamos: routes/station.py
# GET /station/user             → 200 ok, 200 sin data, 502 en service error, 502 en exception
# GET /station/artist/{id}      → 200 ok, 200 sin data, 502 en service error, 502 en exception
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from routes.station import router

USER_ID   = "user-123"
ARTIST_ID = "artist-456"

STATIONS_OK = {"ok": True, "stations": [{"artist_id": ARTIST_ID, "name": "Artist", "thumbnail": None}]}
TRACKS_OK   = {"ok": True, "tracks": [{"id": "t1", "title": "Song"}]}
NO_DATA_STATIONS = {"ok": False, "reason": "no_stations_available"}
NO_DATA_TRACKS   = {"ok": False, "reason": "station_not_found"}
SERVICE_ERROR    = {"ok": False, "reason": "error"}

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/station")
    app.dependency_overrides = {}
    return TestClient(app)

def _override_deps(app, user_id=USER_ID):
    from core.dependencies import get_current_user_id, get_db
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_db] = lambda: None

# ════════════════════════════════════════════════════════
# GET /station/user
# ════════════════════════════════════════════════════════
class TestGetUserStations:
    @pytest.fixture
    def client(self):
        app = FastAPI()
        app.include_router(router, prefix="/station")
        _override_deps(app)
        return TestClient(app)

    def test_returns_200_with_stations_when_ok(self, client):
        with patch("routes.station.get_user_stations", return_value=STATIONS_OK):
            r = client.get("/station/user")
        assert r.status_code == 200
        assert "stations" in r.json()

    def test_returns_200_when_no_data(self, client):
        with patch("routes.station.get_user_stations", return_value=NO_DATA_STATIONS):
            r = client.get("/station/user")
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert r.json()["reason"] == "no_stations_available"

    def test_returns_502_when_service_error(self, client):
        with patch("routes.station.get_user_stations", return_value=SERVICE_ERROR):
            r = client.get("/station/user")
        assert r.status_code == 502

    def test_returns_502_on_exception(self, client):
        with patch("routes.station.get_user_stations", side_effect=Exception("db down")):
            r = client.get("/station/user")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /station/artist/{artist_id}
# ════════════════════════════════════════════════════════
class TestGetArtistStation:
    def test_returns_200_with_tracks_when_ok(self, client):
        with patch("routes.station.get_station_tracks", return_value=TRACKS_OK):
            r = client.get(f"/station/artist/{ARTIST_ID}")
        assert r.status_code == 200
        assert "tracks" in r.json()

    def test_returns_200_when_no_station(self, client):
        with patch("routes.station.get_station_tracks", return_value=NO_DATA_TRACKS):
            r = client.get(f"/station/artist/{ARTIST_ID}")
        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert r.json()["reason"] == "station_not_found"

    def test_returns_502_when_service_error(self, client):
        with patch("routes.station.get_station_tracks", return_value=SERVICE_ERROR):
            r = client.get(f"/station/artist/{ARTIST_ID}")
        assert r.status_code == 502

    def test_returns_502_on_exception(self, client):
        with patch("routes.station.get_station_tracks", side_effect=Exception("ytm down")):
            r = client.get(f"/station/artist/{ARTIST_ID}")
        assert r.status_code == 502
# test/routes/test_upcoming_releases_routes.py
#
# Testeamos: routes/upcoming_releases.py
# GET /  → releases futuros con include_tba/limit opcionales, count correcto, 502 en error
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routes.upcoming_releases import router
from core.dependencies import get_db

FAKE_DB = MagicMock()

RELEASES = [
    {"release_date": "2026-06-01", "artist": "Radiohead", "album": "New Album"},
    {"release_date": "2026-07-01", "artist": "Tame Impala", "album": "Another One"},
]

URL = "/upcoming-releases"

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/upcoming-releases")
    app.dependency_overrides[get_db] = lambda: FAKE_DB
    return TestClient(app)

# ════════════════════════════════════════════════════════
# GET /upcoming-releases
# ════════════════════════════════════════════════════════
class TestGetUpcomingReleases:
    def test_returns_200_with_releases(self, client):
        with patch("routes.upcoming_releases.list_upcoming_releases_cached", return_value=RELEASES):
            r = client.get(URL)
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["releases"] == RELEASES

    def test_count_matches_releases_length(self, client):
        with patch("routes.upcoming_releases.list_upcoming_releases_cached", return_value=RELEASES):
            r = client.get(URL)
        assert r.json()["count"] == len(RELEASES)

    def test_empty_releases_returns_count_zero(self, client):
        with patch("routes.upcoming_releases.list_upcoming_releases_cached", return_value=[]):
            r = client.get(URL)
        assert r.json()["count"] == 0
        assert r.json()["releases"] == []

    def test_passes_db_and_defaults(self, client):
        with patch("routes.upcoming_releases.list_upcoming_releases_cached", return_value=[]) as mock:
            client.get(URL)
        mock.assert_called_once_with(FAKE_DB, include_tba=True, limit=50)

    def test_passes_include_tba_false(self, client):
        with patch("routes.upcoming_releases.list_upcoming_releases_cached", return_value=[]) as mock:
            client.get(f"{URL}?include_tba=false")
        mock.assert_called_once_with(FAKE_DB, include_tba=False, limit=50)

    def test_passes_custom_limit(self, client):
        with patch("routes.upcoming_releases.list_upcoming_releases_cached", return_value=[]) as mock:
            client.get(f"{URL}?limit=10")
        mock.assert_called_once_with(FAKE_DB, include_tba=True, limit=10)

    def test_limit_below_min_returns_422(self, client):
        r = client.get(f"{URL}?limit=0")
        assert r.status_code == 422

    def test_limit_above_max_returns_422(self, client):
        r = client.get(f"{URL}?limit=101")
        assert r.status_code == 422

    def test_returns_502_on_exception(self, client):
        with patch("routes.upcoming_releases.list_upcoming_releases_cached", side_effect=Exception("db down")):
            r = client.get(URL)
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"
        assert r.json()["ok"] is False
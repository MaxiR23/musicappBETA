# test/routes/test_stats_routes.py
#
# Testeamos: routes/stats.py
# GET /weekly  → summary semanal con include/limit opcionales, 502 en error
# GET /monthly → summary mensual con include/limit opcionales, 502 en error
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routes.stats import router
from core.dependencies import get_user_db, get_current_user_id

FAKE_USER_ID = "user-123"
FAKE_DB = MagicMock()

WEEKLY_RESULT = {
    "week_start": "2026-01-01",
    "artists": [{"entity_id": "a1"}],
    "albums": [],
    "tracks": [],
}

MONTHLY_RESULT = {
    "month_start": "2026-01-01",
    "artists": [{"entity_id": "a1"}],
    "albums": [],
    "tracks": [],
}

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_db] = lambda: FAKE_DB
    app.dependency_overrides[get_current_user_id] = lambda: FAKE_USER_ID
    return TestClient(app)

@pytest.fixture
def unauthed_client():
    from fastapi import HTTPException
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_db] = lambda: FAKE_DB
    app.dependency_overrides[get_current_user_id] = lambda: (_ for _ in ()).throw(
        HTTPException(status_code=401, detail="unauthorized")
    )
    return TestClient(app, raise_server_exceptions=False)

# ════════════════════════════════════════════════════════
# GET /weekly
# ════════════════════════════════════════════════════════
class TestWeeklySummary:
    def test_returns_200_with_result(self, client):
        with patch("routes.stats.get_weekly_summary", return_value=WEEKLY_RESULT):
            r = client.get("/weekly")
        assert r.status_code == 200
        assert r.json()["week_start"] == "2026-01-01"

    def test_passes_user_id_and_db(self, client):
        with patch("routes.stats.get_weekly_summary", return_value=WEEKLY_RESULT) as mock:
            client.get("/weekly")
        mock.assert_called_once_with(FAKE_DB, FAKE_USER_ID, include=None, limit=None)

    def test_passes_include_param(self, client):
        with patch("routes.stats.get_weekly_summary", return_value=WEEKLY_RESULT) as mock:
            client.get("/weekly?include=artists")
        mock.assert_called_once_with(FAKE_DB, FAKE_USER_ID, include="artists", limit=None)

    def test_passes_limit_param(self, client):
        with patch("routes.stats.get_weekly_summary", return_value=WEEKLY_RESULT) as mock:
            client.get("/weekly?limit=5")
        mock.assert_called_once_with(FAKE_DB, FAKE_USER_ID, include=None, limit=5)

    def test_passes_include_and_limit(self, client):
        with patch("routes.stats.get_weekly_summary", return_value=WEEKLY_RESULT) as mock:
            client.get("/weekly?include=artists,albums&limit=10")
        mock.assert_called_once_with(FAKE_DB, FAKE_USER_ID, include="artists,albums", limit=10)

    def test_returns_502_on_exception(self, client):
        with patch("routes.stats.get_weekly_summary", side_effect=Exception("db down")):
            r = client.get("/weekly")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

    def test_returns_401_when_unauthenticated(self, unauthed_client):
        r = unauthed_client.get("/weekly")
        assert r.status_code == 401

# ════════════════════════════════════════════════════════
# GET /monthly
# ════════════════════════════════════════════════════════
class TestMonthlySummary:
    def test_returns_200_with_result(self, client):
        with patch("routes.stats.get_monthly_summary", return_value=MONTHLY_RESULT):
            r = client.get("/monthly")
        assert r.status_code == 200
        assert r.json()["month_start"] == "2026-01-01"

    def test_passes_user_id_and_db(self, client):
        with patch("routes.stats.get_monthly_summary", return_value=MONTHLY_RESULT) as mock:
            client.get("/monthly")
        mock.assert_called_once_with(FAKE_DB, FAKE_USER_ID, include=None, limit=None)

    def test_passes_include_param(self, client):
        with patch("routes.stats.get_monthly_summary", return_value=MONTHLY_RESULT) as mock:
            client.get("/monthly?include=tracks")
        mock.assert_called_once_with(FAKE_DB, FAKE_USER_ID, include="tracks", limit=None)

    def test_passes_limit_param(self, client):
        with patch("routes.stats.get_monthly_summary", return_value=MONTHLY_RESULT) as mock:
            client.get("/monthly?limit=3")
        mock.assert_called_once_with(FAKE_DB, FAKE_USER_ID, include=None, limit=3)

    def test_returns_502_on_exception(self, client):
        with patch("routes.stats.get_monthly_summary", side_effect=Exception("db down")):
            r = client.get("/monthly")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"

    def test_returns_401_when_unauthenticated(self, unauthed_client):
        r = unauthed_client.get("/monthly")
        assert r.status_code == 401
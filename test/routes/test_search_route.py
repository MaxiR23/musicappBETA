# test/routes/test_search_routes.py
#
# Testeamos: routes/search.py
# GET /search → query param requerido, warm scheduling, 502 en error
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from routes.search import router

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)

class TestSearchMusic:
    def _result(self):
        return {"query": "radiohead", "artist": {"name": "Radiohead"}, "artist_songs": [{"video_id": "v1"}]}

    def test_returns_200_with_result(self, client):
        with patch("routes.search.search", return_value=self._result()), \
             patch("routes.search.get_warm_ids", return_value=["v1"]), \
             patch("routes.search.schedule_warm"):
            r = client.get("/search?q=radiohead")
        assert r.status_code == 200
        assert r.json()["query"] == "radiohead"

    def test_missing_q_returns_422(self, client):
        r = client.get("/search")
        assert r.status_code == 422

    def test_passes_query_to_search_service(self, client):
        with patch("routes.search.search", return_value=self._result()) as mock_search, \
             patch("routes.search.get_warm_ids", return_value=[]), \
             patch("routes.search.schedule_warm"):
            client.get("/search?q=radiohead")
        mock_search.assert_called_once_with("radiohead")

    def test_schedules_warm_with_extracted_ids(self, client):
        with patch("routes.search.search", return_value=self._result()), \
             patch("routes.search.get_warm_ids", return_value=["v1", "v2"]), \
             patch("routes.search.schedule_warm") as mock_warm:
            client.get("/search?q=radiohead")
        mock_warm.assert_called_once_with(["v1", "v2"])

    def test_warm_uses_result_from_search(self, client):
        result = self._result()
        with patch("routes.search.search", return_value=result), \
             patch("routes.search.get_warm_ids") as mock_ids, \
             patch("routes.search.schedule_warm"):
            client.get("/search?q=radiohead")
        mock_ids.assert_called_once_with(result)

    def test_returns_502_on_exception(self, client):
        with patch("routes.search.search", side_effect=Exception("network error")):
            r = client.get("/search?q=radiohead")
        assert r.status_code == 502
        assert r.json()["error"] == "service_unavailable"
        assert r.json()["ok"] is False
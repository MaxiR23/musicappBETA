# test/routes/test_audio_routes.py
#
# Testeamos: routes/audio.py
# Contrato HTTP: status code, shape del response, lógica de redir.
#
# _has_ip_param              → detecta parámetro ip en URL
# _extract_and_limit_ids     → limpia y limita lista de ids
# GET  /play                 → redir=0 (json), redir=1 (redirect), redir=2 (stream)
# POST /prefetch             → warm condicional
# POST /warm                 → warm con limit custom
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routes.audio import router, _has_ip_param, _extract_and_limit_ids

# ════════════════════════════════════════════════════════
# APP DE TEST
# ════════════════════════════════════════════════════════
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, follow_redirects=False)

# ════════════════════════════════════════════════════════
# _has_ip_param
# ════════════════════════════════════════════════════════
class TestHasIpParam:
    def test_returns_true_when_ip_present(self):
        assert _has_ip_param("https://example.com/audio?ip=1.2.3.4&other=x") is True

    def test_returns_false_when_no_ip(self):
        assert _has_ip_param("https://example.com/audio?expire=9999") is False

    def test_returns_false_on_empty_url(self):
        assert _has_ip_param("") is False

    def test_returns_false_when_ip_value_is_empty(self):
        assert _has_ip_param("https://example.com/audio?ip=") is False

    def test_returns_true_with_ip_among_other_params(self):
        assert _has_ip_param("https://example.com/audio?expire=999&ip=8.8.8.8&mime=audio/webm") is True

# ════════════════════════════════════════════════════════
# _extract_and_limit_ids
# ════════════════════════════════════════════════════════
class TestExtractAndLimitIds:
    def test_strips_whitespace(self):
        assert _extract_and_limit_ids(["  v1  ", "v2"], 10) == ["v1", "v2"]

    def test_filters_falsy_values(self):
        assert _extract_and_limit_ids([None, "", "v1", 0], 10) == ["v1"]

    def test_respects_limit(self):
        ids = [f"v{i}" for i in range(20)]
        assert len(_extract_and_limit_ids(ids, 5)) == 5

    def test_converts_to_string(self):
        result = _extract_and_limit_ids([123, 456], 10)
        assert result == ["123", "456"]

    def test_empty_list_returns_empty(self):
        assert _extract_and_limit_ids([], 10) == []


# ════════════════════════════════════════════════════════
# GET /play
# ════════════════════════════════════════════════════════
class TestPlaySong:
    def _audio_data(self, url="https://audio.example.com/track.webm"):
        return {"direct_url": url}

    def test_redir_0_returns_json_with_url(self, client):
        with patch("routes.audio.get_audio_info", return_value=self._audio_data()):
            r = client.get("/play?id=vid1&redir=0")
        assert r.status_code == 200
        assert r.json()["url"] == "https://audio.example.com/track.webm"

    def test_redir_1_returns_307_redirect(self, client):
        url = "https://audio.example.com/track.webm"
        with patch("routes.audio.get_audio_info", return_value=self._audio_data(url)):
            r = client.get("/play?id=vid1&redir=1")
        assert r.status_code == 307
        assert r.headers["location"] == url

    def test_redir_1_falls_back_to_stream_when_ip_param(self, client):
        # URL con ?ip= → redir=1 se fuerza a redir=2 (stream)
        url = "https://audio.example.com/track.webm?ip=1.2.3.4"
        mock_stream = MagicMock()
        mock_stream.status_code = 200
        with patch("routes.audio.get_audio_info", return_value=self._audio_data(url)), \
             patch("routes.audio.stream_from_url", return_value=mock_stream):
            r = client.get("/play?id=vid1&redir=1")
        # No debe ser 307
        assert r.status_code != 307

    def test_redir_2_calls_stream(self, client):
        mock_stream = MagicMock()
        mock_stream.status_code = 200
        with patch("routes.audio.get_audio_info", return_value=self._audio_data()), \
             patch("routes.audio.stream_from_url", return_value=mock_stream) as mock_s:
            client.get("/play?id=vid1&redir=2")
        mock_s.assert_called_once()

    def test_default_redir_is_2(self, client):
        mock_stream = MagicMock()
        mock_stream.status_code = 200
        with patch("routes.audio.get_audio_info", return_value=self._audio_data()), \
             patch("routes.audio.stream_from_url", return_value=mock_stream) as mock_s:
            client.get("/play?id=vid1")
        mock_s.assert_called_once()

    def test_missing_id_returns_422(self, client):
        r = client.get("/play")
        assert r.status_code == 422

    def test_returns_502_on_exception(self, client):
        with patch("routes.audio.get_audio_info", side_effect=Exception("network error")):
            r = client.get("/play?id=vid1&redir=0")
        assert r.status_code == 502
        assert r.json()["error"] == "no_stream"
        assert r.json()["id"] == "vid1"

    def test_502_includes_detail(self, client):
        with patch("routes.audio.get_audio_info", side_effect=Exception("timeout")):
            r = client.get("/play?id=vid1&redir=0")
        assert "detail" in r.json()

    def test_passes_range_header_to_stream(self, client):
        mock_stream = MagicMock()
        mock_stream.status_code = 206
        with patch("routes.audio.get_audio_info", return_value=self._audio_data()), \
             patch("routes.audio.stream_from_url", return_value=mock_stream) as mock_s:
            client.get("/play?id=vid1&redir=2", headers={"Range": "bytes=0-1023"})
        assert mock_s.call_args[0][1] == "bytes=0-1023"


# ════════════════════════════════════════════════════════
# POST /prefetch
# ════════════════════════════════════════════════════════
class TestPrefetch:
    def test_returns_ok_false_scheduled_when_warm_disabled(self, client):
        with patch("routes.audio.WARM_ENABLED", False):
            r = client.post("/prefetch", json={"ids": ["v1", "v2"]})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "scheduled": 0}

    def test_schedules_ids_when_warm_enabled(self, client):
        with patch("routes.audio.WARM_ENABLED", True), \
             patch("routes.audio.schedule_warm") as mock_warm, \
             patch("routes.audio.get_warm_burst", return_value=20):
            r = client.post("/prefetch", json={"ids": ["v1", "v2"]})
        assert r.status_code == 200
        mock_warm.assert_called_once_with(["v1", "v2"])

    def test_scheduled_capped_by_warm_burst(self, client):
        ids = [f"v{i}" for i in range(10)]
        with patch("routes.audio.WARM_ENABLED", True), \
             patch("routes.audio.schedule_warm"), \
             patch("routes.audio.get_warm_burst", return_value=3):
            r = client.post("/prefetch", json={"ids": ids})
        assert r.json()["scheduled"] == 3

    def test_limits_ids_to_60(self, client):
        ids = [f"v{i}" for i in range(100)]
        with patch("routes.audio.WARM_ENABLED", True), \
             patch("routes.audio.schedule_warm") as mock_warm, \
             patch("routes.audio.get_warm_burst", return_value=100):
            client.post("/prefetch", json={"ids": ids})
        assert len(mock_warm.call_args[0][0]) == 60

    def test_empty_ids_schedules_nothing(self, client):
        with patch("routes.audio.WARM_ENABLED", True), \
             patch("routes.audio.schedule_warm") as mock_warm, \
             patch("routes.audio.get_warm_burst", return_value=20):
            r = client.post("/prefetch", json={"ids": []})
        mock_warm.assert_called_once_with([])
        assert r.json()["scheduled"] == 0

# ════════════════════════════════════════════════════════
# POST /warm
# ════════════════════════════════════════════════════════
class TestWarm:
    def test_returns_ok_false_scheduled_when_warm_disabled(self, client):
        with patch("routes.audio.WARM_ENABLED", False):
            r = client.post("/warm", json={"ids": ["v1"]})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "scheduled": 0}

    def test_schedules_ids_when_warm_enabled(self, client):
        with patch("routes.audio.WARM_ENABLED", True), \
             patch("routes.audio.schedule_warm") as mock_warm, \
             patch("routes.audio.get_warm_burst", return_value=20):
            r = client.post("/warm", json={"ids": ["v1", "v2"]})
        mock_warm.assert_called_once_with(["v1", "v2"])
        assert r.json()["scheduled"] == 2

    def test_uses_custom_limit(self, client):
        ids = [f"v{i}" for i in range(10)]
        with patch("routes.audio.WARM_ENABLED", True), \
             patch("routes.audio.schedule_warm") as mock_warm, \
             patch("routes.audio.get_warm_burst", return_value=20):
            client.post("/warm", json={"ids": ids, "limit": 3})
        assert len(mock_warm.call_args[0][0]) == 3

    def test_uses_warm_burst_as_default_limit(self, client):
        ids = [f"v{i}" for i in range(30)]
        with patch("routes.audio.WARM_ENABLED", True), \
             patch("routes.audio.schedule_warm") as mock_warm, \
             patch("routes.audio.get_warm_burst", return_value=5):
            client.post("/warm", json={"ids": ids})
        assert len(mock_warm.call_args[0][0]) == 5

    def test_scheduled_reflects_actual_ids_sent(self, client):
        with patch("routes.audio.WARM_ENABLED", True), \
             patch("routes.audio.schedule_warm"), \
             patch("routes.audio.get_warm_burst", return_value=20):
            r = client.post("/warm", json={"ids": ["v1", "v2", "v3"]})
        assert r.json()["scheduled"] == 3
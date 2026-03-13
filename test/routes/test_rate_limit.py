# test/routes/test_rate_limit.py
#
# Testeamos: rate limiting global (slowapi) configurado en app.py
# Contrato: después de 200 requests/minuto por IP → 429 Too Many Requests
#
# ADVERTENCIA: no correr junto a la suite normal en desarrollo.
# Puede bloquear 127.0.0.1 por un minuto completo.
# Correr aislado: pytest test/routes/test_rate_limit.py
#
# SEE: https://slowapi.readthedocs.io
# SEE: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429
#

# run with: pytest test/routes/test_rate_limit.py

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app import app
from core.dependencies import get_db, get_current_user_id

# ════════════════════════════════════════════════════════
# APP DE TEST
# ════════════════════════════════════════════════════════
@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[get_current_user_id] = lambda: "user-test"
    yield TestClient(app)
    app.dependency_overrides.clear()

# ════════════════════════════════════════════════════════
# RATE LIMIT GLOBAL
# ════════════════════════════════════════════════════════
class TestRateLimit:
    def test_returns_429_after_200_requests(self, client):
        """Después de 200 requests en un minuto, el siguiente debe devolver 429."""
        with patch("routes.activity.get_recents", return_value=[]):
            for _ in range(200):
                r = client.get("/api/music/me/recent")
            r = client.get("/api/music/me/recent")

        assert r.status_code == 429

    def test_response_below_limit_is_200(self, client):
        """Dentro del límite, los requests deben ser exitosos."""
        with patch("routes.activity.get_recents", return_value=[]):
            r = client.get("/api/music/me/recent")
        assert r.status_code == 200
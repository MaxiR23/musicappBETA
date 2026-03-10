import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    # evito que el lifespan inicialice clientes pesados (yt_dlp, ytmusicapi, InnerTube)
    with patch("shared.clients._ytm"), \
         patch("shared.clients._ydl_global"), \
         patch("shared.clients._ytmusic_client"):
        from app import app
        with TestClient(app) as c:
            yield c
# test/routes/test_feed_routes.py
#
# Testeamos: routes/feed.py
# Contrato HTTP: status code, shape del response, cache hit/miss.
#
# _build_recommendations_result → mapea rows a resultado
# GET /cache/versions           → versiones de caché
# GET /most-played              → feed albums + tracks
# GET /db/new-releases          → feed new releases
# GET /db/new-singles           → feed singles
# GET /db/seed-tracks           → feed seed tracks
# GET /recommendations/me       → recomendaciones por bearer
# GET /recommendations          → recomendaciones por user_id
#

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from routes.feed import router, _build_recommendations_result
from core.dependencies import get_db, get_current_user_id

# ════════════════════════════════════════════════════════
# APP DE TEST
# ════════════════════════════════════════════════════════
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: MagicMock()
    app.dependency_overrides[get_current_user_id] = lambda: "user-test"
    return TestClient(app)

# ════════════════════════════════════════════════════════
# _build_recommendations_result
# ════════════════════════════════════════════════════════
class TestBuildRecommendationsResult:
    def test_separates_artists_and_albums(self):
        rows = [
            {"item_type": "artist", "item_id": "ar1", "payload": {"name": "Radiohead"}},
            {"item_type": "album",  "item_id": "al1", "payload": {"title": "OK Computer"}},
        ]
        result = _build_recommendations_result(rows, "2024-W10")
        assert len(result["recommendations"]["artists"]) == 1
        assert len(result["recommendations"]["albums"]) == 1

    def test_artist_includes_similar_to_when_seed_present(self):
        rows = [{
            "item_type": "artist", "item_id": "ar1", "payload": {},
            "seed_id": "seed1", "seed_name": "Thom Yorke", "seed_thumb": "http://img.jpg",
        }]
        result = _build_recommendations_result(rows, "bucket")
        artist = result["recommendations"]["artists"][0]
        assert artist["similar_to"]["id"] == "seed1"
        assert artist["similar_to"]["name"] == "Thom Yorke"

    def test_artist_without_seed_has_no_similar_to(self):
        rows = [{"item_type": "artist", "item_id": "ar1", "payload": {}, "seed_id": None}]
        result = _build_recommendations_result(rows, "bucket")
        assert "similar_to" not in result["recommendations"]["artists"][0]

    def test_album_payload_spread_into_item(self):
        rows = [{"item_type": "album", "item_id": "al1", "payload": {"title": "Kid A", "year": 2000}}]
        result = _build_recommendations_result(rows, "bucket")
        album = result["recommendations"]["albums"][0]
        assert album["id"] == "al1"
        assert album["title"] == "Kid A"
        assert album["year"] == 2000

    def test_unknown_item_type_ignored(self):
        rows = [{"item_type": "playlist", "item_id": "pl1", "payload": {}}]
        result = _build_recommendations_result(rows, "bucket")
        assert result["recommendations"]["artists"] == []
        assert result["recommendations"]["albums"] == []

    def test_includes_bucket_and_ok(self):
        result = _build_recommendations_result([], "2024-W10")
        assert result["ok"] is True
        assert result["bucket"] == "2024-W10"

    def test_empty_rows_returns_empty_lists(self):
        result = _build_recommendations_result([], "bucket")
        assert result["recommendations"]["artists"] == []
        assert result["recommendations"]["albums"] == []

    def test_artists_capped_by_reco_limit(self):
        rows = [{"item_type": "artist", "item_id": f"ar{i}", "payload": {}, "seed_id": None} for i in range(50)]
        result = _build_recommendations_result(rows, "bucket")
        from routes.feed import _RECO_LIMIT_PER_TYPE
        assert len(result["recommendations"]["artists"]) <= _RECO_LIMIT_PER_TYPE

# ════════════════════════════════════════════════════════
# GET /cache/versions
# ════════════════════════════════════════════════════════
class TestGetCacheVersions:
    def test_returns_ok_and_versions(self, client):
        with patch("routes.feed.get_all_versions", return_value={"SEARCH": "v1", "ARTIST": "v2"}):
            r = client.get("/cache/versions")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert "versions" in r.json()

# ════════════════════════════════════════════════════════
# GET /most-played
# ════════════════════════════════════════════════════════
class TestGetMostPlayed:
    def test_returns_cached_when_available(self, client):
        cached = {"ok": True, "albums": [], "tracks": []}
        with patch("routes.feed.get_cached", return_value=cached):
            r = client.get("/most-played")
        assert r.status_code == 200
        assert r.json() == cached

    def test_fetches_from_db_on_cache_miss(self, client):
        albums = [{"id": "al1"}]
        tracks = [{"id": "t1"}]
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", side_effect=[albums, tracks]), \
             patch("routes.feed.set_cached"):
            r = client.get("/most-played")
        assert r.status_code == 200
        assert r.json()["albums"] == albums
        assert r.json()["tracks"] == tracks

    def test_caches_result(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", side_effect=[[{"id": "al1"}], [{"id": "t1"}]]), \
             patch("routes.feed.set_cached") as mock_set:
            client.get("/most-played")
        mock_set.assert_called_once()

    def test_returns_502_when_empty(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", side_effect=[[], []]):
            r = client.get("/most-played")
        assert r.status_code == 502
        assert r.json()["ok"] is False

    def test_returns_502_on_exception(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", side_effect=Exception("db error")):
            r = client.get("/most-played")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /db/new-releases
# ════════════════════════════════════════════════════════
class TestGetNewReleases:
    def test_returns_cached_when_available(self, client):
        cached = {"ok": True, "new_releases": [{"id": "al1"}]}
        with patch("routes.feed.get_cached", return_value=cached):
            r = client.get("/db/new-releases")
        assert r.status_code == 200
        assert r.json() == cached

    def test_fetches_from_db_on_cache_miss(self, client):
        albums = [{"id": "al1"}]
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", return_value=albums), \
             patch("routes.feed.set_cached"):
            r = client.get("/db/new-releases")
        assert r.status_code == 200
        assert r.json()["new_releases"] == albums

    def test_returns_502_when_empty(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", return_value=[]):
            r = client.get("/db/new-releases")
        assert r.status_code == 502

    def test_returns_502_on_exception(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", side_effect=Exception("fail")):
            r = client.get("/db/new-releases")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /db/new-singles
# ════════════════════════════════════════════════════════
class TestGetNewSingles:
    def test_returns_cached_when_available(self, client):
        cached = {"ok": True, "tracks": [{"id": "t1"}]}
        with patch("routes.feed.get_cached", return_value=cached):
            r = client.get("/db/new-singles")
        assert r.status_code == 200

    def test_fetches_from_db_on_cache_miss(self, client):
        tracks = [{"id": "t1"}]
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", return_value=tracks), \
             patch("routes.feed.set_cached"):
            r = client.get("/db/new-singles")
        assert r.json()["tracks"] == tracks

    def test_returns_502_when_empty(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", return_value=[]):
            r = client.get("/db/new-singles")
        assert r.status_code == 502

    def test_returns_502_on_exception(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", side_effect=Exception("fail")):
            r = client.get("/db/new-singles")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /db/seed-tracks
# ════════════════════════════════════════════════════════
class TestGetSeedTracks:
    def test_returns_cached_when_available(self, client):
        cached = {"ok": True, "tracks": [{"id": "t1"}]}
        with patch("routes.feed.get_cached", return_value=cached):
            r = client.get("/db/seed-tracks")
        assert r.status_code == 200

    def test_fetches_from_db_on_cache_miss(self, client):
        tracks = [{"id": "t1"}]
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", return_value=tracks), \
             patch("routes.feed.set_cached"):
            r = client.get("/db/seed-tracks")
        assert r.json()["tracks"] == tracks

    def test_returns_502_when_empty(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", return_value=[]):
            r = client.get("/db/seed-tracks")
        assert r.status_code == 502

    def test_returns_502_on_exception(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_feed", side_effect=Exception("fail")):
            r = client.get("/db/seed-tracks")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /recommendations/me
# ════════════════════════════════════════════════════════
class TestGetUserRecommendationsMe:
    def test_returns_cached_when_available(self, client):
        cached = {"ok": True, "bucket": "b1", "recommendations": {"artists": [], "albums": []}}
        with patch("routes.feed.get_cached", return_value=cached):
            r = client.get("/recommendations/me")
        assert r.status_code == 200
        assert r.json() == cached

    def test_fetches_rows_on_cache_miss(self, client):
        rows = [{"item_type": "artist", "item_id": "ar1", "payload": {}, "seed_id": None}]
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_user_recommendations", return_value=rows), \
             patch("routes.feed.generate_weekly_bucket", return_value="2024-W10"), \
             patch("routes.feed.set_cached"):
            r = client.get("/recommendations/me")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_uses_provided_bucket(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_user_recommendations", return_value=[]) as mock_list, \
             patch("routes.feed.set_cached"):
            client.get("/recommendations/me?bucket=custom-bucket")
        assert mock_list.call_args[1]["bucket"] == "custom-bucket"

    def test_uses_generated_bucket_when_none(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_user_recommendations", return_value=[]) as mock_list, \
             patch("routes.feed.generate_weekly_bucket", return_value="2024-W10"), \
             patch("routes.feed.set_cached"):
            client.get("/recommendations/me")
        assert mock_list.call_args[1]["bucket"] == "2024-W10"

    def test_caches_result(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_user_recommendations", return_value=[]), \
             patch("routes.feed.generate_weekly_bucket", return_value="b1"), \
             patch("routes.feed.set_cached") as mock_set:
            client.get("/recommendations/me")
        mock_set.assert_called_once()

    def test_returns_502_on_exception(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_user_recommendations", side_effect=Exception("fail")), \
             patch("routes.feed.generate_weekly_bucket", return_value="b1"):
            r = client.get("/recommendations/me")
        assert r.status_code == 502

# ════════════════════════════════════════════════════════
# GET /recommendations
# ════════════════════════════════════════════════════════
class TestGetUserRecommendationsDb:
    def test_requires_user_id_param(self, client):
        r = client.get("/recommendations")
        assert r.status_code == 422

    def test_returns_cached_when_available(self, client):
        cached = {"ok": True, "bucket": "b1", "recommendations": {"artists": [], "albums": []}}
        with patch("routes.feed.get_cached", return_value=cached):
            r = client.get("/recommendations?user_id=u1")
        assert r.status_code == 200

    def test_fetches_rows_on_cache_miss(self, client):
        rows = [{"item_type": "album", "item_id": "al1", "payload": {}}]
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_user_recommendations", return_value=rows), \
             patch("routes.feed.generate_weekly_bucket", return_value="b1"), \
             patch("routes.feed.set_cached"):
            r = client.get("/recommendations?user_id=u1")
        assert r.status_code == 200
        assert len(r.json()["recommendations"]["albums"]) == 1

    def test_uses_provided_bucket(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_user_recommendations", return_value=[]) as mock_list, \
             patch("routes.feed.set_cached"):
            client.get("/recommendations?user_id=u1&bucket=custom-bucket")
        assert mock_list.call_args[1]["bucket"] == "custom-bucket"

    def test_returns_502_on_exception(self, client):
        with patch("routes.feed.get_cached", return_value=None), \
             patch("routes.feed.list_user_recommendations", side_effect=Exception("fail")), \
             patch("routes.feed.generate_weekly_bucket", return_value="b1"):
            r = client.get("/recommendations?user_id=u1")
        assert r.status_code == 502
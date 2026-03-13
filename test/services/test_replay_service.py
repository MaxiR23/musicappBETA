# test/services/test_replay_service.py
#
# Testeamos: services/replay_service.py
# - get_replay_songs → cache hit: devuelve cached sin llamar al RPC
# - get_replay_songs → cache miss: llama al RPC con los parámetros correctos
# - get_replay_songs → cache miss: cachea el resultado
# - get_replay_songs → RPC vacío: devuelve lista vacía
#

import pytest
from unittest.mock import patch, MagicMock

from services.replay_service import get_replay_songs, REPLAY_MIN_PLAYS, REPLAY_LIMIT

class TestGetReplaySongs:
    def _mock_db(self, data=None):
        db = MagicMock()
        db.rpc.return_value.execute.return_value.data = data or []
        return db

    def test_returns_cached_when_available(self):
        cached = [{"track_id": "abc", "play_count": 5}]
        db = self._mock_db()
        with patch("services.replay_service.get_cached", return_value=cached):
            result = get_replay_songs(db=db, user_id="u1")
        assert result == cached
        db.rpc.assert_not_called()

    def test_calls_rpc_on_cache_miss(self):
        db = self._mock_db(data=[])
        with patch("services.replay_service.get_cached", return_value=None), \
             patch("services.replay_service.set_cached"):
            get_replay_songs(db=db, user_id="u1")
        db.rpc.assert_called_once_with("get_replay_songs", {
            "p_user_id":   "u1",
            "p_min_plays": REPLAY_MIN_PLAYS,
            "p_limit":     REPLAY_LIMIT,
        })

    def test_caches_result_on_cache_miss(self):
        songs = [{"track_id": "abc", "play_count": 5}]
        db = self._mock_db(data=songs)
        with patch("services.replay_service.get_cached", return_value=None), \
             patch("services.replay_service.set_cached") as mock_set:
            get_replay_songs(db=db, user_id="u1")
        mock_set.assert_called_once()

    def test_returns_rpc_data(self):
        songs = [{"track_id": "abc", "play_count": 5}]
        db = self._mock_db(data=songs)
        with patch("services.replay_service.get_cached", return_value=None), \
             patch("services.replay_service.set_cached"):
            result = get_replay_songs(db=db, user_id="u1")
        assert result == songs

    def test_returns_empty_list_when_rpc_returns_none(self):
        db = self._mock_db(data=None)
        with patch("services.replay_service.get_cached", return_value=None), \
             patch("services.replay_service.set_cached"):
            result = get_replay_songs(db=db, user_id="u1")
        assert result == []
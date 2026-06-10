from unittest.mock import MagicMock, patch

from services.station_service import get_station_tracks, get_user_stations


def test_get_user_stations_returns_error_when_seed_lookup_fails():
    with patch("services.station_service.get_seed_artists", side_effect=Exception("db down")):
        result = get_user_stations(MagicMock(), "user-1")

    assert result == {"ok": False, "reason": "error"}


def test_get_user_stations_returns_no_data_without_seeds():
    with patch("services.station_service.get_cached", return_value=None), \
         patch("services.station_service.get_seed_artists", return_value=[]):
        result = get_user_stations(MagicMock(), "user-1")

    assert result == {"ok": False, "reason": "no_stations_available"}


def test_get_user_stations_returns_error_when_all_artist_calls_fail():
    yt = MagicMock()
    yt.get_artist.side_effect = Exception("ytmusic down")

    with patch("services.station_service.get_cached", return_value=None), \
         patch("services.station_service.get_seed_artists", return_value=["artist-1"]), \
         patch("services.station_service._ytmusic_client", return_value=yt):
        result = get_user_stations(MagicMock(), "user-1")

    assert result == {"ok": False, "reason": "error"}


def test_get_station_tracks_returns_no_data_without_radio_id():
    yt = MagicMock()
    yt.get_artist.return_value = {"name": "Artist"}

    with patch("services.station_service._ytmusic_client", return_value=yt):
        result = get_station_tracks("artist-1")

    assert result == {"ok": False, "reason": "station_not_found"}


def test_get_station_tracks_returns_error_on_ytmusic_failure():
    yt = MagicMock()
    yt.get_artist.side_effect = Exception("ytmusic down")

    with patch("services.station_service._ytmusic_client", return_value=yt):
        result = get_station_tracks("artist-1")

    assert result == {"ok": False, "reason": "error"}
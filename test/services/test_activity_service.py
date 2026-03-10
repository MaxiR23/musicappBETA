# test/services/test_activity_service.py
#
# Testeamos: services/activity_service.py
# - _validate_entity_type   → validación de entity types permitidos
# - _ids_to_trim             → cálculo de ids a borrar por límite
# - _build_play_event        → construcción de payload de play
# - _build_recent_row        → construcción de payload de recent
# - log_play                 → INSERT en play_events
# - upsert_recent            → UPSERT en recent_activity + trim
# - get_recents              → lectura de recent_activity
# - _trim_recents            → borrado de recents viejos
#
import pytest
from services.activity_service import (
    MAX_RECENTS,
    _validate_entity_type,
    _ids_to_trim,
    _build_play_event,
    _build_recent_row,
    log_play,
    upsert_recent,
    get_recents,
    _trim_recents,
)

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════
class TestValidateEntityType:
    def test_valid_artist(self):
        assert _validate_entity_type("artist") is None

    def test_valid_album(self):
        assert _validate_entity_type("album") is None

    def test_valid_playlist(self):
        assert _validate_entity_type("playlist") is None

    def test_invalid_returns_message(self):
        assert _validate_entity_type("track") is not None

    def test_invalid_empty_string(self):
        assert _validate_entity_type("") is not None

    def test_invalid_case_sensitive(self):
        assert _validate_entity_type("Artist") is not None

class TestIdsToTrim:
    def test_under_limit_returns_empty(self):
        rows = [{"id": str(i)} for i in range(MAX_RECENTS - 1)]
        assert _ids_to_trim(rows) == []

    def test_at_limit_returns_empty(self):
        rows = [{"id": str(i)} for i in range(MAX_RECENTS)]
        assert _ids_to_trim(rows) == []

    def test_over_limit_returns_excess_ids(self):
        rows = [{"id": str(i)} for i in range(MAX_RECENTS + 3)]
        ids = _ids_to_trim(rows)
        assert len(ids) == 3
        assert ids == [str(MAX_RECENTS), str(MAX_RECENTS + 1), str(MAX_RECENTS + 2)]

    def test_custom_max(self):
        rows = [{"id": str(i)} for i in range(5)]
        ids = _ids_to_trim(rows, max_recents=3)
        assert ids == ["3", "4"]

    def test_empty_rows(self):
        assert _ids_to_trim([]) == []

class TestBuildPlayEvent:
    def test_builds_correctly(self):
        result = _build_play_event("user1", "track1", {"album_id": "a1"})
        assert result == {
            "user_id": "user1",
            "track_id": "track1",
            "metadata": {"album_id": "a1"},
        }

    def test_none_metadata_defaults_to_empty_dict(self):
        result = _build_play_event("user1", "track1", None)
        assert result["metadata"] == {}

class TestBuildRecentRow:
    def test_builds_correctly(self):
        result = _build_recent_row("u1", "artist", "a1", {"display_name": "Tame Impala"}, "2024-01-01T00:00:00")
        assert result["user_id"] == "u1"
        assert result["entity_type"] == "artist"
        assert result["entity_id"] == "a1"
        assert result["metadata"]["display_name"] == "Tame Impala"
        assert result["played_at"] == "2024-01-01T00:00:00"

    def test_none_metadata_defaults_to_empty_dict(self):
        result = _build_recent_row("u1", "artist", "a1", None, "2024-01-01T00:00:00")
        assert result["metadata"] == {}

# ════════════════════════════════════════════════════════
# IO (con MockDB)
# ════════════════════════════════════════════════════════
class TestLogPlay:
    def test_success_returns_ok(self, mock_db):
        mock_db.set_table_data("play_events", [{"id": "event-123"}])
        result = log_play(mock_db, user_id="u1", track_id="t1")
        assert result["ok"] is True
        assert result["id"] == "event-123"

    def test_passes_correct_data_to_db(self, mock_db):
        mock_db.set_table_data("play_events", [{"id": "x"}])
        log_play(mock_db, user_id="u1", track_id="t1", metadata={"artist_id": "a1"})
        calls = mock_db.get_builder("play_events").calls
        insert_call = next(c for c in calls if c["method"] == "insert")
        assert insert_call["args"]["user_id"] == "u1"
        assert insert_call["args"]["track_id"] == "t1"
        assert insert_call["args"]["metadata"]["artist_id"] == "a1"

    def test_db_error_returns_not_ok(self, mock_db):
        mock_db.set_table_data("play_events", None)
        # Forzamos excepción sobreescribiendo execute
        mock_db.get_builder("play_events")._return_data = None
        original_execute = mock_db.get_builder("play_events").execute
        mock_db.get_builder("play_events").execute = lambda: (_ for _ in ()).throw(Exception("db down"))
        result = log_play(mock_db, user_id="u1", track_id="t1")
        assert result["ok"] is False
        assert "error" in result

class TestUpsertRecent:
    def test_success_artist(self, mock_db):
        mock_db.set_table_data("recent_activity", [{"id": "r-1"}])
        result = upsert_recent(mock_db, user_id="u1", entity_type="artist", entity_id="a1")
        assert result["ok"] is True
        assert result["id"] == "r-1"

    def test_success_album(self, mock_db):
        mock_db.set_table_data("recent_activity", [{"id": "r-2"}])
        result = upsert_recent(mock_db, user_id="u1", entity_type="album", entity_id="al1")
        assert result["ok"] is True

    def test_success_playlist(self, mock_db):
        mock_db.set_table_data("recent_activity", [{"id": "r-3"}])
        result = upsert_recent(mock_db, user_id="u1", entity_type="playlist", entity_id="p1")
        assert result["ok"] is True

    def test_invalid_entity_type_returns_error(self, mock_db):
        result = upsert_recent(mock_db, user_id="u1", entity_type="track", entity_id="t1")
        assert result["ok"] is False
        assert "invalid entity_type" in result["error"]

    def test_passes_on_conflict_key(self, mock_db):
        mock_db.set_table_data("recent_activity", [{"id": "r-1"}])
        upsert_recent(mock_db, user_id="u1", entity_type="artist", entity_id="a1")
        calls = mock_db.get_builder("recent_activity").calls
        upsert_call = next(c for c in calls if c["method"] == "upsert")
        assert upsert_call["on_conflict"] == "user_id,entity_type,entity_id"

    def test_metadata_passed_correctly(self, mock_db):
        mock_db.set_table_data("recent_activity", [{"id": "r-1"}])
        upsert_recent(mock_db, user_id="u1", entity_type="artist", entity_id="a1", metadata={"display_name": "Radiohead"})
        calls = mock_db.get_builder("recent_activity").calls
        upsert_call = next(c for c in calls if c["method"] == "upsert")
        assert upsert_call["args"]["metadata"]["display_name"] == "Radiohead"

class TestGetRecents:
    def test_returns_data(self, mock_db):
        rows = [
            {"entity_type": "artist", "entity_id": "a1", "metadata": {}, "played_at": "2024-01-02"},
            {"entity_type": "album", "entity_id": "al1", "metadata": {}, "played_at": "2024-01-01"},
        ]
        mock_db.set_table_data("recent_activity", rows)
        result = get_recents(mock_db, user_id="u1")
        assert len(result) == 2
        assert result[0]["entity_type"] == "artist"

    def test_empty_returns_empty_list(self, mock_db):
        mock_db.set_table_data("recent_activity", [])
        result = get_recents(mock_db, user_id="u1")
        assert result == []

    def test_limit_capped_at_max_recents(self, mock_db):
        mock_db.set_table_data("recent_activity", [])
        get_recents(mock_db, user_id="u1", limit=9999)
        calls = mock_db.get_builder("recent_activity").calls
        limit_call = next(c for c in calls if c["method"] == "limit")
        assert limit_call["count"] <= MAX_RECENTS

    def test_db_error_returns_empty_list(self, mock_db):
        mock_db.get_builder("recent_activity").execute = lambda: (_ for _ in ()).throw(Exception("db down"))
        result = get_recents(mock_db, user_id="u1")
        assert result == []

class TestTrimRecents:
    def test_trims_when_over_limit(self, mock_db):
        rows = [{"id": str(i), "played_at": f"2024-01-{i:02d}"} for i in range(1, MAX_RECENTS + 4)]
        mock_db.set_table_data("recent_activity", rows)
        _trim_recents(mock_db, "u1")
        calls = mock_db.get_builder("recent_activity").calls
        assert any(c["method"] == "delete" for c in calls)
        in_call = next(c for c in calls if c["method"] == "in_")
        assert len(in_call["values"]) == 3

    def test_no_trim_when_under_limit(self, mock_db):
        rows = [{"id": str(i), "played_at": f"2024-01-{i:02d}"} for i in range(1, MAX_RECENTS - 1)]
        mock_db.set_table_data("recent_activity", rows)
        _trim_recents(mock_db, "u1")
        calls = mock_db.get_builder("recent_activity").calls
        assert not any(c["method"] == "delete" for c in calls)
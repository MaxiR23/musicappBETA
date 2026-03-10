# test/services/test_auth_utils.py
#
# Testeamos: utils/auth_utils.py //TODO: SHOULD MOVE TO UTILS
# - extract_bearer_token      → extrae token de Authorization header
# - get_user_id_from_state    → extrae user_id de request.state.user
# - get_user_id               → orquesta: state → JWT fallback
#

import pytest
from unittest.mock import patch, MagicMock
from services.auth_utils import (
    extract_bearer_token,
    get_user_id_from_state,
    get_user_id,
)

# ════════════════════════════════════════════════════════
# FUNCIONES PURAS
# ════════════════════════════════════════════════════════

class TestExtractBearerToken:
    def test_extracts_token_from_valid_header(self):
        assert extract_bearer_token("Bearer abc123") == "abc123"

    def test_case_insensitive_bearer(self):
        assert extract_bearer_token("bearer abc123") == "abc123"
        assert extract_bearer_token("BEARER abc123") == "abc123"

    def test_strips_whitespace_from_token(self):
        assert extract_bearer_token("Bearer   abc123  ") == "abc123"

    def test_returns_empty_when_no_bearer_prefix(self):
        assert extract_bearer_token("Token abc123") == ""

    def test_returns_empty_on_empty_string(self):
        assert extract_bearer_token("") == ""

    def test_returns_empty_on_bearer_only(self):
        # "bearer " sin token → split da ["bearer", ""] → strip → ""
        assert extract_bearer_token("Bearer ") == ""

    def test_token_with_dots_preserved(self):
        jwt = "eyJ0.eyJzdWIiOiJ1c2VyMSJ9.signature"
        assert extract_bearer_token(f"Bearer {jwt}") == jwt

    def test_token_with_internal_spaces_returns_first_part(self):
        # solo splitea en el primer espacio
        assert extract_bearer_token("Bearer tok en") == "tok en"


class TestGetUserIdFromState:
    def test_returns_id_from_valid_user_dict(self):
        assert get_user_id_from_state({"id": "user-1"}) == "user-1"

    def test_returns_none_when_user_is_none(self):
        assert get_user_id_from_state(None) is None

    def test_returns_none_when_user_is_not_dict(self):
        assert get_user_id_from_state("string") is None
        assert get_user_id_from_state(42) is None
        assert get_user_id_from_state([]) is None

    def test_returns_none_when_id_missing(self):
        assert get_user_id_from_state({"name": "John"}) is None

    def test_returns_none_when_id_is_none(self):
        assert get_user_id_from_state({"id": None}) is None

    def test_returns_none_when_id_is_empty_string(self):
        # "" es falsy → get("id") retorna "" → not truthy → None
        assert get_user_id_from_state({"id": ""}) is None

    def test_returns_none_on_empty_dict(self):
        assert get_user_id_from_state({}) is None


# ════════════════════════════════════════════════════════
# IO
# ════════════════════════════════════════════════════════

def _make_request(state_user=None, auth_header=None):
    request = MagicMock()
    request.state.user = state_user
    request.headers.get = lambda key, default="": auth_header if key == "Authorization" else default
    return request


class TestGetUserId:
    def test_returns_user_id_from_state(self):
        request = _make_request(state_user={"id": "user-state"})
        assert get_user_id(request) == "user-state"

    def test_falls_back_to_jwt_when_no_state(self):
        request = _make_request(state_user=None, auth_header="Bearer mytoken")
        with patch("services.auth_utils.decode_jwt", return_value={"sub": "user-jwt"}):
            assert get_user_id(request) == "user-jwt"

    def test_state_takes_priority_over_jwt(self):
        request = _make_request(state_user={"id": "user-state"}, auth_header="Bearer mytoken")
        with patch("services.auth_utils.decode_jwt") as mock_decode:
            result = get_user_id(request)
        assert result == "user-state"
        mock_decode.assert_not_called()

    def test_returns_none_when_no_state_and_no_header(self):
        request = _make_request(state_user=None, auth_header="")
        assert get_user_id(request) == None

    def test_returns_none_when_jwt_has_no_sub(self):
        request = _make_request(state_user=None, auth_header="Bearer mytoken")
        with patch("services.auth_utils.decode_jwt", return_value={"name": "John"}):
            assert get_user_id(request) is None

    def test_returns_none_when_decode_jwt_returns_none(self):
        request = _make_request(state_user=None, auth_header="Bearer badtoken")
        with patch("services.auth_utils.decode_jwt", return_value=None):
            assert get_user_id(request) is None

    def test_returns_none_when_token_invalid_format(self):
        request = _make_request(state_user=None, auth_header="NotBearer token")
        with patch("services.auth_utils.decode_jwt") as mock_decode:
            result = get_user_id(request)
        assert result is None
        mock_decode.assert_not_called()

    def test_state_user_without_id_falls_through_to_jwt(self):
        request = _make_request(state_user={"name": "John"}, auth_header="Bearer mytoken")
        with patch("services.auth_utils.decode_jwt", return_value={"sub": "user-jwt"}):
            assert get_user_id(request) == "user-jwt"
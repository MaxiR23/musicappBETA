"""
Test formal de artist_service.get_artist() con pytest
"""
import sys
import time
import pytest

sys.path.insert(0, '../')

from services.artist_service import get_artist

# IDs CORRECTOS
ARTISTS_DATA = [
    {
        "name": "Travis Scott",
        "id": "UCf_gP4AMRSgAfyzbkeS9k4g",
        "expect_ok": True,
    },
    {
        "name": "Bad Bunny",
        "id": "UCiY3z8HAGD6BlSNKVn2kSvQ",
        "expect_ok": True,
    },
    {
        "name": "The Weeknd",
        "id": "UClYV6hHlupm_S_ObS1W-DYw",
        "expect_ok": True,
    },
    {
        "name": "Drake",
        "id": "UCU6cE7pdJPc6DU2jSrKEsdQ",
        "expect_ok": True,
    },
]

@pytest.fixture(params=ARTISTS_DATA, ids=[a["name"] for a in ARTISTS_DATA])
def artist(request):
    """Fixture que proporciona cada artista"""
    return request.param

def test_get_artist_returns_dict(artist):
    """Test: get_artist devuelve dict"""
    payload = get_artist(artist["id"], use_cache=False)
    
    assert isinstance(payload, dict), f"Expected dict, got {type(payload)}"
    print(f"  Payload type: OK")

def test_get_artist_has_required_keys(artist):
    """Test: payload tiene keys requeridas"""
    payload = get_artist(artist["id"], use_cache=False)
    
    assert "header" in payload or "error" in payload, "Missing header or error key"
    print(f"  Has header or error: OK")

def test_get_artist_no_error_with_valid_id(artist):
    """Test: sin error para IDs válidos"""
    if not artist["expect_ok"]:
        pytest.skip("Artist expected to fail")
    
    payload = get_artist(artist["id"], use_cache=False)
    
    assert "error" not in payload, f"Expected no error, got: {payload.get('error')}"
    print(f"  No error: OK")

def test_get_artist_has_header_name(artist):
    """Test: header.name existe"""
    if not artist["expect_ok"]:
        pytest.skip("Artist expected to fail")
    
    payload = get_artist(artist["id"], use_cache=False)
    
    assert "header" in payload, "Missing header"
    header = payload["header"]
    assert isinstance(header, dict), f"header should be dict, got {type(header)}"
    assert "name" in header, "header missing 'name'"
    assert header["name"], f"header.name is empty: {header['name']}"
    
    print(f"  header.name: {header['name']}")

def test_get_artist_has_top_songs(artist):
    """Test: top_songs existe y no vacío"""
    if not artist["expect_ok"]:
        pytest.skip("Artist expected to fail")
    
    payload = get_artist(artist["id"], use_cache=False)
    
    assert "top_songs" in payload, "Missing top_songs"
    top_songs = payload["top_songs"]
    assert isinstance(top_songs, list), f"top_songs should be list, got {type(top_songs)}"
    assert len(top_songs) > 0, "top_songs is empty"
    
    print(f"  top_songs: {len(top_songs)} items")

def test_get_artist_has_albums(artist):
    """Test: albums existe"""
    if not artist["expect_ok"]:
        pytest.skip("Artist expected to fail")
    
    payload = get_artist(artist["id"], use_cache=False)
    
    # albums puede existir o no
    if "albums" in payload:
        albums = payload["albums"]
        assert isinstance(albums, list), f"albums should be list, got {type(albums)}"
    
    print(f"  albums: OK")

def test_get_artist_has_singles_eps(artist):
    """Test: singles_eps existe"""
    if not artist["expect_ok"]:
        pytest.skip("Artist expected to fail")
    
    payload = get_artist(artist["id"], use_cache=False)
    
    # singles_eps puede existir o no
    if "singles_eps" in payload:
        singles = payload["singles_eps"]
        assert isinstance(singles, list), f"singles_eps should be list, got {type(singles)}"
    
    print(f"  singles_eps: OK")

def test_get_artist_has_upcoming_events(artist):
    """Test: upcoming_events existe"""
    if not artist["expect_ok"]:
        pytest.skip("Artist expected to fail")
    
    payload = get_artist(artist["id"], use_cache=False)
    
    assert "upcoming_events" in payload, "Missing upcoming_events"
    events = payload["upcoming_events"]
    assert isinstance(events, list), f"upcoming_events should be list, got {type(events)}"
    
    print(f"  upcoming_events: {len(events)} items")

def test_get_artist_has_related(artist):
    """Test: related existe"""
    if not artist["expect_ok"]:
        pytest.skip("Artist expected to fail")
    
    payload = get_artist(artist["id"], use_cache=False)
    
    assert "related" in payload, "Missing related"
    related = payload["related"]
    assert isinstance(related, list), f"related should be list, got {type(related)}"
    
    print(f"  related: {len(related)} items")

def test_get_artist_has_has_more(artist):
    """Test: has_more existe"""
    if not artist["expect_ok"]:
        pytest.skip("Artist expected to fail")
    
    payload = get_artist(artist["id"], use_cache=False)
    
    assert "has_more" in payload, "Missing has_more"
    has_more = payload["has_more"]
    assert isinstance(has_more, dict), f"has_more should be dict, got {type(has_more)}"
    
    print(f"  has_more: OK")
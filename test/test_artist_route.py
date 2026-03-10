"""
Test de la RUTA /music/artist (no solo la función)
"""
import sys
sys.path.insert(0, '../')

import pytest
from fastapi.testclient import TestClient
from routes.artists import router  # Importa el router

# Crear cliente de test
client = TestClient(router)

# IDs que fallan
failing_ids = [
    'UC7d6hou24HcG5sA2lwTgV0A',  # Duran Duran
    'UCLabAHLHMy2MdTWaZATUmQQ',   # Milo J
]

# IDs que sabemos funcionan
working_ids = [
    'UCf_gP4AMRSgAfyzbkeS9k4g',  # Travis Scott
    'UCiY3z8HAGD6BlSNKVn2kSvQ',  # Bad Bunny
]

@pytest.mark.parametrize("artist_id", failing_ids, ids=failing_ids)
def test_route_get_artist_failing_ids(artist_id):
    """Test: ruta /music/artist con IDs que fallan"""
    print(f"\n  Testing GET /music/artist?id={artist_id}")
    
    response = client.get(f"/artist?id={artist_id}")
    
    print(f"  Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"  Response: OK - {data.get('header', {}).get('name')}")
        assert "header" in data
        assert data.get("header", {}).get("name")
    elif response.status_code == 502:
        data = response.json()
        print(f"  Response: 502 - {data.get('error')}")
        assert "error" in data
    else:
        print(f"  Response: {response.status_code} - {response.text}")
        assert False, f"Unexpected status {response.status_code}"

@pytest.mark.parametrize("artist_id", working_ids, ids=working_ids)
def test_route_get_artist_working_ids(artist_id):
    """Test: ruta /music/artist con IDs que funcionan"""
    print(f"\n  Testing GET /music/artist?id={artist_id}")
    
    response = client.get(f"/artist?id={artist_id}")
    
    print(f"  Status: {response.status_code}")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    data = response.json()
    print(f"  Response: OK - {data.get('header', {}).get('name')}")
    
    assert "header" in data
    assert data.get("header", {}).get("name")
    assert "top_songs" in data
    assert len(data.get("top_songs", [])) > 0

@pytest.mark.parametrize("artist_id", failing_ids, ids=failing_ids)
def test_route_get_artist_path_failing_ids(artist_id):
    """Test: ruta /music/artist/{id} con PATH parameter"""
    print(f"\n  Testing GET /artist/{artist_id}")
    
    response = client.get(f"/artist/{artist_id}")
    
    print(f"  Status: {response.status_code}")
    print(f"  Response: {response.json()}")
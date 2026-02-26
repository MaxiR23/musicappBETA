# services/music_client.py
"""
Abstrae la fuente de datos.
Única capa que conoce los clients internos.
El resto del código importa desde acá, nunca desde shared/clients.
"""
from shared.clients import _ytm, _ytmusic_client

def browse(browse_id: str) -> dict:
    return _ytm().browse(browse_id)

def get_artist(artist_id: str) -> dict:
    return _ytmusic_client().get_artist(artist_id)

def get_artist_albums(browse_id: str, params: str = None) -> list:
    return _ytmusic_client().get_artist_albums(browse_id, params)

def get_album(album_id: str) -> dict:
    return _ytmusic_client().get_album(album_id)
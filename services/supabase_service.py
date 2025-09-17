# services/supabase_service.py
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Clientes globales
supabase_anon: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
supabase_service: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

def db_as_user(jwt: str) -> Client:
    """
    Devuelve un cliente autenticado como el usuario del JWT (RLS ON).
    No uses 'options={'headers': ...}' porque rompe en supabase-py.
    """
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    if jwt:
        client.postgrest.auth(jwt)  # setea Authorization: Bearer <jwt> internamente
    return client
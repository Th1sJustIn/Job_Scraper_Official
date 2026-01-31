
import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

def get_supabase_client() -> Client:
    url: str = os.environ.get("SUPABASE_PROJECT_URL")
    key: str = os.environ.get("SUPABASE_SECRET_KEY")
    
    if not url:
        raise ValueError("SUPABASE_PROJECT_URL is not set in the environment variables.")
    if not key:
        raise ValueError("SUPABASE_SECRET_KEY is not set in the environment variables.")

    return create_client(url, key)

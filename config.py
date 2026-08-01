import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in the environment variables.")

DEFAULT_SCAN_ROOT = Path.home() / "projects"
DB_PATH = Path.home() / ".local" / "share" / "devdna" / "devdna.db"
SDK_OUTPUT_PATH = Path.home() / ".local" / "share" / "devdna" / "my_sdk"

# Ensure directories exist
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
SDK_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
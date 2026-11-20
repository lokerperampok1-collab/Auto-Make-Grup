from pathlib import Path

# Server Configuration (Localhost port 5555 + Auto Open Browser)
HOST = "127.0.0.1"
PORT = 5555
AUTO_OPEN_BROWSER = True

# Built-in Telegram API Credentials (Telegram Desktop Official)
# Tidak perlu diinput melalui Web UI
API_ID = 17158761
API_HASH = "67d9b554799271cca765d42f40e0db43"

# Client Fingerprint
DEVICE_MODEL = "Telegram Desktop"
SYSTEM_VERSION = "Windows 11"
APP_VERSION = "4.16.8 x64"
LANG_CODE = "id"
SYSTEM_LANG_CODE = "id-ID"

# Directories & Files
BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / "sessions"
UPLOADS_DIR = BASE_DIR / "uploads"
PHOTOS_DIR = UPLOADS_DIR / "photos"
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

ACCOUNTS_FILE = DATA_DIR / "accounts.json"
CREATED_GROUPS_FILE = DATA_DIR / "created_groups.json"

for directory in (SESSIONS_DIR, UPLOADS_DIR, PHOTOS_DIR, DATA_DIR, STATIC_DIR):
    directory.mkdir(parents=True, exist_ok=True)

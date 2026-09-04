"""Configuration, constants and paths.

Every secret comes from the environment. Everything else lives here as a plain
constant so there is exactly one place to edit when something moves.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ASSETS_DIR = BASE_DIR / "assets"

load_dotenv(BASE_DIR / ".env")


class ConfigError(SystemExit):
    """Raised at import time when the environment is not usable."""


def _required(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# ---------------------------------------------------------------- Telegram --

try:
    TELEGRAM_API_ID = int(_required("TELEGRAM_API_ID"))
except ValueError:
    raise ConfigError("TELEGRAM_API_ID must be a number, taken from my.telegram.org.")

TELEGRAM_API_HASH = _required("TELEGRAM_API_HASH")
TELEGRAM_BOT_TOKEN = _required("TELEGRAM_BOT_TOKEN")

# ---------------------------------------------------------------- Supabase --
# Optional. Without these the bot still generates and decodes codes, and the
# account features report themselves as unavailable rather than failing.

SUPABASE_URL = _optional("SUPABASE_URL").rstrip("/")
SUPABASE_SERVICE_KEY = _optional("SUPABASE_SERVICE_KEY")
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)

# ------------------------------------------------------------------- owner --
# Optional. Telegram ids allowed to run the health command, comma separated.
# Empty means nobody can, and the command reports itself as unavailable.


def _ids(name: str) -> frozenset[int]:
    raw = _optional(name)
    out = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return frozenset(out)


OWNER_TELEGRAM_IDS = _ids("OWNER_TELEGRAM_ID")

# ----------------------------------------------------------------- Portal ---

WEBAPP_URL = "https://qr.uwuapps.org"
DONATION_URL = _optional("DONATION_URL")

# Supabase objects the portal already owns, plus the two this bot adds.
TABLE_USERS = "qr_users"
TABLE_SESSIONS = "qr_sessions"
TABLE_CODES = "qr_codes"
TABLE_LINKS = "qr_telegram_links"
TABLE_TOKENS = "qr_tokens"
STORAGE_BUCKET = "qr_images"

# Portal sessions last thirty days, matching api/auth.js on the site.
SESSION_TTL_DAYS = 30

# ------------------------------------------------------------------ Local ---

DB_PATH = DATA_DIR / "bot.db"
SESSION_PATH = DATA_DIR / "bot"          # Telethon appends .session
LOG_PATH = DATA_DIR / "bot.log"

# Jua is the font the portal draws the watermark in, so the bot ships it and
# the two look identical. The rest are only a safety net for an install where
# the file has gone missing, and they will not match the site.
WATERMARK_FONT = ASSETS_DIR / "Jua-Regular.ttf"

FONT_CANDIDATES = (
    WATERMARK_FONT,
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
)

# ------------------------------------------------------------ QR defaults ---
# These mirror the portal: 300 px at the smallest step, margin 2, error
# correction H, black on white, watermarked.

DEFAULT_PREFS = {
    "size": 600,
    "margin": 2,
    "ec": "H",
    "watermark": 1,
    "fg": "#000000",
    "bg": "#ffffff",
}

SIZE_STEPS = (300, 600, 900, 1200)
MARGIN_STEPS = (1, 2, 4)
EC_STEPS = ("L", "M", "Q", "H")

# Name, foreground, background. Every pair clears the contrast a scanner needs.
COLOUR_PRESETS = (
    ("Classic", "#000000", "#ffffff"),
    ("Inverted", "#ffffff", "#000000"),
    ("Mint", "#0b3d2e", "#ccffcc"),
    ("Ink", "#1a1a2e", "#f5f5ff"),
    ("Rose", "#5c1a33", "#ffe6ef"),
)

# Watermark geometry, taken from script.js on the portal.
WATERMARK_TEXT = "uwu"
WATERMARK_FONT_RATIO = 0.092
WATERMARK_PAD_RATIO = 0.028

MAX_PAYLOAD_CHARS = 2000
SAVED_PAGE_SIZE = 5
HISTORY_KEEP = 40

# ------------------------------------------------------------------ Limits --

RATE_LIMIT_MAX = 30          # actions
RATE_LIMIT_WINDOW = 60       # seconds

DEEPLINK_TTL = 10 * 60       # seconds, site to Telegram
PULL_OTP_TTL = 10 * 60       # seconds, Telegram to site
PUSH_OTP_TTL = 5 * 60        # seconds, sign in challenge

POLL_INTERVAL = 3            # seconds between Supabase token sweeps

# The portal burns a sign in challenge at five wrong codes. Warn the owner
# before that, so they hear about it while the attempt is still in progress.
WARN_AFTER_ATTEMPTS = 3

DATA_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

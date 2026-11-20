import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TMP_MEDIA_DIR = BASE_DIR / "tmp_media"
PREVIEW_DIR = BASE_DIR / "output_preview"

STATE_FILE = DATA_DIR / "posted_news.json"

# Türkiye Genel Gündem RSS Kaynakları
RSS_FEEDS = [
    {
        "name": "TRT Haber",
        "url": "https://www.trthaber.com/sondakika.rss",
    },
    {
        "name": "NTV",
        "url": "https://www.ntv.com.tr/gundem.rss",
    },
    {
        "name": "BBC Türkçe",
        "url": "https://feeds.bbci.co.uk/turkce/rss.xml",
    },
    {
        "name": "Anadolu Ajansı",
        "url": "https://www.aa.com.tr/tr/rss/default?cat=guncel",
    },
    {
        "name": "Google News TR",
        "url": "https://news.google.com/rss?hl=tr&gl=TR&ceid=TR:tr",
    },
]

# API Anahtarları
X_API_KEY = os.getenv("X_API_KEY", "").strip()
X_API_SECRET = os.getenv("X_API_SECRET", "").strip()
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "").strip()
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET", "").strip()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-4-hydrogen").strip()

# Bot Ayarları
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "evet"}
MAX_POSTS_PER_RUN = max(1, int(os.getenv("MAX_POSTS_PER_RUN", "1")))
INCLUDE_SOURCE_LINK = os.getenv("INCLUDE_SOURCE_LINK", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "evet",
}
BRAND_NAME = os.getenv("BRAND_NAME", "GÜNDEM ÖZETİ").strip()

# Medya ve ağ limitleri
HTTP_TIMEOUT = 15
MAX_IMAGE_BYTES = 5 * 1024 * 1024      # 5 MB (X standart görsel limiti)
MAX_VIDEO_BYTES = 50 * 1024 * 1024     # 50 MB (GitHub Actions + X güvenli limit)
MAX_STORED_HISTORY = 500

# Anlık takip modu (watch.py) ayarları
WATCH_INTERVAL_SECONDS = max(60, int(os.getenv("WATCH_INTERVAL_SECONDS", "120")))
WATCH_MAX_AGE_MINUTES = max(5, int(os.getenv("WATCH_MAX_AGE_MINUTES", "30")))
WATCH_MAX_POSTS_PER_HOUR = max(1, int(os.getenv("WATCH_MAX_POSTS_PER_HOUR", "4")))
WATCH_MAX_POSTS_PER_DAY = max(1, int(os.getenv("WATCH_MAX_POSTS_PER_DAY", "30")))
WATCH_MIN_GAP_SECONDS = max(60, int(os.getenv("WATCH_MIN_GAP_SECONDS", "180")))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TMP_MEDIA_DIR = BASE_DIR / "tmp_media"
PREVIEW_DIR = BASE_DIR / "output_preview"

STATE_FILE = DATA_DIR / "posted_news.json"

# Türkiye Yüksek Etkileşimli Gündem RSS Kaynakları (Doğrudan Gerçek Fotoğraflı Kaynaklar)
RSS_FEEDS = [
    {
        "name": "TRT Haber",
        "category": "gundem",
        "url": "https://www.trthaber.com/sondakika.rss",
    },
    {
        "name": "TRT Ekonomi",
        "category": "ekonomi",
        "url": "https://www.trthaber.com/ekonomi_articles.rss",
    },
    {
        "name": "TRT Spor",
        "category": "spor",
        "url": "https://www.trthaber.com/spor_articles.rss",
    },
    {
        "name": "TRT Teknoloji",
        "category": "teknoloji",
        "url": "https://www.trthaber.com/bilim_teknoloji_articles.rss",
    },
    {
        "name": "NTV",
        "category": "gundem",
        "url": "https://www.ntv.com.tr/gundem.rss",
    },
    {
        "name": "NTV Ekonomi",
        "category": "ekonomi",
        "url": "https://www.ntv.com.tr/ekonomi.rss",
    },
    {
        "name": "NTV Spor",
        "category": "spor",
        "url": "https://www.ntv.com.tr/spor.rss",
    },
    {
        "name": "NTV Teknoloji",
        "category": "teknoloji",
        "url": "https://www.ntv.com.tr/teknoloji.rss",
    },
    {
        "name": "Habertürk",
        "category": "gundem",
        "url": "https://www.haberturk.com/rss/kategori/gundem.xml",
    },
    {
        "name": "BBC Türkçe",
        "category": "gundem",
        "url": "https://feeds.bbci.co.uk/turkce/rss.xml",
    },
    {
        "name": "Anadolu Ajansı",
        "category": "gundem",
        "url": "https://www.aa.com.tr/tr/rss/default?cat=guncel",
    },
]

# Kesinlikle paylaşılmayacak SEO tıklama tuzağı, reklam/advertorial ve magazin kalıpları
BLOCKED_TITLE_PATTERNS = {
    "deprem mi oldu", "az önce deprem", "son depremler", "nerede oldu",
    "ne zaman, hangi ayda", "ne zaman başlıyor", "kaç gün kaldı",
    "advertorial", "sponsorlu", "ilan:", "dap yapı", "kendi kendini ödeyen",
    "sayısal loto", "şans topu", "süper loto", "on numara", "burç yorumları",
    "fragman", "son bölüm izle",
}

# X'te yüksek etkileşim (RT, yorum, alıntı) alan gündem anahtar kelimeleri
HIGH_ENGAGEMENT_KEYWORDS = {
    "son dakika", "zam", "indirim", "faiz", "merkez bankası", "dolar", "euro",
    "altın", "gram altın", "borsa", "enflasyon", "asgari ücret", "emekli",
    "memur", "maaş", "vergi", "kredi", "benzin", "motorin", "akaryakıt",
    "elektrik", "doğalgaz", "resmi gazete", "yürürlüğe", "yasak", "ceza",
    "karar", "açıklama", "deprem", "uyarı", "meteoroloji", "tatil",
    "fenerbahçe", "galatasaray", "beşiktaş", "trabzonspor", "milli takım",
    "süper lig", "şampiyonlar ligi", "transfer", "derbi",
    "yapay zeka", "openai", "google", "apple", "iphone", "tesla", "elon musk",
    "instagram", "whatsapp", "tiktok", "youtube", "bitcoin", "kripto",
}

# Düşük etkileşimli rutin/yerel haberleri geriye atmak için anahtar kelimeler
LOW_ENGAGEMENT_KEYWORDS = {
    "ilçe belediye", "muhtar", "fuarı açıldı", "sergisi açıldı",
    "kermes", "kursiyer", "törenle açıldı", "plaket", "ziyaret etti",
}

# Google Trends Türkiye (sadece ciddi haberlere +6 destek puanı vermek için)
GOOGLE_TRENDS_TR_RSS = "https://trends.google.com/trending/rss?geo=TR"

# Magazin, dizi, loto, burç gibi ciddi haber dışı trendleri tamamen yok say
IGNORED_TREND_KEYWORDS = {
    "bölüm", "fragman", "dizi", "izle", "survivor", "masterchef", "müge anlı",
    "esra erol", "magazin", "burç", "astroloji", "sayısal loto", "şans topu",
    "süper loto", "on numara", "milli piyango", "kimdir", "kaç yaşında",
    "nereli", "sevgilisi", "boşandı", "evlendi", "elbise", "kombin",
}

# API Anahtarları
X_API_KEY = os.getenv("X_API_KEY", "").strip()
X_API_SECRET = os.getenv("X_API_SECRET", "").strip()
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "").strip()
X_ACCESS_TOKEN_SECRET = os.getenv("X_ACCESS_TOKEN_SECRET", "").strip()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()

# Bot Ayarları
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() in {"1", "true", "yes", "evet"}
MAX_POSTS_PER_RUN = max(1, int(os.getenv("MAX_POSTS_PER_RUN", "1")))
INCLUDE_SOURCE_LINK = os.getenv("INCLUDE_SOURCE_LINK", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "evet",
}
INCLUDE_MEDIA = os.getenv("INCLUDE_MEDIA", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "evet",
}
BRAND_NAME = os.getenv("BRAND_NAME", "HABER EXE").strip()

# Medya ve ağ limitleri
HTTP_TIMEOUT = 15
MAX_IMAGE_BYTES = 5 * 1024 * 1024      # 5 MB (X standart görsel limiti)
MAX_VIDEO_BYTES = 50 * 1024 * 1024     # 50 MB (GitHub Actions + X güvenli limit)
MAX_STORED_HISTORY = 500
MAX_NEWS_AGE_HOURS = max(1, int(os.getenv("MAX_NEWS_AGE_HOURS", "12")))

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

import json
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from config import MAX_STORED_HISTORY, STATE_FILE


TURKISH_STOPWORDS = {
    "ve", "ile", "bir", "bu", "da", "de", "için", "icin", "mi", "mı", "mu", "mü",
    "ne", "en", "çok", "cok", "son", "dakika", "haber", "haberleri", "olarak",
    "göre", "gore", "daha", "ise", "gibi", "ama", "fakat", "ancak", "kadar",
    "olan", "oldu", "etti", "yaptı", "yapti", "dedi", "açıkladı", "acikladi",
}


def normalize_url(url: str) -> str:
    """Query parametrelerini temizleyerek kanonik URL üretir."""
    parsed = urlparse(url.strip())
    return urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", ""))


def tokenize_title(title: str) -> set[str]:
    """Başlıktaki anlamlı kelimeleri küçük harfe çevirip küme olarak döndürür."""
    text = title.replace("İ", "i").replace("I", "ı").lower()
    words = re.findall(r"[a-zçğıöşü0-9]{3,}", text)
    return {w for w in words if w not in TURKISH_STOPWORDS}


class PostedNewsStore:
    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        self.posted_urls: list[str] = []
        self.posted_titles: list[str] = []
        self.last_categories: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.posted_urls = list(data.get("posted_urls", []))
            self.posted_titles = list(data.get("posted_titles", []))
            self.last_categories = list(data.get("last_categories", []))
        except (json.JSONDecodeError, OSError):
            self.posted_urls = []
            self.posted_titles = []
            self.last_categories = []

    def get_last_category(self) -> str | None:
        return self.last_categories[-1] if self.last_categories else None

    def is_duplicate(self, url: str, title: str, similarity_threshold: float = 0.35) -> bool:
        norm_url = normalize_url(url)
        if norm_url in self.posted_urls:
            return True

        new_tokens = tokenize_title(title)
        if not new_tokens:
            return False

        # Son 150 başlıkta Jaccard benzerliği kontrolü
        for old_title in self.posted_titles[-150:]:
            old_tokens = tokenize_title(old_title)
            if not old_tokens:
                continue
            intersection = new_tokens & old_tokens
            union = new_tokens | old_tokens
            if union and (len(intersection) / len(union)) >= similarity_threshold:
                return True

        # Son 15 başlıkta en az 3 ortak anlamlı kelime varsa aynı gündem konusunu tekrar etme
        for recent_title in self.posted_titles[-15:]:
            recent_tokens = tokenize_title(recent_title)
            if len(new_tokens & recent_tokens) >= 3:
                return True
        return False

    def mark_posted(self, url: str, title: str, category: str = "gundem") -> None:
        norm_url = normalize_url(url)
        if norm_url not in self.posted_urls:
            self.posted_urls.append(norm_url)
        self.posted_titles.append(title.strip())
        self.last_categories.append(category)

        self.posted_urls = self.posted_urls[-MAX_STORED_HISTORY:]
        self.posted_titles = self.posted_titles[-MAX_STORED_HISTORY:]
        self.last_categories = self.last_categories[-10:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "posted_urls": self.posted_urls,
            "posted_titles": self.posted_titles,
            "last_categories": self.last_categories,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

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
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.posted_urls = list(data.get("posted_urls", []))
            self.posted_titles = list(data.get("posted_titles", []))
        except (json.JSONDecodeError, OSError):
            self.posted_urls = []
            self.posted_titles = []

    def is_duplicate(self, url: str, title: str, similarity_threshold: float = 0.55) -> bool:
        norm_url = normalize_url(url)
        if norm_url in self.posted_urls:
            return True

        new_tokens = tokenize_title(title)
        if not new_tokens:
            return False

        for old_title in self.posted_titles[-150:]:
            old_tokens = tokenize_title(old_title)
            if not old_tokens:
                continue
            intersection = new_tokens & old_tokens
            union = new_tokens | old_tokens
            if union and (len(intersection) / len(union)) >= similarity_threshold:
                return True
        return False

    def mark_posted(self, url: str, title: str) -> None:
        norm_url = normalize_url(url)
        if norm_url not in self.posted_urls:
            self.posted_urls.append(norm_url)
        self.posted_titles.append(title.strip())

        self.posted_urls = self.posted_urls[-MAX_STORED_HISTORY:]
        self.posted_titles = self.posted_titles[-MAX_STORED_HISTORY:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "posted_urls": self.posted_urls,
            "posted_titles": self.posted_titles,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

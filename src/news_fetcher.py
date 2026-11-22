import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from config import (
    GOOGLE_TRENDS_TR_RSS,
    HIGH_ENGAGEMENT_KEYWORDS,
    HTTP_TIMEOUT,
    IGNORED_TREND_KEYWORDS,
    LOW_ENGAGEMENT_KEYWORDS,
    MAX_NEWS_AGE_HOURS,
    RSS_FEEDS,
    USER_AGENT,
)
from src.storage import tokenize_title

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    category: str = "gundem"
    summary: str = ""
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    article_text: str = ""
    engagement_score: float = 0.0


def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_date(entry) -> datetime:
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (TypeError, ValueError):
                pass
    return datetime.now(timezone.utc)


def _extract_rss_media(entry) -> tuple[Optional[str], Optional[str]]:
    """RSS öğesinden varsa doğrudan görsel veya video URL'sini çıkarır."""
    image_url: Optional[str] = None
    video_url: Optional[str] = None

    for media in getattr(entry, "media_content", []) or []:
        m_url = media.get("url")
        m_type = (media.get("type") or "").lower()
        if not m_url:
            continue
        if "video" in m_type or m_url.lower().endswith(".mp4"):
            video_url = video_url or m_url
        elif "image" in m_type or any(
            m_url.lower().split("?")[0].endswith(ext)
            for ext in (".jpg", ".jpeg", ".png", ".webp")
        ):
            image_url = image_url or m_url

    for enc in getattr(entry, "enclosures", []) or []:
        e_url = enc.get("href") or enc.get("url")
        e_type = (enc.get("type") or "").lower()
        if not e_url:
            continue
        if "video" in e_type or e_url.lower().endswith(".mp4"):
            video_url = video_url or e_url
        elif "image" in e_type:
            image_url = image_url or e_url

    for thumb in getattr(entry, "media_thumbnail", []) or []:
        t_url = thumb.get("url")
        if t_url and not image_url:
            image_url = t_url

    # Bazı RSS'ler <img> etiketini summary içine gömer
    if not image_url and getattr(entry, "summary", None):
        soup = BeautifulSoup(entry.summary, "html.parser")
        img = soup.find("img")
        if img and img.get("src"):
            image_url = img["src"]

    return image_url, video_url


def _tr_lower(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()


def _fetch_serious_trends() -> list[str]:
    """
    Google Trends Türkiye RSS'inden anlık aranan konuları çeker;
    magazin/dizi/loto/burç gibi ciddi haber dışı aramaları tamamen eler.
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(GOOGLE_TRENDS_TR_RSS, headers=headers, timeout=8)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:
        logger.debug("Google Trends alınamadı (sorun değil, devam ediliyor): %s", exc)
        return []

    serious_terms: list[str] = []
    for entry in parsed.entries[:25]:
        raw = _clean_html(getattr(entry, "title", ""))
        term = _tr_lower(raw)
        if len(term) < 4:
            continue
        if any(bad in term for bad in IGNORED_TREND_KEYWORDS):
            continue
        serious_terms.append(term)
    return serious_terms


def _rank_by_engagement(
    items: list[NewsItem],
    last_category: Optional[str] = None,
    trend_terms: Optional[list[str]] = None,
) -> list[NewsItem]:
    """
    Haberleri X etkileşim potansiyeline göre puanlar:
    - Birden fazla ajansın aynı anda geçtiği gündem haberleri (+6)
    - Sıkı filtreli Google Trends TR eşleşmesi (+6, sadece ciddi haberlerde)
    - Ekonomi/zam/spor/teknoloji/son dakika anahtar kelimeleri (+3)
    - Güncellik puanı (son 1-6 saat öncelikli)
    - Kategori çeşitliliği (son paylaşılan kategoriye -5, farklı kategoriye +2)
    - Magazin/dizi/rutin yerel haber cezası (-4 / -6)
    """
    now = datetime.now(timezone.utc)
    token_sets = [tokenize_title(it.title) for it in items]
    active_trends = trend_terms or []

    for idx, item in enumerate(items):
        score = 0.0
        haystack = _tr_lower(f"{item.title} {item.summary}")

        # 1. Güncellik puanı (max +8, 12 saat sonra 0)
        age_hours = max(0.0, (now - item.published_at).total_seconds() / 3600.0)
        score += max(0.0, 8.0 - (age_hours * 0.7))

        # 2. Yüksek etkileşimli kategori & anahtar kelime bonusu
        if item.category in ("ekonomi", "spor", "teknoloji"):
            score += 2.0

        kw_hits = sum(1 for kw in HIGH_ENGAGEMENT_KEYWORDS if kw in haystack)
        score += min(kw_hits * 3.0, 12.0)

        # 3. Sıkı filtreli Google Trends TR ciddi haber bonusu (en fazla +6)
        if active_trends and not any(bad in haystack for bad in IGNORED_TREND_KEYWORDS):
            if any(t in haystack for t in active_trends):
                score += 6.0

        # 4. Kategori çeşitliliği (üst üste aynı kategori paylaşılmasın)
        if last_category:
            if item.category == last_category:
                score -= 5.0
            else:
                score += 2.0

        # 5. Çoklu kaynak trend bonusu (en az 2 farklı ajans aynı konuyu yazıyorsa)
        my_tokens = token_sets[idx]
        if my_tokens:
            matching_sources = {item.source}
            for j, other in enumerate(items):
                if j == idx or other.source in matching_sources:
                    continue
                other_tokens = token_sets[j]
                if not other_tokens:
                    continue
                union = my_tokens | other_tokens
                if union and (len(my_tokens & other_tokens) / len(union)) >= 0.35:
                    matching_sources.add(other.source)
            if len(matching_sources) >= 2:
                score += (len(matching_sources) - 1) * 6.0

        # 6. Medya bonusu
        if item.video_url:
            score += 2.5
        elif item.image_url:
            score += 1.5

        # 7. Düşük etkileşim & magazin/dizi cezası
        if any(kw in haystack for kw in LOW_ENGAGEMENT_KEYWORDS):
            score -= 4.0
        if any(bad in haystack for bad in IGNORED_TREND_KEYWORDS):
            score -= 6.0

        item.engagement_score = round(score, 2)

    items.sort(key=lambda x: (x.engagement_score, x.published_at), reverse=True)
    return items


def fetch_trending_news(
    limit_per_feed: int = 8,
    last_category: Optional[str] = None,
    max_age_hours: int = MAX_NEWS_AGE_HOURS,
) -> list[NewsItem]:
    """Tanımlı Türkiye gündem RSS kaynaklarından son X saatteki haberleri çeker ve sıralar."""
    items: list[NewsItem] = []
    headers = {"User-Agent": USER_AGENT}
    now = datetime.now(timezone.utc)

    for feed_cfg in RSS_FEEDS:
        name = feed_cfg["name"]
        category = feed_cfg.get("category", "gundem")
        url = feed_cfg["url"]
        try:
            resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
        except Exception as exc:
            logger.warning("RSS alınamadı (%s): %s", name, exc)
            continue

        for entry in parsed.entries[:limit_per_feed]:
            title = _clean_html(getattr(entry, "title", ""))
            link = getattr(entry, "link", "").strip()
            if not title or not link:
                continue

            # Google News başlıklarında " - Kaynak Adı" kısmını ayır
            source_name = name
            if name == "Google News TR" and " - " in title:
                parts = title.rsplit(" - ", 1)
                if len(parts[0]) > 15:
                    title, source_name = parts[0].strip(), parts[1].strip()

            summary = _clean_html(getattr(entry, "summary", ""))
            image_url, video_url = _extract_rss_media(entry)

            items.append(
                NewsItem(
                    title=title,
                    url=link,
                    source=source_name,
                    category=category,
                    summary=summary,
                    published_at=_parse_date(entry),
                    image_url=image_url,
                    video_url=video_url,
                )
            )

    # Bayat haber filtresi: max_age_hours'tan eski haberleri ele
    fresh_by_age = [
        it for it in items
        if (now - it.published_at).total_seconds() <= max_age_hours * 3600
    ]
    filtered = fresh_by_age if fresh_by_age else items
    if len(filtered) < len(items):
        logger.info(
            "Bayat haber filtresi: %d haberden son %d saatteki %d haber seçildi.",
            len(items),
            max_age_hours,
            len(filtered),
        )

    trend_terms = _fetch_serious_trends()
    if trend_terms:
        logger.info("Google Trends TR'den %d ciddi trend konusu alındı.", len(trend_terms))

    return _rank_by_engagement(filtered, last_category=last_category, trend_terms=trend_terms)


def enrich_news_item(item: NewsItem) -> NewsItem:
    """
    Haber sayfasını ziyaret ederek:
    - Daha kaliteli görsel (og:image / twitter:image)
    - Varsa doğrudan indirilebilir .mp4 video (og:video / <video>)
    - AI özetleme için temiz haber metni
    çıkarır.
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"}
    try:
        resp = requests.get(item.url, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        item.url = resp.url  # Yönlendirme sonrası gerçek haber URL'si
    except Exception as exc:
        logger.warning("Haber sayfası açılamadı (%s): %s", item.url, exc)
        return item

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. Video arama (sadece doğrudan .mp4 linkleri)
    if not item.video_url:
        video_meta_candidates = [
            soup.find("meta", property="og:video:secure_url"),
            soup.find("meta", property="og:video:url"),
            soup.find("meta", property="og:video"),
        ]
        for tag in video_meta_candidates:
            if tag and tag.get("content"):
                cand = urljoin(item.url, tag["content"].strip())
                if ".mp4" in cand.lower():
                    item.video_url = cand
                    break

    if not item.video_url:
        for source_tag in soup.find_all("source"):
            src = source_tag.get("src") or ""
            s_type = (source_tag.get("type") or "").lower()
            if src and (".mp4" in src.lower() or "video/mp4" in s_type):
                item.video_url = urljoin(item.url, src.strip())
                break

    # 2. Yüksek çözünürlüklü görsel arama (og:image her zaman RSS thumbnail'dan daha iyidir)
    image_meta_candidates = [
        soup.find("meta", property="og:image:secure_url"),
        soup.find("meta", property="og:image"),
        soup.find("meta", attrs={"name": "twitter:image"}),
    ]
    for tag in image_meta_candidates:
        if tag and tag.get("content"):
            cand = urljoin(item.url, tag["content"].strip())
            if cand.startswith("http"):
                item.image_url = cand
                break

    # 3. Haber metni çıkarımı (AI daha doğru özet yazsın diye ilk birkaç paragraf)
    paragraphs = []
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) >= 45:
            paragraphs.append(text)
        if sum(len(x) for x in paragraphs) >= 1200:
            break

    if paragraphs:
        item.article_text = " ".join(paragraphs)[:1400]

    return item

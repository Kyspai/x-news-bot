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

from config import HTTP_TIMEOUT, RSS_FEEDS, USER_AGENT

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    summary: str = ""
    published_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    article_text: str = ""


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


def fetch_trending_news(limit_per_feed: int = 8) -> list[NewsItem]:
    """Tanımlı Türkiye gündem RSS kaynaklarından en güncel haberleri çeker."""
    items: list[NewsItem] = []
    headers = {"User-Agent": USER_AGENT}

    for feed_cfg in RSS_FEEDS:
        name = feed_cfg["name"]
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
                    summary=summary,
                    published_at=_parse_date(entry),
                    image_url=image_url,
                    video_url=video_url,
                )
            )

    # En yeni haberler başa gelsin
    items.sort(key=lambda x: x.published_at, reverse=True)
    return items


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

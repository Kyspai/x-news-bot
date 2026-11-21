"""
7/24 Anlık Gündem Takip Modu (watch.py)

Belirlenen aralıklarla (varsayılan 2 dakikada bir) RSS kaynaklarını tarar,
yeni düşen haberleri spam ve maliyet limitlerine uyarak anlık olarak X'e paylaşır.
VPS / bulut sunucuda veya bilgisayarında arka planda çalıştırmak için idealdir.
"""

import logging
import shutil
import signal
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from config import (
    DRY_RUN,
    INCLUDE_MEDIA,
    TMP_MEDIA_DIR,
    WATCH_INTERVAL_SECONDS,
    WATCH_MAX_AGE_MINUTES,
    WATCH_MAX_POSTS_PER_DAY,
    WATCH_MAX_POSTS_PER_HOUR,
    WATCH_MIN_GAP_SECONDS,
)
from src.ai_writer import compose_tweet
from src.media_handler import prepare_media
from src.news_fetcher import enrich_news_item, fetch_trending_news
from src.storage import PostedNewsStore
from src.x_publisher import XPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("x-news-watch")

_running = True


def _handle_stop(signum, _frame):
    global _running
    logger.info("Durdurma sinyali alındı (%s), güvenli çıkış yapılıyor...", signum)
    _running = False


def _prune_timestamps(timestamps: deque[float], window_seconds: int, now: float) -> None:
    while timestamps and (now - timestamps[0]) > window_seconds:
        timestamps.popleft()


def watch_loop() -> int:
    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    logger.info(
        "Anlık takip modu başlatıldı | aralık=%dsn | saatlik_limit=%d | günlük_limit=%d | DRY_RUN=%s",
        WATCH_INTERVAL_SECONDS,
        WATCH_MAX_POSTS_PER_HOUR,
        WATCH_MAX_POSTS_PER_DAY,
        DRY_RUN,
    )

    store = PostedNewsStore()
    publisher = XPublisher(dry_run=DRY_RUN)

    hour_posts: deque[float] = deque()
    day_posts: deque[float] = deque()
    last_post_ts: float = 0.0

    while _running:
        now_ts = time.time()
        _prune_timestamps(hour_posts, 3600, now_ts)
        _prune_timestamps(day_posts, 86400, now_ts)

        if len(day_posts) >= WATCH_MAX_POSTS_PER_DAY:
            logger.info(
                "Günlük üst limite (%d) ulaşıldı, bekleniyor...",
                WATCH_MAX_POSTS_PER_DAY,
            )
        elif len(hour_posts) >= WATCH_MAX_POSTS_PER_HOUR:
            logger.info(
                "Saatlik üst limite (%d) ulaşıldı, bekleniyor...",
                WATCH_MAX_POSTS_PER_HOUR,
            )
        elif (now_ts - last_post_ts) < WATCH_MIN_GAP_SECONDS:
            remaining = int(WATCH_MIN_GAP_SECONDS - (now_ts - last_post_ts))
            logger.info("Paylaşımlar arası bekleme süresi: %d sn kaldı.", remaining)
        else:
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(minutes=WATCH_MAX_AGE_MINUTES)
                items = fetch_trending_news(limit_per_feed=6)
                candidates = [
                    item
                    for item in items
                    if item.published_at >= cutoff
                    and not store.is_duplicate(item.url, item.title)
                ]

                if candidates:
                    # En taze tek haberi paylaş (spam koruması)
                    target = candidates[0]
                    logger.info("Yeni haber yakalandı: [%s] %s", target.source, target.title)
                    enriched = enrich_news_item(target)

                    if not store.is_duplicate(enriched.url, enriched.title):
                        tweet_text = compose_tweet(enriched)
                        media = prepare_media(enriched) if INCLUDE_MEDIA else None
                        publisher.publish(tweet_text, media=media)

                        if not DRY_RUN:
                            store.mark_posted(enriched.url, enriched.title)
                            store.save()

                        posted_at = time.time()
                        hour_posts.append(posted_at)
                        day_posts.append(posted_at)
                        last_post_ts = posted_at
                else:
                    logger.info("Son %d dakikada yeni haber yok.", WATCH_MAX_AGE_MINUTES)
            except Exception as exc:
                logger.exception("Tarama sırasında hata: %s", exc)
            finally:
                if TMP_MEDIA_DIR.exists():
                    shutil.rmtree(TMP_MEDIA_DIR, ignore_errors=True)

        # Durdurma sinyaline hızlı yanıt için 1'er saniyelik adımlarla bekle
        for _ in range(WATCH_INTERVAL_SECONDS):
            if not _running:
                break
            time.sleep(1)

    logger.info("Anlık takip modu sonlandırıldı.")
    return 0


if __name__ == "__main__":
    sys.exit(watch_loop())

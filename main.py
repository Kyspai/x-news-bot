import logging
import shutil
import sys

import tweepy

from config import DRY_RUN, INCLUDE_MEDIA, MAX_POSTS_PER_RUN, TMP_MEDIA_DIR
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
logger = logging.getLogger("x-news-bot")


def run() -> int:
    logger.info(
        "Bot başlatıldı (DRY_RUN=%s, MAX_POSTS_PER_RUN=%d)",
        DRY_RUN,
        MAX_POSTS_PER_RUN,
    )

    store = PostedNewsStore()
    publisher = XPublisher(dry_run=DRY_RUN)

    news_items = fetch_trending_news(limit_per_feed=8)
    logger.info("Toplam %d güncel haber toplandı.", len(news_items))

    fresh_items = [
        item for item in news_items if not store.is_duplicate(item.url, item.title)
    ]
    logger.info("Daha önce paylaşılmamış %d haber bulundu.", len(fresh_items))

    if not fresh_items:
        logger.info("Paylaşılacak yeni haber yok, çıkılıyor.")
        return 0

    posted_count = 0
    for item in fresh_items:
        if posted_count >= MAX_POSTS_PER_RUN:
            break

        try:
            logger.info(
                "İşleniyor (puan=%.1f | %s): [%s] %s",
                item.engagement_score,
                item.category,
                item.source,
                item.title,
            )
            enriched = enrich_news_item(item)

            # Yönlendirme sonrası gerçek URL de daha önce paylaşılmış olabilir
            if store.is_duplicate(enriched.url, enriched.title):
                logger.info("Yönlendirme sonrası tekrar tespit edildi, atlanıyor.")
                continue

            tweet_text = compose_tweet(enriched)
            media = prepare_media(enriched) if INCLUDE_MEDIA else None

            publisher.publish(tweet_text, media=media)

            if not DRY_RUN:
                store.mark_posted(enriched.url, enriched.title)
                store.save()

            posted_count += 1
        except tweepy.TweepyException as exc:
            logger.error("X API hatası nedeniyle çalışma durduruluyor: %s", exc)
            if TMP_MEDIA_DIR.exists():
                shutil.rmtree(TMP_MEDIA_DIR, ignore_errors=True)
            return 1
        except Exception as exc:
            logger.exception("Haber işlenirken hata oluştu: %s", exc)

    # Geçici medya dosyalarını temizle
    if TMP_MEDIA_DIR.exists():
        shutil.rmtree(TMP_MEDIA_DIR, ignore_errors=True)

    logger.info("Tamamlandı. Bu çalışmada işlenen haber sayısı: %d", posted_count)
    return 0


if __name__ == "__main__":
    sys.exit(run())

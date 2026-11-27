import logging
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tweepy

from config import DATA_DIR, DRY_RUN, INCLUDE_MEDIA, MAX_POSTS_PER_RUN, TMP_MEDIA_DIR
from src.ai_writer import compose_tweet
from src.media_handler import prepare_media
from src.news_fetcher import enrich_news_item, fetch_trending_news
from src.special_posts import build_daily_digest_post, build_market_post
from src.storage import PostedNewsStore
from src.x_publisher import XPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("x-news-bot")

HEALTH_REPORT_FILE = DATA_DIR / "health_report.md"


def _append_health_report(status: str, detail: str, tweet_url: str = "-") -> None:
    """Son 30 koşunun durum özetini data/health_report.md ve GitHub Step Summary'ye yazar."""
    tr_now = datetime.now(timezone.utc) + timedelta(hours=3)
    ts = tr_now.strftime("%d.%m.%Y %H:%M TR")
    safe_detail = detail.replace("|", "-").replace("\n", " ")[:110]
    link_md = f"[Tweet]({tweet_url})" if tweet_url.startswith("http") else tweet_url
    new_row = f"| {ts} | {status} | {safe_detail} | {link_md} |"

    header = [
        "# HaberExe Otomasyon Sağlık Raporu",
        "",
        "| Tarih (TR) | Durum | Haber / Detay | Link |",
        "|---|---|---|---|",
    ]
    existing_rows: list[str] = []
    if HEALTH_REPORT_FILE.exists():
        for line in HEALTH_REPORT_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("| ") and not line.startswith("| Tarih") and not line.startswith("|---"):
                existing_rows.append(line)

    rows = [new_row] + existing_rows[:29]
    HEALTH_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_REPORT_FILE.write_text("\n".join(header + rows) + "\n", encoding="utf-8")

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with Path(summary_path).open("a", encoding="utf-8") as f:
                f.write(f"### HaberExe Koşu Raporu ({ts})\n\n")
                f.write(f"- **Durum:** {status}\n")
                f.write(f"- **Detay:** {safe_detail}\n")
                f.write(f"- **Link:** {link_md}\n")
        except OSError:
            pass


def _resolve_post_mode() -> str:
    """
    POST_MODE='auto' iken TR saatine göre otomatik mod seçer:
    - Hafta içi 08:30 - 10:30 TR -> 'market' (Sabah Piyasa Açılışı)
    - Her gün 22:30 - 00:30 TR -> 'digest' (Akşam Günün Özeti)
    - Diğer tüm saatler -> 'news' (Normal yüksek etkileşimli haber)
    """
    explicit = os.getenv("POST_MODE", "auto").strip().lower()
    if explicit in {"news", "market", "digest"}:
        return explicit

    tr_now = datetime.now(timezone.utc) + timedelta(hours=3)
    minutes_of_day = tr_now.hour * 60 + tr_now.minute
    is_weekday = tr_now.weekday() < 5

    if is_weekday and (8 * 60 + 30) <= minutes_of_day <= (10 * 60 + 30):
        return "market"
    if minutes_of_day >= (22 * 60 + 30) or minutes_of_day <= 30:
        return "digest"
    return "news"


def run() -> int:
    mode = _resolve_post_mode()
    logger.info(
        "Bot başlatıldı (MODE=%s, DRY_RUN=%s, MAX_POSTS_PER_RUN=%d)",
        mode,
        DRY_RUN,
        MAX_POSTS_PER_RUN,
    )

    store = PostedNewsStore()
    publisher = XPublisher(dry_run=DRY_RUN)

    # Özel formatlar: Sabah Piyasa Açılışı veya Akşam Günün Özeti
    if mode in {"market", "digest"}:
        try:
            special = (
                build_market_post()
                if mode == "market"
                else build_daily_digest_post(store.posted_titles)
            )
            if special:
                tweet_text, media = special
                tweet_id = publisher.publish(tweet_text, media=media if INCLUDE_MEDIA else None)
                if not DRY_RUN:
                    tweet_url = f"https://x.com/i/web/status/{tweet_id}" if tweet_id else "-"
                    label = "[piyasa] Sabah Piyasa Açılışı" if mode == "market" else "[ozet] Akşam Günün Özeti"
                    _append_health_report("✅ Yayınlandı", label, tweet_url)
                if TMP_MEDIA_DIR.exists():
                    shutil.rmtree(TMP_MEDIA_DIR, ignore_errors=True)
                logger.info("Özel format başarıyla tamamlandı (%s).", mode)
                return 0
        except tweepy.TweepyException as exc:
            logger.error("X API hatası (%s): %s", mode, exc)
            if not DRY_RUN:
                _append_health_report("❌ X API Hatası", str(exc))
            if TMP_MEDIA_DIR.exists():
                shutil.rmtree(TMP_MEDIA_DIR, ignore_errors=True)
            return 1
        except Exception as exc:
            logger.warning("Özel format (%s) başarısız, normal habere geçiliyor: %s", mode, exc)

    news_items = fetch_trending_news(
        limit_per_feed=8,
        last_category=store.get_last_category(),
    )
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

            tweet_id = publisher.publish(tweet_text, media=media)

            if not DRY_RUN:
                store.mark_posted(enriched.url, enriched.title, category=enriched.category)
                store.save()
                tweet_url = f"https://x.com/i/web/status/{tweet_id}" if tweet_id else "-"
                _append_health_report("✅ Yayınlandı", f"[{enriched.category}] {enriched.title}", tweet_url)

            posted_count += 1
        except tweepy.TweepyException as exc:
            logger.error("X API hatası nedeniyle çalışma durduruluyor: %s", exc)
            if not DRY_RUN:
                _append_health_report("❌ X API Hatası", str(exc))
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

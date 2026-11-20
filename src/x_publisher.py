import logging
import shutil
from typing import Optional

import tweepy

from config import (
    DRY_RUN,
    PREVIEW_DIR,
    X_API_KEY,
    X_API_SECRET,
    X_ACCESS_TOKEN,
    X_ACCESS_TOKEN_SECRET,
)
from src.media_handler import PreparedMedia

logger = logging.getLogger(__name__)


class XPublisher:
    def __init__(self, dry_run: bool = DRY_RUN):
        self.dry_run = dry_run
        self._api_v1: Optional[tweepy.API] = None
        self._client_v2: Optional[tweepy.Client] = None

        if not self.dry_run:
            self._validate_credentials()
            auth = tweepy.OAuth1UserHandler(
                X_API_KEY,
                X_API_SECRET,
                X_ACCESS_TOKEN,
                X_ACCESS_TOKEN_SECRET,
            )
            self._api_v1 = tweepy.API(auth, wait_on_rate_limit=True)
            self._client_v2 = tweepy.Client(
                consumer_key=X_API_KEY,
                consumer_secret=X_API_SECRET,
                access_token=X_ACCESS_TOKEN,
                access_token_secret=X_ACCESS_TOKEN_SECRET,
                wait_on_rate_limit=True,
            )

    @staticmethod
    def _validate_credentials() -> None:
        missing = [
            name
            for name, val in [
                ("X_API_KEY", X_API_KEY),
                ("X_API_SECRET", X_API_SECRET),
                ("X_ACCESS_TOKEN", X_ACCESS_TOKEN),
                ("X_ACCESS_TOKEN_SECRET", X_ACCESS_TOKEN_SECRET),
            ]
            if not val
        ]
        if missing:
            raise RuntimeError(
                f"Eksik X API anahtarları: {', '.join(missing)}. "
                "Test için DRY_RUN=true kullanabilir veya anahtarları .env / GitHub Secrets'a ekleyebilirsiniz."
            )

    def publish(self, text: str, media: Optional[PreparedMedia] = None) -> Optional[str]:
        if self.dry_run:
            PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
            saved_media_info = "Yok"
            if media and media.path.exists():
                preview_target = PREVIEW_DIR / media.path.name
                shutil.copy2(media.path, preview_target)
                saved_media_info = f"{media.media_type} -> {preview_target}"

            logger.info("=" * 60)
            logger.info("[DRY_RUN ÖNİZLEME] X'e gerçek gönderim YAPILMADI")
            logger.info("Tweet (%d karakter):\n%s", len(text), text)
            logger.info("Medya: %s", saved_media_info)
            logger.info("=" * 60)
            return "dry-run-id"

        assert self._api_v1 is not None and self._client_v2 is not None
        media_ids = None

        if media and media.path.exists():
            if media.media_type == "video":
                uploaded = self._api_v1.media_upload(
                    filename=str(media.path),
                    media_category="tweet_video",
                    chunked=True,
                    wait_for_async_finalize=True,
                )
            else:
                uploaded = self._api_v1.media_upload(filename=str(media.path))
            media_ids = [uploaded.media_id_string]
            logger.info("Medya X'e yüklendi (media_id=%s)", uploaded.media_id_string)

        response = self._client_v2.create_tweet(text=text, media_ids=media_ids)
        tweet_id = str(response.data["id"])
        logger.info("Tweet başarıyla paylaşıldı! URL: https://x.com/i/web/status/%s", tweet_id)
        return tweet_id

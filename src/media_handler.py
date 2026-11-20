import io
import logging
import textwrap
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import requests
from PIL import Image, ImageDraw, ImageFont

from config import (
    BRAND_NAME,
    HTTP_TIMEOUT,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    TMP_MEDIA_DIR,
    USER_AGENT,
)
from src.news_fetcher import NewsItem

logger = logging.getLogger(__name__)


@dataclass
class PreparedMedia:
    path: Path
    media_type: Literal["image", "video"]
    is_generated_card: bool = False


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Türkçe karakterleri destekleyen sistem fontunu bulur (Linux/GitHub Actions ve Windows)."""
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
    )
    for font_path in candidates:
        if Path(font_path).exists():
            try:
                return ImageFont.truetype(font_path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _download_video(url: str, output_dir: Path) -> Optional[Path]:
    headers = {"User-Agent": USER_AGENT}
    try:
        with requests.get(url, headers=headers, stream=True, timeout=HTTP_TIMEOUT) as resp:
            resp.raise_for_status()
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "video" not in content_type and not url.lower().split("?")[0].endswith(".mp4"):
                return None

            content_length = int(resp.headers.get("Content-Length") or 0)
            if content_length and content_length > MAX_VIDEO_BYTES:
                logger.info("Video çok büyük (%d byte), atlanıyor.", content_length)
                return None

            target = output_dir / f"video_{uuid.uuid4().hex[:8]}.mp4"
            total = 0
            with target.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_VIDEO_BYTES:
                        f.close()
                        target.unlink(missing_ok=True)
                        logger.info("Video indirme limiti aşıldı, atlanıyor.")
                        return None
                    f.write(chunk)

            if total < 10_000:
                target.unlink(missing_ok=True)
                return None
            return target
    except Exception as exc:
        logger.warning("Video indirilemedi (%s): %s", url, exc)
        return None


def _download_and_normalize_image(url: str, output_dir: Path) -> Optional[Path]:
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        if len(resp.content) > MAX_IMAGE_BYTES * 3:
            return None

        img = Image.open(io.BytesIO(resp.content))
        width, height = img.size
        # Çok küçük ikon / piksel görselleri ele
        if width < 300 or height < 200:
            logger.info("Görsel çok küçük (%dx%d), atlanıyor.", width, height)
            return None

        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (18, 22, 32))
            if img.mode == "P":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # X için ideal maksimum genişlik
        if width > 1600:
            ratio = 1600 / float(width)
            img = img.resize((1600, int(height * ratio)), Image.Resampling.LANCZOS)

        target = output_dir / f"image_{uuid.uuid4().hex[:8]}.jpg"
        img.save(target, format="JPEG", quality=90, optimize=True)
        return target
    except Exception as exc:
        logger.warning("Görsel indirilemedi (%s): %s", url, exc)
        return None


def generate_news_card(item: NewsItem, output_dir: Path) -> Path:
    """Görseli/videosu olmayan haberler için 1200x675 modern haber kartı üretir."""
    width, height = 1200, 675
    img = Image.new("RGB", (width, height), (12, 18, 32))
    draw = ImageDraw.Draw(img)

    # Yumuşak dikey arka plan gradyanı
    for y in range(height):
        r = int(12 + (22 - 12) * (y / height))
        g = int(18 + (32 - 18) * (y / height))
        b = int(32 + (56 - 32) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Sol kenar vurgu şeridi (kırmızı-turuncu gündem çizgisi)
    draw.rectangle([(0, 0), (18, height)], fill=(230, 57, 70))

    # Üst rozet ("GÜNDEM")
    badge_font = _load_font(24, bold=True)
    brand_font = _load_font(26, bold=True)
    title_font = _load_font(50, bold=True)
    footer_font = _load_font(24, bold=False)

    draw.rounded_rectangle([(72, 64), (242, 114)], radius=8, fill=(230, 57, 70))
    draw.text((100, 75), "GÜNDEM", font=badge_font, fill=(255, 255, 255))
    draw.text((264, 74), BRAND_NAME.upper(), font=brand_font, fill=(180, 196, 220))

    # Ayırıcı çizgi
    draw.line([(72, 146), (width - 72, 146)], fill=(48, 66, 98), width=2)

    # Başlığı satırlara böl
    wrapped = textwrap.wrap(item.title, width=34)[:5]
    y_cursor = 190
    for line in wrapped:
        draw.text((72, y_cursor), line, font=title_font, fill=(248, 250, 252))
        y_cursor += 68

    # Alt bilgi: Kaynak + Tarih
    date_str = item.published_at.astimezone(timezone.utc).strftime("%d.%m.%Y")
    footer_text = f"Kaynak: {item.source}   •   {date_str}"
    draw.line([(72, height - 108), (width - 72, height - 108)], fill=(48, 66, 98), width=2)
    draw.text((72, height - 80), footer_text, font=footer_font, fill=(160, 178, 204))

    target = output_dir / f"card_{uuid.uuid4().hex[:8]}.jpg"
    img.save(target, format="JPEG", quality=92, optimize=True)
    return target


def prepare_media(item: NewsItem) -> PreparedMedia:
    """
    Öncelik sırası:
    1. Haberin orijinal .mp4 videosu
    2. Haberin orijinal yüksek çözünürlüklü görseli
    3. Otomatik oluşturulan şık haber kartı
    """
    TMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    if item.video_url:
        video_path = _download_video(item.video_url, TMP_MEDIA_DIR)
        if video_path:
            logger.info("Orijinal video indirildi: %s", video_path.name)
            return PreparedMedia(path=video_path, media_type="video")

    if item.image_url:
        image_path = _download_and_normalize_image(item.image_url, TMP_MEDIA_DIR)
        if image_path:
            logger.info("Orijinal görsel indirildi: %s", image_path.name)
            return PreparedMedia(path=image_path, media_type="image")

    card_path = generate_news_card(item, TMP_MEDIA_DIR)
    logger.info("Orijinal medya bulunamadı, haber kartı üretildi: %s", card_path.name)
    return PreparedMedia(path=card_path, media_type="image", is_generated_card=True)

import io
import logging
import textwrap
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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


CATEGORY_LABELS = {
    "gundem": "GÜNDEM",
    "ekonomi": "EKONOMİ",
    "spor": "SPOR",
    "teknoloji": "TEKNOLOJİ",
}

CATEGORY_COLORS = {
    "gundem": (230, 57, 70, 245),     # Kırmızı
    "ekonomi": (16, 185, 129, 245),   # Zümrüt Yeşili
    "spor": (249, 115, 22, 245),      # Canlı Turuncu
    "teknoloji": (59, 130, 246, 245), # Elektrik Mavi
}


def _apply_news_overlay(img: Image.Image, item: NewsItem) -> Image.Image:
    """
    Haber fotoğrafını BPT / HABER.EXE tarzı 1200x800 manşetli görsele dönüştürür:
    - Fotoğrafı 1200x800 çerçeveye oran bozmadan doldurur
    - Alt kısma yumuşak koyu gradyan ekler
    - Sol üste kırmızı HABER.EXE + kategori rozeti koyar
    - Alt kısma vurucu beyaz manşet ve kaynak imzası yazar
    """
    width, height = 1200, 800
    base_rgb = ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS)
    # Hafif keskinleştirme: X sıkıştırmasına karşı netlik korur
    base_rgb = base_rgb.filter(ImageFilter.UnsharpMask(radius=1.1, percent=85, threshold=3))
    base = base_rgb.convert("RGBA")

    # Alt yarıya yumuşak siyah-lacivert gradyan
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    fade_start = int(height * 0.42)
    fade_span = height - fade_start
    for y in range(fade_start, height):
        progress = (y - fade_start) / float(fade_span)
        alpha = int(242 * (progress ** 1.35))
        ov_draw.line([(0, y), (width, y)], fill=(8, 12, 22, alpha))

    # Üst sol köşe için hafif gölge bandı (rozet okunurluğu)
    for y in range(0, 120):
        alpha = int(110 * (1.0 - (y / 120.0)))
        ov_draw.line([(0, y), (width, y)], fill=(8, 12, 22, alpha))

    composed = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(composed)

    badge_font = _load_font(24, bold=True)
    cat_font = _load_font(22, bold=True)
    title_font = _load_font(44, bold=True)
    source_font = _load_font(22, bold=False)

    # Sol üst HABER.EXE rozeti
    brand_text = BRAND_NAME.upper()
    cat_text = CATEGORY_LABELS.get(item.category, "GÜNDEM")
    cat_color = CATEGORY_COLORS.get(item.category, (230, 57, 70, 245))

    draw.rounded_rectangle([(40, 34), (242, 82)], radius=8, fill=(230, 57, 70, 245))
    draw.ellipse([(56, 51), (70, 65)], fill=(255, 255, 255, 255))
    draw.text((82, 44), brand_text[:11], font=badge_font, fill=(255, 255, 255, 255))

    # Yanında kategoriye özel renk kodlu rozet
    cat_box_w = max(148, len(cat_text) * 16 + 44)
    draw.rounded_rectangle([(254, 34), (254 + cat_box_w, 82)], radius=8, fill=cat_color)
    draw.text((274, 46), cat_text, font=cat_font, fill=(255, 255, 255, 255))

    # Başlığı 2-3 satıra sar
    wrapped = textwrap.wrap(item.title.strip(), width=36)[:3]
    if len(wrapped) == 3 and len(item.title.strip()) > sum(len(l) for l in wrapped) + 3:
        wrapped[-1] = wrapped[-1].rstrip(".,;:") + "…"

    line_height = 56
    block_height = len(wrapped) * line_height
    y_start = height - block_height - 76

    # Başlığın solunda kategori renginde dikey vurgu şeridi
    draw.rounded_rectangle(
        [(40, y_start + 4), (50, y_start + block_height - 4)],
        radius=4,
        fill=cat_color,
    )

    # Beyaz manşet satırları (hafif gölgeli)
    y_cursor = y_start
    for line in wrapped:
        draw.text((70, y_cursor + 2), line, font=title_font, fill=(0, 0, 0, 180))
        draw.text((68, y_cursor), line, font=title_font, fill=(255, 255, 255, 255))
        y_cursor += line_height

    # Alt kaynak imzası
    draw.text(
        (68, height - 48),
        f"Kaynak: {item.source}  •  @HaberExe",
        font=source_font,
        fill=(186, 198, 218, 230),
    )

    return composed.convert("RGB")


MIN_HD_WIDTH = 720
MIN_HD_HEIGHT = 400


def _fetch_pil_image(url: str) -> Optional[Image.Image]:
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        if len(resp.content) > MAX_IMAGE_BYTES * 3:
            return None
        img = Image.open(io.BytesIO(resp.content))
        img.load()
        return img
    except Exception as exc:
        logger.debug("Görsel adayı indirilemedi (%s): %s", url, exc)
        return None


def _download_best_image(urls: list[str], output_dir: Path, item: NewsItem) -> Optional[Path]:
    """
    Aday görseller arasından piksellenme olmaması için en az 720x400 çözünürlükte
    en yüksek kaliteli fotoğrafı seçer; HD (>=1000px) bulduğunda hemen kullanır.
    """
    best_img: Optional[Image.Image] = None
    best_pixels = 0

    for url in urls[:6]:
        img = _fetch_pil_image(url)
        if img is None:
            continue
        w, h = img.size
        if w < MIN_HD_WIDTH or h < MIN_HD_HEIGHT:
            logger.info("Düşük çözünürlüklü görsel elendi (%dx%d < %dx%d): %s", w, h, MIN_HD_WIDTH, MIN_HD_HEIGHT, url)
            continue

        pixels = w * h
        if pixels > best_pixels:
            best_img = img
            best_pixels = pixels
        if w >= 1000 and h >= 550:
            logger.info("Yüksek çözünürlüklü (HD) görsel seçildi (%dx%d)", w, h)
            break

    if best_img is None:
        return None

    if best_img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", best_img.size, (18, 22, 32))
        if best_img.mode == "P":
            best_img = best_img.convert("RGBA")
        bg.paste(best_img, mask=best_img.split()[-1] if "A" in best_img.mode else None)
        best_img = bg
    elif best_img.mode != "RGB":
        best_img = best_img.convert("RGB")

    branded = _apply_news_overlay(best_img, item)
    target = output_dir / f"image_{uuid.uuid4().hex[:8]}.jpg"
    # subsampling=0 (4:4:4) kırmızı rozet ve beyaz metin çevresindeki JPEG piksellenmesini engeller
    branded.save(target, format="JPEG", quality=95, subsampling=0, optimize=True)
    return target


def generate_news_card(item: NewsItem, output_dir: Path) -> Path:
    """HD fotoğrafı olmayan haberler için kategori renk kodlu 1200x800 modern haber kartı üretir."""
    width, height = 1200, 800
    img = Image.new("RGBA", (width, height), (8, 12, 22, 255))
    draw = ImageDraw.Draw(img)

    cat_text = CATEGORY_LABELS.get(item.category, "GÜNDEM")
    cat_color = CATEGORY_COLORS.get(item.category, (230, 57, 70, 245))

    # Koyu stüdyo gradyanı
    for y in range(height):
        t = y / float(height)
        r = int(8 + 10 * t)
        g = int(12 + 12 * t)
        b = int(22 + 22 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # Sağ üstte kategori renginde hafif ambiyans parıltısı
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for rad in range(420, 30, -15):
        alpha = int(18 * (1.0 - rad / 420.0))
        gdraw.ellipse([(1020 - rad, 140 - rad), (1020 + rad, 140 + rad)], fill=(cat_color[0], cat_color[1], cat_color[2], alpha))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # Sol kenar kategori renginde vurgu şeridi
    draw.rectangle([(0, 0), (14, height)], fill=cat_color)

    badge_font = _load_font(24, bold=True)
    cat_font = _load_font(22, bold=True)
    title_font = _load_font(52, bold=True)
    footer_font = _load_font(24, bold=False)

    # Üst rozetler
    draw.rounded_rectangle([(68, 58), (270, 106)], radius=8, fill=(230, 57, 70, 255))
    draw.ellipse([(84, 75), (98, 89)], fill=(255, 255, 255, 255))
    draw.text((110, 68), BRAND_NAME.upper()[:11], font=badge_font, fill=(255, 255, 255, 255))

    cat_box_w = max(148, len(cat_text) * 16 + 44)
    draw.rounded_rectangle([(284, 58), (284 + cat_box_w, 106)], radius=8, fill=cat_color)
    draw.text((304, 70), cat_text, font=cat_font, fill=(255, 255, 255, 255))

    draw.line([(68, 146), (width - 68, 146)], fill=(44, 60, 92, 200), width=2)

    # Manşet (dikey ortalanmış, max 4 satır)
    wrapped = textwrap.wrap(item.title.strip(), width=33)[:4]
    line_h = 68
    block_h = len(wrapped) * line_h
    y_cursor = 180 + max(0, (440 - block_h) // 2)
    for line in wrapped:
        draw.text((68, y_cursor), line, font=title_font, fill=(248, 250, 252, 255))
        y_cursor += line_h

    # Alt bilgi
    date_str = item.published_at.astimezone(timezone.utc).strftime("%d.%m.%Y")
    draw.line([(68, height - 104), (width - 68, height - 104)], fill=(44, 60, 92, 200), width=2)
    draw.text((68, height - 74), f"Kaynak: {item.source}  •  {date_str}  •  @HaberExe", font=footer_font, fill=(166, 184, 212, 240))

    target = output_dir / f"card_{uuid.uuid4().hex[:8]}.jpg"
    img.convert("RGB").save(target, format="JPEG", quality=95, subsampling=0, optimize=True)
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

    candidate_urls = list(item.image_candidates) if item.image_candidates else []
    if item.image_url and item.image_url not in candidate_urls:
        candidate_urls.append(item.image_url)

    if candidate_urls:
        image_path = _download_best_image(candidate_urls, TMP_MEDIA_DIR, item)
        if image_path:
            logger.info("HD manşetli haber görseli hazırlandı: %s", image_path.name)
            return PreparedMedia(path=image_path, media_type="image")

    card_path = generate_news_card(item, TMP_MEDIA_DIR)
    logger.info("Orijinal medya bulunamadı, haber kartı üretildi: %s", card_path.name)
    return PreparedMedia(path=card_path, media_type="image", is_generated_card=True)

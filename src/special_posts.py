"""
Özel Günlük Formatlar:
1. Sabah "📊 PİYASA AÇILIŞI" (Dolar, Euro, Gram Altın, Bitcoin) — Hafta içi 09:00 TR
2. Akşam "🌙 GÜNÜN ÖZETİ" (Günün en önemli 5 gelişmesi) — Her akşam 23:00 TR
"""

import logging
import re
import textwrap
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw

from config import BRAND_NAME, DATA_DIR, HTTP_TIMEOUT, TMP_MEDIA_DIR, USER_AGENT
from src.media_handler import PreparedMedia, _load_font

logger = logging.getLogger(__name__)

HEALTH_REPORT_FILE = DATA_DIR / "health_report.md"

TR_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}


def _tr_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=3)


def _tr_date_label(dt: Optional[datetime] = None) -> str:
    now = dt or _tr_now()
    return f"{now.day} {TR_MONTHS[now.month]} {now.year}"


def _fmt_tr_number(value: float, decimals: int = 2) -> str:
    formatted = f"{value:,.{decimals}f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


# ---------------------------------------------------------------------------
# 1. SABAH PİYASA AÇILIŞI
# ---------------------------------------------------------------------------

def _fetch_market_rates() -> dict[str, str]:
    """Ücretsiz, anahtarsız açık kaynaklardan anlık Dolar, Euro, Gram Altın ve Bitcoin çeker."""
    headers = {"User-Agent": USER_AGENT}
    rates: dict[str, str] = {}
    usd_try: Optional[float] = None
    eur_try: Optional[float] = None

    # 1) Dolar & Euro (open.er-api.com -> yedek frankfurter.app)
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", headers=headers, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("rates", {})
        if data.get("TRY"):
            usd_try = float(data["TRY"])
            rates["DOLAR / TL"] = f"{_fmt_tr_number(usd_try, 2)} ₺"
        if usd_try and data.get("EUR"):
            eur_try = usd_try / float(data["EUR"])
            rates["EURO / TL"] = f"{_fmt_tr_number(eur_try, 2)} ₺"
    except Exception as exc:
        logger.warning("open.er-api.com alınamadı: %s", exc)

    if not usd_try:
        try:
            resp = requests.get(
                "https://api.frankfurter.app/latest?from=USD&to=TRY,EUR",
                headers=headers,
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json().get("rates", {})
            if data.get("TRY"):
                usd_try = float(data["TRY"])
                rates["DOLAR / TL"] = f"{_fmt_tr_number(usd_try, 2)} ₺"
            if usd_try and data.get("EUR"):
                eur_try = usd_try / float(data["EUR"])
                rates["EURO / TL"] = f"{_fmt_tr_number(eur_try, 2)} ₺"
        except Exception as exc:
            logger.warning("frankfurter.app alınamadı: %s", exc)

    # 2) Gram Altın TL (Ons Altın USD / 31.1034768 * USD/TRY)
    if usd_try:
        try:
            resp = requests.get("https://api.gold-api.com/price/XAU", headers=headers, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            xau_usd = float(resp.json().get("price") or 0)
            if xau_usd > 500:
                gram_try = (xau_usd / 31.1034768) * usd_try
                rates["GRAM ALTIN"] = f"{_fmt_tr_number(gram_try, 0)} ₺"
        except Exception as exc:
            logger.warning("gold-api.com alınamadı: %s", exc)

    # 3) Bitcoin USD (CoinGecko)
    try:
        resp = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            headers=headers,
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        btc_usd = float(resp.json().get("bitcoin", {}).get("usd") or 0)
        if btc_usd > 1000:
            rates["BITCOIN"] = f"${_fmt_tr_number(btc_usd, 0)}"
    except Exception as exc:
        logger.warning("CoinGecko alınamadı: %s", exc)

    return rates


def _generate_market_card(rates: dict[str, str], date_label: str) -> Path:
    """1200x800 modern koyu zümrüt temalı HABER.EXE Piyasa Açılışı kartı üretir."""
    TMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    width, height = 1200, 800
    img = Image.new("RGB", (width, height), (10, 18, 28))
    draw = ImageDraw.Draw(img)

    # Koyu lacivert -> koyu zümrüt arka plan gradyanı
    for y in range(height):
        t = y / float(height)
        r = int(10 + (12 - 10) * t)
        g = int(18 + (34 - 18) * t)
        b = int(30 + (40 - 30) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Sol kenar zümrüt vurgu şeridi
    draw.rectangle([(0, 0), (16, height)], fill=(16, 185, 129))

    badge_font = _load_font(24, bold=True)
    sub_badge_font = _load_font(22, bold=True)
    date_font = _load_font(26, bold=False)
    heading_font = _load_font(52, bold=True)
    label_font = _load_font(26, bold=True)
    value_font = _load_font(62, bold=True)
    footer_font = _load_font(22, bold=False)

    # Üst rozetler
    draw.rounded_rectangle([(56, 44), (256, 92)], radius=8, fill=(230, 57, 70))
    draw.ellipse([(72, 61), (86, 75)], fill=(255, 255, 255))
    draw.text((98, 54), BRAND_NAME.upper()[:11], font=badge_font, fill=(255, 255, 255))

    draw.rounded_rectangle([(272, 44), (506, 92)], radius=8, fill=(16, 185, 129))
    draw.text((294, 56), "PİYASA AÇILIŞI", font=sub_badge_font, fill=(10, 18, 28))

    draw.text((width - 310, 54), date_label, font=date_font, fill=(180, 198, 218))

    # Ana başlık
    draw.text((56, 126), "Günün Piyasa Verileri", font=heading_font, fill=(248, 250, 252))
    draw.line([(56, 200), (width - 56, 200)], fill=(36, 62, 78), width=2)

    # 2x2 Metrik Kutuları
    items = list(rates.items())[:4]
    box_w, box_h = 524, 212
    gap_x, gap_y = 40, 32
    start_x, start_y = 56, 232

    accent_colors = [
        (16, 185, 129),  # Dolar
        (59, 130, 246),  # Euro
        (245, 158, 11),  # Gram Altın
        (249, 115, 22),  # Bitcoin
    ]

    for idx, (label, val) in enumerate(items):
        col = idx % 2
        row = idx // 2
        x0 = start_x + col * (box_w + gap_x)
        y0 = start_y + row * (box_h + gap_y)
        x1 = x0 + box_w
        y1 = y0 + box_h
        accent = accent_colors[idx % len(accent_colors)]

        draw.rounded_rectangle([(x0, y0), (x1, y1)], radius=16, fill=(18, 30, 44), outline=(42, 72, 92), width=2)
        draw.rounded_rectangle([(x0, y0 + 24), (x0 + 8, y1 - 24)], radius=4, fill=accent)
        draw.text((x0 + 34, y0 + 34), label, font=label_font, fill=(168, 188, 210))
        draw.text((x0 + 34, y0 + 96), val, font=value_font, fill=(255, 255, 255))

    # Alt bilgi
    draw.line([(56, height - 86), (width - 56, height - 86)], fill=(36, 62, 78), width=2)
    draw.text(
        (56, height - 60),
        "Anlık piyasa verilerinden derlenmiştir  •  @HaberExe",
        font=footer_font,
        fill=(152, 174, 198),
    )

    target = TMP_MEDIA_DIR / f"market_{uuid.uuid4().hex[:8]}.jpg"
    img.save(target, format="JPEG", quality=95, subsampling=0, optimize=True)
    return target


def build_market_post() -> Optional[tuple[str, PreparedMedia]]:
    """Sabah Piyasa Açılışı gönderisini (metin + HD kart) hazırlar."""
    rates = _fetch_market_rates()
    if len(rates) < 2:
        logger.warning("Yeterli piyasa verisi alınamadı (%d öğe), normal habere geçiliyor.", len(rates))
        return None

    date_label = _tr_date_label()
    short_date = f"{_tr_now().day} {TR_MONTHS[_tr_now().month]}"

    lines = [f"📊 PİYASA AÇILIŞI | {short_date}", ""]
    emoji_map = {
        "DOLAR / TL": "💵 Dolar:",
        "EURO / TL": "💶 Euro:",
        "GRAM ALTIN": "🥇 Gram Altın:",
        "BITCOIN": "₿ Bitcoin:",
    }
    for k, v in rates.items():
        lines.append(f"{emoji_map.get(k, k)} {v}")

    lines.append("")
    lines.append("Bugün piyasalardan beklentiniz ne?")
    lines.append("")
    lines.append("#Dolar #Altın #Ekonomi")
    lines.append("— HABER.EXE")

    tweet_text = "\n".join(lines)
    card_path = _generate_market_card(rates, date_label)
    return tweet_text, PreparedMedia(path=card_path, media_type="image", is_generated_card=True)


# ---------------------------------------------------------------------------
# 2. AKŞAM GÜNÜN ÖZETİ
# ---------------------------------------------------------------------------

def _collect_todays_headlines(fallback_titles: list[str]) -> list[str]:
    """data/health_report.md içinden bugünün (TR tarihi) başlıklarını toplar."""
    today_prefix = _tr_now().strftime("%d.%m.%Y")
    todays: list[str] = []

    if HEALTH_REPORT_FILE.exists():
        for line in HEALTH_REPORT_FILE.read_text(encoding="utf-8").splitlines():
            if not line.startswith(f"| {today_prefix}"):
                continue
            if "Yayınlandı" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            raw_detail = parts[3]
            # "[ekonomi] Başlık..." -> "Başlık..."
            clean_title = re.sub(r"^\[[^\]]+\]\s*", "", raw_detail).strip()
            if clean_title and "PİYASA AÇILIŞI" not in clean_title.upper() and "GÜNÜN ÖZETİ" not in clean_title.upper():
                if clean_title not in todays:
                    todays.append(clean_title)

    # Eğer bugün 3'ten az haber varsa posted_titles sonundan tamamla
    if len(todays) < 3 and fallback_titles:
        for t in reversed(fallback_titles):
            if t not in todays:
                todays.append(t)
            if len(todays) >= 5:
                break

    return todays[:5]


def _generate_digest_card(headlines: list[str], date_label: str) -> Path:
    """1200x800 gece lacivert temalı HABER.EXE Günün Özeti kartı üretir."""
    TMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    width, height = 1200, 800
    img = Image.new("RGB", (width, height), (10, 14, 28))
    draw = ImageDraw.Draw(img)

    # Gece lacivert -> koyu indigo gradyan
    for y in range(height):
        t = y / float(height)
        r = int(10 + (20 - 10) * t)
        g = int(14 + (24 - 14) * t)
        b = int(28 + (52 - 28) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Sol kenar altın-amber vurgu şeridi
    draw.rectangle([(0, 0), (16, height)], fill=(245, 158, 11))

    badge_font = _load_font(24, bold=True)
    sub_badge_font = _load_font(22, bold=True)
    date_font = _load_font(26, bold=False)
    heading_font = _load_font(46, bold=True)
    num_font = _load_font(26, bold=True)
    item_font = _load_font(29, bold=True)
    footer_font = _load_font(22, bold=False)

    # Üst rozetler
    draw.rounded_rectangle([(56, 40), (256, 88)], radius=8, fill=(230, 57, 70))
    draw.ellipse([(72, 57), (86, 71)], fill=(255, 255, 255))
    draw.text((98, 50), BRAND_NAME.upper()[:11], font=badge_font, fill=(255, 255, 255))

    draw.rounded_rectangle([(272, 40), (484, 88)], radius=8, fill=(245, 158, 11))
    draw.text((294, 52), "GÜNÜN ÖZETİ", font=sub_badge_font, fill=(14, 18, 30))

    draw.text((width - 310, 50), date_label, font=date_font, fill=(182, 196, 222))

    # Başlık
    draw.text((56, 112), "Bugün Öne Çıkan Başlıklar", font=heading_font, fill=(248, 250, 252))
    draw.line([(56, 178), (width - 56, 178)], fill=(44, 62, 98), width=2)

    # 1..5 Maddeler
    y_cursor = 204
    row_step = 100
    for idx, title in enumerate(headlines[:5], start=1):
        # Numara dairesi
        draw.ellipse([(56, y_cursor + 4), (104, y_cursor + 52)], fill=(230, 57, 70))
        draw.text((73, y_cursor + 12), str(idx), font=num_font, fill=(255, 255, 255))

        wrapped = textwrap.wrap(title.strip(), width=54)[:2]
        if len(wrapped) == 2 and len(title.strip()) > sum(len(x) for x in wrapped) + 4:
            wrapped[-1] = wrapped[-1].rstrip(".,;:") + "…"

        text_y = y_cursor + (12 if len(wrapped) == 1 else 0)
        for line in wrapped:
            draw.text((126, text_y), line, font=item_font, fill=(242, 246, 252))
            text_y += 38

        if idx < len(headlines[:5]):
            draw.line([(126, y_cursor + 84), (width - 56, y_cursor + 84)], fill=(30, 44, 72), width=1)
        y_cursor += row_step

    # Alt bilgi
    draw.line([(56, height - 76), (width - 56, height - 76)], fill=(44, 62, 98), width=2)
    draw.text(
        (56, height - 52),
        "Günü tek karede yakala  •  @HaberExe",
        font=footer_font,
        fill=(160, 178, 206),
    )

    target = TMP_MEDIA_DIR / f"digest_{uuid.uuid4().hex[:8]}.jpg"
    img.save(target, format="JPEG", quality=95, subsampling=0, optimize=True)
    return target


def _short_bullet(title: str, max_len: int = 44) -> str:
    clean = title.strip()
    if len(clean) <= max_len:
        return clean
    cut = clean[: max_len - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def build_daily_digest_post(fallback_titles: list[str]) -> Optional[tuple[str, PreparedMedia]]:
    """Akşam Günün Özeti gönderisini (maddeli tweet + HD özet kartı) hazırlar."""
    headlines = _collect_todays_headlines(fallback_titles)
    if len(headlines) < 3:
        logger.warning("Günün özeti için yeterli başlık yok (%d), normal habere geçiliyor.", len(headlines))
        return None

    date_label = _tr_date_label()
    short_date = f"{_tr_now().day} {TR_MONTHS[_tr_now().month]}"

    header = f"🌙 GÜNÜN ÖZETİ | {short_date}\n\n"
    footer = "\n\nGünün en önemli gelişmesi sizce hangisiydi?\n\n#GününÖzeti #SonDakika\n— HABER.EXE"
    budget = 272 - len(header) - len(footer)

    bullets: list[str] = []
    for h in headlines[:4]:
        item_line = f"• {_short_bullet(h, max_len=42)}"
        candidate = "\n".join(bullets + [item_line])
        if len(candidate) <= budget:
            bullets.append(item_line)

    tweet_text = f"{header}" + "\n".join(bullets) + footer
    card_path = _generate_digest_card(headlines, date_label)
    return tweet_text, PreparedMedia(path=card_path, media_type="image", is_generated_card=True)

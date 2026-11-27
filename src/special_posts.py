"""
Özel Günlük Formatlar:
1. Sabah "📊 PİYASA AÇILIŞI" (Dolar, Euro, Gram Altın, Bitcoin) — Hafta içi 09:00 TR
2. Akşam "🌙 GÜNÜN ÖZETİ" (Günün en önemli 5 gelişmesi) — Her akşam 23:00 TR
"""

import logging
import re
import textwrap
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from google import genai
from PIL import Image, ImageDraw

from config import (
    BRAND_NAME,
    DATA_DIR,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    HTTP_TIMEOUT,
    TMP_MEDIA_DIR,
    USER_AGENT,
)
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
    """
    1200x800 modern dergi / Bento split tasarımlı HABER.EXE Günün Özeti kartı:
    - Sol sütun: Koyu antrasit zemin + yumuşak stüdyo parıltısı + dev tipografik tarih & GÜNÜN ÖZETİ başlığı
    - Sağ sütun: 5 adet ayrı yuvarlatılmış koyu cam (glass) haber kartı + renkli 01..05 rozetleri
    """
    TMP_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    width, height = 1200, 800
    img = Image.new("RGBA", (width, height), (8, 12, 20, 255))
    draw = ImageDraw.Draw(img)

    # 1. Arka plan: Derin obsidian + sol üst hafif kırmızı & sağ alt hafif safir ambiyans parıltısı
    for y in range(height):
        t = y / float(height)
        r = int(8 + 6 * t)
        g = int(12 + 8 * t)
        b = int(20 + 16 * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    # Sol üst yumuşak kırmızı stüdyo ışığı
    for rad in range(360, 20, -12):
        alpha = int(16 * (1.0 - rad / 360.0))
        gdraw.ellipse([(140 - rad, 140 - rad), (140 + rad, 140 + rad)], fill=(230, 57, 70, alpha))
    # Sağ alt yumuşak mavi-indigo ışığı
    for rad in range(420, 20, -14):
        alpha = int(14 * (1.0 - rad / 420.0))
        gdraw.ellipse([(1060 - rad, 720 - rad), (1060 + rad, 720 + rad)], fill=(59, 130, 246, alpha))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # Sol sütunda çok hafif mimari nokta dokusu (dot grid)
    for gx in range(36, 380, 26):
        for gy in range(36, height - 36, 26):
            draw.point((gx, gy), fill=(72, 92, 126, 75))

    # Sol kenar ince vurgu çizgisi
    draw.rectangle([(0, 0), (10, height)], fill=(230, 57, 70, 255))

    # Sol & sağ sütun ayırıcı ince dikey çizgi
    draw.line([(394, 48), (394, height - 48)], fill=(38, 52, 78, 180), width=2)

    # Fontlar
    badge_font = _load_font(22, bold=True)
    hero_font = _load_font(66, bold=True)
    day_font = _load_font(86, bold=True)
    month_font = _load_font(26, bold=True)
    meta_font = _load_font(20, bold=False)
    num_font = _load_font(24, bold=True)
    item_font = _load_font(26, bold=True)

    # --- SOL SÜTUN (Dergi Kapağı / Masthead) ---
    draw.rounded_rectangle([(48, 54), (236, 98)], radius=8, fill=(230, 57, 70, 255))
    draw.ellipse([(64, 70), (76, 82)], fill=(255, 255, 255, 255))
    draw.text((88, 63), BRAND_NAME.upper()[:11], font=badge_font, fill=(255, 255, 255, 255))

    draw.text((48, 146), "GÜNÜN", font=hero_font, fill=(248, 250, 252, 255))
    draw.text((48, 218), "ÖZETİ", font=hero_font, fill=(230, 57, 70, 255))

    # İnce vurgu çubuğu
    draw.rounded_rectangle([(48, 308), (156, 316)], radius=4, fill=(245, 158, 11, 255))

    # Büyük editoryal tarih bloğu ("28" + "KASIM 2026")
    date_parts = date_label.split()
    day_str = date_parts[0] if date_parts else ""
    rest_str = " ".join(date_parts[1:]).upper() if len(date_parts) > 1 else date_label.upper()
    draw.text((48, 356), day_str, font=day_font, fill=(255, 255, 255, 255))
    draw.text((48, 456), rest_str, font=month_font, fill=(168, 186, 214, 255))

    # Sol alt özet rozeti + hesap imzası
    shown = headlines[:5]
    draw.rounded_rectangle(
        [(48, 560), (324, 602)],
        radius=10,
        fill=(18, 26, 42, 230),
        outline=(44, 62, 96, 220),
        width=1,
    )
    draw.text((66, 570), f"{len(shown)} ÖNE ÇIKAN GELİŞME", font=meta_font, fill=(226, 232, 240, 255))

    draw.text((48, height - 92), "Günü tek karede yakala", font=meta_font, fill=(140, 158, 186, 230))
    draw.text((48, height - 62), "@HaberExe", font=badge_font, fill=(248, 250, 252, 255))

    # --- SAĞ SÜTUN (5 Ayrı Glassmorphic Bento Haber Kartı) ---
    card_x0 = 428
    card_x1 = width - 48
    card_count = max(1, len(shown))
    top_pad = 54
    bottom_pad = 54
    gap = 18
    avail_h = height - top_pad - bottom_pad - gap * (card_count - 1)
    card_h = min(132, avail_h // card_count)
    # Kart bloğunu dikey ortala
    total_block_h = card_count * card_h + (card_count - 1) * gap
    y_cursor = (height - total_block_h) // 2

    pill_colors = [
        (230, 57, 70, 255),   # 01 Kırmızı
        (16, 185, 129, 255),  # 02 Zümrüt
        (59, 130, 246, 255),  # 03 Elektrik Mavi
        (249, 115, 22, 255),  # 04 Turuncu
        (245, 158, 11, 255),  # 05 Altın
    ]

    for idx, title in enumerate(shown, start=1):
        accent = pill_colors[(idx - 1) % len(pill_colors)]
        y0 = y_cursor
        y1 = y0 + card_h

        # Koyu cam kart yüzeyi + ince kenarlık
        draw.rounded_rectangle(
            [(card_x0, y0), (card_x1, y1)],
            radius=16,
            fill=(16, 24, 39, 238),
            outline=(38, 54, 82, 220),
            width=2,
        )
        # Kartın sol kenarında ince renkli dikey çizgi
        draw.rounded_rectangle(
            [(card_x0, y0 + 18), (card_x0 + 6, y1 - 18)],
            radius=3,
            fill=accent,
        )
        # Numara rozeti ("01".."05")
        badge_y0 = y0 + (card_h - 46) // 2
        draw.rounded_rectangle(
            [(card_x0 + 24, badge_y0), (card_x0 + 78, badge_y0 + 46)],
            radius=10,
            fill=(accent[0], accent[1], accent[2], 38),
            outline=accent,
            width=2,
        )
        draw.text((card_x0 + 36, badge_y0 + 10), f"0{idx}", font=num_font, fill=(255, 255, 255, 255))

        # Başlığı 2 satıra sar ve dikey ortala (sağda rahat nefes payı bırak)
        wrapped = textwrap.wrap(title.strip(), width=38)[:2]
        line_h = 34
        text_block_h = len(wrapped) * line_h
        ty = y0 + (card_h - text_block_h) // 2 - 2
        for line in wrapped:
            draw.text((card_x0 + 98, ty), line, font=item_font, fill=(244, 247, 252, 255))
            ty += line_h

        y_cursor += card_h + gap

    target = TMP_MEDIA_DIR / f"digest_{uuid.uuid4().hex[:8]}.jpg"
    img.convert("RGB").save(target, format="JPEG", quality=95, subsampling=0, optimize=True)
    return target


def _condense_headlines_with_ai(headlines: list[str], max_chars_each: int = 44) -> list[str]:
    """
    Başlıkları üç nokta (...) ile kesmek yerine Gemini ile her birini
    eksiksiz, anlamlı ve kısa (en fazla ~42 karakter) tek satırlık manşetlere dönüştürür.
    """
    if not GEMINI_API_KEY:
        return []

    client = genai.Client(api_key=GEMINI_API_KEY)
    numbered = "\n".join(f"{i}. {h}" for i, h in enumerate(headlines[:5], start=1))
    prompt = (
        f"Aşağıdaki {len(headlines[:5])} haber başlığının her birini, anlamını eksiksiz koruyarak "
        f"en fazla {max_chars_each - 4} karakterlik çok kısa ve tam bir Türkçe özet cümlesine çevir.\n"
        "Kurallar:\n"
        "- Her satır TAM ve anlamlı bir ifade olsun; ASLA '...' veya yarım cümle bırakma.\n"
        "- Sadece maddeleri her satırda bir tane olacak şekilde, başında numara veya tire olmadan yaz.\n"
        "- Bilgi uydurma.\n\n"
        f"{numbered}"
    )

    candidate_models = list(
        dict.fromkeys([GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-4-hydrogen", "gemma-4-31b-it"])
    )
    for model_name in candidate_models:
        result_box: dict[str, object] = {}

        def _call(m_name: str = model_name, box: dict[str, object] = result_box) -> None:
            try:
                box["resp"] = client.interactions.create(
                    model=m_name,
                    input=prompt,
                    store=False,
                    timeout=15.0,
                )
            except Exception as exc:
                box["err"] = exc

        worker = threading.Thread(target=_call, daemon=True)
        worker.start()
        worker.join(timeout=20.0)

        if worker.is_alive() or "err" in result_box:
            continue

        resp = result_box.get("resp")
        text = getattr(resp, "output_text", None) or ""
        if not text.strip():
            continue

        parsed: list[str] = []
        for raw_line in text.strip().splitlines():
            line = re.sub(r"^[\s\d\.\-\•\*]+", "", raw_line).strip().strip('"\'')
            line = line.rstrip("….")
            if 10 <= len(line) <= max_chars_each:
                parsed.append(line)
        if len(parsed) >= 3:
            return parsed[:5]

    return []


def build_daily_digest_post(fallback_titles: list[str]) -> Optional[tuple[str, PreparedMedia]]:
    """Akşam Günün Özeti gönderisini (üç noktasız tam maddeler + HD özet kartı) hazırlar."""
    headlines = _collect_todays_headlines(fallback_titles)
    if len(headlines) < 3:
        logger.warning("Günün özeti için yeterli başlık yok (%d), normal habere geçiliyor.", len(headlines))
        return None

    date_label = _tr_date_label()
    short_date = f"{_tr_now().day} {TR_MONTHS[_tr_now().month]}"

    # Gemini ile her başlığı üç noktasız, tam ve kısa özet satırına dönüştür
    short_headlines = _condense_headlines_with_ai(headlines, max_chars_each=46)
    card_headlines = short_headlines if len(short_headlines) >= 4 else headlines

    header = f"🌙 GÜNÜN ÖZETİ | {short_date}\n\n"
    footer = "\n\nGünün en önemli gelişmesi hangisiydi?\n\n#GününÖzeti #SonDakika\n— HABER.EXE"
    budget = 272 - len(header) - len(footer)

    # Sadece TAM sığan maddeleri ekle (ASLA '...' ile yarım bırakma)
    source_for_tweet = short_headlines if short_headlines else sorted(headlines, key=len)
    bullets: list[str] = []
    for h in source_for_tweet[:4]:
        item_line = f"• {h.strip()}"
        candidate = "\n".join(bullets + [item_line])
        if len(candidate) <= budget:
            bullets.append(item_line)

    if not bullets:
        bullets.append(f"• {headlines[0].strip()[:budget - 2]}")

    tweet_text = f"{header}" + "\n".join(bullets) + footer
    card_path = _generate_digest_card(card_headlines, date_label)
    return tweet_text, PreparedMedia(path=card_path, media_type="image", is_generated_card=True)

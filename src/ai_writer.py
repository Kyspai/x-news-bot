import logging
import re

from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL, INCLUDE_SOURCE_LINK
from src.news_fetcher import NewsItem

logger = logging.getLogger(__name__)

# X her URL'yi 23 karakter (t.co) olarak sayar; güvenlik payıyla 240 karakter hedefleyelim.
MAX_BODY_CHARS_WITH_LINK = 240
MAX_BODY_CHARS_NO_LINK = 270

SYSTEM_INSTRUCTION = """Sen profesyonel, tarafsız ve akıcı Türkçe yazan bir dijital haber editörüsün.
Verilen haberi X (Twitter) platformu için tek bir gönderi olarak yeniden yazacaksın.

Kurallar:
- Sadece verilen haber bilgisine sadık kal, asla bilgi uydurma.
- Kısa, net, merak uyandıran ama tık tuzağı (clickbait) olmayan haber dili kullan.
- En fazla 1-2 adet ilgili ve ölçülü hashtag ekle (ör. #SonDakika #Gündem #Ekonomi).
- Başında uygun tek bir haber emojisi kullanabilirsin (ör. 🔴, 📰, ⚡, 🌍).
- URL veya link ekleme (link sistem tarafından ayrıca eklenecek).
- Çıktı SADECE tweet metni olsun; tırnak işareti, açıklama veya alternatif seçenek yazma.
- Uzunluk kesinlikle 230 karakteri geçmesin."""


def _fallback_tweet(item: NewsItem, max_chars: int) -> str:
    prefix = "📰 "
    suffix = f" ({item.source}) #Gündem"
    available = max_chars - len(prefix) - len(suffix)
    title = item.title.strip()
    if len(title) > available:
        title = title[: available - 1].rstrip() + "…"
    return f"{prefix}{title}{suffix}"


def _strip_urls(text: str) -> str:
    """X'in linkli gönderi ($0.20) ücretine takılmamak için olası URL'leri temizler."""
    return re.sub(r"https?://\S+|www\.\S+", "", text).strip()


def _enforce_length(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip()).strip('"\'')
    if not INCLUDE_SOURCE_LINK:
        cleaned = _strip_urls(cleaned)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def compose_tweet(item: NewsItem) -> str:
    """Gemini API ile haber metnini X formatına dönüştürür; API yoksa şablon kullanır."""
    source_footer = f"\n\n📰 Kaynak: {item.source}"
    if INCLUDE_SOURCE_LINK:
        max_body = MAX_BODY_CHARS_WITH_LINK
    else:
        max_body = MAX_BODY_CHARS_NO_LINK - len(source_footer)

    body = ""
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = (
                f"Kaynak: {item.source}\n"
                f"Başlık: {item.title}\n"
                f"Özet: {item.summary}\n"
                f"Detay: {item.article_text[:900]}\n\n"
                f"Yukarıdaki haberi en fazla {max_body - 10} karakter olacak şekilde "
                f"tek bir X gönderisi olarak yaz. URL veya alan adı ekleme."
            )
            interaction = client.interactions.create(
                model=GEMINI_MODEL,
                system_instruction=SYSTEM_INSTRUCTION,
                input=prompt,
                store=False,
            )
            if interaction.output_text:
                body = _enforce_length(interaction.output_text, max_body)
        except Exception as exc:
            logger.warning("Gemini API hatası, şablona geçiliyor: %s", exc)
    else:
        logger.info("GEMINI_API_KEY tanımlı değil, standart haber şablonu kullanılıyor.")

    if not body:
        body = _fallback_tweet(item, max_body)

    if INCLUDE_SOURCE_LINK:
        return f"{body}\n{item.url}"
    if item.source.lower() not in body.lower():
        return f"{body}{source_footer}"
    return body

import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL, INCLUDE_SOURCE_LINK
from src.news_fetcher import NewsItem

logger = logging.getLogger(__name__)

# X her URL'yi 23 karakter (t.co) olarak sayar; güvenlik payıyla 240 karakter hedefleyelim.
MAX_BODY_CHARS_WITH_LINK = 240
MAX_BODY_CHARS_NO_LINK = 270

SYSTEM_INSTRUCTION = """Sen Türkiye'nin en yüksek etkileşim alan, güvenilir ve hızlı dijital haber sayfası (HABER.EXE) için yazan kıdemli bir X (Twitter) editörüsün.
Verilen haberi, sadece yazı (fotoğrafsız) olarak X akışında yüksek okunma, yorum ve retweet alacak net, boşluklu ve tarafsız tek bir gönderiye dönüştüreceksin.

Format ve Kurallar:
1. İlk satır: Tek başına vurucu, kısa bir manşet olsun ve konuya uygun tek bir emoji ile başlasın (ör. 🚨 ..., 📊 ..., ⚡ ..., ⚽ ..., 🤖 ...).
2. Bir boş satır bırak, ardından 1-2 cümlelik net ve somut özet yaz (haber metnindeki rakam, oran, tarih veya kritik kararı mutlaka öne çıkar; asla bilgi uydurma).
3. Haber tartışmaya açık bir konuysa (ekonomi, zam, karar, düzenleme, spor, teknoloji vb.), bir boş satır daha bırakıp sonuna bot gibi durmayan çok kısa, doğal ve tarafsız bir soru ekle (ör. "Sizce bu karar nasıl etkiler?"). Trajik/hassas haberlerde (ölüm, deprem, kaza vb.) ASLA soru ekleme.
4. Sona en fazla 1-2 adet ilgili ve ölçülü hashtag ekle (ör. #SonDakika #Ekonomi #Gündem).
5. URL, link veya alan adı kesinlikle yazma.
6. Çıktı SADECE tweet metni olsun; tırnak işareti, açıklama veya alternatif seçenek ekleme.
7. Toplam uzunluk kesinlikle 235 karakteri geçmesin."""


def _fallback_tweet(item: NewsItem, max_chars: int) -> str:
    """Gemini API kota/429 hatası verirse temiz ve okunaklı yedek format üretir."""
    emoji_map = {
        "ekonomi": "📊",
        "spor": "⚽",
        "teknoloji": "🤖",
        "gundem": "🚨",
    }
    tag_map = {
        "ekonomi": "#Ekonomi #Gündem",
        "spor": "#Spor #Gündem",
        "teknoloji": "#Teknoloji #Gündem",
        "gundem": "#SonDakika #Gündem",
    }
    emoji = emoji_map.get(item.category, "🚨")
    tags = tag_map.get(item.category, "#SonDakika #Gündem")
    title = item.title.strip()
    summary = item.summary.strip()

    if summary and summary.lower() != title.lower() and len(summary) > 30:
        candidate = f"{emoji} {title}\n\n{summary}\n\n{tags}"
        if len(candidate) <= max_chars:
            return candidate

    candidate = f"{emoji} {title}\n\n{tags}"
    return _enforce_length(candidate, max_chars)


def _strip_urls(text: str) -> str:
    """X'in linkli gönderi ($0.20) ücretine takılmamak için olası URL'leri temizler."""
    return re.sub(r"https?://\S+|www\.\S+", "", text).strip()


def _enforce_length(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip()).strip('"\'')
    if not INCLUDE_SOURCE_LINK:
        cleaned = _strip_urls(cleaned)
    if len(cleaned) <= max_chars:
        return cleaned

    # Kelime veya #hashtag ortasından bölmeden en yakın boşluktan temiz kes
    cut = cleaned[: max_chars - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    cut = cut.rstrip(" ,;:-")
    # Sonda yarım veya tek başına kalmış # işaretini temizle
    cut = re.sub(r"\s+#\S*$", "", cut).rstrip(" ,;:-")
    if not cut.endswith((".", "!", "?", "…")):
        cut += "…"
    return cut


def compose_tweet(item: NewsItem) -> str:
    """Gemini API ile haber metnini X formatına dönüştürür; API yoksa şablon kullanır."""
    source_footer = f"\n\n— {item.source}"
    if INCLUDE_SOURCE_LINK:
        max_body = MAX_BODY_CHARS_WITH_LINK
    else:
        max_body = MAX_BODY_CHARS_NO_LINK - len(source_footer)

    body = ""
    if GEMINI_API_KEY:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"Kaynak: {item.source}\n"
            f"Başlık: {item.title}\n"
            f"Özet: {item.summary}\n"
            f"Detay: {item.article_text[:900]}\n\n"
            f"Yukarıdaki haberi en fazla {max_body - 10} karakter olacak şekilde "
            f"tek bir X gönderisi olarak yaz. URL veya alan adı ekleme."
        )
        # Birincil model 429/503 verirse kesin süre sınırı (25sn) ile yedek modele veya şablona geç
        candidate_models = list(
            dict.fromkeys([GEMINI_MODEL, "gemini-4-hydrogen", "gemini-3.1-flash-lite"])
        )
        for model_name in candidate_models:
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                future = pool.submit(
                    client.interactions.create,
                    model=model_name,
                    system_instruction=SYSTEM_INSTRUCTION,
                    input=prompt,
                    store=False,
                    timeout=20.0,
                )
                interaction = future.result(timeout=25)
                if interaction.output_text:
                    body = _enforce_length(interaction.output_text, max_body)
                    break
            except FuturesTimeoutError:
                logger.warning("Gemini model zaman aşımı (%s, >25sn), sıradakine geçiliyor.", model_name)
            except Exception as exc:
                logger.warning("Gemini model hatası (%s), sıradakine geçiliyor: %s", model_name, exc)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
    else:
        logger.info("GEMINI_API_KEY tanımlı değil, standart haber şablonu kullanılıyor.")

    if not body:
        body = _fallback_tweet(item, max_body)

    if INCLUDE_SOURCE_LINK:
        return f"{body}\n{item.url}"
    if item.source.lower() not in body.lower():
        return f"{body}{source_footer}"
    return body

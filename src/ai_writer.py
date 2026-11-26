import logging
import re
import threading

from google import genai

from config import GEMINI_API_KEY, GEMINI_MODEL, INCLUDE_SOURCE_LINK
from src.news_fetcher import NewsItem

logger = logging.getLogger(__name__)

# X her URL'yi 23 karakter, her emojiyi 2 karakter sayar; güvenli tavanlar:
MAX_BODY_CHARS_WITH_LINK = 238
MAX_BODY_CHARS_NO_LINK = 272

CATEGORY_DEFAULT_TAGS = {
    "ekonomi": ["#Ekonomi", "#Gündem"],
    "spor": ["#Spor", "#Gündem"],
    "teknoloji": ["#Teknoloji", "#Gündem"],
    "gundem": ["#SonDakika", "#Gündem"],
}

SYSTEM_INSTRUCTION = """Sen Türkiye'nin en yüksek etkileşim alan dijital haber sayfası (HABER.EXE) için yazan kıdemli bir X (Twitter) editörüsün.
Verilen haberi X akışında yüksek okunma ve etkileşim alacak kısa, boşluklu ve tarafsız tek bir gönderiye dönüştüreceksin.

Kesin Kurallar:
1. İlk satır: Tek başına vurucu, çok kısa bir manşet olsun ve konuya uygun tek bir emoji ile başlasın (ör. 🚨 ..., 📊 ..., ⚡ ..., ⚽ ..., 🤖 ...).
2. Bir boş satır bırak, ardından TEK cümlelik net ve somut bir özet yaz (rakam, oran veya kritik kararı mutlaka öne çıkar; asla bilgi uydurma).
3. Haber tartışmaya açık bir konuysa (ekonomi, zam, karar, spor, teknoloji vb.), bir boş satır daha bırakıp en fazla 5-7 kelimelik çok kısa ve doğal bir soru ekle (ör. "Sizce bu karar piyasayı nasıl etkiler?"). Trajik/hassas haberlerde (ölüm, deprem, kaza vb.) ASLA soru ekleme.
4. En sona MUTLAKA 2 adet kısa ve konuya uygun hashtag yaz (ör. #Galatasaray #ŞampiyonlarLigi veya #Ekonomi #Gündem).
5. URL, link veya alan adı kesinlikle yazma.
6. Çıktı SADECE tweet metni olsun; tırnak işareti, açıklama veya alternatif seçenek ekleme.
7. Toplam uzunluk (hashtagler ve boş satırlar dahil) kesinlikle 205 karakteri geçmesin ki hiçbir cümle veya soru yarım kalmasın."""


def _extract_first_short_sentence(text: str, max_len: int) -> str:
    """Metinden max_len içine tam sığan ilk tam cümleyi çıkarır; yoksa boş döner."""
    if not text:
        return ""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        s = sentence.strip()
        if 25 <= len(s) <= max_len and s.endswith((".", "!", "?")):
            return s
    return ""


def _fallback_tweet(item: NewsItem, max_chars: int) -> str:
    """Gemini API kota/429 hatası verirse ASLA cümle kesmeden temiz yedek format üretir."""
    emoji_map = {
        "ekonomi": "📊",
        "spor": "⚽",
        "teknoloji": "🤖",
        "gundem": "🚨",
    }
    emoji = emoji_map.get(item.category, "🚨")
    tags = " ".join(CATEGORY_DEFAULT_TAGS.get(item.category, ["#SonDakika", "#Gündem"]))
    title = item.title.strip()
    headline = f"{emoji} {title}"
    tag_block = f"\n\n{tags}"
    summary_budget = max_chars - len(headline) - len(tag_block) - 2

    # Sadece bütçeye TAM sığan bir cümle varsa özet ekle; yoksa yarım kesmek yerine sadece manşet + etiket at
    short_summary = ""
    if summary_budget >= 45:
        for source_text in (item.summary, item.article_text):
            cand = _extract_first_short_sentence(source_text, summary_budget)
            if cand and cand.lower() != title.lower():
                short_summary = cand
                break

    if short_summary:
        candidate = f"{headline}\n\n{short_summary}{tag_block}"
    else:
        candidate = f"{headline}{tag_block}"
    return _enforce_length(candidate, max_chars, category=item.category)


def _strip_urls(text: str) -> str:
    """X'in linkli gönderi ($0.20) ücretine takılmamak için olası URL'leri temizler."""
    return re.sub(r"https?://\S+|www\.\S+", "", text).strip()


def _extract_hashtags(text: str, category: str) -> tuple[str, list[str]]:
    """Metindeki hashtagleri ayırır; eksikse kategoriye göre varsayılan 2 hashtag ekler."""
    raw_tags = re.findall(r"#[A-Za-z0-9_çğıöşüÇĞİÖŞÜ]+", text)
    seen: set[str] = set()
    chosen: list[str] = []
    for tag in raw_tags:
        key = tag.replace("İ", "i").replace("I", "ı").lower()
        if key not in seen and 2 < len(tag) <= 24:
            seen.add(key)
            chosen.append(tag)
        if len(chosen) == 2:
            break

    # Metin gövdesindeki satır sonu / sonda kalan hashtagleri temizle
    body_without_tags = re.sub(r"(?:^|\s)#[A-Za-z0-9_çğıöşüÇĞİÖŞÜ]+", "", text)
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in body_without_tags.splitlines()]
    cleaned_body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    if not chosen:
        chosen = list(CATEGORY_DEFAULT_TAGS.get(category, ["#SonDakika", "#Gündem"]))

    return cleaned_body, chosen


def _trim_to_complete_sentences(paragraph: str, budget: int, allow_word_cut: bool = False) -> str:
    """Paragrafı asla cümle/soru ortasından bölmeden bütçeye sığan tam cümlelerle kırpar."""
    if len(paragraph) <= budget:
        return paragraph

    sentences = re.split(r"(?<=[.!?])\s+", paragraph.strip())
    kept: list[str] = []
    for sentence in sentences:
        candidate = " ".join(kept + [sentence])
        if len(candidate) <= budget:
            kept.append(sentence)
        else:
            break

    if kept:
        return " ".join(kept)

    if not allow_word_cut:
        return ""

    # Yalnızca son çare (manşetin tek başına bile sığmaması) durumunda kelime sınırından kes
    cut = paragraph[: max(10, budget - 1)]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def _enforce_length(text: str, max_chars: int, category: str = "gundem") -> str:
    """
    Metni X karakter sınırına göre düzenler:
    - URL'leri temizler (INCLUDE_SOURCE_LINK=False ise)
    - 1-2 hashtag'in her zaman tam ve kesilmeden kalmasını garanti eder
    - Sığmayan soru/paragrafı ortadan kesmek yerine tamamen çıkarır; cümle yarım kalmaz
    """
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip()).strip('"\'')
    if not INCLUDE_SOURCE_LINK:
        cleaned = _strip_urls(cleaned)

    body_text, tags = _extract_hashtags(cleaned, category)
    tag_block = "\n\n" + " ".join(tags)

    # Eğer tek hashtag bile çok uzunsa 1 etikete düş
    if len(tag_block) > max_chars // 3 and len(tags) > 1:
        tags = tags[:1]
        tag_block = "\n\n" + tags[0]

    budget = max_chars - len(tag_block)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body_text) if p.strip()]

    if not paragraphs:
        return " ".join(tags)

    # 1) Tüm paragraflar bütçeye sığıyorsa dokunma
    joined = "\n\n".join(paragraphs)
    if len(joined) <= budget:
        return f"{joined}{tag_block}"

    # 2) 3+ paragraf varsa (Manşet + Özet + Soru), soru yarım kalmasın diye önce son paragrafı çıkar
    while len(paragraphs) > 2 and len("\n\n".join(paragraphs)) > budget:
        paragraphs.pop()

    joined = "\n\n".join(paragraphs)
    if len(joined) <= budget:
        return f"{joined}{tag_block}"

    # 3) 2 paragraf (Manşet + Özet) hâlâ sığmıyorsa özeti SADECE tam cümle sınırından kısalt; sığmıyorsa yarım bırakma
    if len(paragraphs) == 2:
        headline, summary = paragraphs[0], paragraphs[1]
        summary_budget = budget - len(headline) - 2
        if summary_budget >= 45:
            trimmed_summary = _trim_to_complete_sentences(summary, summary_budget, allow_word_cut=False)
            if trimmed_summary:
                return f"{headline}\n\n{trimmed_summary}{tag_block}"
        paragraphs = [headline]

    # 4) Sadece manşet kaldıysa temiz sığdır
    final_headline = _trim_to_complete_sentences(paragraphs[0], budget, allow_word_cut=True)
    return f"{final_headline}{tag_block}"


def compose_tweet(item: NewsItem) -> str:
    """Gemini API ile haber metnini X formatına dönüştürür; API yoksa şablon kullanır."""
    source_footer = f"\n— {item.source}"
    if INCLUDE_SOURCE_LINK:
        max_body = MAX_BODY_CHARS_WITH_LINK
    else:
        max_body = MAX_BODY_CHARS_NO_LINK - len(source_footer)

    body = ""
    if GEMINI_API_KEY:
        client = genai.Client(api_key=GEMINI_API_KEY)
        target_chars = min(205, max_body - 20)
        prompt = (
            f"Kategori: {item.category}\n"
            f"Kaynak: {item.source}\n"
            f"Başlık: {item.title}\n"
            f"Özet: {item.summary}\n"
            f"Detay: {item.article_text[:900]}\n\n"
            f"Yukarıdaki haberi, 2 kısa hashtag dahil TOPLAM en fazla {target_chars} karakter "
            f"olacak şekilde tek bir X gönderisi olarak yaz. URL veya alan adı ekleme."
        )
        # Birincil model 429/503 verirse 4 farklı model havuzundan sırayla dene (her biri max 20sn)
        candidate_models = list(
            dict.fromkeys([GEMINI_MODEL, "gemini-3.5-flash-lite", "gemini-4-hydrogen", "gemma-4-31b-it"])
        )
        for model_name in candidate_models:
            result_box: dict[str, object] = {}

            def _call_model(m_name: str = model_name, box: dict[str, object] = result_box) -> None:
                try:
                    box["resp"] = client.interactions.create(
                        model=m_name,
                        system_instruction=SYSTEM_INSTRUCTION,
                        input=prompt,
                        store=False,
                        timeout=15.0,
                    )
                except Exception as exc:
                    box["err"] = exc

            worker = threading.Thread(target=_call_model, daemon=True)
            worker.start()
            worker.join(timeout=20.0)

            if worker.is_alive():
                logger.warning("Gemini model zaman aşımı (%s, >20sn), sıradakine geçiliyor.", model_name)
                continue
            if "err" in result_box:
                logger.warning("Gemini model hatası (%s), sıradakine geçiliyor: %s", model_name, result_box["err"])
                continue

            interaction = result_box.get("resp")
            if interaction and getattr(interaction, "output_text", None):
                body = _enforce_length(interaction.output_text, max_body, category=item.category)
                break
    else:
        logger.info("GEMINI_API_KEY tanımlı değil, standart haber şablonu kullanılıyor.")

    if not body:
        body = _fallback_tweet(item, max_body)

    if INCLUDE_SOURCE_LINK:
        return f"{body}\n{item.url}"
    if item.source.lower() not in body.lower():
        return f"{body}{source_footer}"
    return body

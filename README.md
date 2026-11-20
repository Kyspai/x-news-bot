# X (Twitter) Gündem Haber Otomasyon Botu

Türkiye gündemindeki son dakika haberlerini RSS kaynaklarından (TRT Haber, NTV, BBC Türkçe, Anadolu Ajansı, Google News TR) otomatik olarak çeken, **Gemini API** ile X diline uygun özetleyen, haberin orijinal **video veya görselini** (yoksa otomatik tasarlanan şık bir haber kartını) hazırlayıp **GitHub Actions** üzerinden ücretsiz olarak X'e paylaşan Python botu.

## Özellikler
- **Ücretsiz Haber Kaynakları:** TRT Haber, NTV, BBC Türkçe, Anadolu Ajansı ve Google News TR.
- **Akıllı Tekrar Engelleme:** Hem URL hem de başlık benzerliği (Jaccard) kontrolü ile farklı ajansların geçtiği aynı haberi tekrar paylaşmaz (`data/posted_news.json`).
- **Görsel & Video Desteği:** Haberde doğrudan `.mp4` video varsa videoyu, yoksa yüksek çözünürlüklü `og:image` görselini indirir; ikisi de yoksa Pillow ile 1200x675 modern Türkçe haber kartı üretir.
- **Gemini AI Editörü:** `google-genai` SDK (`gemini-4-hydrogen`) ile tarafsız, 280 karakter sınırına uygun, ölçülü hashtag'li Türkçe tweet yazar.
- **Bulutta Ücretsiz Otomasyon:** GitHub Actions ile her 2 saatte bir otomatik çalışır ve geçmişi repo'ya kaydeder.

---

## 1. Gerekli API Anahtarlarını Alma

### A) X (Twitter) Developer API (Ücretsiz / Free Tier)
1. [X Developer Portal](https://developer.x.com/) adresine girip ücretsiz (Free) hesap oluşturun.
2. Bir **Project** ve **App** oluşturun.
3. App ayarlarında **User authentication settings** bölümüne girin ve izinleri mutlaka **Read and write** yapın (Type of App: *Web App, Automated App or Bot*).
4. **Keys and tokens** sekmesinden şu 4 değeri kopyalayın (izin değiştirdiyseniz Access Token'ı *Regenerate* edin):
   - `X_API_KEY` (API Key / Consumer Key)
   - `X_API_SECRET` (API Key Secret / Consumer Secret)
   - `X_ACCESS_TOKEN` (Access Token)
   - `X_ACCESS_TOKEN_SECRET` (Access Token Secret)

### B) Google Gemini API
1. [Google AI Studio](https://aistudio.google.com/apikey) adresinden ücretsiz API anahtarı oluşturun.
2. Bu anahtarı `GEMINI_API_KEY` olarak saklayın.

---

## 2. Bilgisayarda / Sunucuda Çalıştırma

### Tek Seferlik Çalıştırma (DRY_RUN Test Modu)
Gerçek paylaşım yapmadan önce botun haber çekmesini, metin yazmasını ve görsel/kart hazırlamasını test edebilirsiniz:

```bash
pip install -r requirements.txt
copy .env.example .env
python main.py
```

`DRY_RUN=true` iken X'e paylaşım yapılmaz; tweet metni terminale yazdırılır ve indirilen/üretilen görsel `output_preview/` klasörüne kaydedilir.

### 7/24 Anlık Gündem Takip Modu (`watch.py`)
Bir VPS/sunucuda veya bilgisayarınızda arka planda sürekli çalıştırıp yeni haber düştüğü anda paylaşım yapmak için:

```bash
python watch.py
```

`watch.py` varsayılan olarak her **2 dakikada bir** RSS kaynaklarını tarar; spam ve maliyet koruması için saatte en fazla **4**, günde en fazla **30** gönderi limitiyle (`.env` içinden değiştirilebilir) çalışır.

---

## 3. GitHub Actions ile Bulutta Otomatik Çalıştırma

1. GitHub'da **Private** (veya Public) yeni bir repo oluşturun ve bu proje dosyalarını push edin.
2. Repo ayarlarından **Settings → Secrets and variables → Actions → New repository secret** yolunu izleyerek şu 5 secret'ı ekleyin:
   - `X_API_KEY`
   - `X_API_SECRET`
   - `X_ACCESS_TOKEN`
   - `X_ACCESS_TOKEN_SECRET`
   - `GEMINI_API_KEY`
3. **Settings → Actions → General → Workflow permissions** bölümünde **Read and write permissions** seçeneğini işaretleyip kaydedin (botun `data/posted_news.json` dosyasını güncelleyebilmesi için gereklidir).
4. **Actions** sekmesine girip **X Gündem Haber Botu → Run workflow** diyerek ilk testi hemen başlatabilirsiniz (`dry_run: true` ile önce önizleme yapabilirsiniz).

---

## Özelleştirme
- **Paylaşım Sıklığı:** `.github/workflows/news_bot.yml` içindeki `cron: "0 */2 * * *"` satırını değiştirebilirsiniz (ör. her saat başı için `"0 * * * *"`).
- **Haber Kaynakları:** `config.py` içindeki `RSS_FEEDS` listesine yeni RSS adresleri ekleyebilirsiniz.
- **Marka Adı / Kart Tasarımı:** `.env` veya workflow dosyasındaki `BRAND_NAME` değerini kendi sayfa adınızla değiştirebilirsiniz.

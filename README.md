# KampüsSes — Kampüs Sorun Bildirim ve Takip Platformu

Yazılım Kalite Standartları dersi grup projesi.

Öğrenciler kampüsteki sorunları (bozuk asansör, kopan Wi-Fi, uzun yemekhane kuyruğu vb.) bildirir. Diğer öğrenciler aynı sorunu yaşadıklarını "destek" vererek gösterir. Bildirim kategoriye göre ilgili birime otomatik atanır. Birim, durumu açıklamayla günceller. Değerlendirme kurulu da sorunları aciliyet ve etkiye göre önceliklendirir.

## Proje yapısı

```
backend/               Django + Django REST Framework API
  config/              Ayarlar ve URL'ler
  accounts/            Kullanıcılar, roller, giriş (token)
  units/               Birimler ve birim personeli
  reports/             Bildirimler, kategoriler, etiketler, ekler, durum geçmişi, iş kuralları (services.py)
  interactions/        Destek ve yorumlar
  prioritization/      Kurul değerlendirmesi (aciliyet / etki puanı)
frontend/              HTML + CSS + vanilla JavaScript (Express ile sunulur)
```

## Kurulum ve çalıştırma

Gereksinimler: Python 3.12+ ve Node.js 18+.

### 1. Backend (http://localhost:8000)

```bash
cd backend
python -m venv venv
# Windows: venv\Scripts\activate    macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
python manage.py migrate
python manage.py seed_demo    # demo kullanıcıları ve örnek bildirimler
python manage.py runserver
```

**Windows notları (PowerShell):**
- `python` komutu tanınmazsa `py` yazın (örn. `py -m venv venv`).
- `activate` betiği "running scripts is disabled" hatası verirse ortamı etkinleştirmeden çalışabilirsiniz: `venv\Scripts\python manage.py runserver` gibi her komutun başına `venv\Scripts\python` yazın (`pip` için: `venv\Scripts\python -m pip install -r requirements.txt`).
- `.env` dosyası olmadan backend açılmaz (DEBUG kapalıyken SECRET_KEY zorunludur); `copy .env.example .env` adımını atlamayın.

### 2. Frontend (http://localhost:3000)

Backend açıkken ikinci bir terminalde:

```bash
cd frontend
npm install
npm start
```

Windows PowerShell'de `npm` "running scripts is disabled" hatası verirse `npm.cmd install` ve `npm.cmd start` yazın.

Tarayıcıda http://localhost:3000 adresini açın.

### 3. E-posta yeniden deneme (NFR-14, isteğe bağlı)

Durum değişikliği e-postası gönderilemezse 1, 5 ve 15 dakika sonra yeniden denenir. Denemeleri yapan komutu üçüncü bir terminalde çalıştırın (veya zamanlanmış görev olarak her dakika çalıştırın):

```bash
cd backend
python manage.py retry_emails --loop
```

Son denemede de gönderilemeyen e-postalar Django yönetim panelinde "E-posta bildirimleri" altında "Başarısız" olarak görünür.

### Demo kullanıcıları

Hepsinin parolası `Kampus.2026`.

| Rol | E-posta |
|---|---|
| Admin | admin@kampusses.local |
| Öğrenci | ayse@kampusses.local, mehmet@kampusses.local |
| Birim Sorumlusu (Bilgi İşlem) | bilgiislem@kampusses.local |
| Birim Sorumlusu (Yapı İşleri) | yapiisleri@kampusses.local |
| Kurul Üyesi | kurul@kampusses.local |

Django yönetim paneli: http://localhost:8000/admin/ (Admin hesabıyla).

## Testler

`.env` dosyası oluşturulmuş olmalıdır (bkz. Kurulum). Testler kendi geçici veritabanını kullanır; açık olan siteyi etkilemez, sunucuları kapatmanız gerekmez.

```bash
cd backend
python manage.py test
```

76 test bulunur: kimlik doğrulama, yetkiler, durum geçişleri, geri çekme, destek, yorum, önceliklendirme, e-posta bildirimleri ve dosya yükleme kuralları.

## Kalite kontrolü (K3 ve K4 kalite kapıları)

Testleri, test kapsamını (coverage), kod kontrolünü ve karmaşıklığı (Ruff), güvenlik taramasını (Bandit) ve paket açıklarını (pip-audit) tek komutla çalıştırır:

```bash
cd backend
pip install -r requirements-dev.txt
python kalite_kontrol.py
```

Her kapı için GEÇTİ / KALDI özeti ekrana yazılır. Ayrıntılı raporlar `backend/kalite_raporlari/` klasörüne kaydedilir. Eşikler `backend/pyproject.toml` dosyasındadır.

## Roller

| Rol | Yapabildikleri |
|---|---|
| Ziyaretçi | Bildirimleri ve birimleri görüntüler, kayıt olur. |
| Öğrenci | Sorun bildirir; bildirimini birim işleme başlayana kadar düzenler veya geri çeker; destek verir, yorum yapar. |
| Birim Sorumlusu | Birimine atanan bildirimlerin durumunu günceller, başka birime aktarır. Yorumları "Resmi Yanıt" olarak görünür. |
| Kurul Üyesi | Açık bildirimlere aciliyet ve etki puanı (1–5) verir. |
| Admin | Kullanıcı rolleri, birimler, birim personeli ve kategorileri yönetir; uygunsuz bildirimi gizler. |

Kayıt olan herkes Öğrenci rolüyle başlar. Rolleri yalnızca Admin değiştirir.

## Temel iş kuralları

- **Durum akışı:** Yeni → Atandı → İşlemde → Çözüldü. Herhangi bir açık durumdan Reddedildi'ye geçilebilir. Kapanan bildirim yeniden açılmaz. Her geçiş açıklama ister ve durum geçmişine kaydedilir.
- **Otomatik atama:** Kategorinin varsayılan birimi varsa bildirim oluşturulunca o birime atanır.
- **Benzer bildirim uyarısı:** Aynı kategori ve konumda açık bildirim varsa formda gösterilir.
- **Destek:** Kullanıcı başına bildirim başına bir destek. Bu kural veritabanı kısıtıyla korunur.
- **Öncelik skoru:** Kurul puan ortalaması × 10 + destek sayısı.
- **Bildirim:** Durum değişince bildiren kişiye ve destek verenlere e-posta gönderilir. Geliştirmede e-postalar backend konsoluna yazılır.
- **Dosya ekleri:** En fazla 3 dosya, her biri en fazla 5 MB (JPG, PNG, WEBP, PDF).

## API özeti

Tüm uçlar `/api/` altındadır. Kimlik doğrulama: `Authorization: Token <token>`.

| Uç | Açıklama |
|---|---|
| `POST auth/register/`, `POST auth/login/`, `POST auth/logout/`, `GET auth/me/` | Kayıt, giriş, çıkış, oturum bilgisi |
| `GET/POST reports/` | Liste (filtreler: `search`, `category`, `status`, `unit`, `tag`, `open`, `mine`, `my_units`, `unassessed`, `ordering`) / oluştur |
| `GET/PATCH/DELETE reports/{id}/` | Detay / düzenle / geri çek (Admin için gizle) |
| `GET reports/similar/?category=&location=` | Benzer açık bildirimler |
| `POST reports/{id}/status/` | Durum güncelle (birim personeli) |
| `POST reports/{id}/assign/` | Başka birime aktar (birim personeli) |
| `POST reports/{id}/media/` | Dosya ekle |
| `POST/DELETE reports/{id}/support/` | Destek ver / geri al |
| `GET/POST reports/{id}/comments/`, `DELETE comments/{id}/` | Yorumlar |
| `GET/PUT reports/{id}/assessment/` | Kurul değerlendirmesi |
| `units/`, `categories/`, `tags/`, `users/` | Birim, kategori, etiket ve kullanıcı yönetimi |

## Önceki prototipten (IdeaHub) farklar

Bu proje, ekibin önceki IdeaHub prototipinin yapısından yola çıkılarak yeniden yazıldı.

| IdeaHub | KampüsSes |
|---|---|
| Idea | Report (Bildirim) |
| Vote | Support (Destek) |
| Team / TeamMember | Unit (Birim) |
| Update | StatusUpdate (Durum geçmişi) |
| Participant / Team Leader / Judge | Öğrenci / Birim Sorumlusu / Kurul Üyesi |

Faz 1 analizinde bulunan sorunlar şöyle giderildi:

| Bulgu | Düzeltme |
|---|---|
| B1 – Giriş tarayıcıda yapılıyordu | Giriş sunucuda yapılıyor ve token tabanlı. 5 hatalı denemeden sonra 15 dakika kilit. |
| B2 – Parolalar düz metindi ve API'de dönüyordu | Django'nun parola özetleme mekanizması kullanılıyor. Parola hiçbir yanıtta yok, başka kullanıcıların e-postası gizli. |
| B3 – API'de yetki kontrolü yoktu | Varsayılan olarak kimlik doğrulama zorunlu. Her uç kendi rol veya sahiplik kuralını uyguluyor. |
| B4 – SECRET_KEY repo'daydı, DEBUG açıktı, CORS herkese açıktı | Ayarlar `.env` dosyasından okunuyor. CORS yalnızca frontend adresine açık. |
| B5 – Hiç test yoktu | 38 otomatik test eklendi. |
| B6 – Serviste olmayan alanlar kullanılıyordu | Servis katmanı (`reports/services.py`) yeniden yazıldı ve testlerle doğrulandı. |
| B7 – Çift oy oluşabiliyordu | `UniqueConstraint` eklendi. |
| B8 – requirements.txt eksikti | Tüm bağımlılıklar sürümleriyle listelendi. |
| B9 – İsimlendirme tutarsızdı | Tüm modeller Django isimlendirme kurallarına göre yeniden adlandırıldı. |
| Ek – Frontend'de XSS riski vardı | Kullanıcı verisi HTML'e eklenmeden önce kaçışlanıyor (`escapeHtml`). |

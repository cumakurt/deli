# deli 🥪

**deli**, yüksek performanslı, hafif ve modern bir yük testi (load testing) motorudur. Hız, düşük kaynak tüketimi ve geliştirici deneyimine odaklanır.

## 🚀 Özellikler

*   **Yüksek Performans:**
    *   **Async I/O:** `asyncio` ve `httpx` (HTTP/2 destekli) üzerine kurulu asenkron mimari.
    *   **uvloop:** 2-4x daha hızlı event loop desteği (Python 3.12+ ile otomatik aktif).
    *   **Düşük Overhead:** Optimize edilmiş bellek kullanımı (`__slots__`), string cache, ve batch processing ile saniyede 10.000+ isteği tek bir çekirdekte işleyebilir.
    *   **Zero-Allocation Paths:** Hot-path üzerinde minimum nesne oluşturma.
*   **Akıllı Metrikler:**
    *   **T-Digest:** Bellek dostu, yüksek doğruluklu streaming percentile hesaplama (P50, P95, P99).
    *   **Düşük Bellek:** Sabit boyutlu ring-buffer ile bellek kullanımı test süresinden bağımsızdır.
    *   **Real-time Dashboard:** Terminal üzerinde çalışan, düşük kaynak tüketen canlı izleme paneli.
*   **Kolay Kullanım:**
    *   **Postman Desteği:** Postman Collection v2.1 dosyalarını doğrudan çalıştırır.
    *   **YAML Konfigürasyon:** Basit ve okunabilir test senaryosu tanımları.
    *   **Tek Dosya Rapor:** Paylaşılabilir, çevrimdışı çalışabilen, interaktif grafikli HTML raporlar.
*   **Gelişmiş Senaryolar:**
    *   **Stress Test:** Kırılma noktasını ve darboğazları otomatik tespit eden aşamalı testler.
    *   **SLA Doğrulama:** P95, Hata Oranı gibi metrikler için eşik değer belirleme ve otomatik fail.
    *   **CI/CD Entegrasyonu:** JUnit XML ve JSON çıktı formatları.

## 📦 Kurulum

```bash
# Sanal ortam oluştur
python3 -m venv .venv
source .venv/bin/activate

# Bağımlılıkları yükle
pip install -r requirements.txt
```

## ⚡ Hızlı Başlangıç

### 1. Basit bir yük testi çalıştırın

```bash
# Postman koleksiyonu ile
deli -c my_collection.json --users 50 --duration 60

# Konfigürasyon dosyası ile
deli -c my_collection.json -f config.yaml

# Tek bir URL'ye test (Postman olmadan)
deli -m https://httpbin.org/get --users 100 --duration 30
```

### 2. Örnek Konfigürasyon (`config.yaml`)

```yaml
users: 100               # Eşzamanlı sanal kullanıcı sayısı
ramp_up_seconds: 10      # Yükü kademeli artırma süresi
duration_seconds: 60     # Test süresi
scenario: gradual        # constant, gradual, spike
think_time_ms: 50        # İstekler arası bekleme süresi

# SLA (Service Level Agreement) Hedefleri
sla_p95_ms: 500          # P95 < 500ms olmalı 
sla_error_rate_pct: 1.0  # Hata oranı < %1.0 olmalı
```

### 3. Stress Test Modu

Sistemin sınırlarını zorlamak için stress test modunu kullanın:

```bash
deli -c my_collection.json -f stress_config.yaml --stress
```

**`stress_config.yaml` Örneği:**

```yaml
scenario: linear_overload
initial_users: 10
step_users: 10           # Her adımda eklenecek kullanıcı
step_interval_seconds: 10 # Adım süresi
max_users: 1000          # Maksimum kullanıcı limiti

# Kırılma noktası eşikleri
sla_p95_ms: 1000
sla_error_rate_pct: 5.0
```

## 📊 Performans Notları

`deli`, performans için agresif optimizasyonlar içerir. Detaylı bilgi için [PERFORMANCE.md](PERFORMANCE.md) dosyasına göz atın.

Anahtar optimizasyonlar:
- **GC Disabled:** Test sırasında garbage collector devre dışı bırakılır (latency spike önlenir).
- **Batch Processing:** Sonuçlar queue'dan toplu alınır ve işlenir.
- **Lazy Metrics:** Histogram verileri sadece raporlama anında hesaplanır.

## 🛠 Geliştirme

```bash
# Linter çalıştır
ruff check .

# Testleri çalıştır
pytest tests/
```

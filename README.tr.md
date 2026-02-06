# deli

Python için hafif **yük çalıştırma motoru**. **Hız ve performans öncelikli** — framework değil: minimal soyutlama, doğrudan çalıştırma, sınırlı bellek. **Postman Collection v2.1**, asenkron HTTP/2, yük ve stres modu, HTML raporları desteklenir.

- **Çalıştırma motoru**: Çalışma başına tek client, yüksek bağlantı limiti, hızlı tüketim, düşük ek yük
- **Yığın**: asyncio + httpx (HTTP/2) + uvloop, raporlar için orjson
- **Yük testi**: YAML config (kullanıcı, ramp-up, süre, senaryo), constant/gradual/spike
- **Stres testi** (`-s`): Eşik aşılana kadar fazlı ramp; kırılma noktası, bozulma tespiti
- **Raporlar**: HTML (ECharts), JUnit, JSON

Yerel ve Docker içinde çalışır (durumsuz, konteyner dostu).

**Dil:** [Türkçe](README.tr.md) | [English](README.md)

---

## Yasal ve sorumlu kullanım

**Yalnızca yasal hedeflerde kullanın.** Yük veya stres testlerini **yalnızca** sahibi olduğunuz veya sahibinden **açık yazılı izin** aldığınız sistemler, API'ler veya kaynaklara karşı çalıştırın. İzinsiz test, bilgisayar suistimali yasalarına (örn. ulusal karşılıklar), kullanım koşullarına aykırılık ve hizmet reddi / kötüye kullanım sayılabilir.

- **Sorumluluk:** Bu aracı nerede ve nasıl kullandığınızdan yalnızca siz sorumlusunuz. Geliştiriciler ve katkıda bulunanlar, kötüye kullanım, zarar veya hukuki sonuçlar için hiçbir sorumluluk kabul etmez.
- **Yasal zorunluluklar:** Yetkili olduğunuz ülkedeki tüm geçerli yasalara (ceza, hukuk, sözleşme) uyun. Üçüncü taraf veya canlı sistemleri test etmeden önce yazılı izin alın. İzin verilmeyen sistemlere kullanılamazlık veya zarar vermeyin.
- **Uyarı:** Araç yüksek istek hacmi üretebilir. İzinsiz kullanım (örn. yetkisiz sistemlere karşı) hukuki işlem, hesap kapatma veya tazminat sorumluluğuna yol açabilir. Yalnızca meşru kapasite planlama, performans doğrulama ve yetkili penetrasyon testi için kullanın.
- **Garanti yok:** Yazılım "olduğu gibi" sunulur; garanti verilmez. Bkz. [Lisans](LICENSE).

---

## Gereksinimler

- Python 3.11+
- Postman Collection v2.1 (JSON dışa aktarma) — yalnızca `-c` kullanıldığında

---

## Kurulum

```bash
# Proje kökünden
pip install -e .

# Veya requirements ile
pip install -r requirements.txt && pip install -e .

# Sanal ortam kullanarak (önerilen)
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -e .
```

---

## CLI referansı

| Seçenek | Kısa | Açıklama |
|--------|------|----------|
| **--collection** | **-c** | Postman Collection v2.1 JSON yolu (yük testinde -m kullanılmıyorsa zorunlu; stres testinde hedef Postman ise zorunlu) |
| **--config** | **-f** | YAML config yolu (yük testinde isteğe bağlı: atlanıp --users, --duration vb. kullanılabilir; stres testinde zorunlu) |
| **--output** | **-o** | Rapor çıktı yolu (dosya veya dizin). Varsayılan: `report.html` (yük) veya `stress_report.html` (stres) |
| **--env** | **-e** | Collection ortam değişkeni: `KEY=VALUE`. Tekrarlanabilir. Yalnızca -c (Postman) ile |
| **--manual-url** | **-m** | Manuel hedef URL: yalnızca bu URL'ye karşı çalıştır (Postman yok). -f ve -o ile kullanın |
| **--stress** | **-s** | Stres testi modunu çalıştır. -f stress config'e işaret etmeli; hedef -c veya -m ile |
| **--no-live** | | Canlı Rich panelini kapatır (headless; CI/Docker için uygun) |
| **--junit** | | JUnit XML raporunu da PATH'e yazar (CI: Jenkins, GitLab vb.) |
| **--json** | | JSON raporunu da PATH'e yazar (makine okunabilir metrikler) |
| **--version** | **-v** | Sürümü gösterir ve çıkar |

**Config geçersiz kılmaları** (`-f` YAML'daki değerleri verildiğinde geçersiz kılar):

| Seçenek | Açıklama |
|--------|----------|
| **--users** | Sanal kullanıcı sayısı |
| **--duration** | Test süresi (saniye) |
| **--ramp-up** | Ramp-up süresi (saniye) |
| **--scenario** | `constant`, `gradual` veya `spike` |
| **--think-time** | İstekler arası bekleme (ms) |
| **--iterations** | Kullanıcı başına döngü (0 = süreye göre) |
| **--spike-users**, **--spike-duration** | Spike senaryosunda ek kullanıcı ve süre |
| **--sla-p95**, **--sla-p99**, **--sla-error-rate** | SLA eşikleri |

---

## Kullanım örnekleri

### 1. Postman collection ile yük testi (temel)

**Örnek:** Postman collection ile yük testi ve varsayılan çıktı `report.html`.

```bash
deli -c path/to/collection.json -f config.yaml
```

**Örnek:** Aynı, ancak raporu belirli bir dosyaya yaz.

```bash
deli -c path/to/collection.json -f config.yaml -o report.html
```

**Örnek:** Raporu bir dizine yaz (dizin içinde `report.html` oluşturur).

```bash
deli -c path/to/collection.json -f config.yaml -o ./reports/2025-02/
```

**Örnek:** Boşluk içeren collection yolu — tırnak kullanın.

```bash
deli -c "/home/user/Downloads/My API.postman_collection.json" -f config.yaml -o report.html
```

---

### 2. Yük testi — `-e` seçeneği (ortam değişkenleri)

Collection'daki `{{base_url}}` gibi değişkenleri çalışma anında geçersiz kılmak için `-e` kullanın. Birden fazla `-e` verilebilir.

**Örnek:** Tek değişken.

```bash
deli -c collection.json -f config.yaml -e base_url=https://api.example.com -o report.html
```

**Örnek:** Birden fazla değişken.

```bash
deli -c collection.json -f config.yaml \
  -e base_url=https://staging.example.com \
  -e api_key=secret123 \
  -e timeout=5000 \
  -o report.html
```

---

### 3. Yük testi — config geçersiz kılmaları (komut satırı)

Config dosyasındaki değerleri CLI seçenekleriyle geçersiz kılın. `-f` ile verilen YAML'daki ilgili anahtar, seçenek verildiğinde geçersiz kalır.

**Örnek — `--users`:** `deli -m https://api.example.com/health -f config.yaml -o report.html --users 80 --no-live`

**Örnek — `--duration`:** `deli -c collection.json -f config.yaml -o report.html --duration 120 --no-live`

**Örnek — `--scenario`:** `deli -m https://httpbin.org/get -f config.yaml -o report.html --scenario gradual --no-live`

**Örnek — config dosyası olmadan (-f atlanır):** Sadece CLI parametreleriyle çalıştırma (varsayılan: 10 kullanıcı, 60 sn süre, constant senaryo).

```bash
deli -m https://httpbin.org/get -o report.html --users 5 --duration 10 --no-live
deli -c collection.json -o report.html --users 20 --duration 30 --scenario gradual --no-live
```

---

### 4. Yük testi — `--no-live` seçeneği (headless)

Canlı Rich paneli istemiyorsanız (CI, Docker, script) `--no-live` kullanın.

**Örnek:** Headless çalıştırma.

```bash
deli -c collection.json -f config.yaml -o report.html --no-live
```

---

### 5. Yük testi — senaryo örnekleri (config)

**Sabit yük (constant)** — Sabit kullanıcı sayısı, belirli süre:

```yaml
# config_constant.yaml
users: 20
ramp_up_seconds: 5
duration_seconds: 120
iterations: 0
think_time_ms: 100
scenario: constant
```

```bash
deli -c collection.json -f config_constant.yaml -o report_constant.html
```

**Kademeli (gradual)** — Kademeli kullanıcı artışı, sonra süre boyunca sabit:

```yaml
# config_gradual.yaml
users: 50
ramp_up_seconds: 60
duration_seconds: 180
iterations: 0
think_time_ms: 50
scenario: gradual
```

```bash
deli -c collection.json -f config_gradual.yaml -o report_gradual.html
```

**Spike** — Önce ramp, ortada ani yük artışı, sonra düşüş:

```yaml
# config_spike.yaml
users: 10
ramp_up_seconds: 20
duration_seconds: 120
think_time_ms: 100
scenario: spike
spike_users: 40
spike_duration_seconds: 15
```

```bash
deli -c collection.json -f config_spike.yaml -o report_spike.html
```

**SLA (raporda ihlal gösterimi)** — İsteğe bağlı; rapor P95/P99/hata oranı ihlallerini listeler:

```yaml
# config_with_sla.yaml
users: 30
ramp_up_seconds: 10
duration_seconds: 60
think_time_ms: 100
scenario: constant
sla_p95_ms: 500
sla_p99_ms: 1000
sla_error_rate_pct: 1.0
```

```bash
deli -c collection.json -f config_with_sla.yaml -o report_sla.html
```

**Hazır senaryo config'leri** — `examples/` dizininde yaygın senaryolar için config'ler bulunur: smoke (`config_smoke.yaml`), baseline load (`config_load_baseline.yaml`), yüksek yük (`config_load_stress.yaml`), spike (`config_spike.yaml`), soak/dayanıklılık (`config_soak.yaml`), gradual ramp (`config_ramp_gradual.yaml`). Kısa tablo ve çalıştırma komutları için [examples/README.md](examples/README.md) dosyasına bakın.

---

### 6. Manuel URL modu (`-m`) — Postman kullanmadan tek URL

**Örnek:** Tek URL'e yük testi; config ve output zorunlu.

```bash
deli -m https://api.example.com/health -f config.yaml -o report.html
```

**Örnek:** Farklı base path.

```bash
deli -m https://api.example.com/v1/users -f config.yaml -o report_manual.html
```

**Örnek:** Manuel URL + headless.

```bash
deli -m https://httpbin.org/get -f config.yaml -o report.html --no-live
```

`-m` kullanıldığında `-c` ve `-e` kullanılmaz; hedef yalnızca verilen URL'dir.

---

### 7. Stres testi (`-s`) — Ayrı mod, ayrı config

Stres testi için **-s** ve **stres'e özel YAML** gerekir. Hedef **-c** (Postman) veya **-m** (manuel URL) ile verilir.

**Örnek:** Stres testi, hedef Postman collection.

```bash
deli -s -f stress_config.yaml -c collection.json -o stress_report.html
```

**Örnek:** Stres testi, hedef manuel URL.

```bash
deli -s -f stress_config.yaml -m https://api.example.com/health -o stress_report.html
```

**Örnek:** Stres testi, çıktıyı dizine yaz (içinde `stress_report.html` oluşur).

```bash
deli -s -f stress_config.yaml -c collection.json -o ./stress_results/
```

**Örnek:** Stres testi, headless.

```bash
deli -s -f stress_config.yaml -c collection.json -o stress_report.html --no-live
```

---

### 8. Stres testi — senaryo örnekleri (stress config)

**Linear overload** — Kullanıcı sayısı kademeli artar; SLA aşılınca test durur.

```yaml
# stress_linear.yaml
sla_p95_ms: 500
sla_p99_ms: 1000
sla_error_rate_pct: 1.0
sla_timeout_rate_pct: 5.0
initial_users: 5
step_users: 5
step_interval_seconds: 30
max_users: 200
think_time_ms: 0
scenario: linear_overload
```

```bash
deli -s -f stress_linear.yaml -c collection.json -o stress_linear.html
```

**Spike stress** — Tek fazda yüksek kullanıcı sayısı, belirli süre.

```yaml
# stress_spike.yaml
sla_p95_ms: 500
sla_p99_ms: 1000
sla_error_rate_pct: 1.0
initial_users: 5
step_users: 5
step_interval_seconds: 30
max_users: 100
scenario: spike_stress
spike_users: 80
spike_hold_seconds: 45
```

```bash
deli -s -f stress_spike.yaml -c collection.json -o stress_spike.html
```

**Soak + stress** — Önce soak (düşük yük), sonra kademeli artış.

```yaml
# stress_soak.yaml
sla_p95_ms: 500
sla_p99_ms: 1000
sla_error_rate_pct: 1.0
initial_users: 10
step_users: 10
step_interval_seconds: 30
max_users: 150
scenario: soak_stress
soak_users: 20
soak_duration_seconds: 120
```

```bash
deli -s -f stress_soak.yaml -c collection.json -o stress_soak.html
```

---

### 9. Sürüm

**Örnek:** Sürüm bilgisi.

```bash
deli -v
# veya
deli --version
```

---

### 10. Docker örnekleri

**Build:**

```bash
docker build -t deli .
```

Konteyner root olmayan kullanıcıyla çalışır. Raporu host'ta almak için bağlanan dizine **mutlak** çıktı yolu verin: örn. `-v $(pwd):/data` ve `-o /data/report.html`. Bağlanan dizine yazabilmek için **`--user $(id -u):$(id -g)`** kullanın; aksi halde "Permission denied" alabilirsiniz.

**Örnek — raporu host'un mevcut dizinine yaz:**

```bash
docker run --rm --user $(id -u):$(id -g) -v $(pwd):/data deli \
  -m https://httpbin.org/get \
  -f /app/examples/config.yaml \
  -o /data/report.html \
  --no-live
# => report.html mevcut dizinde
```

**Yük testi — kendi config ve collection (mount):**

```bash
docker run --rm --user $(id -u):$(id -g) -v $(pwd):/data -v $(pwd)/reports:/tmp deli \
  -c /data/collection.json \
  -f /data/config.yaml \
  -o /tmp/report.html \
  --no-live
# => reports/report.html
```

**Yük testi — yerleşik examples, çıktı /tmp:**

```bash
docker run --rm --user $(id -u):$(id -g) -v $(pwd)/reports:/tmp deli \
  -m https://httpbin.org/get \
  -f /app/examples/config.yaml \
  -o /tmp/report.html \
  --no-live
```

**Stres testi — yerleşik examples:**

```bash
docker run --rm --user $(id -u):$(id -g) -v $(pwd)/reports:/tmp deli \
  -s -m https://httpbin.org/get \
  -f /app/examples/stress_config.yaml \
  -o /tmp/stress_report.html \
  --no-live
```

**Docker — config geçersiz kılmaları:** Komut satırından config değerlerini geçersiz kılmak için `--user $(id -u):$(id -g)` ve bir dizin mount'u kullanın; rapor host'ta oluşur. Örnek: `--users 50 --duration 20`, `--scenario gradual --ramp-up 10`, `--sla-p95 400 --sla-p99 800 --sla-error-rate 1.0`.

---

### 11. Tam yük config örneği

```yaml
# config.yaml — yük testi
users: 25
ramp_up_seconds: 15
duration_seconds: 300
iterations: 0
think_time_ms: 200
scenario: gradual

# Spike (yalnızca scenario: spike ise)
spike_users: 50
spike_duration_seconds: 20

# SLA (rapor ihlal listesi)
sla_p95_ms: 400
sla_p99_ms: 800
sla_error_rate_pct: 0.5
```

---

### 12. Tam stres config örneği

```yaml
# stress_config.yaml — stres testi (-s)
sla_p95_ms: 500
sla_p99_ms: 1000
sla_error_rate_pct: 1.0
sla_timeout_rate_pct: 5.0
initial_users: 5
step_users: 5
step_interval_seconds: 30
max_users: 200
think_time_ms: 0
scenario: linear_overload

# spike_stress için
spike_users: 60
spike_hold_seconds: 30

# soak_stress için
soak_users: 15
soak_duration_seconds: 90
```

---

## Konfigürasyon referansı

### Yük testi config (-s olmadan kullanılır)

| Anahtar | Açıklama | Varsayılan |
|---------|----------|------------|
| users | Sanal kullanıcı sayısı | 10 |
| ramp_up_seconds | Ramp-up süresi (gradual senaryo) | 10 |
| duration_seconds | Test süresi (saniye) | 60 |
| iterations | 0 = süreye göre; >0 = kullanıcı başına N döngü | 0 |
| think_time_ms | İstekler arası gecikme (ms) | 0 |
| scenario | constant \| gradual \| spike | constant |
| spike_users | Spike sırasında ek kullanıcı | 0 |
| spike_duration_seconds | Spike faz süresi | 0 |
| sla_p95_ms | SLA P95 (ms); ihlalleri raporla | - |
| sla_p99_ms | SLA P99 (ms) | - |
| sla_error_rate_pct | SLA max hata % | - |

### Stres testi config (-s ile kullanılır)

| Anahtar | Açıklama | Örnek |
|---------|----------|-------|
| sla_p95_ms | P95 eşiği (ms); aşılınca dur | 500 |
| sla_p99_ms | P99 eşiği (ms) | 1000 |
| sla_error_rate_pct | Max hata %; aşılınca dur | 1.0 |
| sla_timeout_rate_pct | Max timeout % | 5.0 |
| initial_users | Başlangıç eşzamanlı kullanıcı | 5 |
| step_users | Her fazda eklenen kullanıcı | 5 |
| step_interval_seconds | Faz başına süre (saniye) | 30 |
| max_users | Kullanıcı üst sınırı | 200 |
| scenario | linear_overload \| spike_stress \| soak_stress | linear_overload |
| spike_users, spike_hold_seconds | Spike fazı (spike_stress) | 50, 30 |
| soak_users, soak_duration_seconds | Soak fazı (soak_stress) | 10, 60 |

---

## Parametre referansı (detaylı)

Her seçenek ve config anahtarının ne anlama geldiği, neden kullanılacağı ve gerektiğinde uyarılar aşağıda özetlenir. **Hatırlatma:** Parametreler yük yoğunluğunu ve hedefi belirler; yalnızca sahibi olduğunuz veya test için açık yetkiniz olan sistemlerde kullanın. Bkz. [Yasal ve sorumlu kullanım](#yasal-ve-sorumlu-kullanım).

### CLI seçenekleri

| Seçenek | Anlamı | Neden kullanılır | Uyarılar / notlar |
|--------|--------|------------------|-------------------|
| **--collection** (-c) | Postman Collection v2.1 JSON dosya yolu. Tekrarlanacak HTTP isteklerini tanımlar. | API akışınız Postman'de tanımlıysa; -m kullanılmıyorsa yük testinde zorunlu; hedef Postman ise stres testinde zorunlu. | Dosya geçerli v2.1 JSON olmalı. |
| **--config** (-f) | YAML config yolu (yük veya stres parametreleri). | Tekrarlanabilir çalıştırma, paylaşılan config; yük testinde isteğe bağlı (sadece CLI geçersiz kılmaları kullanılabilir); **stres testinde zorunlu**. | Stres testi her zaman -f gerektirir. |
| **--output** (-o) | HTML raporunun (ve isteğe bağlı JUnit/JSON) yazılacağı yer. | Sonuçları saklamak veya CI için. Varsayılan: `report.html` (yük) veya `stress_report.html` (stres). | Yol bir dizinse, rapor dosyası o dizin içinde varsayılan adla oluşturulur. |
| **--env** (-e) | Collection değişkeni geçersiz kılma: `KEY=VALUE`. Tekrarlanabilir. | Collection'ı düzenlemeden farklı ortamlara (örn. `base_url`) yönlendirmek. Yalnızca -c ile. | -e içindeki gizliler işlem listelerinde görünebilir; hassas veri için ortam dosyaları tercih edin. |
| **--manual-url** (-m) | Tek hedef URL; Postman yok. | Tek endpoint için hızlı test. -f ve -o ile kullanın. | -m kullanıldığında -c ve -e yok sayılır. **Yalnızca test yetkiniz olan URL'lerde kullanın.** |
| **--stress** (-s) | Stres testi modunu aç (SLA ihlaline kadar fazlı ramp). | Kırılma noktası ve maksimum sürdürülebilir yükü bulmak. -f stress config'e işaret etmeli; hedef -c veya -m ile. | Stres testleri yüksek yük üretir; yetkilendirmeden emin olun. |
| **--no-live** | Canlı Rich panelini kapat. | TTY olmayan CI, Docker veya script ortamları. | TTY yoksa saniyede bir satır metrik yazılır. |
| **--junit** PATH | JUnit XML raporunu da yaz. | CI entegrasyonu (Jenkins, GitLab vb.); SLA ihlalleri başarısız test olarak görünür. | PATH yazılabilir olmalı. |
| **--json** PATH | JSON metriklerini de yaz. | Özel pipeline veya panolar için makine okunabilir metrikler. | PATH yazılabilir olmalı. |
| **--version** (-v) | Sürümü yazdır ve çık. | Script veya destek. | — |

### Config geçersiz kılmaları (CLI)

| Seçenek | Anlamı | Neden kullanılır | Uyarılar / notlar |
|--------|--------|------------------|-------------------|
| **--users** | Sanal (eşzamanlı) kullanıcı sayısı. | YAML düzenlemeden hızlı değişiklik. | **Çok yüksek değerler hedefi veya kendi makinenizi aşırı yükleyebilir; yalnızca yetkili hedeflerde kullanın.** |
| **--duration** | Test süresi (saniye). | Çalışmayı kısaltmak veya uzatmak. | Uzun süre + yüksek kullanıcı = sürekli yüksek yük; izin aldığınızdan emin olun. |
| **--ramp-up** | Ramp-up süresi (saniye); tam kullanıcı sayısına ulaşma veya başlangıç ramp süresi. | Daha yumuşak başlangıç, soğuk başlangıç spike'ı azaltma. | Çok kısa ramp başlangıçta trafik spike'ına yol açabilir. |
| **--scenario** | Yük deseni: `constant`, `gradual` veya `spike`. | constant = sabit; gradual = ramp sonra tut; spike = ortada ani artış. | spike anlamlı olması için --spike-users ve --spike-duration gerekir. |
| **--think-time** | Kullanıcı başına istekler arası gecikme (ms). | Gerçekçi "düşünme süresi" simülasyonu. | 0 = maksimum istek hızı; 0 yalnızca yetkili sistemlerde ham verim testi için kullanın. |
| **--iterations** | 0 = süreye göre; >0 = kullanıcı başına N döngü sonra dur. | Kullanıcı başına sabit iş yükü. | >0 iken tüm kullanıcılar N döngüyü bitirince test biter (duration'tan önce olabilir). |
| **--spike-users**, **--spike-duration** | Spike sırasında ek kullanıcı ve süre (spike senaryosu). | Flaş satış veya viral trafik simülasyonu. | Yalnızca senaryo spike iken kullanılır. |
| **--sla-p95**, **--sla-p99**, **--sla-error-rate** | SLA eşikleri (ms veya %). | Yük testinde: ihlalleri raporla; stres testinde: aşılınca dur. | SLO veya sözleşmenize uygun değerler verin. |

### Yük testi config (YAML anahtarları)

| Anahtar | Anlamı | Neden kullanılır | Uyarılar / notlar |
|---------|--------|------------------|-------------------|
| **users** | Eşzamanlı sanal kullanıcı sayısı. | Yük yoğunluğunun ana kolu. Varsayılan 10. | **Yüksek değerler yükü artırır; yalnızca test yetkiniz olan sistemlerde kullanın.** |
| **ramp_up_seconds** | Tam kullanıcı sayısına ulaşma süresi (gradual) veya başlangıç ramp. | Soğuk başlangıç spike'ı azaltma; gradual senaryoda ramp süresi. | Çok düşük değer ani başlangıç spike'ına yol açabilir. |
| **duration_seconds** | Toplam test süresi (saniye). | Yükü ne kadar süre sürdüreceğiniz. Varsayılan 60. | Uzun süre + çok kullanıcı = ağır test; yetkilendirme gerekir. |
| **iterations** | 0 = süreye göre; >0 = kullanıcı başına N döngü sonra dur. | Kullanıcı başına sabit iş yükü. Varsayılan 0. | >0 ise tüm kullanıcılar N döngüyü bitirince test biter (duration'tan önce olabilir). |
| **think_time_ms** | Kullanıcı başına istekler arası bekleme (ms). | Kullanıcı "düşünme süresi" simülasyonu; yüksek = düşük istek hızı. Varsayılan 0. | 0 = maksimum verim; yükü artırır. |
| **scenario** | `constant` \| `gradual` \| `spike`. constant = baştan tüm kullanıcılar; gradual = doğrusal ramp sonra tut; spike = taban + ortada ani artış. | Gerçek senaryoya uygun desen (sabit, ramp, spike). | spike için spike_users ve spike_duration_seconds gerekir. |
| **spike_users**, **spike_duration_seconds** | Spike sırasında ek kullanıcı ve spike penceresi (yalnızca spike senaryosu). | Ani artış ve toparlanma testi (örn. flaş satış). | Senaryo spike değilse yok sayılır. |
| **sla_p95_ms**, **sla_p99_ms**, **sla_error_rate_pct** | İsteğe bağlı. Yük testinde: raporda ihlaller listelenir; stres testinde: aşılınca dur. | Kabul edilebilir gecikme ve hata oranı; SLO'ları zorunlu kılmak. | Verilmezse raporda SLA kontrolü yapılmaz. |

### Stres testi config (YAML anahtarları)

| Anahtar | Anlamı | Neden kullanılır | Uyarılar / notlar |
|---------|--------|------------------|-------------------|
| **sla_p95_ms**, **sla_p99_ms**, **sla_error_rate_pct**, **sla_timeout_rate_pct** | Eşikler; herhangi biri aşılınca stres testi **durur**. | SLO altında maksimum yükü bulmak; kırılma noktasını tespit. | Zorunlu; SLO'nuza uygun değerler seçin. |
| **initial_users**, **step_users**, **step_interval_seconds**, **max_users** | Fazlı ramp: initial_users'tan başla, her step_interval_seconds'ta step_users ekle, max_users'a kadar. | Doğrusal aşırı yükleme: yük artarken sistemin nasıl bozulduğunu görmek. | **SLA ihlali veya max_users'a ulaşana kadar yükü artırır; yalnızca yetkili hedeflerde kullanın.** |
| **scenario** | `linear_overload` \| `spike_stress` \| `soak_stress`. | linear = ramp; spike = ani yüksek yük; soak = taban sonra ramp. | spike_stress spike_users, spike_hold_seconds; soak_stress soak_users, soak_duration_seconds kullanır. |
| **spike_users**, **spike_hold_seconds** | spike_stress için: ek kullanıcı ve tutma süresi. | Ani trafik spike'ı testi. | Yalnızca senaryo spike_stress iken kullanılır. |
| **soak_users**, **soak_duration_seconds** | soak_stress için: taban yük ve soak süresi (ramp öncesi). | Önce sürdürülen taban, sonra stres. | Yalnızca senaryo soak_stress iken kullanılır. |
| **think_time_ms** | İstekler arası gecikme (ms). | Düşük = yüksek istek hızı. Varsayılan 0. | 0 = maksimum yük. |

---

## Raporlar

**Yük testi raporu:** Tek dosya HTML, tam çevrimdışı (CDN yok). Kurumsal pano: Yönetici Özeti, Test Senaryosu Özeti, KPI kartları (toplam istek, TPS, P95/P99, başarı/hata oranı), Test Kararı, performans grafikleri (TPS, ortalama/P95 gecikme, hata oranı zaman serisi), yanıt süresi dağılımı, SLA ihlalleri, endpoint performans tablosu, ham veri (açılır, >10k istekte sayfalı). Grafikler `templates/vendor/echarts.min.js` ile gömülü ECharts kullanır.

**Stres testi raporu:** Aynı tasarım; Kırılma Noktası ve Maksimum Sürdürülebilir Yük KPI'ları, Sistem Davranış Özeti (yönetici/CISO), yük vs P95/P99 ve hata oranı eğrileri, faz sonuçları tablosu.

**JUnit ve JSON raporları:** `--junit path.xml` ve/veya `--json path.json` ile CI uyumlu JUnit XML (SLA ihlalleri = başarısız test) ve makine okunabilir JSON metrikleri üretilir.

**Günlük:** `DELI_LOG_LEVEL` (örn. `DEBUG`, `INFO`) ve isteğe bağlı `DELI_LOG_FORMAT=json` ile yapılandırılabilir.


---

## Geliştirici

- **E-posta**: [cumakurt@gmail.com](mailto:cumakurt@gmail.com)
- **LinkedIn**: [cuma-kurt-34414917](https://www.linkedin.com/in/cuma-kurt-34414917/)
- **GitHub**: [cumakurt](https://github.com/cumakurt)

---

## Lisans

GNU General Public License v3.0 veya sonrası (GPL-3.0-or-later). Tam metin için [LICENSE](LICENSE) dosyasına bakın.

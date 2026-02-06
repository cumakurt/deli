# deli 🥪

**deli** is a high-performance, lightweight, and modern load testing engine. It focuses on speed, low resource usage, and developer experience.

**Language:** [English](README.md) | [Türkçe](README.tr.md)

---

## 🚀 Features

*   **High Performance:**
    *   **Async I/O:** Asynchronous architecture built on `asyncio` and `httpx` (HTTP/2 support).
    *   **uvloop:** 2–4x faster event loop (automatically enabled on Python 3.12+).
    *   **Low Overhead:** Optimized memory usage (`__slots__`), string cache, and batch processing — can handle 10,000+ requests per second on a single core.
    *   **Zero-Allocation Paths:** Minimal object creation on the hot path.
*   **Smart Metrics:**
    *   **T-Digest:** Memory-efficient, high-accuracy streaming percentile calculation (P50, P95, P99).
    *   **Low Memory:** Fixed-size ring buffer keeps memory usage independent of test duration.
    *   **Real-time Dashboard:** Live terminal dashboard with low resource usage.
*   **Easy to Use:**
    *   **Postman Support:** Runs Postman Collection v2.1 files directly.
    *   **YAML Configuration:** Simple, readable test scenario definitions.
    *   **Single-File Report:** Shareable, offline-capable HTML reports with interactive charts.
*   **Advanced Scenarios:**
    *   **Stress Test:** Phased tests that automatically detect breaking points and bottlenecks.
    *   **SLA Validation:** Set thresholds for P95, error rate, etc., with automatic fail.
    *   **CI/CD Integration:** JUnit XML and JSON output formats.

---

## Legal and responsible use

**Use only on targets you are authorized to test.** Run load or stress tests **only** against systems, APIs, or resources you own or have **explicit written permission** from the owner. Unauthorized testing may violate computer misuse laws, terms of service, and can constitute abuse or denial of service.

- **Responsibility:** You alone are responsible for where and how you use this tool. Developers and contributors accept no liability for misuse, damage, or legal consequences.
- **Legal compliance:** Comply with all applicable laws (criminal, civil, contractual) in your jurisdiction. Obtain written permission before testing third-party or production systems. Do not cause unavailability or harm to systems you are not authorized to test.
- **Warning:** The tool can generate high request volume. Unauthorized use may lead to legal action, account termination, or liability. Use only for legitimate capacity planning, performance validation, and authorized testing.
- **No warranty:** Software is provided "as is"; no warranty. See [License](LICENSE).

---

## Requirements

- Python 3.11+
- Postman Collection v2.1 (JSON export) — only when using `-c`

---

## 📦 Installation

```bash
# From project root
pip install -e .

# Or with requirements
pip install -r requirements.txt && pip install -e .

# With virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -e .
```

---

## ⚡ Quick start

### 1. Run a simple load test

```bash
# With Postman collection
deli -c my_collection.json --users 50 --duration 60

# With config file
deli -c my_collection.json -f config.yaml

# Single URL test (no Postman)
deli -m https://httpbin.org/get --users 100 --duration 30
```

### 2. Example config (`config.yaml`)

```yaml
users: 100               # Number of concurrent virtual users
ramp_up_seconds: 10      # Gradual load ramp-up time
duration_seconds: 60     # Test duration
scenario: gradual        # constant, gradual, spike
think_time_ms: 50        # Delay between requests

# SLA (Service Level Agreement) targets
sla_p95_ms: 500          # P95 must be < 500ms
sla_error_rate_pct: 1.0  # Error rate must be < 1%
```

### 3. Stress test mode

Use stress test mode to find system limits:

```bash
deli -c my_collection.json -f stress_config.yaml --stress
```

**Example `stress_config.yaml`:**

```yaml
scenario: linear_overload
initial_users: 10
step_users: 10           # Users added each step
step_interval_seconds: 10 # Step duration
max_users: 1000          # Maximum user limit

# Breaking point thresholds
sla_p95_ms: 1000
sla_error_rate_pct: 5.0
```

---

## CLI reference

| Option | Short | Description |
|--------|-------|-------------|
| **--collection** | **-c** | Path to Postman Collection v2.1 JSON (required in load test if -m not used; required in stress test if target is Postman) |
| **--config** | **-f** | Path to YAML config (optional in load test: can omit and use --users, --duration etc.; required in stress test) |
| **--output** | **-o** | Report output path (file or directory). Default: `report.html` (load) or `stress_report.html` (stress) |
| **--env** | **-e** | Collection env var: `KEY=VALUE`. Repeatable. Only with -c (Postman) |
| **--manual-url** | **-m** | Manual target URL: run only against this URL (no Postman). Use with -f and -o |
| **--stress** | **-s** | Run stress test mode. -f must point to stress config; target via -c or -m |
| **--no-live** | | Disable live Rich panel (headless; suitable for CI/Docker) |
| **--junit** | | Also write JUnit XML report to PATH (CI: Jenkins, GitLab, etc.) |
| **--json** | | Also write JSON report to PATH (machine-readable metrics) |
| **--version** | **-v** | Show version and exit |

**Config overrides** (when given, override values from -f YAML):

| Option | Description |
|--------|-------------|
| **--users** | Virtual user count |
| **--duration** | Test duration (seconds) |
| **--ramp-up** | Ramp-up time (seconds) |
| **--scenario** | `constant`, `gradual`, or `spike` |
| **--think-time** | Delay between requests (ms) |
| **--iterations** | Loops per user (0 = by duration) |
| **--spike-users**, **--spike-duration** | Extra users and duration for spike scenario |
| **--sla-p95**, **--sla-p99**, **--sla-error-rate** | SLA thresholds |

---

## Usage examples

### Postman collection with config

```bash
deli -c path/to/collection.json -f config.yaml -o report.html
```

### Environment variables (`-e`)

```bash
deli -c collection.json -f config.yaml -e base_url=https://api.example.com -o report.html
```

### Config overrides (CLI)

```bash
deli -m https://api.example.com/health -f config.yaml -o report.html --users 80 --no-live
deli -m https://httpbin.org/get -o report.html --users 5 --duration 10 --no-live
```

### Headless (`--no-live`)

```bash
deli -c collection.json -f config.yaml -o report.html --no-live
```

### Manual URL mode (`-m`) — single URL without Postman

```bash
deli -m https://api.example.com/health -f config.yaml -o report.html
```

### Stress test (`-s`)

```bash
deli -s -f stress_config.yaml -c collection.json -o stress_report.html
deli -s -f stress_config.yaml -m https://api.example.com/health -o stress_report.html
```

For more examples and scenario configs, see [examples/README.md](examples/README.md).

---

## Configuration reference

### Load test config (used without -s)

| Key | Description | Default |
|-----|-------------|---------|
| users | Virtual user count | 10 |
| ramp_up_seconds | Ramp-up time (gradual scenario) | 10 |
| duration_seconds | Test duration (seconds) | 60 |
| iterations | 0 = by duration; >0 = N loops per user | 0 |
| think_time_ms | Delay between requests (ms) | 0 |
| scenario | constant \| gradual \| spike | constant |
| spike_users | Extra users during spike | 0 |
| spike_duration_seconds | Spike phase duration | 0 |
| sla_p95_ms | SLA P95 (ms); report violations | - |
| sla_p99_ms | SLA P99 (ms) | - |
| sla_error_rate_pct | Max error % | - |

### Stress test config (used with -s)

| Key | Description | Example |
|-----|-------------|---------|
| sla_p95_ms | P95 threshold (ms); stop when exceeded | 500 |
| sla_p99_ms | P99 threshold (ms) | 1000 |
| sla_error_rate_pct | Max error %; stop when exceeded | 1.0 |
| sla_timeout_rate_pct | Max timeout % | 5.0 |
| initial_users | Initial concurrent users | 5 |
| step_users | Users added per phase | 5 |
| step_interval_seconds | Duration per phase (seconds) | 30 |
| max_users | Maximum user limit | 200 |
| scenario | linear_overload \| spike_stress \| soak_stress | linear_overload |
| spike_users, spike_hold_seconds | Spike phase (spike_stress) | 50, 30 |
| soak_users, soak_duration_seconds | Soak phase (soak_stress) | 10, 60 |

---

## Reports

**Load test report:** Single-file HTML, fully offline (no CDN). Includes summary, scenario summary, KPI cards (total requests, TPS, P95/P99, success/error rate), test verdict, performance charts (TPS, latency, error rate over time), response time distribution, SLA violations, endpoint table, and raw data (paginated for >10k requests). Charts use embedded ECharts.

**Stress test report:** Same layout; adds Breaking Point and Max Sustainable Load KPIs, system behavior summary, load vs P95/P99 and error rate curves, phase results table.

**JUnit and JSON:** Use `--junit path.xml` and/or `--json path.json` for CI-friendly JUnit XML (SLA violations = failed tests) and machine-readable JSON metrics.

**Logging:** Configurable via `DELI_LOG_LEVEL` (e.g. `DEBUG`, `INFO`) and optional `DELI_LOG_FORMAT=json`.

---

## 📊 Performance notes

`deli` includes aggressive performance optimizations. See [PERFORMANCE.md](PERFORMANCE.md) for details.

Key optimizations:
- **GC disabled:** Garbage collector is disabled during the test (reduces latency spikes).
- **Batch processing:** Results are consumed and processed in batches from the queue.
- **Lazy metrics:** Histogram data is computed only at report time.

---

## 🛠 Development

```bash
# Run linter
ruff check .

# Run tests
pytest tests/
```

---

## Developer

- **Email:** [cumakurt@gmail.com](mailto:cumakurt@gmail.com)
- **LinkedIn:** [cuma-kurt-34414917](https://www.linkedin.com/in/cuma-kurt-34414917/)
- **GitHub:** [cumakurt](https://github.com/cumakurt)

---

## License

GNU General Public License v3.0 or later (GPL-3.0-or-later). See [LICENSE](LICENSE) for the full text.

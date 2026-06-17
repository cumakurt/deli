# deli

**deli** is a high-performance, lightweight, and modern load testing engine. It focuses on speed, low resource usage, and developer experience.

**Language:** [English](README.md) | [Türkçe](README.tr.md)

---

## Features

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

## Installation

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

## Quick start

The fastest way to validate an installation is a short manual-URL smoke run against a public endpoint you are allowed to test:

```bash
deli -m https://httpbin.org/get -o report.html --users 5 --duration 10 --no-live
```

This starts 5 virtual users for 10 seconds, sends GET requests to the URL, and writes `report.html`. Open the report in a browser to see TPS, latency percentiles, and per-endpoint stats.

### 1. Load test with a Postman collection

Export your API as Postman Collection v2.1 JSON, then point `deli` at it with a YAML config that defines users, duration, and scenario:

```bash
deli -c path/to/collection.json -f config.yaml -o report.html
```

Each virtual user replays the requests in the collection (folders included). Use `-e` to override `{{variables}}` without editing the file:

```bash
deli -c collection.json -f config.yaml \
  -e base_url=https://staging.example.com \
  -e api_key=your-token \
  -o report.html
```

Load a Postman Environment file when your collection relies on many variables:

```bash
deli -c collection.json -E staging.postman_environment.json -f config.yaml -o report.html
```

CLI `-e` values override the environment file.

### 2. Load test without Postman (single URL)

When you only need to hammer one endpoint (health check, gateway, static route), use `-m`:

```bash
deli -m https://api.example.com/health -f config.yaml -o report.html
```

You can skip `-f` and pass everything on the command line (defaults: 10 users, 60 s, `constant`):

```bash
deli -m https://httpbin.org/get -o report.html --users 100 --duration 30 --scenario gradual --ramp-up 10
```

### 3. Example config (`config.yaml`)

```yaml
users: 100               # Concurrent virtual users at peak
ramp_up_seconds: 10      # Time to reach full user count (gradual scenario)
duration_seconds: 60     # How long the test runs after ramp-up
scenario: gradual        # constant | gradual | spike
think_time_ms: 50        # Pause between requests per user (ms); simulates user think time

# Optional SLA — violations appear in the HTML report verdict
sla_p95_ms: 500
sla_p99_ms: 1000
sla_error_rate_pct: 1.0
```

| Scenario | Behavior |
|----------|----------|
| `constant` | All users start immediately and run for `duration_seconds`. |
| `gradual` | Users ramp linearly over `ramp_up_seconds`, then hold for the remainder of `duration_seconds`. |
| `spike` | Baseline load, then `spike_users` extra users for `spike_duration_seconds`, then back to baseline. |

### 4. Collection verification (`--smoke-test`)

Before a full load run, verify that the collection and environment resolve correctly:

```bash
deli -c collection.json -E staging.postman_environment.json --smoke-test -o smoke_report.html
```

This runs a lightweight check: 5 users, one iteration each. Use it after export changes or in a deploy pipeline before heavier tests.

### 5. Stress test mode

Stress mode ramps load in phases until an SLA threshold is breached, then stops and reports the breaking point:

```bash
deli -s -f stress_config.yaml -c collection.json -o stress_report.html
deli -s -f stress_config.yaml -m https://api.example.com/health -o stress_report.html
```

**Example `stress_config.yaml`:**

```yaml
scenario: linear_overload
initial_users: 10
step_users: 10              # Users added each phase
step_interval_seconds: 30   # Duration of each phase
max_users: 500              # Hard cap on concurrent users

sla_p95_ms: 1000            # Stop when P95 exceeds this (ms)
sla_p99_ms: 2000
sla_error_rate_pct: 5.0
sla_timeout_rate_pct: 10.0
```

The stress report adds **Breaking Point** and **Max Sustainable Load** KPIs plus a phase-by-phase table.

### 6. Recommended workflow

| Step | Goal | Example |
|------|------|---------|
| 1. Smoke | Confirm endpoints respond | `deli -c collection.json --smoke-test -o smoke.html` |
| 2. Baseline | Measure normal traffic | `deli -f examples/config_load_baseline.yaml -c collection.json -o baseline.html` |
| 3. Spike / soak | Test surge and endurance | `deli -f examples/config_spike.yaml -c collection.json -o spike.html` |
| 4. Stress | Find capacity limit | `deli -s -f stress_config.yaml -c collection.json -o stress.html` |

Ready-made configs live in [examples/](examples/). See [examples/README.md](examples/README.md) for a scenario table.

---

## CLI reference

| Option | Short | Description |
|--------|-------|-------------|
| **--collection** | **-c** | Path to Postman Collection v2.1 JSON (required in load test if -m not used; required in stress test if target is Postman) |
| **--config** | **-f** | Path to YAML config (optional in load test: can omit and use --users, --duration etc.; required in stress test) |
| **--output** | **-o** | Report output path (file or directory). Default: `report.html` (load) or `stress_report.html` (stress) |
| **--env** | **-e** | Collection env var: `KEY=VALUE`. Repeatable. Overrides environment file. Only with `-c` |
| **--environment** | **-E** | Path to Postman Environment JSON. Used with `-c`; `-e` overrides file values |
| **--manual-url** | **-m** | Manual target URL: run only against this URL (no Postman). Use with `-f` and `-o` |
| **--stress** | **-s** | Run stress test mode. `-f` must point to stress config; target via `-c` or `-m` |
| **--smoke-test** | | Run a 5-user, one-iteration verification test (collection/environment sanity check) |
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

The sections below walk through common tasks end to end: what each command does, when to use it, and what to expect in the report.

### 1. Postman collection load test

**When:** Your API flow is already defined in Postman and you want repeatable load against all requests in the collection.

**Basic run** — config defines users, duration, and scenario; default output is `report.html` in the current directory:

```bash
deli -c path/to/collection.json -f config.yaml
```

**Explicit report path:**

```bash
deli -c path/to/collection.json -f config.yaml -o report.html
```

**Report directory** — if `-o` points to a folder, `deli` creates `report.html` inside it (useful for dated runs):

```bash
deli -c path/to/collection.json -f config.yaml -o ./reports/2026-06-17/
```

**Paths with spaces** — quote the collection path:

```bash
deli -c "/home/user/Downloads/My API.postman_collection.json" -f config.yaml -o report.html
```

**Built-in sample** — try the repo examples without preparing your own collection:

```bash
deli -c examples/sample_collection.json -f examples/config_smoke.yaml -o report_smoke.html --no-live
```

**What to check in the report:** Test Verdict (pass/fail if SLA set), TPS over time, P95/P99 latency, endpoint table (slowest routes first), and SLA violation list.

---

### 2. Environment variables (`-e`) and environment file (`-E`)

**When:** The collection uses `{{base_url}}`, `{{api_key}}`, or other Postman variables and you need different targets per run without editing JSON.

**Single override:**

```bash
deli -c collection.json -f config.yaml -e base_url=https://api.example.com -o report.html
```

**Multiple overrides** — repeat `-e`; later values do not override earlier keys:

```bash
deli -c collection.json -f config.yaml \
  -e base_url=https://staging.example.com \
  -e api_key=secret123 \
  -e timeout=5000 \
  -o report.html
```

**Postman Environment file** — load all variables from an exported environment, then override specific keys with `-e`:

```bash
deli -c collection.json \
  -E staging.postman_environment.json \
  -e base_url=https://hotfix.example.com \
  -f config.yaml \
  -o report.html
```

**Note:** Secrets passed via `-e` may appear in process listings; prefer environment files with restricted permissions in production pipelines.

---

### 3. Collection smoke test (`--smoke-test`)

**When:** After exporting a collection, changing environment variables, or before a long soak test — confirm every request resolves and returns without running full load.

```bash
deli -c collection.json -E staging.postman_environment.json --smoke-test -o smoke_report.html
```

Runs 5 virtual users with one iteration each. Failures surface quickly in the terminal and in `smoke_report.html`. Pair with CI:

```bash
deli -c collection.json --smoke-test -o smoke_report.html --junit ci/smoke.xml --no-live
```

---

### 4. Config overrides from the CLI

**When:** You have a shared YAML config but need to tweak one run (more users, longer duration, different scenario) without duplicating files.

CLI flags override matching keys in `-f` YAML. Example — bump users to 80 for a single staging run:

```bash
deli -m https://api.example.com/health -f config.yaml -o report.html --users 80 --no-live
```

**Extend duration to 2 minutes:**

```bash
deli -c collection.json -f config.yaml -o report.html --duration 120 --no-live
```

**Switch to gradual ramp:**

```bash
deli -m https://httpbin.org/get -f config.yaml -o report.html --scenario gradual --ramp-up 30 --no-live
```

**No config file** — all parameters on the command line (defaults: 10 users, 60 s, `constant`):

```bash
deli -m https://httpbin.org/get -o report.html --users 5 --duration 10 --no-live
deli -c collection.json -o report.html --users 20 --duration 30 --scenario gradual --ramp-up 15 --no-live
```

**SLA from CLI** — enforce thresholds without editing YAML:

```bash
deli -c collection.json -f config.yaml -o report.html \
  --sla-p95 400 --sla-p99 800 --sla-error-rate 0.5
```

---

### 5. Headless mode (`--no-live`)

**When:** CI runners, Docker, cron jobs, or any environment without a TTY. Disables the live Rich dashboard; metrics print once per second to stdout.

```bash
deli -c collection.json -f config.yaml -o report.html --no-live
```

Typical CI step:

```bash
deli -c collection.json -f examples/config_smoke.yaml \
  -o report.html \
  --junit test-results/deli.xml \
  --json test-results/deli.json \
  --no-live
```

JUnit marks SLA violations as failed tests; JSON feeds dashboards or custom gates.

---

### 6. Load scenarios (YAML)

Each scenario answers a different performance question. Save separate YAML files per scenario for reproducible runs.

#### Constant load

**Question:** How does the system behave under steady, fixed concurrency?

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

#### Gradual ramp

**Question:** Can the system absorb a smooth traffic increase without latency spikes at startup?

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

#### Spike

**Question:** What happens during a sudden surge (flash sale, viral event) and does the system recover?

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

During the spike window, effective concurrency is `users + spike_users` (50 in this example).

#### SLA validation

**Question:** Did the run meet our SLOs? Violations are listed in the report verdict.

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

#### Ready-made configs in `examples/`

| File | Purpose |
|------|---------|
| `config_smoke.yaml` | Minimal load; post-deploy sanity check |
| `config_load_baseline.yaml` | Normal expected traffic; regression baseline |
| `config_load_stress.yaml` | Heavy constant load toward capacity |
| `config_spike.yaml` | Sudden traffic surge |
| `config_soak.yaml` | Long endurance run; leaks and degradation |
| `config_ramp_gradual.yaml` | Smooth 0 → target user ramp |

```bash
deli -f examples/config_load_baseline.yaml -c examples/sample_collection.json -o report_baseline.html --no-live
```

---

### 7. Manual URL mode (`-m`)

**When:** Quick health-check or single-endpoint throughput test without maintaining a Postman collection.

```bash
deli -m https://api.example.com/health -f config.yaml -o report.html
```

**Different path on the same host:**

```bash
deli -m https://api.example.com/v1/users -f config.yaml -o report_manual.html
```

**Headless single-URL benchmark:**

```bash
deli -m https://httpbin.org/get -f config.yaml -o report.html --no-live
```

With `-m`, `-c` and `-e` are ignored; only the given URL is exercised.

---

### 8. Stress test (`-s`)

**When:** You need the maximum sustainable load or the exact point where latency or errors exceed SLOs. Stress mode is separate from load test: different config schema, phased ramp, automatic stop on breach.

**Postman target:**

```bash
deli -s -f stress_config.yaml -c collection.json -o stress_report.html
```

**Manual URL target:**

```bash
deli -s -f stress_config.yaml -m https://api.example.com/health -o stress_report.html
```

**Output directory:**

```bash
deli -s -f stress_config.yaml -c collection.json -o ./stress_results/
```

**Headless stress run:**

```bash
deli -s -f stress_config.yaml -c collection.json -o stress_report.html --no-live
```

---

### 9. Stress scenarios

#### Linear overload

Users increase step by step until an SLA breaks or `max_users` is reached. Identifies the load level at which P95 or error rate degrades.

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

#### Spike stress

Applies a high concurrent spike for `spike_hold_seconds` to test burst handling.

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

#### Soak then ramp

Runs sustained low load (`soak_users` for `soak_duration_seconds`), then ramps up — useful for catching memory leaks before overload.

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

### 10. Docker

**Build the image:**

```bash
docker build -t deli .
```

The container runs as a non-root user. Mount a host directory and pass an **absolute** output path inside the container. Use `--user $(id -u):$(id -g)` so the report is writable on the host.

**Quick manual-URL run — report in current directory:**

```bash
docker run --rm --user $(id -u):$(id -g) -v $(pwd):/data deli \
  -m https://httpbin.org/get \
  -f /app/examples/config.yaml \
  -o /data/report.html \
  --no-live
```

**Your own collection and config:**

```bash
docker run --rm --user $(id -u):$(id -g) -v $(pwd):/data -v $(pwd)/reports:/tmp deli \
  -c /data/collection.json \
  -f /data/config.yaml \
  -o /tmp/report.html \
  --no-live
# => reports/report.html on the host
```

**Stress test with bundled example config:**

```bash
docker run --rm --user $(id -u):$(id -g) -v $(pwd)/reports:/tmp deli \
  -s -m https://httpbin.org/get \
  -f /app/examples/stress_config.yaml \
  -o /tmp/stress_report.html \
  --no-live
```

**Override config from CLI inside Docker:**

```bash
docker run --rm --user $(id -u):$(id -g) -v $(pwd):/data deli \
  -m https://httpbin.org/get \
  -f /app/examples/config.yaml \
  -o /data/report.html \
  --users 50 --duration 20 --scenario gradual --ramp-up 10 \
  --no-live
```

---

### 11. Full load config reference example

```yaml
# config.yaml — load test
users: 25
ramp_up_seconds: 15
duration_seconds: 300
iterations: 0          # 0 = run for duration; >0 = N loops per user then stop
think_time_ms: 200
scenario: gradual

# Spike keys (only when scenario: spike)
spike_users: 50
spike_duration_seconds: 20

# SLA (optional — violations listed in report)
sla_p95_ms: 400
sla_p99_ms: 800
sla_error_rate_pct: 0.5
```

---

### 12. Full stress config reference example

```yaml
# stress_config.yaml — use with -s
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

# For spike_stress
spike_users: 60
spike_hold_seconds: 30

# For soak_stress
soak_users: 15
soak_duration_seconds: 90
```

For the complete scenario catalog and copy-paste commands, see [examples/README.md](examples/README.md).

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

## Performance notes

`deli` includes aggressive performance optimizations. See [PERFORMANCE.md](PERFORMANCE.md) for details.

Key optimizations:
- **GC disabled:** Garbage collector is disabled during the test (reduces latency spikes).
- **Batch processing:** Results are consumed and processed in batches from the queue.
- **Lazy metrics:** Histogram data is computed only at report time.

---

## Development

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

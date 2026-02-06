# Example configs

Ready-to-use load test configs for common industry scenarios. Use with a Postman collection or manual URL. **Use only on systems you own or have explicit permission to test.** See the main [README](README.md#legal-and-responsible-use) for legal and responsible use.

| Config | Scenario | Purpose |
|--------|----------|---------|
| `config_smoke.yaml` | Smoke | Minimal load, quick validation (CI/deploy check). |
| `config_load_baseline.yaml` | Baseline load | Normal expected traffic; establish baseline. |
| `config_load_stress.yaml` | High load | Heavy constant load toward capacity. |
| `config_spike.yaml` | Spike | Sudden traffic surge; validate recovery. |
| `config_soak.yaml` | Soak / endurance | Long sustained load; find leaks/degradation. |
| `config_ramp_gradual.yaml` | Gradual ramp | Smooth increase from 0 to target users. |
| `config.yaml` | Generic | Simple default (e.g. 100 users, 5 min). |

**Run examples** (replace `-c collection.json` with `-m https://...` for single URL):

```bash
# Smoke test
deli -f examples/config_smoke.yaml -c examples/sample_collection.json -o report_smoke.html

# Baseline load
deli -f examples/config_load_baseline.yaml -c examples/sample_collection.json -o report_baseline.html

# Spike test
deli -f examples/config_spike.yaml -c examples/sample_collection.json -o report_spike.html

# Soak test (1 hour)
deli -f examples/config_soak.yaml -c examples/sample_collection.json -o report_soak.html

# Gradual ramp
deli -f examples/config_ramp_gradual.yaml -c examples/sample_collection.json -o report_ramp.html
```

Stress tests use a separate config format; see `stress_config.yaml` and the main README (stress test section).

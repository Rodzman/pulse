# pulse

[![ci](https://github.com/Rodzman/pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/Rodzman/pulse/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/github/license/Rodzman/pulse)

**Zero-dependency HTTP endpoint health checker.** One file, stdlib only, exits non-zero when something is down — built for cron jobs, CI pipelines, and Raspberry Pis.

```text
pulse · 2026-08-23 14:00:00
OK   website         200    142ms
OK   api-health      200    318ms
FAIL legacy-redirect 200    105ms
      └─ got status 200, expected 301

2/3 healthy
```

## Why pulse

- **Zero dependencies** — pure Python stdlib, nothing to `pip install`, nothing to break
- **Single file** — drop `pulse.py` anywhere, read the whole tool in ten minutes
- **Pipeline-native** — meaningful exit codes and JSON output instead of a dashboard login
- **Private by design** — your infrastructure list never leaves the machine it runs on

## Requirements

Python **3.11+** (uses the built-in `tomllib`). That's it.

## Quick start

```bash
git clone https://github.com/Rodzman/pulse.git && cd pulse
cp pulse.example.toml pulse.toml   # create your own config, then edit it
python3 pulse.py                   # run every check once
python3 pulse.py --loop            # monitor continuously (interval from config)
python3 pulse.py --json            # machine-readable output
```

## Configuration

Top-level keys in `pulse.toml`:

| Key           | Default  | Description                                   |
| ------------- | -------- | --------------------------------------------- |
| `interval`    | `60`     | Seconds between rounds in `--loop` mode       |
| `webhook_url` | _(none)_ | POSTs a JSON failure summary when checks fail |

Each endpoint gets an `[[endpoints]]` block:

| Option            | Default  | Description                                     |
| ----------------- | -------- | ----------------------------------------------- |
| `url`             | —        | Endpoint URL (**required**)                     |
| `name`            | `url`    | Display name                                    |
| `expect_status`   | `200`    | Expected HTTP status code                       |
| `expect_keyword`  | _(none)_ | Substring that must appear in the response body |
| `max_latency_ms`  | _(none)_ | Fail if response takes longer than this         |
| `timeout_seconds` | `5`      | Per-request timeout                             |

A check passes only if **all** configured assertions hold.

Your `pulse.toml` is git-ignored, so your endpoint list stays private.

## Exit codes

| Code | Meaning                   |
| ---- | ------------------------- |
| `0`  | All endpoints healthy     |
| `1`  | At least one check failed |

Config errors also exit non-zero with a message on stderr — safe to gate on unconditionally.

## Automation recipes

**Cron alerting** (every minute, log appended, failures leave a non-zero exit):

```cron
* * * * * cd /opt/pulse && python3 pulse.py >> /var/log/pulse.log 2>&1
```

**Post-deploy smoke test** in another repo's GitHub Actions workflow:

```yaml
- name: Smoke-test the new release
  run: |
    git clone --depth 1 https://github.com/Rodzman/pulse.git /tmp/pulse
    printf '[[endpoints]]\nurl = "https://my-app.example.com/healthz"\nexpect_keyword = "ok"\nmax_latency_ms = 1000\n' > /tmp/smoke.toml
    python3 /tmp/pulse/pulse.py -c /tmp/smoke.toml
```

Point `webhook_url` at a Slack or Discord incoming webhook and failures arrive as JSON:

```json
{
  "ts": "2026-08-23T14:03:11Z",
  "failed": [
    {
      "name": "api-health",
      "url": "https://api.example.com/healthz",
      "ok": false,
      "status_code": 503,
      "latency_ms": 412.7,
      "error": "got status 503, expected 200"
    }
  ],
  "healthy": 2,
  "total": 3
}
```

## Development

```bash
python3 -m unittest -v        # run the test suite
```

## Roadmap

See [`CHANGELOG.md`](CHANGELOG.md) — up next: TLS certificate-expiry warnings, SQLite history, Prometheus `/metrics` exporter.

## License

[MIT](LICENSE)

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned

- TLS certificate-expiry warnings
- SQLite history storage
- Prometheus `/metrics` exporter

## [0.1.0] - 2026-08-23

### Added

- HTTP health checks defined in TOML (`[[endpoints]]` blocks) with assertions on
  status code (`expect_status`), response body (`expect_keyword`), and latency
  budget (`max_latency_ms`)
- Concurrent execution of all checks via a thread pool
- `--loop` continuous mode with configurable `interval`
- `--json` machine-readable output mode
- Non-zero exit code when any check fails — cron/CI friendly
- Optional `webhook_url` receiving a JSON failure summary
- Unit test suite (`python3 -m unittest`)
- CI via GitHub Actions across Python 3.11, 3.12, and 3.13

[Unreleased]: https://github.com/Rodzman/pulse/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Rodzman/pulse/releases/tag/v0.1.0

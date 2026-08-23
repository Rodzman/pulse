# Changelog

All notable changes to **pulse** will be documented in this file.
This file is auto-generated from [Conventional Commits](https://www.conventionalcommits.org) —
write good commit messages; don't edit this file directly.

## [Unreleased]

### Added

- ship pulse.example.toml template instead of checked-in pulse.toml
- retries with jittered backoff + TLS certificate-expiry checks
- add resilient-api and cert-watch endpoints with retries and TLS warning

### CI

- auto-update CHANGELOG.md via git-cliff

### Fixed

- preserve newlines in changelog template
- smoke-test against local server instead of example.com
- hermetic smoke test; validate example config

### Miscellaneous

- update CHANGELOG.md [skip ci]
- update CHANGELOG.md [skip ci]
- update CHANGELOG.md [skip ci]
- update CHANGELOG.md [skip ci]

## [v0.1.0] - 2026-08-23


### Documentation

- expanded README, added changelog

### Other

- Initial commit
- pulse v0.1.0: zero-dependency HTTP health checker
- Add CI workflow for testing with multiple Python versions


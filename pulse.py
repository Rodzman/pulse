#!/usr/bin/env python3
"""
pulse — a zero-dependency endpoint health checker.

Runs HTTP checks defined in a TOML file, prints a report, optionally POSTs
a JSON failure summary to a webhook, and exits non-zero on failure so it
slots straight into cron jobs and CI pipelines.

v0.2.0 additions:
  * retries with jittered exponential backoff (transient failures only:
    timeouts, connection errors, HTTP 5xx / 429)
  * TLS certificate-expiry checking (fail if expired, warn near expiry)

Requires Python 3.11+ (stdlib tomllib). No third-party packages.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit("pulse requires Python 3.11+ (built-in tomllib)")

USER_AGENT = "pulse-healthchecker/0.2"
MAX_BODY_BYTES = 65536
MAX_BACKOFF_SECONDS = 30.0


@dataclass
class CheckResult:
    name: str
    url: str
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None = None
    warnings: str | None = None
    attempts: int = 1


def _merge(*parts: str | None) -> str | None:
    """Join non-empty fragments with '; ' — None if everything is empty."""
    joined = "; ".join(p for p in parts if p)
    return joined or None


def evaluate(
    *,
    name,
    url,
    code,
    body,
    expect_status,
    keyword,
    max_latency_ms,
    latency_ms,
):
    """Pure decision logic — easy to unit-test. TLS handled separately."""
    problems = []
    if code != expect_status:
        problems.append(f"got status {code}, expected {expect_status}")
    if keyword and keyword not in body:
        problems.append(f"keyword {keyword!r} not found in response")
    if max_latency_ms is not None and latency_ms > max_latency_ms:
        problems.append(f"latency {latency_ms:.0f} ms > limit {max_latency_ms} ms")
    return CheckResult(
        name=name, url=url, ok=not problems, status_code=code,
        latency_ms=latency_ms, error=_merge(*problems),
    )


def _cert_not_after(host: str, port: int, timeout_s: float) -> datetime:
    """TLS handshake; returns the certificate's notAfter as an aware UTC datetime."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # we're reading the cert, not validating it
    with socket.create_connection((host, port), timeout=timeout_s) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise RuntimeError("server did not present a certificate")

    pem = (
        "-----BEGIN CERTIFICATE-----\n"
        + base64.encodebytes(der).decode("ascii")
        + "-----END CERTIFICATE-----\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as fh:
        fh.write(pem)
        path = fh.name
    try:
        # Long-standing stdlib trick for decoding certs without third-party libs
        decoded = ssl._ssl._test_decode_cert(path)
    finally:
        os.unlink(path)

    return datetime.strptime(
        decoded["notAfter"], "%b %d %H:%M:%S %Y %Z"
    ).replace(tzinfo=timezone.utc)


def _apply_tls(result: CheckResult, cfg: dict) -> CheckResult:
    """Attach certificate-expiry outcomes to a finished HTTP result."""
    warn_days = cfg.get("tls_warn_days")
    if warn_days is None or result.status_code is None:
        return result
    u = urlsplit(cfg["url"])
    if u.scheme != "https" or not u.hostname:
        return result

    timeout_s = float(cfg.get("timeout_seconds", 5))
    try:
        not_after = _cert_not_after(u.hostname, u.port or 443, timeout_s)
    except Exception as exc:  # never let TLS inspection break the check itself
        result.warnings = _merge(result.warnings, f"TLS check skipped ({exc})")
        return result

    days_left = (not_after - datetime.now(timezone.utc)).total_seconds() / 86400
    until = not_after.strftime("%Y-%m-%d")
    if days_left <= 0:
        result.ok = False
        result.error = _merge(result.error, f"TLS certificate expired (valid until {until})")
    elif days_left <= float(warn_days):
        result.warnings = _merge(
            result.warnings, f"TLS certificate expires in {int(days_left)} day(s) ({until})"
        )
    return result


def _is_transient(result: CheckResult) -> bool:
    """Only retry failures that plausibly resolve on their own."""
    return result.status_code is None or result.status_code >= 500 or result.status_code == 429


def probe_once(cfg: dict) -> CheckResult:
    """A single HTTP attempt — no retries, no TLS."""
    name = cfg.get("name") or cfg["url"]
    url = cfg["url"]
    expect_status = int(cfg.get("expect_status", 200))
    timeout_s = float(cfg.get("timeout_seconds", 5))
    keyword = cfg.get("expect_keyword")
    max_latency_ms = cfg.get("max_latency_ms")

    start = time.perf_counter()
    code, body = None, ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                code = resp.status
                body = resp.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            code = e.code
            body = e.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
    except Exception as exc:  # DNS failure, refused, timeout, bad URL…
        latency = (time.perf_counter() - start) * 1000
        return CheckResult(name=name, url=url, ok=False, status_code=None,
                           latency_ms=round(latency, 1), error=str(exc))

    latency = (time.perf_counter() - start) * 1000
    return evaluate(name=name, url=url, code=code, body=body,
                    expect_status=expect_status, keyword=keyword,
                    max_latency_ms=max_latency_ms, latency_ms=latency)


def check_endpoint(cfg: dict) -> CheckResult:
    """Full check policy: HTTP probes with retries, then TLS expiry."""
    if "url" not in cfg:
        sys.exit(f"error: endpoint block missing required key 'url': {cfg}")

    retries = max(0, int(cfg.get("retries", 0)))
    backoff = float(cfg.get("backoff_seconds", 1.0))

    result = probe_once(cfg)
    for attempt in range(2, retries + 2):
        if not _is_transient(result):
            break  # deterministic failure (404, keyword miss…) — retrying won't help
        delay = min(backoff * 2 ** (attempt - 2), MAX_BACKOFF_SECONDS)
        time.sleep(delay + random.uniform(0, backoff))  # jittered exponential backoff
        result = probe_once(cfg)
        result.attempts = attempt

    return _apply_tls(result, cfg)


def load_config(path: str) -> dict:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        sys.exit(
            f"error: config file not found: {path}\n"
            f"hint: copy the example config to get started:  cp pulse.example.toml {path}"
        )
    except tomllib.TOMLDecodeError as exc:
        sys.exit(f"error: invalid TOML in {path}: {exc}")


def notify_webhook(webhook_url: str, results: list[CheckResult]) -> None:
    """Best-effort POST of failures — alerting must never crash the monitor."""
    payload = json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "failed": [asdict(r) for r in results if not r.ok],
        "healthy": sum(r.ok for r in results),
        "total": len(results),
    }).encode()
    req = urllib.request.Request(webhook_url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def render_report(results: list[CheckResult]) -> str:
    lines, width = [], max(len(r.name) for r in results)
    for r in sorted(results, key=lambda x: (not x.ok, x.name)):
        icon = "OK  " if r.ok else "FAIL"
        code = str(r.status_code) if r.status_code is not None else "  -"
        lat = f"{r.latency_ms:.0f}ms" if r.latency_ms is not None else "  -"
        retried = f"  x{r.attempts}" if r.attempts > 1 else ""
        lines.append(f"{icon} {r.name:<{width}}  {code:>4}  {lat:>7}{retried}")
        if r.error:
            lines.append(f"      └─ error: {r.error}")
        if r.warnings:
            lines.append(f"      └─ warn:  {r.warnings}")
    return "\n".join(lines)


def run_once(cfg: dict, as_json: bool) -> bool:
    endpoints = cfg.get("endpoints", [])
    if not endpoints:
        sys.exit("error: no [[endpoints]] blocks found in config")

    with ThreadPoolExecutor(max_workers=min(len(endpoints), 16)) as pool:
        results = list(pool.map(check_endpoint, endpoints))

    if as_json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print(f"pulse · {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(render_report(results))
        down = sum(not r.ok for r in results)
        print(f"\n{len(results) - down}/{len(results)} healthy")

    webhook_url = cfg.get("webhook_url")
    if webhook_url and any(not r.ok for r in results):
        notify_webhook(webhook_url, results)

    return all(r.ok for r in results)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pulse", description=__doc__)
    ap.add_argument("-c", "--config", default="pulse.toml", help="path to TOML config")
    ap.add_argument("--loop", action="store_true", help="run continuously")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--version", action="version", version="pulse 0.2.0")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    interval = float(cfg.get("interval", 60))

    while True:
        healthy = run_once(cfg, as_json=args.json)
        if not args.loop:
            sys.exit(0 if healthy else 1)
        time.sleep(interval)


if __name__ == "__main__":
    main()
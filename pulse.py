#!/usr/bin/env python3
"""
pulse — a zero-dependency endpoint health checker.

Runs HTTP checks defined in a TOML file, prints a report, optionally POSTs
a JSON failure summary to a webhook, and exits non-zero on failure so it
slots straight into cron jobs and CI pipelines.

Requires Python 3.11+ (stdlib tomllib). No third-party packages.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit("pulse requires Python 3.11+ (built-in tomllib)")

USER_AGENT = "pulse-healthchecker/0.1"
MAX_BODY_BYTES = 65536


@dataclass
class CheckResult:
    name: str
    url: str
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None = None


def evaluate(*, name, url, code, body, expect_status, keyword, max_latency_ms, latency_ms) -> CheckResult:
    """Pure decision logic — easy to unit-test."""
    problems = []
    if code != expect_status:
        problems.append(f"got status {code}, expected {expect_status}")
    if keyword and keyword not in body:
        problems.append(f"keyword {keyword!r} not found in response")
    if max_latency_ms is not None and latency_ms > max_latency_ms:
        problems.append(f"latency {latency_ms:.0f} ms > limit {max_latency_ms} ms")
    return CheckResult(
        name=name, url=url, ok=not problems, status_code=code,
        latency_ms=latency_ms, error="; ".join(problems) if problems else None,
    )


def check_endpoint(cfg: dict) -> CheckResult:
    """Perform one HTTP check according to an [[endpoints]] block."""
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
            # Non-2xx raises; still treat it as a measurable outcome
            code = e.code
            body = e.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
    except Exception as exc:  # DNS failure, connection refused, timeout, bad URL…
        latency = (time.perf_counter() - start) * 1000
        return CheckResult(name=name, url=url, ok=False, status_code=None,
                           latency_ms=round(latency, 1), error=str(exc))

    latency = (time.perf_counter() - start) * 1000
    return evaluate(name=name, url=url, code=code, body=body,
                    expect_status=expect_status, keyword=keyword,
                    max_latency_ms=max_latency_ms, latency_ms=latency)


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
        lines.append(f"{icon} {r.name:<{width}}  {code:>4}  {lat:>7}")
        if r.error:
            lines.append(f"      └─ {r.error}")
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
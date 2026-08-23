# pulse

Zero-dependency HTTP endpoint health checker. One file, Python 3.11+, stdlib only.

## Quick start

    python3 pulse.py                 # run all checks once, exit 1 if anything is down
    python3 pulse.py --loop          # monitor continuously
    python3 pulse.py --json          # machine-readable output

## Exit codes

0 = all healthy · 1 = at least one check failed (perfect for cron/CI)

## Run tests

    python3 -m unittest test_pulse.py

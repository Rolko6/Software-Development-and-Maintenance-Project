#!/usr/bin/env python3
"""Compare POST /device-data latency across gateway security modes.

Work Package 5 evaluation harness. Measures the same request shape the
baseline harness measures (`scripts/baseline/measure_latency.py`'s
`device_data` target: `POST {url}/device-data`, timed from just before
the request is sent to just after its response body is fully read, one
bare `requests.post(...)` call per sample, no connection reuse across
samples) under two or more named "modes" -- normally the gateway's
crypto security mode (`off` / `enabled` / `required`, see
`gateway/app/metrics.py`'s `GATEWAY_SECURITY_MODE`) -- and reports the
delta between each mode and a reference mode.

This script cannot switch modes itself
--------------------------------------
It sends HTTP requests only; it never touches Docker, a container, or a
process. It cannot restart anything and does not try to. Switching the
target's security mode between phases is the operator's job, done one
of two ways:

1. **Same URL, switched between phases (default).** Pass one `--url`
   and two or more `--modes`. Before each phase after the first, the
   script pauses and prints the mode the target must now be running
   under; press Enter once it is (see "Switching the mode" below for
   how, given whatever the ML-KEM integration work has landed as its
   switch mechanism). Use `--no-interactive` only if you have arranged
   the timing some other way (e.g. a fixed sleep in an outer script) --
   without a pause, both phases would silently measure whatever mode
   happened to be active.
2. **One URL per mode, no switch needed.** If you have two (or three)
   already-running instances configured for different modes -- e.g.
   two local uvicorn processes on different ports, mirroring how
   `scripts/baseline/run_baseline.sh` runs the plaintext baseline on
   ports 18000/18001 -- pass `--target off=http://127.0.0.1:PORT1/device-data
   --target enabled=http://127.0.0.1:PORT2/device-data` instead of a
   shared `--url`. No pause is needed because nothing has to change
   mid-run; this is the more reliable option when it is available,
   since phase 1 and phase 2 no longer have to run at different times
   on a system whose load may have drifted in between.

`--target` entries always take precedence over `--url` for their mode.

Switching the mode
------------------
How to actually put the gateway into a given mode depends on the ML-KEM
integration this script's design predates in this repository's history
of concurrent work. As of this writing that work was still in progress
under `gateway/app/crypto/`; check that module (or its own docs) for the
authoritative mechanism -- an environment variable read at startup
(requiring a restart, hence phase pauses matter) and a runtime
admin/config endpoint are the two shapes such a switch commonly takes.
Record whichever one was actually used in `--mode-switch-method`; it is
carried into the JSON output so a reader of the results knows how
comparability was achieved rather than having to guess.

Comparable conditions
----------------------
For the comparison to mean anything, keep everything but the mode fixed
between phases: same host, same `--samples`/`--warmup`, same payload
shape, same Python (this script, run once, applies its own logic
identically to every phase), and -- if using a single restarted target
-- as little wall-clock gap as reasonably possible between phases so
background load on the machine has not drifted. See
`docs/validation/2026-09-15-measurement-method.md` for the full
discussion of what "comparable" means here and this repository's
remaining confounds (pure-Python ML-KEM, loopback vs container
networking, local uvicorn vs container Python version).

Method (per phase, per mode)
-----------------------------
`--warmup` requests are sent first and discarded, then `--samples`
requests are sent sequentially (one in flight at a time). A request
that raises `requests.exceptions.RequestException` counts as a failure
and is excluded from latency statistics; a non-2xx HTTP response is
still a fully timed, valid observation, not a failure.

Reported statistics, in milliseconds, per mode: count, min, mean,
median, p95 (nearest-rank), max, failures. Deltas are reported for every
non-reference mode against the reference mode (`--reference-mode`,
default: the first mode in `--modes`), both as an absolute difference in
milliseconds and as a percentage of the reference mode's value, for
each of min/mean/median/p95/max.

Exit status
-----------
Exits 1 if any phase had zero successful samples. Transport failures
alone (unlike the baseline harness) do not fail this script, since a
`required` security mode is expected to reject plaintext and callers
may deliberately probe a misconfigured mode; failure counts are still
reported and worth reading.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DEFAULT_JSON_OUT = Path(__file__).resolve().parent / "last-comparison.json"
DEFAULT_MODES = ["off", "enabled"]


def env_default(name: str, default, cast=str):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


class TargetAction(argparse.Action):
    """Parse repeated --target mode=url into a dict."""

    def __call__(self, parser, namespace, values, option_string=None):
        if "=" not in values:
            raise argparse.ArgumentError(
                self, f"expected mode=url, got {values!r}"
            )
        mode, _, url = values.partition("=")
        mode = mode.strip()
        url = url.strip()
        if not mode or not url:
            raise argparse.ArgumentError(
                self, f"expected mode=url with both parts non-empty, got {values!r}"
            )
        current = getattr(namespace, self.dest) or {}
        current[mode] = url
        setattr(namespace, self.dest, current)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare POST /device-data latency across gateway security "
            "modes (e.g. plaintext 'off' vs ML-KEM 'enabled'). Measures "
            "over HTTP only; never restarts anything -- see the module "
            "docstring for how to switch modes between phases."
        ),
    )
    parser.add_argument(
        "--url",
        default=env_default("EVAL_URL", None),
        help=(
            "Gateway device-data URL reused for every mode that has no "
            "--target override, e.g. http://127.0.0.1:18000/device-data "
            "(env EVAL_URL). Required unless --target covers every mode "
            "in --modes."
        ),
    )
    parser.add_argument(
        "--target",
        dest="targets",
        action=TargetAction,
        default=None,
        metavar="MODE=URL",
        help=(
            "Per-mode URL override, repeatable, e.g. "
            "--target off=http://127.0.0.1:18000/device-data "
            "--target enabled=http://127.0.0.1:18002/device-data. "
            "Takes precedence over --url for that mode; use this to "
            "compare two already-running instances with no mode switch "
            "or pause needed."
        ),
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=env_default(
            "EVAL_MODES", DEFAULT_MODES, lambda s: s.split(",")
        ),
        help=(
            "Ordered list of mode labels to measure and compare "
            "(default: off enabled). Labels are free text recorded in "
            "the report; they are not validated against the gateway's "
            "actual configured mode -- the operator is responsible for "
            "the target really being in the named mode when each phase "
            "runs."
        ),
    )
    parser.add_argument(
        "--reference-mode",
        default=None,
        help=(
            "Mode to compute deltas against (default: the first entry "
            "in --modes, typically the plaintext baseline)."
        ),
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=env_default("EVAL_SAMPLES", 50, int),
        help="Timed samples per mode (env EVAL_SAMPLES, default 50)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=env_default("EVAL_WARMUP", 5, int),
        help="Untimed warm-up requests per mode (env EVAL_WARMUP, default 5)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=env_default("EVAL_TIMEOUT", 5.0, float),
        help="Per-request timeout in seconds (env EVAL_TIMEOUT, default 5.0)",
    )
    parser.add_argument(
        "--device-id",
        default=env_default("EVAL_DEVICE_ID", "latency-eval-001"),
        help="device_id used in synthetic readings (default latency-eval-001)",
    )
    parser.add_argument(
        "--mode-switch-method",
        default=env_default(
            "EVAL_MODE_SWITCH_METHOD",
            "not recorded -- pass --mode-switch-method to document how "
            "the target's mode was actually changed between phases",
        ),
        help=(
            "Free-text description of how the mode was switched between "
            "phases (e.g. 'env var GATEWAY_SECURITY_MODE + uvicorn "
            "restart', or 'two separate instances, no switch'). Stored "
            "in the JSON output and printed in the report so results "
            "carry their own provenance."
        ),
    )
    parser.add_argument(
        "--interactive",
        dest="interactive",
        action="store_true",
        default=True,
        help=(
            "Pause and prompt before each phase after the first, for "
            "modes using the shared --url (default: on)."
        ),
    )
    parser.add_argument(
        "--no-interactive",
        dest="interactive",
        action="store_false",
        help=(
            "Do not pause between phases -- use only when timing is "
            "arranged some other way (e.g. every mode has its own "
            "--target and nothing needs to change mid-run)."
        ),
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=DEFAULT_JSON_OUT,
        help=f"Path to write machine-readable JSON results (default {DEFAULT_JSON_OUT})",
    )
    args = parser.parse_args(argv)

    args.targets = args.targets or {}
    if len(args.modes) < 2:
        parser.error("--modes needs at least two entries to produce a comparison")
    missing = [m for m in args.modes if m not in args.targets and not args.url]
    if missing:
        parser.error(
            "no URL for mode(s) "
            + ", ".join(missing)
            + " -- pass --url (shared) or --target MODE=URL for each"
        )
    if args.reference_mode is None:
        args.reference_mode = args.modes[0]
    elif args.reference_mode not in args.modes:
        parser.error(
            f"--reference-mode {args.reference_mode!r} is not in --modes {args.modes!r}"
        )
    return args


def percentile(ordered_values, pct: float):
    n = len(ordered_values)
    if n == 0:
        return None
    if n == 1:
        return ordered_values[0]
    rank = math.ceil(pct / 100.0 * n)
    rank = min(max(rank, 1), n)
    return ordered_values[rank - 1]


def compute_stats(latencies_ms):
    if not latencies_ms:
        return None
    ordered = sorted(latencies_ms)
    return {
        "count": len(ordered),
        "min_ms": round(ordered[0], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(percentile(ordered, 95), 3),
        "max_ms": round(ordered[-1], 3),
    }


def make_reading(device_id: str) -> dict:
    import random

    return {
        "device_id": device_id,
        "temperature": round(random.uniform(15.0, 30.0), 2),
    }


def run_phase(url: str, device_id: str, count: int, timeout: float):
    latencies = []
    failures = 0
    for _ in range(count):
        body = make_reading(device_id)
        start = time.perf_counter()
        try:
            response = requests.post(url, json=body, timeout=timeout)
            _ = response.content  # force full body read before stopping the clock
        except requests.exceptions.RequestException:
            failures += 1
            continue
        latencies.append((time.perf_counter() - start) * 1000.0)
    return latencies, failures


def resolve_url(mode: str, args: argparse.Namespace) -> str:
    return args.targets.get(mode) or args.url


def prompt_for_phase(mode: str, url: str, previous_mode: str | None):
    print()
    if previous_mode is not None:
        print(f"== Switch target to mode '{mode}' before continuing ==")
        print(f"   (previous phase measured mode '{previous_mode}')")
    else:
        print(f"== First phase: mode '{mode}' ==")
    print(f"   Target: POST {url}")
    input("   Press Enter once the target is confirmed running in this mode... ")


def format_stats_table(rows) -> str:
    header = f"{'mode':<12}{'count':>7}{'min_ms':>10}{'mean_ms':>10}{'median_ms':>11}{'p95_ms':>10}{'max_ms':>10}{'failures':>10}"
    lines = [header, "-" * len(header)]
    for row in rows:
        stats = row["stats"] or {}
        lines.append(
            f"{row['mode']:<12}"
            f"{stats.get('count', 0):>7}"
            f"{stats.get('min_ms', float('nan')):>10.3f}"
            f"{stats.get('mean_ms', float('nan')):>10.3f}"
            f"{stats.get('median_ms', float('nan')):>11.3f}"
            f"{stats.get('p95_ms', float('nan')):>10.3f}"
            f"{stats.get('max_ms', float('nan')):>10.3f}"
            f"{row['failures']:>10}"
        )
    return "\n".join(lines)


def compute_deltas(reference_stats, mode_stats):
    if reference_stats is None or mode_stats is None:
        return None
    delta = {}
    for key in ("min_ms", "mean_ms", "median_ms", "p95_ms", "max_ms"):
        ref_val = reference_stats.get(key)
        mode_val = mode_stats.get(key)
        if ref_val is None or mode_val is None:
            delta[key] = {"absolute_ms": None, "percent": None}
            continue
        abs_delta = round(mode_val - ref_val, 3)
        pct_delta = round((abs_delta / ref_val) * 100.0, 2) if ref_val else None
        delta[key] = {"absolute_ms": abs_delta, "percent": pct_delta}
    return delta


_DELTA_COL_WIDTH = 22


def format_delta_table(reference_mode, deltas_by_mode) -> str:
    label = "mode vs " + reference_mode
    header = f"{label:<20}" + "".join(
        f"{col:>{_DELTA_COL_WIDTH}}" for col in ("min", "mean", "median", "p95", "max")
    )
    lines = [header, "-" * len(header)]
    for mode, delta in deltas_by_mode.items():
        if delta is None:
            lines.append(f"{mode:<20}{'n/a':>{_DELTA_COL_WIDTH}}")
            continue

        def fmt(key):
            d = delta[key]
            if d["absolute_ms"] is None:
                return "n/a"
            pct = f"{d['percent']:+.1f}%" if d["percent"] is not None else "n/a"
            return f"{d['absolute_ms']:+.3f}ms/{pct}"

        lines.append(
            f"{mode:<20}"
            + "".join(
                f"{fmt(key):>{_DELTA_COL_WIDTH}}"
                for key in ("min_ms", "mean_ms", "median_ms", "p95_ms", "max_ms")
            )
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    args = parse_args(argv)

    print(
        "Latency comparison across security modes\n"
        f"  modes:              {args.modes}\n"
        f"  reference mode:     {args.reference_mode}\n"
        f"  samples per mode:   {args.samples} (warmup {args.warmup})\n"
        f"  timeout:            {args.timeout}s\n"
        f"  mode-switch method: {args.mode_switch_method}\n"
        f"  interactive pauses: {args.interactive}\n"
    )

    results = {}
    rows = []
    any_zero_success = False
    previous_mode = None
    previous_url = None

    for mode in args.modes:
        url = resolve_url(mode, args)

        needs_pause = (
            args.interactive
            and previous_mode is not None
            and url == previous_url
        )
        if needs_pause:
            prompt_for_phase(mode, url, previous_mode)
        elif previous_mode is None:
            print(f"== Phase 1: mode '{mode}' -- POST {url} ==")
        else:
            print(f"== Phase: mode '{mode}' -- POST {url} (separate target, no pause needed) ==")

        if args.warmup > 0:
            run_phase(url, f"{args.device_id}-warmup", args.warmup, args.timeout)

        latencies, failures = run_phase(url, args.device_id, args.samples, args.timeout)
        stats = compute_stats(latencies)
        if stats is None:
            any_zero_success = True

        results[mode] = {
            "url": url,
            "samples_requested": args.samples,
            "warmup": args.warmup,
            "failures": failures,
            "stats_ms": stats,
        }
        rows.append({"mode": mode, "stats": stats, "failures": failures})

        previous_mode = mode
        previous_url = url

    print()
    print(format_stats_table(rows))

    reference_stats = results[args.reference_mode]["stats_ms"]
    deltas_by_mode = {
        mode: compute_deltas(reference_stats, results[mode]["stats_ms"])
        for mode in args.modes
        if mode != args.reference_mode
    }

    print()
    print("Delta vs reference (absolute ms / percent; positive = slower):")
    print(format_delta_table(args.reference_mode, deltas_by_mode))
    print()

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "config": {
            "modes": args.modes,
            "reference_mode": args.reference_mode,
            "samples": args.samples,
            "warmup": args.warmup,
            "timeout_s": args.timeout,
            "device_id": args.device_id,
            "mode_switch_method": args.mode_switch_method,
            "interactive": args.interactive,
        },
        "results": results,
        "deltas_vs_reference": deltas_by_mode,
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Wrote JSON results to {args.json_out}")

    if any_zero_success:
        print("FAIL: at least one mode had zero successful samples.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

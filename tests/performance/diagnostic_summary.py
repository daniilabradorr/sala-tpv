"""Summarize per-request correlated observations, not differences of percentiles."""

import argparse
import json
from pathlib import Path
from statistics import median

from tests.performance.metrics import distribution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("work/tpv-diagnostic"))
    args = parser.parse_args()
    browser = json.loads((args.root / "gunicorn/browser.json").read_text())
    gunicorn = {}
    for line in (args.root / "gunicorn/gunicorn.log").read_text().splitlines():
        if "{" in line:
            row = json.loads(line[line.index("{") :])
            if row.get("trace_id"):
                gunicorn[row["trace_id"]] = row
    summary = {}
    for name, scenario in browser["scenarios"].items():
        rows = scenario["samples"]
        stages = {key for row in rows for key in row["trace"]["stages"]}
        summary[name] = {
            "http_ms": distribution([r["http_ms"] for r in rows]),
            "django_ms": distribution([r["trace"]["django_ms"] for r in rows]),
            "sql_execute_ms": distribution(
                [r["trace"]["sql_execute_ms"] for r in rows]
            ),
            "http_minus_django_ms_not_pure_network": distribution(
                [r["http_ms"] - r["trace"]["django_ms"] for r in rows]
            ),
            "http_minus_gunicorn_ms_not_pure_network": distribution(
                [r["http_ms"] - gunicorn[r["trace_id"]]["gunicorn_ms"] for r in rows]
            ),
            "visual_after_response_ms": distribution(
                [r["response_to_frame_ms"] for r in rows]
            ),
            "interaction_to_frame_ms": scenario["interaction_to_frame_ms"],
            "sql_count": sorted({r["trace"]["sql_count"] for r in rows}),
            "stages_p50_inclusive_ms": {
                key: round(
                    median(
                        [r["trace"]["stages"].get(key, {}).get("ms", 0) for r in rows]
                    ),
                    3,
                )
                for key in sorted(stages)
            },
            "locks_ms": None,
            "pre_worker_queue_ms": None,
        }
    report = {"gunicorn_http": summary}
    paired = args.root / "postgres/overhead-paired.json"
    if paired.exists():
        report["paired_collection_overhead"] = json.loads(paired.read_text())
    on = args.root / "postgres/server.json"
    off = args.root / "postgres-off/server.json"
    if on.exists() and off.exists():
        enabled = json.loads(on.read_text())["scenarios"]
        disabled = json.loads(off.read_text())["scenarios"]
        report["overhead_unpaired_sequential_runs_not_causal_estimate"] = {
            name: {
                "on_p50_ms": row["client_ms"]["p50"],
                "off_p50_ms": disabled[name]["client_ms"]["p50"],
                "delta_ms": round(
                    row["client_ms"]["p50"] - disabled[name]["client_ms"]["p50"], 3
                ),
            }
            for name, row in enabled.items()
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

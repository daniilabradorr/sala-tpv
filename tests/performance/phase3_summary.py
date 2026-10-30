"""Assemble measured phase 3 artifacts; missing metrics remain null."""

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import platform
import re
from statistics import median
import subprocess
from zoneinfo import ZoneInfo


def stats(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {
        "n": len(values),
        "min": round(min(values), 3),
        "median": round(median(values), 3),
        "max": round(max(values), 3),
        "p95": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/workspace/work/phase3-b"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root

    def read(name):
        path = root / name
        return json.loads(path.read_text()) if path.exists() else None

    browser = read("matrix/browser.json")
    summaries = {}
    for name, case in (browser or {}).items():
        rows = case["samples"]

        def stage(row, label, field="ms"):
            return row["trace"]["stages"].get(label, {}).get(field)

        metrics = {
            "post_http_ms": stats([r["post"]["http_ms"] for r in rows]),
            "scripted_open_to_confirmation_ms": stats(
                [r["frontend"]["frame"] - r["open"]["detail"]["click"] for r in rows]
            ),
            "machine_intervals_excluding_selection_ms": stats(
                [
                    (r["open"]["detail"]["frame"] - r["open"]["detail"]["click"])
                    + (r["frontend"]["frame"] - r["frontend"]["click"])
                    for r in rows
                ]
            ),
            "confirm_click_to_two_frames_ms": stats(
                [r["frontend"]["frame"] - r["frontend"]["click"] for r in rows]
            ),
            "confirm_click_to_request_ms": stats(
                [r["frontend"]["request"] - r["frontend"]["click"] for r in rows]
            ),
            "open_click_to_modal_ms": stats(
                [
                    r["open"]["detail"]["modal"] - r["open"]["detail"]["click"]
                    for r in rows
                ]
            ),
            "open_click_to_two_frames_ms": stats(
                [
                    r["open"]["detail"]["frame"] - r["open"]["detail"]["click"]
                    for r in rows
                ]
            ),
            "flush_ms": stats([r["open"]["flush"][0]["ms"] for r in rows]),
            "checkout_get_http_ms": stats(
                [r["open"]["observer"]["http_ms"] for r in rows]
            ),
            "django_ms": stats([r["trace"]["django_ms"] for r in rows]),
            "sql_execute_ms": stats([r["trace"]["sql_execute_ms"] for r in rows]),
            "sql_count": stats([r["trace"]["sql_count"] for r in rows]),
            "sql_max_single_execute_ms": stats(
                [max(g["max_ms"] for g in r["trace"]["sql_groups"]) for r in rows]
            ),
            "http_minus_django_ms": stats(
                [r["post"]["http_ms"] - r["trace"]["django_ms"] for r in rows]
            ),
            "response_to_frame_ms": stats(
                [r["post"]["response_to_frame_ms"] for r in rows]
            ),
        }
        for label in (
            "checkout",
            "complete_sale",
            "inventory",
            "payment",
            "billing",
            "billing_lines",
            "state",
            "options",
            "html_render",
            "db_commit",
            "db_connect",
            "db_rollback",
        ):
            metrics[label + "_ms"] = stats([stage(r, label) for r in rows])
        for label in ("checkout", "payment", "billing"):
            metrics["transaction_" + label + "_ms"] = stats(
                [
                    t["ms"]
                    for r in rows
                    for t in r["trace"]["transactions"]
                    if t["phase"] == label
                ]
            )
        details = sorted({key for r in rows for key in r["trace"]["detail_stages"]})
        detail_summary = {
            key: {
                field: stats(
                    [r["trace"]["detail_stages"].get(key, {}).get(field) for r in rows]
                )
                for field in ("calls", "ms", "exclusive_ms")
            }
            for key in details
        }
        groups = defaultdict(
            lambda: {"count": 0, "ms": 0.0, "max_ms": 0.0, "tables": []}
        )
        for row in rows:
            for group in row["trace"]["sql_groups"]:
                key = (
                    group["operation"]
                    if group["operation"] in ("SAVEPOINT", "RELEASE", "ROLLBACK")
                    else group["fingerprint"]
                )
                value = groups[key]
                value["operation"] = group["operation"]
                value["tables"] = group["tables"]
                value["count"] += group["count"]
                value["ms"] += group["ms"]
                value["max_ms"] = max(value["max_ms"], group["max_ms"])
        summaries[name] = {
            "sample_size": len(rows),
            "specification": {
                k: v
                for k, v in case.items()
                if k not in ("samples", "economic_checks_including_warmup")
            },
            "metrics": metrics,
            "details": detail_summary,
            "top_sql_groups_aggregate_across_samples": sorted(
                (
                    {"fingerprint_or_command": key, **value}
                    for key, value in groups.items()
                ),
                key=lambda v: v["ms"],
                reverse=True,
            )[:20],
            "economic_checks": case.get("economic_checks_including_warmup"),
        }
        # Keep compact per-request evidence and every lock duration; the exhaustive
        # group list is retained in scratch, aggregated top groups in deliverable.
        for row in rows:
            row["trace"]["sql_max_single_execute_ms"] = max(
                g["max_ms"] for g in row["trace"]["sql_groups"]
            )
            row["trace"].pop("sql_groups", None)
            if row.get("get_trace"):
                row["get_trace"].pop("sql_groups", None)
    scripts = [
        *Path("tests/performance").glob("phase3*"),
        Path("config/settings/diagnostic_phase3.py"),
    ]
    result = {
        "collected_at": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(),
        "branch": subprocess.check_output(
            ["git", "branch", "--show-current"], text=True
        ).strip(),
        "base_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "main_sha": subprocess.check_output(
            ["git", "rev-parse", "origin/main"], text=True
        ).strip(),
        "instrumentation_source_sha256": {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in scripts
            if p.is_file()
        },
        "environment": {
            "python": platform.python_version(),
            "chromium": subprocess.check_output(
                ["/usr/bin/chromium", "--version"], text=True
            ).strip(),
            "os": platform.system() + " " + platform.release(),
            "logical_cpus_visible": 3,
            "cpu_quota_cores": 2,
            "memory_limit_bytes": 8589934592,
            "cpu_model": "AMD EPYC 9V74 80-Core Processor (virtualized)",
            "transport": "loopback HTTP, Gunicorn sync 1 worker / 1 thread; PostgreSQL direct dedicated disposable Docker",
            "runtime": read("runtime.json"),
            "cleanup": read("cleanup.json"),
            "image_digest": "postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab",
        },
        "method": {
            "warmups_per_cell": 1,
            "samples_per_cell": 7,
            "stats": "min/median/max; p95 null at n=7; individual values included",
            "cold": None,
            "external_resources": "blocked in Gunicorn matrix",
            "durations": "ms; nested spans inclusive; detail exclusive only subtracts directly nested detail spans",
            "worker_queue_ms": None,
            "pure_network_ms": None,
            "production_latency_ms": None,
            "stock_and_series_mutations": "synthetic fixture + real service under test only",
        },
        "scenario_summaries": summaries,
        "browser_raw": browser,
        "contention": read("cases/contention.json"),
        "controlled_locks": read("cases/controlled-locks.json"),
        "boundaries": read("cases/boundaries.json"),
        "frontend_boundaries": read("frontend/frontend-boundaries.json"),
        "overhead": read("overhead/overhead.json"),
        "initial_collector_overhead": read("overhead-v1/overhead.json"),
        "initial_collector_source_sha256": hashlib.sha256(
            (root / "collector-v1.py").read_bytes()
        ).hexdigest()
        if (root / "collector-v1.py").exists()
        else None,
        "fiscal_model_costs": read("cases/fiscal-models.json"),
        "between_transactions": read("cases/between-transactions.json"),
        "validation": {
            name: {
                "test_count": int(match.group(1))
                if (match := re.search(r"Ran (\d+) tests?", log))
                else None,
                "duration_seconds": float(match.group(1))
                if (match := re.search(r"in ([\d.]+)s", log))
                else None,
                "result": "OK"
                if re.search(r"^OK$", log, re.M)
                else ("FAILED" if "FAILED" in log else None),
            }
            for name in (
                "matrix-final",
                "cases-final",
                "frontend-final",
                "overhead-final",
                "regression",
                "fiscal-counter-final",
            )
            if (file := root / (name + ".log")).exists() and (log := file.read_text())
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for key, case in summaries.items():
        metrics = case["metrics"]

        def med(metric):
            return metrics[metric]["median"] if metrics[metric] else None

        print(
            key,
            {
                key: med(key)
                for key in (
                    "post_http_ms",
                    "django_ms",
                    "transaction_checkout_ms",
                    "inventory_ms",
                    "payment_ms",
                    "billing_ms",
                    "sql_execute_ms",
                    "sql_count",
                    "html_render_ms",
                    "flush_ms",
                    "open_click_to_two_frames_ms",
                    "confirm_click_to_two_frames_ms",
                )
            },
        )


if __name__ == "__main__":
    main()

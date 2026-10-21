"""Separate read-only sampler; outputs no query, user, database or relation names.

TPV_LOCK_DSN must select the direct PostgreSQL instance, not a transaction pooler.
"""

import argparse
import json
import os
from time import monotonic, sleep, time

import psycopg


SQL = """
SELECT pid, wait_event_type, wait_event,
       EXTRACT(EPOCH FROM (clock_timestamp() - xact_start)) * 1000,
       pg_blocking_pids(pid)
FROM pg_stat_activity
WHERE datname = current_database() AND pid = ANY(%s)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pids", nargs="+", type=int, required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--interval", type=float, default=0.1)
    args = parser.parse_args()
    if args.interval < 0.05 or args.seconds <= 0:
        parser.error("interval >= 0.05; seconds > 0")
    with psycopg.connect(os.environ["TPV_LOCK_DSN"], autocommit=True) as connection:
        connection.execute("SET default_transaction_read_only = on")
        connection.execute("SET statement_timeout = '2s'")
        start = monotonic()
        while monotonic() - start < args.seconds:
            for pid, kind, event, age, blockers in connection.execute(
                SQL, (args.pids,)
            ):
                print(
                    json.dumps(
                        {
                            "epoch_ms": round(time() * 1000),
                            "pid": pid,
                            "wait_type": kind,
                            "wait_event": event,
                            "transaction_age_ms": float(age)
                            if age is not None
                            else None,
                            "blocking_pids": blockers,
                        }
                    ),
                    flush=True,
                )
            sleep(args.interval)


if __name__ == "__main__":
    main()

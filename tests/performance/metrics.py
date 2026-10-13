"""Small stdlib measurement helpers; exported SQL never contains literals."""

import hashlib
import math
import re
from collections import Counter
from statistics import median


_LITERAL = re.compile(r"'(?:''|[^'])*'|\b\d+(?:\.\d+)?\b")


def sql_pattern(sql):
    return re.sub(r"\s+", " ", _LITERAL.sub("?", sql)).strip()


def distribution(values):
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 3),
        "p50": round(median(ordered), 3),
        "p95": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 3),
        "max": round(ordered[-1], 3),
    }


def query_summary(queries):
    patterns = Counter(sql_pattern(query["sql"]) for query in queries)
    exact = Counter(query["sql"] for query in queries)
    return {
        "count": len(queries),
        "unique_exact": len(exact),
        "repeated_exact": sum(count - 1 for count in exact.values()),
        "unique_patterns": len(patterns),
        "repeated_patterns": sum(count - 1 for count in patterns.values()),
        "top_patterns": [
            {
                "fingerprint": hashlib.sha256(pattern.encode()).hexdigest()[:12],
                "operation": pattern.split()[0],
                "tables": sorted(
                    set(re.findall(r'(?:FROM|JOIN|INTO|UPDATE) "(\w+)"', pattern))
                ),
                "count": count,
            }
            for pattern, count in patterns.most_common(3)
        ],
    }

"""Guard percentile semantics and ensure SQL literal values are never exported."""

import json

from django.test import SimpleTestCase

from tests.performance.metrics import distribution, query_summary, sql_pattern


class MetricSemanticsTests(SimpleTestCase):
    def test_p95_uses_nearest_rank_and_median_uses_two_middle_values(self):
        self.assertEqual(
            distribution(list(range(1, 21))),
            {"min": 1, "p50": 10.5, "p95": 19, "max": 20},
        )
        self.assertEqual(distribution([7]), {"min": 7, "p50": 7, "p95": 7, "max": 7})

    def test_patterns_group_literals_but_exact_duplicates_stay_distinct(self):
        queries = [
            {
                "sql": 'SELECT * FROM "customers_customer" WHERE "name" = \'Private Alice\' AND "id" = 41'
            },
            {
                "sql": 'SELECT * FROM "customers_customer" WHERE "name" = \'Private Bob\' AND "id" = 42'
            },
        ]
        result = query_summary(queries + queries[:1])
        self.assertEqual(result["unique_exact"], 2)
        self.assertEqual(result["unique_patterns"], 1)
        self.assertEqual(result["repeated_exact"], 1)
        self.assertEqual(result["repeated_patterns"], 2)
        self.assertNotIn("Private", json.dumps(result))
        self.assertNotIn("Private", sql_pattern(queries[0]["sql"]))
        self.assertEqual(result["top_patterns"][0]["tables"], ["customers_customer"])

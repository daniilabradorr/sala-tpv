"""Alternating paired samples to reduce drift in the trace-collection estimate."""

import os
from statistics import median
from time import perf_counter

from django.test import Client, TestCase, override_settings

from tests.performance.dataset import Dataset
from tests.performance.diagnostic_matrix import (
    checkout_data,
    guard,
    path,
    save_result,
    verify,
)
from tests.performance.metrics import distribution


class OverheadComparison(TestCase):
    def test_alternating_pairs(self):
        guard()
        dataset = Dataset(60, label="diagnostic-overhead")
        clients = {}
        for enabled in (True, False):
            with override_settings(TPV_DIAGNOSTICS=enabled):
                client = Client()
                client.force_login(dataset.user)
                client.handler.load_middleware()
                clients[enabled] = client
        samples = int(os.getenv("TPV_DIAGNOSTIC_SAMPLES", "10"))
        scenarios = {}
        for size in (1, 20, 50):
            rows = []
            for iteration in range(samples + 2):
                fixtures = {enabled: dataset.sale(size)[0] for enabled in (True, False)}
                data = {enabled: checkout_data(dataset) for enabled in (True, False)}
                elapsed = {}
                for enabled in (True, False) if iteration % 2 else (False, True):
                    sale = fixtures[enabled]
                    start = perf_counter()
                    response = clients[enabled].post(
                        path("sale_checkout", sale),
                        data[enabled],
                        HTTP_HX_REQUEST="true",
                    )
                    elapsed[enabled] = (perf_counter() - start) * 1000
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual("X-TPV-Trace" in response, enabled)
                    verify(self, sale, "checkout_post", size)
                if iteration >= 2:
                    rows.append(
                        {
                            "on_ms": elapsed[True],
                            "off_ms": elapsed[False],
                            "delta_ms": elapsed[True] - elapsed[False],
                        }
                    )
            scenarios[f"checkout_post_{size}"] = {
                "on_ms": distribution([r["on_ms"] for r in rows]),
                "off_ms": distribution([r["off_ms"] for r in rows]),
                "paired_delta_ms": distribution([r["delta_ms"] for r in rows]),
                "median_paired_percent": round(
                    median([100 * r["delta_ms"] / r["off_ms"] for r in rows]), 3
                ),
                "samples": rows,
            }
        save_result(
            "overhead-paired.json",
            scenarios,
            iterations=samples,
            caveat="Measures collection overhead; disabled path retains no-op wrappers. No log I/O.",
        )

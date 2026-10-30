"""Privacy and time-accounting checks for the opt-in phase 3 collector."""

import json
from unittest.mock import patch
from uuid import uuid4

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from tests.performance.diagnostic import CURRENT
from tests.performance.phase3_trace import DetailedTrace, Phase3Middleware, measured


class Phase3TraceTests(SimpleTestCase):
    def test_query_details_omit_text_values_and_unknown_identifiers(self):
        trace = DetailedTrace(str(uuid4()))
        for statement in (
            'SELECT secret FROM "private_name" WHERE token = %s',
            'SELECT * FROM "sales_sale" FOR UPDATE',
        ):
            trace.execute(
                lambda *args: None,
                statement,
                ["private-token"],
                False,
                {"connection": type("DB", (), {"connection": None})()},
            )
        result = trace.report(200)
        encoded = json.dumps(result)
        for forbidden in (
            "secret",
            "private_name",
            "private-token",
            "SELECT *",
            "FOR UPDATE",
        ):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(len(result["lock_executes"]), 1)
        self.assertEqual(result["sql_count"], 2)

    def test_nested_exclusive_time_and_exception_cleanup(self):
        trace = DetailedTrace(str(uuid4()))
        token = CURRENT.set(trace)

        def child():
            raise ValueError("private")

        wrapped_child = measured(child, "child")
        wrapped_parent = measured(wrapped_child, "parent")
        try:
            with self.assertRaises(ValueError):
                wrapped_parent()
            self.assertEqual(trace.detail_stack, [])
            parent, child_row = trace.details["parent"], trace.details["child"]
            self.assertAlmostEqual(
                parent["ms"] - child_row["ms"], parent["exclusive_ms"], places=5
            )
            self.assertEqual(child_row["calls"], 1)
        finally:
            CURRENT.reset(token)

    @override_settings(TPV_DIAGNOSTICS=False, TPV_PHASE3_DIAGNOSTICS=False)
    def test_disabled_never_installs(self):
        with patch("tests.performance.phase3_trace.install") as install:
            response = Phase3Middleware(lambda request: HttpResponse())(
                RequestFactory().get("/sales/stores/1/sales/2/checkout/")
            )
        install.assert_not_called()
        self.assertNotIn("X-TPV-Trace", response)

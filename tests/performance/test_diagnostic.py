import json
from unittest.mock import patch
from uuid import uuid4

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from tests.performance.diagnostic import (
    CURRENT,
    DiagnosticMiddleware,
    Trace,
    recent,
    span,
)


class TraceTests(SimpleTestCase):
    def test_nested_sql_is_inclusive_and_does_not_record_values(self):
        trace = Trace(str(uuid4()))
        token = CURRENT.set(trace)
        try:
            with span("checkout"):
                with span("payment"):
                    trace.execute(
                        lambda *args: None,
                        "SELECT secret",
                        ["private"],
                        False,
                        {"connection": type("DB", (), {"connection": None})()},
                    )
            data = trace.report(200)
            self.assertEqual(data["sql_count"], 1)
            self.assertEqual(data["stages"]["checkout"]["queries"], 1)
            self.assertEqual(data["stages"]["payment"]["queries"], 1)
            self.assertNotIn("secret", json.dumps(data))
            self.assertNotIn("private", json.dumps(data))
        finally:
            CURRENT.reset(token)

    def test_exception_restores_span_stack(self):
        trace = Trace(str(uuid4()))
        token = CURRENT.set(trace)
        try:
            with self.assertRaises(ValueError), span("billing"):
                raise ValueError("private")
            self.assertEqual(trace.stack, [])
            self.assertEqual(trace.stages["billing"]["calls"], 1)
        finally:
            CURRENT.reset(token)

    @override_settings(TPV_DIAGNOSTICS=True)
    def test_middleware_sanitizes_header_and_resets_context(self):
        request = RequestFactory().post(
            "/sales/stores/1/sales/2/checkout/",
            {"cash_received": "private"},
            HTTP_X_TPV_TRACE="invalid-sensitive-id",
        )
        with patch("tests.performance.diagnostic.install"):
            middleware = DiagnosticMiddleware(
                lambda request: HttpResponse("private HTML")
            )
        with patch("tests.performance.diagnostic.LOGGER.info") as logger:
            response = middleware(request)
        self.assertTrue(response["X-TPV-Trace"])
        self.assertIsNotNone(recent(response["X-TPV-Trace"]))
        self.assertNotIn("private", logger.call_args.args[0])
        self.assertNotIn("sensitive", logger.call_args.args[0])
        self.assertIsNone(CURRENT.get())

    @override_settings(TPV_DIAGNOSTICS=False)
    def test_disabled_does_not_install_or_add_headers(self):
        with patch("tests.performance.diagnostic.install") as install:
            response = DiagnosticMiddleware(lambda request: HttpResponse())(
                RequestFactory().get("/sales/stores/1/sales/2/")
            )
        install.assert_not_called()
        self.assertNotIn("X-TPV-Trace", response)

"""Manual browser privacy/error coverage, independent of commercial fixtures."""

import json
import os
from pathlib import Path

from django.test import SimpleTestCase


class BrowserObserverTests(SimpleTestCase):
    def test_private_headers_and_error_payload_are_not_exported(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM", "/usr/bin/chromium"),
                headless=True,
            )
            page = browser.new_page()
            page.evaluate(Path(__file__).with_name("diagnostic-browser.js").read_text())
            page.evaluate("""() => {
              const xhr = {status: 500, responseURL: 'private-url',
                responseText: 'private body', getResponseHeader(name) {
                  return name === 'X-TPV-Trace' ? 'private-trace'
                    : 'sql;dur=7,unknown;desc=private';
                }};
              const detail = {xhr};
              document.dispatchEvent(new CustomEvent('htmx:beforeRequest', {detail}));
              document.dispatchEvent(new CustomEvent('htmx:afterRequest', {detail}));
            }""")
            rows = page.evaluate("window.tpvDiagnostic.rows")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], 500)
            self.assertIsNone(rows[0]["trace_id"])
            self.assertNotIn("private", json.dumps(rows))
            page.evaluate("window.tpvDiagnostic.stop()")
            self.assertFalse(page.evaluate("Boolean(window.tpvDiagnostic)"))
            browser.close()

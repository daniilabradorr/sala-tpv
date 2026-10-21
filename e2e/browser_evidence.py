"""Bounded, synthetic-test diagnostics; never capture cookies or form payloads."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


class BrowserEvidence:
    def __init__(self, page, test_id):
        self.page, self.test_id, self.events = page, test_id, []
        page.on(
            "console",
            lambda msg: (
                self.record(console_error=msg.text[:600])
                if msg.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda error: self.record(pageerror=str(error)[:600]))
        page.on(
            "requestfailed",
            lambda request: self.record(
                failed=urlsplit(request.url).path, reason=request.failure
            ),
        )
        page.on("response", self.response)

    def record(self, **event):
        self.events.append(event)
        self.events[:] = self.events[-200:]

    def response(self, response):
        path = urlsplit(response.url).path
        if (
            response.status >= 400
            or "/cart-sync/" in path
            or path.startswith("/static/")
        ):
            self.record(
                path=path,
                status=response.status,
                content_type=response.headers.get("content-type"),
                protocol=response.headers.get("x-sales-cart-protocol"),
            )

    def capture(self):
        try:
            state = self.page.evaluate("""() => ({
                scripts:[...document.scripts].map(x=>new URL(x.src||location.href).pathname),
                queueDefined:!!window.tpvCart, classDefined:!!window.SalesCartQueue,
                rootPresent:!!document.querySelector('.tpv[data-cart-sync]'),
                queue:window.tpvCart?{ready:tpvCart.protocolReady,busy:tpvCart.busy,
                    pending:tpvCart.ops.length,version:tpvCart.cart?.version,
                    error:tpvCart.error,headerPending:tpvCart.headerPending,headerError:tpvCart.headerError}:null,
                storageEntries:sessionStorage.length,
                csrfInputPresent:!!document.querySelector('[name=csrfmiddlewaretoken]'),
                checkoutOpen:document.querySelector('#checkout-dialog')?.open,
                checkoutFormPresent:!!document.querySelector('#checkout-panel [data-checkout-form]')
            })""")
        except Exception as error:
            state = {"capture_error": str(error)[:300]}
        try:
            cookies = [
                {
                    key: cookie.get(key)
                    for key in ("name", "secure", "httpOnly", "sameSite")
                }
                for cookie in self.page.context.cookies()
            ]
        except Exception:
            cookies = []
        record = {
            "test": self.test_id,
            "events": self.events,
            "state": state,
            "cookie_flags": cookies,
        }
        target = Path("artifacts/e2e")
        target.mkdir(parents=True, exist_ok=True)
        path = target / (re.sub(r"[^a-zA-Z0-9_.-]", "_", self.test_id) + ".json")
        path.write_text(json.dumps(record, indent=2) + "\n")
        print("BROWSER_EVIDENCE " + json.dumps(record), flush=True)

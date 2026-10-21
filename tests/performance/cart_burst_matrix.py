"""Optional local A/B: a356003 frontend vs current, identical current backend.

All 27 line/latency/burst combinations once; repeat the representative
20-line/300ms/20-click cell to 20 samples per frontend for descriptive quantiles.
No production network, bank, payment gateway or fiscal submission is used.
"""

import itertools
import json
import math
import os
import statistics
import subprocess
import time
from pathlib import Path

from apps.inventory.models import InventoryItem
from apps.payments.models import Payment
from e2e import browser_optimistic_cart as fixture


class CartBurstMatrix(fixture.OptimisticCartBrowserTests):
    def test_matrix(self):
        baseline = subprocess.check_output(
            ["git", "show", "a356003:static/js/sales_cart.js"], text=True
        )
        self.d.grow_catalog(50)
        # Synthetic starting inventory only, equal for both frontend treatments.
        InventoryItem.objects.filter(business=self.d.business).update(
            current_stock=100000
        )
        cells = list(itertools.product((1, 20, 50), (100, 300, 600), (10, 20, 50)))
        if os.getenv("TPV_BURST_SMOKE") == "1":
            cells = [(20, 300, 20)]
        repeats = int(os.getenv("TPV_BURST_REPRESENTATIVE_SAMPLES", "20"))
        cells += [(20, 300, 20)] * (repeats - 1)
        output = Path(
            os.environ.get(
                "TPV_BURST_REPORT", "work/tpv-optimistic-cart/phase2c-bursts.json"
            )
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        samples = []
        for cell_index, (lines, latency, clicks) in enumerate(cells):
            modes = (
                ("baseline", "hardened")
                if cell_index % 2 == 0
                else ("hardened", "baseline")
            )
            for mode in modes:
                sale, _ = self.d.sale(lines)
                page = self.context.new_page()
                page.set_default_timeout(90000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("dialog", lambda dialog: dialog.accept())
                if mode == "baseline":
                    page.route(
                        "**/static/js/sales_cart.js",
                        lambda route: route.fulfill(
                            status=200, content_type="text/javascript", body=baseline
                        ),
                    )
                requests = []

                def delayed(route):
                    if (
                        route.request.method == "POST"
                        or "/checkout/" in route.request.url
                    ):
                        requests.append(
                            (
                                route.request.method,
                                "checkout"
                                if "/checkout/" in route.request.url
                                else "cart",
                            )
                        )
                        time.sleep(latency / 1000)
                    route.continue_()

                page.route("**/cart-sync/", delayed)
                page.route("**/checkout/", delayed)
                page.goto(
                    self.url.replace(f"/sales/{self.sale.pk}/", f"/sales/{sale.pk}/")
                )
                page.wait_for_function("Boolean(window.tpvCart?.cart)")
                page.evaluate("tpvCart.refresh()")
                value = page.evaluate(
                    """async clicks => {
                    window.burstStart=performance.now();window.burstPersisted=null;window.burstHTTP=[];
                    const changed=tpvCart.changed,send=tpvCart.send;
                    tpvCart.changed=function(queue) {
                        changed(queue);
                        if(window.burstPersisted===null && !queue.ops.length && !queue.busy)window.burstPersisted=performance.now()-burstStart;
                    };
                    tpvCart.send=async function(op) {
                        const start=performance.now();
                        try{return await send(op);}
                        finally{burstHTTP.push(performance.now()-start);}
                    };
                    const product=document.querySelector('.product-grid form');
                    for(let i=0;i<clicks;i++)product.requestSubmit();
                    return new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(performance.now()-burstStart))));
                }""",
                    clicks,
                )
                shell = page.evaluate("""() => {
                    window.checkoutStart=performance.now();
                    document.querySelector('[data-checkout-open]').click();
                    return {ms:performance.now()-checkoutStart,open:document.querySelector('#checkout-dialog').open};
                }""")
                self.assertTrue(shell["open"])
                page.locator("#checkout-panel [data-checkout-form]").wait_for()
                timings = page.evaluate("""() => ({persist_ms:burstPersisted,
                    usable_ms:performance.now()-checkoutStart,http_ms:burstHTTP})""")
                self.assertEqual(
                    sum(line.quantity for line in sale.lines.all()), lines + clicks
                )
                self.assertEqual(sale.lines.count(), lines + clicks)
                page.locator(
                    '#checkout-panel [name="method"][data-method-code="card"]'
                ).check()
                payment_start = page.evaluate("performance.now()")
                page.locator("#checkout-panel .checkout-confirm").click()
                page.locator("#checkout-panel .checkout-success").wait_for()
                payment_ms = page.evaluate("performance.now()") - payment_start
                self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
                self.assertEqual(errors, [])
                samples.append(
                    dict(
                        mode=mode,
                        initial_lines=lines,
                        latency_ms=latency,
                        clicks=clicks,
                        visual_frame_bound_ms=value,
                        persisted_ms=timings["persist_ms"],
                        mutation_requests=sum(kind == "cart" for _, kind in requests),
                        mutation_http_ms=timings["http_ms"],
                        checkout_shell_ms=shell["ms"],
                        checkout_usable_ms=timings["usable_ms"],
                        payment_confirm_ms=payment_ms,
                    )
                )
                output.write_text(
                    json.dumps({"complete": False, "samples": samples}, indent=2) + "\n"
                )
                print(
                    f"BURST {len(samples)}/{len(cells) * 2} {mode} lines={lines} latency={latency} clicks={clicks}",
                    flush=True,
                )
                page.unroute_all(behavior="wait")
                page.close()
        summary = []
        for lines, latency, clicks, mode in itertools.product(
            (1, 20, 50), (100, 300, 600), (10, 20, 50), ("baseline", "hardened")
        ):
            group = [
                row
                for row in samples
                if (row["initial_lines"], row["latency_ms"], row["clicks"], row["mode"])
                == (lines, latency, clicks, mode)
            ]
            if not group:
                continue
            metrics = {}
            for name in (
                "visual_frame_bound_ms",
                "persisted_ms",
                "mutation_requests",
                "checkout_shell_ms",
                "checkout_usable_ms",
                "payment_confirm_ms",
            ):
                values = sorted(row[name] for row in group)
                metrics[name] = {
                    "n": len(values),
                    "min": min(values),
                    "max": max(values),
                }
                if len(values) >= 20:
                    metrics[name].update(
                        p50=statistics.median(values),
                        p95=values[math.ceil(0.95 * len(values)) - 1],
                    )
            summary.append(
                dict(
                    lines=lines,
                    latency_ms=latency,
                    clicks=clicks,
                    mode=mode,
                    metrics=metrics,
                )
            )
        output.write_text(
            json.dumps(
                dict(
                    complete=True,
                    baseline_frontend="a356003",
                    backend_commit=subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], text=True
                    ).strip(),
                    synthetic_delay="before forwarding each cart POST and checkout GET/POST; cart GET has no imposed delay",
                    samples=samples,
                    summary=summary,
                ),
                indent=2,
            )
            + "\n"
        )


for _name in dir(fixture.OptimisticCartBrowserTests):
    if _name.startswith("test_") and _name != "test_matrix":
        setattr(CartBurstMatrix, _name, None)

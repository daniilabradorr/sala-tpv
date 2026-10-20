"""Optional local frontend A/B: same backend/data, old HTMX vs optimistic JS.

Baseline disables only sales_cart.js; both run the current Sales domain services.
The imposed 400ms response delay isolates the visual dependence on HTTP. These
are not production measurements or an A/B benchmark of backend commits.
"""

import time
from e2e import browser_optimistic_cart as browser_tests


class VisualMatrix(browser_tests.OptimisticCartBrowserTests):
    # Inherit the fixture without re-running the functional browser suite here.
    pass


# unittest discovers inherited test methods; keep only this explicit benchmark.
for _name in dir(browser_tests.OptimisticCartBrowserTests):
    if _name.startswith("test_"):
        setattr(VisualMatrix, _name, None)


def matrix(self):
    self.d.grow_catalog(50)
    samples = []
    for lines in (1, 20, 50):
        for mode in ("htmx", "optimistic"):
            for sample in range(10):
                sale, _ = self.d.sale(lines)
                page = self.context.new_page()
                if mode == "htmx":
                    page.route(
                        "**/static/js/sales_cart.js",
                        lambda route: route.fulfill(
                            status=200, content_type="text/javascript", body=""
                        ),
                    )

                def slow(route):
                    if route.request.method == "POST":
                        time.sleep(0.4)
                    route.continue_()

                page.route("**/lines/add/", slow)
                page.route("**/cart-sync/", slow)
                page.goto(
                    self.url.replace(f"/sales/{self.sale.pk}/", f"/sales/{sale.pk}/")
                )
                if mode == "optimistic":
                    page.wait_for_function("Boolean(tpvCart?.cart)")
                page.wait_for_timeout(150)
                value = page.evaluate("""async () => {
                    const cart=document.querySelector('#sale-cart');
                    return new Promise((resolve,reject)=>{
                        const start=performance.now();
                        const timer=setTimeout(()=>reject(new Error("No visual cart mutation within 10s")),10000);
                        const observer=new MutationObserver(()=>{
                            observer.disconnect();clearTimeout(timer);
                            requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(performance.now()-start)));
                        });
                        observer.observe(cart,{subtree:true,childList:true,characterData:true});
                        document.querySelector('.product-card').click();
                    });
                }""")
                if mode == "optimistic":
                    self.settled(page)
                else:
                    page.wait_for_function("!document.querySelector('.htmx-request')")
                http = page.evaluate("""() => performance.getEntriesByType('resource')
                    .filter(x=>x.name.endsWith('/lines/add/')||x.name.endsWith('/cart-sync/')).at(-1)?.duration""")
                self.assertEqual(
                    sum(line.quantity for line in sale.lines.all()), lines + 1
                )
                samples.append(
                    {
                        "lines": lines,
                        "mode": mode,
                        "sample": sample,
                        "frame_bound_ms": value,
                        "http_ms": http,
                    }
                )
                page.unroute_all(behavior="wait")
                page.close()
    self.measurements.append(
        {
            "scenario": "frontend A/B with 400ms artificial response delay",
            "matrix": samples,
        }
    )


VisualMatrix.test_matrix = matrix

"""End-to-end optimistic UI on synthetic data and a local HTTP test server."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client
from django.urls import reverse
from playwright.sync_api import sync_playwright

from apps.sales.models import CartOperation
from tests.performance.dataset import Dataset


class OptimisticCartBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        cls.async_guard = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        cls.async_guard.start()
        cls.addClassCleanup(cls.async_guard.stop)
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.getenv("TPV_CHROMIUM")
            or ("/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None),
            headless=True,
        )
        cls.measurements = []

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        output = os.getenv("TPV_CART_BROWSER_REPORT")
        if output:
            Path(output).write_text(json.dumps(cls.measurements, indent=2) + "\n")
        super().tearDownClass()

    def setUp(self):
        self.d = Dataset(20, label="browser-cart")
        self.sale, _ = self.d.sale(0)
        client = Client()
        client.force_login(self.d.user)
        self.context = self.browser.new_context(viewport={"width": 1365, "height": 900})
        self.context.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": client.cookies["sessionid"].value,
                    "url": self.live_server_url,
                }
            ]
        )
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.url = self.live_server_url + reverse(
            "sales:sale_detail", args=[self.d.store.pk, self.sale.pk]
        )
        self.page.goto(self.url)
        self.page.wait_for_function("Boolean(window.tpvCart?.cart)")

    def tearDown(self):
        self.page.unroute_all(behavior="wait")
        self.context.close()
        self.assertEqual(self.errors, [])

    def settled(self, page=None):
        page = page or self.page
        page.wait_for_function(
            "window.tpvCart.ops.length===0 && !window.tpvCart.busy && !window.tpvCart.error",
            timeout=45000,
        )

    def add(self, count=1, different=False):
        values = self.page.evaluate(
            """({count,different}) => {
          const cards=[...document.querySelectorAll('.product-grid form')];
          const measurements=[];
          for(let i=0;i<count;i++) {
            const start=performance.now();cards[different?i:0].requestSubmit();
            const visible=document.querySelectorAll('[data-optimistic-row]').length;
            measurements.push({ms:performance.now()-start,visible});
          }
          return measurements;
        }""",
            {"count": count, "different": different},
        )
        self.measurements.append(
            {"count": count, "different": different, "interactions": values}
        )
        self.assertTrue(all(x["visible"] > 0 for x in values))
        return values

    def test_twenty_same_product_immediate_and_persisted(self):
        self.add(20)
        self.assertEqual(self.page.locator("[data-optimistic-row]").count(), 1)
        self.settled()
        self.assertEqual(sum(line.quantity for line in self.sale.lines.all()), 20)
        self.assertEqual(CartOperation.objects.filter(sale=self.sale).count(), 20)

    def test_twenty_different_products_and_stable_dom(self):
        self.add(20, different=True)
        self.page.evaluate(
            "window.savedRow=document.querySelector('[data-optimistic-row]')"
        )
        self.settled()
        self.assertEqual(self.sale.lines.count(), 20)
        self.assertTrue(
            self.page.evaluate(
                "savedRow===document.querySelector('[data-optimistic-row]')"
            )
        )
        self.assertEqual(self.page.locator("[data-optimistic-row]").count(), 20)

    def test_quantity_during_sync_then_delete(self):
        self.add()
        self.page.evaluate("""() => {
          document.querySelector('[data-plus]').click();
          document.querySelector('[data-plus]').click();
          document.querySelector('[data-delete]').click();
        }""")
        self.assertEqual(self.page.locator("[data-optimistic-row]").count(), 0)
        self.settled()
        self.assertFalse(self.sale.lines.exists())

    def test_offline_retry_and_reload_durable_intents(self):
        self.context.set_offline(True)
        self.add(3)
        self.page.wait_for_function("Boolean(tpvCart.error)")
        self.assertEqual(len(self.page.evaluate("tpvCart.ops")), 3)
        self.context.set_offline(False)
        self.page.reload()
        self.settled()
        self.assertEqual(sum(line.quantity for line in self.sale.lines.all()), 3)

    def test_lost_response_timeout_replay_does_not_duplicate(self):
        dropped = [False]

        def lose_response(route):
            if route.request.method == "POST" and not dropped[0]:
                dropped[0] = True
                route.fetch()  # The server commits, but its response never reaches JS.
                route.abort("failed")
            else:
                route.continue_()

        self.page.route("**/cart-sync/", lose_response)
        self.add()
        self.page.wait_for_function("Boolean(tpvCart.error)")
        self.assertEqual(self.sale.lines.count(), 1)
        self.page.evaluate("tpvCart.retry()")
        self.settled()
        self.assertEqual(self.sale.lines.count(), 1)
        self.assertEqual(CartOperation.objects.filter(sale=self.sale).count(), 1)

    def test_two_tabs_conflict_requires_explicit_resolution(self):
        self.add()
        self.settled()
        other = self.context.new_page()
        other.goto(self.url)
        other.wait_for_function("Boolean(window.tpvCart?.cart)")
        # Prevent passive storage refresh to deliberately reproduce a stale tab.
        other.evaluate("tpvCart.read=async()=>({cart:tpvCart.cart})")
        self.page.locator("[data-plus]").click()
        self.settled()
        other.locator("[data-plus]").click()
        other.wait_for_function("tpvCart.conflict")
        self.assertEqual(sum(line.quantity for line in self.sale.lines.all()), 2)
        other.get_by_role(
            "button", name="Descartar pendientes y recuperar venta"
        ).click()
        self.assertEqual(CartOperation.objects.filter(sale=self.sale).count(), 2)

    def test_checkout_opens_shell_and_flushes_pending_before_enabling_payment(self):
        self.add(5)
        self.page.locator("[data-checkout-open]").click()
        self.assertTrue(self.page.locator("#checkout-dialog").evaluate("x=>x.open"))
        self.page.wait_for_selector("[data-checkout-form]")
        self.assertEqual(self.page.locator('[name="cart_version"]').input_value(), "5")
        self.assertEqual(sum(line.quantity for line in self.sale.lines.all()), 5)
        self.assertTrue(self.page.evaluate("tpvCart.frozen"))

    def test_rejected_inactive_product_can_discard_pending(self):
        self.d.products[0].is_active = False
        self.d.products[0].save()
        self.add()
        self.page.wait_for_function("tpvCart.rejected")
        self.assertFalse(self.sale.lines.exists())
        self.page.get_by_role(
            "button", name="Descartar pendientes y recuperar venta"
        ).click()
        self.settled()
        self.assertEqual(self.page.locator("[data-optimistic-row]").count(), 0)

    def test_slow_response_does_not_block_visual_change_or_search(self):
        def slow(route):
            if route.request.method == "POST":
                time.sleep(0.5)
            route.continue_()

        self.page.route("**/cart-sync/", slow)
        measurements = self.add(3)
        self.assertTrue(all(x["ms"] < 100 for x in measurements))
        self.page.locator("[data-tpv-search]").fill("Producto")
        self.settled()
        self.assertEqual(sum(line.quantity for line in self.sale.lines.all()), 3)

    def test_actual_timeout_replays_original_operation_identity(self):
        self.page.evaluate("""() => {
          window.originalTimer=window.setTimeout;
          window.setTimeout=(fn,delay,...args)=>originalTimer(fn,delay===15000?40:delay,...args);
        }""")
        lost = [False]

        def timeout_response(route):
            if route.request.method == "POST" and not lost[0]:
                lost[0] = True
                route.fetch()
                time.sleep(0.08)
                route.abort("failed")
            else:
                route.continue_()

        self.page.route("**/cart-sync/", timeout_response)
        self.add()
        self.page.wait_for_function("Boolean(tpvCart.error)")
        key = self.page.evaluate("tpvCart.ops[0].key")
        self.page.evaluate("window.setTimeout=window.originalTimer;tpvCart.retry()")
        self.settled()
        self.assertEqual(self.sale.lines.count(), 1)
        self.assertEqual(str(CartOperation.objects.get(sale=self.sale).key), key)

    def test_decimal_quantity_focus_scroll_and_tablet(self):
        self.context.set_default_timeout(10000)
        self.page.set_viewport_size({"width": 1024, "height": 768})
        self.add(20, different=True)
        self.settled()
        self.page.evaluate("""() => {
          const region=document.querySelector('[data-cart-scroll-region]');region.scrollTop=120;
          window.scrollBefore=region.scrollTop;
          const input=document.querySelector('[data-optimistic-row] input');
          input.focus({preventScroll:true});input.value='1.125';input.dispatchEvent(new Event('change',{bubbles:true}));
          window.focusedInput=input;
        }""")
        self.settled()
        self.assertTrue(self.page.evaluate("document.activeElement===focusedInput"))
        self.assertTrue(
            self.page.evaluate(
                "document.querySelector('[data-cart-scroll-region]').scrollTop===scrollBefore"
            )
        )
        self.assertEqual(str(self.sale.lines.order_by("pk").first().quantity), "1.125")

    def test_frame_latency_measured_separately_from_slow_http(self):
        def slow(route):
            if route.request.method == "POST":
                time.sleep(0.4)
            route.continue_()

        self.page.route("**/cart-sync/", slow)
        measurements = []
        for _ in range(10):
            value = self.page.evaluate("""async () => {
              const start=performance.now();document.querySelector('.product-grid form').requestSubmit();
              const dom=performance.now()-start;
              await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
              return {dom_ms:dom,frame_bound_ms:performance.now()-start};
            }""")
            measurements.append(value)
            self.settled()
        self.measurements.append(
            {
                "scenario": "single add with 400ms artificial response delay",
                "samples": measurements,
                "http_ms": self.page.evaluate(
                    "performance.getEntriesByType('resource').filter(x=>x.name.includes('cart-sync')&&x.initiatorType==='fetch').map(x=>x.duration)"
                ),
            }
        )

    def test_twenty_quantity_steps_coalesce_without_losing_units(self):
        self.add()
        self.settled()
        self.page.evaluate("""() => {
            for(let i=0;i<20;i++)document.querySelector('[data-plus]').click();
        }""")
        self.settled()
        self.assertEqual(sum(line.quantity for line in self.sale.lines.all()), 21)
        self.assertEqual(CartOperation.objects.filter(sale=self.sale).count(), 2)

    def test_older_read_cannot_replace_newer_confirmed_cart(self):
        result = self.page.evaluate("""async () => {
            let resolve;
            const q=new SalesCartQueue({storage:sessionStorage,prefix:'test-old-read:',
                send:async()=>{},read:()=>new Promise(r=>resolve=r)});
            q.cart={version:2,lines:[]};const refresh=q.refresh();
            q.cart={version:3,lines:[{id:1,quantity:'4'}]};
            resolve({cart:{version:2,lines:[]},receipts:[]});await refresh;
            return q.cart;
        }""")
        self.assertEqual(result["version"], 3)
        self.assertEqual(result["lines"][0]["quantity"], "4")

    def test_manual_price_editor_reconciles_grouped_rows(self):
        self.add(2)
        self.settled()
        self.page.locator("[data-editors] summary").click()
        self.page.get_by_role(
            "link", name="Editar precio · línea 1", exact=True
        ).click()
        self.page.wait_for_selector('.line-editor [name="unit_base_price"]')
        self.page.locator('.line-editor [name="unit_base_price"]').fill("11.00")
        self.page.get_by_role("button", name="Guardar cambios").click()
        self.page.wait_for_function(
            "tpvCart.cart.lines.some(line=>line.price==='11.00')"
        )
        self.assertEqual(self.page.locator("[data-optimistic-row]").count(), 2)
        self.assertEqual(
            self.page.locator(
                ".cart-lines > article:not([data-optimistic-row])"
            ).count(),
            0,
        )
        self.assertFalse(
            self.page.locator("#line-editor-dialog").evaluate("dialog=>dialog.open")
        )

    def test_invalid_quantity_is_visible_and_blocks_checkout_until_fixed(self):
        self.add()
        self.settled()
        field = self.page.locator("[data-optimistic-row] input")
        field.fill("0")
        self.assertEqual(field.get_attribute("aria-invalid"), "true")
        self.page.locator("[data-checkout-open]").click()
        self.assertFalse(
            self.page.locator("#checkout-dialog").evaluate("dialog=>dialog.open")
        )
        self.assertEqual(sum(line.quantity for line in self.sale.lines.all()), 1)
        field.fill("1.125")
        self.settled()
        self.assertEqual(field.get_attribute("aria-invalid"), "false")
        self.assertEqual(str(self.sale.lines.first().quantity), "1.125")

    def external_quantity(self, quantity):
        from uuid import uuid4
        from apps.sales.cart import mutate

        self.sale.refresh_from_db()
        line = self.sale.lines.order_by("pk").first()
        mutate(
            business=self.d.business,
            store=self.d.store,
            sale_id=self.sale.pk,
            user=self.d.user,
            data={
                "key": str(uuid4()),
                "kind": "quantity",
                "line": line.pk,
                "version": self.sale.cart_version,
                "quantity": str(quantity),
            },
        )

    def test_replayed_receipt_does_not_rebase_pending_quantity_over_other_tab(self):
        self.add()
        self.settled()
        lost = [False]

        def lose(route):
            if route.request.method == "POST" and not lost[0]:
                lost[0] = True
                route.fetch()
                route.abort("failed")
            else:
                route.continue_()

        self.page.route("**/cart-sync/", lose)
        self.page.locator("[data-plus]").click()
        self.page.wait_for_function("Boolean(tpvCart.error)")
        self.page.locator("[data-plus]").click()
        self.external_quantity(5)
        self.page.evaluate("tpvCart.retry()")
        self.page.wait_for_function("tpvCart.conflict")
        self.assertEqual(str(self.sale.lines.first().quantity), "5.000")
        self.assertEqual(self.page.evaluate("tpvCart.ops.length"), 1)
        self.page.get_by_role(
            "button", name="Descartar pendientes y recuperar venta"
        ).click()
        self.settled()
        self.assertEqual(str(self.sale.lines.first().quantity), "5.000")

    def test_reload_unsent_intent_detects_changed_baseline(self):
        self.add()
        self.settled()
        self.page.evaluate("""() => {
            tpvCart.busy=true;
            tpvCart.enqueue({kind:'quantity',line:tpvCart.cart.lines[0].id,quantity:'2.000'});
        }""")
        self.external_quantity(5)
        self.page.reload()
        self.page.wait_for_function("Boolean(tpvCart?.conflict)")
        self.assertEqual(str(self.sale.lines.first().quantity), "5.000")
        self.page.get_by_role(
            "button", name="Descartar pendientes y recuperar venta"
        ).click()
        self.settled()

    def test_reload_preserves_add_quantity_delete_order_with_arbitrary_storage_iteration(
        self,
    ):
        result = self.page.evaluate("""() => {
            const values=new Map();
            const storage={get length(){return values.size;},
                key:i=>[...values.keys()].reverse()[i],
                getItem:key=>values.get(key)||null,
                setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
            const originalUuid=crypto.randomUUID,originalDate=Date.now,originalPerformance=performance.now;
            let sequence=4;
            try {
                crypto.randomUUID=()=>`00000000-0000-4000-8000-${String(--sequence).padStart(12,'0')}`;
                Date.now=()=>1700000000000;performance.now=()=>0;
                const options={storage,prefix:'restore-order:',send:async()=>{},read:async()=>({})};
                const queue=new SalesCartQueue(options);
                queue.cart={version:0,status:'open',lines:[]};queue.busy=true;
                const key=queue.enqueue({kind:'add',product:1,quantity:'1',price:'1',estimate:'1',name:'Test'});
                queue.enqueue({kind:'quantity',line:'tmp:'+key,quantity:'2'});
                queue.enqueue({kind:'delete',line:'tmp:'+key});
                const restored=new SalesCartQueue(options);restored.cart=queue.cart;
                return {before:queue.visible(),after:restored.visible()};
            } finally {
                crypto.randomUUID=originalUuid;Date.now=originalDate;performance.now=originalPerformance;
            }
        }""")
        self.assertEqual(result["before"], [])
        self.assertEqual(result["after"], [])

"""Phase 2C transport, storage and bounded checkout recovery on synthetic fixtures."""

import json
import time
from e2e import browser_optimistic_cart as base
from apps.sales.models import CartOperation


class HardenedCartBrowserTests(base.OptimisticCartBrowserTests):
    def test_aborted_checkout_worker_finishes_before_database_flush(self):
        from threading import Event, current_thread
        from unittest.mock import patch

        from django.db import connection

        from apps.sales.views import SaleCheckoutView

        entered, release, finished = Event(), Event(), Event()
        worker = {}
        original_get = SaleCheckoutView.get

        def delayed(view, request, *args, **kwargs):
            worker["thread"] = current_thread()
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    worker["pid"] = cursor.fetchone()[0]
            entered.set()
            try:
                if not release.wait(timeout=10):
                    raise AssertionError("Server shutdown did not release checkout")
                return original_get(view, request, *args, **kwargs)
            finally:
                finished.set()

        self.add()
        self.settled()
        # Exercise the shared keepalive pool used by route.fetch(), too.
        response = self.context.request.get(self.url)
        self.assertEqual(response.status, 200)
        response.dispose()
        self.enterContext(patch.object(SaleCheckoutView, "get", delayed))
        self.page.locator("[data-checkout-open]").click()
        self.assertTrue(entered.wait(timeout=10))
        self.page.keyboard.press("Escape")
        self.context.close()
        self.assertFalse(finished.is_set())

        server = self.server_thread.httpd
        original_shutdown = server.shutdown

        def shutdown():
            original_shutdown()
            release.set()

        server.shutdown = shutdown
        original_flush = self._fixture_teardown

        def checked_flush():
            try:
                self.assertTrue(finished.is_set(), "flush raced an aborted request")
                self.assertFalse(worker["thread"].is_alive())
                if "pid" in worker:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT count(*) FROM pg_stat_activity WHERE pid = %s",
                            [worker["pid"]],
                        )
                        self.assertEqual(cursor.fetchone()[0], 0)
            finally:
                # Release the held worker even when the assertion fails.
                release.set()
                worker["thread"].join(timeout=10)
                original_flush()

        self._fixture_teardown = checked_flush

    def test_fifty_clicks_one_atomic_request_preserves_snapshots(self):
        requests = []
        self.page.on(
            "request",
            lambda request: (
                requests.append(request.post_data_json)
                if request.method == "POST" and "/cart-sync/" in request.url
                else None
            ),
        )
        self.add(50)
        self.settled()
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(requests[0]["operations"]), 50)
        self.assertEqual(self.sale.lines.count(), 50)
        self.assertEqual(CartOperation.objects.filter(sale=self.sale).count(), 50)
        self.assertEqual(sum(x.quantity for x in self.sale.lines.all()), 50)

    def test_batch_provisional_quantity_delete_dependencies(self):
        self.page.evaluate("tpvCart.busy=true")
        self.add(3)
        self.page.evaluate("""() => {
            const key=tpvCart.ops[2].key;
            tpvCart.enqueue({kind:'quantity',line:'tmp:'+key,quantity:'2.125'});
            tpvCart.enqueue({kind:'delete',line:'tmp:'+key});
            tpvCart.busy=false;tpvCart.pump();
        }""")
        self.settled()
        self.assertEqual(self.sale.lines.count(), 2)
        self.assertEqual(CartOperation.objects.filter(sale=self.sale).count(), 5)

    def test_lost_batch_response_reload_replays_original_envelope(self):
        lost = []

        def lose(route):
            if route.request.method == "POST" and not lost:
                lost.append(route.request.post_data_json)
                route.fetch()
                route.abort("failed")
            else:
                route.continue_()

        self.page.route("**/cart-sync/", lose)
        self.add(20)
        self.page.wait_for_function("Boolean(tpvCart.error)")
        journal = self.page.evaluate("sessionStorage.getItem(tpvCart.prefix+'flight')")
        self.assertTrue(journal)
        self.page.reload()
        self.settled()
        self.assertEqual(self.sale.lines.count(), 20)
        self.assertEqual(CartOperation.objects.filter(sale=self.sale).count(), 20)
        self.assertEqual(
            self.page.evaluate("sessionStorage.getItem(tpvCart.prefix+'flight')"), None
        )
        self.assertEqual(len(json.loads(journal)["ops"]), 20)

    def test_quota_failure_before_envelope_send_is_recoverable(self):
        self.page.evaluate("""() => {
            window.originalSetItem=Storage.prototype.setItem;
            Storage.prototype.setItem=function(key,value) {
                if(key.endsWith(':flight'))throw new DOMException('Quota','QuotaExceededError');
                return originalSetItem.call(this,key,value);
            };
        }""")
        self.add(2)
        self.page.wait_for_function("Boolean(tpvCart.error)")
        self.assertEqual(self.sale.lines.count(), 0)
        self.page.evaluate(
            "Storage.prototype.setItem=window.originalSetItem;tpvCart.retry()"
        )
        self.settled()
        self.assertEqual(self.sale.lines.count(), 2)

    def test_partial_local_cleanup_restores_entire_committed_envelope(self):
        self.page.evaluate("""() => {
            window.originalRemove=Storage.prototype.removeItem;
            let removed=0;
            Storage.prototype.removeItem=function(key) {
                if(key.includes(':op:') && ++removed===2)throw new Error('Simulated local cleanup failure');
                return originalRemove.call(this,key);
            };
        }""")
        self.add(10)
        self.page.wait_for_function("Boolean(tpvCart.error)")
        self.assertEqual(self.sale.lines.count(), 10)
        self.page.reload()
        self.settled()
        self.assertEqual(self.sale.lines.count(), 10)
        self.assertEqual(CartOperation.objects.filter(sale=self.sale).count(), 10)

    def test_namespace_never_imports_other_user_business_store_or_sale(self):
        counts = self.page.evaluate("""() => {
            const values=new Map();
            const storage={get length(){return values.size;},key:i=>[...values.keys()][i],
                getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};
            const options={storage,send:async()=>{},read:async()=>({})};
            const queue=new SalesCartQueue({...options,prefix:'nx-cart:1:1:1:1:'});
            queue.cart={version:0,status:'open',lines:[]};queue.busy=true;
            queue.enqueue({kind:'add',product:1,quantity:'1'});
            return ['nx-cart:2:1:1:1:','nx-cart:1:2:1:1:','nx-cart:1:1:2:1:','nx-cart:1:1:1:2:']
                .map(prefix=>new SalesCartQueue({...options,prefix}).ops.length);
        }""")
        self.assertEqual(counts, [0, 0, 0, 0])

    def test_unavailable_storage_quota_does_not_accept_a_click(self):
        self.page.evaluate("""() => {
            window.originalSetItem=Storage.prototype.setItem;
            Storage.prototype.setItem=function(key,value) {
                if(key.includes(':op:'))throw new DOMException('Quota','QuotaExceededError');
                return originalSetItem.call(this,key,value);
            };
            document.querySelector('.product-grid form').requestSubmit();
            Storage.prototype.setItem=window.originalSetItem;
        }""")
        self.assertEqual(self.page.evaluate("tpvCart.ops.length"), 0)
        self.assertFalse(self.sale.lines.exists())
        self.assertTrue(self.page.evaluate("Boolean(tpvCart.error)"))

    def test_corrupt_storage_blocks_editing_without_silent_fallback(self):
        self.page.evaluate(
            "sessionStorage.setItem(tpvCart.prefix+'op:broken','{invalid')"
        )
        self.page.reload()
        self.page.get_by_role("alert").filter(has_text="diario local").wait_for()
        self.assertTrue(self.page.locator(".product-card").first.is_disabled())
        self.page.evaluate(
            "document.querySelector('.product-grid form').requestSubmit()"
        )
        self.page.wait_for_timeout(100)
        self.assertFalse(self.sale.lines.exists())
        self.assertIn(
            "{invalid", self.page.evaluate("JSON.stringify({...sessionStorage})")
        )

    def test_invalid_flight_revision_is_quarantined_without_deletion(self):
        self.page.evaluate(
            "sessionStorage.setItem(tpvCart.prefix+'flight',JSON.stringify({version:-1,ops:[]}))"
        )
        self.page.reload()
        self.page.get_by_role("alert").filter(has_text="diario local").wait_for()
        self.assertTrue(self.page.locator(".product-card").first.is_disabled())
        self.assertIn(
            '"version":-1',
            self.page.evaluate("JSON.stringify({...sessionStorage})").replace(
                '\\"', '"'
            ),
        )

    def test_header_timeout_clears_wait_but_blocks_checkout(self):
        held = []
        self.page.evaluate("tpvCart.headerTimeout=100;tpvCart.flushTimeout=500")
        self.page.route("**/header/", lambda route: held.append(route))
        self.page.locator("#header-document-invoice").check()
        self.add()
        self.page.locator("[data-checkout-open]").click()
        self.page.wait_for_function(
            "tpvCart.headerPending===0 && Boolean(tpvCart.headerError)"
        )
        self.page.locator("#checkout-panel").get_by_text(
            "No se ha verificado", exact=False
        ).wait_for()
        self.assertEqual(
            self.page.locator("#checkout-panel [name=cart_version]").count(), 0
        )
        for route in held:
            route.abort("failed")

    def test_header_http_error_requires_review(self):
        self.page.route(
            "**/header/",
            lambda route: route.fulfill(
                status=422, body='<p role="alert">Rechazo de prueba</p>'
            ),
        )
        self.page.locator("#header-document-invoice").click()
        self.page.wait_for_function("Boolean(tpvCart.headerError)")
        self.assertEqual(self.page.evaluate("tpvCart.headerPending"), 0)
        self.assertEqual(
            self.page.locator(".tpv-sync-status").get_attribute("data-state"),
            "intervention",
        )

    def test_header_network_abort_has_bounded_recovery(self):
        self.page.evaluate("tpvCart.headerTimeout=80")
        self.page.route("**/header/", lambda route: route.abort("failed"))
        self.page.locator("#header-document-invoice").check()
        self.page.wait_for_function(
            "tpvCart.headerPending===0 && Boolean(tpvCart.headerError)"
        )

    def test_incompatible_worker_or_identity_never_sends_pending_mutations(self):
        self.page.evaluate("""async () => {
            tpvCart.read=async()=>({cart:tpvCart.cart,protocol:1,user_id:tpvCart.expectedUser});
            try{await tpvCart.refresh();}catch(_){}
        }""")
        self.add()
        self.page.wait_for_timeout(100)
        self.assertFalse(self.sale.lines.exists())
        self.assertFalse(self.page.evaluate("tpvCart.protocolReady"))
        self.assertEqual(self.page.evaluate("tpvCart.ops.length"), 1)

    def test_stuck_busy_or_header_flag_has_bounded_flush(self):
        result = self.page.evaluate("""async () => {
            const results=[];
            for(const field of ['busy','headerPending']) {
                const storage={length:0,getItem:()=>null,setItem:()=>{},removeItem:()=>{}};
                const queue=new SalesCartQueue({storage,prefix:'test:',read:async()=>({}),send:async()=>{}});
                queue.cart={version:0,status:'open',lines:[]};queue.flushTimeout=60;
                queue[field]=1;
                const start=performance.now();
                try {await queue.flush();results.push({resolved:true});}
                catch(error){results.push({ms:performance.now()-start,error:error.message,waiters:queue.waiters.size});}
            }
            return results;
        }""")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(x["ms"] < 1000 and x["waiters"] == 0 for x in result))

    def test_close_reopen_cancels_only_local_flush_wait(self):
        self.page.route(
            "**/cart-sync/",
            lambda route: (
                route.abort("failed")
                if route.request.method == "POST"
                else route.continue_()
            ),
        )
        self.add()
        self.page.wait_for_function("Boolean(tpvCart.error)")
        self.page.locator("[data-checkout-open]").click()
        self.page.keyboard.press("Escape")
        self.page.wait_for_function("!tpvCart.frozen")
        self.page.unroute("**/cart-sync/")
        self.page.evaluate("tpvCart.retry()")
        self.settled()
        self.page.locator("[data-checkout-open]").click()
        self.page.locator("#checkout-panel [name=cart_version]").wait_for(
            state="attached"
        )
        self.assertEqual(self.sale.lines.count(), 1)

    def test_stale_checkout_read_cannot_fill_reopened_modal(self):
        from threading import Event
        from unittest.mock import patch
        from apps.sales.views import SaleCheckoutView

        self.add()
        self.settled()
        entered, release, finished = Event(), Event(), Event()
        original = SaleCheckoutView.get

        def delayed(view, request, *args, **kwargs):
            first = not entered.is_set()
            if first:
                entered.set()
                release.wait(timeout=10)
            response = original(view, request, *args, **kwargs)
            if first:
                response.content = (
                    b'<p id="obsolete-response">Obsoleto</p>' + response.content
                )
                finished.set()
            return response

        with patch.object(SaleCheckoutView, "get", delayed):
            try:
                self.page.locator("[data-checkout-open]").click()
                deadline = time.monotonic() + 10
                while not entered.is_set() and time.monotonic() < deadline:
                    self.page.wait_for_timeout(20)
                self.assertTrue(entered.is_set())
                self.page.keyboard.press("Escape")
                self.page.wait_for_function("!tpvCart.frozen")
                release.set()
                self.page.locator("[data-checkout-open]").click()
                self.page.locator("#checkout-panel [name=cart_version]").wait_for(
                    state="attached"
                )
                while not finished.is_set() and time.monotonic() < deadline:
                    self.page.wait_for_timeout(20)
                self.assertTrue(finished.is_set())
                self.assertEqual(self.page.locator("#obsolete-response").count(), 0)
                self.assertTrue(
                    self.page.locator("#checkout-dialog").evaluate(
                        "element=>element.open"
                    )
                )
            finally:
                release.set()

    def test_abandon_warning_only_while_changes_are_unverified(self):
        self.page.evaluate("tpvCart.busy=true")
        self.add()
        self.assertTrue(
            self.page.evaluate("""() => {
            const event=new Event('beforeunload',{cancelable:true});
            window.dispatchEvent(event);return event.defaultPrevented;
        }""")
        )
        self.page.evaluate("tpvCart.busy=false;tpvCart.pump()")
        self.settled()
        self.assertFalse(
            self.page.evaluate("""() => {
            const event=new Event('beforeunload',{cancelable:true});
            window.dispatchEvent(event);return event.defaultPrevented;
        }""")
        )

    def test_expired_login_preserves_unknown_intent_until_same_user_revalidates(self):
        from django.test import Client

        self.page.route(
            "**/cart-sync/",
            lambda route: (
                route.abort("failed")
                if route.request.method == "POST"
                else route.continue_()
            ),
        )
        self.add()
        self.page.wait_for_function("Boolean(tpvCart.error)")
        key = self.page.evaluate("tpvCart.ops[0].key")
        self.page.unroute("**/cart-sync/")
        self.context.clear_cookies()
        self.page.evaluate("tpvCart.retry()")
        self.page.wait_for_function("Boolean(tpvCart.error) && !tpvCart.busy")
        self.assertFalse(self.sale.lines.exists())
        client = Client()
        client.force_login(self.d.user)
        self.context.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": client.cookies["sessionid"].value,
                    "url": self.live_server_url,
                }
            ]
        )
        self.page.reload()
        self.settled()
        self.assertEqual(self.sale.lines.count(), 1)
        self.assertEqual(str(CartOperation.objects.get(sale=self.sale).key), key)

    def test_forced_close_reopen_keeps_only_server_confirmed_state(self):
        self.page.route(
            "**/cart-sync/",
            lambda route: (
                route.abort("failed")
                if route.request.method == "POST"
                else route.continue_()
            ),
        )
        self.add()
        self.page.wait_for_function("Boolean(tpvCart.error)")
        # Forced termination models loss of tab context, bypassing beforeunload.
        self.page.close()
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.url)
        self.page.wait_for_function("Boolean(window.tpvCart?.protocolReady)")
        self.assertEqual(self.page.evaluate("tpvCart.ops.length"), 0)
        self.assertFalse(self.sale.lines.exists())

    def test_keyboard_wedge_search_and_enter_preserve_units(self):
        product = self.d.products[0]
        self.page.locator("[data-tpv-search]").fill(product.sku)
        self.page.locator(".product-card").first.wait_for()
        button = self.page.locator(".product-card").first
        button.focus()
        for _ in range(10):
            self.page.keyboard.press("Enter")
        self.settled()
        self.assertEqual(sum(line.quantity for line in self.sale.lines.all()), 10)


# Fixture reuse only; the original suite runs separately.
for _name in dir(base.OptimisticCartBrowserTests):
    if _name.startswith("test_") and _name not in HardenedCartBrowserTests.__dict__:
        setattr(HardenedCartBrowserTests, _name, None)

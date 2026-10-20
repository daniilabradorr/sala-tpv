/* Sales optimistic cart: durable intents, one mutation in flight, explicit conflicts. */
(() => {
  "use strict";
  class CartQueue {
    constructor({ storage, prefix, send, read, changed }) {
      Object.assign(this, { storage, prefix, send, read, changed });
      this.ops = [];
      this.cart = null;
      this.busy = false;
      this.error = "";
      this.conflict = false;
      this.rejected = false;
      this.acknowledged = new Set();
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i);
        if (key.startsWith(prefix + "op:"))
          this.ops.push(JSON.parse(storage.getItem(key)));
      }
      this.ops.sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));
      this.sequence = this.ops.reduce(
        (maximum, op) => Math.max(maximum, op.order),
        0,
      );
    }
    save(op) {
      this.storage.setItem(this.prefix + "op:" + op.key, JSON.stringify(op));
    }
    notify() {
      this.changed?.(this);
    }
    async refresh() {
      const result = await this.read();
      const cart = result.cart;
      if (!this.cart || cart.version >= this.cart.version) {
        this.cart = cart;
        this.acknowledged = new Set((result.receipts || []).map((x) => x.key));
        for (const receipt of result.receipts || []) {
          if (receipt.line)
            this.storage.setItem(
              this.prefix + "map:" + receipt.key,
              JSON.stringify(receipt.line),
            );
        }
      }
      this.notify();
    }
    enqueue(intent) {
      if (
        this.frozen ||
        this.rejected ||
        !this.cart ||
        this.cart.status !== "open"
      )
        return false;
      const previous = this.ops.at(-1);
      if (
        intent.kind === "quantity" &&
        previous?.kind === "quantity" &&
        previous.line === intent.line &&
        previous.version === undefined
      ) {
        const replacement = { ...previous, quantity: intent.quantity };
        try {
          this.save(replacement);
        } catch (_) {
          this.error =
            "No se pueden guardar los cambios pendientes. Libera espacio y reintenta.";
          this.notify();
          return false;
        }
        this.ops[this.ops.length - 1] = replacement;
        this.notify();
        return replacement.key;
      }
      const op = {
        ...intent,
        key: crypto.randomUUID(),
        baseVersion: this.cart.version,
        order: ++this.sequence,
      };
      try {
        this.save(op);
      } catch (_) {
        this.error =
          "No se pueden guardar cambios pendientes en este navegador. Libera espacio y recarga.";
        this.notify();
        return false;
      }
      this.ops.push(op);
      this.notify();
      // A microtask starts network work after the synchronous visual update.
      queueMicrotask(() => this.pump());
      return op.key;
    }
    resolve(line) {
      return typeof line === "string" && line.startsWith("tmp:")
        ? JSON.parse(
            this.storage.getItem(this.prefix + "map:" + line.slice(4)) ||
              "null",
          )
        : line;
    }
    visible() {
      const lines = (this.cart?.lines || []).map((x) => ({ ...x }));
      for (const op of this.ops) {
        if (this.acknowledged.has(op.key)) continue;
        const id = this.resolve(op.line) ?? op.line;
        if (op.kind === "add")
          lines.push({
            id: "tmp:" + op.key,
            product: op.product,
            name: op.name,
            quantity: op.quantity,
            price: op.price,
            total: op.estimate,
            group: op.group || "product:" + op.product,
            provisional: true,
          });
        else {
          const index = lines.findIndex((x) => String(x.id) === String(id));
          if (index < 0) continue;
          if (op.kind === "delete") lines.splice(index, 1);
          else {
            const line = lines[index];
            line.total = String(
              (Number(line.total) * Number(op.quantity)) /
                Number(line.quantity),
            );
            line.quantity = op.quantity;
            line.provisional = true;
          }
        }
      }
      return lines;
    }
    async pump() {
      if (this.busy || this.error || !this.cart || !this.ops.length) return;
      this.busy = true;
      this.notify();
      const op = this.ops[0];
      try {
        if (op.version === undefined && op.baseVersion !== this.cart.version) {
          this.conflict = this.rejected = true;
          this.error =
            "La venta ha cambiado desde que preparaste estos cambios. Revisa el estado confirmado.";
          await this.refresh();
          return;
        }
        if (op.version === undefined) {
          op.version = this.cart.version;
          this.save(op);
        }
        const line = this.resolve(op.line);
        if (op.kind !== "add" && !line)
          throw new Error("Falta la confirmación de una línea pendiente.");
        const result = await this.send({ ...op, line });
        if (result.status === 409 || result.status === 422) {
          this.conflict =
            result.status === 409 && result.body.code === "version";
          this.rejected = true;
          this.error = result.body.error;
          await this.refresh();
        } else if (result.status !== 200) {
          throw new Error(
            "No se recibió confirmación. Reintenta para comprobar la operación sin duplicarla.",
          );
        } else {
          // Persist dependency resolution BEFORE removing the accepted parent operation.
          if (op.kind === "add")
            this.storage.setItem(
              this.prefix + "map:" + op.key,
              JSON.stringify(result.body.line),
            );
          this.storage.removeItem(this.prefix + "op:" + op.key);
          this.ops.shift();
          if (result.body.cart.version >= this.cart.version)
            this.cart = result.body.cart;
          const externalChange =
            this.cart.version !== result.body.accepted_version;
          if (
            externalChange &&
            this.ops.length &&
            this.ops[0].version === undefined
          ) {
            this.conflict = this.rejected = true;
            this.error =
              "Otra ventana cambió la venta después de la operación confirmada. Revisa los pendientes antes de aplicarlos.";
            await this.refresh();
          } else if (!externalChange) {
            // Only our own confirmed transition may advance the baseline of
            // unsent intents. Never silently rebase them onto another editor.
            for (const pending of this.ops) {
              if (pending.version === undefined) {
                pending.baseVersion = this.cart.version;
                this.save(pending);
              }
            }
          }
        }
      } catch (error) {
        this.error =
          error.message || "Sin conexión. Los cambios siguen pendientes.";
      } finally {
        this.busy = false;
        this.notify();
      }
      if (!this.error) return this.pump();
    }
    async retry() {
      // Only a definitive 409 proves the mutation was not accepted. Never rebase
      // a timed-out operation: replay its original UUID and version first.
      if (this.rejected) return;
      this.error = "";
      await this.pump();
    }
    async acceptConflict() {
      if (!this.conflict || this.busy) return;
      const op = this.ops[0];
      // A definitive version conflict has no receipt. The user may explicitly
      // resubmit the same intent against the freshly reviewed version.
      delete op.version;
      op.baseVersion = this.cart.version;
      this.save(op);
      this.error = "";
      this.conflict = this.rejected = false;
      await this.pump();
    }
    async discard() {
      if (this.busy || !this.rejected) return;
      for (const op of this.ops)
        this.storage.removeItem(this.prefix + "op:" + op.key);
      this.ops = [];
      this.error = "";
      this.conflict = this.rejected = false;
      this.busy = true;
      this.notify();
      try {
        await this.refresh();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.busy = false;
        this.notify();
      }
    }
    async flush() {
      await this.pump();
      // A pump might already be active when checkout is clicked.
      while (this.busy) await new Promise((resolve) => setTimeout(resolve, 20));
      if (this.error || this.ops.length)
        throw new Error(this.error || "Hay cambios pendientes.");
      await this.refresh();
    }
  }
  window.SalesCartQueue = CartQueue;
  const root = document.querySelector(".tpv[data-cart-sync]");
  if (!root) return;
  const endpoint = root.dataset.cartSync;
  const csrf = () =>
    document.querySelector('[name="csrfmiddlewaretoken"]').value;
  const read = async () => {
    const pending = queue?.ops
      .slice(0, 50)
      .map((op) => op.key)
      .join(",");
    const r = await fetch(
      endpoint + (pending ? "?pending=" + encodeURIComponent(pending) : ""),
      { credentials: "same-origin", cache: "no-store" },
    );
    if (!r.ok)
      throw new Error(
        "No se puede recuperar esta venta. Comprueba sesión y permisos.",
      );
    return r.json();
  };
  const money = (value) =>
    new Intl.NumberFormat("es-ES", {
      style: "currency",
      currency: "EUR",
    }).format(value);
  let queue,
    checkoutRequested = false;
  const rows = new Map();
  const status = document.createElement("div");
  status.className = "tpv-sync-status";
  status.setAttribute("role", "status");
  function groups(lines) {
    const result = new Map();
    const variants = new Map();
    for (const line of lines) {
      if (!variants.has(line.product)) variants.set(line.product, new Set());
      if (line.group && line.group !== "product:" + line.product)
        variants.get(line.product).add(line.group);
    }
    for (const line of lines) {
      const choices = variants.get(line.product);
      const key =
        line.product == null
          ? "line:" + line.id
          : choices.size > 1
            ? line.group && choices.has(line.group)
              ? line.group
              : [...choices][0]
            : "product:" + line.product;
      if (!result.has(key))
        result.set(key, {
          key,
          name: line.name,
          product: line.product,
          lines: [],
          quantity: 0,
          total: 0,
        });
      const group = result.get(key);
      group.lines.push(line);
      group.quantity += Number(line.quantity);
      group.total += Number(line.total);
    }
    return [...result.values()].map((group) => ({
      ...group,
      quantity: Number(group.quantity.toFixed(3)),
    }));
  }
  function changeGroup(group, desired) {
    if (
      !Number.isFinite(desired) ||
      desired <= 0 ||
      Math.abs(Math.round(desired * 1000) - desired * 1000) > 1e-7
    )
      return;
    const difference = Math.round((desired - group.quantity) * 1000);
    if (!difference) return;
    if (difference > 0) {
      const line = group.lines.at(-1);
      queue.enqueue({
        kind: "quantity",
        line: line.id,
        quantity: (
          (Math.round(Number(line.quantity) * 1000) + difference) /
          1000
        ).toFixed(3),
      });
    } else {
      let remaining = -difference;
      for (const line of [...group.lines].reverse()) {
        if (!remaining) break;
        const current = Math.round(Number(line.quantity) * 1000);
        if (remaining >= current) {
          queue.enqueue({ kind: "delete", line: line.id });
          remaining -= current;
        } else {
          queue.enqueue({
            kind: "quantity",
            line: line.id,
            quantity: ((current - remaining) / 1000).toFixed(3),
          });
          remaining = 0;
        }
      }
    }
  }
  function render() {
    const container = document.querySelector(".cart-lines");
    if (!container || !queue.cart) return;
    if (!status.isConnected)
      document.querySelector(".cart-heading").after(status);
    status.replaceChildren();
    const message = document.createElement("span");
    message.textContent =
      queue.error ||
      (queue.ops.length
        ? `${queue.ops.length} cambios pendientes · importes provisionales`
        : "Sincronizado");
    status.append(message);
    if (queue.error) {
      const confirmed = document.createElement("p");
      confirmed.textContent = `Total confirmado en el servidor: ${money(queue.cart.total)} · versión ${queue.cart.version}. Revisa las cantidades confirmadas antes de aplicar pendientes.`;
      status.append(confirmed);
    }
    if (queue.error) {
      const button = (text, action) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = text;
        b.onclick = action;
        b.disabled = queue.busy;
        status.append(b);
      };
      if (queue.conflict)
        button("Revisar y aplicar pendientes", () => queue.acceptConflict());
      else if (!queue.rejected)
        button("Reintentar sin duplicar", () => queue.retry());
      if (queue.rejected)
        button("Descartar pendientes y recuperar venta", () => queue.discard());
    }
    const visible = groups(queue.visible());
    const keys = new Set(visible.map((x) => x.key));
    container
      .querySelectorAll(":scope > :not([data-optimistic-row])")
      .forEach((x) => x.remove());
    for (const [key, row] of rows)
      if (!keys.has(key)) {
        row.remove();
        rows.delete(key);
      }
    for (const group of visible) {
      let row = rows.get(group.key);
      if (!row) {
        row = document.createElement("article");
        row.className = "cart-line";
        row.dataset.optimisticRow = "true";
        row.innerHTML =
          '<div><strong data-name></strong><small data-state></small></div><strong data-total></strong><div class="quantity-form"><button type="button" data-minus aria-label="Reducir cantidad">−</button><input type="number" min="0.001" step="0.001" aria-label="Cantidad"><button type="button" data-plus aria-label="Aumentar cantidad">+</button></div><div class="line-actions"><button type="button" class="link-danger" data-delete>Eliminar</button><span data-editors></span></div>';
        rows.set(group.key, row);
        container.append(row);
      }
      if (!row.isConnected) container.append(row);
      row.querySelector("[data-name]").textContent = group.name;
      row.querySelector("[data-total]").textContent = money(group.total);
      const confirmedQuantity = (queue.cart.lines || [])
        .filter((x) =>
          group.lines.some((line) => String(line.id) === String(x.id)),
        )
        .reduce((sum, x) => sum + Number(x.quantity), 0);
      row.querySelector("[data-state]").textContent = queue.ops.length
        ? `Provisional · confirmado: ${confirmedQuantity}`
        : "Confirmado";
      const input = row.querySelector("input");
      if (
        document.activeElement !== input &&
        input.getAttribute("aria-invalid") !== "true"
      )
        input.value = String(Number(group.quantity.toFixed(3)));
      input.oninput = () => {
        const value = Number(input.value);
        const valid =
          Number.isFinite(value) &&
          value > 0 &&
          Math.abs(Math.round(value * 1000) - value * 1000) < 1e-7;
        input.setCustomValidity(
          valid
            ? ""
            : "Introduce una cantidad positiva con hasta tres decimales.",
        );
        input.setAttribute("aria-invalid", String(!valid));
        if (valid) changeGroup(group, value);
      };
      input.onchange = () => {
        input.oninput();
        if (!input.checkValidity()) input.reportValidity();
      };
      const step = (amount) => {
        input.setCustomValidity("");
        input.setAttribute("aria-invalid", "false");
        input.value = String(group.quantity);
        changeGroup(group, Number((group.quantity + amount).toFixed(3)));
      };
      row.querySelector("[data-minus]").onclick = () => step(-1);
      row.querySelector("[data-plus]").onclick = () => step(1);
      row.querySelector("[data-delete]").onclick = () =>
        group.lines.forEach((line) =>
          queue.enqueue({ kind: "delete", line: line.id }),
        );
      row
        .querySelectorAll("button,input")
        .forEach(
          (x) =>
            (x.disabled = Boolean(
              queue.frozen || queue.rejected || queue.cart.status !== "open",
            )),
        );
      // Keep the existing manual price/discount editors for confirmed source lines.
      const editors = row.querySelector("[data-editors]");
      const signature =
        group.lines.map((line) => line.id).join(",") +
        Boolean(queue.ops.length);
      if (editors.dataset.signature === signature) continue;
      editors.dataset.signature = signature;
      editors.replaceChildren();
      let editorTarget = editors;
      if (group.lines.length > 1 && !queue.ops.length) {
        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = `Precios y descuentos por línea (${group.lines.length})`;
        details.append(summary);
        editors.append(details);
        editorTarget = details;
      }
      if (!queue.ops.length)
        for (const [index, line] of group.lines.entries()) {
          for (const mode of ["price", "discount"]) {
            if (root.dataset[mode] !== "true") continue;
            const a = document.createElement("a");
            a.textContent =
              (mode === "price" ? "Editar precio" : "Descuento") +
              (group.lines.length > 1 ? ` · línea ${index + 1}` : "");
            a.href = location.pathname + `lines/${line.id}/edit/?mode=${mode}`;
            a.setAttribute("hx-get", a.href);
            a.setAttribute("hx-target", "#line-editor-panel");
            a.setAttribute("hx-swap", "innerHTML");
            a.dataset.nxModalTrigger = "line-editor-dialog";
            editorTarget.append(a);
            window.htmx?.process(a);
          }
        }
    }
    document.querySelectorAll(".product-card").forEach((button) => {
      button.disabled = Boolean(
        queue.frozen ||
          queue.rejected ||
          queue.cart.status !== "open" ||
          !Number.isFinite(Number(button.form.dataset.price)),
      );
    });
    document
      .querySelectorAll(
        "#workspace-header input:not([type=hidden]), #workspace-header select, #workspace-header button",
      )
      .forEach((control) => {
        control.disabled = Boolean(queue.frozen);
      });
    const total = visible.reduce((sum, x) => sum + x.total, 0);
    document
      .querySelectorAll("strong[data-cart-total],.grand-total dd")
      .forEach(
        (x) => (x.textContent = money(total) + (queue.ops.length ? " *" : "")),
      );
    document
      .querySelectorAll("[data-cart-count]")
      .forEach(
        (x) =>
          (x.textContent = String(
            Number(visible.reduce((sum, x) => sum + x.quantity, 0).toFixed(3)),
          )),
      );
    const count = document.querySelector(".cart-heading > span");
    if (count)
      count.textContent = `${Number(visible.reduce((sum, x) => sum + x.quantity, 0).toFixed(3))} productos`;
    let checkout = document.querySelector(".cart-actions .checkout-open");
    if (checkout?.tagName === "BUTTON" && visible.length) {
      const anchor = document.createElement("a");
      anchor.className = checkout.className;
      anchor.href = location.pathname + "checkout/";
      anchor.dataset.checkoutOpen = "";
      checkout.replaceWith(anchor);
      checkout = anchor;
    }
    if (checkout) {
      checkout.textContent = `COBRAR · ${money(total)}`;
      checkout.disabled = !visible.length;
    }
    // Authoritative breakdown is refreshed only after the queue settles.
    if (!queue.ops.length) {
      for (const [label, value] of [
        ["Subtotal", queue.cart.subtotal],
        ["Impuestos", queue.cart.tax],
        ["Descuento", queue.cart.discount],
      ]) {
        document.querySelectorAll(".cart-totals > div").forEach((x) => {
          if (x.querySelector("dt")?.textContent === label)
            x.querySelector("dd").textContent = money(value);
        });
      }
    }
  }
  try {
    queue = new CartQueue({
      storage: sessionStorage,
      prefix: `nx-cart:${root.dataset.user}:${root.dataset.business}:${root.dataset.store}:${root.dataset.sale}:`,
      read,
      changed: render,
      send: async (op) => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 15000);
        try {
          const r = await fetch(endpoint, {
            method: "POST",
            credentials: "same-origin",
            signal: controller.signal,
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": csrf(),
            },
            body: JSON.stringify(op),
          });
          const body = await r.json();
          return { status: r.status, body };
        } finally {
          clearTimeout(timeout);
        }
      },
    });
    queue.cart = {
      sale_id: Number(root.dataset.sale),
      business_id: Number(root.dataset.business),
      store_id: Number(root.dataset.store),
      version: Number(root.dataset.cartVersion),
      status: root.dataset.cartStatus,
      total: root.dataset.cartTotal,
      subtotal: root.dataset.cartSubtotal,
      tax: root.dataset.cartTax,
      discount: root.dataset.cartDiscount,
      lines: [...document.querySelectorAll(".cart-line[data-line]")].map(
        (row) => ({
          id: Number(row.dataset.line),
          product: Number(row.dataset.product),
          name: row.dataset.name,
          group: row.dataset.group,
          quantity: row.dataset.quantity,
          price: row.dataset.price,
          total: row.dataset.total,
        }),
      ),
    };
    queue.acknowledged = new Set(
      queue.ops.filter((op) => op.version !== undefined).map((op) => op.key),
    );
    window.tpvCart = queue;
    render();
    const channel =
      typeof BroadcastChannel !== "undefined"
        ? new BroadcastChannel(queue.prefix)
        : null;
    if (channel) {
      channel.onmessage = () => {
        if (!queue.busy && !queue.ops.length) queue.refresh().catch(() => {});
      };
      const originalSend = queue.send;
      queue.send = async (op) => {
        const result = await originalSend(op);
        if (result.status === 200) channel.postMessage("changed");
        return result;
      };
    }
    window.addEventListener("focus", () => {
      if (!queue.busy && !queue.ops.length) queue.refresh().catch(() => {});
    });
  } catch (_) {
    return;
  } // Storage unavailable: retain the original progressive forms.
  // Capture before HTMX and the legacy delegated cart handlers.
  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (form.closest("#sale-cart") && !form.matches(".product-grid form")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        const line = Number(form.closest("[data-line]")?.dataset.line);
        if (line)
          queue.enqueue(
            form.querySelector('[name="quantity"]')
              ? {
                  kind: "quantity",
                  line,
                  quantity: form.querySelector('[name="quantity"]').value,
                }
              : { kind: "delete", line },
          );
        return;
      }
      if (!form.matches(".product-grid form")) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const product = Number(form.querySelector('[name="product"]').value);
      const existing = queue
        .visible()
        .find((x) => Number(x.product) === product);
      queue.enqueue({
        kind: "add",
        product,
        quantity: "1.000",
        name: form.dataset.name,
        price: form.dataset.price,
        estimate: form.dataset.price,
        group: existing?.group || "product:" + product,
      });
    },
    true,
  );
  document.addEventListener(
    "click",
    (event) => {
      const checkout = event.target.closest("[data-checkout-open]");
      if (!checkout) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (checkoutRequested || !queue.visible().length) return;
      const invalid = document.querySelector(
        '.cart-lines input[aria-invalid="true"]',
      );
      if (invalid) {
        invalid.focus();
        invalid.reportValidity();
        return;
      }
      checkoutRequested = true;
      queue.frozen = true;
      render();
      const dialog = document.querySelector("#checkout-dialog"),
        panel = document.querySelector("#checkout-panel");
      panel.replaceChildren(
        document
          .querySelector("#checkout-loading-template")
          .content.cloneNode(true),
      );
      if (!dialog.open) dialog.showModal();
      const provisionalTotal = queue
        .visible()
        .reduce((sum, line) => sum + Number(line.total), 0)
        .toFixed(2);
      queue
        .flush()
        .then(() =>
          window.htmx.ajax("GET", checkout.href, {
            target: panel,
            swap: "innerHTML",
          }),
        )
        .then(() => {
          if (provisionalTotal !== Number(queue.cart.total).toFixed(2)) {
            const note = document.createElement("p");
            note.className = "recovery-note";
            note.textContent = `Total definitivo: ${money(queue.cart.total)}. El provisional era ${money(provisionalTotal)}. Revisa el total antes de confirmar.`;
            panel.prepend(note);
          }
        })
        .catch((error) => {
          panel.replaceChildren();
          const p = document.createElement("p");
          p.textContent =
            error.message +
            " Cierra esta ventana para resolverlo en el ticket.";
          panel.append(p);
        })
        .finally(() => {
          checkoutRequested = false;
        });
    },
    true,
  );
  document.querySelector("#checkout-dialog").addEventListener("close", () => {
    queue.frozen = false;
    queue.refresh().catch(() => {});
  });
  document.addEventListener("htmx:beforeSwap", (event) => {
    if (
      event.detail.xhr?.status === 200 &&
      event.detail.requestConfig?.elt?.closest?.(".line-editor")
    ) {
      // Optimistic rows group source lines; legacy OOB fragments target their
      // individual IDs. Reconcile via JSON instead of inserting nested rows.
      event.detail.shouldSwap = false;
    }
  });
  document.addEventListener("htmx:afterRequest", (event) => {
    if (
      event.detail.xhr?.status === 200 &&
      event.detail.elt?.closest?.(".line-editor")
    )
      queue.refresh().catch((error) => {
        queue.error = error.message;
        render();
      });
  });
  document.addEventListener("htmx:afterSettle", () => {
    if (!queue.busy && !queue.ops.length) queue.refresh().catch(() => {});
  });
  window.addEventListener("storage", (event) => {
    if (event.key?.startsWith(queue.prefix) && !queue.busy && !queue.ops.length)
      queue.refresh().catch(() => {});
  });
  queue
    .refresh()
    .then(() => queue.pump())
    .catch((error) => {
      queue.error = error.message;
      render();
    });
})();

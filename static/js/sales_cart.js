/* Sales optimistic cart: durable intents, one mutation in flight, explicit conflicts. */
(() => {
  "use strict";
  class CartQueue {
    constructor({ storage, prefix, send, read, changed, expectedUser = null }) {
      Object.assign(this, { storage, prefix, send, read, changed, expectedUser });
      this.protocolReady = expectedUser === null;
      this.ops = [];
      this.cart = null;
      this.busy = false;
      this.headerPending = 0;
      this.ownRevisions = new Map();
      this.waiters = new Set();
      this.headerError = "";
      this.readTimeout = 15000;
      this.headerTimeout = 15000;
      this.flushTimeout = 20000;
      this.flight = null;
      this.error = "";
      this.conflict = false;
      this.rejected = false;
      this.acknowledged = new Set();
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i);
        if (key.startsWith(prefix + "op:"))
          this.ops.push(JSON.parse(storage.getItem(key)));
      }
      const flight = storage.getItem(prefix + "flight");
      if (flight) {
        this.flight = JSON.parse(flight);
        if (!Number.isSafeInteger(this.flight.version) || this.flight.version < 0 ||
            !Array.isArray(this.flight.ops) || !this.flight.ops.length || this.flight.ops.length > 50)
          throw new Error("Diario de petición no válido");
        for (const op of this.flight.ops) {
          this.ops = this.ops.filter((pending) => pending.key !== op.key);
          this.ops.push(op);
        }
      }
      for (const op of this.ops) {
        if (!op || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(op.key) ||
            !["add", "quantity", "delete"].includes(op.kind) ||
            !Number.isSafeInteger(op.order) || !Number.isSafeInteger(op.baseVersion) ||
            (op.version !== undefined && !Number.isSafeInteger(op.version)))
          throw new Error("Diario local dañado; no se reenviará automáticamente.");
      }
      if (new Set(this.ops.map(op => op.key)).size !== this.ops.length)
        throw new Error("Identidades locales duplicadas.");
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
      for (const wake of [...this.waiters]) wake();
      this.changed?.(this);
    }
    async bounded(work, milliseconds, signal) {
      if (signal?.aborted) throw new Error("Sincronización cancelada. Las operaciones conservan su identidad.");
      return new Promise((resolve, reject) => {
        const finish = (callback, value) => {
          clearTimeout(timer);
          signal?.removeEventListener("abort", abort);
          callback(value);
        };
        const abort = () => finish(reject, new Error("Sincronización cancelada. No se supone rollback."));
        const timer = setTimeout(() => finish(reject, new Error(
          "La sincronización supera el tiempo de espera. El resultado puede ser desconocido; reintenta sin duplicar."
        )), milliseconds);
        signal?.addEventListener("abort", abort, { once: true });
        Promise.resolve(work).then(value => finish(resolve, value), error => finish(reject, error));
      });
    }
    async waitIdle(signal, deadline) {
      while (this.busy || this.headerPending) {
        const left = deadline - performance.now();
        if (left <= 0) throw new Error("La sincronización sigue pendiente. No se puede cobrar sin verificarla.");
        let wake;
        const changed = new Promise(resolve => { wake = resolve; this.waiters.add(wake); });
        try { await this.bounded(changed, left, signal); }
        finally { this.waiters.delete(wake); }
      }
    }
    async refresh() {
      const result = await this.read();
      const cart = result.cart;
      if (this.expectedUser !== null) {
        const sameScope = this.cart && ["sale_id", "business_id", "store_id"]
          .every(field => cart?.[field] === this.cart[field]);
        if (result.protocol !== 2 || result.user_id !== this.expectedUser || !sameScope) {
          this.protocolReady = false;
          this.error = "Ha cambiado la sesión o la versión del servidor. Recarga la página y revisa la venta; no se enviarán los pendientes automáticamente.";
          this.notify();
          throw new Error(this.error);
        }
        this.protocolReady = true;
      }

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
        previous.version === undefined &&
        !this.flight?.ops.some(op => op.key === previous.key)
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
    advanceOwnVersion(version) {
      while (this.ownRevisions.has(version))
        version = this.ownRevisions.get(version);
      return version;
    }
    recordOwnRevision(previous, current) {
      if (current > previous) this.ownRevisions.set(previous, current);
      this.cart.version = this.advanceOwnVersion(this.cart.version);
      for (const op of this.ops) {
        if (op.version === undefined) {
          op.baseVersion = this.advanceOwnVersion(op.baseVersion);
          this.save(op);
        }
      }
      this.notify();
    }
    async pump() {
      if (
        !this.protocolReady ||
        this.headerPending ||
        this.headerError ||
        this.busy ||
        this.error ||
        !this.cart ||
        !this.ops.length
      ) return;
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
        let sending = this.flight?.ops;
        if (!sending) {
          sending = op.version === undefined
            ? this.ops.slice(0, 50).filter((pending, index, all) =>
                pending.version === undefined && pending.baseVersion === op.baseVersion &&
                all.slice(0, index).every(before => before.version === undefined))
            : [op];
          if (sending.length > 1) {
            sending = sending.map(pending => ({ ...pending, version: this.cart.version }));
            const flight = { version: this.cart.version, ops: sending };
            // One atomic storage write BEFORE any network mutation; survives partial cleanup.
            this.storage.setItem(this.prefix + "flight", JSON.stringify(flight));
            this.flight = flight;
            for (const pending of sending) {
              this.save(pending);
              Object.assign(this.ops.find(x => x.key === pending.key), pending);
            }
          } else if (op.version === undefined) {
            op.version = this.cart.version;
            this.save(op);
          }
        }
        const wire = pending => {
          const line = this.resolve(pending.line);
          if (pending.kind === "add") return { ...pending };
          if (line) return { ...pending, line };
          if (String(pending.line).startsWith("tmp:")) {
            const { line: _, ...rest } = pending;
            return { ...rest, line_ref: pending.line.slice(4) };
          }
          throw new Error("Falta la confirmación de una línea pendiente.");
        };
        const result = await this.send(this.flight
          ? { version: this.flight.version, operations: sending.map(wire) }
          : wire(op));
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
          const receipts = this.flight ? result.body.results : [result.body];
          if (!Array.isArray(receipts) || receipts.length !== sending.length ||
              receipts.some((receipt, index) => receipt.key !== sending[index].key))
            throw new Error("Respuesta incompleta. Reintenta las mismas identidades.");
          for (const receipt of receipts) {
            if (receipt.line)
              this.storage.setItem(this.prefix + "map:" + receipt.key, JSON.stringify(receipt.line));
          }
          for (const pending of sending)
            this.storage.removeItem(this.prefix + "op:" + pending.key);
          this.storage.removeItem(this.prefix + "flight");
          this.flight = null;
          const accepted = new Set(sending.map(pending => pending.key));
          this.ops = this.ops.filter(pending => !accepted.has(pending.key));
          if (result.body.cart.version >= this.cart.version)
            this.cart = result.body.cart;
          this.cart.version = this.advanceOwnVersion(this.cart.version);
          const externalChange =
            this.cart.version !== this.advanceOwnVersion(result.body.accepted_version);
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
      try {
        if (!this.protocolReady) await this.refresh();
        await this.pump();
      } catch (error) { this.error = error.message; this.notify(); }
    }
    async acceptConflict() {
      if (!this.conflict || this.busy) return;
      // A definitive version conflict has no receipt. The user may explicitly
      // resubmit the same intent against the freshly reviewed version.
      this.storage.removeItem(this.prefix + "flight");
      this.flight = null;
      for (const pending of this.ops) {
        delete pending.version;
        pending.baseVersion = this.cart.version;
        this.save(pending);
      }
      this.error = "";
      this.conflict = this.rejected = false;
      await this.pump();
    }
    async discard() {
      if (this.busy || !this.rejected) return;
      for (const op of this.ops)
        this.storage.removeItem(this.prefix + "op:" + op.key);
      this.storage.removeItem(this.prefix + "flight");
      this.flight = null;
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
    async flush({ signal } = {}) {
      const deadline = performance.now() + this.flushTimeout;
      // The initial protocol read must validate this session before queued
      // mutations can drain. Reuse that read rather than racing a second one.
      if (!this.protocolReady)
        await this.bounded(
          this.initialization || this.refresh(),
          Math.max(1, deadline - performance.now()),
          signal,
        );
      await this.waitIdle(signal, deadline);
      if (this.headerError) throw new Error(this.headerError);
      // Start draining without letting its Promise hide an unbounded wait.
      this.pump();
      await this.waitIdle(signal, deadline);
      if (this.error || this.ops.length)
        throw new Error(this.error || "Hay cambios pendientes.");
      await this.bounded(this.refresh(), Math.max(1, deadline - performance.now()), signal);
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
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), queue?.readTimeout || 15000);
    try {
      const r = await fetch(
        endpoint + (pending ? "?pending=" + encodeURIComponent(pending) : ""),
        { credentials: "same-origin", cache: "no-store", signal: controller.signal },
      );
      if (!r.ok) throw new Error("No se puede recuperar esta venta. Comprueba sesión y permisos.");
      return await r.json();
    } catch (error) {
      if (error.name === "AbortError")
        throw new Error("No se recibió el estado de la venta a tiempo. Reintenta la sincronización.");
      if (error instanceof TypeError) throw new Error("No se puede conectar para verificar la venta. Conserva los pendientes.");
      throw error;
    } finally { clearTimeout(timer); }
  };

  const money = (value) =>
    new Intl.NumberFormat("es-ES", {
      style: "currency",
      currency: "EUR",
    }).format(value);
  let queue,
    checkoutRequested = false,
    checkoutTrigger = null,
    checkoutAttempt = null;
  const checkoutReads = new WeakMap();
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
      queue.headerError || queue.error ||
      (!navigator.onLine ? "Sin conexión · no se enviarán cambios" :
        queue.headerPending || queue.busy ? "Sincronizando · espera la confirmación antes de cerrar" :
        queue.ops.length ? `${queue.ops.length} cambios pendientes · importes provisionales` :
        "Cambios guardados en el servidor");
    status.dataset.state = queue.headerError ? "intervention" : queue.conflict ? "conflict" :
      !navigator.onLine ? "offline" : queue.error ? "intervention" :
      queue.busy || queue.headerPending ? "syncing" : queue.ops.length ? "pending" : "saved";
    status.append(message);
    if (queue.headerError) {
      const reload = document.createElement("button");
      reload.type = "button";
      reload.textContent = "Recargar y revisar cabecera";
      reload.onclick = () => location.reload();
      status.append(reload);
    }
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
          '<div><strong data-name></strong><small data-state></small></div><strong data-total></strong><div class="quantity-form"><button type="button" data-minus aria-label="Reducir cantidad">−</button><input name="quantity" type="number" min="0.001" step="0.001" aria-label="Cantidad"><button type="button" data-plus aria-label="Aumentar cantidad">+</button></div><div class="line-actions"><button type="button" class="link-danger" data-delete>Eliminar</button><span data-editors></span></div>';
        rows.set(group.key, row);
        container.append(row);
      }
      if (!row.isConnected) container.append(row);
      row.querySelector("[data-name]").textContent = group.name;
      row
        .querySelector("[data-minus]")
        .setAttribute("aria-label", `Reducir ${group.name}`);
      row
        .querySelector("[data-plus]")
        .setAttribute("aria-label", `Aumentar ${group.name}`);
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
      expectedUser: Number(root.dataset.user),
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
              "X-Sales-Cart-User": root.dataset.user,
              "X-Sales-Cart-Protocol": "2",
            },
            body: JSON.stringify(op),
          });
          if (r.headers.get("X-Sales-Cart-Protocol") !== "2")
            throw new Error("El servidor no confirma un protocolo compatible. Conserva los pendientes y recarga para revisar.");
          const body = await r.json();
          return { status: r.status, body };
        } catch (error) {
          if (error.name === "AbortError")
            throw new Error("Sin confirmación en 15 segundos. El servidor puede haber guardado los cambios; reintenta sin duplicar.");
          if (error instanceof TypeError) throw new Error("Sin conexión o respuesta no válida. Conserva los pendientes y reintenta sin duplicar.");
          throw error;
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
    // Fail closed: an unreadable journal may contain a committed unknown operation.
    const warning = document.createElement("p");
    warning.setAttribute("role", "alert");
    warning.textContent = "No se puede verificar el diario local del carrito. No borres el almacenamiento: podría haber cambios de resultado desconocido. Revisa la venta desde otra pestaña o solicita asistencia antes de editar o cobrar.";
    root.prepend(warning);
    root.querySelectorAll(".product-card, .cart-lines input, .cart-lines button, .checkout-open").forEach(control => {
      control.disabled = true;
      control.setAttribute("aria-disabled", "true");
    });
    for (const type of ["submit", "click"]) root.addEventListener(type, event => {
      if (event.target.closest(".product-grid, #sale-cart, [data-checkout-open]")) {
        event.preventDefault(); event.stopImmediatePropagation();
      }
    }, true);
    return;
  }
  window.addEventListener("beforeunload", event => {
    if (queue.ops.length || queue.busy || queue.headerPending || queue.headerError) {
      event.preventDefault(); event.returnValue = "";
    }
  });
  window.addEventListener("offline", render);
  window.addEventListener("online", () => {
    render(); // Recovery requires an explicit retry; never silently rebase.
  });
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
      const attempt = new AbortController();
      checkoutAttempt = attempt;
      checkoutTrigger = checkout;
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
        .flush({ signal: attempt.signal })
        .then(() => {
          if (attempt.signal.aborted) throw new Error("Apertura cancelada.");
          return queue.bounded(window.htmx.ajax("GET", checkout.href, {
            target: panel, swap: "innerHTML",
            headers: { "X-Sales-Checkout-Read": "1" },
          }), 15000, attempt.signal);
        })
        .then(() => {
          if (checkoutAttempt !== attempt || attempt.signal.aborted) return;
          if (provisionalTotal !== Number(queue.cart.total).toFixed(2)) {
            const note = document.createElement("p");
            note.className = "recovery-note";
            note.textContent = `Total definitivo: ${money(queue.cart.total)}. El provisional era ${money(provisionalTotal)}. Revisa el total antes de confirmar.`;
            panel.prepend(note);
          }
        })
        .catch((error) => {
          if (checkoutAttempt !== attempt || !dialog.open) return;
          attempt.abort();
          panel.replaceChildren();
          const p = document.createElement("p");
          p.textContent =
            error.message +
            " Cierra esta ventana para resolverlo en el ticket.";
          panel.append(p);
          const retry = document.createElement("button");
          retry.type = "button";
          retry.textContent = "Volver al ticket";
          retry.onclick = () => dialog.close();
          panel.append(retry);
        })
        .finally(() => {
          if (checkoutAttempt === attempt) checkoutRequested = false;
        });
    },
    true,
  );
  document.querySelector("#checkout-dialog").addEventListener("close", () => {
    checkoutAttempt?.abort();
    checkoutAttempt = null;
    checkoutRequested = false;
    queue.frozen = false;
    render();
    if (checkoutTrigger?.isConnected)
      checkoutTrigger.focus({ preventScroll: true });
    queue.refresh().catch(() => {});
  });
  document.addEventListener("htmx:beforeSwap", (event) => {
    if (checkoutReads.get(event.detail.xhr)?.signal.aborted) {
      event.detail.shouldSwap = false;
      event.detail.isError = false;
      return;
    }
    if (
      event.detail.xhr?.status === 200 &&
      event.detail.requestConfig?.elt?.closest?.(".line-editor")
    ) {
      // Optimistic rows group source lines; legacy OOB fragments target their
      // individual IDs. Reconcile via JSON instead of inserting nested rows.
      event.detail.shouldSwap = false;
    }
  });
  const headerRequests = new Map();
  const uncertainHeaders = new Set();
  const finishHeader = (xhr, timedOut = false) => {
    const request = headerRequests.get(xhr);
    if (!request) return;
    if (!request.finished) {
      request.finished = true;
      queue.headerPending--;
      clearTimeout(request.timer);
    }
    const previous = xhr.getResponseHeader("X-Sales-Cart-Previous-Version");
    const current = xhr.getResponseHeader("X-Sales-Cart-Version");
    if (!timedOut && xhr.status === 200 && previous !== null && current !== null) {
      uncertainHeaders.delete(xhr);
      queue.recordOwnRevision(Number(previous), Number(current));
      headerRequests.delete(xhr);
    } else {
      uncertainHeaders.add(xhr);
    }
    queue.headerError = uncertainHeaders.size
      ? "No se ha verificado el guardado de cliente/documento. Recarga y revisa la cabecera antes de cobrar."
      : "";
    queue.notify();
    if (!queue.headerPending && !queue.headerError) queue.pump();
  };
  document.addEventListener("htmx:beforeRequest", (event) => {
    const { elt, xhr, requestConfig } = event.detail;
    if (requestConfig?.headers?.["X-Sales-Checkout-Read"] && checkoutAttempt) {
      const attempt = checkoutAttempt;
      checkoutReads.set(xhr, attempt);
      xhr.timeout = 15000;
      attempt.signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }
    if (requestConfig?.verb?.toLowerCase() === "post" &&
        (elt?.matches?.("[data-header-autosave]") || elt?.closest?.("#quick-customer-panel"))) {
      const request = { finished: false };
      headerRequests.set(xhr, request);
      queue.headerPending++;
      request.timer = setTimeout(() => finishHeader(xhr, true), queue.headerTimeout);
      queue.notify();
    }
  });
  document.addEventListener("htmx:afterRequest", (event) => {
    finishHeader(event.detail.xhr);

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
  queue.initialization = queue.refresh();
  queue.initialization
    .then(() => queue.pump())
    .catch((error) => {
      queue.error = error.message;
      render();
    });
})();

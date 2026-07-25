# Customers

Gestiona clientes del negocio completo, no de una tienda concreta.

## Modelos

- `Customer`: ficha identificativa, fiscal y de contacto.
- `CustomerAccount`: cuenta corriente única del cliente.
- `CustomerAccountEntry`: histórico inmutable de cambios de saldo.

## Cuenta corriente

`balance` positivo representa deuda del cliente, cero representa cuenta saldada y negativo saldo a favor. Los cargos son positivos; pagos y reembolsos negativos; ajustes positivos o negativos, nunca cero. Los pagos pueden superar la deuda y dejan el sobrante como saldo a favor.

`Customer` y `CustomerAccount` se separan para impedir que datos de ficha y saldo se mezclen. El balance nunca se modifica directamente desde forms, views o admin: todo cambio pasa por `CustomerAccountService`, con transacción, bloqueo `select_for_update`, cálculo de saldo posterior y creación de `CustomerAccountEntry`.

## Servicios

- `CustomerService`: crear, actualizar, desactivar y reactivar clientes.
- `CustomerAccountService`: configurar límite/bloqueo y registrar cargos, pagos, reembolsos y ajustes.

## Permisos y aislamiento

Las vistas de listado, detalle y creación requieren usuario autenticado con negocio. Cashier puede crear ficha básica. Edición, desactivación, reactivación y configuración de cuenta requieren manager u owner. Todas las lecturas y escrituras filtran por `business`.

`Sale` y `Payment` se enlazarán en migraciones futuras cuando existan sus modelos reales. Billing validará y congelará datos fiscales al emitir.

## Tests

```bash
uv run python manage.py test apps.customers
uv run python manage.py test
```

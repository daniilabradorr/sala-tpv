# Billing contract

Billing is the immutable fiscal snapshot layer. HTTP input belongs to forms and
views, reads to selectors, and issue/rectification rules to services.

## Source of truth fiscal

The only resolution order is an active product-specific `Product.tax`, then the
active `Tax.is_default` belonging to the same Business, then a controlled error.
`BusinessProfile.default_tax_rate` remains in the database only as a deprecated
compatibility field; it is not a fiscal or commercial calculation source.

The snapshot chain is `Catalog Tax -> SaleLine -> BillingDocumentLine ->
BillingTaxBreakdown`. Emission must never reconstruct history from the current
Product or Tax.

## Supported issue flows

The MVP issues F1, F2, and F3 through Billing services. The current authorization
contract remains active user, same Business, and permission to sell in the Store.

## Automatic return rectifications

`SaleReturn -> Billing service` deterministically produces:

* F1 return -> R1, rectification method I (differences).
* F2 return -> R5, rectification method I (differences).

The service, not an HTTP form, selects the type. Return rectifications link to the
original through `RECTIFIES` and preserve `sale_return` and `source_sale_line`
provenance.

## Recognized but non-automatic in MVP

R2, R3, and R4 remain valid document type choices, but no SaleReturn branch
generates them. Their legal inputs and manual owner/manager workflow require a
separate explicit specification.

## Cancellation

A commercial return is not fiscal cancellation. Returns preserve the Sale,
Payment, SaleReturn, original BillingDocument, and original number and produce an
R1/R5 where supported.

Billing has no CANCEL document type and cancellation must not consume a Billing
series. The future contract is `BillingDocument -> integrations/verifacti ->
VerifactiSubmission(submission_type=cancel)`. The future sensitive use case may be
named conceptually `cancel_fiscal_registration(...)`; neither that model nor any
external HTTP request is implemented here.

## Historical rules

Issued documents are never edited or deleted. Issuer, recipient, line, tax, and
total values are snapshots. `RECTIFIES` identifies the corrected document and
`SUBSTITUTES` identifies F3 substitution. `source_sale_line` and `sale_return`
retain provenance. Idempotency fingerprints protect intent, retries return the
same result, numbering is assigned atomically under series locks, and failed
transactions do not consume numbers.

## Dates

`issued_at` is the real issuance instant. F1/F2/F3 operation dates follow their
existing sale issue contract. Automatic R1/R5 `operation_date` is copied from the
historical original fiscal document, never from `SaleReturn.completed_at` and
never from client input.

For the companion F3 in an F2 -> F3 -> return -> R5 -> F3 flow, the existing
operation-date behavior is intentionally unchanged. Its independent fiscal
semantics still require an explicit product decision.

## Future external payload boundary

Billing currently snapshots document identity/type/series/number/dates, issuer
and recipient identity/address, monetary totals, detailed line provenance and tax
treatment, grouped tax breakdowns, and `RECTIFIES`/`SUBSTITUTES` relations. These
are the internal sources for future F1/F2/F3/R1/R5 serialization.

No authoritative external Verifacti schema exists in this module. Before a DTO or
HTTP adapter is added, the integration specification must define external field
names, required/conditional fields per document type, identifiers and timestamps
for submissions, cancellation reason/evidence, chaining/hash/signature data,
software identity, retry/error states, and acknowledgement storage. Billing must
not invent those fields.

## Onboarding and series

Billing requires explicit usable `BillingSeries`, but current onboarding does not
define their creation contract. No series are auto-created here. Product decisions
are required for global-versus-Store scope, name, prefix, initial document types,
year lifecycle, and optional cash-register scope.

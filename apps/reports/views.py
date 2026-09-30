import csv
from datetime import date

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View

from apps.core.shell import resolve_active_store
from apps.reports import selectors
from apps.reports.forms import ReportFilterForm
from apps.reports.presentation import chart_rows
from apps.users.mixins import CanViewReportsMixin


TABS = (
    ("general", "General"),
    ("sales", "Ventas"),
    ("payments", "Pagos"),
    ("cash", "Caja"),
    ("tax", "Fiscal"),
    ("inventory", "Inventario"),
    ("purchases", "Compras"),
)
TAB_KEYS = {key for key, _label in TABS}


class ReportsContextMixin(CanViewReportsMixin):
    def get_business(self):
        business = getattr(self.request.user, "business", None)
        if business is None:
            raise PermissionDenied("Informes requiere un contexto de negocio.")
        return business

    def get_filter_form(self):
        business = self.get_business()
        _stores, active_store = resolve_active_store(
            self.request, user=self.request.user
        )
        data = self.request.GET.copy()
        data.setdefault("period", "30d")
        if not data.get("store"):
            data["store"] = str(active_store.pk) if active_store else "all"
        return ReportFilterForm(
            data, business=business, user=self.request.user, active_store=active_store
        )


class ReportsOverviewView(ReportsContextMixin, View):
    http_method_names = ["get"]

    def get(self, request):
        tab = request.GET.get("tab", "general")
        if tab not in TAB_KEYS:
            tab = "general"
        form = self.get_filter_form()
        if not form.is_valid():
            if request.headers.get("HX-Request") == "true":
                response = render(
                    request,
                    "reports/partials/_filters.html",
                    {"form": form, "tab": tab},
                    status=422,
                )
                response["HX-Retarget"] = "#reports-filters"
                response["HX-Reswap"] = "outerHTML"
                return response
            return render(
                request,
                "reports/report.html",
                {"form": form, "tab": tab, "tabs": TABS},
                status=400,
            )

        context = self._context(form=form, tab=tab)
        template = (
            "reports/partials/_workspace.html"
            if request.headers.get("HX-Request") == "true"
            else "reports/report.html"
        )
        return render(request, template, context)

    def _context(self, *, form, tab):
        cleaned = form.cleaned_data
        business = self.get_business()
        store = cleaned["selected_store"]
        period = cleaned["report_period"]
        args = {"business": business, "period": period, "store": store}
        data = {}
        if tab == "general":
            data["dashboard"] = selectors.dashboard_summary(**args)
            data["dashboard"]["sales_timeseries"] = chart_rows(
                data["dashboard"]["sales_timeseries"], "net_sales"
            )
        elif tab == "sales":
            data.update(
                sales=selectors.sales_summary(**args),
                sales_timeseries=chart_rows(
                    selectors.sales_timeseries(**args), "gross_sales", "returns_amount"
                ),
                sales_products=selectors.sales_by_product(**args),
                sales_categories=selectors.sales_by_category(**args),
                sales_stores=selectors.sales_by_store(**args) if store is None else [],
            )
        elif tab == "payments":
            data.update(
                payments=selectors.payment_summary(**args),
                payment_methods=selectors.payments_by_method(**args),
            )
        elif tab == "cash":
            data.update(
                cash=selectors.cash_summary(**args),
                cash_sessions=selectors.cash_sessions_summary(**args, limit=25),
            )
        elif tab == "tax":
            data.update(
                documents=selectors.billing_documents_summary(**args),
                tax=selectors.tax_summary(**args),
                tax_rates=selectors.tax_by_rate(**args),
            )
        elif tab == "inventory":
            data.update(
                inventory=selectors.inventory_summary(business=business, store=store),
                inventory_movements=selectors.inventory_movements_summary(**args),
            )
        elif tab == "purchases":
            data.update(
                purchases=selectors.purchase_summary(**args),
                purchase_suppliers=selectors.purchases_by_supplier(**args),
                purchase_stores=selectors.purchases_by_store(**args)
                if store is None
                else [],
                purchase_products=selectors.purchases_by_product(**args),
                purchase_receipts=selectors.purchase_receipts_summary(**args),
            )
        query = self.request.GET.copy()
        query["tab"] = tab
        query["period"] = cleaned["period"]
        query["store"] = cleaned["store"]
        if cleaned["period"] == "custom":
            query["date_from"] = cleaned["date_from"].isoformat()
            query["date_to"] = cleaned["date_to"].isoformat()
        else:
            query.pop("date_from", None)
            query.pop("date_to", None)
        tab_urls = []
        for key, label in TABS:
            tab_query = query.copy()
            tab_query["tab"] = key
            tab_query.pop("purchase_view", None)
            tab_urls.append(
                {
                    "key": key,
                    "label": label,
                    "url": f"{reverse('reports:overview')}?{tab_query.urlencode()}",
                }
            )
        export_query = query.copy()
        export_query.pop("tab", None)
        return {
            "form": form,
            "tabs": TABS,
            "tab": tab,
            "report_data": data,
            "date_from": cleaned["date_from"],
            "date_to": cleaned["date_to"],
            "scope_name": store.name if store else "Todas las tiendas",
            "filter_query": query.urlencode(),
            "tab_urls": tab_urls,
            "sales_export_url": f"{reverse('reports:sales_export')}?{export_query.urlencode()}",
            "selected_store": store,
            "purchase_view": self.request.GET.get("purchase_view", "orders")
            if self.request.GET.get("purchase_view") in {"orders", "receipts"}
            else "orders",
        }


class SalesExportView(ReportsContextMixin, View):
    http_method_names = ["get"]

    def get(self, request):
        form = self.get_filter_form()
        if not form.is_valid():
            return HttpResponse(
                "Filtros no válidos",
                status=400,
                content_type="text/plain; charset=utf-8",
            )
        cleaned = form.cleaned_data
        args = {
            "business": self.get_business(),
            "period": cleaned["report_period"],
            "store": cleaned["selected_store"],
        }
        summary = selectors.sales_summary(**args)
        timeseries = selectors.sales_timeseries(**args)
        products = selectors.sales_by_product(**args)
        categories = selectors.sales_by_category(**args)
        stores = (
            selectors.sales_by_store(**args)
            if cleaned["selected_store"] is None
            else []
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="informe-ventas-{date.today().isoformat()}.csv"'
        )
        response.write("\ufeff")
        writer = csv.writer(response, delimiter=";")
        writer.writerow(["Resumen"])
        writer.writerow(["Métrica", "Valor"])
        for key in (
            "gross_sales",
            "returns_amount",
            "net_sales",
            "ticket_count",
            "average_ticket",
            "units_sold",
            "units_returned",
        ):
            writer.writerow([key, summary[key]])
        for title, rows, fields in (
            (
                "Serie temporal",
                timeseries,
                ("day", "gross_sales", "returns_amount", "net_sales", "ticket_count"),
            ),
            (
                "Productos",
                products,
                ("sku", "product_name", "units_sold", "units_returned", "net_sales"),
            ),
            (
                "Categorías",
                categories,
                ("category_name", "units_sold", "units_returned", "net_sales"),
            ),
            (
                "Tiendas",
                stores,
                (
                    "store_name",
                    "gross_sales",
                    "returns_amount",
                    "net_sales",
                    "ticket_count",
                ),
            ),
        ):
            writer.writerow([])
            writer.writerow([title])
            writer.writerow(fields)
            for row in rows:
                writer.writerow([row[field] for field in fields])
        return response

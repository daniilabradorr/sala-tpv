from django.shortcuts import render
from django.views import View

from apps.sales.selectors import get_sales_for_business
from apps.users.mixins import BusinessRequiredMixin


class SaleListView(BusinessRequiredMixin, View):
    template_name = "sales/sale_list.html"

    def get(self, request):
        sales = get_sales_for_business(
            business=request.user.business,
            store=...,
            status=...,
            payment_status=...,
            customer=...,
        )

        context = {
            "sales": sales,
            # filtros y choices
        }

        return render(request, self.template_name, context)

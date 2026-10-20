from django import template

from apps.sales.cart import line_group

register = template.Library()
register.filter("cart_group", line_group)

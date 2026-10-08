"""Quantity filters for human text and HTML number inputs."""

from django import template

from apps.core.quantities import quantity, quantity_input

register = template.Library()
register.filter("quantity", quantity)
register.filter("quantity_input", quantity_input)

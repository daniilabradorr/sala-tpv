"""Presentation helpers for persisted fiscal snapshots."""

from django import template

from apps.core.quantities import quantity

register = template.Library()


register.filter("quantity", quantity)

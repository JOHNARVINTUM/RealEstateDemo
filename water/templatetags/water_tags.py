"""
Custom template tags for water app.
"""
from django import template
import calendar

register = template.Library()


@register.filter
def month_name(month_number):
    """
    Convert month number to month name.
    Usage: {{ month|month_name }}
    """
    try:
        return calendar.month_name[int(month_number)]
    except (ValueError, IndexError):
        return ""


@register.filter
def month_abbr(month_number):
    """
    Convert month number to abbreviated month name.
    Usage: {{ month|month_abbr }}
    """
    try:
        return calendar.month_abbr[int(month_number)]
    except (ValueError, IndexError):
        return ""

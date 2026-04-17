from django import template

register = template.Library()

@register.filter
def add_class(value, css_class):
    """
    Add CSS class to form field widget
    """
    if hasattr(value, 'as_widget'):
        return value.as_widget(attrs={'class': css_class})
    return value

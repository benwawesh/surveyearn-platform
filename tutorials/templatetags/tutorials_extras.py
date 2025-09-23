# tutorials/templatetags/tutorials_extras.py
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def lookup(dictionary, key):
    """
    Template filter to lookup a value in a dictionary
    Usage: {{ dict|lookup:key }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def mul(value, arg):
    """
    Template filter to multiply two values
    Usage: {{ value|mul:2 }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def sub(value, arg):
    """
    Template filter to subtract two values
    Usage: {{ value|sub:2 }}
    """
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def percentage(value, total):
    """
    Calculate percentage
    Usage: {{ correct|percentage:total }}
    """
    try:
        if float(total) == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError):
        return 0


@register.filter
def duration_format(duration):
    """
    Format duration in a human readable way
    Usage: {{ duration|duration_format }}
    """
    if not duration:
        return "N/A"

    total_seconds = int(duration.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


@register.simple_tag
def progress_color(percentage):
    """
    Return appropriate color based on progress percentage
    Usage: {% progress_color 75 %}
    """
    percentage = float(percentage)
    if percentage >= 90:
        return "text-green-600"
    elif percentage >= 70:
        return "text-yellow-600"
    elif percentage >= 50:
        return "text-orange-600"
    else:
        return "text-red-600"


@register.simple_tag
def quiz_status_badge(is_passed, attempts, max_attempts):
    """
    Generate quiz status badge HTML
    Usage: {% quiz_status_badge quiz_passed attempts max_attempts %}
    """
    if is_passed:
        return mark_safe(
            '<span class="bg-green-100 text-green-800 px-2 py-1 rounded-full text-xs font-medium">Passed</span>')
    elif attempts >= max_attempts:
        return mark_safe(
            '<span class="bg-red-100 text-red-800 px-2 py-1 rounded-full text-xs font-medium">Failed</span>')
    elif attempts > 0:
        return mark_safe(
            '<span class="bg-yellow-100 text-yellow-800 px-2 py-1 rounded-full text-xs font-medium">In Progress</span>')
    else:
        return mark_safe(
            '<span class="bg-gray-100 text-gray-800 px-2 py-1 rounded-full text-xs font-medium">Not Started</span>')


@register.inclusion_tag('tutorials/partials/progress_bar.html')
def progress_bar(percentage, show_text=True, height="h-2"):
    """
    Render a progress bar
    Usage: {% progress_bar 75 %}
    """
    return {
        'percentage': percentage,
        'show_text': show_text,
        'height': height,
    }
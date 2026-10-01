"""Calendar-date ordering and section labels for the task view."""

from datetime import date, timedelta

from dateutil.parser import isoparse
import calendar


def serialize_due(value):
    """Return a date-only API timestamp, or None to remove a scheduled date."""
    if value is None or value == '':
        return None
    day = isoparse(value).date() if isinstance(value, str) else value
    return f'{day.year:04d}-{day.month:02d}-{day.day:02d}T00:00:00Z'


def shift_month(day, delta):
    """Move by months, clamping the day for shorter months."""
    month_index = (day.year - 1) * 12 + day.month - 1 + delta
    month_index = max(0, min(9999 * 12 - 1, month_index))
    year, month = divmod(month_index, 12)
    year, month = year + 1, month + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def due_date(task):
    """Read the date as supplied, without shifting date-only deadlines by timezone."""
    value = task.get("due")
    if not value:
        return None
    try:
        return isoparse(value).date()
    except (ValueError, TypeError, OverflowError):
        return None


def sort_tasks(tasks):
    """Stable chronological order, preserving existing order within each day."""
    return sorted(tasks, key=lambda task: due_date(task) or date.max)


def date_section(task, today=None):
    today = today or date.today()
    due = due_date(task)
    if due is None:
        return "No date"
    if due < today:
        return "Overdue"
    if due == today:
        return "Today"
    if due == today + timedelta(days=1):
        return "Tomorrow"
    label = f"{due:%a, %b} {due.day}"
    return label if due.year == today.year else f"{label}, {due.year}"

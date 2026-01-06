"""Date parsing and formatting utilities."""

from datetime import date, datetime
from typing import Optional
from dateutil import parser as date_parser


def parse_date(date_string: str) -> Optional[date]:
    """
    Parse a date string into a date object.
    Handles various formats commonly used in Slack Lists.
    
    Args:
        date_string: Date string in various formats (ISO, US, etc.)
        
    Returns:
        date object or None if parsing fails
    """
    if not date_string:
        return None
    
    try:
        # Use dateutil for flexible parsing
        parsed = date_parser.parse(date_string)
        return parsed.date()
    except (ValueError, TypeError):
        return None


def format_date(d: date, fmt: str = "%b %d") -> str:
    """
    Format a date for display.
    
    Args:
        d: Date object to format
        fmt: strftime format string (default: "Jan 01")
        
    Returns:
        Formatted date string
    """
    return d.strftime(fmt)


def date_range_days(start: date, end: date) -> int:
    """
    Calculate the number of days between two dates (inclusive).
    
    Args:
        start: Start date
        end: End date
        
    Returns:
        Number of days (minimum 1 for same-day tasks)
    """
    delta = (end - start).days
    return max(1, delta + 1)  # Inclusive, minimum 1 day


def get_date_bounds(dates: list[date]) -> tuple[date, date]:
    """
    Get the minimum and maximum dates from a list.
    
    Args:
        dates: List of date objects
        
    Returns:
        Tuple of (min_date, max_date)
    """
    if not dates:
        today = date.today()
        return today, today
    return min(dates), max(dates)


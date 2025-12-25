"""Date validation and parsing utilities for timeline events"""
from typing import Optional, List, Any
from datetime import datetime, date, timedelta
import re
import logging
from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)


def parse_and_normalize_date(date_str: str, reference_date: Optional[datetime] = None) -> str:
    """
    Parse date string in various formats and normalize to YYYY-MM-DD format.
    
    Supports:
    - ISO format: "2023-09-20"
    - Russian format: "20 сентября 2023 г."
    - Russian format: "20.09.2023"
    - Relative dates: "через 5 дней после подписания договора"
    - Date ranges: "20-25 сентября 2023 г." (takes first date)
    
    Args:
        date_str: Date string to parse
        reference_date: Reference date for relative date calculations
        
    Returns:
        Normalized date string in YYYY-MM-DD format
    """
    if not date_str or not isinstance(date_str, str):
        raise ValueError(f"Invalid date string: {date_str}")
    
    date_str = date_str.strip()
    
    # Try to parse relative dates first
    if reference_date and any(keyword in date_str.lower() for keyword in ['через', 'после', 'до', 'до']):
        try:
            parsed_date = compute_relative_date(date_str, reference_date)
            return parsed_date.strftime("%Y-%m-%d")
        except Exception as e:
            logger.warning(f"Could not parse relative date '{date_str}': {e}")
    
    # Try ISO format first (fastest)
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    # Try Russian date format: "20 сентября 2023 г."
    russian_months = {
        'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4,
        'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8,
        'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12
    }
    
    for month_name, month_num in russian_months.items():
        pattern = rf'(\d{{1,2}})\s+{month_name}\s+(\d{{4}})'
        match = re.search(pattern, date_str, re.IGNORECASE)
        if match:
            day = int(match.group(1))
            year = int(match.group(2))
            try:
                parsed = datetime(year, month_num, day)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue
    
    # Try DD.MM.YYYY format
    pattern = r'(\d{1,2})\.(\d{1,2})\.(\d{4})'
    match = re.search(pattern, date_str)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            parsed = datetime(year, month, day)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass
    
    # Try dateutil parser as fallback (handles many formats)
    try:
        parsed = dateutil_parser.parse(date_str, dayfirst=True)
        return parsed.strftime("%Y-%m-%d")
    except Exception as e:
        logger.warning(f"Could not parse date '{date_str}': {e}")
        # Return original string if parsing fails (will be caught by validator)
        return date_str


def compute_relative_date(date_str: str, reference_date: datetime) -> date:
    """
    Compute absolute date from relative date string.
    
    Examples:
    - "через 5 дней после подписания" -> reference_date + 5 days
    - "через 2 недели" -> reference_date + 2 weeks
    - "через 1 месяц" -> reference_date + 1 month
    
    Args:
        date_str: Relative date string
        reference_date: Reference date for calculation
        
    Returns:
        Computed absolute date
    """
    date_str_lower = date_str.lower()
    
    # Extract number and unit
    # Pattern: "через N дней/недель/месяцев"
    patterns = [
        (r'через\s+(\d+)\s+дн', 'days'),
        (r'через\s+(\d+)\s+недел', 'weeks'),
        (r'через\s+(\d+)\s+месяц', 'months'),
        (r'через\s+(\d+)\s+год', 'years'),
    ]
    
    for pattern, unit in patterns:
        match = re.search(pattern, date_str_lower)
        if match:
            number = int(match.group(1))
            if unit == 'days':
                return (reference_date + timedelta(days=number)).date()
            elif unit == 'weeks':
                return (reference_date + timedelta(weeks=number)).date()
            elif unit == 'months':
                return (reference_date + relativedelta(months=number)).date()
            elif unit == 'years':
                return (reference_date + relativedelta(years=number)).date()
    
    # If no pattern matched, return reference date
    logger.warning(f"Could not parse relative date '{date_str}', using reference date")
    return reference_date.date()


def validate_date_sequence(events: List[Any]) -> List[str]:
    """
    Validate logical sequence of dates in events.
    
    Checks:
    - Dates are in chronological order (if order field exists)
    - No future dates beyond reasonable limits
    - No dates before 1900 (likely parsing errors)
    
    Args:
        events: List of timeline events (TimelineEventModel or dict with 'date' field)
        
    Returns:
        List of validation error messages (empty if all valid)
    """
    errors = []
    current_date = None
    
    for idx, event in enumerate(events):
        try:
            # Extract date from event
            if hasattr(event, 'date'):
                date_str = event.date
            elif isinstance(event, dict):
                date_str = event.get('date')
            else:
                continue
            
            if not date_str:
                continue
            
            # Parse date
            try:
                event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                errors.append(f"Event {idx}: Invalid date format '{date_str}'")
                continue
            
            # Check for unreasonable dates
            if event_date.year < 1900:
                errors.append(f"Event {idx}: Date {date_str} is before 1900 (likely parsing error)")
            
            if event_date.year > 2100:
                errors.append(f"Event {idx}: Date {date_str} is after 2100 (likely parsing error)")
            
            # Check chronological order (if we have previous date)
            if current_date and event_date < current_date:
                # This is a warning, not necessarily an error (events might not be sorted)
                logger.debug(f"Event {idx}: Date {date_str} is before previous date {current_date}")
            
            current_date = event_date
            
        except Exception as e:
            errors.append(f"Event {idx}: Error validating date: {e}")
    
    return errors


def normalize_date(date_str: str) -> str:
    """
    Normalize date string to YYYY-MM-DD format.
    Alias for parse_and_normalize_date for backward compatibility.
    
    Args:
        date_str: Date string to normalize
        
    Returns:
        Normalized date string in YYYY-MM-DD format
    """
    return parse_and_normalize_date(date_str)


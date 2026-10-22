"""Calendar dates as the intelligence layer stores them: "YYYY-MM-DD" strings."""

from datetime import datetime, timedelta


def shift_date(date: str, days: int) -> str:
    """`date` moved by `days` whole days (negative = earlier). Raises ValueError if malformed."""
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")

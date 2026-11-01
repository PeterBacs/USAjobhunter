"""U.S. local time <-> Philippine time for interviews."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..config import HOME_TZ

US_TIMEZONES = {
    "America/New_York": "Eastern", "America/Chicago": "Central", "America/Denver": "Mountain",
    "America/Phoenix": "Arizona (no DST)", "America/Los_Angeles": "Pacific", "America/Anchorage": "Alaska",
    "Pacific/Honolulu": "Hawaii",
}


def local_to_utc(local_iso: str, tz: str) -> datetime:
    naive = datetime.fromisoformat(local_iso)
    return naive.replace(tzinfo=ZoneInfo(tz)).astimezone(timezone.utc).replace(tzinfo=None)


def both_times(utc_naive: datetime | None, tz: str | None) -> dict:
    if not utc_naive or not tz:
        return {"us_local": None, "ph_local": None}
    u = utc_naive.replace(tzinfo=timezone.utc)
    us = u.astimezone(ZoneInfo(tz))
    ph = u.astimezone(ZoneInfo(HOME_TZ))
    return {
        "us_local": us.strftime("%a %b %d, %Y %I:%M %p ") + (us.tzname() or ""),
        "ph_local": ph.strftime("%a %b %d, %Y %I:%M %p ") + "PHT",
        "us_local_iso": us.replace(tzinfo=None).isoformat(timespec="minutes"),
        "ph_local_iso": ph.replace(tzinfo=None).isoformat(timespec="minutes"),
    }

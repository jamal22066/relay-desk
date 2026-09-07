"""SLA deadline calculation.

Two modes. Wall-clock simply adds the target to the creation time. Business-hours
walks forward through the calendar, counting only working minutes and skipping
weekends and holidays.

A ticket parked on the customer accrues no time; when it resumes, the deadline
moves forward by however much working time the pause consumed.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app import settings_store as store


class Calendar:
    def __init__(self, db: Session):
        self.tz = ZoneInfo(store.get(db, "business_timezone") or "UTC")
        self.days = set(store.get(db, "business_days") or [0, 1, 2, 3, 4])
        self.start = self._time(store.get(db, "business_day_start") or "09:00")
        self.end = self._time(store.get(db, "business_day_end") or "17:00")
        self.holidays = {
            date.fromisoformat(d) for d in (store.get(db, "business_holidays") or [])
        }
        self.business_only = bool(store.get(db, "sla_business_hours_only"))
        self.pause_enabled = bool(store.get(db, "sla_pause_on_customer"))
        self.targets = {
            p: int(store.get(db, f"sla_{p.lower()}_hours"))
            for p in ("P1", "P2", "P3", "P4")
        }

    @staticmethod
    def _time(hhmm: str) -> time:
        h, m = hhmm.split(":")
        return time(int(h), int(m))

    def _working_day(self, d: date) -> bool:
        return d.weekday() in self.days and d not in self.holidays

    def _window(self, d: date) -> tuple[datetime, datetime]:
        return (
            datetime.combine(d, self.start, tzinfo=self.tz),
            datetime.combine(d, self.end, tzinfo=self.tz),
        )

    def add(self, start: datetime, minutes: int) -> datetime:
        """Advance `start` by `minutes` of working time."""
        if not self.business_only:
            return start + timedelta(minutes=minutes)

        cur = start.astimezone(self.tz)
        remaining = minutes
        guard = 0

        while remaining > 0:
            guard += 1
            if guard > 3650:  # ten years of days; the config is broken
                raise ValueError("SLA calculation did not converge — check business days")

            if not self._working_day(cur.date()):
                cur = datetime.combine(cur.date() + timedelta(days=1), self.start, tzinfo=self.tz)
                continue

            open_at, close_at = self._window(cur.date())
            if cur < open_at:
                cur = open_at
            if cur >= close_at:
                cur = datetime.combine(cur.date() + timedelta(days=1), self.start, tzinfo=self.tz)
                continue

            available = (close_at - cur).total_seconds() / 60
            if available >= remaining:
                return cur + timedelta(minutes=remaining)
            remaining -= available
            cur = datetime.combine(cur.date() + timedelta(days=1), self.start, tzinfo=self.tz)

        return cur

    def elapsed(self, start: datetime, end: datetime) -> int:
        """Working minutes between two instants."""
        if not self.business_only:
            return int((end - start).total_seconds() / 60)
        if end <= start:
            return 0

        total = 0.0
        cur = start.astimezone(self.tz)
        end = end.astimezone(self.tz)

        while cur.date() <= end.date():
            if self._working_day(cur.date()):
                open_at, close_at = self._window(cur.date())
                lo = max(cur, open_at)
                hi = min(end, close_at)
                if hi > lo:
                    total += (hi - lo).total_seconds() / 60
            cur = datetime.combine(cur.date() + timedelta(days=1), time(0, 0), tzinfo=self.tz)

        return int(total)

    def deadline(self, created_at: datetime, priority: str, paused_seconds: int = 0) -> datetime:
        due = self.add(created_at, self.targets[priority] * 60)
        if paused_seconds:
            due = self.add(due, paused_seconds // 60)
        return due

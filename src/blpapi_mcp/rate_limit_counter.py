"""
Daily rate-limit counter: 10,000 hits/day (EST/NY), persisted to JSON.
Single process, thread-safe. Used by BLP MCP to cap Bloomberg API usage.
"""

from __future__ import annotations

import json
import os
import threading
import typing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


def _today_est_str(tz: ZoneInfo, now: datetime) -> str:
    return now.astimezone(tz).strftime("%Y-%m-%d")


def _yesterday_est_str(today_str: str) -> str:
    dt = datetime.strptime(today_str, "%Y-%m-%d")
    return (dt - timedelta(days=1)).strftime("%Y-%m-%d")


class DailyRateLimitCounter:
    DAILY_LIMIT_DEFAULT = 10_000
    TZ_NAME = "America/New_York"
    RETENTION_DAYS = 30

    def __init__(
        self,
        state_path: Path | str | None = None,
        daily_limit: int = DAILY_LIMIT_DEFAULT,
        tz_name: str = TZ_NAME,
        retention_days: int = RETENTION_DAYS,
        now_func: typing.Callable[[], datetime] | None = None,
    ) -> None:
        self._state_path = Path(state_path) if state_path is not None else Path("var/ratelimit_state.json")
        self._daily_limit = daily_limit
        self._tz = ZoneInfo(tz_name)
        self._retention_days = retention_days
        self._now = now_func if now_func is not None else (lambda: datetime.now(ZoneInfo("UTC")))
        self._lock = threading.Lock()
        self._current_date = ""
        self._current_count = 0
        self._history: dict[str, int] = {}
        self._load_or_init()

    def _today_str(self) -> str:
        return _today_est_str(self._tz, self._now())

    def _atomic_write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _serialize_state(self) -> dict:
        return {
            "tz": getattr(self._tz, "key", str(self._tz)),
            "daily_limit": self._daily_limit,
            "current_date": self._current_date,
            "current_count": self._current_count,
            "history": self._history,
            "updated_at_utc": self._now().isoformat(),
        }

    def _load_or_init(self) -> None:
        if self._state_path.exists():
            try:
                with open(self._state_path) as f:
                    data = json.load(f)
                self._current_date = data["current_date"]
                self._current_count = int(data["current_count"])
                self._history = {k: int(v) for k, v in (data.get("history") or {}).items()}
                self._rollover_if_needed()
                return
            except (json.JSONDecodeError, KeyError, TypeError):
                backup = self._state_path.with_suffix(
                    self._state_path.suffix + ".corrupt." + self._now().strftime("%Y%m%d%H%M%S")
                )
                self._state_path.rename(backup)
        today = self._today_str()
        self._current_date = today
        self._current_count = 0
        self._history = {}
        self._save()

    def _save(self) -> None:
        self._atomic_write_json(self._state_path, self._serialize_state())

    def _rollover_if_needed(self) -> None:
        today = self._today_str()
        if today == self._current_date:
            return
        self._history[self._current_date] = self._current_count
        self._current_date = today
        self._current_count = 0
        if self._history:
            sorted_dates = sorted(self._history.keys(), reverse=True)
            if len(sorted_dates) > self._retention_days:
                for d in sorted_dates[self._retention_days :]:
                    del self._history[d]
        self._save()

    def try_consume(self, n: int = 1) -> tuple[bool, int]:
        """If adding n would exceed daily limit, return (False, current_count). Else add and return (True, new_count)."""
        if not isinstance(n, int) or n <= 0:
            raise ValueError("n must be a positive integer")
        with self._lock:
            self._rollover_if_needed()
            if self._current_count + n > self._daily_limit:
                return (False, self._current_count)
            self._current_count += n
            self._save()
            return (True, self._current_count)

    def can_consume(self, n: int = 1) -> bool:
        """True if n more hits would not exceed the daily limit (after rollover)."""
        with self._lock:
            self._rollover_if_needed()
            return self._current_count + n <= self._daily_limit

    def record_usage(self, n: int) -> None:
        """Record n hits after a request (e.g. after BLP returns). May push count over daily_limit."""
        if not isinstance(n, int) or n < 0:
            raise ValueError("n must be a non-negative integer")
        if n == 0:
            return
        with self._lock:
            self._rollover_if_needed()
            self._current_count += n
            self._save()

    def get_count(self) -> int:
        with self._lock:
            self._rollover_if_needed()
            return self._current_count

    def remaining(self) -> int:
        with self._lock:
            self._rollover_if_needed()
            return max(0, self._daily_limit - self._current_count)

    def get_usage(self, date_str: str) -> int | None:
        with self._lock:
            self._rollover_if_needed()
            if date_str == self._current_date:
                return self._current_count
            return self._history.get(date_str)

    def get_yesterday_usage(self) -> int | None:
        with self._lock:
            self._rollover_if_needed()
            yesterday = _yesterday_est_str(self._current_date)
            return self._history.get(yesterday)

    def force_save(self) -> None:
        with self._lock:
            self._rollover_if_needed()
            self._save()

from datetime import datetime, timedelta

import pytest
import pytz
from apscheduler.triggers.cron import CronTrigger

from src.scheduler import _crontab_dow

TZ = pytz.timezone("Europe/Istanbul")
ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def fire_days(dow: str) -> list:
    trigger = CronTrigger(minute="0", hour="9", day_of_week=_crontab_dow(dow), timezone=TZ)
    prev, now, days = None, TZ.localize(datetime(2026, 11, 1, 10, 0)), set()
    for _ in range(14):
        prev = trigger.get_next_fire_time(prev, prev or now)
        days.add(prev.strftime("%a"))
        prev += timedelta(minutes=1)
    return sorted(days, key=ORDER.index)


@pytest.mark.parametrize("dow, expected", [
    ("*",       ORDER),
    ("1-5",     ["Mon", "Tue", "Wed", "Thu", "Fri"]),   # hafta içi — Salı–Cumartesi DEĞİL
    ("0,6",     ["Sat", "Sun"]),                        # hafta sonu
    ("1,3,5",   ["Mon", "Wed", "Fri"]),
    ("0",       ["Sun"]),
    ("7",       ["Sun"]),
    ("0-6",     ORDER),
    ("mon-fri", ["Mon", "Tue", "Wed", "Thu", "Fri"]),
])
def test_crontab_weekdays_map_to_the_right_days(dow, expected):
    assert fire_days(dow) == expected

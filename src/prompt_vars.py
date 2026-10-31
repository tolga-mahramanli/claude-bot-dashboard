"""
prompt_vars.py - Prompt şablon değişkenleri

  {tarih}  → 30.10.2026      {gün}   → Cuma        {saat}  → 09:00
  {ay}     → Ekim            {yıl}   → 2026
  {dün}    → 29.10.2026      {yarın} → 31.10.2026
  {a|b|c}  → her çalışmada seçeneklerden biri rastgele
  {{ ve }} → düz süslü parantez

Tanınmayan {ifade}'ler olduğu gibi bırakılır (ör. kod parçaları).
"""

import random
import re
from datetime import datetime, timedelta
from typing import Optional

import pytz

DAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
MONTH_NAMES = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
               "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

# Arayüzde gösterilen değişkenler (ASCII yazımlar da kabul edilir)
VARIABLES = [
    ("tarih", "Bugünün tarihi"),
    ("gün",   "Haftanın günü"),
    ("saat",  "Çalışma saati"),
    ("ay",    "Ay adı"),
    ("yıl",   "Yıl"),
    ("dün",   "Dünün tarihi"),
    ("yarın", "Yarının tarihi"),
]
_ALIASES = {"gun": "gün", "yil": "yıl", "dun": "dün", "yarin": "yarın"}

_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}\n]+)\}")


def _values(now: datetime) -> dict:
    fmt = "%d.%m.%Y"
    return {
        "tarih": now.strftime(fmt),
        "gün":   DAY_NAMES[now.weekday()],
        "saat":  now.strftime("%H:%M"),
        "ay":    MONTH_NAMES[now.month - 1],
        "yıl":   str(now.year),
        "dün":   (now - timedelta(days=1)).strftime(fmt),
        "yarın": (now + timedelta(days=1)).strftime(fmt),
    }


def render(
    prompt: str,
    now: Optional[datetime] = None,
    timezone: str = "Europe/Istanbul",
    rng: Optional[random.Random] = None,
) -> str:
    """Prompt içindeki değişkenleri ve rastgele seçimleri doldurur."""
    if not prompt:
        return prompt
    if now is None:
        now = datetime.now(pytz.timezone(timezone))
    rng = rng or random.Random()
    values = _values(now)

    def _sub(m: re.Match) -> str:
        token = m.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        inner = m.group(1)
        key = inner.strip().lower()
        key = _ALIASES.get(key, key)
        if key in values:
            return values[key]
        if "|" in inner:
            return rng.choice([opt.strip() for opt in inner.split("|")])
        return token

    return _TOKEN.sub(_sub, prompt)

import random
from datetime import datetime

import pytz

from src.prompt_vars import render

NOW = pytz.timezone("Europe/Istanbul").localize(datetime(2026, 10, 30, 9, 5))  # Cuma


def test_variables_are_filled():
    out = render("{gün} {tarih} {saat} {ay} {yıl} {dün} {yarın}", now=NOW)
    assert out == "Cuma 30.10.2026 09:05 Ekim 2026 29.10.2026 31.10.2026"


def test_ascii_aliases_and_case():
    assert render("{gun} {YIL} {Yarin}", now=NOW) == "Cuma 2026 31.10.2026"


def test_random_choice_uses_one_of_the_options():
    seen = {render("{a | b|c}", now=NOW, rng=random.Random(i)) for i in range(40)}
    assert seen == {"a", "b", "c"}


def test_unknown_braces_and_escapes_are_kept():
    assert render("kod: {x} ve {{gün}}", now=NOW) == "kod: {x} ve {gün}"
    assert render('json: {"a": 1}', now=NOW) == 'json: {"a": 1}'


def test_empty_prompt():
    assert render("", now=NOW) == ""

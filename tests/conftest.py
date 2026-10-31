import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLE_CONFIG = """\
# üst yorum
claude:
  base_url: https://claude.ai/chat
  chat_id: ''
  prompt: 'Global prompt'
scheduler:
  jobs:
  - id: sabah
    cron: 0 9 * * 1-5        # hafta içi
    enabled: true
    chat_id: abc
    prompt: Günaydın {gün}
  - id: aksam
    cron: 0 18 * * *
    enabled: false
    chat_id: ''
    prompt: devam et
  timezone: Europe/Istanbul
browser:
  headless: true   # pencere açılmasın
"""


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(SAMPLE_CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def history_db(tmp_path):
    from src import history
    history.init(str(tmp_path / "history.db"))
    yield history
    history._db_path = None

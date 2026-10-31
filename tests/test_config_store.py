import pytest

from src.config_store import load_config, merge_jobs, section, update_config


def test_update_keeps_comments_and_other_keys(config_file):
    def mutate(doc):
        section(doc, "browser")["headless"] = False
        merge_jobs(section(doc, "scheduler"), [
            {"id": "sabah", "cron": "30 9 * * 1-5", "enabled": True, "chat_id": "abc",
             "prompt": "Yeni", "retries": 2, "retry_delay": 5},
            {"id": "yeni", "cron": "0 12 * * *", "enabled": True, "chat_id": "", "prompt": "x",
             "retries": 0, "retry_delay": 5},
        ])

    update_config(str(config_file), mutate)
    text = config_file.read_text(encoding="utf-8")

    assert "# üst yorum" in text and "# pencere açılmasın" in text and "# hafta içi" in text
    assert "  jobs:\n  - id: sabah" in text  # mevcut girinti biçimi korunur
    cfg = load_config(str(config_file))
    assert cfg["browser"]["headless"] is False
    assert cfg["claude"]["prompt"] == "Global prompt"
    assert [j["id"] for j in cfg["scheduler"]["jobs"]] == ["sabah", "yeni"]  # 'aksam' silindi
    assert cfg["scheduler"]["jobs"][0]["cron"] == "30 9 * * 1-5"
    assert cfg["scheduler"]["jobs"][0]["retries"] == 2


def test_failed_update_leaves_file_untouched(config_file):
    before = config_file.read_text(encoding="utf-8")

    def boom(doc):
        doc["claude"]["prompt"] = "değişti"
        raise RuntimeError("yarıda kesildi")

    with pytest.raises(RuntimeError):
        update_config(str(config_file), boom)
    assert config_file.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in config_file.parent.iterdir()) == ["config.yaml"]  # geçici dosya kalmaz


def test_example_config_is_valid_yaml():
    from pathlib import Path
    cfg = load_config(str(Path(__file__).resolve().parent.parent / "config" / "config.example.yaml"))
    assert "{gün}" in cfg["scheduler"]["jobs"][0]["prompt"]
    assert cfg["scheduler"]["paused"] is False

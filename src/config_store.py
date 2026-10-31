"""
config_store.py - config.yaml okuma/yazma
Yazarken dosyadaki yorumları ve anahtar sırasını korur (ruamel round-trip)
ve atomik yazar: önce geçici dosyaya, sonra os.replace ile yerine taşır.
Böylece yazma yarıda kesilse bile config.yaml asla yarım kalmaz.
"""

import os
import tempfile
import threading
from pathlib import Path
from typing import Callable

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

_write_lock = threading.Lock()


def _yaml() -> YAML:
    y = YAML()  # round-trip
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=2, offset=0)  # PyYAML'ın ve örnek dosyanın biçimi
    y.width = 4096
    return y


def load_config(config_path: str = "config/config.yaml") -> dict:
    """YAML konfigürasyonunu düz bir dict olarak yükler."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config dosyası bulunamadı: {config_path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def update_config(config_path: str, mutate: Callable[[CommentedMap], None]) -> None:
    """
    Config'i yorumlarıyla birlikte yükler, `mutate(doc)` ile yerinde değiştirir
    ve atomik olarak geri yazar.
    """
    path = Path(config_path)
    with _write_lock:
        y = _yaml()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                doc = y.load(f) or CommentedMap()
        else:
            doc = CommentedMap()

        mutate(doc)

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".yaml", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                y.dump(doc, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def section(doc: CommentedMap, key: str) -> CommentedMap:
    """`doc[key]` bir map değilse oluşturur ve döndürür."""
    if not isinstance(doc.get(key), dict):
        doc[key] = CommentedMap()
    return doc[key]


def merge_jobs(sched: CommentedMap, jobs: list) -> None:
    """
    Görev listesini günceller. Aynı id'ye sahip mevcut görevlerin map'leri
    yeniden kullanılır; böylece görev içindeki yorumlar kaybolmaz.
    """
    existing = {}
    for item in sched.get("jobs") or []:
        if isinstance(item, dict) and item.get("id") is not None:
            existing.setdefault(str(item["id"]), item)

    seq = CommentedSeq()
    for job in jobs:
        target = existing.pop(str(job["id"]), None)
        if target is None:
            target = CommentedMap()
        for k, v in job.items():
            target[k] = v
        seq.append(target)
    sched["jobs"] = seq

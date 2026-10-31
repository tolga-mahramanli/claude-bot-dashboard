"""
history.py - Kalıcı çalışma geçmişi (SQLite)

runs      → her çalışma: görev, tetikleyici, süre, sonuç, prompt, Claude'un yanıtı, loglar
one_offs  → tek seferlik planlanmış çalışmalar
skips     → "sıradaki çalışmayı atla" işaretleri (görev başına bir tane)
"""

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

DEFAULT_DB_PATH = "./data/history.db"

# Bitmiş çalışma durumları ("running" ve "skipped" istatistiğe girmez)
FINISHED = ("success", "error", "session")

_lock = threading.RLock()
_db_path: Optional[str] = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT    NOT NULL,
    trigger     TEXT    NOT NULL,             -- scheduled | manual | retry | once | cli
    attempt     INTEGER NOT NULL DEFAULT 1,
    status      TEXT    NOT NULL,             -- running | success | error | session | skipped
    started_at  TEXT    NOT NULL,             -- ISO 8601, scheduler saat diliminde
    finished_at TEXT,
    duration    REAL,
    chat_id     TEXT,
    prompt      TEXT,
    response    TEXT,
    error       TEXT,
    screenshot  TEXT,
    logs        TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_job     ON runs(job_id, id);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at);

CREATE TABLE IF NOT EXISTS one_offs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL,
    run_at     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending', -- pending | done | cancelled | missed
    run_id     INTEGER
);

CREATE TABLE IF NOT EXISTS skips (
    job_id TEXT PRIMARY KEY,
    run_at TEXT NOT NULL
);
"""


def init(db_path: str = DEFAULT_DB_PATH) -> None:
    """Veritabanını hazırlar; önceki süreçte yarım kalan çalışmaları kapatır."""
    global _db_path
    with _lock:
        _db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with _connect() as db:
            db.executescript(_SCHEMA)
            db.execute(
                "UPDATE runs SET status='error', error=COALESCE(error, 'Süreç çalışma sırasında kapandı') "
                "WHERE status='running'"
            )


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path or DEFAULT_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
    with _lock:
        if _db_path is None:
            init()
        with _connect() as conn:
            yield conn


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _preview(text: Optional[str], n: int = 240) -> Optional[str]:
    if not text:
        return text
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rstrip() + "…"


# ── Çalışmalar ────────────────────────────────────────────────

def start_run(job_id: str, trigger: str, started_at: datetime, attempt: int = 1,
              chat_id: str = "", prompt: str = "") -> int:
    with _db() as db:
        cur = db.execute(
            "INSERT INTO runs (job_id, trigger, attempt, status, started_at, chat_id, prompt) "
            "VALUES (?, ?, ?, 'running', ?, ?, ?)",
            (job_id, trigger, attempt, _iso(started_at), chat_id, prompt),
        )
        return cur.lastrowid


def finish_run(run_id: int, status: str, finished_at: datetime, *, error: Optional[str] = None,
               screenshot: Optional[str] = None, response: Optional[str] = None,
               logs: Optional[str] = None) -> None:
    with _db() as db:
        row = db.execute("SELECT started_at FROM runs WHERE id=?", (run_id,)).fetchone()
        duration = None
        if row:
            duration = round((finished_at - datetime.fromisoformat(row["started_at"])).total_seconds(), 1)
        db.execute(
            "UPDATE runs SET status=?, finished_at=?, duration=?, error=?, screenshot=?, response=?, logs=? "
            "WHERE id=?",
            (status, _iso(finished_at), duration, error, screenshot, response, logs, run_id),
        )


def record_skipped(job_id: str, trigger: str, at: datetime, reason: str) -> int:
    with _db() as db:
        cur = db.execute(
            "INSERT INTO runs (job_id, trigger, status, started_at, finished_at, duration, error) "
            "VALUES (?, ?, 'skipped', ?, ?, 0, ?)",
            (job_id, trigger, _iso(at), _iso(at), reason),
        )
        return cur.lastrowid


def _summary(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("logs", None)
    d["response_preview"] = _preview(d.pop("response", None))
    d["prompt"] = _preview(d.get("prompt"), 160)
    return d


def list_runs(job_id: Optional[str] = None, status: Optional[str] = None,
              limit: int = 30, before_id: Optional[int] = None) -> list:
    where, args = [], []
    if job_id:
        where.append("job_id=?"); args.append(job_id)
    if status:
        where.append("status=?"); args.append(status)
    if before_id:
        where.append("id<?"); args.append(before_id)
    sql = "SELECT * FROM runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(limit, 200)))
    with _db() as db:
        return [_summary(r) for r in db.execute(sql, args).fetchall()]


def get_run(run_id: int) -> Optional[dict]:
    with _db() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None


def last_finished_run() -> Optional[dict]:
    with _db() as db:
        row = db.execute(
            f"SELECT * FROM runs WHERE status IN {FINISHED} ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _summary(row) if row else None


def totals() -> dict:
    with _db() as db:
        rows = db.execute("SELECT status, COUNT(*) AS n FROM runs GROUP BY status").fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    out = {s: counts.get(s, 0) for s in (*FINISHED, "skipped")}
    out["total"] = sum(counts.get(s, 0) for s in FINISHED)
    return out


def status_counts(job_id: Optional[str] = None) -> dict:
    sql, args = "SELECT status, COUNT(*) AS n FROM runs", []
    if job_id:
        sql += " WHERE job_id=?"; args.append(job_id)
    sql += " GROUP BY status"
    with _db() as db:
        rows = db.execute(sql, args).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    counts["all"] = sum(counts.values())
    return counts


def heatmap(today: datetime, days: int = 91) -> list:
    """Son `days` günün günlük başarı/hata sayıları (eskiden yeniye)."""
    start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    with _db() as db:
        rows = db.execute(
            "SELECT substr(started_at, 1, 10) AS day, "
            "SUM(status='success') AS success, SUM(status IN ('error','session')) AS error "
            "FROM runs WHERE substr(started_at, 1, 10) >= ? GROUP BY day",
            (start,),
        ).fetchall()
    by_day = {r["day"]: (r["success"] or 0, r["error"] or 0) for r in rows}
    out = []
    for i in range(days - 1, -1, -1):
        day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        ok, bad = by_day.get(day, (0, 0))
        out.append({"date": day, "success": ok, "error": bad})
    return out


def job_stats() -> dict:
    """Görev başına özet: toplam, başarılı, son çalışma durumu ve yanıt önizlemesi."""
    with _db() as db:
        agg = db.execute(
            f"SELECT job_id, COUNT(*) AS total, SUM(status='success') AS success "
            f"FROM runs WHERE status IN {FINISHED} GROUP BY job_id"
        ).fetchall()
        last = db.execute(
            f"SELECT r.* FROM runs r JOIN (SELECT job_id, MAX(id) AS id FROM runs "
            f"WHERE status IN {FINISHED} GROUP BY job_id) m ON r.id = m.id"
        ).fetchall()
    out = {r["job_id"]: {"total": r["total"], "success": r["success"] or 0} for r in agg}
    for r in last:
        out.setdefault(r["job_id"], {"total": 0, "success": 0})["last"] = {
            "id": r["id"], "status": r["status"], "started_at": r["started_at"],
            "response_preview": _preview(r["response"], 120),
        }
    return out


# ── Tek seferlik çalışmalar ───────────────────────────────────

def add_one_off(job_id: str, run_at: datetime, created_at: datetime) -> int:
    with _db() as db:
        cur = db.execute(
            "INSERT INTO one_offs (job_id, run_at, created_at) VALUES (?, ?, ?)",
            (job_id, _iso(run_at), _iso(created_at)),
        )
        return cur.lastrowid


def get_one_off(one_off_id: int) -> Optional[dict]:
    with _db() as db:
        row = db.execute("SELECT * FROM one_offs WHERE id=?", (one_off_id,)).fetchone()
        return dict(row) if row else None


def list_one_offs(status: str = "pending") -> list:
    with _db() as db:
        rows = db.execute("SELECT * FROM one_offs WHERE status=? ORDER BY run_at", (status,)).fetchall()
        return [dict(r) for r in rows]


def set_one_off_status(one_off_id: int, status: str, run_id: Optional[int] = None) -> None:
    with _db() as db:
        db.execute("UPDATE one_offs SET status=?, run_id=COALESCE(?, run_id) WHERE id=?",
                   (status, run_id, one_off_id))


# ── Atlamalar ─────────────────────────────────────────────────

def set_skip(job_id: str, run_at: datetime) -> None:
    with _db() as db:
        db.execute("INSERT OR REPLACE INTO skips (job_id, run_at) VALUES (?, ?)", (job_id, _iso(run_at)))


def clear_skip(job_id: str) -> None:
    with _db() as db:
        db.execute("DELETE FROM skips WHERE job_id=?", (job_id,))


def get_skips(now: datetime, grace: timedelta = timedelta(minutes=10)) -> dict:
    """Geçerli atlamaları {job_id: datetime} olarak döndürür; süresi geçenleri siler."""
    with _db() as db:
        rows = db.execute("SELECT job_id, run_at FROM skips").fetchall()
        out = {}
        for r in rows:
            at = datetime.fromisoformat(r["run_at"])
            if at < now - grace:
                db.execute("DELETE FROM skips WHERE job_id=?", (r["job_id"],))
            else:
                out[r["job_id"]] = at
        return out


def consume_skip(job_id: str, now: datetime, window: timedelta = timedelta(minutes=6)) -> bool:
    """Bu tetiklenme atlanacak çalışmaya denk geliyorsa işareti siler ve True döner."""
    with _db() as db:
        row = db.execute("SELECT run_at FROM skips WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return False
        at = datetime.fromisoformat(row["run_at"])
        if abs((now - at).total_seconds()) <= window.total_seconds():
            db.execute("DELETE FROM skips WHERE job_id=?", (job_id,))
            return True
        return False

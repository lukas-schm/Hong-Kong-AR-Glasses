"""SQLite back-end for the CDARS warehouse.

A single relational database file under data/cdars.sqlite holding the
encounter-based EHR tables. Thread-safe for FastAPI's threadpool via a
module-level lock. The schema is created on first use; seed.py populates it.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DB_PATH = Path("data/cdars.sqlite")

_SCHEMA = """
-- ── De-identified patient master (research view keys off this) ──────────────
CREATE TABLE IF NOT EXISTS patient (
    reference_key TEXT PRIMARY KEY,   -- CDARS pseudo-identifier, never the HKID
    sex           TEXT NOT NULL,
    birth_year    INTEGER NOT NULL,
    age           INTEGER NOT NULL,   -- age at the index/active episode
    dod           TEXT,               -- HK Death Registry date of death, or NULL
    active        INTEGER NOT NULL DEFAULT 0  -- 1 = current admission in this demo
);

-- ── Identity vault: HKID ↔ reference key. HA-internal; demo-only, exists
--    only for current admissions so they can be re-identified into eHRSS. ──
CREATE TABLE IF NOT EXISTS identity_vault (
    reference_key TEXT PRIMARY KEY,
    hkid          TEXT NOT NULL,
    name_en       TEXT NOT NULL,
    name_zh       TEXT NOT NULL,
    ccc           TEXT NOT NULL,
    dob           TEXT NOT NULL,
    hospital      TEXT NOT NULL,
    ward_en       TEXT NOT NULL,
    ward_zh       TEXT NOT NULL,
    FOREIGN KEY (reference_key) REFERENCES patient(reference_key)
);

CREATE TABLE IF NOT EXISTS episode (
    episode_id     TEXT PRIMARY KEY,
    reference_key  TEXT NOT NULL,
    episode_type   TEXT NOT NULL,     -- IP / SOPC / GOPC / AE / DH
    admission_date TEXT NOT NULL,
    discharge_date TEXT,              -- NULL → still admitted
    cluster        TEXT NOT NULL,
    hospital       TEXT NOT NULL,
    specialty      TEXT NOT NULL,
    ward           TEXT,
    FOREIGN KEY (reference_key) REFERENCES patient(reference_key)
);

CREATE TABLE IF NOT EXISTS diagnosis (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT NOT NULL,
    reference_key TEXT NOT NULL,
    code          TEXT NOT NULL,      -- ICD-9-CM
    rank          INTEGER NOT NULL,   -- 1 = principal
    dx_date       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prescription (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT NOT NULL,
    reference_key TEXT NOT NULL,
    bnf           TEXT NOT NULL,
    drug_code     TEXT NOT NULL,
    dose          TEXT,
    route         TEXT,
    frequency     TEXT,
    start_date    TEXT NOT NULL,
    end_date      TEXT,
    status        TEXT NOT NULL DEFAULT 'active'  -- active / stopped / completed
);

CREATE TABLE IF NOT EXISTS procedure (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT NOT NULL,
    reference_key TEXT NOT NULL,
    code          TEXT NOT NULL,
    name          TEXT NOT NULL,
    proc_date     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS allergy (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reference_key TEXT NOT NULL,
    code          TEXT NOT NULL,
    substance_en  TEXT NOT NULL,
    substance_zh  TEXT NOT NULL,
    reaction_en   TEXT NOT NULL,
    reaction_zh   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_result (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT NOT NULL,
    reference_key TEXT NOT NULL,
    test_code     TEXT NOT NULL,     -- HA local code
    value         REAL,
    unit          TEXT,
    flag          TEXT,
    collected     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS micro_result (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT NOT NULL,
    reference_key TEXT NOT NULL,
    specimen      TEXT NOT NULL,     -- blood / urine / sputum
    organism      TEXT NOT NULL,     -- catalog code (ECOLI, NG, PEND, …)
    result        TEXT NOT NULL,     -- positive / negative / pending
    collected     TEXT NOT NULL,
    resulted      TEXT
);

CREATE TABLE IF NOT EXISTS vital_sign (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT NOT NULL,
    reference_key TEXT NOT NULL,
    taken         TEXT NOT NULL,
    hr REAL, rr REAL, sbp REAL, map REAL, spo2 REAL, temp REAL
);

CREATE TABLE IF NOT EXISTS clinical_note (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id    TEXT,
    reference_key TEXT NOT NULL,
    author        TEXT NOT NULL,
    note_time     TEXT NOT NULL,
    lang          TEXT NOT NULL,
    text          TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'voice'  -- voice / chat / system
);

-- ── Derived decision-time feature snapshot for the sepsis cohort.
--    This is what the causal model scores; voice charting updates it. ──
CREATE TABLE IF NOT EXISTS patient_state (
    reference_key       TEXT PRIMARY KEY,
    sofa REAL, sapsii REAL, lactate REAL,
    vaso INTEGER, ventilation INTEGER, aki INTEGER, dialysis INTEGER,
    pct REAL, crp REAL, wbc REAL, temperature REAL,
    culture_result TEXT, source_identified INTEGER, pathogen_identified INTEGER,
    antibiotic_days REAL,
    age REAL, female INTEGER, comorbidity REAL, immunocompromised INTEGER,
    heart_rate REAL, resp_rate REAL, spo2 REAL, map REAL, urine_output REAL, weight REAL,
    active_treatment_id TEXT NOT NULL DEFAULT 'continue',
    updated_at TEXT
);

-- ── Analytic cohort table: the antibiotic-continuation decision + arm.
--    Mirrors the kind of derived table CDARS analysts build for studies. ──
CREATE TABLE IF NOT EXISTS abx_course (
    reference_key TEXT PRIMARY KEY,
    decision_date TEXT NOT NULL,
    arm           TEXT NOT NULL,     -- continue / deescalate / cease (observed)
    days_on_abx   INTEGER NOT NULL,
    mortality_28d INTEGER,           -- outcome for historic episodes; NULL if active
    -- denormalised severity for fast stratified cohort analytics
    sofa          REAL,
    lactate       REAL,
    culture       TEXT,
    age           INTEGER,
    sex           TEXT,
    cluster       TEXT
);

-- ── Presentation metadata for active admissions (HUD subtitle/tags,
--    cached fallback outcomes/recommendation). JSON blob for flexibility. ──
CREATE TABLE IF NOT EXISTS active_meta (
    reference_key TEXT PRIMARY KEY,
    meta          TEXT NOT NULL
);

-- ── Data Sharing Portal audit trail: every query / read / write. ──
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    actor         TEXT NOT NULL,
    action        TEXT NOT NULL,     -- query / read / write / reidentify / predict
    reference_key TEXT,
    channel       TEXT NOT NULL,     -- portal / agent / voice / glasses
    detail        TEXT
);

CREATE INDEX IF NOT EXISTS ix_episode_ref   ON episode(reference_key);
CREATE INDEX IF NOT EXISTS ix_episode_dx    ON diagnosis(code);
CREATE INDEX IF NOT EXISTS ix_lab_ref       ON lab_result(reference_key);
CREATE INDEX IF NOT EXISTS ix_vital_ref     ON vital_sign(reference_key);
CREATE INDEX IF NOT EXISTS ix_note_ref      ON clinical_note(reference_key);
CREATE INDEX IF NOT EXISTS ix_audit_ts      ON audit_log(ts);
"""


class Database:
    """Thin thread-safe wrapper around a single SQLite connection."""

    def __init__(self, path: Path = DB_PATH):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── core helpers ─────────────────────────────────────────────────────────
    def query(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur.lastrowid

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self._conn.executemany(sql, [tuple(p) for p in seq])
            self._conn.commit()

    def count(self, table: str, where: str = "", params: Iterable[Any] = ()) -> int:
        sql = f"SELECT COUNT(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        row = self.query_one(sql, params)
        return int(row["n"]) if row else 0

    def is_seeded(self) -> bool:
        try:
            return self.count("patient") > 0
        except sqlite3.Error:
            return False

    # ── audit ────────────────────────────────────────────────────────────────
    def audit(
        self,
        actor: str,
        action: str,
        *,
        reference_key: Optional[str] = None,
        channel: str = "portal",
        detail: str = "",
        ts: Optional[str] = None,
    ) -> None:
        from datetime import datetime, timezone

        self.execute(
            "INSERT INTO audit_log (ts, actor, action, reference_key, channel, detail) "
            "VALUES (?,?,?,?,?,?)",
            (
                ts or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                actor,
                action,
                reference_key,
                channel,
                detail,
            ),
        )


# Module-level singleton.
_db: Optional[Database] = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db

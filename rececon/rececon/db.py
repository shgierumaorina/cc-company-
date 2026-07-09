"""DB接続とスキーマ定義（詳細設計書3章の簡易実装。単一テナント・SQLite）。"""

import datetime
import sqlite3
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    patient_no TEXT NOT NULL UNIQUE,
    name_kanji TEXT NOT NULL,
    name_kana TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    gender TEXT NOT NULL CHECK (gender IN ('1', '2')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insurances (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    insurer_number TEXT NOT NULL,
    certificate_symbol TEXT,
    certificate_number TEXT NOT NULL,
    ratio REAL NOT NULL CHECK (ratio > 0 AND ratio <= 1),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS encounters (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    encounter_date TEXT NOT NULL,
    department_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'closed', 'billed')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS medical_acts (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL REFERENCES encounters(id),
    act_type TEXT NOT NULL,
    master_code TEXT NOT NULL,
    name TEXT NOT NULL,
    points INTEGER NOT NULL CHECK (points >= 0),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    source TEXT NOT NULL DEFAULT 'manual',
    source_ref TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (encounter_id, source_ref)
);

CREATE TABLE IF NOT EXISTS calculations (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL REFERENCES encounters(id),
    total_points INTEGER NOT NULL,
    total_amount INTEGER NOT NULL,
    patient_burden INTEGER NOT NULL,
    detail_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'calculated'
        CHECK (status IN ('calculated', 'superseded', 'error')),
    calculated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL REFERENCES encounters(id),
    claim_amount INTEGER NOT NULL,
    patient_burden INTEGER NOT NULL,
    paid_amount INTEGER NOT NULL,
    receipt_no TEXT NOT NULL UNIQUE,
    paid_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    billing_month TEXT NOT NULL,
    total_points INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'checked'
        CHECK (status IN ('draft', 'checked', 'submitted', 'returned')),
    record_data TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    patient_id TEXT,
    detail TEXT
);
"""


def connect(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def new_id():
    return str(uuid.uuid4())


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

"""患者・保険情報管理（詳細設計書4.1 / FR-01）。"""

import datetime
import sqlite3

from . import audit, db
from .errors import DuplicateError, NotFoundError, ValidationError


def _validate_date(value, field):
    try:
        datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} はYYYY-MM-DD形式で指定してください: {value!r}")


def register_patient(conn, actor, patient_no, name_kanji, name_kana,
                     birth_date, gender):
    """患者登録。戻り値は (patient_id, 類似患者リスト)。

    類似患者（カナ氏名＋生年月日＋性別が一致）が存在する場合も登録は行い、
    呼び出し側（画面）が警告表示する（詳細設計書4.1 二重登録防止フロー）。
    """
    if not patient_no or not name_kanji or not name_kana:
        raise ValidationError("診察券番号・氏名・カナ氏名は必須です")
    if gender not in ("1", "2"):
        raise ValidationError(f"性別は '1'（男）または '2'（女）: {gender!r}")
    _validate_date(birth_date, "生年月日")

    similar = find_similar(conn, name_kana, birth_date, gender)
    patient_id = db.new_id()
    try:
        conn.execute(
            "INSERT INTO patients "
            "(id, patient_no, name_kanji, name_kana, birth_date, gender, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (patient_id, patient_no, name_kanji, name_kana,
             birth_date, gender, db.now()),
        )
    except sqlite3.IntegrityError:
        raise DuplicateError(f"診察券番号が重複しています: {patient_no}")
    audit.log(conn, actor, "create", "patient", patient_id,
              patient_id, f"patient_no={patient_no}")
    return patient_id, similar


def find_similar(conn, name_kana, birth_date, gender):
    rows = conn.execute(
        "SELECT * FROM patients "
        "WHERE name_kana = ? AND birth_date = ? AND gender = ?",
        (name_kana, birth_date, gender),
    ).fetchall()
    return [dict(r) for r in rows]


def get_patient(conn, patient_id):
    row = conn.execute(
        "SELECT * FROM patients WHERE id = ?", (patient_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"患者が見つかりません: {patient_id}")
    return row


def search_patients(conn, query):
    """診察券番号完全一致またはカナ氏名前方一致で検索。"""
    like = query + "%"
    rows = conn.execute(
        "SELECT * FROM patients WHERE patient_no = ? OR name_kana LIKE ? "
        "ORDER BY patient_no",
        (query, like),
    ).fetchall()
    return [dict(r) for r in rows]


def add_insurance(conn, actor, patient_id, insurer_number, certificate_symbol,
                  certificate_number, ratio, valid_from, valid_to=None):
    get_patient(conn, patient_id)
    if not insurer_number or not certificate_number:
        raise ValidationError("保険者番号・被保険者証番号は必須です")
    if not (0 < ratio <= 1):
        raise ValidationError(f"負担割合は0より大きく1以下: {ratio}")
    _validate_date(valid_from, "資格開始日")
    if valid_to is not None:
        _validate_date(valid_to, "資格終了日")

    insurance_id = db.new_id()
    conn.execute(
        "INSERT INTO insurances "
        "(id, patient_id, insurer_number, certificate_symbol, "
        " certificate_number, ratio, valid_from, valid_to, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (insurance_id, patient_id, insurer_number, certificate_symbol,
         certificate_number, ratio, valid_from, valid_to, db.now()),
    )
    audit.log(conn, actor, "create", "insurance", insurance_id,
              patient_id, f"insurer={insurer_number}")
    return insurance_id


def get_valid_insurance(conn, patient_id, on_date):
    """指定日に有効な保険資格を返す。なければ None。"""
    row = conn.execute(
        "SELECT * FROM insurances "
        "WHERE patient_id = ? AND valid_from <= ? "
        "AND (valid_to IS NULL OR valid_to >= ?) "
        "ORDER BY valid_from DESC LIMIT 1",
        (patient_id, on_date, on_date),
    ).fetchone()
    return row

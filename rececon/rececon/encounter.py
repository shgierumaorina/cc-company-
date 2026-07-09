"""診療イベント・診療行為取込（詳細設計書4.2 / FR-02）。"""

import datetime

from . import audit, db
from .errors import BillingError, NotFoundError, ValidationError


def create_encounter(conn, actor, patient_id, encounter_date, department_code):
    try:
        datetime.date.fromisoformat(encounter_date)
    except (TypeError, ValueError):
        raise ValidationError(f"診療日はYYYY-MM-DD形式: {encounter_date!r}")
    row = conn.execute(
        "SELECT id FROM patients WHERE id = ?", (patient_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"患者が見つかりません: {patient_id}")

    encounter_id = db.new_id()
    conn.execute(
        "INSERT INTO encounters "
        "(id, patient_id, encounter_date, department_code, status, created_at) "
        "VALUES (?, ?, ?, ?, 'open', ?)",
        (encounter_id, patient_id, encounter_date, department_code, db.now()),
    )
    audit.log(conn, actor, "create", "encounter", encounter_id,
              patient_id, f"date={encounter_date}")
    return encounter_id


def get_encounter(conn, encounter_id):
    row = conn.execute(
        "SELECT * FROM encounters WHERE id = ?", (encounter_id,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"診療イベントが見つかりません: {encounter_id}")
    return row


def add_act(conn, actor, encounter_id, act_type, master_code, name, points,
            quantity=1, source="manual", source_ref=None):
    """診療行為の追加。

    source_ref が指定され既存の場合は更新する（電カル取込の冪等化、
    詳細設計書4.2）。戻り値は (act_id, created: bool)。
    """
    enc = get_encounter(conn, encounter_id)
    if enc["status"] != "open":
        raise BillingError(
            f"確定済みの診療イベントには追加できません（status={enc['status']}）")
    if points < 0 or quantity <= 0:
        raise ValidationError("点数は0以上、数量は1以上で指定してください")

    if source_ref is not None:
        existing = conn.execute(
            "SELECT id FROM medical_acts "
            "WHERE encounter_id = ? AND source_ref = ?",
            (encounter_id, source_ref),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE medical_acts SET act_type = ?, master_code = ?, "
                "name = ?, points = ?, quantity = ?, source = ? WHERE id = ?",
                (act_type, master_code, name, points, quantity, source,
                 existing["id"]),
            )
            audit.log(conn, actor, "update", "medical_act", existing["id"],
                      enc["patient_id"], f"source_ref={source_ref}")
            return existing["id"], False

    act_id = db.new_id()
    conn.execute(
        "INSERT INTO medical_acts "
        "(id, encounter_id, act_type, master_code, name, points, quantity, "
        " source, source_ref, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (act_id, encounter_id, act_type, master_code, name, points,
         quantity, source, source_ref, db.now()),
    )
    audit.log(conn, actor, "create", "medical_act", act_id,
              enc["patient_id"], f"code={master_code}")
    return act_id, True


def list_acts(conn, encounter_id):
    rows = conn.execute(
        "SELECT * FROM medical_acts WHERE encounter_id = ? ORDER BY created_at",
        (encounter_id,),
    ).fetchall()
    return rows


def close_encounter(conn, actor, encounter_id):
    """診療行為確定。1件以上の診療行為があることを検証する。"""
    enc = get_encounter(conn, encounter_id)
    if enc["status"] != "open":
        raise BillingError(f"すでに確定済みです（status={enc['status']}）")
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM medical_acts WHERE encounter_id = ?",
        (encounter_id,),
    ).fetchone()["c"]
    if count == 0:
        raise BillingError("診療行為が1件も登録されていません")
    conn.execute(
        "UPDATE encounters SET status = 'closed' WHERE id = ?", (encounter_id,)
    )
    audit.log(conn, actor, "close", "encounter", encounter_id,
              enc["patient_id"])

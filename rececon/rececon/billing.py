"""算定・会計（詳細設計書4.3 / FR-03, FR-04）。"""

import json

from . import audit, db, patient
from .calculator import SimpleCalculator
from .errors import BillingError
from .encounter import get_encounter


def run_calculation(conn, actor, encounter_id, calculator=None):
    """算定実行。既存の算定結果は superseded にして履歴保持する。"""
    calculator = calculator or SimpleCalculator()
    enc = get_encounter(conn, encounter_id)
    if enc["status"] not in ("closed", "billed"):
        raise BillingError("診療行為が確定されていません（先にclose_encounterを実行）")

    ins = patient.get_valid_insurance(
        conn, enc["patient_id"], enc["encounter_date"])
    if ins is None:
        raise BillingError(
            f"診療日 {enc['encounter_date']} に有効な保険資格がありません")

    acts = conn.execute(
        "SELECT * FROM medical_acts WHERE encounter_id = ?", (encounter_id,)
    ).fetchall()
    result = calculator.calculate(acts, ins["ratio"])

    conn.execute(
        "UPDATE calculations SET status = 'superseded' "
        "WHERE encounter_id = ? AND status = 'calculated'",
        (encounter_id,),
    )
    calc_id = db.new_id()
    conn.execute(
        "INSERT INTO calculations "
        "(id, encounter_id, total_points, total_amount, patient_burden, "
        " detail_json, status, calculated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'calculated', ?)",
        (calc_id, encounter_id, result["total_points"],
         result["total_amount"], result["patient_burden"],
         json.dumps(result["details"], ensure_ascii=False), db.now()),
    )
    audit.log(conn, actor, "calculate", "calculation", calc_id,
              enc["patient_id"],
              f"points={result['total_points']} burden={result['patient_burden']}")
    return conn.execute(
        "SELECT * FROM calculations WHERE id = ?", (calc_id,)
    ).fetchone()


def get_current_calculation(conn, encounter_id):
    return conn.execute(
        "SELECT * FROM calculations "
        "WHERE encounter_id = ? AND status = 'calculated' "
        "ORDER BY calculated_at DESC LIMIT 1",
        (encounter_id,),
    ).fetchone()


def confirm_payment(conn, actor, encounter_id, paid_amount):
    """会計確定。算定済みであることを前提に収納を記録する。"""
    enc = get_encounter(conn, encounter_id)
    calc = get_current_calculation(conn, encounter_id)
    if calc is None:
        raise BillingError("算定結果がありません（先にrun_calculationを実行）")
    if paid_amount != calc["patient_burden"]:
        raise BillingError(
            f"収納額が患者負担額と一致しません: "
            f"負担額={calc['patient_burden']} 収納額={paid_amount}")

    seq = conn.execute("SELECT COUNT(*) AS c FROM payments").fetchone()["c"] + 1
    receipt_no = f"{seq:08d}"
    payment_id = db.new_id()
    conn.execute(
        "INSERT INTO payments "
        "(id, encounter_id, claim_amount, patient_burden, paid_amount, "
        " receipt_no, paid_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (payment_id, encounter_id, calc["total_amount"],
         calc["patient_burden"], paid_amount, receipt_no, db.now()),
    )
    audit.log(conn, actor, "payment", "payment", payment_id,
              enc["patient_id"], f"receipt_no={receipt_no}")
    return conn.execute(
        "SELECT * FROM payments WHERE id = ?", (payment_id,)
    ).fetchone()

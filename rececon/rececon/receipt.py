"""レセプト作成・請求（詳細設計書4.4 / FR-05〜07）。

record_data は電子レセプト作成手引き（UKE）準拠を目標とした
簡易プレースホルダ形式。本実装ではレコード種別ごとのビルダー関数に
分割してあり、手引き準拠版への差替え時はビルダーのみ変更する。
"""

from . import audit, db, patient
from .billing import get_current_calculation
from .errors import ValidationError


def _build_re(seq, pat, billing_month):
    return f"RE,{seq},{pat['patient_no']},{pat['name_kanji']}," \
           f"{pat['gender']},{pat['birth_date']},{billing_month}"


def _build_ho(ins):
    symbol = ins["certificate_symbol"] or ""
    return f"HO,{ins['insurer_number']},{symbol}," \
           f"{ins['certificate_number']},{ins['ratio']}"


def _build_si(act):
    return f"SI,{act['act_type']},{act['master_code']},{act['name']}," \
           f"{act['points']},{act['quantity']}"


def _build_go(total_points):
    return f"GO,{total_points}"


def _month_prefix(billing_month):
    if len(billing_month) != 6 or not billing_month.isdigit():
        raise ValidationError(f"請求年月はYYYYMM形式: {billing_month!r}")
    return billing_month[:4] + "-" + billing_month[4:]


def generate_monthly_receipts(conn, actor, billing_month):
    """月次レセプト生成（詳細設計書4.4のフロー）。

    戻り値: 患者ごとの結果リスト
      [{patient_id, status: 'generated'|'error', receipt_id?, errors?}]
    チェックNGの患者はレセプトを生成せずエラーを返す（他患者は継続）。
    """
    prefix = _month_prefix(billing_month)
    encounters = conn.execute(
        "SELECT * FROM encounters "
        "WHERE status = 'closed' AND substr(encounter_date, 1, 7) = ? "
        "ORDER BY patient_id, encounter_date",
        (prefix,),
    ).fetchall()

    by_patient = {}
    for enc in encounters:
        by_patient.setdefault(enc["patient_id"], []).append(enc)

    results = []
    for patient_id, encs in by_patient.items():
        errors = []

        existing = conn.execute(
            "SELECT id FROM receipts "
            "WHERE patient_id = ? AND billing_month = ? "
            "AND status IN ('checked', 'submitted')",
            (patient_id, billing_month),
        ).fetchone()
        if existing:
            errors.append(f"当月のレセプトが既に存在します: {existing['id']}")

        ins = None
        calcs = {}
        for enc in encs:
            enc_ins = patient.get_valid_insurance(
                conn, patient_id, enc["encounter_date"])
            if enc_ins is None:
                errors.append(
                    f"診療日 {enc['encounter_date']} に有効な保険資格がありません")
            else:
                ins = enc_ins
            calc = get_current_calculation(conn, enc["id"])
            if calc is None:
                errors.append(
                    f"診療日 {enc['encounter_date']} の算定結果がありません")
            else:
                calcs[enc["id"]] = calc

        if errors:
            results.append({
                "patient_id": patient_id, "status": "error", "errors": errors,
            })
            continue

        pat = patient.get_patient(conn, patient_id)
        lines = [_build_re(len(results) + 1, pat, billing_month),
                 _build_ho(ins)]
        total_points = 0
        for enc in encs:
            acts = conn.execute(
                "SELECT * FROM medical_acts WHERE encounter_id = ? "
                "ORDER BY created_at",
                (enc["id"],),
            ).fetchall()
            for act in acts:
                lines.append(_build_si(act))
            total_points += calcs[enc["id"]]["total_points"]
        lines.append(_build_go(total_points))

        receipt_id = db.new_id()
        conn.execute(
            "INSERT INTO receipts "
            "(id, patient_id, billing_month, total_points, status, "
            " record_data, created_at) "
            "VALUES (?, ?, ?, ?, 'checked', ?, ?)",
            (receipt_id, patient_id, billing_month, total_points,
             "\n".join(lines), db.now()),
        )
        for enc in encs:
            conn.execute(
                "UPDATE encounters SET status = 'billed' WHERE id = ?",
                (enc["id"],),
            )
        audit.log(conn, actor, "generate", "receipt", receipt_id,
                  patient_id, f"month={billing_month} points={total_points}")
        results.append({
            "patient_id": patient_id, "status": "generated",
            "receipt_id": receipt_id, "total_points": total_points,
        })
    return results


def export_uke(conn, billing_month):
    """請求月のレセプト一式を1ファイル分の文字列として出力する。"""
    _month_prefix(billing_month)
    rows = conn.execute(
        "SELECT * FROM receipts "
        "WHERE billing_month = ? AND status = 'checked' "
        "ORDER BY created_at",
        (billing_month,),
    ).fetchall()
    header = f"IR,{billing_month},{len(rows)}"
    bodies = [r["record_data"] for r in rows]
    return "\n".join([header] + bodies)

"""監査ログ（詳細設計書8.1）。医療情報への操作を追記専用で記録する。"""

from . import db


def log(conn, actor, action, resource_type, resource_id=None,
        patient_id=None, detail=""):
    conn.execute(
        "INSERT INTO audit_logs "
        "(id, at, actor, action, resource_type, resource_id, patient_id, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (db.new_id(), db.now(), actor, action, resource_type,
         resource_id, patient_id, detail),
    )


def search(conn, patient_id=None, actor=None):
    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []
    if patient_id:
        query += " AND patient_id = ?"
        params.append(patient_id)
    if actor:
        query += " AND actor = ?"
        params.append(actor)
    query += " ORDER BY at"
    return conn.execute(query, params).fetchall()

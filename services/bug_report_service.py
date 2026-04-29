"""Servicio de bug reports."""
from __future__ import annotations
from models.bug_report import BugReport, BugReportCreate, BugReportUpdate
from services.db_protocol import DBClient

def create_bug_report(db: DBClient, reporter_id: str, payload: BugReportCreate) -> BugReport:
    """Crea un nuevo reporte. RLS valida que el caller sea tester+."""
    data = payload.model_dump()
    data["reporter_id"] = reporter_id
    if data.get("entity_type") is None:
        data["entity_id"] = None
    if data.get("entity_id") is None:
        data["entity_type"] = None
    response = db.table("bug_reports").insert(data).execute()
    if not response.data:
        raise ValueError("bug_report_create_failed")
    return BugReport(**response.data[0])

def list_my_reports(db: DBClient, reporter_id: str, limit: int = 50) -> list[BugReport]:
    """Lista los reportes del user actual, mas nuevos primero."""
    response = (
        db.table("bug_reports")
        .select("*")
        .eq("reporter_id", reporter_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [BugReport(**row) for row in (response.data or [])]

def list_all_reports(db: DBClient, status: str | None = None, limit: int = 100) -> list[BugReport]:
    """Lista todos los reportes con info del reporter. RLS limita a developer+."""
    query = (
        db.table("bug_reports")
        .select("*, reporter:profiles!reporter_id(username,display_name,avatar_url)")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if status:
        query = query.eq("status", status)
    response = query.execute()
    return [BugReport(**row) for row in (response.data or [])]

def update_report_status(db: DBClient, report_id: str, payload: BugReportUpdate) -> BugReport:
    """Actualiza el status de un reporte. RLS limita a developer+."""
    response = (
        db.table("bug_reports")
        .update({"status": payload.status})
        .eq("id", report_id)
        .execute()
    )
    if not response.data:
        raise ValueError(f"bug_report_not_found_or_update_failed: {report_id}")
    return BugReport(**response.data[0])
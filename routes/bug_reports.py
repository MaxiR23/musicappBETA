"""Endpoints de bug reports."""
from fastapi import APIRouter, Depends, HTTPException, Query
from core.dependencies import get_current_profile, get_user_db, require_role
from services.db_protocol import DBClient
from services.bug_report_service import (
    create_bug_report,
    list_my_reports,
    list_all_reports,
    update_report_status,
)
from models.bug_report import BugReport, BugReportCreate, BugReportUpdate
from models.profile import Profile

router = APIRouter()

@router.post("", response_model=BugReport)
def create_report(
    payload: BugReportCreate,
    profile: Profile = Depends(require_role("tester")),
    db: DBClient = Depends(get_user_db),
):
    """Crea un reporte. Solo tester+."""
    try:
        return create_bug_report(db, profile.id, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/me", response_model=list[BugReport])
def get_my_reports(
    limit: int = Query(50, ge=1, le=100),
    profile: Profile = Depends(get_current_profile),
    db: DBClient = Depends(get_user_db),
):
    """Lista reportes del user actual."""
    return list_my_reports(db, profile.id, limit=limit)

@router.get("", response_model=list[BugReport])
def get_all_reports(
    status: str | None = Query(None, regex="^(open|closed)$"),
    limit: int = Query(100, ge=1, le=200),
    profile: Profile = Depends(require_role("developer")),
    db: DBClient = Depends(get_user_db),
):
    """Lista todos los reportes. Solo developer+."""
    return list_all_reports(db, status=status, limit=limit)

@router.patch("/{report_id}", response_model=BugReport)
def patch_report(
    report_id: str,
    payload: BugReportUpdate,
    profile: Profile = Depends(require_role("developer")),
    db: DBClient = Depends(get_user_db),
):
    """Actualiza el status. Solo developer+."""
    try:
        return update_report_status(db, report_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
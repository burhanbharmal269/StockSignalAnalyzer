"""Runbook retrieval API.

GET /api/v1/runbooks           — list all runbooks
GET /api/v1/runbooks/{run_id}  — fetch a specific runbook by ID (e.g. RB-001)
"""


import pathlib
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from core.presentation.api.v1.dependencies.auth import require_authenticated
from fastapi import Depends
from core.presentation.api.v1.schemas.auth import CurrentUser

router = APIRouter(prefix="/api/v1/runbooks", tags=["Operational Runbooks"])

_RUNBOOK_DIR = pathlib.Path(__file__).parents[7] / "runbooks"


def _load_all() -> list[dict[str, Any]]:
    runbooks = []
    if not _RUNBOOK_DIR.exists():
        return runbooks
    for path in sorted(_RUNBOOK_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                runbooks.append(data)
        except Exception:
            pass
    return runbooks


class RunbookSummary(BaseModel):
    id: str
    title: str
    version: str
    severity: str
    last_updated: str
    summary: str


@router.get("", response_model=list[RunbookSummary], summary="List all operational runbooks")
async def list_runbooks(
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
) -> list[RunbookSummary]:
    return [
        RunbookSummary(
            id=rb.get("id", "UNKNOWN"),
            title=rb.get("title", ""),
            version=str(rb.get("version", "1.0")),
            severity=rb.get("severity", ""),
            last_updated=str(rb.get("last_updated", "")),
            summary=str(rb.get("summary", "")).strip(),
        )
        for rb in _load_all()
    ]


@router.get("/{runbook_id}", summary="Fetch full runbook by ID (e.g. RB-001)")
async def get_runbook(
    runbook_id: str,
    _user: CurrentUser = Depends(require_authenticated),  # noqa: B008
) -> dict[str, Any]:
    for rb in _load_all():
        if rb.get("id", "").upper() == runbook_id.upper():
            return rb
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Runbook '{runbook_id}' not found.",
    )

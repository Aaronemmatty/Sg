from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_prompt_manager, get_repository
from app.auth import require_role
from app.db.repository import AnalystRepository
from app.models.domain import AnalysisCapability, PromptTemplate
from app.services.prompt_manager import PromptManager

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateTemplateRequest(BaseModel):
    system_prompt: str = Field(..., min_length=1)
    user_template: str = Field(..., min_length=1)
    activate: bool = False


@router.get("/prompts")
async def list_prompts(
    capability: AnalysisCapability | None = None,
    repo: AnalystRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(require_role("risk_officer")),
) -> list[PromptTemplate]:
    return await repo.list_templates(capability)


@router.post("/prompts/{capability}", status_code=status.HTTP_201_CREATED)
async def create_prompt_version(
    capability: AnalysisCapability,
    body: CreateTemplateRequest,
    repo: AnalystRepository = Depends(get_repository),
    prompt_manager: PromptManager = Depends(get_prompt_manager),
    user: dict[str, Any] = Depends(require_role("risk_officer")),
) -> PromptTemplate:
    created_by = str(user.get("sub", "unknown"))
    template = await repo.create_template(
        capability, body.system_prompt, body.user_template, created_by, activate=body.activate
    )
    prompt_manager.invalidate(capability)
    return template


@router.post("/prompts/{capability}/activate/{version}")
async def activate_prompt_version(
    capability: AnalysisCapability,
    version: int,
    repo: AnalystRepository = Depends(get_repository),
    prompt_manager: PromptManager = Depends(get_prompt_manager),
    user: dict[str, Any] = Depends(require_role("risk_officer")),
) -> PromptTemplate:
    template = await repo.activate_template(capability, version)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No version {version} found for capability '{capability.value}'",
        )
    prompt_manager.invalidate(capability)
    return template


@router.get("/audit/summary")
async def audit_summary(
    hours: int = 24,
    repo: AnalystRepository = Depends(get_repository),
    user: dict[str, Any] = Depends(require_role("risk_officer")),
) -> dict:
    return await repo.get_audit_summary(hours=hours)

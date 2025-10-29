"""Workflow execution endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.workflows.engine import workflow_engine

router = APIRouter(prefix="/workflows", tags=["workflows"])

WorkflowType = Literal["incident", "release", "onboarding"]


class WorkflowRequest(BaseModel):
    workflow: WorkflowType
    payload: dict = Field(default_factory=dict)


class WorkflowResponse(BaseModel):
    run_id: str
    workflow: WorkflowType


@router.post("/run", response_model=WorkflowResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_workflow(body: WorkflowRequest) -> WorkflowResponse:
    """Kick off a Temporal workflow run."""

    try:
        start_result = await workflow_engine.start_workflow(body.workflow, body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return WorkflowResponse(run_id=start_result.run_id, workflow=body.workflow)

"""Query processing endpoints."""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.knowledge.retrieval.graph_rag import GraphRAGEngine
from backend.models.query import Query
from backend.models.response import Citation, QueryResponse

router = APIRouter(prefix="/queries", tags=["queries"])

rag_engine = GraphRAGEngine()


class QueryPayload(BaseModel):
    text: str = Field(..., description="Natural language query")
    context: dict = Field(default_factory=dict, description="Optional contextual metadata")


class QueryResult(BaseModel):
    response: QueryResponse


@router.post("/", response_model=QueryResult)
async def run_query(payload: QueryPayload) -> QueryResult:
    """Execute a graph-aware retrieval query."""

    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="Query text must not be empty")

    query = Query(id=str(uuid.uuid4()), text=payload.text, context=payload.context)
    documents = await rag_engine.retrieve(query)

    citations: List[Citation] = [
        Citation(document_id=doc["document"].id, snippet=doc["snippet"], score=doc["score"]) for doc in documents
    ]

    response = QueryResponse(
        id=str(uuid.uuid4()),
        query_id=query.id,
        content=documents[0]["summary"] if documents else "No relevant documents were found.",
        citations=citations,
    )

    return QueryResult(response=response)

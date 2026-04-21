"""
FastAPI Application Layer
=========================
Exposes the Graph RAG pipeline as a REST API.

Endpoints:
  GET  /health          → liveness probe (used by Docker healthcheck)
  POST /ingest          → ingest a knowledge graph triple
  POST /query           → run a Graph RAG query against Claude

This module will be superseded by the MCP server layer
(src/mcp_server.py) once the Model Context Protocol integration
is complete. The REST API remains as a fallback / non-MCP interface.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.graph_rag_agent import (
    GraphTriple,
    KnowledgeGraphClient,
    graph_rag_query,
)

logger = structlog.get_logger(__name__)

app = FastAPI(
    title="FalkorDB × Claude Graph RAG Service",
    description=(
        "Sovereign Graph RAG for European Enterprise AI. "
        "Retrieves structured knowledge graph context and grounds "
        "Claude's responses for GDPR-compliant, explainable AI."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    subject: str = Field(..., description="Source entity identifier", example="ACME_Corp")
    relation: str = Field(..., description="Relationship type (UPPER_SNAKE_CASE)", example="OWNS")
    object: str = Field(..., description="Target entity identifier", example="CustomerPII_Dataset_EU")


class IngestResponse(BaseModel):
    status: str
    triple: dict[str, str]


class QueryRequest(BaseModel):
    question: str = Field(..., description="Natural language question", example="Which entities own EU personal data?")
    entity_filter: str | None = Field(None, description="Optional entity id to anchor traversal")
    max_hops: int = Field(2, description="Maximum graph traversal hops", ge=1, le=5)


class QueryResponse(BaseModel):
    answer: str
    context_summary: dict[str, Any]
    cypher_used: str
    provenance: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    """Liveness probe — returns 200 when the service is up."""
    return {"status": "ok", "service": "graph-rag"}


@app.post("/ingest", response_model=IngestResponse, tags=["graph"])
async def ingest_triple(req: IngestRequest) -> IngestResponse:
    """
    Ingest a subject-relation-object triple into the knowledge graph.

    Uses MERGE semantics — safe to call idempotently.
    """
    try:
        kg = KnowledgeGraphClient()
        triple = GraphTriple(
            subject=req.subject,
            predicate=req.relation.upper().replace(" ", "_"),
            object=req.object,
        )
        kg.ingest_triple(triple)
        logger.info("Triple ingested via API", triple=triple)
        return IngestResponse(
            status="ingested",
            triple={"subject": triple.subject, "predicate": triple.predicate, "object": triple.object},
        )
    except Exception as exc:
        logger.error("Ingest failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/query", response_model=QueryResponse, tags=["rag"])
async def query(req: QueryRequest) -> QueryResponse:
    """
    Execute a Graph RAG query: retrieve context → call Claude → return answer.

    The response includes full provenance (the Cypher query used and the
    specific graph triples that grounded Claude's answer).
    """
    try:
        result = graph_rag_query(
            user_question=req.question,
            entity_filter=req.entity_filter,
            max_hops=req.max_hops,
        )
        return QueryResponse(**result)
    except Exception as exc:
        logger.error("Query failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

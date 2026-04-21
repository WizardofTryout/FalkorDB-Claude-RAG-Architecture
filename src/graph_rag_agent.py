"""
FalkorDB × Claude — Graph RAG Core Agent
=========================================
Proof-of-concept for the Sovereign Graph RAG architecture.

This module demonstrates:
  1. Connecting to a FalkorDB Knowledge Graph
  2. Ingesting entity relationships as graph triples
  3. Executing Cypher queries to retrieve structured context
  4. Sending retrieved context + user query to Claude via the
     official Anthropic Python SDK
  5. Returning a grounded, provenance-aware answer

MCP Integration Points
-----------------------
Functions decorated with `# [MCP_TOOL]` are candidates for
exposure as Model Context Protocol tools once src/mcp_server.py
is implemented. Each will become a named tool that Claude can
call autonomously during an agentic workflow.

See: https://modelcontextprotocol.io/docs/concepts/tools

Architecture Flow
-----------------
  User Query
      │
      ▼
  [1] graph_rag_query()        ← entry point / MCP orchestrator
      │
      ├─► [2] retrieve_graph_context()  ← Cypher query → FalkorDB
      │         └── returns structured triples as List[dict]
      │
      ├─► [3] build_graph_prompt()      ← assembles system prompt
      │         └── injects graph context as structured XML block
      │
      └─► [4] call_claude()             ← Anthropic SDK invocation
                └── returns Message with citations & reasoning

Author: FalkorDB-Claude-RAG-Architecture contributors
License: MIT
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import anthropic
import structlog
from dotenv import load_dotenv
from falkordb import FalkorDB

# ---------------------------------------------------------------------------
# Environment & Logging Setup
# ---------------------------------------------------------------------------

load_dotenv()

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO"))
    ),
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FALKORDB_HOST: str = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT: int = int(os.getenv("FALKORDB_PORT", "6379"))
GRAPH_NAME: str = os.getenv("FALKORDB_GRAPH_NAME", "enterprise_kg")
CLAUDE_MODEL: str = "claude-3-5-sonnet-20241022"
MAX_TOKENS: int = 2048


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphTriple:
    """An immutable RDF-style subject-predicate-object triple."""

    subject: str
    predicate: str
    object: str
    metadata: dict[str, Any] | None = None

    def to_cypher_props(self) -> str:
        """Serialise metadata as a Cypher property map string."""
        if not self.metadata:
            return ""
        props = ", ".join(f"{k}: {json.dumps(v)}" for k, v in self.metadata.items())
        return f" {{{props}}}"


@dataclass
class GraphContext:
    """Structured context bundle retrieved from the knowledge graph."""

    query: str
    triples: list[dict[str, Any]]
    entity_count: int
    relationship_count: int
    cypher_used: str

    def to_xml_block(self) -> str:
        """
        Render context as structured XML for injection into Claude's prompt.

        Using XML delimiters is the Anthropic-recommended pattern for
        reliably separating retrieved context from user instructions.
        See: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering
        """
        triples_text = "\n".join(
            f"  <triple id='{i}'>"
            f"<subject>{t.get('subject', '')}</subject>"
            f"<predicate>{t.get('predicate', '')}</predicate>"
            f"<object>{t.get('object', '')}</object>"
            f"</triple>"
            for i, t in enumerate(self.triples)
        )

        return f"""<knowledge_graph_context>
  <metadata>
    <entity_count>{self.entity_count}</entity_count>
    <relationship_count>{self.relationship_count}</relationship_count>
    <cypher_query><![CDATA[{self.cypher_used}]]></cypher_query>
  </metadata>
  <triples>
{triples_text}
  </triples>
</knowledge_graph_context>"""


# ---------------------------------------------------------------------------
# FalkorDB Client
# ---------------------------------------------------------------------------


class KnowledgeGraphClient:
    """
    Thin wrapper around the FalkorDB Python client.

    Provides typed methods for ingesting and querying graph data
    using the openCypher query language.

    # [MCP_TOOL] ingest_entity → exposes as MCP tool for autonomous ingestion
    # [MCP_TOOL] query_graph   → exposes as MCP tool for read-only graph queries
    """

    def __init__(
        self,
        host: str = FALKORDB_HOST,
        port: int = FALKORDB_PORT,
        graph_name: str = GRAPH_NAME,
    ) -> None:
        self._graph_name = graph_name
        logger.info(
            "Connecting to FalkorDB",
            host=host,
            port=port,
            graph=graph_name,
        )
        db = FalkorDB(host=host, port=port)
        self._graph = db.select_graph(graph_name)

    # ── Schema Initialisation ─────────────────────────────────────────────

    def ensure_schema(self) -> None:
        """
        Create graph constraints and indices if they don't exist.

        In production, this would enforce uniqueness on Entity.id and
        create full-text search indices for hybrid retrieval.
        """
        logger.info("Ensuring graph schema constraints")
        try:
            # Create a uniqueness constraint on the Entity node id property
            self._graph.query(
                "CREATE CONSTRAINT ON (e:Entity) ASSERT e.id IS UNIQUE"
            )
        except Exception:
            # Constraint may already exist — safe to ignore
            pass

    # ── Ingestion ─────────────────────────────────────────────────────────

    def ingest_triple(self, triple: GraphTriple) -> None:
        """
        Ingest a subject-predicate-object triple into the knowledge graph.

        Uses MERGE to ensure idempotency — safe to call multiple times
        with the same data without creating duplicate nodes/edges.

        # [MCP_TOOL] → will become the `ingest_entity` MCP tool
        # Claude can call this autonomously to persist newly discovered
        # relationships during an agentic research workflow.

        Args:
            triple: A GraphTriple dataclass with subject, predicate, object.

        Example Cypher generated:
            MERGE (s:Entity {id: 'ACME_Corp'})
            MERGE (o:Entity {id: 'CustomerPII_Dataset_EU'})
            MERGE (s)-[r:OWNS]->(o)
        """
        cypher = (
            f"MERGE (s:Entity {{id: $subject}}) "
            f"MERGE (o:Entity {{id: $object}}) "
            f"MERGE (s)-[r:{triple.predicate}]->(o)"
        )
        params = {
            "subject": triple.subject,
            "object": triple.object,
        }

        logger.info(
            "Ingesting triple",
            subject=triple.subject,
            predicate=triple.predicate,
            object=triple.object,
        )

        self._graph.query(cypher, params)

    # ── Retrieval ─────────────────────────────────────────────────────────

    def retrieve_context(
        self,
        entity_filter: str | None = None,
        max_hops: int = 2,
        limit: int = 50,
    ) -> GraphContext:
        """
        Retrieve structured graph context via a Cypher traversal query.

        Performs a multi-hop neighbourhood traversal to capture rich
        relational context — a key advantage over flat vector retrieval
        which cannot natively represent multi-entity relationships.

        # [MCP_TOOL] → will become the `graph_query` MCP tool
        # Claude can call this to ground its reasoning in the live graph.

        Args:
            entity_filter:  Optional entity id to anchor the traversal.
            max_hops:       Maximum relationship hops to traverse (default: 2).
            limit:          Maximum number of triples to return.

        Returns:
            A GraphContext with structured triples and provenance metadata.
        """
        if entity_filter:
            cypher = (
                f"MATCH (s:Entity {{id: $entity}})-[r*1..{max_hops}]->(o:Entity) "
                f"RETURN s.id AS subject, type(r[0]) AS predicate, o.id AS object "
                f"LIMIT {limit}"
            )
            params: dict[str, Any] = {"entity": entity_filter}
        else:
            cypher = (
                f"MATCH (s:Entity)-[r]->(o:Entity) "
                f"RETURN s.id AS subject, type(r) AS predicate, o.id AS object "
                f"LIMIT {limit}"
            )
            params = {}

        logger.info("Executing Cypher retrieval", cypher=cypher)

        result = self._graph.query(cypher, params)
        triples = [
            {
                "subject": row[0],
                "predicate": row[1],
                "object": row[2],
            }
            for row in result.result_set
        ]

        # Count distinct entities and relationships for metadata
        entity_ids: set[str] = set()
        for t in triples:
            entity_ids.add(t["subject"])
            entity_ids.add(t["object"])

        return GraphContext(
            query=entity_filter or "(all entities)",
            triples=triples,
            entity_count=len(entity_ids),
            relationship_count=len(triples),
            cypher_used=cypher,
        )


# ---------------------------------------------------------------------------
# Prompt Builder
# ---------------------------------------------------------------------------


def build_graph_prompt(context: GraphContext, user_question: str) -> tuple[str, str]:
    """
    Construct a structured system prompt and user message for Claude.

    The system prompt establishes Claude's role as a Knowledge Graph analyst
    and instructs it to ONLY answer from the provided graph context —
    a critical constraint for GDPR-compliant, hallucination-resistant AI.

    Returns:
        A tuple of (system_prompt, user_message).
    """
    system_prompt = """You are a precise Knowledge Graph Analyst for a European enterprise AI platform.

Your role is to answer questions EXCLUSIVELY based on the structured graph context provided.

Rules:
1. ONLY use information present in the <knowledge_graph_context> block.
2. If the answer cannot be derived from the graph, say so explicitly.
3. Always cite the specific triples (by id) that support your answer.
4. Structure your response as: ANSWER → EVIDENCE → CONFIDENCE.
5. CONFIDENCE is one of: HIGH | MEDIUM | LOW, based on path completeness.

This strict grounding ensures GDPR compliance and full auditability."""

    user_message = f"""{context.to_xml_block()}

<user_question>{user_question}</user_question>

Please answer the question based solely on the knowledge graph context above."""

    return system_prompt, user_message


# ---------------------------------------------------------------------------
# Claude Invocation
# ---------------------------------------------------------------------------


def call_claude(
    system_prompt: str,
    user_message: str,
    model: str = CLAUDE_MODEL,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """
    Send a structured prompt to Claude and return the response text.

    Uses the official Anthropic Python SDK. The API key is read from
    the ANTHROPIC_API_KEY environment variable — never hardcoded.

    # [MCP_TOOL] → In the MCP architecture, Claude calls the graph tools
    # autonomously rather than being called with pre-fetched context.
    # This function will be replaced by the MCP tool-use loop in
    # src/mcp_server.py once the MCP server is implemented.

    Args:
        system_prompt: Grounding instructions for Claude.
        user_message:  The graph context + user question.
        model:         Claude model identifier.
        max_tokens:    Maximum output tokens.

    Returns:
        The text content of Claude's response.
    """
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    logger.info("Calling Claude", model=model, max_tokens=max_tokens)

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_message},
        ],
    )

    response_text: str = message.content[0].text

    logger.info(
        "Claude response received",
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        stop_reason=message.stop_reason,
    )

    return response_text


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------


def graph_rag_query(
    user_question: str,
    entity_filter: str | None = None,
    max_hops: int = 2,
) -> dict[str, Any]:
    """
    End-to-end Graph RAG pipeline: retrieve → prompt → answer.

    This is the primary entry point called by the FastAPI layer (src/api.py)
    and will eventually be the orchestrating MCP server function.

    # [MCP_TOOL] → The MCP server will wrap this as the primary
    # `graph_rag_query` tool exposed to Claude for autonomous use.

    Args:
        user_question:  The natural language query from the end user.
        entity_filter:  Optional entity to anchor the graph traversal.
        max_hops:       Maximum relationship hops for context retrieval.

    Returns:
        A dict with keys: answer, context_summary, cypher_used, provenance.
    """
    kg = KnowledgeGraphClient()

    # Step 1: Retrieve structured context from the knowledge graph
    context = kg.retrieve_context(
        entity_filter=entity_filter,
        max_hops=max_hops,
    )

    logger.info(
        "Graph context retrieved",
        triples=context.relationship_count,
        entities=context.entity_count,
    )

    # Step 2: Build structured prompt with XML-delimited context
    system_prompt, user_message = build_graph_prompt(context, user_question)

    # Step 3: Call Claude with the grounded prompt
    answer = call_claude(system_prompt, user_message)

    return {
        "answer": answer,
        "context_summary": {
            "entity_count": context.entity_count,
            "relationship_count": context.relationship_count,
            "entity_filter": entity_filter,
            "max_hops": max_hops,
        },
        "cypher_used": context.cypher_used,
        "provenance": context.triples,
    }


# ---------------------------------------------------------------------------
# Demo / Smoke Test
# ---------------------------------------------------------------------------


def _demo_ingest(kg: KnowledgeGraphClient) -> None:
    """
    Ingest a small set of sample triples to demonstrate the pipeline.

    Represents a simple GDPR-relevant data lineage graph:

        ACME_Corp ──[OWNS]──► CustomerPII_Dataset_EU
        CustomerPII_Dataset_EU ──[STORED_IN]──► Frankfurt_DC
        Frankfurt_DC ──[OPERATED_BY]──► ACME_Corp
        ACME_Corp ──[PROCESSES_UNDER]──► GDPR_Article_6
    """
    sample_triples = [
        GraphTriple("ACME_Corp", "OWNS", "CustomerPII_Dataset_EU"),
        GraphTriple("CustomerPII_Dataset_EU", "STORED_IN", "Frankfurt_DC"),
        GraphTriple("Frankfurt_DC", "OPERATED_BY", "ACME_Corp"),
        GraphTriple("ACME_Corp", "PROCESSES_UNDER", "GDPR_Article_6"),
        GraphTriple("CustomerPII_Dataset_EU", "CLASSIFIED_AS", "Sensitive_Personal_Data"),
    ]

    for triple in sample_triples:
        kg.ingest_triple(triple)


if __name__ == "__main__":
    """
    Standalone smoke test.
    Run inside the graph-rag Docker container:
        docker compose exec graph-rag python src/graph_rag_agent.py
    """
    logger.info("Starting Graph RAG smoke test")

    # Initialise client and schema
    kg = KnowledgeGraphClient()
    kg.ensure_schema()

    # Ingest sample data
    logger.info("Ingesting sample knowledge graph triples")
    _demo_ingest(kg)

    # Run a Graph RAG query
    result = graph_rag_query(
        user_question="Which entities own EU personal data and where is it stored?",
        entity_filter="ACME_Corp",
        max_hops=2,
    )

    print("\n" + "=" * 60)
    print("GRAPH RAG ANSWER")
    print("=" * 60)
    print(result["answer"])
    print("\n── Context Summary ──")
    print(json.dumps(result["context_summary"], indent=2))
    print("\n── Cypher Query Used ──")
    print(result["cypher_used"])
    print("=" * 60)

"""
MCP Server — Model Context Protocol Bindings (Work In Progress)
===============================================================
This module will expose the Graph RAG tools as an MCP server,
allowing Claude to autonomously query and update the knowledge
graph during agentic workflows — without any custom API glue.

MCP Tools to be implemented:
  - graph_query(cypher: str) → list[dict]
  - ingest_entity(subject, relation, object) → None
  - find_paths(source, target, max_hops) → list[dict]
  - get_entity_context(entity_id) → GraphContext

See: https://modelcontextprotocol.io/docs/concepts/tools

TODO: Implement using the official MCP Python SDK once available.
"""

# [PLACEHOLDER] MCP server implementation coming soon
# Expected dependencies:
#   mcp>=1.x.x  (add to requirements.txt when SDK stabilises)

raise NotImplementedError(
    "MCP server not yet implemented. "
    "Use the FastAPI layer (src/api.py) in the meantime."
)

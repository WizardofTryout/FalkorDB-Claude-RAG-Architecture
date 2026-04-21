# FalkorDB × Claude Graph RAG — GDPR Compliance Notes
# Architecture Decision Records and Compliance Mapping

## Data Flow Analysis

| Data Category | Stays On-Prem | Sent to Claude API |
|---|---|---|
| Raw documents | ✅ Never leaves FalkorDB | ❌ No |
| Entity relationships (triples) | ✅ Stored in FalkorDB | ✅ Structured subset only |
| User queries | Logged locally | ✅ Sent with context |
| Claude's responses | Logged locally | — |

## GDPR Article Mapping

- **Art. 5(1)(a) Lawfulness**: Claude is called with structured, minimal data
- **Art. 5(1)(c) Data minimisation**: Only relevant Cypher-extracted triples are sent
- **Art. 25 Privacy by Design**: FalkorDB is isolated in internal Docker network
- **Art. 32 Security**: mTLS recommended for production; secrets via env vars
- **Art. 30 Records of Processing**: Cypher queries logged for full audit trail

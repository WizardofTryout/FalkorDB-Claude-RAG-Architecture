-- FalkorDB Knowledge Graph — Initial Schema
-- Runs on first container start via /docker-entrypoint-initdb.d/
--
-- Creates the foundational node labels and relationship types
-- for the enterprise GDPR data lineage graph.
--
-- This is a placeholder. FalkorDB uses Cypher syntax.
-- Production schema management should use migration scripts.

-- Create sample seed data for development / smoke tests
MERGE (e:Entity {id: 'SEED_ENTITY', type: 'system', description: 'Schema initialisation sentinel'})
RETURN e.id AS initialised;

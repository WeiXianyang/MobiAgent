# Proactive Personal Memory System

## Design Position

This memory system is not a vector-database-first RAG module. It uses a local event timeline as the primary store, structured indexes for exact and range retrieval, a relation graph for causal and temporal links, memory cards for proactive service, and optional semantic recall for fuzzy queries.

## Layers

1. Raw Multimodal Store: screenshot, OCR, XML, text, CLI, and ADB evidence metadata.
2. Event Timeline: normalized user events with time, app, event type, task, state, entities, evidence, confidence, and privacy level.
3. Structured Index: SQLite indexes over time, app, event type, task, state, and privacy.
4. Relation Graph: `before`, `after`, `causes`, `refers_to`, `creates_todo`, and `resolves_todo` edges.
5. Profile and Todo Memory: compact memory cards derived from profile facts, todo candidates, and weekly summaries.
6. Vector Memory: optional semantic fallback used after structured search, not as the primary database.
7. Agent Search Planner: intent rules that choose which layers to query for weekly reports, todo service, task continuation, and general lookup.

## Lightweight Storage Structure

The optimized store keeps SQLite as the required local backend and avoids making embeddings the primary memory store. The core table is `events`; `raw_artifacts` stores evidence references; `relations` stores causal and temporal edges; `memory_cards` stores compact proactive-service summaries.

Derived indexes are deliberately small and rebuildable:

- `card_events(card_id, event_id)` maps cards to evidence events for time, app, task, state, and privacy filters.
- `relation_events(relation_id, event_id)` maps relation edges to source, target, and evidence events.
- `events_fts`, `cards_fts`, and `relations_fts` provide local text recall without a remote vector service.
- `schema_meta` stores the current format version. When the version changes, `ensure_initialized()` rebuilds derived indexes and FTS tables from canonical rows.

This layout is efficient for proactive agents because common decisions are structured: "what changed this week", "which open todo is stale", "which card links to this app event", or "why is this reminder relevant". These queries are answered by indexed SQLite filters and bounded relation traversal before optional semantic fallback.

## Retrieval Modes

`AgentMemoryQuery.include_explanation` defaults to `True` for research and debugging. Each returned hit can include `explanation_trace`, showing the query plan, structured filters, text match source, linked events, lifecycle adjustment, and final score.

Production or benchmark paths can set `include_explanation=False`. In that mode the store keeps the same ranking behavior, but skips trace construction and avoids materializing linked event sets that are only needed for explanations.

## Relation Text Index

Relation descriptions are often short Chinese phrases, and SQLite FTS tokenization does not always match arbitrary CJK substrings. The store therefore writes an expanded search string into `relations_fts` while keeping `relations.description` unchanged. Short CJK runs are expanded with contiguous substrings; long runs are bounded to keep storage growth acceptable for a lightweight local database.

The tradeoff is intentional: relation descriptions should stay concise. Very long unbroken CJK descriptions can increase the FTS row size, but canonical relation rows remain compact and the derived FTS table can be rebuilt from them.

## Benchmark

Use the storage benchmark to quantify write cost, query latency, and database size for a synthetic personal-memory workload:

```powershell
python -m runner.mobiagent.personal_memory.benchmark_storage --db .tmp\personal_memory_benchmark.db --events 1000 --cards 200 --relations 200
```

The benchmark reports `write_ms`, `event_query_ms`, `card_query_ms`, `relation_query_ms`, and `db_size_bytes`. It runs with `include_explanation=False` to measure the low-latency retrieval path.

## Verification Commands

```powershell
python -m unittest runner.mobiagent.personal_memory.test_personal_memory -v
python -m unittest runner.mobiagent.profile_pipeline.test_profile_pipeline -v
python -m runner.mobiagent.personal_memory.benchmark_storage --db .tmp\personal_memory_benchmark.db --events 100 --cards 20 --relations 20
```

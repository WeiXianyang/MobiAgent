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

## Verification Commands

```powershell
python -m unittest runner.mobiagent.personal_memory.test_personal_memory -v
python -m unittest runner.mobiagent.profile_pipeline.test_profile_pipeline -v
```

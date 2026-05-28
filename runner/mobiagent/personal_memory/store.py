from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Iterator

from runner.mobiagent.personal_memory.schemas import (
    AgentMemoryQuery,
    MemoryCard,
    MemoryHit,
    NormalizedEvent,
    RawArtifact,
    RelationEdge,
)

SCHEMA_VERSION = "3"
SCHEMA_VERSION_KEY = "personal_memory_schema_version"


class PersonalMemoryStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS raw_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    uri TEXT NOT NULL,
                    source TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    app TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    entities_json TEXT NOT NULL,
                    entities_text TEXT NOT NULL,
                    artifact_ids_json TEXT NOT NULL,
                    task_id TEXT,
                    state TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    privacy_level TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS relations (
                    relation_id TEXT PRIMARY KEY,
                    relation_type TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    target_event_id TEXT,
                    description TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_event_ids_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_cards (
                    card_id TEXT PRIMARY KEY,
                    card_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    event_ids_json TEXT NOT NULL,
                    relation_ids_json TEXT NOT NULL,
                    priority REAL NOT NULL,
                    status TEXT NOT NULL,
                    privacy_level TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT,
                    expires_at TEXT,
                    lifecycle_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS card_events (
                    card_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    PRIMARY KEY (card_id, event_id)
                );

                CREATE TABLE IF NOT EXISTS relation_events (
                    relation_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    PRIMARY KEY (relation_id, event_id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_event_time ON events(event_time);
                CREATE INDEX IF NOT EXISTS idx_events_app_time ON events(app, event_time);
                CREATE INDEX IF NOT EXISTS idx_events_event_type_time ON events(event_type, event_time);
                CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id);
                CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_event_id);
                CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_event_id);
                CREATE INDEX IF NOT EXISTS idx_cards_type_priority ON memory_cards(card_type, priority);
                CREATE INDEX IF NOT EXISTS idx_card_events_event ON card_events(event_id, card_id);
                CREATE INDEX IF NOT EXISTS idx_relation_events_event ON relation_events(event_id, relation_id);

                CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                    event_id UNINDEXED,
                    summary,
                    entities_text
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
                    card_id UNINDEXED,
                    title,
                    content
                );
                """
            )
            _ensure_column(conn, "memory_cards", "created_at", "TEXT")
            _ensure_column(conn, "memory_cards", "updated_at", "TEXT")
            _ensure_column(conn, "memory_cards", "expires_at", "TEXT")
            _ensure_column(conn, "memory_cards", "lifecycle_json", "TEXT NOT NULL DEFAULT '{}'")
            _backfill_card_events(conn)
            _backfill_relation_events(conn)
            _set_schema_version(conn, SCHEMA_VERSION)

    def ensure_initialized(self) -> None:
        if not self.db_path.exists():
            self.initialize()
            return

        with self._connect() as conn:
            version = _get_schema_version(conn)
        if version != SCHEMA_VERSION:
            self.initialize()

    def upsert_artifacts(self, artifacts: Iterable[RawArtifact]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO raw_artifacts (
                    artifact_id, kind, uri, source, captured_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    kind = excluded.kind,
                    uri = excluded.uri,
                    source = excluded.source,
                    captured_at = excluded.captured_at,
                    metadata_json = excluded.metadata_json
                """,
                [
                    (
                        artifact.artifact_id,
                        artifact.kind,
                        artifact.uri,
                        artifact.source,
                        artifact.captured_at,
                        _to_json(artifact.metadata),
                    )
                    for artifact in artifacts
                ],
            )

    def upsert_events(self, events: Iterable[NormalizedEvent]) -> None:
        event_rows = []
        fts_rows = []
        for event in events:
            entities_text = _flatten_text(event.entities)
            event_rows.append(
                (
                    event.event_id,
                    event.user_id,
                    event.event_time,
                    event.app,
                    event.package_name,
                    event.event_type,
                    event.action,
                    event.summary,
                    _to_json(event.entities),
                    entities_text,
                    _to_json(event.artifact_ids),
                    event.task_id,
                    event.state,
                    event.confidence,
                    event.privacy_level,
                )
            )
            fts_rows.append((event.event_id, event.summary, entities_text))

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO events (
                    event_id, user_id, event_time, app, package_name, event_type,
                    action, summary, entities_json, entities_text, artifact_ids_json,
                    task_id, state, confidence, privacy_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    event_time = excluded.event_time,
                    app = excluded.app,
                    package_name = excluded.package_name,
                    event_type = excluded.event_type,
                    action = excluded.action,
                    summary = excluded.summary,
                    entities_json = excluded.entities_json,
                    entities_text = excluded.entities_text,
                    artifact_ids_json = excluded.artifact_ids_json,
                    task_id = excluded.task_id,
                    state = excluded.state,
                    confidence = excluded.confidence,
                    privacy_level = excluded.privacy_level
                """,
                event_rows,
            )
            conn.executemany("DELETE FROM events_fts WHERE event_id = ?", [(row[0],) for row in fts_rows])
            conn.executemany(
                "INSERT INTO events_fts(event_id, summary, entities_text) VALUES (?, ?, ?)",
                fts_rows,
            )

    def upsert_relations(self, relations: Iterable[RelationEdge]) -> None:
        relations_list = list(relations)
        latest_relations = {relation.relation_id: relation for relation in relations_list}
        relation_rows = [
            (
                relation.relation_id,
                relation.relation_type,
                relation.source_event_id,
                relation.target_event_id,
                relation.description,
                relation.confidence,
                _to_json(relation.evidence_event_ids),
            )
            for relation in relations_list
        ]
        relation_event_rows = [
            (relation.relation_id, event_id)
            for relation in latest_relations.values()
            for event_id in _unique_relation_event_ids(relation)
        ]

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO relations (
                    relation_id, relation_type, source_event_id, target_event_id,
                    description, confidence, evidence_event_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(relation_id) DO UPDATE SET
                    relation_type = excluded.relation_type,
                    source_event_id = excluded.source_event_id,
                    target_event_id = excluded.target_event_id,
                    description = excluded.description,
                    confidence = excluded.confidence,
                    evidence_event_ids_json = excluded.evidence_event_ids_json
                """,
                relation_rows,
            )
            conn.executemany(
                "DELETE FROM relation_events WHERE relation_id = ?",
                [(relation.relation_id,) for relation in relations_list],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO relation_events(relation_id, event_id) VALUES (?, ?)",
                list(dict.fromkeys(relation_event_rows)),
            )

    def upsert_cards(self, cards: Iterable[MemoryCard]) -> None:
        cards_list = list(cards)
        latest_cards = {card.card_id: card for card in cards_list}
        card_rows = []
        fts_rows = []
        for card in cards_list:
            card_rows.append(
                (
                    card.card_id,
                    card.card_type,
                    card.title,
                    card.content,
                    _to_json(card.event_ids),
                    _to_json(card.relation_ids),
                    card.priority,
                    card.status,
                    card.privacy_level,
                    card.created_at,
                    card.updated_at,
                    card.expires_at,
                    _to_json(card.lifecycle),
                )
            )
            fts_rows.append((card.card_id, card.title, card.content))
        card_event_rows = [
            (card.card_id, event_id)
            for card in latest_cards.values()
            for event_id in _unique_event_ids(card.event_ids)
        ]

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO memory_cards (
                    card_id, card_type, title, content, event_ids_json,
                    relation_ids_json, priority, status, privacy_level,
                    created_at, updated_at, expires_at, lifecycle_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    card_type = excluded.card_type,
                    title = excluded.title,
                    content = excluded.content,
                    event_ids_json = excluded.event_ids_json,
                    relation_ids_json = excluded.relation_ids_json,
                    priority = excluded.priority,
                    status = excluded.status,
                    privacy_level = excluded.privacy_level,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at,
                    lifecycle_json = excluded.lifecycle_json
                """,
                card_rows,
            )
            conn.executemany("DELETE FROM cards_fts WHERE card_id = ?", [(row[0],) for row in fts_rows])
            conn.executemany(
                "INSERT INTO cards_fts(card_id, title, content) VALUES (?, ?, ?)",
                fts_rows,
            )
            conn.executemany(
                "DELETE FROM card_events WHERE card_id = ?",
                [(card.card_id,) for card in cards_list],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO card_events(card_id, event_id) VALUES (?, ?)",
                list(dict.fromkeys(card_event_rows)),
            )

    def search(self, query: AgentMemoryQuery) -> list[MemoryHit]:
        self.ensure_initialized()
        hits = self._search_once(query)
        if hits or not query.semantic_fallback:
            return hits
        return self._search_once(replace(query, text="", semantic_fallback=False))

    def _search_once(self, query: AgentMemoryQuery) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        with self._connect() as conn:
            if query.include_events:
                hits.extend(self._search_events(conn, query))
            if query.include_relations:
                hits.extend(self._search_relations(conn, query))
            if query.include_cards:
                hits.extend(self._search_cards(conn, query))

        hits.sort(key=lambda hit: (-hit.score, hit.layer, hit.item_id))
        return hits[: query.limit]

    def relations_for_event(self, event_id: str) -> list[RelationEdge]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT relation_id, relation_type, source_event_id, target_event_id,
                       description, confidence, evidence_event_ids_json
                FROM relations
                WHERE source_event_id = ? OR target_event_id = ?
                ORDER BY confidence DESC, relation_id
                """,
                (event_id, event_id),
            ).fetchall()
        return [
            RelationEdge(
                relation_id=row["relation_id"],
                relation_type=row["relation_type"],
                source_event_id=row["source_event_id"],
                target_event_id=row["target_event_id"],
                description=row["description"],
                confidence=row["confidence"],
                evidence_event_ids=json.loads(row["evidence_event_ids_json"]),
            )
            for row in rows
        ]

    def relation_neighborhood(self, event_id: str, max_depth: int = 1) -> list[RelationEdge]:
        seen_events = {event_id}
        frontier = {event_id}
        collected: dict[str, RelationEdge] = {}
        depth = 0
        while frontier and depth < max_depth:
            next_frontier: set[str] = set()
            for current_event_id in frontier:
                for relation in self.relations_for_event(current_event_id):
                    collected[relation.relation_id] = relation
                    for neighbor in (relation.source_event_id, relation.target_event_id):
                        if neighbor and neighbor not in seen_events:
                            seen_events.add(neighbor)
                            next_frontier.add(neighbor)
            frontier = next_frontier
            depth += 1
        return sorted(collected.values(), key=lambda relation: (-relation.confidence, relation.relation_id))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _search_events(self, conn: sqlite3.Connection, query: AgentMemoryQuery) -> list[MemoryHit]:
        where, params = _event_filters(query)
        sql = (
            "SELECT event_id, summary, entities_json, artifact_ids_json, task_id, confidence "
            "FROM events"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY event_time DESC, event_id"

        fts_ids = _matching_fts_ids(conn, "events_fts", "event_id", query.text)
        rows = conn.execute(sql, params).fetchall()
        hits = []
        require_text_match = bool(query.text) and not _has_event_structured_filters(query)
        for row in rows:
            score = _event_score(row, query.text, fts_ids)
            if require_text_match and score <= 0:
                continue
            if score <= 0:
                score = float(row["confidence"])
            hit_score = score
            hits.append(
                MemoryHit(
                    item_id=row["event_id"],
                    layer="event",
                    text=row["summary"],
                    score=hit_score,
                    event_ids=[row["event_id"]],
                    metadata={
                        "entities": json.loads(row["entities_json"]),
                        "artifact_ids": json.loads(row["artifact_ids_json"]),
                        "task_id": row["task_id"],
                        "confidence": row["confidence"],
                    },
                    explanation_trace=_event_trace(row, query, hit_score, fts_ids)
                    if query.include_explanation
                    else [],
                )
            )
        return hits

    def _search_relations(self, conn: sqlite3.Connection, query: AgentMemoryQuery) -> list[MemoryHit]:
        rows = conn.execute(
            """
            SELECT relation_id, relation_type, source_event_id, target_event_id,
                   description, confidence, evidence_event_ids_json
            FROM relations
            ORDER BY confidence DESC, relation_id
            """
        ).fetchall()
        linked_event_ids = _matching_event_ids(conn, query) if _has_linked_event_filters(query) else None
        require_text_match = bool(query.text) and linked_event_ids is None
        hits: list[MemoryHit] = []
        for row in rows:
            evidence_event_ids = json.loads(row["evidence_event_ids_json"])
            relation_event_ids = {
                row["source_event_id"],
                row["target_event_id"],
                *evidence_event_ids,
            }
            relation_event_ids.discard(None)
            if linked_event_ids is not None and not linked_event_ids.intersection(relation_event_ids):
                continue
            score = _relation_score(row, query.text)
            if require_text_match and score <= 0:
                continue
            if score <= 0:
                score = float(row["confidence"])
            hit_score = score
            hits.append(
                MemoryHit(
                    item_id=row["relation_id"],
                    layer="relation",
                    text=row["description"],
                    score=hit_score,
                    event_ids=evidence_event_ids,
                    relation_ids=[row["relation_id"]],
                    metadata={
                        "relation_type": row["relation_type"],
                        "source_event_id": row["source_event_id"],
                        "target_event_id": row["target_event_id"],
                        "confidence": row["confidence"],
                    },
                    explanation_trace=_relation_trace(
                        row,
                        query,
                        hit_score,
                        linked_event_ids,
                        relation_event_ids,
                        include_structured_filters=linked_event_ids is not None,
                    )
                    if query.include_explanation
                    else [],
                )
            )
        return hits

    def _search_cards(self, conn: sqlite3.Connection, query: AgentMemoryQuery) -> list[MemoryHit]:
        where, params = _card_filters(query)
        sql = (
            "SELECT card_id, title, content, event_ids_json, relation_ids_json, "
            "priority, card_type, status, privacy_level, created_at, updated_at, "
            "expires_at, lifecycle_json FROM memory_cards"
        )
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY priority DESC, card_id"

        fts_ids = _matching_fts_ids(conn, "cards_fts", "card_id", query.text)
        rows = conn.execute(sql, params).fetchall()
        hits = []
        linked_event_ids = _matching_event_ids(conn, query) if _has_linked_event_filters(query) else None
        require_text_match = bool(query.text) and not _has_card_structured_filters(query)
        for row in rows:
            event_ids = json.loads(row["event_ids_json"])
            if linked_event_ids is not None and not linked_event_ids.intersection(event_ids):
                continue
            score = _card_score(row, query.text, fts_ids)
            if require_text_match and score <= 0:
                continue
            if score <= 0:
                score = float(row["priority"])
            hit_score = score
            lifecycle = json.loads(row["lifecycle_json"])
            hits.append(
                MemoryHit(
                    item_id=row["card_id"],
                    layer="card",
                    text=f"{row['title']}\n{row['content']}",
                    score=hit_score,
                    event_ids=event_ids,
                    relation_ids=json.loads(row["relation_ids_json"]),
                    metadata={
                        "card_type": row["card_type"],
                        "status": row["status"],
                        "privacy_level": row["privacy_level"],
                        "priority": row["priority"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                        "expires_at": row["expires_at"],
                        "lifecycle": lifecycle,
                    },
                    explanation_trace=_card_trace(row, query, hit_score, fts_ids, linked_event_ids, event_ids, lifecycle)
                    if query.include_explanation
                    else [],
                )
            )
        return hits


def _event_trace(
    row: sqlite3.Row,
    query: AgentMemoryQuery,
    score: float,
    fts_ids: set[str],
) -> list[dict[str, Any]]:
    trace = _base_trace(query)
    text_score = _text_score(
        row["event_id"],
        f"{row['summary']} {_flatten_text(json.loads(row['entities_json']))}",
        query.text,
        fts_ids,
    )
    if query.text and text_score > 0:
        trace.append(
            {
                "stage": "text_match",
                "reason": "Event summary or entities matched query text",
                "details": {
                    "query": query.text,
                    "fts_match": row["event_id"] in fts_ids,
                    "summary_contains_query": query.text.lower() in row["summary"].lower(),
                },
            }
        )
    trace.append(
        {
            "stage": "score",
            "reason": "Event score uses text match score when available, otherwise event confidence",
            "details": {"score": score, "text_score": text_score, "confidence": float(row["confidence"])},
        }
    )
    return trace


def _card_trace(
    row: sqlite3.Row,
    query: AgentMemoryQuery,
    score: float,
    fts_ids: set[str],
    linked_event_ids: set[str] | None,
    event_ids: list[str],
    lifecycle: dict[str, Any],
) -> list[dict[str, Any]]:
    trace = _base_trace(query)
    if linked_event_ids is not None:
        trace.append(
            {
                "stage": "linked_event",
                "reason": "Card is linked to an event that matched structured event filters",
                "details": {"matched_event_ids": sorted(linked_event_ids.intersection(event_ids))},
            }
        )
    card_text = f"{row['title']} {row['content']}"
    text_score = _text_score(row["card_id"], card_text, query.text, fts_ids)
    if query.text and text_score > 0:
        trace.append(
            {
                "stage": "text_match",
                "reason": "Card title or content matched query text",
                "details": {
                    "query": query.text,
                    "fts_match": row["card_id"] in fts_ids,
                    "content_contains_query": query.text.lower() in card_text.lower(),
                },
            }
        )
    if lifecycle:
        trace.append(
            {
                "stage": "lifecycle",
                "reason": "Card priority includes lifecycle adjustments",
                "details": lifecycle,
            }
        )
    trace.append(
        {
            "stage": "score",
            "reason": "Card score uses text match score when available, otherwise lifecycle-adjusted priority",
            "details": {"score": score, "text_score": text_score, "priority": float(row["priority"])},
        }
    )
    return trace


def _relation_trace(
    row: sqlite3.Row,
    query: AgentMemoryQuery,
    score: float,
    linked_event_ids: set[str] | None,
    relation_event_ids: set[str],
    *,
    include_structured_filters: bool,
) -> list[dict[str, Any]]:
    trace = _base_trace(query, include_structured_filters=include_structured_filters)
    if linked_event_ids is not None:
        trace.append(
            {
                "stage": "linked_event",
                "reason": "Relation is connected to an event that matched structured event filters",
                "details": {"matched_event_ids": sorted(linked_event_ids.intersection(relation_event_ids))},
            }
        )
    text_score = _relation_score(row, query.text) if query.text else 0.0
    if query.text and text_score > 0:
        trace.append(
            {
                "stage": "text_match",
                "reason": "Relation type or description matched query text",
                "details": {"query": query.text, "relation_type": row["relation_type"]},
            }
        )
    trace.append(
        {
            "stage": "score",
            "reason": "Relation score uses text match score when available, otherwise relation confidence",
            "details": {"score": score, "text_score": text_score, "confidence": float(row["confidence"])},
        }
    )
    return trace


def _base_trace(
    query: AgentMemoryQuery,
    *,
    include_structured_filters: bool = True,
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = [
        {
            "stage": "query_plan",
            "reason": "Search executed with an AgentMemoryQuery plan",
            "details": {
                "intent": query.intent,
                "include_events": query.include_events,
                "include_cards": query.include_cards,
                "include_relations": query.include_relations,
                "semantic_fallback": query.semantic_fallback,
            },
        }
    ]
    filters = _structured_filter_details(query) if include_structured_filters else {}
    if filters:
        trace.append(
            {
                "stage": "structured_filter",
                "reason": "Structured filters narrowed candidate memories before scoring",
                "details": filters,
            }
        )
    return trace


def _structured_filter_details(query: AgentMemoryQuery) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if query.time_start:
        details["time_start"] = query.time_start
    if query.time_end:
        details["time_end"] = query.time_end
    if query.apps:
        details["apps"] = query.apps
    if query.event_types:
        details["event_types"] = query.event_types
    if query.task_ids:
        details["task_ids"] = query.task_ids
    if query.states:
        details["states"] = query.states
    if query.privacy_levels:
        details["privacy_levels"] = query.privacy_levels
    return details


def _event_filters(query: AgentMemoryQuery) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    _range_filter(where, params, "event_time", query.time_start, query.time_end)
    _in_filter(where, params, "app", query.apps)
    _in_filter(where, params, "event_type", query.event_types)
    _in_filter(where, params, "task_id", query.task_ids)
    _in_filter(where, params, "state", query.states)
    _in_filter(where, params, "privacy_level", query.privacy_levels)
    return where, params


def _card_filters(query: AgentMemoryQuery) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    _in_filter(where, params, "privacy_level", query.privacy_levels)
    return where, params


def _has_event_structured_filters(query: AgentMemoryQuery) -> bool:
    return any(
        [
            query.time_start,
            query.time_end,
            query.apps,
            query.event_types,
            query.task_ids,
            query.states,
            query.privacy_levels,
        ]
    )


def _has_card_structured_filters(query: AgentMemoryQuery) -> bool:
    return bool(query.privacy_levels) or _has_linked_event_filters(query)


def _has_linked_event_filters(query: AgentMemoryQuery) -> bool:
    return any(
        [
            query.time_start,
            query.time_end,
            query.apps,
            query.event_types,
            query.task_ids,
            query.states,
        ]
    )


def _matching_event_ids(conn: sqlite3.Connection, query: AgentMemoryQuery) -> set[str]:
    where, params = _event_filters(query)
    sql = "SELECT event_id FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    return {row["event_id"] for row in conn.execute(sql, params).fetchall()}


def _backfill_card_events(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT card_id, event_ids_json FROM memory_cards").fetchall()
    conn.execute("DELETE FROM card_events")
    conn.executemany(
        "INSERT OR IGNORE INTO card_events(card_id, event_id) VALUES (?, ?)",
        [
            (row["card_id"], event_id)
            for row in rows
            for event_id in _unique_event_ids(json.loads(row["event_ids_json"]))
        ],
    )


def _backfill_relation_events(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT relation_id, source_event_id, target_event_id, evidence_event_ids_json
        FROM relations
        """
    ).fetchall()
    conn.execute("DELETE FROM relation_events")
    conn.executemany(
        "INSERT OR IGNORE INTO relation_events(relation_id, event_id) VALUES (?, ?)",
        [
            (row["relation_id"], event_id)
            for row in rows
            for event_id in _unique_event_ids(
                [
                    row["source_event_id"],
                    row["target_event_id"],
                    *json.loads(row["evidence_event_ids_json"]),
                ]
            )
        ],
    )


def _unique_event_ids(event_ids: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(event_id for event_id in event_ids if event_id is not None))


def _unique_relation_event_ids(relation: RelationEdge) -> list[str]:
    return _unique_event_ids([relation.source_event_id, relation.target_event_id, *relation.evidence_event_ids])


def _range_filter(
    where: list[str],
    params: list[Any],
    column: str,
    start: str | None,
    end: str | None,
) -> None:
    if start is not None:
        where.append(f"{column} >= ?")
        params.append(start)
    if end is not None:
        where.append(f"{column} <= ?")
        params.append(end)


def _in_filter(where: list[str], params: list[Any], column: str, values: list[str]) -> None:
    if not values:
        return
    where.append(f"{column} IN ({', '.join('?' for _ in values)})")
    params.extend(values)


def _matching_fts_ids(
    conn: sqlite3.Connection,
    table: str,
    id_column: str,
    text: str,
) -> set[str]:
    if not text:
        return set()
    try:
        rows = conn.execute(
            f"SELECT {id_column} FROM {table} WHERE {table} MATCH ?",
            (text,),
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {row[id_column] for row in rows}


def _event_score(row: sqlite3.Row, text: str, fts_ids: set[str]) -> float:
    if not text:
        return float(row["confidence"])
    haystack = f"{row['summary']} {_flatten_text(json.loads(row['entities_json']))}"
    return _text_score(row["event_id"], haystack, text, fts_ids)


def _card_score(row: sqlite3.Row, text: str, fts_ids: set[str]) -> float:
    if not text:
        return float(row["priority"])
    haystack = f"{row['title']} {row['content']}"
    return _text_score(row["card_id"], haystack, text, fts_ids)


def _relation_score(row: sqlite3.Row, text: str) -> float:
    if not text:
        return float(row["confidence"])
    haystack = f"{row['description']} {row['relation_type']}"
    return _text_score(row["relation_id"], haystack, text, set())


def _text_score(item_id: str, haystack: str, needle: str, fts_ids: set[str]) -> float:
    score = 0.0
    if item_id in fts_ids:
        score += 1.0
    if needle and needle in haystack:
        score += 1.0
    return score


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(part) for item in value.items() for part in (_flatten_text(item[0]), _flatten_text(item[1])))
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _set_schema_version(conn: sqlite3.Connection, version: str) -> None:
    conn.execute(
        """
        INSERT INTO schema_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value
        """,
        (SCHEMA_VERSION_KEY, version),
    )


def _get_schema_version(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = ?",
            (SCHEMA_VERSION_KEY,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return str(row["value"])


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

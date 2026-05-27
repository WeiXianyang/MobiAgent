from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
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


class PersonalMemoryStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
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
                    privacy_level TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_event_time ON events(event_time);
                CREATE INDEX IF NOT EXISTS idx_events_app_time ON events(app, event_time);
                CREATE INDEX IF NOT EXISTS idx_events_event_type_time ON events(event_type, event_time);
                CREATE INDEX IF NOT EXISTS idx_events_task_id ON events(task_id);
                CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_event_id);
                CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_event_id);
                CREATE INDEX IF NOT EXISTS idx_cards_type_priority ON memory_cards(card_type, priority);

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
                [
                    (
                        relation.relation_id,
                        relation.relation_type,
                        relation.source_event_id,
                        relation.target_event_id,
                        relation.description,
                        relation.confidence,
                        _to_json(relation.evidence_event_ids),
                    )
                    for relation in relations
                ],
            )

    def upsert_cards(self, cards: Iterable[MemoryCard]) -> None:
        card_rows = []
        fts_rows = []
        for card in cards:
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
                )
            )
            fts_rows.append((card.card_id, card.title, card.content))

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO memory_cards (
                    card_id, card_type, title, content, event_ids_json,
                    relation_ids_json, priority, status, privacy_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    card_type = excluded.card_type,
                    title = excluded.title,
                    content = excluded.content,
                    event_ids_json = excluded.event_ids_json,
                    relation_ids_json = excluded.relation_ids_json,
                    priority = excluded.priority,
                    status = excluded.status,
                    privacy_level = excluded.privacy_level
                """,
                card_rows,
            )
            conn.executemany("DELETE FROM cards_fts WHERE card_id = ?", [(row[0],) for row in fts_rows])
            conn.executemany(
                "INSERT INTO cards_fts(card_id, title, content) VALUES (?, ?, ?)",
                fts_rows,
            )

    def search(self, query: AgentMemoryQuery) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        with self._connect() as conn:
            if query.include_events:
                hits.extend(self._search_events(conn, query))
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
        return sorted(collected.values(), key=lambda relation: relation.confidence, reverse=True)

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
            hits.append(
                MemoryHit(
                    item_id=row["event_id"],
                    layer="event",
                    text=row["summary"],
                    score=score,
                    event_ids=[row["event_id"]],
                    metadata={
                        "entities": json.loads(row["entities_json"]),
                        "artifact_ids": json.loads(row["artifact_ids_json"]),
                        "task_id": row["task_id"],
                        "confidence": row["confidence"],
                    },
                )
            )
        return hits

    def _search_cards(self, conn: sqlite3.Connection, query: AgentMemoryQuery) -> list[MemoryHit]:
        where, params = _card_filters(query)
        sql = (
            "SELECT card_id, title, content, event_ids_json, relation_ids_json, "
            "priority, card_type, status, privacy_level FROM memory_cards"
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
            hits.append(
                MemoryHit(
                    item_id=row["card_id"],
                    layer="card",
                    text=f"{row['title']}\n{row['content']}",
                    score=score,
                    event_ids=event_ids,
                    relation_ids=json.loads(row["relation_ids_json"]),
                    metadata={
                        "card_type": row["card_type"],
                        "status": row["status"],
                        "privacy_level": row["privacy_level"],
                        "priority": row["priority"],
                    },
                )
            )
        return hits


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

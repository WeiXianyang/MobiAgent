from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from runner.mobiagent.profile_pipeline.schemas import Relation, UserEvent

from .ingest import events_from_profile_events, relations_from_profile_relations
from .planner import plan_memory_query
from .schemas import AgentMemoryQuery, NormalizedEvent, RawArtifact, RelationEdge
from .store import PersonalMemoryStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and query local proactive personal memory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build a local memory database from normalized JSON artifacts.")
    build.add_argument("--db", required=True)
    build.add_argument("--events", required=True)
    build.add_argument("--artifacts")
    build.add_argument("--relations")

    search = subparsers.add_parser("search", help="Search memory with agent planner rules.")
    search.add_argument("--db", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        store = PersonalMemoryStore(Path(args.db))
        store.initialize()
        events, generated_artifacts = _load_events_and_artifacts(Path(args.events))
        if generated_artifacts:
            store.upsert_artifacts(generated_artifacts)
        store.upsert_events(events)
        if args.artifacts:
            store.upsert_artifacts(_load_artifacts(Path(args.artifacts)))
        if args.relations:
            store.upsert_relations(_load_relations(Path(args.relations)))
        print(json.dumps({"db": args.db, "status": "built"}, ensure_ascii=False))
        return 0

    if args.command == "search":
        store = PersonalMemoryStore(Path(args.db))
        query = _apply_limit(plan_memory_query(args.query), args.limit)
        hits = [hit.to_dict() for hit in store.search(query)]
        print(json.dumps({"query": args.query, "hits": hits}, ensure_ascii=False, indent=2))
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


def _load_events(path: Path) -> list[NormalizedEvent]:
    events, _ = _load_events_and_artifacts(path)
    return events


def _load_events_and_artifacts(path: Path) -> tuple[list[NormalizedEvent], list[RawArtifact]]:
    normalized_events: list[NormalizedEvent] = []
    profile_events: list[UserEvent] = []
    for record in _load_records(path):
        if _is_normalized_event(record):
            normalized_events.append(NormalizedEvent(**record))
        elif _is_profile_event(record):
            profile_events.append(UserEvent(**record))
        else:
            raise ValueError(f"Unsupported event record in {path}: {sorted(record)}")

    profile_normalized, profile_artifacts = events_from_profile_events(profile_events)
    return [*normalized_events, *profile_normalized], profile_artifacts


def _load_artifacts(path: Path) -> list[RawArtifact]:
    return [RawArtifact(**item) for item in _load_records(path)]


def _load_relations(path: Path) -> list[RelationEdge]:
    relations: list[Relation] = []
    for record in _load_records(path):
        if _is_relation_record(record):
            relations.append(Relation(**record))
        else:
            raise ValueError(f"Unsupported relation record in {path}: {sorted(record)}")

    return relations_from_profile_relations(relations)


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return []
    if text.lstrip().startswith("["):
        records = json.loads(text)
        if not isinstance(records, list):
            raise ValueError(f"Expected JSON array in {path}")
        return records
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _apply_limit(query: AgentMemoryQuery, limit: int | None) -> AgentMemoryQuery:
    if limit is None:
        return query
    return replace(query, limit=limit)


def _is_normalized_event(record: dict[str, Any]) -> bool:
    return "artifact_ids" in record and "action" in record


def _is_profile_event(record: dict[str, Any]) -> bool:
    return "evidence_paths" in record and "source_run" in record and "source_step" in record


def _is_relation_record(record: dict[str, Any]) -> bool:
    return {
        "relation_id",
        "relation_type",
        "source_event_id",
        "description",
        "evidence_event_ids",
        "confidence",
    }.issubset(record)


if __name__ == "__main__":
    raise SystemExit(main())

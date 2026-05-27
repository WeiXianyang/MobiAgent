from __future__ import annotations

import argparse
import json
from pathlib import Path

from .planner import plan_memory_query
from .schemas import NormalizedEvent, RawArtifact, RelationEdge
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
    search.add_argument("--limit", type=int, default=10)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        store = PersonalMemoryStore(Path(args.db))
        store.initialize()
        store.upsert_events(_load_events(Path(args.events)))
        if args.artifacts:
            store.upsert_artifacts(_load_artifacts(Path(args.artifacts)))
        if args.relations:
            store.upsert_relations(_load_relations(Path(args.relations)))
        print(json.dumps({"db": args.db, "status": "built"}, ensure_ascii=False))
        return 0

    if args.command == "search":
        store = PersonalMemoryStore(Path(args.db))
        query = plan_memory_query(args.query)
        query = type(query)(**{**query.__dict__, "limit": args.limit})
        hits = [hit.to_dict() for hit in store.search(query)]
        print(json.dumps({"query": args.query, "hits": hits}, ensure_ascii=False, indent=2))
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


def _load_events(path: Path) -> list[NormalizedEvent]:
    return [NormalizedEvent(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _load_artifacts(path: Path) -> list[RawArtifact]:
    return [RawArtifact(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _load_relations(path: Path) -> list[RelationEdge]:
    return [RelationEdge(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from statistics import mean
from typing import Any

from runner.mobiagent.personal_memory.schemas import (
    AgentMemoryQuery,
    MemoryCard,
    NormalizedEvent,
    RelationEdge,
)
from runner.mobiagent.personal_memory.store import PersonalMemoryStore


def run_benchmark(
    db_path: Path | str,
    event_count: int = 1000,
    card_count: int = 200,
    relation_count: int = 200,
    iterations: int = 5,
) -> dict[str, Any]:
    db = Path(db_path)
    if db.exists():
        db.unlink()

    store = PersonalMemoryStore(db)
    store.initialize()

    events = [_make_event(index) for index in range(event_count)]
    relations = [_make_relation(index, event_count) for index in range(relation_count)]
    cards = [_make_card(index, event_count, relation_count) for index in range(card_count)]

    write_started = time.perf_counter()
    store.upsert_events(events)
    store.upsert_relations(relations)
    store.upsert_cards(cards)
    write_ms = _elapsed_ms(write_started)

    event_query_ms = _mean_query_ms(
        store,
        AgentMemoryQuery(
            intent="benchmark_event_lookup",
            text="shopping materials",
            event_types=["shopping_browse"],
            include_events=True,
            include_relations=False,
            include_cards=False,
            limit=10,
            include_explanation=False,
        ),
        iterations,
    )
    card_query_ms = _mean_query_ms(
        store,
        AgentMemoryQuery(
            intent="benchmark_card_lookup",
            text="weekly material profile",
            include_events=False,
            include_relations=False,
            include_cards=True,
            limit=10,
            include_explanation=False,
        ),
        iterations,
    )
    relation_query_ms = _mean_query_ms(
        store,
        AgentMemoryQuery(
            intent="benchmark_relation_lookup",
            text="material purchase signal",
            include_events=False,
            include_relations=True,
            include_cards=False,
            limit=10,
            include_explanation=False,
        ),
        iterations,
    )

    return {
        "db_path": str(db),
        "event_count": event_count,
        "card_count": card_count,
        "relation_count": relation_count,
        "iterations": iterations,
        "write_ms": round(write_ms, 3),
        "event_query_ms": event_query_ms,
        "card_query_ms": card_query_ms,
        "relation_query_ms": relation_query_ms,
        "db_size_bytes": db.stat().st_size if db.exists() else 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark the lightweight personal memory SQLite layout.")
    parser.add_argument("--db", required=True, help="SQLite database path to create for the benchmark.")
    parser.add_argument("--events", type=int, default=1000, help="Number of synthetic events to write.")
    parser.add_argument("--cards", type=int, default=200, help="Number of synthetic memory cards to write.")
    parser.add_argument("--relations", type=int, default=200, help="Number of synthetic relation edges to write.")
    parser.add_argument("--iterations", type=int, default=5, help="Repeated search iterations used for average latency.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_benchmark(
        args.db,
        event_count=args.events,
        card_count=args.cards,
        relation_count=args.relations,
        iterations=args.iterations,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _make_event(index: int) -> NormalizedEvent:
    return NormalizedEvent(
        event_id=f"evt_bench_{index:06d}",
        user_id="local_user",
        event_time=f"2026-05-{(index % 28) + 1:02d}T{index % 24:02d}:00:00",
        app="Taobao" if index % 2 == 0 else "WeChat",
        package_name="com.taobao.taobao" if index % 2 == 0 else "com.tencent.mm",
        event_type="shopping_browse" if index % 2 == 0 else "chat_context",
        action="observe",
        summary=f"shopping materials browse signal {index} with material purchase signal",
        entities={
            "category": ["materials", "home"],
            "keyword": [f"bench-{index % 17}"],
        },
        artifact_ids=[f"raw_bench_{index:06d}"],
        task_id=f"task_{index % 32:02d}",
        state="observed",
        confidence=0.65 + (index % 30) / 100,
        privacy_level="derived",
    )


def _make_relation(index: int, event_count: int) -> RelationEdge:
    source_index = index % max(event_count, 1)
    target_index = (index * 7 + 3) % max(event_count, 1)
    return RelationEdge(
        relation_id=f"rel_bench_{index:06d}",
        relation_type="supports" if index % 2 == 0 else "updates",
        source_event_id=f"evt_bench_{source_index:06d}",
        target_event_id=f"evt_bench_{target_index:06d}",
        description=f"material purchase signal relation {index} links shopping evidence",
        confidence=0.6 + (index % 35) / 100,
        evidence_event_ids=[
            f"evt_bench_{source_index:06d}",
            f"evt_bench_{target_index:06d}",
        ],
    )


def _make_card(index: int, event_count: int, relation_count: int) -> MemoryCard:
    event_total = max(event_count, 1)
    relation_total = max(relation_count, 1)
    event_ids = [f"evt_bench_{(index + offset) % event_total:06d}" for offset in range(3)]
    relation_ids = [f"rel_bench_{(index + offset) % relation_total:06d}" for offset in range(2)]
    return MemoryCard(
        card_id=f"card_bench_{index:06d}",
        card_type="profile_summary" if index % 2 == 0 else "todo_hint",
        title=f"weekly material profile {index}",
        content="material profile keeps compact event and relation links for proactive retrieval",
        event_ids=event_ids,
        relation_ids=relation_ids,
        priority=0.5 + (index % 40) / 100,
        status="active",
        privacy_level="derived",
        created_at="2026-05-01T00:00:00",
        updated_at="2026-05-28T00:00:00",
        lifecycle={"source": "benchmark"},
    )


def _mean_query_ms(store: PersonalMemoryStore, query: AgentMemoryQuery, iterations: int) -> float:
    samples = []
    for _ in range(max(iterations, 1)):
        started = time.perf_counter()
        store.search(query)
        samples.append(_elapsed_ms(started))
    return round(mean(samples), 3)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .schemas import ProfileItem, Relation, TodoItem, UserEvent


DEFAULT_USER_ID = "default_user"


def default_env_file() -> Path:
    return Path(__file__).resolve().parents[3] / "runner" / "mobiagent" / ".env"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_mem0_config() -> dict[str, Any]:
    embedding_model = Path(require_env("EMBEDDING_MODEL")).expanduser().resolve()
    if not embedding_model.exists():
        raise RuntimeError(f"Embedding model path does not exist: {embedding_model}")

    return {
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": str(embedding_model),
            },
        },
        "vector_store": {
            "provider": "milvus",
            "config": {
                "collection_name": os.getenv("MEM0_COLLECTION_NAME", "mobiagent"),
                "embedding_model_dims": require_env("EMBEDDING_MODEL_DIMS"),
                "url": require_env("MILVUS_URL"),
                "db_name": "default",
                "token": "",
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": "gpt-4o-mini",
                "api_key": require_env("OPENAI_API_KEY"),
                "openai_base_url": require_env("OPENAI_BASE_URL"),
            },
        },
    }


def create_memory_client(env_file: Path | str | None = None) -> Any:
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
    load_dotenv(env_file or default_env_file())

    from mem0 import Memory

    return Memory.from_config(config_dict=build_mem0_config())


def _base_metadata(kind: str, item_id: str, source_event_ids: list[str]) -> dict[str, Any]:
    return {
        "kind": kind,
        "item_id": item_id,
        "source_event_ids": source_event_ids,
        "source": "task2_profile_pipeline",
        "timestamp": time.time(),
    }


def build_memory_records(
    events: list[UserEvent],
    relations: list[Relation],
    profile_items: list[ProfileItem],
    todos: list[TodoItem],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        metadata = _base_metadata("event", event.event_id, [event.event_id])
        metadata.update(
            {
                "event_type": event.event_type,
                "app": event.app,
                "package_name": event.package_name,
                "event_time": event.event_time,
                "privacy_level": event.privacy_level,
                "source_run": event.source_run,
            }
        )
        records.append(
            {
                "text": f"事件 {event.app} {event.event_type}: {event.summary}; 实体={event.entities}",
                "metadata": metadata,
            }
        )

    for relation in relations:
        metadata = _base_metadata("relation", relation.relation_id, relation.evidence_event_ids)
        metadata.update(
            {
                "relation_type": relation.relation_type,
                "source_event_id": relation.source_event_id,
                "target_event_id": relation.target_event_id,
                "confidence": relation.confidence,
            }
        )
        records.append({"text": f"关系 {relation.relation_type}: {relation.description}", "metadata": metadata})

    for item in profile_items:
        metadata = _base_metadata("profile", item.profile_id, item.evidence_event_ids)
        metadata.update(
            {
                "category": item.category,
                "confidence": item.confidence,
                "time_range": item.time_range,
                "service_eligible": item.service_eligible,
                "privacy_level": item.privacy_level,
            }
        )
        records.append({"text": f"用户画像 {item.category}: {item.claim}", "metadata": metadata})

    for todo in todos:
        metadata = _base_metadata("todo", todo.todo_id, todo.source_event_ids)
        metadata.update(
            {
                "priority": todo.priority,
                "due_time": todo.due_time,
                "status": todo.status,
            }
        )
        records.append({"text": f"待办 {todo.title}: {todo.reason}", "metadata": metadata})
    return records


def sync_memory_records(memory: Any, records: list[dict[str, Any]], user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    for record in records:
        result = memory.add(
            record["text"],
            user_id=user_id,
            infer=False,
            metadata={
                **record["metadata"],
                "user_id": user_id,
            },
        )
        inserted.append({"record": record, "result": result})
    return inserted


def normalize_memory_results(results: Any) -> list[dict[str, Any]]:
    if isinstance(results, dict) and "results" in results:
        normalized = results["results"]
    elif isinstance(results, list):
        normalized = results
    else:
        normalized = []
    return [item for item in normalized if isinstance(item, dict)]


def _tokens(text: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{1,4}", text.lower()))
    chars = {ch for ch in text if "\u4e00" <= ch <= "\u9fff"}
    return words | chars


def _dedupe_memories(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("id") or record.get("memory") or record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _rerank_memories(records: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    asks_for_todo = "待办" in query or "todo" in query.lower()

    def ranking_key(record: dict[str, Any]) -> tuple[int, float]:
        memory = str(record.get("memory") or record.get("text") or "")
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        overlap = len(query_tokens & _tokens(memory))
        if query and query in memory:
            overlap += 3
        if asks_for_todo and metadata.get("kind") == "todo":
            overlap += 10
        vector_score = record.get("score")
        score_value = float(vector_score) if isinstance(vector_score, (int, float)) else 999.0
        return (-overlap, score_value)

    return sorted(records, key=ranking_key)


def search_memories(memory: Any, query: str, user_id: str = DEFAULT_USER_ID, limit: int = 5) -> list[dict[str, Any]]:
    records = normalize_memory_results(memory.search(query, user_id=user_id, limit=limit))
    if "待办" in query or "todo" in query.lower():
        get_all = getattr(memory, "get_all", None)
        if get_all is not None:
            records.extend(normalize_memory_results(get_all(user_id=user_id, limit=100)))
    return _rerank_memories(_dedupe_memories(records), query)[:limit]

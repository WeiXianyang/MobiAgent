from __future__ import annotations

import re
from typing import Any

from .schemas import ProfileItem, Relation, TodoItem, UserEvent


def _tokens(text: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{1,4}", text.lower()))
    chars = {ch for ch in text if "\u4e00" <= ch <= "\u9fff"}
    return words | chars


def build_search_documents(
    events: list[UserEvent],
    relations: list[Relation],
    profile_items: list[ProfileItem],
    todos: list[TodoItem],
) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for event in events:
        docs.append(
            {
                "id": event.event_id,
                "kind": "event",
                "text": f"{event.app} {event.event_type} {event.summary} {event.entities}",
                "source_event_ids": [event.event_id],
            }
        )
    for relation in relations:
        docs.append(
            {
                "id": relation.relation_id,
                "kind": "relation",
                "text": f"{relation.relation_type} {relation.description}",
                "source_event_ids": relation.evidence_event_ids,
            }
        )
    for item in profile_items:
        docs.append(
            {
                "id": item.profile_id,
                "kind": "profile",
                "text": f"{item.category} {item.claim}",
                "source_event_ids": item.evidence_event_ids,
            }
        )
    for todo in todos:
        docs.append(
            {
                "id": todo.todo_id,
                "kind": "service_opportunity",
                "text": f"主动服务机会 画像驱动 购物 {todo.title} {todo.reason}",
                "source_event_ids": todo.source_event_ids,
            }
        )
    return docs


def search_documents(documents: list[dict[str, Any]], query: str, limit: int = 5) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    hits: list[dict[str, Any]] = []
    for doc in documents:
        text = str(doc.get("text", ""))
        score = len(query_tokens & _tokens(text))
        if query in text:
            score += 3
        if score:
            item = dict(doc)
            item["score"] = score
            hits.append(item)
    return sorted(hits, key=lambda item: (-item["score"], item["kind"], item["id"]))[:limit]

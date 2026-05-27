from __future__ import annotations

import hashlib

from runner.mobiagent.profile_pipeline.schemas import ProfileItem, TodoItem

from .schemas import MemoryCard, RelationEdge


PRIORITY_SCORE = {"high": 0.9, "medium": 0.65, "low": 0.4}


def build_memory_cards(
    profiles: list[ProfileItem],
    todos: list[TodoItem],
    relations: list[RelationEdge],
) -> list[MemoryCard]:
    relation_ids_by_event = _relation_ids_by_event(relations)
    cards: list[MemoryCard] = []
    for todo in sorted(todos, key=lambda item: PRIORITY_SCORE.get(item.priority, 0.5), reverse=True):
        cards.append(
            MemoryCard(
                card_id=f"card_{todo.todo_id}",
                card_type="todo",
                title=todo.title,
                content=f"{todo.reason} due_time={todo.due_time or 'none'}",
                event_ids=todo.source_event_ids,
                relation_ids=_linked_relations(todo.source_event_ids, relation_ids_by_event),
                priority=PRIORITY_SCORE.get(todo.priority, 0.5),
                status=todo.status,
                privacy_level="derived",
            )
        )
    for profile in sorted(profiles, key=lambda item: item.confidence, reverse=True):
        cards.append(
            MemoryCard(
                card_id=f"card_{profile.profile_id}",
                card_type="profile",
                title=profile.category,
                content=f"{profile.claim} time_range={profile.time_range}",
                event_ids=profile.evidence_event_ids,
                relation_ids=_linked_relations(profile.evidence_event_ids, relation_ids_by_event),
                priority=profile.confidence,
                status="active" if profile.service_eligible else "reference",
                privacy_level=profile.privacy_level,
            )
        )
    if profiles or todos:
        cards.append(_weekly_summary_card(profiles, todos, relations))
    return cards


def _relation_ids_by_event(relations: list[RelationEdge]) -> dict[str, list[str]]:
    by_event: dict[str, list[str]] = {}
    for relation in relations:
        for event_id in relation.evidence_event_ids:
            by_event.setdefault(event_id, []).append(relation.relation_id)
    return by_event


def _linked_relations(event_ids: list[str], relation_ids_by_event: dict[str, list[str]]) -> list[str]:
    relation_ids: list[str] = []
    for event_id in event_ids:
        relation_ids.extend(relation_ids_by_event.get(event_id, []))
    return sorted(set(relation_ids))


def _weekly_summary_card(
    profiles: list[ProfileItem],
    todos: list[TodoItem],
    relations: list[RelationEdge],
) -> MemoryCard:
    profile_titles = "、".join(profile.category for profile in profiles[:5]) or "无画像"
    todo_titles = "、".join(todo.title for todo in todos[:5]) or "无待办"
    raw_key = "|".join(profile.profile_id for profile in profiles) + "|" + "|".join(todo.todo_id for todo in todos)
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:8]
    event_ids = sorted({event_id for profile in profiles for event_id in profile.evidence_event_ids})
    event_ids.extend(event_id for todo in todos for event_id in todo.source_event_ids if event_id not in event_ids)
    return MemoryCard(
        card_id=f"card_weekly_{digest}",
        card_type="weekly_summary",
        title="过去一周画像摘要",
        content=f"画像主题：{profile_titles}。待办主题：{todo_titles}。关系数量：{len(relations)}。",
        event_ids=event_ids,
        relation_ids=[relation.relation_id for relation in relations],
        priority=0.7,
        status="active",
        privacy_level="derived",
    )

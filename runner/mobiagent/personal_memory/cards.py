from __future__ import annotations

from datetime import datetime
import hashlib

from runner.mobiagent.profile_pipeline.schemas import ProfileItem, TodoItem

from .lifecycle import (
    ProfileConflict,
    detect_profile_conflicts,
    lifecycle_adjusted_priority,
    reinforcement_for_profile,
    weakening_for_profile,
)
from .schemas import MemoryCard, RelationEdge


PRIORITY_SCORE = {"high": 0.9, "medium": 0.65, "low": 0.4}


def build_memory_cards(
    profiles: list[ProfileItem],
    todos: list[TodoItem],
    relations: list[RelationEdge],
    now: datetime | None = None,
) -> list[MemoryCard]:
    current = now or datetime.now()
    relation_ids_by_event = _relation_ids_by_event(relations)
    profile_records = [
        {
            "profile_id": profile.profile_id,
            "category": profile.category,
            "claim": profile.claim,
        }
        for profile in profiles
    ]
    conflicts = detect_profile_conflicts(profile_records)
    conflict_ids_by_profile = _conflict_ids_by_profile(conflicts)
    cards: list[MemoryCard] = []
    for todo in sorted(todos, key=lambda item: (-PRIORITY_SCORE.get(item.priority, 0.5), item.todo_id)):
        base_priority = PRIORITY_SCORE.get(todo.priority, 0.5)
        lifecycle = lifecycle_adjusted_priority(
            base_priority=base_priority,
            updated_at=todo.updated_at or todo.created_at,
            now=current,
            due_time=todo.due_time,
            status=todo.status,
        )
        cards.append(
            MemoryCard(
                card_id=f"card_todo_{todo.todo_id}",
                card_type="todo",
                title=todo.title,
                content=f"{todo.reason} due_time={todo.due_time or 'none'}",
                event_ids=sorted(set(todo.source_event_ids)),
                relation_ids=_linked_relations(todo.source_event_ids, relation_ids_by_event),
                priority=lifecycle.priority_after_lifecycle,
                status=todo.status,
                privacy_level="derived",
                created_at=todo.created_at,
                updated_at=todo.updated_at,
                expires_at=todo.due_time,
                lifecycle=lifecycle.to_metadata(),
            )
        )
    for profile in sorted(profiles, key=lambda item: (-item.confidence, item.profile_id)):
        reinforcement = reinforcement_for_profile(profile.profile_id, profile_records)
        weakening = weakening_for_profile(profile.profile_id, conflicts)
        lifecycle = lifecycle_adjusted_priority(
            base_priority=profile.confidence,
            updated_at=profile.updated_at or profile.created_at,
            now=current,
            reinforcement=reinforcement,
            weakening=weakening,
            status="active" if profile.service_eligible else "reference",
        )
        lifecycle_metadata = lifecycle.to_metadata()
        lifecycle_metadata["conflict_ids"] = conflict_ids_by_profile.get(profile.profile_id, [])
        lifecycle_metadata["conflicts"] = [
            conflict.to_metadata()
            for conflict in conflicts
            if conflict.profile_id == profile.profile_id or conflict.conflicting_profile_id == profile.profile_id
        ]
        cards.append(
            MemoryCard(
                card_id=f"card_profile_{profile.profile_id}",
                card_type="profile",
                title=profile.category,
                content=f"{profile.claim} time_range={profile.time_range}",
                event_ids=sorted(set(profile.evidence_event_ids)),
                relation_ids=_linked_relations(profile.evidence_event_ids, relation_ids_by_event),
                priority=lifecycle.priority_after_lifecycle,
                status="active" if profile.service_eligible else "reference",
                privacy_level=profile.privacy_level,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
                lifecycle=lifecycle_metadata,
            )
        )
    if profiles or todos:
        cards.append(_weekly_summary_card(profiles, todos, relations, current, conflicts))
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


def _conflict_ids_by_profile(conflicts: list[ProfileConflict]) -> dict[str, list[str]]:
    by_profile: dict[str, set[str]] = {}
    for conflict in conflicts:
        by_profile.setdefault(conflict.profile_id, set()).add(conflict.conflicting_profile_id)
        by_profile.setdefault(conflict.conflicting_profile_id, set()).add(conflict.profile_id)
    return {profile_id: sorted(conflict_ids) for profile_id, conflict_ids in by_profile.items()}


def _weekly_summary_card(
    profiles: list[ProfileItem],
    todos: list[TodoItem],
    relations: list[RelationEdge],
    now: datetime,
    conflicts: list[ProfileConflict],
) -> MemoryCard:
    canonical_profiles = sorted(profiles, key=lambda profile: profile.profile_id)
    canonical_todos = sorted(todos, key=lambda todo: todo.todo_id)
    profile_titles = "、".join(profile.category for profile in canonical_profiles[:5]) or "无画像"
    todo_titles = "、".join(todo.title for todo in canonical_todos[:5]) or "无待办"
    raw_key = (
        "|".join(profile.profile_id for profile in canonical_profiles)
        + "|"
        + "|".join(todo.todo_id for todo in canonical_todos)
    )
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:8]
    event_ids = sorted(
        {event_id for profile in profiles for event_id in profile.evidence_event_ids}
        | {event_id for todo in todos for event_id in todo.source_event_ids}
    )
    relation_ids = sorted({relation.relation_id for relation in relations})
    return MemoryCard(
        card_id=f"card_weekly_{digest}",
        card_type="weekly_summary",
        title="过去一周画像摘要",
        content=f"画像主题：{profile_titles}。待办主题：{todo_titles}。关系数量：{len(relations)}。",
        event_ids=event_ids,
        relation_ids=relation_ids,
        priority=0.7,
        status="active",
        privacy_level="derived",
        created_at=now.isoformat(timespec="seconds"),
        updated_at=now.isoformat(timespec="seconds"),
        lifecycle={
            "profile_count": len(profiles),
            "todo_count": len(todos),
            "conflict_count": len(conflicts),
            "expired_todo_count": sum(
                1
                for todo in todos
                if todo.due_time and datetime.fromisoformat(todo.due_time).replace(tzinfo=None) < now.replace(tzinfo=None) and todo.status == "open"
            ),
        },
    )

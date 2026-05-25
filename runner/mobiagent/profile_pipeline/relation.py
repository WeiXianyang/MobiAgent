from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime

from .schemas import Relation, UserEvent


def _relation_id(*parts: str) -> str:
    digest = hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"rel_{digest}"


def _date_part(event: UserEvent) -> str:
    if event.event_time == "unknown":
        return "unknown"
    return event.event_time.split("T", 1)[0]


def _sort_key(event: UserEvent) -> datetime:
    try:
        return datetime.fromisoformat(event.event_time)
    except ValueError:
        return datetime.min


def build_relations(events: list[UserEvent]) -> list[Relation]:
    relations: list[Relation] = []
    by_app: dict[str, list[UserEvent]] = defaultdict(list)
    by_day: dict[str, list[UserEvent]] = defaultdict(list)
    for event in events:
        by_app[event.app].append(event)
        by_day[_date_part(event)].append(event)

    for app_events in by_app.values():
        ordered = sorted(app_events, key=_sort_key)
        for earlier, later in zip(ordered, ordered[1:]):
            relations.append(
                Relation(
                    relation_id=_relation_id("before", earlier.event_id, later.event_id),
                    relation_type="before",
                    source_event_id=earlier.event_id,
                    target_event_id=later.event_id,
                    description=f"{earlier.app} event {earlier.source_step} happened before {later.source_step}.",
                    evidence_event_ids=[earlier.event_id, later.event_id],
                    confidence=0.9,
                )
            )
            relations.append(
                Relation(
                    relation_id=_relation_id("after", later.event_id, earlier.event_id),
                    relation_type="after",
                    source_event_id=later.event_id,
                    target_event_id=earlier.event_id,
                    description=f"{later.app} event {later.source_step} happened after {earlier.source_step}.",
                    evidence_event_ids=[earlier.event_id, later.event_id],
                    confidence=0.9,
                )
            )

    for day, day_events in by_day.items():
        if day == "unknown" or len(day_events) < 2:
            continue
        ordered = sorted(day_events, key=_sort_key)
        for index, source in enumerate(ordered):
            for target in ordered[index + 1 :]:
                relations.append(
                    Relation(
                        relation_id=_relation_id("same_day", source.event_id, target.event_id),
                        relation_type="same_day",
                        source_event_id=source.event_id,
                        target_event_id=target.event_id,
                        description=f"Both events occurred on {day}.",
                        evidence_event_ids=[source.event_id, target.event_id],
                        confidence=0.88,
                    )
                )

    for event in events:
        if event.event_type == "order_record":
            locations = event.entities.get("location_signal") or "unknown"
            relations.append(
                Relation(
                    relation_id=_relation_id("spatial", event.event_id),
                    relation_type="spatial",
                    source_event_id=event.event_id,
                    target_event_id=None,
                    description=f"Location evidence for this order record is {locations}.",
                    evidence_event_ids=[event.event_id],
                    confidence=0.55 if locations == "unknown" else 0.75,
                )
            )
        if event.event_type == "content_history_state" and event.entities.get("history_status") == "empty":
            relations.append(
                Relation(
                    relation_id=_relation_id("behavior_causal", event.event_id),
                    relation_type="behavior_causal",
                    source_event_id=event.event_id,
                    target_event_id=None,
                    description="Empty browsing history prevents a reliable content-interest inference.",
                    evidence_event_ids=[event.event_id],
                    confidence=0.8,
                )
            )
    return relations


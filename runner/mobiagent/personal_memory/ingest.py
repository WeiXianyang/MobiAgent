from __future__ import annotations

from runner.mobiagent.profile_pipeline.schemas import Relation, UserEvent

from .schemas import NormalizedEvent, RawArtifact, RelationEdge


def events_from_profile_events(events: list[UserEvent]) -> tuple[list[NormalizedEvent], list[RawArtifact]]:
    normalized: list[NormalizedEvent] = []
    artifacts: list[RawArtifact] = []
    for event in events:
        artifact_ids: list[str] = []
        for index, path in enumerate(event.evidence_paths):
            artifact_id = f"raw_{event.event_id}_{index}"
            artifact_ids.append(artifact_id)
            artifacts.append(
                RawArtifact(
                    artifact_id=artifact_id,
                    kind=_artifact_kind(path),
                    uri=path,
                    source="profile_pipeline",
                    captured_at=event.event_time,
                    metadata={
                        "source_run": event.source_run,
                        "source_step": event.source_step,
                        "app": event.app,
                        "package_name": event.package_name,
                    },
                )
            )
        normalized.append(
            NormalizedEvent(
                event_id=event.event_id,
                user_id=event.user_id,
                event_time=event.event_time,
                app=event.app,
                package_name=event.package_name,
                event_type=event.event_type,
                action="observe",
                summary=event.summary,
                entities=event.entities,
                artifact_ids=artifact_ids,
                task_id=event.source_run,
                state="observed",
                confidence=event.confidence,
                privacy_level=event.privacy_level,
            )
        )
    return normalized, artifacts


def relations_from_profile_relations(relations: list[Relation]) -> list[RelationEdge]:
    return [
        RelationEdge(
            relation_id=relation.relation_id,
            relation_type=relation.relation_type,
            source_event_id=relation.source_event_id,
            target_event_id=relation.target_event_id,
            description=relation.description,
            confidence=relation.confidence,
            evidence_event_ids=relation.evidence_event_ids,
        )
        for relation in relations
    ]


def _artifact_kind(path: str) -> str:
    lower = path.lower()
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return "screenshot"
    if ".json" in lower:
        return "json"
    if ".md" in lower or ".txt" in lower:
        return "text"
    return "reference"

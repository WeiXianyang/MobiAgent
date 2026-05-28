from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawArtifact:
    artifact_id: str
    kind: str
    uri: str
    source: str
    captured_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedEvent:
    event_id: str
    user_id: str
    event_time: str
    app: str
    package_name: str
    event_type: str
    action: str
    summary: str
    entities: dict[str, Any]
    artifact_ids: list[str]
    task_id: str | None
    state: str
    confidence: float
    privacy_level: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RelationEdge:
    relation_id: str
    relation_type: str
    source_event_id: str
    target_event_id: str | None
    description: str
    confidence: float
    evidence_event_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryCard:
    card_id: str
    card_type: str
    title: str
    content: str
    event_ids: list[str]
    relation_ids: list[str]
    priority: float
    status: str
    privacy_level: str
    created_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    lifecycle: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentMemoryQuery:
    intent: str
    text: str
    time_start: str | None = None
    time_end: str | None = None
    apps: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    privacy_levels: list[str] = field(default_factory=list)
    include_events: bool = True
    include_relations: bool = False
    include_cards: bool = True
    semantic_fallback: bool = False
    limit: int = 10
    include_explanation: bool = True


@dataclass(frozen=True)
class MemoryHit:
    item_id: str
    layer: str
    text: str
    score: float
    event_ids: list[str] = field(default_factory=list)
    relation_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    explanation_trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    kind: str
    step_id: str | None = None


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    run_dir: Path
    summary_path: Path
    workflow_file: str
    status: str
    app_name: str
    package_name: str
    daily_log_paths: list[Path] = field(default_factory=list)
    screenshot_paths: list[Path] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UserEvent:
    event_id: str
    user_id: str
    app: str
    package_name: str
    event_time: str
    source_run: str
    source_step: str
    evidence_paths: list[str]
    event_type: str
    summary: str
    entities: dict[str, Any]
    confidence: float
    privacy_level: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Relation:
    relation_id: str
    relation_type: str
    source_event_id: str
    target_event_id: str | None
    description: str
    evidence_event_ids: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileItem:
    profile_id: str
    category: str
    claim: str
    evidence_event_ids: list[str]
    confidence: float
    time_range: str
    service_eligible: bool
    privacy_level: str = "derived"
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TodoItem:
    todo_id: str
    title: str
    reason: str
    source_event_ids: list[str]
    priority: str
    due_time: str | None
    status: str
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def to_dict_list(items: list[Any]) -> list[dict[str, Any]]:
    return [item.to_dict() if hasattr(item, "to_dict") else asdict(item) for item in items]


@dataclass(frozen=True)
class TaskCompletionResult:
    original_task: str
    completed_task: str
    evidence_event_ids: list[str]
    source_profile_ids: list[str]
    source_opportunity_ids: list[str]
    confidence: float
    requires_user_confirmation: bool
    privacy_level: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ServiceOpportunityExecutionPlan:
    opportunity_id: str
    title: str
    workflow_path: str
    task_description: str
    evidence_event_ids: list[str]
    source_profile_ids: list[str]
    confidence: float
    requires_user_confirmation: bool
    service_ip: str
    decider_port: int
    grounder_port: int
    planner_port: int
    model_name: str
    device: str
    model_base_url: str | None = None
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ServiceOpportunityExecutionResult:
    opportunity_id: str
    workflow_path: str
    status: str
    command: list[str]
    run_summary_path: str | None = None
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScheduledTodo:
    scheduled_todo_id: str
    title: str
    original_instruction: str
    due_at: str
    workflow_path: str
    task_description: str
    status: str
    requires_user_confirmation: bool
    model_name: str
    model_base_url: str | None = None
    device: str = "Android"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScheduledTodoResult:
    scheduled_todo_id: str
    workflow_path: str
    status: str
    due_at: str
    command: list[str]
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DoctorResult:
    ok: bool
    service_ip: str
    model_port: int
    model_name: str
    checks: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WeeklyProfileReport:
    title: str
    days: int
    end_date: str
    event_count: int
    profile_count: int
    scheduled_todo_count: int
    markdown: str
    evidence_event_ids: list[str]
    proactive_items: list[str]
    scheduled_result_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PresentationOutline:
    title: str
    slides: list[dict[str, Any]]
    markdown: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlidevExportResult:
    deck_path: str
    pptx_path: str
    command_path: str
    status: str
    command: list[str]
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImagePromptBundle:
    prompts: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

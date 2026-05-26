from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runner.mobiagent.profile_pipeline.search import search_documents


CORE_FILES = ("events.jsonl", "relations.jsonl", "profile.json", "service_opportunities.json", "search_index.json")


def default_task2_artifacts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "profile_pipeline" / "artifacts"


def default_artifacts_dir() -> Path:
    return Path(__file__).resolve().parent / "artifacts"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@dataclass
class ProactiveStore:
    artifacts_dir: Path = field(default_factory=default_task2_artifacts_dir)
    events: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)
    profiles: list[dict[str, Any]] = field(default_factory=list)
    service_opportunities: list[dict[str, Any]] = field(default_factory=list)
    search_index: list[dict[str, Any]] = field(default_factory=list)
    rag_sync: dict[str, Any] | None = None

    def load(self) -> "ProactiveStore":
        missing = [name for name in CORE_FILES if not (self.artifacts_dir / name).exists()]
        if missing:
            raise FileNotFoundError(
                f"Missing task2 artifacts: {', '.join(missing)}. "
                "Run: python -m runner.mobiagent.profile_pipeline.cli build-profile"
            )
        self.events = _read_jsonl(self.artifacts_dir / "events.jsonl")
        self.relations = _read_jsonl(self.artifacts_dir / "relations.jsonl")
        self.profiles = json.loads((self.artifacts_dir / "profile.json").read_text(encoding="utf-8"))
        self.service_opportunities = json.loads(
            (self.artifacts_dir / "service_opportunities.json").read_text(encoding="utf-8")
        )
        self.search_index = json.loads((self.artifacts_dir / "search_index.json").read_text(encoding="utf-8"))
        rag_path = self.artifacts_dir / "rag_sync.json"
        self.rag_sync = json.loads(rag_path.read_text(encoding="utf-8")) if rag_path.exists() else None
        return self

    def search_local(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return search_documents(self.search_index, query, limit=limit)

    def profile_by_id(self, profile_id: str) -> dict[str, Any] | None:
        return next((item for item in self.profiles if item.get("profile_id") == profile_id), None)

    def event_by_id(self, event_id: str) -> dict[str, Any] | None:
        return next((item for item in self.events if item.get("event_id") == event_id), None)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .schemas import AgentMemoryQuery


DEFAULT_MULTIMODAL_ARTIFACT_KINDS = ("screenshot", "ui_tree", "ocr", "action_trace", "json")


@dataclass(frozen=True)
class HybridSearchStage:
    name: str
    purpose: str
    backend: str
    trigger: str
    inputs: dict[str, Any] = field(default_factory=dict)
    output: str = "candidate_hits"
    cost: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DisclosureLayer:
    level: str
    name: str
    contents: list[str]
    opens_when: str
    cost: str
    stage_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HybridSearchPlan:
    architecture: str
    backend_role: str
    query: AgentMemoryQuery
    stages: list[HybridSearchStage]
    disclosure_layers: list[DisclosureLayer]
    multimodal_artifact_kinds: list[str]
    min_structured_hits: int
    vector_backend: str

    def should_call_embedding(self, structured_hit_count: int) -> bool:
        return self.query.semantic_fallback and structured_hit_count < self.min_structured_hits

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture": self.architecture,
            "backend_role": self.backend_role,
            "query": asdict(self.query),
            "stages": [stage.to_dict() for stage in self.stages],
            "disclosure_layers": [layer.to_dict() for layer in self.disclosure_layers],
            "multimodal_artifact_kinds": self.multimodal_artifact_kinds,
            "min_structured_hits": self.min_structured_hits,
            "vector_backend": self.vector_backend,
            "embedding_policy": {
                "default": "defer",
                "trigger": "fallback_if_structured_low_confidence",
                "reason": "Range, app, state, relation, card, and evidence stages run before any embedding call.",
            },
        }


def build_hybrid_search_plan(
    query: AgentMemoryQuery,
    *,
    vector_backend: str = "milvus",
    multimodal_artifact_kinds: list[str] | tuple[str, ...] | None = None,
    min_structured_hits: int = 3,
) -> HybridSearchPlan:
    artifact_kinds = list(multimodal_artifact_kinds or DEFAULT_MULTIMODAL_ARTIFACT_KINDS)
    stages: list[HybridSearchStage] = []
    stages.append(_scalar_filter_stage(query))
    if query.text:
        stages.append(_fts_stage(query))
    if query.include_relations or query.include_cards:
        stages.append(_relation_card_stage(query))
    stages.append(_multimodal_evidence_stage(artifact_kinds))
    if query.semantic_fallback:
        stages.append(_vector_recall_stage(vector_backend, min_structured_hits))
    stages.append(_rerank_stage(query))
    return HybridSearchPlan(
        architecture="pml_hybrid_agent_search",
        backend_role=_backend_role(vector_backend),
        query=query,
        stages=stages,
        disclosure_layers=_disclosure_layers(vector_backend, artifact_kinds, min_structured_hits),
        multimodal_artifact_kinds=artifact_kinds,
        min_structured_hits=min_structured_hits,
        vector_backend=vector_backend,
    )


def _backend_role(vector_backend: str) -> str:
    if vector_backend == "milvus":
        return "milvus_optional_hybrid_index"
    return f"{vector_backend}_optional_hybrid_index"


def _disclosure_layers(
    vector_backend: str,
    artifact_kinds: list[str],
    min_structured_hits: int,
) -> list[DisclosureLayer]:
    return [
        DisclosureLayer(
            level="L0",
            name="index_filter",
            contents=["event_time", "app", "event_type", "task_id", "state", "privacy_level"],
            opens_when="always",
            cost="local_scalar_index",
            stage_names=["scalar_filter"],
        ),
        DisclosureLayer(
            level="L1",
            name="memory_brief",
            contents=["event.summary", "entities_text", "card.title", "card.content"],
            opens_when="query_text_present_or_card_lookup",
            cost="local_fts_and_cards",
            stage_names=["fts_text_match"],
        ),
        DisclosureLayer(
            level="L2",
            name="relation_context",
            contents=["RelationEdge", "card_events", "relation_events"],
            opens_when="relations_or_cards_requested",
            cost="local_join",
            stage_names=["relation_card_expansion"],
        ),
        DisclosureLayer(
            level="L3",
            name="multimodal_evidence",
            contents=artifact_kinds,
            opens_when="candidate_hits_available",
            cost="local_metadata",
            stage_names=["multimodal_evidence_lookup"],
        ),
        DisclosureLayer(
            level="L4",
            name="semantic_recall",
            contents=[f"{vector_backend} scalar_vector_recall", "cached_embeddings", "multimodal_vectors"],
            opens_when=f"structured_hit_count < {min_structured_hits}",
            cost="embedding_if_cache_miss",
            stage_names=["vector_recall"],
        ),
        DisclosureLayer(
            level="L5",
            name="raw_evidence",
            contents=["raw_screenshot", "full_ocr", "full_ui_tree", "full_action_log"],
            opens_when="agent_requests_evidence_or_trace_confidence_low",
            cost="raw_artifact_read",
            stage_names=["rerank_and_trace"],
        ),
    ]


def _scalar_filter_stage(query: AgentMemoryQuery) -> HybridSearchStage:
    return HybridSearchStage(
        name="scalar_filter",
        purpose="Apply hard Agent Search constraints before ranking.",
        backend="sqlite_or_milvus_scalar",
        trigger="always",
        inputs={
            "time_start": query.time_start,
            "time_end": query.time_end,
            "apps": query.apps,
            "event_types": query.event_types,
            "task_ids": query.task_ids,
            "states": query.states,
            "privacy_levels": query.privacy_levels,
        },
        output="structured_candidates",
        cost="local_index",
    )


def _fts_stage(query: AgentMemoryQuery) -> HybridSearchStage:
    return HybridSearchStage(
        name="fts_text_match",
        purpose="Use local lexical lookup for exact terms and short CJK fragments.",
        backend="sqlite_fts",
        trigger="query_text_present",
        inputs={"text": query.text},
        output="lexical_candidates",
        cost="local_index",
    )


def _relation_card_stage(query: AgentMemoryQuery) -> HybridSearchStage:
    return HybridSearchStage(
        name="relation_card_expansion",
        purpose="Expand event hits through relation edges and lifecycle-aware memory cards.",
        backend="pml_relation_graph",
        trigger="relations_or_cards_requested",
        inputs={"include_relations": query.include_relations, "include_cards": query.include_cards},
        output="agent_memory_candidates",
        cost="local_join",
    )


def _multimodal_evidence_stage(artifact_kinds: list[str]) -> HybridSearchStage:
    return HybridSearchStage(
        name="multimodal_evidence_lookup",
        purpose="Attach screenshot, UI tree, OCR, action trace, and JSON evidence references without flattening them into text only.",
        backend="pml_artifact_index",
        trigger="candidate_hits_available",
        inputs={"artifact_kinds": artifact_kinds},
        output="evidence_bound_candidates",
        cost="local_metadata",
    )


def _vector_recall_stage(vector_backend: str, min_structured_hits: int) -> HybridSearchStage:
    return HybridSearchStage(
        name="vector_recall",
        purpose="Recall open semantic or multimodal neighbors only when structured search is sparse.",
        backend=f"{vector_backend}_scalar_vector",
        trigger="fallback_if_structured_low_confidence",
        inputs={"min_structured_hits": min_structured_hits},
        output="semantic_candidates",
        cost="embedding_if_cache_miss",
    )


def _rerank_stage(query: AgentMemoryQuery) -> HybridSearchStage:
    return HybridSearchStage(
        name="rerank_and_trace",
        purpose="Merge candidates, enforce limits, and expose an explanation path for the agent.",
        backend="pml_agent_search",
        trigger="always",
        inputs={"limit": query.limit, "include_explanation": query.include_explanation},
        output="ranked_memory_hits",
        cost="local_scoring",
    )

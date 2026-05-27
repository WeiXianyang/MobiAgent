from __future__ import annotations

from collections import Counter
import math
import re

from .schemas import MemoryHit


class LexicalSemanticMemory:
    def __init__(self) -> None:
        self._items: list[MemoryHit] = []
        self._vectors: dict[str, Counter[str]] = {}

    def index(self, hits: list[MemoryHit]) -> None:
        self._items = list(hits)
        self._vectors = {hit.item_id: _token_counts(hit.text) for hit in hits}

    def search(self, text: str, limit: int = 5) -> list[MemoryHit]:
        query_vector = _token_counts(text)
        ranked: list[MemoryHit] = []
        for hit in self._items:
            score = _cosine(query_vector, self._vectors[hit.item_id])
            if score <= 0:
                continue
            metadata = dict(hit.metadata)
            metadata["semantic_backend"] = "lexical"
            ranked.append(
                MemoryHit(
                    item_id=hit.item_id,
                    layer=hit.layer,
                    text=hit.text,
                    score=hit.score + score,
                    event_ids=hit.event_ids,
                    relation_ids=hit.relation_ids,
                    metadata=metadata,
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:limit]


def _token_counts(text: str) -> Counter[str]:
    parts = [part for part in re.split(r"[\W_]+", text, flags=re.UNICODE) if part]
    chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    return Counter(parts + chars)


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    dot = sum(left[key] * right[key] for key in shared)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)

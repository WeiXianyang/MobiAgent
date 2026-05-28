from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any


@dataclass(frozen=True)
class DecayedConfidence:
    original_confidence: float
    adjusted_confidence: float
    decay_factor: float
    days_since_update: float


@dataclass(frozen=True)
class LifecyclePriority:
    priority_before_lifecycle: float
    priority_after_lifecycle: float
    decay_factor: float
    days_since_update: float
    reinforcement: float
    weakening: float
    expired: bool

    def to_metadata(self) -> dict[str, Any]:
        return {
            "priority_before_lifecycle": self.priority_before_lifecycle,
            "priority_after_lifecycle": self.priority_after_lifecycle,
            "decay_factor": self.decay_factor,
            "days_since_update": self.days_since_update,
            "reinforcement": self.reinforcement,
            "weakening": self.weakening,
            "expired": self.expired,
        }


@dataclass(frozen=True)
class ProfileConflict:
    profile_id: str
    conflicting_profile_id: str
    conflict_type: str
    reason: str

    def to_metadata(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "conflicting_profile_id": self.conflicting_profile_id,
            "conflict_type": self.conflict_type,
            "reason": self.reason,
        }


def apply_confidence_decay(
    confidence: float,
    updated_at: str | None,
    *,
    now: datetime,
    half_life_days: float = 30.0,
) -> DecayedConfidence:
    days = _days_since(updated_at, now)
    decay_factor = _decay_factor(days, half_life_days)
    adjusted = _clamp(confidence * decay_factor)
    return DecayedConfidence(
        original_confidence=confidence,
        adjusted_confidence=adjusted,
        decay_factor=decay_factor,
        days_since_update=days,
    )


def lifecycle_adjusted_priority(
    base_priority: float,
    updated_at: str | None,
    *,
    now: datetime,
    half_life_days: float = 30.0,
    reinforcement: float = 0.0,
    weakening: float = 0.0,
    due_time: str | None = None,
    status: str = "active",
) -> LifecyclePriority:
    decay = apply_confidence_decay(base_priority, updated_at, now=now, half_life_days=half_life_days)
    expired = _is_expired(due_time, status, now)
    expired_penalty = 0.35 if expired else 0.0
    adjusted = decay.adjusted_confidence + reinforcement - weakening - expired_penalty
    return LifecyclePriority(
        priority_before_lifecycle=base_priority,
        priority_after_lifecycle=_clamp(adjusted),
        decay_factor=decay.decay_factor,
        days_since_update=decay.days_since_update,
        reinforcement=reinforcement,
        weakening=weakening + expired_penalty,
        expired=expired,
    )


def detect_profile_conflicts(records: list[dict[str, Any]]) -> list[ProfileConflict]:
    conflicts: list[ProfileConflict] = []
    for left_index, left in enumerate(records):
        for right in records[left_index + 1 :]:
            conflict = _food_conflict(left, right)
            if conflict is not None:
                conflicts.append(conflict)
    return conflicts


def reinforcement_for_profile(profile_id: str, records: list[dict[str, Any]]) -> float:
    normalized_id = profile_id.lower()
    related = 0
    for record in records:
        if str(record.get("profile_id", "")).lower() == normalized_id:
            continue
        claim = str(record.get("claim", "")).lower()
        category = str(record.get("category", "")).lower()
        if any(token in claim or token in category for token in _profile_tokens(normalized_id)):
            related += 1
    return min(0.2, related * 0.05)


def weakening_for_profile(profile_id: str, conflicts: list[ProfileConflict]) -> float:
    count = sum(
        1
        for conflict in conflicts
        if conflict.profile_id == profile_id or conflict.conflicting_profile_id == profile_id
    )
    return min(0.35, count * 0.2)


def _food_conflict(left: dict[str, Any], right: dict[str, Any]) -> ProfileConflict | None:
    left_claim = str(left.get("claim", ""))
    right_claim = str(right.get("claim", ""))
    left_likes_spicy = _mentions_like_hotpot_or_spicy(left_claim)
    right_avoids_spicy = _mentions_avoid_spicy(right_claim)
    right_likes_spicy = _mentions_like_hotpot_or_spicy(right_claim)
    left_avoids_spicy = _mentions_avoid_spicy(left_claim)
    if left_likes_spicy and right_avoids_spicy:
        return ProfileConflict(
            profile_id=str(left.get("profile_id", "")),
            conflicting_profile_id=str(right.get("profile_id", "")),
            conflict_type="spicy_food_preference",
            reason="One profile says the user likes hotpot or spicy food, while another says the user avoids spicy food.",
        )
    if right_likes_spicy and left_avoids_spicy:
        return ProfileConflict(
            profile_id=str(right.get("profile_id", "")),
            conflicting_profile_id=str(left.get("profile_id", "")),
            conflict_type="spicy_food_preference",
            reason="One profile says the user likes hotpot or spicy food, while another says the user avoids spicy food.",
        )
    return None


def _mentions_like_hotpot_or_spicy(text: str) -> bool:
    lowered = text.lower()
    positive = "喜欢" in text or "偏好" in text or "经常" in text or "like" in lowered or "prefer" in lowered
    spicy_food = "火锅" in text or "辛辣" in text or "spicy" in lowered or "hotpot" in lowered
    return positive and spicy_food


def _mentions_avoid_spicy(text: str) -> bool:
    lowered = text.lower()
    avoids = "避免" in text or "少吃" in text or "不吃" in text or "avoid" in lowered
    spicy = "辛辣" in text or "辣" in text or "spicy" in lowered
    return avoids and spicy


def _profile_tokens(profile_id: str) -> list[str]:
    return [part for part in profile_id.replace("-", "_").split("_") if part]


def _days_since(timestamp: str | None, now: datetime) -> float:
    if timestamp is None:
        return 0.0
    parsed, comparable_now = _normalize_datetime_pair(datetime.fromisoformat(timestamp), now)
    return max(0.0, (comparable_now - parsed).total_seconds() / 86400.0)


def _decay_factor(days: float, half_life_days: float) -> float:
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    return math.pow(0.5, days / half_life_days)


def _is_expired(due_time: str | None, status: str, now: datetime) -> bool:
    if status != "open" or due_time is None:
        return False
    parsed, comparable_now = _normalize_datetime_pair(datetime.fromisoformat(due_time), now)
    return parsed < comparable_now


def _normalize_datetime_pair(left: datetime, right: datetime) -> tuple[datetime, datetime]:
    if (left.tzinfo is None) == (right.tzinfo is None):
        return left, right
    return left.replace(tzinfo=None), right.replace(tzinfo=None)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))

from __future__ import annotations

import re

from .schemas import TaskCompletionResult
from .store import ProactiveStore


RISKY_TERMS = ("购物", "买", "下单", "付款", "支付", "发消息", "发送", "订单")


def _profile_ids_for_events(store: ProactiveStore, event_ids: set[str]) -> list[str]:
    ids: list[str] = []
    for profile in store.profiles:
        if event_ids & set(profile.get("evidence_event_ids", [])):
            ids.append(str(profile["profile_id"]))
    return ids


def _opportunity_ids_for_events(store: ProactiveStore, event_ids: set[str]) -> list[str]:
    ids: list[str] = []
    for opportunity in store.service_opportunities:
        if event_ids & set(opportunity.get("source_event_ids", [])):
            ids.append(str(opportunity["opportunity_id"]))
    return ids


def _extract_categories(store: ProactiveStore) -> list[str]:
    categories: list[str] = []
    for event in store.events:
        entities = event.get("entities") if isinstance(event.get("entities"), dict) else {}
        for category in entities.get("product_categories", []):
            if category not in categories:
                categories.append(str(category))
    return categories


def complete_task(store: ProactiveStore, task: str, limit: int = 5) -> TaskCompletionResult:
    query = task or "主动服务"
    hits = store.search_local(query, limit=limit)
    evidence_ids: set[str] = set()
    for hit in hits:
        evidence_ids.update(str(item) for item in hit.get("source_event_ids", []))

    if not evidence_ids:
        for opportunity in store.service_opportunities:
            evidence_ids.update(str(item) for item in opportunity.get("source_event_ids", []))

    source_profile_ids = _profile_ids_for_events(store, evidence_ids)
    source_opportunity_ids = _opportunity_ids_for_events(store, evidence_ids)
    todo_titles = [
        opportunity["title"]
        for opportunity in store.service_opportunities
        if opportunity.get("opportunity_id") in source_opportunity_ids
    ]
    categories = _extract_categories(store)
    details = []
    if todo_titles:
        details.append("；".join(todo_titles))
    if categories:
        details.append("重点关注：" + "、".join(categories))
    if not details:
        details.append("结合已有用户画像和主动服务机会进行信息收集与确认")

    completed = f"{task.strip()}：{'; '.join(details)}。先收集和比对信息，向用户确认后再执行高风险操作。"
    risky = any(term in task for term in RISKY_TERMS) or bool(re.search(r"买|购|付|发", task))
    return TaskCompletionResult(
        original_task=task,
        completed_task=completed,
        evidence_event_ids=sorted(evidence_ids),
        source_profile_ids=source_profile_ids,
        source_opportunity_ids=source_opportunity_ids,
        confidence=0.78 if evidence_ids else 0.4,
        requires_user_confirmation=risky or any(item.get("status") == "candidate" for item in store.service_opportunities),
        privacy_level="derived",
        notes=["使用任务2画像/主动服务机会证据补全", "画像驱动建议只用于弱提醒，不自动下单或付款"],
    )

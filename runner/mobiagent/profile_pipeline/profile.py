from __future__ import annotations

import hashlib

from .schemas import ProfileItem, Relation, TodoItem, UserEvent


def _id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1(":".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _time_range(events: list[UserEvent]) -> str:
    times = sorted(event.event_time for event in events if event.event_time != "unknown")
    if not times:
        return "unknown"
    return times[0] if len(times) == 1 else f"{times[0]} 至 {times[-1]}"


def build_profile_and_todos(events: list[UserEvent], relations: list[Relation]) -> tuple[list[ProfileItem], list[TodoItem]]:
    profile_items: list[ProfileItem] = []
    todos: list[TodoItem] = []
    chat_events = [event for event in events if event.event_type == "chat_context"]
    if chat_events:
        profile_items.append(
            ProfileItem(
                profile_id=_id("profile", "chat", *[event.event_id for event in chat_events]),
                category="沟通/社交线索",
                claim=f"微信聊天保留{len(chat_events)}条摘要级社交上下文，不扩散原始聊天文本。",
                evidence_event_ids=[event.event_id for event in chat_events],
                confidence=0.68,
                time_range=_time_range(chat_events),
                service_eligible=False,
                privacy_level="sensitive_summary",
            )
        )
    for event in events:
        if event.event_type == "shopping_browse":
            categories = event.entities.get("product_categories") or []
            prices = event.entities.get("price_signal") or []
            claim = f"候选购物偏好：近期浏览过{','.join(categories) or '未知品类'}；价格信号为{','.join(prices) or 'unknown'}。"
            profile_items.append(
                ProfileItem(
                    profile_id=_id("profile", event.event_id, "shopping"),
                    category="购物偏好",
                    claim=claim,
                    evidence_event_ids=[event.event_id],
                    confidence=min(event.confidence, 0.78),
                    time_range=_time_range([event]),
                    service_eligible=True,
                )
            )
            todos.append(
                TodoItem(
                    todo_id=_id("todo", event.event_id, "price-review"),
                    title="复查近期购物需求并进行比价",
                    reason="淘宝足迹只证明近期浏览，适合生成弱提醒而不是长期偏好结论。",
                    source_event_ids=[event.event_id],
                    priority="low",
                    due_time=None,
                    status="candidate",
                )
            )
        elif event.event_type == "order_record":
            services = event.entities.get("service_type") or ["unknown"]
            status = event.entities.get("order_status") or []
            profile_items.append(
                ProfileItem(
                    profile_id=_id("profile", event.event_id, "service"),
                    category="生活服务/消费习惯",
                    claim=f"存在{','.join(services)}消费记录；订单状态信号为{','.join(status) or 'unknown'}。",
                    evidence_event_ids=[event.event_id],
                    confidence=0.82,
                    time_range=_time_range([event]),
                    service_eligible=True,
                )
            )
        elif event.event_type == "content_history_state":
            profile_items.append(
                ProfileItem(
                    profile_id=_id("profile", event.event_id, "content"),
                    category="内容兴趣",
                    claim="小红书浏览记录页面为空，当前不能据此推断内容兴趣。",
                    evidence_event_ids=[event.event_id],
                    confidence=0.8,
                    time_range=_time_range([event]),
                    service_eligible=False,
                )
            )
    return profile_items, todos

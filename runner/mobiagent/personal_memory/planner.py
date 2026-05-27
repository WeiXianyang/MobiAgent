from __future__ import annotations

from datetime import datetime, timedelta

from .schemas import AgentMemoryQuery


def plan_memory_query(text: str, now: datetime | None = None) -> AgentMemoryQuery:
    current = now or datetime.now()
    report_terms = ("总结", "报告", "画像")
    is_weekly_report = (
        "周报" in text
        or "画像报告" in text
        or (("过去一周" in text or "上周" in text) and any(term in text for term in report_terms))
    )
    if is_weekly_report:
        start = current - timedelta(days=7)
        return AgentMemoryQuery(
            intent="weekly_report",
            text=text,
            time_start=start.isoformat(timespec="seconds"),
            time_end=current.isoformat(timespec="seconds"),
            include_events=True,
            include_relations=True,
            include_cards=True,
            semantic_fallback=False,
            limit=30,
        )
    if "待办" in text or "提醒" in text or "主动执行" in text:
        return AgentMemoryQuery(
            intent="todo_service",
            text=text,
            states=["observed", "open"],
            include_events=True,
            include_relations=True,
            include_cards=True,
            semantic_fallback=False,
            limit=20,
        )
    if "上次" in text or "那个" in text or "继续" in text:
        return AgentMemoryQuery(
            intent="task_resume",
            text=text,
            include_events=True,
            include_relations=True,
            include_cards=True,
            semantic_fallback=True,
            limit=10,
        )
    return AgentMemoryQuery(
        intent="general_memory_lookup",
        text=text,
        include_events=True,
        include_relations=False,
        include_cards=True,
        semantic_fallback=True,
        limit=10,
    )

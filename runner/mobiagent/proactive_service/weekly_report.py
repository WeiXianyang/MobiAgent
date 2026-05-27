from __future__ import annotations

from datetime import date, datetime, timedelta

from .schemas import ScheduledTodo, ScheduledTodoResult, WeeklyProfileReport
from .store import ProactiveStore


def _parse_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def build_weekly_report(
    store: ProactiveStore,
    *,
    days: int = 7,
    end_date: str | None = None,
    scheduled_todos: list[ScheduledTodo] | None = None,
    scheduled_results: list[ScheduledTodoResult] | None = None,
) -> WeeklyProfileReport:
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = end - timedelta(days=days)
    events = [
        event
        for event in store.events
        if event.get("event_time") and start <= _parse_date(str(event["event_time"])) <= end
    ]
    evidence_ids = [str(event["event_id"]) for event in events]
    profiles = [profile for profile in store.profiles if set(profile.get("evidence_event_ids", [])) & set(evidence_ids)]
    opportunities = [
        opportunity
        for opportunity in store.service_opportunities
        if set(opportunity.get("source_event_ids", [])) & set(evidence_ids)
    ]
    scheduled_todos = scheduled_todos or []
    scheduled_results = scheduled_results or []
    proactive_items = [str(opportunity["title"]) for opportunity in opportunities]
    lines = [
        "# 任务3 过去一周画像报告",
        "",
        f"- 时间窗口: {start.isoformat()} 至 {end.isoformat()}",
        f"- 事件数: {len(events)}",
        f"- 画像数: {len(profiles)}",
        f"- 画像驱动主动建议数: {len(opportunities)}",
        f"- 用户明确定时待办数: {len(scheduled_todos)}",
        f"- 定时主动执行结果数: {len(scheduled_results)}",
        "",
        "## 用户画像",
        "",
    ]
    for profile in profiles:
        lines.append(f"- [{profile.get('category')}] {profile.get('claim')} 证据={','.join(profile.get('evidence_event_ids', []))}")
    lines.extend(["", "## 画像驱动主动建议", ""])
    for opportunity in opportunities:
        lines.append(f"- {opportunity.get('title')}: {opportunity.get('reason')} status={opportunity.get('status')}")
    if not opportunities:
        lines.append("- 本周期无画像驱动主动建议。")
    lines.extend(["", "## 用户明确待办", ""])
    for scheduled_todo in scheduled_todos:
        lines.append(f"- {scheduled_todo.title}: due_at={scheduled_todo.due_at} status={scheduled_todo.status}")
    if not scheduled_todos:
        lines.append("- 本周期未记录用户明确设置的定时待办。")
    lines.extend(["", "## 定时主动执行结果", ""])
    for result in scheduled_results:
        lines.append(f"- {result.scheduled_todo_id}: due_at={result.due_at} status={result.status}")
    if not scheduled_results:
        lines.append("- 本周期暂无已到期定时待办执行结果。")
    lines.extend(
        [
            "",
            "## 局限性",
            "",
            "- 画像驱动建议只用于弱提醒；购物、付款、发消息等行为必须经过用户确认。",
            "- 用户明确待办来自用户直接指令，例如“1分钟后打开淘宝搜索护肤品”；只有到期后才进入执行队列。",
        ]
    )
    return WeeklyProfileReport(
        title="任务3 过去一周画像报告",
        days=days,
        end_date=end.isoformat(),
        event_count=len(events),
        profile_count=len(profiles),
        scheduled_todo_count=len(scheduled_todos),
        markdown="\n".join(lines) + "\n",
        evidence_event_ids=evidence_ids,
        proactive_items=proactive_items,
        scheduled_result_count=len(scheduled_results),
    )

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas import RunRecord, UserEvent


PACKAGE_EVENT_TYPES = {
    "com.taobao.taobao": "shopping_browse",
    "com.sankuai.meituan": "order_record",
    "com.xingin.xhs": "content_history_state",
    "com.tencent.mm": "chat_context",
}


def _event_id(run_id: str, event_type: str, step_id: str) -> str:
    digest = hashlib.sha1(f"{run_id}:{event_type}:{step_id}".encode("utf-8")).hexdigest()[:10]
    return f"evt_{digest}"


def _iso_time(timestamp: float | int | None) -> str:
    if not timestamp:
        return "unknown"
    return datetime.fromtimestamp(float(timestamp)).isoformat(timespec="seconds")


def _structured_steps(record: RunRecord) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    steps = []
    for step_id, step in record.summary.get("steps", {}).items():
        output = step.get("output") or {}
        structured = output.get("structured_output")
        if isinstance(structured, dict):
            steps.append((step_id, step, output))
    return steps


def _evidence_paths(record: RunRecord, output: dict[str, Any], step_id: str) -> list[str]:
    paths: list[str] = []
    for key in ("image", "image_path"):
        value = output.get(key)
        if value and Path(value).exists():
            paths.append(str(Path(value)))
    daily_log_path = output.get("daily_log_path")
    if daily_log_path and Path(daily_log_path).exists():
        paths.append(str(Path(daily_log_path)))
    for path in record.daily_log_paths[:2]:
        if str(path) not in paths:
            paths.append(str(path))
    for path in record.screenshot_paths[:2]:
        if str(path) not in paths:
            paths.append(str(path))
    paths.append(f"{record.summary_path}#steps.{step_id}.output.structured_output")
    return paths


def _entities_for(event_type: str, structured: dict[str, Any]) -> dict[str, Any]:
    if event_type == "shopping_browse":
        return {
            "product_categories": structured.get("product_categories") or [],
            "brand_or_shop_signal": structured.get("brand_or_shop_signal") or [],
            "price_signal": structured.get("price_signal") or [],
        }
    if event_type == "order_record":
        return {
            "merchant_or_service": structured.get("merchant_or_category") or [],
            "price_signal": structured.get("price_signal") or [],
            "order_status": structured.get("order_status_signal") or [],
            "service_type": _service_type(structured),
            "location_signal": structured.get("location_signal") or "unknown",
        }
    if event_type == "content_history_state":
        empty = not structured.get("content_items") and not structured.get("interest_tags")
        return {
            "history_status": "empty" if empty else "has_items",
            "page_type": "浏览记录",
            "content_items": structured.get("content_items") or [],
            "interest_tags": structured.get("interest_tags") or [],
        }
    if event_type == "chat_context":
        return {
            "topic_summary": structured.get("summary", ""),
            "contains_today_chat": bool(structured.get("contains_today_chat", False)),
            "sensitive_raw_text_retained": False,
        }
    return dict(structured)


def _service_type(structured: dict[str, Any]) -> list[str]:
    text = " ".join(str(item) for item in structured.get("merchant_or_category", [])) + " " + str(structured.get("summary", ""))
    values: list[str] = []
    if "单车" in text or "骑行" in text:
        values.append("骑行")
    if "外卖" in text or "煎饼" in text or "鱼你在一起" in text:
        values.append("外卖")
    return values or ["unknown"]


def _confidence_for(event_type: str, structured: dict[str, Any]) -> float:
    if event_type == "content_history_state" and not structured.get("content_items"):
        return 0.82
    if event_type == "chat_context":
        return 0.7
    return 0.86


def events_from_runs(records: list[RunRecord], user_id: str = "local_user") -> list[UserEvent]:
    events: list[UserEvent] = []
    for record in records:
        event_type = PACKAGE_EVENT_TYPES.get(record.package_name)
        if not event_type:
            continue
        structured_steps = _structured_steps(record)
        if not structured_steps:
            continue
        selected_steps = structured_steps if event_type == "chat_context" else [structured_steps[-1]]
        for step_id, step, output in selected_steps:
            structured = output.get("structured_output") or {}
            events.append(
                UserEvent(
                    event_id=_event_id(record.run_id, event_type, step_id),
                    user_id=user_id,
                    app=record.app_name,
                    package_name=record.package_name,
                    event_time=_iso_time(step.get("started_at")),
                    source_run=record.run_id,
                    source_step=step_id,
                    evidence_paths=_evidence_paths(record, output, step_id),
                    event_type=event_type,
                    summary=str(structured.get("summary") or ""),
                    entities=_entities_for(event_type, structured),
                    confidence=_confidence_for(event_type, structured),
                    privacy_level="sensitive_summary" if event_type == "chat_context" else "derived",
                )
            )
    return events

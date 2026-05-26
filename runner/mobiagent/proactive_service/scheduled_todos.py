from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .doctor import DEFAULT_MODEL_NAME
from .schemas import ScheduledTodo, ScheduledTodoResult


RISKY_TERMS = ("购物", "淘宝", "商品", "搜索", "买", "下单", "付款", "支付", "发消息", "发送", "订单")


def _id(prefix: str, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _parse_now(now_iso: str | None) -> datetime:
    return datetime.fromisoformat(now_iso) if now_iso else datetime.now().replace(microsecond=0)


def _safe_file_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value).strip("-") or "scheduled"


def _parse_relative_instruction(instruction: str, now: datetime) -> tuple[str, datetime]:
    text = instruction.strip()
    match = re.match(r"^(?P<num>\d+)\s*(?P<unit>分钟|分|小时|秒)后(?P<task>.+)$", text)
    if not match:
        raise ValueError("目前只支持相对时间指令，例如：1分钟后打开淘宝搜索护肤品")
    amount = int(match.group("num"))
    unit = match.group("unit")
    if unit in {"分钟", "分"}:
        delta = timedelta(minutes=amount)
    elif unit == "小时":
        delta = timedelta(hours=amount)
    else:
        delta = timedelta(seconds=amount)
    return match.group("task").strip(), now + delta


def _workflow_for_scheduled_todo(todo: ScheduledTodo) -> dict:
    return {
        "metadata": {"name": f"task3-scheduled-{todo.scheduled_todo_id}", "description": todo.title},
        "defaults": {
            "device": todo.device,
            "use_e2e": True,
            "use_qwen3": True,
            "decider_protocol": "qwen_json",
            "output_dir": "runner/mobiagent/workflow/test-runs",
        },
        "context": {
            "scheduled_todo_id": todo.scheduled_todo_id,
            "model_name": todo.model_name,
            "due_at": todo.due_at,
        },
        "steps": [
            {"id": 1, "type": "gui_task", "name": "执行用户明确待办", "task_description": todo.task_description},
            {"id": 2, "type": "gui_action", "name": "保存执行截图", "action": "screenshot", "file_name": "scheduled_todo_result.jpg"},
            {
                "id": 3,
                "type": "tool",
                "tool_name": "vlm_qa",
                "inputs": {
                    "mode": "summary",
                    "image": "${steps.2.output.image_path}",
                    "question": "请总结本次用户定时待办的执行结果。",
                },
            },
        ],
    }


def parse_scheduled_todo(
    instruction: str,
    *,
    now_iso: str | None = None,
    workflow_dir: Path,
    model_name: str = DEFAULT_MODEL_NAME,
    model_base_url: str | None = None,
    device: str = "Android",
) -> ScheduledTodo:
    now = _parse_now(now_iso)
    title, due_at = _parse_relative_instruction(instruction, now)
    scheduled_todo_id = _id("scheduled", f"{instruction}:{now.isoformat()}")
    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_path = workflow_dir / f"{_safe_file_part(scheduled_todo_id)}.json"
    requires_confirmation = any(term in title for term in RISKY_TERMS)
    task_description = f"{title}。这是用户明确设置的定时待办，到点后主动执行；如涉及下单、付款、发消息等高风险动作，只执行到确认前。"
    todo = ScheduledTodo(
        scheduled_todo_id=scheduled_todo_id,
        title=title,
        original_instruction=instruction,
        due_at=due_at.isoformat(timespec="seconds"),
        workflow_path=str(workflow_path),
        task_description=task_description,
        status="scheduled",
        requires_user_confirmation=requires_confirmation,
        model_name=model_name,
        model_base_url=model_base_url,
        device=device,
    )
    workflow_path.write_text(json.dumps(_workflow_for_scheduled_todo(todo), ensure_ascii=False, indent=2), encoding="utf-8")
    return todo


def _command_for(
    todo: ScheduledTodo,
    *,
    service_ip: str,
    decider_port: int,
    grounder_port: int,
    planner_port: int,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "runner.mobiagent.workflow_runner",
        "--workflow_file",
        todo.workflow_path,
        "--service_ip",
        service_ip,
        "--decider_port",
        str(decider_port),
        "--grounder_port",
        str(grounder_port),
        "--planner_port",
        str(planner_port),
        "--device",
        todo.device,
        "--use_qwen3",
        "on",
        "--decider_protocol",
        "qwen_json",
    ]


def build_due_scheduled_todo_results(
    scheduled_todos: list[ScheduledTodo],
    *,
    now_iso: str | None = None,
    execute: bool = False,
    service_ip: str = "127.0.0.1",
    model_port: int = 7000,
    decider_port: int | None = None,
    grounder_port: int | None = None,
    planner_port: int | None = None,
) -> list[ScheduledTodoResult]:
    now = _parse_now(now_iso)
    resolved_decider_port = decider_port or model_port
    resolved_grounder_port = grounder_port or model_port
    resolved_planner_port = planner_port or model_port
    results: list[ScheduledTodoResult] = []
    for todo in scheduled_todos:
        due_at = datetime.fromisoformat(todo.due_at)
        if due_at > now:
            continue
        command = _command_for(
            todo,
            service_ip=service_ip,
            decider_port=resolved_decider_port,
            grounder_port=resolved_grounder_port,
            planner_port=resolved_planner_port,
        )
        if not execute:
            results.append(ScheduledTodoResult(todo.scheduled_todo_id, todo.workflow_path, "planned_only", todo.due_at, command))
            continue
        env = os.environ.copy()
        env.update(
            {
                "MOBIAGENT_DECIDER_MODEL": todo.model_name,
                "MOBIAGENT_GROUNDER_MODEL": todo.model_name,
                "MOBIAGENT_PLANNER_MODEL": todo.model_name,
            }
        )
        if todo.model_base_url:
            env.update(
                {
                    "MOBIAGENT_DECIDER_BASE_URL": todo.model_base_url,
                    "MOBIAGENT_GROUNDER_BASE_URL": todo.model_base_url,
                    "MOBIAGENT_PLANNER_BASE_URL": todo.model_base_url,
                }
            )
        completed = subprocess.run(command, capture_output=True, text=True, env=env, timeout=600)
        results.append(
            ScheduledTodoResult(
                todo.scheduled_todo_id,
                todo.workflow_path,
                "success" if completed.returncode == 0 else "failed",
                todo.due_at,
                command,
                completed.stdout,
                completed.stderr,
            )
        )
    return results


def wait_until_due(scheduled_todos: list[ScheduledTodo], *, now_iso: str | None = None) -> None:
    if now_iso:
        return
    if not scheduled_todos:
        return
    next_due = min(datetime.fromisoformat(todo.due_at) for todo in scheduled_todos)
    seconds = max(0.0, (next_due - datetime.now()).total_seconds())
    if seconds:
        time.sleep(seconds)

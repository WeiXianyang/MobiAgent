from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from .doctor import DEFAULT_MODEL_NAME
from .schemas import ServiceOpportunityExecutionPlan, ServiceOpportunityExecutionResult
from .store import ProactiveStore


def _safe_file_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in value).strip("-") or "todo"


def _related_profile_ids(store: ProactiveStore, event_ids: list[str]) -> list[str]:
    event_set = set(event_ids)
    return [
        str(profile["profile_id"])
        for profile in store.profiles
        if event_set & set(profile.get("evidence_event_ids", []))
    ]


def _build_task_description(opportunity: dict, store: ProactiveStore) -> str:
    categories: list[str] = []
    for event_id in opportunity.get("source_event_ids", []):
        event = store.event_by_id(str(event_id)) or {}
        entities = event.get("entities") if isinstance(event.get("entities"), dict) else {}
        categories.extend(str(item) for item in entities.get("product_categories", []))
    category_text = "、".join(dict.fromkeys(categories)) or "相关商品"
    return (
        f"在淘宝搜索结果列表页围绕{category_text}复查近期购物需求并进行比价。"
        "这是画像驱动主动服务机会，不是用户明确待办；"
        "只查看搜索结果列表中的商品名称、价格、店铺和优惠信息，停留在列表页截图并总结给用户确认；"
        "不要点击商品详情、不要加入购物车、不要下单、不要付款、不要提交订单。"
    )


def _workflow_for_plan(plan: ServiceOpportunityExecutionPlan) -> dict:
    return {
        "metadata": {"name": f"task3-proactive-{plan.opportunity_id}", "description": plan.title},
        "defaults": {
            "device": plan.device,
            "use_e2e": True,
            "use_qwen3": True,
            "decider_protocol": "qwen_json",
            "output_dir": "runner/mobiagent/workflow/test-runs",
        },
        "context": {"opportunity_id": plan.opportunity_id, "model_name": plan.model_name},
        "steps": [
            {"id": 1, "type": "gui_task", "name": "打开目标应用", "task_description": "打开淘宝"},
            {"id": 2, "type": "gui_action", "name": "重置淘宝进程", "action": "app_stop", "package_name": "com.taobao.taobao"},
            {"id": 3, "type": "gui_action", "name": "重新启动淘宝", "action": "app_start", "package_name": "com.taobao.taobao"},
            {"id": 4, "type": "gui_task", "name": "收集比价信息", "task_description": plan.task_description},
            {"id": 5, "type": "gui_action", "name": "保存结果截图", "action": "screenshot", "file_name": "task3_result.jpg"},
            {
                "id": 6,
                "type": "tool",
                "tool_name": "vlm_qa",
                "inputs": {
                    "mode": "summary",
                    "image": "${steps.5.output.image_path}",
                    "question": "请总结本次画像驱动主动服务机会的执行结果，列出商品、价格和仍需用户确认的事项。",
                },
            },
        ],
    }


def build_service_opportunity_execution_plans(
    store: ProactiveStore,
    *,
    workflow_dir: Path,
    service_ip: str = "127.0.0.1",
    model_port: int = 7000,
    model_name: str = DEFAULT_MODEL_NAME,
    model_base_url: str | None = None,
    device: str = "Android",
) -> list[ServiceOpportunityExecutionPlan]:
    workflow_dir.mkdir(parents=True, exist_ok=True)
    plans: list[ServiceOpportunityExecutionPlan] = []
    for opportunity in store.service_opportunities:
        opportunity_id = str(opportunity["opportunity_id"])
        event_ids = [str(item) for item in opportunity.get("source_event_ids", [])]
        plan = ServiceOpportunityExecutionPlan(
            opportunity_id=opportunity_id,
            title=str(opportunity["title"]),
            workflow_path=str(workflow_dir / f"{_safe_file_part(opportunity_id)}.json"),
            task_description=_build_task_description(opportunity, store),
            evidence_event_ids=event_ids,
            source_profile_ids=_related_profile_ids(store, event_ids),
            confidence=0.74,
            requires_user_confirmation=bool(opportunity.get("requires_user_confirmation", True)),
            service_ip=service_ip,
            decider_port=model_port,
            grounder_port=model_port,
            planner_port=model_port,
            model_name=model_name,
            device=device,
            model_base_url=model_base_url,
        )
        Path(plan.workflow_path).write_text(json.dumps(_workflow_for_plan(plan), ensure_ascii=False, indent=2), encoding="utf-8")
        plans.append(plan)
    return plans


def execute_service_opportunity_plans(
    plans: list[ServiceOpportunityExecutionPlan], *, execute: bool
) -> list[ServiceOpportunityExecutionResult]:
    results: list[ServiceOpportunityExecutionResult] = []
    for plan in plans:
        command = [
            sys.executable,
            "-m",
            "runner.mobiagent.workflow_runner",
            "--workflow_file",
            plan.workflow_path,
            "--service_ip",
            plan.service_ip,
            "--decider_port",
            str(plan.decider_port),
            "--grounder_port",
            str(plan.grounder_port),
            "--planner_port",
            str(plan.planner_port),
            "--device",
            plan.device,
            "--use_qwen3",
            "on",
            "--decider_protocol",
            "qwen_json",
        ]
        if not execute:
            results.append(ServiceOpportunityExecutionResult(plan.opportunity_id, plan.workflow_path, "planned_only", command))
            continue
        env = os.environ.copy()
        env.update({
            "MOBIAGENT_DECIDER_MODEL": plan.model_name,
            "MOBIAGENT_GROUNDER_MODEL": plan.model_name,
            "MOBIAGENT_PLANNER_MODEL": plan.model_name,
        })
        if plan.model_base_url:
            env.update({
                "MOBIAGENT_DECIDER_BASE_URL": plan.model_base_url,
                "MOBIAGENT_GROUNDER_BASE_URL": plan.model_base_url,
                "MOBIAGENT_PLANNER_BASE_URL": plan.model_base_url,
            })
        completed = subprocess.run(command, capture_output=True, text=True, env=env, timeout=600)
        results.append(
            ServiceOpportunityExecutionResult(
                opportunity_id=plan.opportunity_id,
                workflow_path=plan.workflow_path,
                status="success" if completed.returncode == 0 else "failed",
                command=command,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )
    return results

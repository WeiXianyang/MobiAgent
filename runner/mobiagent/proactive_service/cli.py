from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .completion import complete_task
from .doctor import DEFAULT_MODEL_NAME, run_doctor
from .exporters import export_image_prompts, export_ppt_outline, export_slidev_deck
from .image_generation import DEFAULT_IMAGE_API_BASE_URL, DEFAULT_IMAGE_MODEL, generate_task3_images
from .scheduled_todos import build_due_scheduled_todo_results, parse_scheduled_todo, wait_until_due
from .schemas import ScheduledTodo, ScheduledTodoResult, to_dict_list
from .store import ProactiveStore, default_artifacts_dir, default_task2_artifacts_dir
from .todo_executor import build_service_opportunity_execution_plans, execute_service_opportunity_plans
from .weekly_report import build_weekly_report


def default_task3_report_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "task3" / "task3-proactive-service-report.md"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_store(args: argparse.Namespace) -> ProactiveStore:
    return ProactiveStore(Path(args.artifacts_dir)).load()


def _load_scheduled_todos(path: Path) -> list[ScheduledTodo]:
    if not path.exists():
        return []
    return [ScheduledTodo(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _load_scheduled_results(path: Path) -> list[ScheduledTodoResult]:
    if not path.exists():
        return []
    return [ScheduledTodoResult(**item) for item in json.loads(path.read_text(encoding="utf-8"))]


def _build_report_for_exports(store: ProactiveStore, args: argparse.Namespace, output_dir: Path):
    return build_weekly_report(
        store,
        days=args.days,
        end_date=args.end_date,
        scheduled_todos=_load_scheduled_todos(output_dir / "scheduled_todos.json"),
        scheduled_results=_load_scheduled_results(output_dir / "scheduled_todo_results.json"),
    )


def _build_summary_report(output_dir: Path, report_path: Path) -> None:
    lines = [
        "# 任务3 增强版主动服务阶段报告",
        "",
        "## 实现范围",
        "",
        "- 使用 e2e 模式和远端单模型 `fengerhu1/MobiMind-1.5-4B`。",
        "- 基于任务2画像、主动服务机会和检索 artifacts 实现主动补全、画像驱动建议执行、过去一周画像报告。",
        "- 基于用户明确指令生成 `scheduled_todos.json`，到期后主动执行并写入 `scheduled_todo_results.json`。",
        "- 输出 PPT 大纲、Slidev deck、Slidev 导出的 PPTX，并通过配置的 Gemini/OpenAI-compatible 图像接口生成周报封面图和主动服务流程图。",
        "",
        "## 语义边界",
        "",
        "- `service_opportunities.json` 是画像驱动主动建议，不是用户明确待办。",
        "- `scheduled_todos.json` 才表示用户明确设置的待办，例如“1分钟后打开淘宝搜索护肤品”。",
        "- `scheduled_todo_results.json` 表示到期后的主动执行结果。",
        "",
        "## 输出文件",
        "",
    ]
    for path in [
        "doctor.json",
        "task_completion.json",
        "service_opportunity_execution_plans.json",
        "service_opportunity_execution_results.json",
        "scheduled_todos.json",
        "scheduled_todo_results.json",
        "weekly_profile_report.md",
        "weekly_profile_report.json",
        "ppt_outline.md",
        "ppt_outline.json",
        "slidev_task3.md",
        "package.json",
        "slidev_export_command.json",
        "slidev_export_result.json",
        "task3_slidev_report.pptx",
        "image_prompts.json",
        "generated_images.json",
    ]:
        full = output_dir / path
        if full.exists():
            lines.append(f"- `{full}`")
    lines.extend(
        [
            "",
            "## 验证命令",
            "",
            "- `python -m unittest runner.mobiagent.proactive_service.test_proactive_service`",
            "- `python -m runner.mobiagent.proactive_service.cli doctor --strict --service-ip 127.0.0.1 --model-port 7000 --model-name fengerhu1/MobiMind-1.5-4B`",
            "- `python -m runner.mobiagent.proactive_service.cli complete-task --task \"帮我处理近期购物需求\"`",
            "- `python -m runner.mobiagent.proactive_service.cli plan-service-opportunities`",
            "- `python -m runner.mobiagent.proactive_service.cli create-scheduled-todo --instruction \"1分钟后打开淘宝搜索护肤品\"`",
            "- `python -m runner.mobiagent.proactive_service.cli run-scheduled-todos --execute`",
            "- `python -m runner.mobiagent.proactive_service.cli weekly-report --days 7`",
            "- `python -m runner.mobiagent.proactive_service.cli export-slidev-ppt --execute --days 7`",
            "- `python -m runner.mobiagent.proactive_service.cli generate-images --image-api-base-url http://104.238.220.141:9988 --image-model gemini-3.1-flash-image-preview`",
            "",
            "## 原理说明",
            "",
            "主动补全会检索任务2的画像、事件和主动服务机会，反查证据 ID，再把模糊任务补全成可执行的信息收集任务。画像驱动建议会生成 e2e workflow，但默认只收集信息并等待用户确认。用户明确待办由相对时间指令解析得到，到期后才进入执行队列。",
            "",
            "## 安全边界",
            "",
            "画像驱动建议默认只做信息收集；用户明确设置的定时待办到期后才执行。购物/付款/发消息类行为只做到确认前，不自动下单、付款或提交订单。",
        ]
    )
    _write_text(report_path, "\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task3 proactive service CLI.")
    parser.add_argument(
        "command",
        choices=[
            "doctor",
            "complete-task",
            "plan-service-opportunities",
            "execute-service-opportunities",
            "create-scheduled-todo",
            "run-scheduled-todos",
            "weekly-report",
            "export-ppt-outline",
            "export-slidev-ppt",
            "export-image-prompts",
            "generate-images",
            "report",
        ],
    )
    parser.add_argument("--artifacts-dir", type=Path, default=default_task2_artifacts_dir())
    parser.add_argument("--output-dir", type=Path, default=default_artifacts_dir())
    parser.add_argument("--report-path", type=Path, default=default_task3_report_path())
    parser.add_argument("--task", default="帮我处理近期购物需求")
    parser.add_argument("--instruction", default="1分钟后打开淘宝搜索护肤品")
    parser.add_argument("--now", default=None)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--service-ip", default="127.0.0.1")
    parser.add_argument("--model-port", type=int, default=7000)
    parser.add_argument("--decider-port", type=int, default=None)
    parser.add_argument("--grounder-port", type=int, default=None)
    parser.add_argument("--planner-port", type=int, default=None)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--model-base-url", default=None)
    parser.add_argument("--device", choices=["Android", "Harmony"], default="Android")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--skip-remote-check", action="store_true")
    parser.add_argument("--skip-device-check", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image-api-base-url", default=DEFAULT_IMAGE_API_BASE_URL)
    parser.add_argument("--image-api-key", default=None)
    parser.add_argument("--image-model", default=DEFAULT_IMAGE_MODEL)
    parser.add_argument("--image-size", default="1024x1024")
    parser.add_argument("--image-api-format", choices=["gemini", "openai"], default="gemini")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "doctor":
        result = run_doctor(
            artifacts_dir=Path(args.artifacts_dir),
            output_path=output_dir / "doctor.json",
            service_ip=args.service_ip,
            model_port=args.model_port,
            model_name=args.model_name,
            model_base_url=args.model_base_url,
            check_remote=not args.skip_remote_check,
            check_device=not args.skip_device_check,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.ok or not args.strict else 1

    if args.command == "create-scheduled-todo":
        scheduled_path = output_dir / "scheduled_todos.json"
        scheduled_todos = _load_scheduled_todos(scheduled_path)
        scheduled_todo = parse_scheduled_todo(
            args.instruction,
            now_iso=args.now,
            workflow_dir=output_dir / "generated_workflows",
            model_name=args.model_name,
            model_base_url=args.model_base_url,
            device=args.device,
        )
        scheduled_todos = [
            item for item in scheduled_todos if item.scheduled_todo_id != scheduled_todo.scheduled_todo_id
        ]
        scheduled_todos.append(scheduled_todo)
        _write_json(scheduled_path, to_dict_list(scheduled_todos))
        print(json.dumps(scheduled_todo.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "run-scheduled-todos":
        scheduled_todos = _load_scheduled_todos(output_dir / "scheduled_todos.json")
        if args.wait:
            wait_until_due(scheduled_todos, now_iso=args.now)
        results = build_due_scheduled_todo_results(
            scheduled_todos,
            now_iso=args.now,
            execute=args.execute,
            service_ip=args.service_ip,
            model_port=args.model_port,
            decider_port=args.decider_port,
            grounder_port=args.grounder_port,
            planner_port=args.planner_port,
        )
        _write_json(output_dir / "scheduled_todo_results.json", to_dict_list(results))
        print(json.dumps(to_dict_list(results), ensure_ascii=False, indent=2))
        return 0 if all(result.status != "failed" for result in results) else 1

    store = _load_store(args)

    if args.command == "complete-task":
        result = complete_task(store, args.task)
        _write_json(output_dir / "task_completion.json", result.to_dict())
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command in {"plan-service-opportunities", "execute-service-opportunities"}:
        for stale_name in ("todo_execution_plans.json", "todo_execution_results.json"):
            stale_path = output_dir / stale_name
            if stale_path.exists():
                stale_path.unlink()
        plans = build_service_opportunity_execution_plans(
            store,
            workflow_dir=output_dir / "generated_workflows",
            service_ip=args.service_ip,
            model_port=args.model_port,
            model_name=args.model_name,
            model_base_url=args.model_base_url,
            device=args.device,
        )
        _write_json(output_dir / "service_opportunity_execution_plans.json", to_dict_list(plans))
        should_execute = args.execute or args.command == "execute-service-opportunities"
        results = execute_service_opportunity_plans(plans, execute=should_execute)
        _write_json(output_dir / "service_opportunity_execution_results.json", to_dict_list(results))
        print(json.dumps({"plans": to_dict_list(plans), "results": to_dict_list(results)}, ensure_ascii=False, indent=2))
        return 0 if all(result.status != "failed" for result in results) else 1

    if args.command == "weekly-report":
        report = build_weekly_report(
            store,
            days=args.days,
            end_date=args.end_date,
            scheduled_todos=_load_scheduled_todos(output_dir / "scheduled_todos.json"),
            scheduled_results=_load_scheduled_results(output_dir / "scheduled_todo_results.json"),
        )
        _write_text(output_dir / "weekly_profile_report.md", report.markdown)
        _write_json(output_dir / "weekly_profile_report.json", report.to_dict())
        print(report.markdown)
        return 0

    if args.command == "export-ppt-outline":
        report = _build_report_for_exports(store, args, output_dir)
        outline = export_ppt_outline(report)
        _write_text(output_dir / "ppt_outline.md", outline.markdown)
        _write_json(output_dir / "ppt_outline.json", outline.to_dict())
        print(outline.markdown)
        return 0

    if args.command == "export-slidev-ppt":
        report = _build_report_for_exports(store, args, output_dir)
        result = export_slidev_deck(report, output_dir=output_dir, execute=args.execute)
        _write_json(output_dir / "slidev_export_result.json", result.to_dict())
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.status != "failed" else 1

    if args.command == "export-image-prompts":
        report = _build_report_for_exports(store, args, output_dir)
        prompts = export_image_prompts(report)
        _write_json(output_dir / "image_prompts.json", prompts.to_dict())
        print(json.dumps(prompts.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "generate-images":
        report = _build_report_for_exports(store, args, output_dir)
        prompts = export_image_prompts(report)
        prompt_dict = prompts.to_dict()
        _write_json(output_dir / "image_prompts.json", prompt_dict)
        results = generate_task3_images(
            prompt_dict,
            output_dir=output_dir,
            api_base_url=args.image_api_base_url,
            api_key=args.image_api_key,
            model=args.image_model,
            size=args.image_size,
            api_format=args.image_api_format,
            dry_run=args.dry_run,
        )
        _write_json(output_dir / "generated_images.json", results)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if args.command == "report":
        _build_summary_report(output_dir, Path(args.report_path))
        print(f"wrote report: {args.report_path}")
        return 0

    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

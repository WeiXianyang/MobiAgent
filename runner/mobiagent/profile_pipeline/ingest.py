from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .schemas import RunRecord


DEFAULT_SUCCESS_RUNS = [
    "20260524-205318-basic-gui-task",
    "20260524-231720-basic-gui-task-xiaohongshu-goal-v4",
    "20260525-011614-basic-gui-task-meituan-goal-v7",
    "20260525-024026-basic-gui-task-taobao-goal-v9",
]


def default_test_runs_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "workflow" / "test-runs"


def _first_app_identity(summary: dict) -> tuple[str, str]:
    for step in summary.get("steps", {}).values():
        output = step.get("output") or {}
        app_name = output.get("app_name")
        package_name = output.get("package_name")
        if app_name or package_name:
            return app_name or "unknown", package_name or "unknown"
    return "unknown", "unknown"


def _run_status(summary: dict) -> str:
    steps = summary.get("steps", {})
    if not steps:
        return "unknown"
    return "success" if all((step.get("status") == "success") for step in steps.values()) else "partial"


def _daily_logs_for_run(daily_root: Path, record: dict, package_name: str, workflow_file: str) -> list[Path]:
    candidates: set[Path] = set()
    workflow_stem = Path(workflow_file).stem.lower()
    for step in record.get("steps", {}).values():
        output = step.get("output") or {}
        daily_log_path = output.get("daily_log_path")
        if daily_log_path:
            path = Path(daily_log_path)
            if path.exists():
                candidates.add(path)
    if daily_root.exists():
        for path in daily_root.rglob("*.md"):
            name = path.name.lower()
            if package_name != "unknown" and package_name in path.name:
                if workflow_stem in name or not workflow_stem:
                    candidates.add(path)
                elif any(part and part in name for part in workflow_stem.split("_")):
                    candidates.add(path)
                else:
                    candidates.add(path)
    return sorted(candidates)


def _screenshot_paths(summary: dict, run_dir: Path) -> list[Path]:
    paths: set[Path] = set()
    for step in summary.get("steps", {}).values():
        output = step.get("output") or {}
        for key in ("image_path", "image"):
            value = output.get(key)
            if value:
                path = Path(value)
                if path.exists():
                    paths.add(path)
        step_dir = output.get("step_dir")
        if step_dir:
            step_path = Path(step_dir)
            if step_path.exists():
                for pattern in ("*.jpg", "*.jpeg", "*.png"):
                    paths.update(step_path.glob(pattern))
    for pattern in ("*.jpg", "*.jpeg", "*.png"):
        paths.update(run_dir.rglob(pattern))
    return sorted(paths)


def collect_successful_runs(test_runs_dir: Path, run_ids: Iterable[str] = DEFAULT_SUCCESS_RUNS) -> list[RunRecord]:
    records: list[RunRecord] = []
    daily_root = test_runs_dir / "daily-log"
    for run_id in run_ids:
        run_dir = test_runs_dir / run_id
        summary_path = run_dir / "run_summary.json"
        if not summary_path.exists():
            raise FileNotFoundError(f"missing run_summary.json for {run_id}: {summary_path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        workflow_file = str(summary.get("workflow_file") or "")
        app_name, package_name = _first_app_identity(summary)
        records.append(
            RunRecord(
                run_id=run_id,
                run_dir=run_dir,
                summary_path=summary_path,
                workflow_file=workflow_file,
                status=_run_status(summary),
                app_name=app_name,
                package_name=package_name,
                daily_log_paths=_daily_logs_for_run(daily_root, summary, package_name, workflow_file),
                screenshot_paths=_screenshot_paths(summary, run_dir),
                summary=summary,
            )
        )
    return records

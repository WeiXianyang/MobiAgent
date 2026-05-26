from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .schemas import ImagePromptBundle, PresentationOutline, SlidevExportResult, WeeklyProfileReport


def export_ppt_outline(report: WeeklyProfileReport) -> PresentationOutline:
    slides = [
        {"title": "任务3增强版主动服务", "bullets": ["e2e模式", "远端单模型 MobiMind-1.5-4B", "画像建议与用户定时待办分离"]},
        {"title": "数据来源", "bullets": [f"过去{report.days}天事件 {report.event_count} 条", f"证据事件: {', '.join(report.evidence_event_ids) or '无'}"]},
        {"title": "用户画像摘要", "bullets": [f"画像条目 {report.profile_count} 条", "保留证据与置信度"]},
        {"title": "画像驱动主动建议", "bullets": report.proactive_items or ["暂无画像驱动主动建议"]},
        {"title": "风险与下一步", "bullets": ["候选画像不自动执行高风险动作", "真实执行前进行 doctor 检查"]},
    ]
    lines = ["# 任务3 PPT 大纲", ""]
    for index, slide in enumerate(slides, start=1):
        lines.append(f"## {index}. {slide['title']}")
        lines.extend(f"- {bullet}" for bullet in slide["bullets"])
        lines.append("")
    return PresentationOutline(title="任务3增强版主动服务汇报", slides=slides, markdown="\n".join(lines))


def export_image_prompts(report: WeeklyProfileReport) -> ImagePromptBundle:
    profile_rows = _profile_rows_from_markdown(report.markdown)
    profile_summary = "；".join(profile_rows) if profile_rows else f"画像条目{report.profile_count}类"
    evidence_preview = ", ".join(report.evidence_event_ids[:5])
    if len(report.evidence_event_ids) > 5:
        evidence_preview += f", ... 共{len(report.evidence_event_ids)}条"
    if not evidence_preview:
        evidence_preview = "无"
    return ImagePromptBundle(
        prompts=[
            {
                "id": "profile_category_chart",
                "purpose": "过去一周用户画像分类统计图",
                "prompt": (
                    "生成科研汇报数据图表，标题“任务3：MobiAgent过去一周用户画像图表”。"
                    f"真实数据：截至{report.end_date}，过去{report.days}天，事件{report.event_count}条，画像{report.profile_count}类，"
                    f"主动建议{len(report.proactive_items)}条，用户待办{report.scheduled_todo_count}条。"
                    f"用柱状图/环形图展示画像分类证据量：{profile_summary}。"
                    "风格为数据仪表盘；不要手机宣传图，不要泛化AI流程图。"
                ),
            },
            {
                "id": "profile_evidence_chart",
                "purpose": "过去一周画像证据与主动服务图表",
                "prompt": (
                    "生成科研汇报数据图表，标题“任务3：一周MobiAgent用户画像证据分布与主动服务”。"
                    f"真实数据：事件{report.event_count}条，画像{report.profile_count}类，证据ID示例：{evidence_preview}。"
                    f"用桑基图/矩阵图展示 数据采集->画像构建->周报图表->主动建议：{profile_summary}。"
                    f"主动服务建议：{', '.join(report.proactive_items) if report.proactive_items else '无'}。"
                    "突出用户画像图表，不要抽象机器人、手机宣传图或无关日程插画。"
                ),
            },
        ]
    )


def _profile_rows_from_markdown(markdown: str) -> list[str]:
    lines: list[str] = []
    in_profiles = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line == "## 用户画像":
            in_profiles = True
            continue
        if in_profiles and line.startswith("## "):
            break
        if in_profiles and line.startswith("- ["):
            profile_text, _, evidence_text = line.removeprefix("- ").partition(" 证据=")
            category = profile_text.split("]", 1)[0].removeprefix("[")
            evidence_count = len([item for item in evidence_text.split(",") if item.strip()])
            if evidence_count:
                lines.append(f"{category}={evidence_count}条证据")
            else:
                lines.append(category)
    return lines


def _slidev_frontmatter() -> str:
    return "\n".join(
        [
            "---",
            "theme: default",
            "title: 任务3增强版主动服务汇报",
            "info: 基于 MobiAgent 任务2画像 artifacts 的任务3主动服务周报",
            "class: text-left",
            "drawings:",
            "  persist: false",
            "transition: slide-left",
            "mdc: true",
            "---",
        ]
    )


def _bullet_lines(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def build_slidev_markdown(report: WeeklyProfileReport) -> str:
    proactive_items = report.proactive_items or ["本周期暂无画像驱动主动建议"]
    evidence_preview = ", ".join(report.evidence_event_ids[:6])
    if len(report.evidence_event_ids) > 6:
        evidence_preview += f", ... 共 {len(report.evidence_event_ids)} 条"
    if not evidence_preview:
        evidence_preview = "无"

    slides = [
        [
            _slidev_frontmatter(),
            "",
            "# 任务3增强版主动服务汇报",
            "",
            "基于用户画像、主动服务机会与定时待办的可执行周报",
            "",
            "<div class=\"mt-10 grid grid-cols-3 gap-4\">",
            f"<div><div class=\"text-4xl font-bold\">{report.event_count}</div><div>事件数</div></div>",
            f"<div><div class=\"text-4xl font-bold\">{report.profile_count}</div><div>画像条目</div></div>",
            f"<div><div class=\"text-4xl font-bold\">{report.scheduled_todo_count}</div><div>用户待办</div></div>",
            "</div>",
        ],
        [
            "# 数据来源与证据边界",
            "",
            *_bullet_lines(
                [
                    f"时间窗口: 过去 {report.days} 天，截至 {report.end_date}",
                    f"证据事件: {evidence_preview}",
                    "画像与主动建议均保留证据 ID，不把弱信号升级为稳定长期偏好。",
                ]
            ),
        ],
        [
            "# 用户画像摘要",
            "",
            *_bullet_lines(
                [
                    f"本周期画像条目: {report.profile_count}",
                    "画像用于主动补全、弱提醒和报告生成。",
                    "敏感或高风险动作必须进入用户确认流程。",
                ]
            ),
        ],
        [
            "# 画像驱动主动建议",
            "",
            *_bullet_lines(proactive_items),
            "",
            "> 画像驱动建议只生成信息收集或提醒计划，不自动购物、付款或发消息。",
        ],
        [
            "# Slidev 外部生成路径",
            "",
            *_bullet_lines(
                [
                    "由任务3 CLI 生成 Slidev Markdown deck。",
                    "通过 npx 在线调用 @slidev/cli 导出 PPTX。",
                    "导出的 PPTX 可作为科研汇报附件或继续人工编辑。",
                ]
            ),
        ],
    ]
    return "\n\n---\n\n".join("\n".join(slide) for slide in slides) + "\n"


def build_slidev_export_command(deck_path: Path, pptx_path: Path) -> list[str]:
    npx = "npx.cmd" if os.name == "nt" else "npx"
    return [
        npx,
        "slidev",
        "export",
        deck_path.name,
        "--format",
        "pptx",
        "--output",
        pptx_path.stem,
    ]


def build_slidev_install_command() -> list[str]:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return [
        npm,
        "install",
        "@slidev/cli@0.49.29",
        "@slidev/theme-default@0.25.0",
        "playwright-chromium@1.48.2",
    ]


def write_slidev_package_json(output_dir: Path) -> Path:
    package_path = output_dir / "package.json"
    package_path.write_text(
        json.dumps(
            {
                "private": True,
                "scripts": {"export:pptx": "slidev export slidev_task3.md --format pptx --output task3_slidev_report"},
                "dependencies": {
                    "@slidev/cli": "0.49.29",
                    "@slidev/theme-default": "0.25.0",
                    "playwright-chromium": "1.48.2",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return package_path


def export_slidev_deck(report: WeeklyProfileReport, *, output_dir: Path, execute: bool = False) -> SlidevExportResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    deck_path = output_dir / "slidev_task3.md"
    pptx_path = output_dir / "task3_slidev_report.pptx"
    command_path = output_dir / "slidev_export_command.json"
    deck_path.write_text(build_slidev_markdown(report), encoding="utf-8")
    package_path = write_slidev_package_json(output_dir)
    install_command = build_slidev_install_command()
    command = build_slidev_export_command(deck_path, pptx_path)
    command_path.write_text(
        json.dumps(
            {
                "tool": "slidev",
                "package_json": str(package_path),
                "npm_install_argv": install_command,
                "argv": command,
                "requires_network": True,
                "requires_node": True,
                "requires_playwright_chromium": True,
                "output": str(pptx_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not execute:
        return SlidevExportResult(
            deck_path=str(deck_path),
            pptx_path=str(pptx_path),
            command_path=str(command_path),
            status="planned",
            command=command,
        )

    with tempfile.TemporaryDirectory(prefix="mobiagent_slidev_") as temp:
        work_dir = Path(temp)
        work_deck = work_dir / deck_path.name
        work_pptx = work_dir / pptx_path.name
        work_deck.write_text(deck_path.read_text(encoding="utf-8"), encoding="utf-8")
        write_slidev_package_json(work_dir)
        install_completed = subprocess.run(install_command, cwd=work_dir, text=True, capture_output=True, check=False)
        if install_completed.returncode != 0:
            return SlidevExportResult(
                deck_path=str(deck_path),
                pptx_path=str(pptx_path),
                command_path=str(command_path),
                status="failed",
                command=command,
                stdout=install_completed.stdout,
                stderr=install_completed.stderr,
            )
        export_completed = subprocess.run(command, cwd=work_dir, text=True, capture_output=True, check=False)
        if export_completed.returncode == 0 and work_pptx.exists():
            shutil.copy2(work_pptx, pptx_path)
        status = "exported" if export_completed.returncode == 0 and pptx_path.exists() else "failed"
    return SlidevExportResult(
        deck_path=str(deck_path),
        pptx_path=str(pptx_path),
        command_path=str(command_path),
        status=status,
        command=command,
        stdout=install_completed.stdout + export_completed.stdout,
        stderr=install_completed.stderr + export_completed.stderr,
    )

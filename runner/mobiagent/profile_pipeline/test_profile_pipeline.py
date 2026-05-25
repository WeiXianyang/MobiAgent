from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.mobiagent.profile_pipeline.extract import events_from_runs
from runner.mobiagent.profile_pipeline.ingest import collect_successful_runs, default_test_runs_dir
from runner.mobiagent.profile_pipeline.profile import build_profile_and_todos
from runner.mobiagent.profile_pipeline.relation import build_relations
from runner.mobiagent.profile_pipeline.search import build_search_documents, search_documents
from runner.mobiagent.profile_pipeline.cli import default_report_path, write_report


SUCCESS_RUNS = [
    "20260524-205318-basic-gui-task",
    "20260524-231720-basic-gui-task-xiaohongshu-goal-v4",
    "20260525-011614-basic-gui-task-meituan-goal-v7",
    "20260525-024026-basic-gui-task-taobao-goal-v9",
]


def write_summary(run_dir: Path, package_name: str, app_name: str, structured: dict, *, image_name: str = "screen.jpg") -> None:
    step_dir = run_dir / "steps" / "8.iter1.1"
    step_dir.mkdir(parents=True)
    image_path = step_dir / image_name
    image_path.write_bytes(b"fake image")
    summary = {
        "workflow_file": str(run_dir.parent / "runtime-workflows" / f"{run_dir.name}.json"),
        "run_dir": str(run_dir),
        "steps": {
            "1": {
                "step_id": "1",
                "status": "success",
                "started_at": 1779648000.0,
                "finished_at": 1779648001.0,
                "output": {
                    "app_name": app_name,
                    "package_name": package_name,
                },
                "error": None,
            },
            "8.iter1.1": {
                "step_id": "8.iter1.1",
                "status": "success",
                "started_at": 1779648002.0,
                "finished_at": 1779648003.0,
                "output": {
                    "image_path": str(image_path),
                    "step_dir": str(step_dir),
                },
                "error": None,
            },
            "8.iter1.2": {
                "step_id": "8.iter1.2",
                "status": "success",
                "started_at": 1779648004.0,
                "finished_at": 1779648005.0,
                "output": {
                    "tool_name": "vlm_qa",
                    "mode": "summary",
                    "image": str(image_path),
                    "structured_output": structured,
                    "daily_log_path": str(run_dir.parent / "daily-log" / "2026-05-25" / f"{package_name}.md"),
                },
                "error": None,
            },
        },
    }
    (run_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


def append_structured_step(run_dir: Path, step_id: str, structured: dict, image_name: str) -> None:
    summary_path = run_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    step_dir = run_dir / "steps" / step_id.replace(".2", ".1")
    step_dir.mkdir(parents=True, exist_ok=True)
    image_path = step_dir / image_name
    image_path.write_bytes(b"fake image")
    summary["steps"][step_id] = {
        "step_id": step_id,
        "status": "success",
        "started_at": 1779648010.0,
        "finished_at": 1779648011.0,
        "output": {
            "tool_name": "vlm_qa",
            "mode": "summary",
            "image": str(image_path),
            "structured_output": structured,
        },
        "error": None,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


class ProfilePipelineTests(unittest.TestCase):
    def test_default_report_path_stays_inside_mobiagent_repo(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        self.assertTrue(default_report_path().is_relative_to(repo_root))
        self.assertEqual(default_report_path().relative_to(repo_root), Path("docs/task2/task2-user-profile-report.md"))

    def test_default_test_runs_dir_points_to_existing_workflow_artifacts(self) -> None:
        self.assertTrue((default_test_runs_dir() / "20260524-205318-basic-gui-task" / "run_summary.json").exists())

    def test_collect_successful_runs_finds_required_sources_and_daily_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            daily = base / "daily-log" / "2026-05-25"
            daily.mkdir(parents=True)
            for run in SUCCESS_RUNS:
                run_dir = base / run
                run_dir.mkdir()
                package_name = "com.taobao.taobao" if "taobao" in run else "com.tencent.mm"
                write_summary(run_dir, package_name, "淘宝" if "taobao" in run else "微信", {"summary": "ok"})
            (daily / "com.taobao.taobao__01_basic_gui_task_taobao_goal_v9.md").write_text("淘宝摘要", encoding="utf-8")
            (daily / "com.tencent.mm__01_basic_gui_task_weixin_v2_grounder__小赵.md").write_text(
                "微信摘要",
                encoding="utf-8",
            )

            records = collect_successful_runs(base, SUCCESS_RUNS)

        self.assertEqual([record.run_id for record in records], SUCCESS_RUNS)
        self.assertTrue(all(record.summary_path.name == "run_summary.json" for record in records))
        self.assertTrue(any(record.daily_log_paths for record in records))

    def test_extract_builds_required_event_types_without_sensitive_chat_raw_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            samples = [
                (
                    "20260524-205318-basic-gui-task",
                    "com.tencent.mm",
                    "微信",
                    {"summary": "聊天双方讨论工作选择和休息安排", "contains_today_chat": True},
                ),
                (
                    "20260524-231720-basic-gui-task-xiaohongshu-goal-v4",
                    "com.xingin.xhs",
                    "小红书",
                    {"summary": "当前浏览记录页面显示无任何浏览记录", "content_items": [], "interest_tags": []},
                ),
                (
                    "20260525-011614-basic-gui-task-meituan-goal-v7",
                    "com.sankuai.meituan",
                    "美团",
                    {
                        "summary": "美团全部订单页面，显示已完成的骑行订单和外卖订单。",
                        "merchant_or_category": ["单车", "鱼你在一起"],
                        "price_signal": ["¥1.5", "¥22.5"],
                        "order_status_signal": ["已完成", "已完成"],
                    },
                ),
                (
                    "20260525-024026-basic-gui-task-taobao-goal-v9",
                    "com.taobao.taobao",
                    "淘宝",
                    {
                        "summary": "当前截图商品浏览摘要",
                        "product_categories": ["建材", "护肤品"],
                        "brand_or_shop_signal": ["沪心有业", "官方"],
                        "price_signal": ["¥3.02", "¥13.4"],
                    },
                ),
            ]
            for run_id, package_name, app_name, structured in samples:
                run_dir = base / run_id
                run_dir.mkdir()
                write_summary(run_dir, package_name, app_name, structured)

            records = collect_successful_runs(base, SUCCESS_RUNS)
            events = events_from_runs(records)

        by_type = {event.event_type: event for event in events}
        self.assertEqual(set(by_type), {"chat_context", "content_history_state", "order_record", "shopping_browse"})
        self.assertEqual(by_type["shopping_browse"].entities["product_categories"], ["建材", "护肤品"])
        self.assertEqual(by_type["content_history_state"].entities["history_status"], "empty")
        self.assertNotIn("raw_chat", by_type["chat_context"].entities)
        self.assertTrue(all(event.evidence_paths for event in events))

    def test_weixin_structured_summaries_remain_separate_temporal_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            run_dir = base / "20260524-205318-basic-gui-task"
            run_dir.mkdir()
            write_summary(
                run_dir,
                "com.tencent.mm",
                "微信",
                {"summary": "第一屏聊天摘要", "contains_today_chat": True},
                image_name="chat_1.jpg",
            )
            append_structured_step(
                run_dir,
                "8.iter2.2",
                {"summary": "第二屏聊天摘要", "contains_today_chat": True},
                "chat_2.jpg",
            )

            events = events_from_runs(collect_successful_runs(base, ["20260524-205318-basic-gui-task"]))
            relations = build_relations(events)

        self.assertEqual([event.summary for event in events], ["第一屏聊天摘要", "第二屏聊天摘要"])
        self.assertTrue(any(relation.relation_type == "before" for relation in relations))

    def test_multiple_chat_events_roll_up_to_one_social_profile_item(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            run_dir = base / "20260524-205318-basic-gui-task"
            run_dir.mkdir()
            write_summary(
                run_dir,
                "com.tencent.mm",
                "微信",
                {"summary": "第一屏聊天摘要", "contains_today_chat": True},
                image_name="chat_1.jpg",
            )
            append_structured_step(
                run_dir,
                "8.iter2.2",
                {"summary": "第二屏聊天摘要", "contains_today_chat": True},
                "chat_2.jpg",
            )
            events = events_from_runs(collect_successful_runs(base, ["20260524-205318-basic-gui-task"]))
            profile_items, _todos = build_profile_and_todos(events, build_relations(events))

        social_items = [item for item in profile_items if item.category == "沟通/社交线索"]
        self.assertEqual(len(social_items), 1)
        self.assertEqual(len(social_items[0].evidence_event_ids), 2)

    def test_relations_profile_todos_and_search_are_evidence_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for run_id, package_name, app_name, structured in [
                (
                    "20260525-011614-basic-gui-task-meituan-goal-v7",
                    "com.sankuai.meituan",
                    "美团",
                    {
                        "summary": "美团全部订单页面，显示已完成的骑行订单和外卖订单。",
                        "merchant_or_category": ["单车", "鱼你在一起"],
                        "price_signal": ["¥1.5", "¥22.5"],
                        "order_status_signal": ["已完成", "已完成"],
                    },
                ),
                (
                    "20260525-024026-basic-gui-task-taobao-goal-v9",
                    "com.taobao.taobao",
                    "淘宝",
                    {
                        "summary": "当前截图商品浏览摘要",
                        "product_categories": ["建材", "护肤品"],
                        "brand_or_shop_signal": ["沪心有业", "官方"],
                        "price_signal": ["¥3.02", "¥13.4"],
                    },
                ),
            ]:
                run_dir = base / run_id
                run_dir.mkdir()
                write_summary(run_dir, package_name, app_name, structured)

            events = events_from_runs(collect_successful_runs(base, [
                "20260525-011614-basic-gui-task-meituan-goal-v7",
                "20260525-024026-basic-gui-task-taobao-goal-v9",
            ]))
            relations = build_relations(events)
            profile_items, todos = build_profile_and_todos(events, relations)
            docs = build_search_documents(events, relations, profile_items, todos)
            hits = search_documents(docs, "最近购物偏好", limit=3)

        self.assertTrue(any(relation.relation_type in {"before", "after", "same_day"} for relation in relations))
        self.assertTrue(any(item.category == "购物偏好" and item.service_eligible for item in profile_items))
        self.assertFalse(any("待支付" in todo.title for todo in todos))
        self.assertTrue(any(todo.status == "candidate" for todo in todos))
        self.assertGreaterEqual(hits[0]["score"], 1)
        self.assertIn("购物", hits[0]["text"])

    def test_report_records_verification_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            run_dir = temp_path / "20260525-024026-basic-gui-task-taobao-goal-v9"
            run_dir.mkdir()
            write_summary(
                run_dir,
                "com.taobao.taobao",
                "淘宝",
                {
                    "summary": "当前截图商品浏览摘要",
                    "product_categories": ["建材"],
                    "brand_or_shop_signal": ["官方"],
                    "price_signal": ["¥3.02"],
                },
            )
            records = collect_successful_runs(temp_path, ["20260525-024026-basic-gui-task-taobao-goal-v9"])
            events = events_from_runs(records)
            relations = build_relations(events)
            profile_items, todos = build_profile_and_todos(events, relations)
            search_docs = build_search_documents(events, relations, profile_items, todos)
            report_path = temp_path / "report.md"

            write_report(
                {
                    "records": records,
                    "events": events,
                    "relations": relations,
                    "profile_items": profile_items,
                    "todos": todos,
                    "search_docs": search_docs,
                },
                temp_path / "artifacts",
                report_path,
            )

            report = report_path.read_text(encoding="utf-8")
        self.assertIn("## 验证命令", report)
        self.assertIn("python -m unittest runner.mobiagent.profile_pipeline.test_profile_pipeline", report)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner.mobiagent.profile_pipeline.extract import events_from_runs
from runner.mobiagent.profile_pipeline.ingest import collect_successful_runs, default_test_runs_dir
from runner.mobiagent.profile_pipeline.mem0_rag import build_memory_records, search_memories, sync_memory_records
from runner.mobiagent.profile_pipeline.profile import build_profile_and_todos
from runner.mobiagent.profile_pipeline.relation import build_relations
from runner.mobiagent.profile_pipeline.schemas import ProfileItem, Relation, TodoItem, UserEvent
from runner.mobiagent.profile_pipeline.search import build_search_documents, search_documents
from runner.mobiagent.profile_pipeline.cli import default_report_path, write_report
from runner.mobiagent.profile_pipeline.cli import build_pipeline, build_service_opportunities, build_task2_coverage


SUCCESS_RUNS = [
    "20260524-205318-basic-gui-task",
    "20260524-231720-basic-gui-task-xiaohongshu-goal-v4",
    "20260525-011614-basic-gui-task-meituan-goal-v7",
    "20260525-024026-basic-gui-task-taobao-goal-v9",
]


class FakeMemory:
    def __init__(self) -> None:
        self.add_calls: list[dict] = []
        self.search_calls: list[dict] = []

    def add(self, text: str, *, user_id: str, infer: bool, metadata: dict) -> dict:
        self.add_calls.append({"text": text, "user_id": user_id, "infer": infer, "metadata": metadata})
        return {"id": f"mem-{len(self.add_calls)}", "memory": text}

    def search(self, query: str, *, user_id: str, limit: int) -> list[dict]:
        self.search_calls.append({"query": query, "user_id": user_id, "limit": limit})
        return [{"id": "mem-1", "memory": "购物偏好：近期浏览过建材", "score": 0.8}]

    def get_all(self, *, user_id: str, limit: int) -> list[dict]:
        return [{"id": "mem-2", "memory": "主动服务机会 复查近期购物需求并进行比价", "metadata": {"kind": "service_opportunity"}}]


def sample_event() -> UserEvent:
    return UserEvent(
        event_id="evt_shop",
        user_id="default_user",
        app="淘宝",
        package_name="com.taobao.taobao",
        event_time="2026-05-25T00:00:00",
        source_run="run-taobao",
        source_step="8.iter1.2",
        evidence_paths=["screen.jpg"],
        event_type="shopping_browse",
        summary="当前截图商品浏览摘要",
        entities={"product_categories": ["建材"], "price_signal": ["¥3.02"]},
        confidence=0.85,
        privacy_level="derived",
    )


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

    def test_mem0_records_preserve_evidence_metadata_for_rag(self) -> None:
        event = sample_event()
        relation = Relation(
            relation_id="rel_shop",
            relation_type="behavior_causal",
            source_event_id=event.event_id,
            target_event_id=None,
            description="浏览足迹可作为近期购物需求的弱证据",
            evidence_event_ids=[event.event_id],
            confidence=0.7,
        )
        profile = ProfileItem(
            profile_id="profile_shop",
            category="购物偏好",
            claim="候选购物偏好：近期浏览过建材。",
            evidence_event_ids=[event.event_id],
            confidence=0.78,
            time_range="recent",
            service_eligible=True,
        )
        todo = TodoItem(
            todo_id="todo_shop",
            title="复查近期购物需求并进行比价",
            reason="淘宝足迹只证明近期浏览，适合生成弱提醒。",
            source_event_ids=[event.event_id],
            priority="low",
            due_time=None,
            status="candidate",
        )

        opportunities = [
            {
                "opportunity_id": todo.todo_id,
                "title": todo.title,
                "reason": todo.reason,
                "source_event_ids": todo.source_event_ids,
                "priority": todo.priority,
                "status": todo.status,
                "requires_user_confirmation": True,
            }
        ]

        records = build_memory_records([event], [relation], [profile], opportunities)

        self.assertEqual({record["metadata"]["kind"] for record in records}, {"event", "relation", "profile", "service_opportunity"})
        profile_record = next(record for record in records if record["metadata"]["kind"] == "profile")
        self.assertIn("购物偏好", profile_record["text"])
        self.assertEqual(profile_record["metadata"]["source_event_ids"], [event.event_id])
        self.assertTrue(profile_record["metadata"]["service_eligible"])

    def test_sync_and_search_use_external_mem0_client(self) -> None:
        memory = FakeMemory()
        records = build_memory_records([sample_event()], [], [], [])

        inserted = sync_memory_records(memory, records, user_id="task2_user")
        hits = search_memories(memory, "最近购物偏好", user_id="task2_user", limit=3)

        self.assertEqual(len(inserted), 1)
        self.assertEqual(memory.add_calls[0]["user_id"], "task2_user")
        self.assertFalse(memory.add_calls[0]["infer"])
        self.assertEqual(memory.add_calls[0]["metadata"]["source"], "task2_profile_pipeline")
        self.assertEqual(memory.search_calls, [{"query": "最近购物偏好", "user_id": "task2_user", "limit": 3}])
        self.assertEqual(hits[0]["memory"], "购物偏好：近期浏览过建材")

    def test_service_opportunity_rag_search_enriches_with_external_mem0_records(self) -> None:
        memory = FakeMemory()

        hits = search_memories(memory, "有哪些主动服务机会", user_id="task2_user", limit=1)

        self.assertEqual(hits[0]["metadata"]["kind"], "service_opportunity")

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
            service_opportunities = build_service_opportunities(profile_items, todos)
            search_docs = build_search_documents(events, relations, profile_items, todos)
            report_path = temp_path / "report.md"

            write_report(
                {
                    "records": records,
                    "events": events,
                    "relations": relations,
                    "profile_items": profile_items,
                    "service_opportunities": service_opportunities,
                    "search_docs": search_docs,
                },
                temp_path / "artifacts",
                report_path,
            )

            report = report_path.read_text(encoding="utf-8")
        self.assertIn("## 验证命令", report)
        self.assertIn("python -m unittest runner.mobiagent.profile_pipeline.test_profile_pipeline", report)
        self.assertIn("## 任务2达标说明", report)
        self.assertIn("多模态数据管理", report)
        self.assertIn("因果、时域和空域关系", report)
        self.assertIn("候选待办/主动服务机会", report)
        self.assertIn("不是稳定长期偏好或敏感属性判断", report)

    def test_report_marks_legacy_rag_sync_as_outdated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            artifacts = temp_path / "artifacts"
            artifacts.mkdir()
            (artifacts / "rag_sync.json").write_text(
                json.dumps(
                    {
                        "backend": "Mem0 + Milvus",
                        "collection_name": "legacy",
                        "user_id": "default_user",
                        "inserted_count": 1,
                        "kinds": {"todo": 1},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            report_path = temp_path / "report.md"

            write_report(
                {
                    "records": [],
                    "events": [],
                    "relations": [],
                    "profile_items": [],
                    "service_opportunities": [],
                    "search_docs": [],
                },
                artifacts,
                report_path,
            )

            report = report_path.read_text(encoding="utf-8")

        self.assertIn("旧版 RAG 同步摘要", report)
        self.assertIn("service_opportunity", report)

    def test_task2_coverage_reflects_missing_relations_and_rag_sync(self) -> None:
        event = sample_event()
        profile = ProfileItem(
            profile_id="profile_shop",
            category="购物偏好",
            claim="近期浏览建材",
            evidence_event_ids=[event.event_id],
            confidence=0.8,
            time_range="recent",
            service_eligible=True,
        )
        opportunities = [
            {
                "opportunity_id": "opp_shop",
                "kind": "profile_driven_suggestion",
                "title": "复查近期购物需求并进行比价",
                "reason": "淘宝足迹只证明近期浏览。",
                "source_event_ids": [event.event_id],
                "source_profile_ids": [profile.profile_id],
                "priority": "low",
                "status": "candidate",
                "requires_user_confirmation": True,
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            coverage = build_task2_coverage(
                records=[],
                events=[event],
                relations=[],
                profile_items=[profile],
                service_opportunities=opportunities,
                artifacts_dir=Path(temp),
            )

        self.assertFalse(coverage["standards"]["causal_temporal_spatial_relations"])
        self.assertFalse(coverage["standards"]["mem0_milvus_retrievable_memory"])

    def test_task2_coverage_rejects_legacy_todo_rag_sync(self) -> None:
        event = sample_event()
        relation = Relation(
            relation_id="rel_shop",
            relation_type="behavior_causal",
            source_event_id=event.event_id,
            target_event_id=None,
            description="浏览足迹可作为弱提醒证据",
            evidence_event_ids=[event.event_id],
            confidence=0.7,
        )
        profile = ProfileItem(
            profile_id="profile_shop",
            category="购物偏好",
            claim="近期浏览建材",
            evidence_event_ids=[event.event_id],
            confidence=0.8,
            time_range="recent",
            service_eligible=True,
        )
        opportunities = [
            {
                "opportunity_id": "opp_shop",
                "kind": "profile_driven_suggestion",
                "title": "复查近期购物需求并进行比价",
                "reason": "淘宝足迹只证明近期浏览。",
                "source_event_ids": [event.event_id],
                "source_profile_ids": [profile.profile_id],
                "priority": "low",
                "status": "candidate",
                "requires_user_confirmation": True,
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp)
            (artifacts / "rag_sync.json").write_text(
                json.dumps(
                    {
                        "inserted_count": 4,
                        "kinds": {"event": 1, "relation": 1, "profile": 1, "todo": 1},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            coverage = build_task2_coverage(
                records=[object()],
                events=[event],
                relations=[relation],
                profile_items=[profile],
                service_opportunities=opportunities,
                artifacts_dir=artifacts,
            )

        self.assertTrue(coverage["standards"]["causal_temporal_spatial_relations"])
        self.assertFalse(coverage["standards"]["mem0_milvus_retrievable_memory"])

    def test_build_pipeline_writes_only_service_opportunities_for_profile_driven_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            run_dir = base / "20260525-024026-basic-gui-task-taobao-goal-v9"
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
            artifacts = base / "artifacts"

            build_pipeline(base, artifacts, ["20260525-024026-basic-gui-task-taobao-goal-v9"])

            opportunities = json.loads((artifacts / "service_opportunities.json").read_text(encoding="utf-8"))
            coverage = json.loads((artifacts / "task2_coverage.json").read_text(encoding="utf-8"))

        self.assertFalse((artifacts / "todos.json").exists())
        self.assertEqual(opportunities[0]["kind"], "profile_driven_suggestion")
        self.assertEqual(opportunities[0]["status"], "candidate")
        self.assertNotIn("legacy_todo_id", opportunities[0])
        self.assertIn("不是用户明确待办", opportunities[0]["safety_note"])
        self.assertTrue(coverage["standards"]["multimodal_data_management"])
        self.assertTrue(coverage["standards"]["useful_information_extraction"])
        self.assertFalse(coverage["standards"]["causal_temporal_spatial_relations"])
        self.assertTrue(coverage["standards"]["profile_and_candidate_todo_generation"])
        self.assertEqual(coverage["safety_boundary"], "candidate_or_summary_only")


if __name__ == "__main__":
    unittest.main()

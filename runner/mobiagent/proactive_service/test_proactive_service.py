from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from runner.mobiagent.mobiagent import split_openai_base_url_and_query
from runner.mobiagent.proactive_service.cli import main
from runner.mobiagent.proactive_service.completion import complete_task
from runner.mobiagent.proactive_service.doctor import run_doctor
from runner.mobiagent.proactive_service.exporters import export_image_prompts, export_ppt_outline, export_slidev_deck
from runner.mobiagent.proactive_service.image_generation import generate_task3_images
from runner.mobiagent.proactive_service.scheduled_todos import build_due_scheduled_todo_results, parse_scheduled_todo
from runner.mobiagent.proactive_service.store import ProactiveStore
from runner.mobiagent.proactive_service.todo_executor import build_service_opportunity_execution_plans
from runner.mobiagent.proactive_service.weekly_report import build_weekly_report


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def seed_task2_artifacts(base: Path) -> None:
    event = {
        "event_id": "evt_shop",
        "user_id": "default_user",
        "app": "淘宝",
        "package_name": "com.taobao.taobao",
        "event_time": "2026-05-25T00:00:00",
        "source_run": "run-taobao",
        "source_step": "8.iter1.2",
        "evidence_paths": ["screen.jpg"],
        "event_type": "shopping_browse",
        "summary": "近期浏览过建材和护肤品，价格信号为低价。",
        "entities": {"product_categories": ["建材", "护肤品"], "price_signal": ["¥3.02", "¥13.4"]},
        "confidence": 0.85,
        "privacy_level": "derived",
    }
    relation = {
        "relation_id": "rel_shop",
        "relation_type": "behavior_causal",
        "source_event_id": "evt_shop",
        "target_event_id": None,
        "description": "浏览足迹可作为近期购物需求的弱证据",
        "evidence_event_ids": ["evt_shop"],
        "confidence": 0.7,
    }
    profile = {
        "profile_id": "profile_shop",
        "category": "购物偏好",
        "claim": "候选购物偏好：近期浏览过建材,护肤品；价格信号为¥3.02,¥13.4。",
        "evidence_event_ids": ["evt_shop"],
        "confidence": 0.78,
        "time_range": "recent",
        "service_eligible": True,
        "privacy_level": "derived",
    }
    opportunity = {
        "opportunity_id": "opp_shop",
        "kind": "profile_driven_suggestion",
        "title": "复查近期购物需求并进行比价",
        "reason": "淘宝足迹只证明近期浏览，适合生成弱提醒而不是长期偏好结论。",
        "source_event_ids": ["evt_shop"],
        "source_profile_ids": ["profile_shop"],
        "priority": "low",
        "status": "candidate",
        "requires_user_confirmation": True,
        "safety_note": "这是画像驱动主动服务机会，不是用户明确待办。",
    }
    docs = [
        {"id": "evt_shop", "kind": "event", "text": "淘宝 shopping_browse 近期浏览过建材和护肤品", "source_event_ids": ["evt_shop"]},
        {"id": "profile_shop", "kind": "profile", "text": "购物偏好 候选购物偏好：近期浏览过建材,护肤品", "source_event_ids": ["evt_shop"]},
        {"id": "opp_shop", "kind": "service_opportunity", "text": "主动服务机会 购物 复查近期购物需求并进行比价", "source_event_ids": ["evt_shop"]},
    ]
    write_jsonl(base / "events.jsonl", [event])
    write_jsonl(base / "relations.jsonl", [relation])
    write_json(base / "profile.json", [profile])
    write_json(base / "service_opportunities.json", [opportunity])
    write_json(base / "search_index.json", docs)
    write_json(base / "rag_sync.json", {"backend": "Mem0 + Milvus", "inserted_count": 4, "collection_name": "mobiagent"})


class ProactiveServiceTests(unittest.TestCase):
    def test_openai_base_url_query_is_split_for_token_mapped_endpoint(self) -> None:
        base_url, default_query = split_openai_base_url_and_query("https://example.invalid/v1?token=test-token")

        self.assertEqual(base_url, "https://example.invalid/v1")
        self.assertEqual(default_query, {"token": "test-token"})

    def test_store_requires_task2_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ProactiveStore(Path(temp))
            with self.assertRaisesRegex(FileNotFoundError, "build-profile"):
                store.load()

    def test_doctor_writes_single_model_e2e_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "task2"
            seed_task2_artifacts(artifacts)
            output = Path(temp) / "doctor.json"

            result = run_doctor(
                artifacts_dir=artifacts,
                output_path=output,
                service_ip="127.0.0.1",
                model_port=7000,
                model_name="fengerhu1/MobiMind-1.5-4B",
                model_base_url="https://example.invalid/v1?token=test-token",
                check_remote=False,
                check_device=False,
                env={
                    "MOBIAGENT_DECIDER_MODEL": "fengerhu1/MobiMind-1.5-4B",
                    "MOBIAGENT_GROUNDER_MODEL": "fengerhu1/MobiMind-1.5-4B",
                    "MOBIAGENT_PLANNER_MODEL": "fengerhu1/MobiMind-1.5-4B",
                },
            )
            self.assertTrue(output.exists())

        self.assertTrue(result.ok)
        self.assertEqual(result.model_name, "fengerhu1/MobiMind-1.5-4B")
        self.assertEqual(result.checks["remote_model"]["base_url"], "https://example.invalid/v1?token=test-token")
        self.assertTrue(result.checks["single_model_env"]["ok"])
        self.assertTrue(result.checks["task2_artifacts"]["ok"])

    def test_complete_task_uses_profile_and_requires_confirmation_for_shopping(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "task2"
            seed_task2_artifacts(artifacts)
            store = ProactiveStore(artifacts).load()

            result = complete_task(store, "帮我处理近期购物需求")

        self.assertIn("复查近期购物需求并进行比价", result.completed_task)
        self.assertTrue(result.requires_user_confirmation)
        self.assertEqual(result.source_profile_ids, ["profile_shop"])
        self.assertEqual(result.source_opportunity_ids, ["opp_shop"])
        self.assertIn("evt_shop", result.evidence_event_ids)

    def test_plan_service_opportunities_generates_e2e_workflow_without_payment_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "task2"
            seed_task2_artifacts(artifacts)
            workflow_dir = Path(temp) / "workflows"
            store = ProactiveStore(artifacts).load()

            plans = build_service_opportunity_execution_plans(
                store,
                workflow_dir=workflow_dir,
                service_ip="127.0.0.1",
                model_port=7000,
                model_name="fengerhu1/MobiMind-1.5-4B",
                model_base_url="https://example.invalid/v1?token=test-token",
            )
            self.assertTrue(Path(plans[0].workflow_path).exists())
            workflow = json.loads(Path(plans[0].workflow_path).read_text(encoding="utf-8"))

        self.assertEqual(len(plans), 1)
        self.assertTrue(plans[0].requires_user_confirmation)
        self.assertEqual(plans[0].model_base_url, "https://example.invalid/v1?token=test-token")
        self.assertTrue(workflow["defaults"]["use_e2e"])
        self.assertEqual(workflow["defaults"]["decider_protocol"], "qwen_json")
        rendered = json.dumps(workflow, ensure_ascii=False)
        self.assertIn("不要付款", rendered)
        self.assertIn("不要下单", rendered)
        self.assertIn("不要点击商品详情", rendered)
        self.assertIn('"action": "app_stop"', rendered)
        self.assertIn('"action": "app_start"', rendered)
        self.assertNotIn('"action": "input"', rendered)

    def test_store_loads_service_opportunities_without_legacy_todos(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "task2"
            seed_task2_artifacts(artifacts)
            store = ProactiveStore(artifacts).load()

        self.assertEqual(store.service_opportunities[0]["kind"], "profile_driven_suggestion")
        self.assertFalse(hasattr(store, "todos"))

    def test_parse_scheduled_todo_from_relative_user_instruction(self) -> None:
        todo = parse_scheduled_todo(
            "1分钟后打开淘宝搜索护肤品",
            now_iso="2026-05-26T00:00:00",
            workflow_dir=Path("generated_workflows"),
            model_name="fengerhu1/MobiMind-1.5-4B",
        )

        self.assertEqual(todo.title, "打开淘宝搜索护肤品")
        self.assertEqual(todo.due_at, "2026-05-26T00:01:00")
        self.assertTrue(todo.requires_user_confirmation)
        self.assertEqual(todo.status, "scheduled")

    def test_due_scheduled_todos_execute_only_when_due(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workflow_dir = Path(temp) / "workflows"
            due = parse_scheduled_todo(
                "0分钟后打开淘宝搜索护肤品",
                now_iso="2026-05-26T00:00:00",
                workflow_dir=workflow_dir,
                model_name="fengerhu1/MobiMind-1.5-4B",
            )
            future = parse_scheduled_todo(
                "1分钟后打开淘宝搜索建材",
                now_iso="2026-05-26T00:00:00",
                workflow_dir=workflow_dir,
                model_name="fengerhu1/MobiMind-1.5-4B",
            )

            results = build_due_scheduled_todo_results(
                [due, future],
                now_iso="2026-05-26T00:00:00",
                execute=False,
            )

        self.assertEqual([item.scheduled_todo_id for item in results], [due.scheduled_todo_id])
        self.assertEqual(results[0].status, "planned_only")

    def test_due_scheduled_todos_use_configured_routing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workflow_dir = Path(temp) / "workflows"
            due = parse_scheduled_todo(
                "0分钟后打开淘宝搜索护肤品",
                now_iso="2026-05-26T00:00:00",
                workflow_dir=workflow_dir,
                model_name="fengerhu1/MobiMind-1.5-4B",
            )

            results = build_due_scheduled_todo_results(
                [due],
                now_iso="2026-05-26T00:00:00",
                execute=False,
                service_ip="10.0.0.5",
                decider_port=7101,
                grounder_port=7102,
                planner_port=7103,
            )

        command = results[0].command
        self.assertEqual(command[command.index("--service_ip") + 1], "10.0.0.5")
        self.assertEqual(command[command.index("--decider_port") + 1], "7101")
        self.assertEqual(command[command.index("--grounder_port") + 1], "7102")
        self.assertEqual(command[command.index("--planner_port") + 1], "7103")

    def test_weekly_report_and_exports_include_task3_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "task2"
            seed_task2_artifacts(artifacts)
            store = ProactiveStore(artifacts).load()
            report = build_weekly_report(store, days=7, end_date="2026-05-26")
            ppt = export_ppt_outline(report)
            prompts = export_image_prompts(report)

        self.assertIn("过去一周画像报告", report.markdown)
        self.assertIn("画像驱动主动建议", report.markdown)
        self.assertIn("用户明确待办", report.markdown)
        self.assertIn("定时主动执行结果", report.markdown)
        self.assertEqual(len(ppt.slides), 5)
        self.assertGreaterEqual(len(prompts.prompts), 2)
        prompt_text = json.dumps(prompts.to_dict(), ensure_ascii=False)
        self.assertIn("MobiAgent过去一周用户画像图表", prompt_text)
        self.assertIn("事件1条", prompt_text)
        self.assertIn("购物偏好", prompt_text)
        self.assertIn("不要泛化AI流程图", prompt_text)
        self.assertEqual(prompts.prompts[0]["id"], "profile_category_chart")
        self.assertEqual(prompts.prompts[1]["id"], "profile_evidence_chart")

    def test_cli_writes_completion_plan_report_and_exports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            artifacts = base / "task2"
            output = base / "task3"
            seed_task2_artifacts(artifacts)

            self.assertEqual(main(["complete-task", "--task", "帮我处理近期购物需求", "--artifacts-dir", str(artifacts), "--output-dir", str(output)]), 0)
            self.assertEqual(main(["plan-service-opportunities", "--artifacts-dir", str(artifacts), "--output-dir", str(output)]), 0)
            self.assertEqual(
                main(
                    [
                        "create-scheduled-todo",
                        "--instruction",
                        "0分钟后打开淘宝搜索护肤品",
                        "--now",
                        "2026-05-26T00:00:00",
                        "--output-dir",
                        str(output),
                    ]
                ),
                0,
            )
            self.assertEqual(main(["run-scheduled-todos", "--now", "2026-05-26T00:00:00", "--output-dir", str(output)]), 0)
            self.assertEqual(main(["weekly-report", "--artifacts-dir", str(artifacts), "--output-dir", str(output), "--end-date", "2026-05-26"]), 0)
            self.assertEqual(main(["export-ppt-outline", "--artifacts-dir", str(artifacts), "--output-dir", str(output), "--end-date", "2026-05-26"]), 0)
            self.assertEqual(main(["export-slidev-ppt", "--artifacts-dir", str(artifacts), "--output-dir", str(output), "--end-date", "2026-05-26"]), 0)
            self.assertEqual(main(["export-image-prompts", "--artifacts-dir", str(artifacts), "--output-dir", str(output), "--end-date", "2026-05-26"]), 0)

            self.assertTrue((output / "task_completion.json").exists())
            self.assertTrue((output / "service_opportunity_execution_plans.json").exists())
            self.assertTrue((output / "scheduled_todos.json").exists())
            self.assertTrue((output / "scheduled_todo_results.json").exists())
            self.assertTrue((output / "weekly_profile_report.md").exists())
            self.assertTrue((output / "ppt_outline.md").exists())
            self.assertTrue((output / "slidev_task3.md").exists())
            self.assertTrue((output / "package.json").exists())
            self.assertTrue((output / "slidev_export_command.json").exists())
            self.assertTrue((output / "image_prompts.json").exists())

    def test_cli_run_scheduled_todos_passes_routing_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "task3"

            self.assertEqual(
                main(
                    [
                        "create-scheduled-todo",
                        "--instruction",
                        "0分钟后打开淘宝搜索护肤品",
                        "--now",
                        "2026-05-26T00:00:00",
                        "--output-dir",
                        str(output),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "run-scheduled-todos",
                        "--now",
                        "2026-05-26T00:00:00",
                        "--output-dir",
                        str(output),
                        "--service-ip",
                        "10.0.0.5",
                        "--model-port",
                        "7100",
                    ]
                ),
                0,
            )
            results = json.loads((output / "scheduled_todo_results.json").read_text(encoding="utf-8"))

        command = results[0]["command"]
        self.assertEqual(command[command.index("--service_ip") + 1], "10.0.0.5")
        self.assertEqual(command[command.index("--decider_port") + 1], "7100")
        self.assertEqual(command[command.index("--grounder_port") + 1], "7100")
        self.assertEqual(command[command.index("--planner_port") + 1], "7100")

    def test_export_slidev_deck_builds_slidev_markdown_and_pptx_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            artifacts = Path(temp) / "task2"
            output = Path(temp) / "task3"
            seed_task2_artifacts(artifacts)
            store = ProactiveStore(artifacts).load()
            report = build_weekly_report(store, days=7, end_date="2026-05-26")

            result = export_slidev_deck(report, output_dir=output, execute=False)

            deck_text = Path(result.deck_path).read_text(encoding="utf-8")
            package = json.loads((output / "package.json").read_text(encoding="utf-8"))
            command = json.loads(Path(result.command_path).read_text(encoding="utf-8"))

        self.assertIn("theme: default", deck_text)
        self.assertIn("任务3增强版主动服务汇报", deck_text)
        self.assertIn("画像驱动主动建议", deck_text)
        self.assertIn("---", deck_text)
        self.assertEqual(result.status, "planned")
        self.assertTrue(result.pptx_path.endswith("task3_slidev_report.pptx"))
        self.assertEqual(package["dependencies"]["@slidev/cli"], "0.49.29")
        self.assertEqual(package["dependencies"]["playwright-chromium"], "1.48.2")
        self.assertEqual(command["tool"], "slidev")
        if os.name == "nt":
            self.assertEqual(command["argv"][0], "npx.cmd")
        self.assertIn("slidev", command["argv"])
        self.assertIn("@slidev/cli@0.49.29", command["npm_install_argv"])
        self.assertIn("@slidev/theme-default@0.25.0", command["npm_install_argv"])
        self.assertIn("playwright-chromium@1.48.2", command["npm_install_argv"])
        self.assertIn("slidev_task3.md", command["argv"])
        self.assertIn("task3_slidev_report", command["argv"])
        self.assertFalse(any(str(output) in item for item in command["argv"]))
        self.assertIn("--format", command["argv"])
        self.assertIn("pptx", command["argv"])

    def test_generate_task3_images_posts_prompts_to_openai_compatible_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            calls = []

            def fake_post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
                calls.append({"url": url, "headers": headers, "payload": payload})
                return {
                    "data": [
                        {
                            "b64_json": "iVBORw0KGgo=",
                        }
                    ]
                }

            prompts = {
                "prompts": [
                    {
                        "id": "cover",
                        "purpose": "周报封面图",
                        "prompt": "生成移动端智能体主动服务周报封面图。",
                    }
                ]
            }

            results = generate_task3_images(
                prompts,
                output_dir=output,
                api_base_url="http://104.238.220.141:9988",
                api_key="test-key",
                model="gemini-3.1-flash-image-preview",
                api_format="openai",
                post_json=fake_post_json,
            )
            self.assertTrue(Path(results[0]["path"]).exists())
            self.assertEqual(Path(results[0]["path"]).read_bytes(), b"\x89PNG\r\n\x1a\n")

        self.assertEqual(len(results), 1)
        self.assertEqual(calls[0]["url"], "http://104.238.220.141:9988/v1/images/generations")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(calls[0]["payload"]["model"], "gemini-3.1-flash-image-preview")
        self.assertEqual(calls[0]["payload"]["prompt"], "生成移动端智能体主动服务周报封面图。")
        self.assertEqual(calls[0]["payload"]["response_format"], "b64_json")
        self.assertEqual(results[0]["status"], "generated")

    def test_generate_task3_images_requires_explicit_key_for_real_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "TASK3_IMAGE_API_KEY"):
                generate_task3_images(
                    {"prompts": [{"id": "cover", "prompt": "Generate a cover image."}]},
                    output_dir=Path(temp),
                    api_key=None,
                    api_format="openai",
                )

    def test_generate_task3_images_can_use_gemini_generate_content_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            calls = []

            def fake_post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
                calls.append({"url": url, "headers": headers, "payload": payload})
                return {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": "iVBORw0KGgo=",
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }

            results = generate_task3_images(
                {"prompts": [{"id": "workflow", "prompt": "Generate a workflow diagram."}]},
                output_dir=output,
                api_base_url="http://104.238.220.141:9988",
                api_key="test-key",
                model="gemini-3.1-flash-image-preview",
                api_format="gemini",
                post_json=fake_post_json,
            )
            self.assertTrue(Path(results[0]["path"]).exists())

        self.assertEqual(calls[0]["url"], "http://104.238.220.141:9988/v1beta/models/gemini-3.1-flash-image-preview:generateContent")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(calls[0]["payload"]["contents"][0]["parts"][0]["text"], "Generate a workflow diagram.")
        self.assertEqual(calls[0]["payload"]["generationConfig"]["responseModalities"], ["TEXT", "IMAGE"])
        self.assertEqual(results[0]["api_format"], "gemini")
        self.assertEqual(results[0]["status"], "generated")

    def test_cli_generates_task3_images_from_exported_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            artifacts = base / "task2"
            output = base / "task3"
            seed_task2_artifacts(artifacts)

            self.assertEqual(main(["generate-images", "--artifacts-dir", str(artifacts), "--output-dir", str(output), "--dry-run"]), 0)

            self.assertTrue((output / "image_prompts.json").exists())
            self.assertTrue((output / "generated_images.json").exists())
            prompt_text = (output / "image_prompts.json").read_text(encoding="utf-8")
            self.assertIn("用户待办0条", prompt_text)


if __name__ == "__main__":
    unittest.main()

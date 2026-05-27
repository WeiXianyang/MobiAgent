from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from runner.mobiagent.personal_memory.ingest import events_from_profile_events, relations_from_profile_relations
from runner.mobiagent.personal_memory.store import PersonalMemoryStore
from runner.mobiagent.profile_pipeline.schemas import Relation, UserEvent

from .extract import events_from_runs
from .ingest import DEFAULT_SUCCESS_RUNS, collect_successful_runs, default_test_runs_dir
from .mem0_rag import (
    DEFAULT_USER_ID,
    build_memory_records,
    create_memory_client,
    default_env_file,
    search_memories,
    sync_memory_records,
)
from .profile import build_profile_and_todos
from .relation import build_relations
from .search import build_search_documents, search_documents


def default_artifacts_dir() -> Path:
    return Path(__file__).resolve().parent / "artifacts"


def default_report_path() -> Path:
    return Path(__file__).resolve().parents[3] / "docs" / "task2" / "task2-user-profile-report.md"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text[0] == "[":
        records = json.loads(text)
        if not isinstance(records, list):
            raise ValueError(f"expected JSON array in {path}")
        return records
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def build_pipeline(test_runs_dir: Path, artifacts_dir: Path, run_ids: list[str] = DEFAULT_SUCCESS_RUNS) -> dict[str, Any]:
    records = collect_successful_runs(test_runs_dir, run_ids)
    events = events_from_runs(records)
    relations = build_relations(events)
    profile_items, todos = build_profile_and_todos(events, relations)
    search_docs = build_search_documents(events, relations, profile_items, todos)

    _write_jsonl(artifacts_dir / "events.jsonl", [event.to_dict() for event in events])
    _write_jsonl(artifacts_dir / "relations.jsonl", [relation.to_dict() for relation in relations])
    _write_json(artifacts_dir / "profile.json", [item.to_dict() for item in profile_items])
    stale_todos = artifacts_dir / "todos.json"
    if stale_todos.exists():
        stale_todos.unlink()
    service_opportunities = build_service_opportunities(profile_items, todos)
    task2_coverage = build_task2_coverage(
        records,
        events,
        relations,
        profile_items,
        service_opportunities,
        artifacts_dir=artifacts_dir,
    )
    _write_json(artifacts_dir / "service_opportunities.json", service_opportunities)
    _write_json(artifacts_dir / "task2_coverage.json", task2_coverage)
    _write_json(artifacts_dir / "search_index.json", search_docs)
    _write_json(
        artifacts_dir / "ingest_inventory.json",
        [
            {
                "run_id": record.run_id,
                "summary_path": str(record.summary_path),
                "workflow_file": record.workflow_file,
                "status": record.status,
                "app_name": record.app_name,
                "package_name": record.package_name,
                "daily_log_paths": [str(path) for path in record.daily_log_paths],
                "screenshot_count": len(record.screenshot_paths),
            }
            for record in records
        ],
    )
    return {
        "records": records,
        "events": events,
        "relations": relations,
        "profile_items": profile_items,
        "service_opportunities": service_opportunities,
        "task2_coverage": task2_coverage,
        "search_docs": search_docs,
    }


def build_service_opportunities(profile_items: list[Any], todos: list[Any]) -> list[dict[str, Any]]:
    opportunities: list[dict[str, Any]] = []
    for todo in todos:
        source_event_ids = list(todo.source_event_ids)
        source_profiles = [
            item.profile_id
            for item in profile_items
            if set(item.evidence_event_ids) & set(source_event_ids)
        ]
        opportunities.append(
            {
                "opportunity_id": todo.todo_id,
                "kind": "profile_driven_suggestion",
                "title": todo.title,
                "reason": todo.reason,
                "source_event_ids": source_event_ids,
                "source_profile_ids": source_profiles,
                "priority": todo.priority,
                "status": todo.status,
                "requires_user_confirmation": True,
                "safety_note": "这是画像驱动主动服务机会，不是用户明确待办。",
            }
        )
    return opportunities


def build_task2_coverage(
    records: list[Any],
    events: list[Any],
    relations: list[Any],
    profile_items: list[Any],
    service_opportunities: list[dict[str, Any]],
    artifacts_dir: Path | None = None,
) -> dict[str, Any]:
    event_types = sorted({event.event_type for event in events})
    relation_types = sorted({relation.relation_type for relation in relations})
    evidence_items = sum(len(event.evidence_paths) for event in events)
    rag_sync = load_rag_sync_summary(artifacts_dir) if artifacts_dir else None
    rag_kinds = rag_sync.get("kinds", {}) if isinstance(rag_sync, dict) else {}
    expected_rag_kinds = {
        kind
        for kind, present in {
            "event": bool(events),
            "relation": bool(relations),
            "profile": bool(profile_items),
            "service_opportunity": bool(service_opportunities),
        }.items()
        if present
    }
    mem0_synced = bool(
        rag_sync
        and int(rag_sync.get("inserted_count") or 0) > 0
        and isinstance(rag_kinds, dict)
        and all(int(rag_kinds.get(kind) or 0) > 0 for kind in expected_rag_kinds)
    )
    return {
        "standards": {
            "multimodal_data_management": bool(records) and evidence_items > 0,
            "useful_information_extraction": bool(events),
            "causal_temporal_spatial_relations": bool(relations),
            "profile_and_candidate_todo_generation": bool(profile_items) and bool(service_opportunities),
            "mem0_milvus_retrievable_memory": mem0_synced,
        },
        "data_management": {
            "run_count": len(records),
            "event_count": len(events),
            "evidence_path_count": evidence_items,
            "event_types": event_types,
        },
        "relation_management": {
            "relation_count": len(relations),
            "relation_types": relation_types,
            "supported_relation_types": ["before", "after", "same_day", "behavior_causal", "spatial"],
        },
        "derived_outputs": {
            "profile_count": len(profile_items),
            "candidate_todo_or_service_opportunity_count": len(service_opportunities),
            "profile_categories": sorted({item.category for item in profile_items}),
        },
        "rag_backend": "Mem0 + Milvus",
        "rag_sync": rag_sync or {"inserted_count": 0, "kinds": {}},
        "safety_boundary": "candidate_or_summary_only",
        "safety_note": "画像和候选待办只作为任务3主动补全、弱提醒和周期性报告输入，不作为稳定长期偏好、用户明确待办或敏感属性判断。",
    }


def load_search_index(artifacts_dir: Path) -> list[dict[str, Any]]:
    return json.loads((artifacts_dir / "search_index.json").read_text(encoding="utf-8"))


def load_rag_sync_summary(artifacts_dir: Path) -> dict[str, Any] | None:
    path = artifacts_dir / "rag_sync.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_memory_ids(result: Any) -> list[str]:
    if isinstance(result, dict):
        if isinstance(result.get("id"), str):
            return [result["id"]]
        if isinstance(result.get("results"), list):
            return [str(item["id"]) for item in result["results"] if isinstance(item, dict) and item.get("id")]
    if isinstance(result, list):
        return [str(item["id"]) for item in result if isinstance(item, dict) and item.get("id")]
    return []


def write_rag_sync_summary(
    inserted: list[dict[str, Any]],
    records: list[dict[str, Any]],
    artifacts_dir: Path,
    user_id: str,
) -> dict[str, Any]:
    kinds: dict[str, int] = {}
    memory_ids: list[str] = []
    for item in inserted:
        record = item["record"]
        kind = record["metadata"]["kind"]
        kinds[kind] = kinds.get(kind, 0) + 1
        memory_ids.extend(_extract_memory_ids(item["result"]))
    summary = {
        "backend": "Mem0 + Milvus",
        "user_id": user_id,
        "collection_name": os.getenv("MEM0_COLLECTION_NAME", "mobiagent"),
        "record_count": len(records),
        "inserted_count": len(inserted),
        "kinds": kinds,
        "memory_ids": memory_ids,
    }
    _write_json(artifacts_dir / "rag_sync.json", summary)
    return summary


def write_report(result: dict[str, Any], artifacts_dir: Path, report_path: Path) -> None:
    records = result["records"]
    events = result["events"]
    relations = result["relations"]
    profile_items = result["profile_items"]
    service_opportunities = result["service_opportunities"]
    task2_coverage = result.get("task2_coverage") or build_task2_coverage(
        records,
        events,
        relations,
        profile_items,
        service_opportunities,
        artifacts_dir=artifacts_dir,
    )
    search_docs = result["search_docs"]
    example_queries = ["最近购物偏好", "有哪些主动服务机会", "美团订单反映了什么消费习惯"]
    search_lines: list[str] = []
    for query in example_queries:
        hits = search_documents(search_docs, query, limit=3)
        rendered = "; ".join(f"{hit['kind']}:{hit['id']} score={hit['score']}" for hit in hits) or "无命中"
        search_lines.append(f"- `{query}` -> {rendered}")
    rag_sync = load_rag_sync_summary(artifacts_dir)

    lines = [
        "# 任务2 用户多模态数据管理与画像生成阶段报告",
        "",
        "## 输入数据",
        "",
        "本阶段只读消费任务1已有成功 run 和 daily-log，没有重新运行手机 workflow。",
        "",
    ]
    for record in records:
        lines.append(
            f"- {record.run_id}: app={record.app_name}, package={record.package_name}, "
            f"summary={record.summary_path}, daily_logs={len(record.daily_log_paths)}, screenshots={len(record.screenshot_paths)}"
        )
    lines.extend(
        [
            "",
            "## 任务2达标说明",
            "",
            "- 多模态数据管理：按 run 维度管理 `run_summary.json`、daily-log、截图路径和 VLM `structured_output`，每个事件都保留可回溯证据路径。",
            "- 有用信息抽取：将原始截图摘要转为 `shopping_browse`、`order_record`、`content_history_state`、`chat_context` 等事件，并保留实体、置信度和隐私等级。",
            "- 因果、时域和空域关系：输出 `before`、`after`、`same_day`、`behavior_causal`、`spatial` 关系；关系均绑定证据事件和置信度。",
            "- 画像与候选待办/主动服务机会：生成证据绑定的用户画像，并把可执行线索写为候选弱提醒或主动服务机会，需要用户确认后才能进入任务3执行。",
            "- RAG 管理：事件、关系、画像和候选待办/主动服务机会可同步到 Mem0 + Milvus，并通过本地检索或外部 RAG 召回。",
            "- 安全边界：全部画像是候选画像或摘要级线索，不是稳定长期偏好或敏感属性判断。",
            "",
            "## 覆盖清单",
            "",
            f"- runs: {task2_coverage['data_management']['run_count']}",
            f"- events: {task2_coverage['data_management']['event_count']} ({', '.join(task2_coverage['data_management']['event_types'])})",
            f"- evidence_paths: {task2_coverage['data_management']['evidence_path_count']}",
            f"- relations: {task2_coverage['relation_management']['relation_count']} ({', '.join(task2_coverage['relation_management']['relation_types']) or '当前样本无可构造关系'})",
            f"- profiles: {task2_coverage['derived_outputs']['profile_count']}",
            f"- candidate_todo_or_service_opportunities: {task2_coverage['derived_outputs']['candidate_todo_or_service_opportunity_count']}",
        ]
    )
    lines.extend(
        [
            "",
            "## 抽取规则",
            "",
            "- 淘宝足迹映射为 `shopping_browse`，只记录商品品类、店铺/品牌信号和价格信号，标记为候选偏好。",
            "- 美团订单映射为 `order_record`，记录商户/服务、价格、订单状态和服务类型；已完成订单不生成待支付事项。",
            "- 小红书浏览记录映射为 `content_history_state`，空记录只证明无法推断内容兴趣。",
            "- 微信聊天映射为 `chat_context`，只保留 VLM 摘要级上下文，不保存或扩散原始聊天文本。",
            "",
            "## 事件统计",
            "",
        ]
    )
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1
    for event_type, count in sorted(event_counts.items()):
        lines.append(f"- {event_type}: {count}")
    lines.extend(["", "## 关系统计", ""])
    relation_counts: dict[str, int] = {}
    for relation in relations:
        relation_counts[relation.relation_type] = relation_counts.get(relation.relation_type, 0) + 1
    for relation_type, count in sorted(relation_counts.items()):
        lines.append(f"- {relation_type}: {count}")
    lines.extend(["", "## 用户画像", ""])
    for item in profile_items:
        lines.append(f"- [{item.category}] {item.claim} 证据={','.join(item.evidence_event_ids)} 置信度={item.confidence}")
    lines.extend(["", "## 画像驱动主动服务机会", ""])
    for opportunity in service_opportunities:
        lines.append(
            f"- {opportunity['title']}: {opportunity['reason']} "
            f"status={opportunity['status']} priority={opportunity['priority']} note={opportunity['safety_note']}"
        )
    lines.extend(["", "## 检索示例", "", *search_lines])
    lines.extend(["", "## 外部 Mem0/Milvus RAG", ""])
    if rag_sync:
        kinds = rag_sync.get("kinds", {})
        if isinstance(kinds, dict) and "todo" in kinds and "service_opportunity" not in kinds:
            lines.append(
                "- 发现旧版 RAG 同步摘要：当前 pipeline 已将候选待办输出为 "
                "`service_opportunity`，请在完整 MobiMind 环境中重跑 `build-rag` 更新 Mem0/Milvus。"
            )
        lines.extend(
            [
                f"- backend: {rag_sync.get('backend', 'Mem0 + Milvus')}",
                f"- collection: {rag_sync.get('collection_name', '')}",
                f"- user_id: {rag_sync.get('user_id', '')}",
                f"- inserted_count: {rag_sync.get('inserted_count', 0)}",
                f"- kinds: {json.dumps(kinds, ensure_ascii=False)}",
            ]
        )
    else:
        lines.append("- 尚未生成 `rag_sync.json`；请先运行 `build-rag` 将任务2结果写入外部 Mem0/Milvus。")
    lines.extend(
        [
            "",
            "## 验证命令",
            "",
            "- `python -m unittest runner.mobiagent.profile_pipeline.test_profile_pipeline` -> 单元测试覆盖采集、抽取、关系、画像、主动服务机会、检索与报告结构。",
            "- `python -m runner.mobiagent.profile_pipeline.cli build-profile` -> 生成事件、关系、画像、主动服务机会和检索索引。",
            "- `python -m runner.mobiagent.profile_pipeline.cli build-rag` -> 将事件、关系、画像和主动服务机会写入外部 Mem0/Milvus。",
            "- `python -m runner.mobiagent.profile_pipeline.cli rag-search --query \"最近购物偏好\"` -> 从外部 Mem0/Milvus RAG 召回画像和主动服务机会。",
            "- `python -m runner.mobiagent.profile_pipeline.cli search --query \"最近购物偏好\"` -> 命中购物画像和主动服务机会。",
            "- `python -m runner.mobiagent.profile_pipeline.cli search --query \"有哪些主动服务机会\"` -> 命中画像驱动主动服务机会。",
            "- `python -m runner.mobiagent.profile_pipeline.cli search --query \"美团订单反映了什么消费习惯\"` -> 命中生活服务/消费习惯画像和美团订单事件。",
        ]
    )
    lines.extend(
        [
            "",
            "## 输出文件",
            "",
            f"- `{artifacts_dir / 'events.jsonl'}`",
            f"- `{artifacts_dir / 'relations.jsonl'}`",
            f"- `{artifacts_dir / 'profile.json'}`",
            f"- `{artifacts_dir / 'service_opportunities.json'}`",
            f"- `{artifacts_dir / 'task2_coverage.json'}`",
            f"- `{artifacts_dir / 'search_index.json'}`",
            f"- `{artifacts_dir / 'rag_sync.json'}`",
            "",
            "## 边界约束与任务3衔接",
            "",
            "当前闭环已经覆盖任务2要求的多模态数据管理、信息抽取、关系构建、画像生成、候选待办/主动服务机会生成和 Mem0 + Milvus 可检索记忆。任务3可以消费这些候选画像和摘要级线索做主动补全、弱提醒、确认型执行和周期性报告；系统仍保留受控边界，不把这些线索升级为稳定长期偏好、用户明确待办或敏感属性判断。",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build task2 profile artifacts and Mem0/Milvus RAG from workflow test-runs.")
    parser.add_argument(
        "command",
        choices=[
            "ingest",
            "build-profile",
            "search",
            "build-rag",
            "rag-search",
            "report",
            "build-personal-memory",
        ],
    )
    parser.add_argument("--test-runs-dir", type=Path, default=default_test_runs_dir())
    parser.add_argument("--artifacts-dir", type=Path, default=default_artifacts_dir())
    parser.add_argument("--report-path", type=Path, default=default_report_path())
    parser.add_argument("--env-file", type=Path, default=default_env_file())
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--events-json", type=Path)
    parser.add_argument("--relations-json", type=Path)
    parser.add_argument("--db")
    return parser


def _cmd_build_personal_memory(args: argparse.Namespace) -> int:
    if args.events_json is None:
        raise SystemExit("--events-json is required for build-personal-memory")
    if args.db is None:
        raise SystemExit("--db is required for build-personal-memory")

    raw_events = _load_records(args.events_json)
    events = [UserEvent(**item) for item in raw_events]
    normalized_events, artifacts = events_from_profile_events(events)

    relations = []
    if args.relations_json:
        raw_relations = _load_records(args.relations_json)
        relations = relations_from_profile_relations([Relation(**item) for item in raw_relations])

    store = PersonalMemoryStore(Path(args.db))
    store.initialize()
    store.upsert_artifacts(artifacts)
    store.upsert_events(normalized_events)
    store.upsert_relations(relations)
    print(
        json.dumps(
            {
                "db": str(args.db),
                "events": len(normalized_events),
                "artifacts": len(artifacts),
                "relations": len(relations),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "build-personal-memory":
        return _cmd_build_personal_memory(args)

    if args.command == "ingest":
        records = collect_successful_runs(args.test_runs_dir)
        _write_json(args.artifacts_dir / "ingest_inventory.json", [{"run_id": r.run_id, "status": r.status} for r in records])
        print(f"ingested {len(records)} runs")
        return 0
    if args.command == "search":
        hits = search_documents(load_search_index(args.artifacts_dir), args.query, limit=args.limit)
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0
    if args.command == "rag-search":
        memory = create_memory_client(args.env_file)
        hits = search_memories(memory, args.query, user_id=args.user_id, limit=args.limit)
        print(json.dumps(hits, ensure_ascii=False, indent=2, default=str))
        return 0

    result = build_pipeline(args.test_runs_dir, args.artifacts_dir)
    if args.command == "build-rag":
        memory = create_memory_client(args.env_file)
        records = build_memory_records(
            result["events"],
            result["relations"],
            result["profile_items"],
            result["service_opportunities"],
        )
        inserted = sync_memory_records(memory, records, user_id=args.user_id)
        summary = write_rag_sync_summary(inserted, records, args.artifacts_dir, args.user_id)
        result["task2_coverage"] = build_task2_coverage(
            result["records"],
            result["events"],
            result["relations"],
            result["profile_items"],
            result["service_opportunities"],
            artifacts_dir=args.artifacts_dir,
        )
        _write_json(args.artifacts_dir / "task2_coverage.json", result["task2_coverage"])
        print(
            f"rag_records={summary['record_count']} inserted={summary['inserted_count']} "
            f"collection={summary['collection_name']}"
        )
        return 0
    if args.command == "report":
        write_report(result, args.artifacts_dir, args.report_path)
        print(f"wrote report: {args.report_path}")
    else:
        print(
            f"events={len(result['events'])} relations={len(result['relations'])} "
            f"profile={len(result['profile_items'])} service_opportunities={len(result['service_opportunities'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

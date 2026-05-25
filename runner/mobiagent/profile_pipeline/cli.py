from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

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


def build_pipeline(test_runs_dir: Path, artifacts_dir: Path, run_ids: list[str] = DEFAULT_SUCCESS_RUNS) -> dict[str, Any]:
    records = collect_successful_runs(test_runs_dir, run_ids)
    events = events_from_runs(records)
    relations = build_relations(events)
    profile_items, todos = build_profile_and_todos(events, relations)
    search_docs = build_search_documents(events, relations, profile_items, todos)

    _write_jsonl(artifacts_dir / "events.jsonl", [event.to_dict() for event in events])
    _write_jsonl(artifacts_dir / "relations.jsonl", [relation.to_dict() for relation in relations])
    _write_json(artifacts_dir / "profile.json", [item.to_dict() for item in profile_items])
    _write_json(artifacts_dir / "todos.json", [todo.to_dict() for todo in todos])
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
        "todos": todos,
        "search_docs": search_docs,
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
    todos = result["todos"]
    search_docs = result["search_docs"]
    example_queries = ["最近购物偏好", "用户有哪些待办", "美团订单反映了什么消费习惯"]
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
    lines.extend(["", "## 待办事项", ""])
    for todo in todos:
        lines.append(f"- {todo.title}: {todo.reason} status={todo.status} priority={todo.priority}")
    lines.extend(["", "## 检索示例", "", *search_lines])
    lines.extend(["", "## 外部 Mem0/Milvus RAG", ""])
    if rag_sync:
        lines.extend(
            [
                f"- backend: {rag_sync.get('backend', 'Mem0 + Milvus')}",
                f"- collection: {rag_sync.get('collection_name', '')}",
                f"- user_id: {rag_sync.get('user_id', '')}",
                f"- inserted_count: {rag_sync.get('inserted_count', 0)}",
                f"- kinds: {json.dumps(rag_sync.get('kinds', {}), ensure_ascii=False)}",
            ]
        )
    else:
        lines.append("- 尚未生成 `rag_sync.json`；请先运行 `build-rag` 将任务2结果写入外部 Mem0/Milvus。")
    lines.extend(
        [
            "",
            "## 验证命令",
            "",
            "- `python -m unittest runner.mobiagent.profile_pipeline.test_profile_pipeline` -> 单元测试覆盖采集、抽取、关系、画像、待办、检索与报告结构。",
            "- `python -m runner.mobiagent.profile_pipeline.cli build-profile` -> 生成事件、关系、画像、待办和检索索引。",
            "- `python -m runner.mobiagent.profile_pipeline.cli build-rag` -> 将事件、关系、画像和待办写入外部 Mem0/Milvus。",
            "- `python -m runner.mobiagent.profile_pipeline.cli rag-search --query \"最近购物偏好\"` -> 从外部 Mem0/Milvus RAG 召回画像和待办。",
            "- `python -m runner.mobiagent.profile_pipeline.cli search --query \"最近购物偏好\"` -> 命中购物画像和候选待办。",
            "- `python -m runner.mobiagent.profile_pipeline.cli search --query \"用户有哪些待办\"` -> 命中候选待办。",
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
            f"- `{artifacts_dir / 'todos.json'}`",
            f"- `{artifacts_dir / 'search_index.json'}`",
            f"- `{artifacts_dir / 'rag_sync.json'}`",
            "",
            "## 局限性与任务3衔接",
            "",
            "当前闭环依赖任务1 VLM 结构化输出和截图路径，并通过 Mem0 + Milvus 保存可检索记忆。画像均为候选画像或摘要级线索，可作为任务3主动补全、弱提醒、周期性报告生成的输入，但不应作为稳定长期偏好或敏感属性判断。",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build task2 profile artifacts and Mem0/Milvus RAG from workflow test-runs.")
    parser.add_argument("command", choices=["ingest", "build-profile", "search", "build-rag", "rag-search", "report"])
    parser.add_argument("--test-runs-dir", type=Path, default=default_test_runs_dir())
    parser.add_argument("--artifacts-dir", type=Path, default=default_artifacts_dir())
    parser.add_argument("--report-path", type=Path, default=default_report_path())
    parser.add_argument("--env-file", type=Path, default=default_env_file())
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--query", default="")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)

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
        records = build_memory_records(result["events"], result["relations"], result["profile_items"], result["todos"])
        inserted = sync_memory_records(memory, records, user_id=args.user_id)
        summary = write_rag_sync_summary(inserted, records, args.artifacts_dir, args.user_id)
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
            f"profile={len(result['profile_items'])} todos={len(result['todos'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

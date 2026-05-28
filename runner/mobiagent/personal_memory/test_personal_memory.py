from __future__ import annotations

import contextlib
from datetime import datetime
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from runner.mobiagent.personal_memory.schemas import (
    AgentMemoryQuery,
    MemoryCard,
    MemoryHit,
    NormalizedEvent,
    RawArtifact,
    RelationEdge,
)
from runner.mobiagent.personal_memory.cards import build_memory_cards
from runner.mobiagent.personal_memory.ingest import events_from_profile_events, relations_from_profile_relations
from runner.mobiagent.personal_memory.lifecycle import (
    apply_confidence_decay,
    detect_profile_conflicts,
    lifecycle_adjusted_priority,
)
from runner.mobiagent.personal_memory.store import PersonalMemoryStore
from runner.mobiagent.personal_memory.vector import LexicalSemanticMemory
from runner.mobiagent.profile_pipeline.schemas import ProfileItem, Relation, TodoItem, UserEvent


class PersonalMemorySchemaTests(unittest.TestCase):
    def test_raw_artifact_and_event_keep_multimodal_evidence(self) -> None:
        artifact = RawArtifact(
            artifact_id="raw_001",
            kind="screenshot",
            uri="runs/wechat/step-1.png",
            source="workflow",
            captured_at="2026-05-27T09:30:00",
            metadata={"app": "微信", "step_id": "1"},
        )
        event = NormalizedEvent(
            event_id="evt_chat_001",
            user_id="local_user",
            event_time="2026-05-27T09:30:05",
            app="微信",
            package_name="com.tencent.mm",
            event_type="chat_context",
            action="observe",
            summary="朋友提到周五吃火锅",
            entities={"date": ["周五"], "food": ["火锅"]},
            artifact_ids=[artifact.artifact_id],
            task_id="task_dinner",
            state="observed",
            confidence=0.78,
            privacy_level="sensitive_summary",
        )

        self.assertEqual(event.artifact_ids, ["raw_001"])
        self.assertEqual(event.entities["food"], ["火锅"])
        self.assertEqual(event.task_id, "task_dinner")

    def test_query_and_hit_support_agent_search(self) -> None:
        query = AgentMemoryQuery(
            intent="weekly_report",
            text="总结过去一周画像",
            time_start="2026-05-20T00:00:00",
            time_end="2026-05-27T23:59:59",
            apps=["微信", "淘宝"],
            event_types=["chat_context", "shopping_browse"],
            include_relations=True,
            include_cards=True,
            semantic_fallback=True,
            limit=5,
        )
        hit = MemoryHit(
            item_id="card_weekly",
            layer="card",
            text="本周出现聚餐和建材浏览两个主题",
            score=1.2,
            event_ids=["evt_chat_001", "evt_shop_001"],
            relation_ids=["rel_chat_to_shop"],
            metadata={"card_type": "weekly_summary"},
        )

        self.assertTrue(query.include_relations)
        self.assertTrue(query.semantic_fallback)
        self.assertEqual(hit.layer, "card")
        self.assertEqual(hit.relation_ids, ["rel_chat_to_shop"])

    def test_agent_memory_query_positional_limit_remains_compatible(self) -> None:
        query = AgentMemoryQuery(
            "lookup",
            "建材",
            None,
            None,
            [],
            [],
            [],
            [],
            [],
            True,
            False,
            True,
            False,
            25,
        )

        self.assertEqual(query.limit, 25)
        self.assertTrue(query.include_explanation)

    def test_relation_and_card_preserve_causal_trace(self) -> None:
        edge = RelationEdge(
            relation_id="rel_chat_to_shop",
            relation_type="causes",
            source_event_id="evt_chat_001",
            target_event_id="evt_shop_001",
            description="聊天邀约后出现火锅店搜索行为",
            confidence=0.72,
            evidence_event_ids=["evt_chat_001", "evt_shop_001"],
        )
        card = MemoryCard(
            card_id="card_dinner_plan",
            card_type="todo_candidate",
            title="聚餐计划候选",
            content="用户可能需要确认周五火锅聚餐地点。",
            event_ids=["evt_chat_001", "evt_shop_001"],
            relation_ids=[edge.relation_id],
            priority=0.83,
            status="active",
            privacy_level="derived",
        )

        self.assertEqual(edge.relation_type, "causes")
        self.assertEqual(card.relation_ids, ["rel_chat_to_shop"])
        self.assertEqual(card.status, "active")

    def test_card_and_hit_serialize_lifecycle_and_explanation_trace(self) -> None:
        card = MemoryCard(
            card_id="card_profile_food",
            card_type="profile",
            title="饮食偏好",
            content="用户喜欢火锅。",
            event_ids=["evt_hotpot"],
            relation_ids=["rel_hotpot"],
            priority=0.8,
            status="active",
            privacy_level="derived",
            created_at="2026-05-01T00:00:00",
            updated_at="2026-05-20T00:00:00",
            expires_at=None,
            lifecycle={"decay_factor": 0.9, "reinforcement": 0.1},
        )
        hit = MemoryHit(
            item_id="card_profile_food",
            layer="card",
            text="饮食偏好\n用户喜欢火锅。",
            score=0.9,
            event_ids=["evt_hotpot"],
            relation_ids=["rel_hotpot"],
            explanation_trace=[
                {
                    "stage": "card_match",
                    "reason": "Card text matched query",
                    "details": {"card_type": "profile"},
                }
            ],
        )

        self.assertEqual(card.to_dict()["created_at"], "2026-05-01T00:00:00")
        self.assertEqual(card.to_dict()["updated_at"], "2026-05-20T00:00:00")
        self.assertIsNone(card.to_dict()["expires_at"])
        self.assertEqual(card.to_dict()["lifecycle"]["decay_factor"], 0.9)
        self.assertEqual(hit.to_dict()["explanation_trace"][0]["stage"], "card_match")


class PersonalMemoryLifecycleTests(unittest.TestCase):
    def test_confidence_decay_reduces_old_memory(self) -> None:
        now = datetime.fromisoformat("2026-05-27T00:00:00")

        recent = apply_confidence_decay(0.9, "2026-05-26T00:00:00", now=now, half_life_days=30.0)
        old = apply_confidence_decay(0.9, "2026-04-27T00:00:00", now=now, half_life_days=30.0)

        self.assertGreater(recent.adjusted_confidence, old.adjusted_confidence)
        self.assertAlmostEqual(old.decay_factor, 0.5, places=2)

    def test_lifecycle_accepts_aware_timestamps_with_naive_now(self) -> None:
        now = datetime.fromisoformat("2026-05-27T00:00:00")

        decay = apply_confidence_decay(0.9, "2026-05-26T00:00:00+08:00", now=now)
        priority = lifecycle_adjusted_priority(
            base_priority=0.9,
            updated_at="2026-05-20T00:00:00+08:00",
            now=now,
            due_time="2026-05-25T00:00:00+08:00",
            status="open",
        )

        self.assertGreaterEqual(decay.days_since_update, 0.0)
        self.assertTrue(priority.expired)

    def test_profile_conflict_detection_for_hotpot_and_avoid_spicy(self) -> None:
        conflicts = detect_profile_conflicts(
            [
                {
                    "profile_id": "profile_hotpot_like",
                    "claim": "用户喜欢火锅，周末经常约朋友吃火锅。",
                    "category": "饮食偏好",
                },
                {
                    "profile_id": "profile_spicy_avoid",
                    "claim": "用户最近避免辛辣食物，偏好清淡饮食。",
                    "category": "饮食偏好",
                },
            ]
        )

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].profile_id, "profile_hotpot_like")
        self.assertEqual(conflicts[0].conflicting_profile_id, "profile_spicy_avoid")

    def test_expired_open_todo_priority_is_demoted(self) -> None:
        now = datetime.fromisoformat("2026-05-27T00:00:00")

        result = lifecycle_adjusted_priority(
            base_priority=0.9,
            updated_at="2026-05-20T00:00:00",
            now=now,
            due_time="2026-05-25T00:00:00",
            status="open",
        )

        self.assertTrue(result.expired)
        self.assertLess(result.priority_after_lifecycle, 0.5)


class PersonalMemoryCardTests(unittest.TestCase):
    def test_build_memory_cards_from_profiles_and_todos(self) -> None:
        profile = ProfileItem(
            profile_id="profile_food",
            category="饮食偏好",
            claim="用户近期出现火锅聚餐相关意图。",
            evidence_event_ids=["evt_chat_001"],
            confidence=0.81,
            time_range="2026-05-20/2026-05-27",
            service_eligible=True,
            privacy_level="derived",
        )
        todo = TodoItem(
            todo_id="todo_dinner",
            title="确认周五火锅地点",
            reason="聊天中出现聚餐时间和食物偏好，但缺少地点。",
            source_event_ids=["evt_chat_001"],
            priority="high",
            due_time="2026-05-29T18:00:00",
            status="open",
        )

        cards = build_memory_cards([profile], [todo], [])

        self.assertEqual(cards[0].card_type, "todo")
        self.assertEqual(cards[0].priority, 0.9)
        self.assertEqual(cards[1].card_type, "profile")
        self.assertIn("火锅", cards[1].content)

    def test_todo_and_profile_cards_with_same_source_id_do_not_collide_in_store(self) -> None:
        profile = ProfileItem(
            profile_id="shared",
            category="饮食偏好",
            claim="用户近期出现火锅聚餐相关意图。",
            evidence_event_ids=["evt_chat_001"],
            confidence=0.81,
            time_range="2026-05-20/2026-05-27",
            service_eligible=True,
            privacy_level="derived",
        )
        todo = TodoItem(
            todo_id="shared",
            title="确认周五火锅地点",
            reason="聊天中出现聚餐时间和食物偏好，但缺少地点。",
            source_event_ids=["evt_chat_001"],
            priority="high",
            due_time="2026-05-29T18:00:00",
            status="open",
        )
        cards = build_memory_cards([profile], [todo], [])

        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_cards(cards)

            hits = store.search(AgentMemoryQuery(intent="card_lookup", text="", include_events=False, limit=10))

        self.assertIn("card_todo_shared", [hit.item_id for hit in hits])
        self.assertIn("card_profile_shared", [hit.item_id for hit in hits])

    def test_weekly_summary_card_is_stable_for_reordered_inputs(self) -> None:
        profiles = [
            ProfileItem(
                profile_id="profile_b",
                category="饮食偏好",
                claim="用户近期出现火锅聚餐相关意图。",
                evidence_event_ids=["evt_chat_002"],
                confidence=0.81,
                time_range="2026-05-20/2026-05-27",
                service_eligible=True,
                privacy_level="derived",
            ),
            ProfileItem(
                profile_id="profile_a",
                category="购物偏好",
                claim="用户近期浏览建材商品。",
                evidence_event_ids=["evt_shop_001"],
                confidence=0.78,
                time_range="2026-05-20/2026-05-27",
                service_eligible=True,
                privacy_level="derived",
            ),
        ]
        todos = [
            TodoItem(
                todo_id="todo_b",
                title="确认周五火锅地点",
                reason="聊天中出现聚餐时间和食物偏好，但缺少地点。",
                source_event_ids=["evt_todo_b"],
                priority="high",
                due_time="2026-05-29T18:00:00",
                status="open",
            ),
            TodoItem(
                todo_id="todo_a",
                title="比较建材价格",
                reason="购物浏览中出现建材需求。",
                source_event_ids=["evt_todo_a"],
                priority="medium",
                due_time=None,
                status="open",
            ),
        ]
        relations = [
            RelationEdge(
                relation_id="rel_b",
                relation_type="causes",
                source_event_id="evt_chat_002",
                target_event_id="evt_todo_b",
                description="聊天后形成火锅地点待办",
                confidence=0.72,
                evidence_event_ids=["evt_chat_002", "evt_todo_b"],
            ),
            RelationEdge(
                relation_id="rel_a",
                relation_type="causes",
                source_event_id="evt_shop_001",
                target_event_id="evt_todo_a",
                description="购物浏览后形成价格比较待办",
                confidence=0.68,
                evidence_event_ids=["evt_shop_001", "evt_todo_a"],
            ),
        ]

        weekly = [card for card in build_memory_cards(profiles, todos, relations) if card.card_type == "weekly_summary"][0]
        reversed_weekly = [
            card
            for card in build_memory_cards(list(reversed(profiles)), list(reversed(todos)), list(reversed(relations)))
            if card.card_type == "weekly_summary"
        ][0]

        self.assertEqual(weekly.card_id, reversed_weekly.card_id)
        self.assertEqual(weekly.content, reversed_weekly.content)
        self.assertEqual(weekly.event_ids, reversed_weekly.event_ids)
        self.assertEqual(weekly.relation_ids, reversed_weekly.relation_ids)

    def test_cards_apply_lifecycle_conflicts_and_expired_todo_demotion(self) -> None:
        now = datetime.fromisoformat("2026-05-27T00:00:00")
        profiles = [
            ProfileItem(
                profile_id="profile_hotpot_like",
                category="饮食偏好",
                claim="用户喜欢火锅，周末经常约朋友吃火锅。",
                evidence_event_ids=["evt_hotpot_like"],
                confidence=0.9,
                time_range="2026-04-01/2026-04-30",
                service_eligible=True,
                updated_at="2026-04-27T00:00:00",
            ),
            ProfileItem(
                profile_id="profile_spicy_avoid",
                category="饮食偏好",
                claim="用户最近避免辛辣食物，偏好清淡饮食。",
                evidence_event_ids=["evt_spicy_avoid"],
                confidence=0.85,
                time_range="2026-05-20/2026-05-27",
                service_eligible=True,
                updated_at="2026-05-26T00:00:00",
            ),
        ]
        todos = [
            TodoItem(
                todo_id="todo_expired",
                title="确认火锅地点",
                reason="计划已经过期。",
                source_event_ids=["evt_hotpot_like"],
                priority="high",
                due_time="2026-05-25T00:00:00",
                status="open",
                updated_at="2026-05-20T00:00:00",
            )
        ]

        cards = build_memory_cards(profiles, todos, [], now=now)
        by_id = {card.card_id: card for card in cards}

        hotpot = by_id["card_profile_profile_hotpot_like"]
        avoid = by_id["card_profile_profile_spicy_avoid"]
        todo = by_id["card_todo_todo_expired"]

        self.assertIn("profile_spicy_avoid", hotpot.lifecycle["conflict_ids"])
        self.assertLess(hotpot.priority, 0.9)
        self.assertLess(avoid.priority, 0.85)
        self.assertTrue(todo.lifecycle["expired"])
        self.assertLess(todo.priority, 0.5)
        self.assertEqual(todo.expires_at, "2026-05-25T00:00:00")


class PersonalMemoryIngestTests(unittest.TestCase):
    def test_profile_event_converts_to_normalized_event(self) -> None:
        source = UserEvent(
            event_id="evt_chat_001",
            user_id="local_user",
            app="微信",
            package_name="com.tencent.mm",
            event_time="2026-05-27T09:30:05",
            source_run="run_wechat",
            source_step="2",
            evidence_paths=["runs/wechat/step-2.png"],
            event_type="chat_context",
            summary="朋友提到周五吃火锅",
            entities={"date": ["周五"], "food": ["火锅"]},
            confidence=0.78,
            privacy_level="sensitive_summary",
        )

        events, artifacts = events_from_profile_events([source])

        self.assertEqual(events[0].event_id, "evt_chat_001")
        self.assertEqual(events[0].artifact_ids, ["raw_evt_chat_001_0"])
        self.assertEqual(artifacts[0].uri, "runs/wechat/step-2.png")
        self.assertEqual(events[0].action, "observe")

    def test_profile_relation_converts_to_relation_edge(self) -> None:
        source = Relation(
            relation_id="rel_001",
            relation_type="causes",
            source_event_id="evt_chat_001",
            target_event_id="evt_shop_001",
            description="聊天后搜索火锅店",
            evidence_event_ids=["evt_chat_001", "evt_shop_001"],
            confidence=0.72,
        )

        edges = relations_from_profile_relations([source])

        self.assertEqual(edges[0].relation_id, "rel_001")
        self.assertEqual(edges[0].relation_type, "causes")
        self.assertEqual(edges[0].target_event_id, "evt_shop_001")

    def test_profile_event_artifact_kind_uses_file_extension_only(self) -> None:
        source = UserEvent(
            event_id="evt_files_001",
            user_id="local_user",
            app="文件",
            package_name="com.android.documentsui",
            event_time="2026-05-27T10:00:00",
            source_run="run_files",
            source_step="1",
            evidence_paths=[
                "archive/notes.md.backup",
                "runs/data.json",
                "runs/run_summary.json#steps.2.output.structured_output",
                "runs/screen.png#bbox",
                "runs/screen.jpg?x=1",
            ],
            event_type="file_context",
            summary="用户查看文件",
            entities={},
            confidence=0.8,
            privacy_level="derived",
        )

        _, artifacts = events_from_profile_events([source])

        self.assertEqual(
            [artifact.kind for artifact in artifacts],
            ["reference", "json", "json", "screenshot", "screenshot"],
        )


def _sample_artifact() -> RawArtifact:
    return RawArtifact(
        artifact_id="raw_shop_001",
        kind="screenshot",
        uri="runs/taobao/step-8.png",
        source="workflow",
        captured_at="2026-05-25T20:05:00",
        metadata={"app": "淘宝", "step_id": "8"},
    )


def _sample_event(event_id: str = "evt_shop_001", event_time: str = "2026-05-25T20:05:05") -> NormalizedEvent:
    return NormalizedEvent(
        event_id=event_id,
        user_id="local_user",
        event_time=event_time,
        app="淘宝",
        package_name="com.taobao.taobao",
        event_type="shopping_browse",
        action="observe",
        summary="用户浏览建材商品，价格信号为3.02元",
        entities={"product_categories": ["建材"], "price_signal": ["3.02"]},
        artifact_ids=["raw_shop_001"],
        task_id="task_shopping",
        state="observed",
        confidence=0.86,
        privacy_level="derived",
    )


class PersonalMemoryStoreTests(unittest.TestCase):
    def test_event_range_query_uses_structured_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_artifacts([_sample_artifact()])
            store.upsert_events([
                _sample_event("evt_old", "2026-05-01T08:00:00"),
                _sample_event("evt_recent", "2026-05-25T20:05:05"),
            ])

            hits = store.search(
                AgentMemoryQuery(
                    intent="range_lookup",
                    text="最近购物记录",
                    time_start="2026-05-20T00:00:00",
                    time_end="2026-05-27T23:59:59",
                    apps=["淘宝"],
                    event_types=["shopping_browse"],
                    include_cards=False,
                    limit=10,
                )
            )

            self.assertEqual([hit.item_id for hit in hits], ["evt_recent"])
            self.assertEqual(hits[0].layer, "event")

    def test_fts_retrieves_event_without_embedding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_artifacts([_sample_artifact()])
            store.upsert_events([_sample_event()])

            hits = store.search(
                AgentMemoryQuery(
                    intent="keyword_lookup",
                    text="建材",
                    include_cards=False,
                    limit=5,
                )
            )

            self.assertEqual(hits[0].item_id, "evt_shop_001")
            self.assertGreater(hits[0].score, 0)

    def test_card_search_respects_linked_event_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_artifacts([_sample_artifact()])
            store.upsert_events([
                _sample_event("evt_old", "2026-05-01T08:00:00"),
                _sample_event("evt_recent", "2026-05-25T20:05:05"),
            ])
            store.upsert_cards([
                MemoryCard(
                    card_id="card_old",
                    card_type="shopping_summary",
                    title="建材浏览摘要",
                    content="用户浏览建材商品。",
                    event_ids=["evt_old"],
                    relation_ids=[],
                    priority=0.95,
                    status="active",
                    privacy_level="derived",
                ),
                MemoryCard(
                    card_id="card_recent",
                    card_type="shopping_summary",
                    title="建材浏览摘要",
                    content="用户浏览建材商品。",
                    event_ids=["evt_recent"],
                    relation_ids=[],
                    priority=0.8,
                    status="active",
                    privacy_level="derived",
                ),
            ])

            hits = store.search(
                AgentMemoryQuery(
                    intent="card_range_lookup",
                    text="建材",
                    time_start="2026-05-20T00:00:00",
                    include_events=False,
                    include_cards=True,
                    limit=10,
                )
            )

            self.assertEqual([hit.item_id for hit in hits], ["card_recent"])

    def test_card_lifecycle_fields_are_persisted_and_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_cards([
                MemoryCard(
                    card_id="card_todo_expired",
                    card_type="todo",
                    title="过期待办",
                    content="已过期。 due_time=2026-05-25T00:00:00",
                    event_ids=["evt_due"],
                    relation_ids=[],
                    priority=0.35,
                    status="open",
                    privacy_level="derived",
                    created_at="2026-05-20T00:00:00",
                    updated_at="2026-05-20T00:00:00",
                    expires_at="2026-05-25T00:00:00",
                    lifecycle={"expired": True, "priority_before_lifecycle": 0.9},
                )
            ])

            hits = store.search(
                AgentMemoryQuery(
                    intent="todo_service",
                    text="过期待办",
                    include_events=False,
                    include_cards=True,
                    include_relations=False,
                )
            )

        self.assertEqual(hits[0].metadata["created_at"], "2026-05-20T00:00:00")
        self.assertEqual(hits[0].metadata["updated_at"], "2026-05-20T00:00:00")
        self.assertEqual(hits[0].metadata["expires_at"], "2026-05-25T00:00:00")
        self.assertTrue(hits[0].metadata["lifecycle"]["expired"])

    def test_search_migrates_legacy_card_schema_without_initialize(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE memory_cards (
                    card_id TEXT PRIMARY KEY,
                    card_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    event_ids_json TEXT NOT NULL,
                    relation_ids_json TEXT NOT NULL,
                    priority REAL NOT NULL,
                    status TEXT NOT NULL,
                    privacy_level TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE cards_fts USING fts5(
                    card_id UNINDEXED,
                    title,
                    content
                );
                """
            )
            conn.execute(
                """
                INSERT INTO memory_cards (
                    card_id, card_type, title, content, event_ids_json,
                    relation_ids_json, priority, status, privacy_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("card_legacy", "profile", "建材浏览摘要", "用户浏览建材商品。", "[]", "[]", 0.8, "active", "derived"),
            )
            conn.execute(
                "INSERT INTO cards_fts(card_id, title, content) VALUES (?, ?, ?)",
                ("card_legacy", "建材浏览摘要", "用户浏览建材商品。"),
            )
            conn.commit()
            conn.close()

            store = PersonalMemoryStore(db_path)
            hits = store.search(
                AgentMemoryQuery(intent="legacy", text="建材", include_events=False, include_cards=True)
            )

        self.assertEqual(hits[0].item_id, "card_legacy")
        self.assertIsNone(hits[0].metadata["created_at"])
        self.assertIsNone(hits[0].metadata["updated_at"])
        self.assertIsNone(hits[0].metadata["expires_at"])
        self.assertEqual(hits[0].metadata["lifecycle"], {})

    def test_task_resume_plan_falls_back_to_recent_candidates_when_text_misses(self) -> None:
        from runner.mobiagent.personal_memory.planner import plan_memory_query

        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([_sample_event("evt_recent", "2026-05-25T20:05:05")])
            store.upsert_cards([
                MemoryCard(
                    card_id="card_recent",
                    card_type="shopping_summary",
                    title="建材浏览摘要",
                    content="用户浏览建材商品。",
                    event_ids=["evt_recent"],
                    relation_ids=[],
                    priority=0.8,
                    status="active",
                    privacy_level="derived",
                )
            ])

            hits = store.search(plan_memory_query("继续上次那个"))

        self.assertTrue(hits)
        self.assertIn("evt_recent", [hit.item_id for hit in hits])

    def test_include_relations_query_returns_stored_relation_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([_sample_event("evt_shop_001", "2026-05-25T20:05:05")])
            store.upsert_relations([
                RelationEdge(
                    relation_id="rel_shop_need",
                    relation_type="behavior_causal",
                    source_event_id="evt_shop_001",
                    target_event_id=None,
                    description="浏览建材后形成近期购物需求线索",
                    confidence=0.74,
                    evidence_event_ids=["evt_shop_001"],
                )
            ])

            hits = store.search(
                AgentMemoryQuery(
                    intent="relation_lookup",
                    text="购物需求",
                    include_events=False,
                    include_cards=False,
                    include_relations=True,
                    limit=5,
                )
            )

        self.assertEqual([hit.item_id for hit in hits], ["rel_shop_need"])
        self.assertEqual(hits[0].layer, "relation")
        self.assertEqual(hits[0].event_ids, ["evt_shop_001"])
        self.assertEqual(hits[0].relation_ids, ["rel_shop_need"])
        self.assertEqual(hits[0].metadata["relation_type"], "behavior_causal")

    def test_planner_structured_query_can_return_relation_for_matching_linked_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([
                _sample_event("evt_old", "2026-05-01T08:00:00"),
                _sample_event("evt_recent", "2026-05-25T20:05:05"),
            ])
            store.upsert_relations([
                RelationEdge(
                    relation_id="rel_old",
                    relation_type="behavior_causal",
                    source_event_id="evt_old",
                    target_event_id=None,
                    description="旧浏览形成旧购物线索",
                    confidence=0.95,
                    evidence_event_ids=["evt_old"],
                ),
                RelationEdge(
                    relation_id="rel_recent",
                    relation_type="behavior_causal",
                    source_event_id="evt_recent",
                    target_event_id=None,
                    description="近期浏览形成购物线索",
                    confidence=0.7,
                    evidence_event_ids=["evt_recent"],
                ),
            ])

            hits = store.search(
                AgentMemoryQuery(
                    intent="weekly_report",
                    text="生成过去一周画像报告",
                    time_start="2026-05-20T00:00:00",
                    time_end="2026-05-27T23:59:59",
                    include_events=False,
                    include_cards=False,
                    include_relations=True,
                    limit=10,
                )
            )

        self.assertEqual([hit.item_id for hit in hits], ["rel_recent"])

    def test_search_hits_include_explanation_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([_sample_event("evt_recent", "2026-05-25T20:05:05")])
            store.upsert_relations([
                RelationEdge(
                    relation_id="rel_recent",
                    relation_type="behavior_causal",
                    source_event_id="evt_recent",
                    target_event_id=None,
                    description="近期浏览形成建材购物线索",
                    confidence=0.7,
                    evidence_event_ids=["evt_recent"],
                )
            ])
            store.upsert_cards([
                MemoryCard(
                    card_id="card_todo_shop",
                    card_type="todo",
                    title="复查建材购物需求",
                    content="浏览足迹显示用户可能仍需比较建材价格。 due_time=none",
                    event_ids=["evt_recent"],
                    relation_ids=["rel_recent"],
                    priority=0.9,
                    status="open",
                    privacy_level="derived",
                    lifecycle={"expired": False, "priority_after_lifecycle": 0.9},
                )
            ])

            hits = store.search(
                AgentMemoryQuery(
                    intent="todo_service",
                    text="建材",
                    time_start="2026-05-20T00:00:00",
                    apps=["淘宝"],
                    include_events=True,
                    include_cards=True,
                    include_relations=True,
                    limit=10,
                )
            )

        traces_by_id = {hit.item_id: hit.explanation_trace for hit in hits}
        self.assertTrue(traces_by_id["evt_recent"])
        self.assertTrue(traces_by_id["card_todo_shop"])
        self.assertTrue(traces_by_id["rel_recent"])
        self.assertIn("structured_filter", [item["stage"] for item in traces_by_id["evt_recent"]])
        self.assertIn("text_match", [item["stage"] for item in traces_by_id["card_todo_shop"]])
        self.assertIn("linked_event", [item["stage"] for item in traces_by_id["rel_recent"]])

    def test_search_can_disable_explanation_trace_for_low_latency_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([_sample_event("evt_recent", "2026-05-25T20:05:05")])

            hits = store.search(
                AgentMemoryQuery(
                    intent="fast_lookup",
                    text="建材",
                    include_cards=False,
                    include_relations=False,
                    include_explanation=False,
                )
            )

        self.assertEqual(hits[0].item_id, "evt_recent")
        self.assertEqual(hits[0].explanation_trace, [])

    def test_search_includes_explanation_trace_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([_sample_event("evt_recent", "2026-05-25T20:05:05")])

            hits = store.search(
                AgentMemoryQuery(
                    intent="explain_lookup",
                    text="建材",
                    include_cards=False,
                    include_relations=False,
                )
            )

        self.assertTrue(hits[0].explanation_trace)

    def test_relation_trace_omits_unapplied_privacy_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([_sample_event("evt_recent", "2026-05-25T20:05:05")])
            store.upsert_relations([
                RelationEdge(
                    relation_id="rel_recent",
                    relation_type="behavior_causal",
                    source_event_id="evt_recent",
                    target_event_id=None,
                    description="近期浏览形成购物线索",
                    confidence=0.7,
                    evidence_event_ids=["evt_recent"],
                )
            ])

            hits = store.search(
                AgentMemoryQuery(
                    intent="relation_lookup",
                    text="购物线索",
                    privacy_levels=["nonexistent"],
                    include_events=False,
                    include_cards=False,
                    include_relations=True,
                )
            )

        self.assertEqual([hit.item_id for hit in hits], ["rel_recent"])
        self.assertNotIn("structured_filter", [item["stage"] for item in hits[0].explanation_trace])

    def test_relation_trace_includes_privacy_when_linked_event_filters_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([
                _sample_event("evt_derived", "2026-05-25T20:05:05"),
                NormalizedEvent(
                    event_id="evt_raw",
                    user_id="local_user",
                    event_time="2026-05-25T20:05:05",
                    app="淘宝",
                    package_name="com.taobao.taobao",
                    event_type="shopping_browse",
                    action="observe",
                    summary="原始浏览记录",
                    entities={},
                    artifact_ids=[],
                    task_id="task_shopping",
                    state="observed",
                    confidence=0.8,
                    privacy_level="raw",
                ),
            ])
            store.upsert_relations([
                RelationEdge(
                    relation_id="rel_derived",
                    relation_type="behavior_causal",
                    source_event_id="evt_derived",
                    target_event_id=None,
                    description="derived relation",
                    confidence=0.7,
                    evidence_event_ids=["evt_derived"],
                )
            ])

            derived_hits = store.search(
                AgentMemoryQuery(
                    intent="relation_lookup",
                    text="",
                    time_start="2026-05-20T00:00:00",
                    privacy_levels=["derived"],
                    include_events=False,
                    include_cards=False,
                    include_relations=True,
                )
            )
            raw_hits = store.search(
                AgentMemoryQuery(
                    intent="relation_lookup",
                    text="",
                    time_start="2026-05-20T00:00:00",
                    privacy_levels=["raw"],
                    include_events=False,
                    include_cards=False,
                    include_relations=True,
                )
            )

        self.assertEqual([hit.item_id for hit in derived_hits], ["rel_derived"])
        self.assertEqual(raw_hits, [])
        structured = next(item for item in derived_hits[0].explanation_trace if item["stage"] == "structured_filter")
        self.assertEqual(structured["details"]["privacy_levels"], ["derived"])


class PersonalMemoryRelationTests(unittest.TestCase):
    def test_relation_lookup_returns_causal_neighbors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([
                _sample_event("evt_chat_001", "2026-05-25T19:00:00"),
                _sample_event("evt_shop_001", "2026-05-25T20:05:05"),
            ])
            store.upsert_relations([
                RelationEdge(
                    relation_id="rel_chat_to_shop",
                    relation_type="causes",
                    source_event_id="evt_chat_001",
                    target_event_id="evt_shop_001",
                    description="聊天邀约后出现购物搜索",
                    confidence=0.72,
                    evidence_event_ids=["evt_chat_001", "evt_shop_001"],
                )
            ])

            neighbors = store.relation_neighborhood("evt_chat_001", max_depth=1)

            self.assertEqual(neighbors[0].relation_id, "rel_chat_to_shop")
            self.assertEqual(neighbors[0].target_event_id, "evt_shop_001")

    def test_relation_lookup_orders_equal_confidence_by_relation_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalMemoryStore(Path(tmp) / "memory.db")
            store.initialize()
            store.upsert_events([
                _sample_event("evt_root", "2026-05-25T19:00:00"),
                _sample_event("evt_mid_a", "2026-05-25T19:01:00"),
                _sample_event("evt_mid_b", "2026-05-25T19:02:00"),
                _sample_event("evt_leaf_a", "2026-05-25T19:03:00"),
                _sample_event("evt_leaf_b", "2026-05-25T19:04:00"),
            ])
            store.upsert_relations([
                RelationEdge(
                    relation_id="rel_root_to_mid_a",
                    relation_type="causes",
                    source_event_id="evt_root",
                    target_event_id="evt_mid_a",
                    description="root to mid a",
                    confidence=0.72,
                    evidence_event_ids=["evt_root", "evt_mid_a"],
                ),
                RelationEdge(
                    relation_id="rel_root_to_mid_b",
                    relation_type="causes",
                    source_event_id="evt_root",
                    target_event_id="evt_mid_b",
                    description="root to mid b",
                    confidence=0.72,
                    evidence_event_ids=["evt_root", "evt_mid_b"],
                ),
                RelationEdge(
                    relation_id="rel_leaf_from_mid_a",
                    relation_type="causes",
                    source_event_id="evt_mid_a",
                    target_event_id="evt_leaf_a",
                    description="mid a to leaf a",
                    confidence=0.72,
                    evidence_event_ids=["evt_mid_a", "evt_leaf_a"],
                ),
                RelationEdge(
                    relation_id="rel_leaf_from_mid_b",
                    relation_type="causes",
                    source_event_id="evt_mid_b",
                    target_event_id="evt_leaf_b",
                    description="mid b to leaf b",
                    confidence=0.72,
                    evidence_event_ids=["evt_mid_b", "evt_leaf_b"],
                ),
            ])

            relation_ids = [
                relation.relation_id
                for relation in store.relation_neighborhood("evt_root", max_depth=2)
            ]

            self.assertEqual(
                relation_ids,
                [
                    "rel_leaf_from_mid_a",
                    "rel_leaf_from_mid_b",
                    "rel_root_to_mid_a",
                    "rel_root_to_mid_b",
                ],
            )


class PersonalMemoryVectorFallbackTests(unittest.TestCase):
    def test_lexical_semantic_memory_returns_fuzzy_hits_without_remote_embedding(self) -> None:
        memory = LexicalSemanticMemory()
        memory.index(
            [
                MemoryHit(
                    item_id="evt_food",
                    layer="event",
                    text="朋友约周五吃火锅并讨论地点",
                    score=0.8,
                    event_ids=["evt_food"],
                ),
                MemoryHit(
                    item_id="evt_bike",
                    layer="event",
                    text="用户查看共享单车订单",
                    score=0.8,
                    event_ids=["evt_bike"],
                ),
            ]
        )

        hits = memory.search("火锅 地点", limit=1)

        self.assertEqual(hits[0].item_id, "evt_food")
        self.assertEqual(hits[0].metadata["semantic_backend"], "lexical")

    def test_lexical_semantic_memory_splits_general_punctuation(self) -> None:
        memory = LexicalSemanticMemory()
        memory.index(
            [
                MemoryHit(
                    item_id="evt_punctuation",
                    layer="event",
                    text="alpha;beta foo/bar 火锅！地点",
                    score=0.8,
                    event_ids=["evt_punctuation"],
                )
            ]
        )

        for query in ["beta", "bar", "地点"]:
            with self.subTest(query=query):
                hits = memory.search(query, limit=1)
                self.assertEqual(hits[0].item_id, "evt_punctuation")

    def test_lexical_semantic_memory_splits_underscore(self) -> None:
        memory = LexicalSemanticMemory()
        memory.index(
            [
                MemoryHit(
                    item_id="evt_underscore",
                    layer="event",
                    text="foo_bar",
                    score=0.8,
                    event_ids=["evt_underscore"],
                )
            ]
        )

        hits = memory.search("bar", limit=1)

        self.assertEqual(hits[0].item_id, "evt_underscore")

    def test_lexical_semantic_memory_keeps_duplicate_item_vectors_separate(self) -> None:
        memory = LexicalSemanticMemory()
        memory.index(
            [
                MemoryHit(
                    item_id="evt_duplicate",
                    layer="event",
                    text="alpha only",
                    score=0.8,
                    event_ids=["evt_duplicate_alpha"],
                ),
                MemoryHit(
                    item_id="evt_duplicate",
                    layer="event",
                    text="gamma only",
                    score=0.8,
                    event_ids=["evt_duplicate_gamma"],
                ),
            ]
        )

        hits = memory.search("gamma", limit=5)

        self.assertEqual([hit.text for hit in hits], ["gamma only"])

    def test_lexical_semantic_memory_matches_ascii_case_insensitively(self) -> None:
        memory = LexicalSemanticMemory()
        memory.index(
            [
                MemoryHit(
                    item_id="evt_case",
                    layer="event",
                    text="Alpha Beta",
                    score=0.8,
                    event_ids=["evt_case"],
                )
            ]
        )

        hits = memory.search("alpha", limit=1)

        self.assertEqual(hits[0].item_id, "evt_case")


from runner.mobiagent.personal_memory.planner import plan_memory_query


class PersonalMemoryPlannerTests(unittest.TestCase):
    def test_weekly_report_uses_range_and_cards_without_vector_first(self) -> None:
        query = plan_memory_query("生成过去一周画像报告")

        self.assertEqual(query.intent, "weekly_report")
        self.assertTrue(query.include_events)
        self.assertTrue(query.include_cards)
        self.assertTrue(query.include_relations)
        self.assertFalse(query.semantic_fallback)

    def test_ambiguous_task_uses_semantic_fallback_after_structured_search(self) -> None:
        query = plan_memory_query("继续上次那个")

        self.assertEqual(query.intent, "task_resume")
        self.assertTrue(query.include_events)
        self.assertTrue(query.include_cards)
        self.assertTrue(query.semantic_fallback)

    def test_plain_last_week_lookup_is_not_weekly_report(self) -> None:
        query = plan_memory_query("查一下上周五吃火锅的地点")

        self.assertNotEqual(query.intent, "weekly_report")
        self.assertTrue(query.semantic_fallback)


from runner.mobiagent.personal_memory.cli import _apply_limit, build_parser, main


class PersonalMemoryCliTests(unittest.TestCase):
    def test_cli_parser_accepts_build_and_search(self) -> None:
        parser = build_parser()
        build_args = parser.parse_args([
            "build",
            "--db",
            "memory.db",
            "--events",
            "events.json",
            "--profiles",
            "profile.jsonl",
            "--todos",
            "todos.jsonl",
        ])
        search_args = parser.parse_args(["search", "--db", "memory.db", "--query", "过去一周画像"])

        self.assertEqual(build_args.command, "build")
        self.assertEqual(build_args.db, "memory.db")
        self.assertEqual(build_args.profiles, "profile.jsonl")
        self.assertEqual(build_args.todos, "todos.jsonl")
        self.assertEqual(search_args.command, "search")
        self.assertEqual(search_args.query, "过去一周画像")

    def test_cli_build_and_search_accept_profile_jsonl_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "memory.db"
            events_path = tmp_path / "events.jsonl"
            relations_path = tmp_path / "relations.jsonl"
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_id": "evt_chat_jsonl",
                                "user_id": "local_user",
                                "app": "微信",
                                "package_name": "com.tencent.mm",
                                "event_time": "2026-05-27T09:30:05",
                                "source_run": "run_chat",
                                "source_step": "2",
                                "evidence_paths": ["runs/wechat/step-2.png"],
                                "event_type": "chat_context",
                                "summary": "朋友提到周五吃火锅",
                                "entities": {"food": ["火锅"]},
                                "confidence": 0.78,
                                "privacy_level": "sensitive_summary",
                            },
                            ensure_ascii=False,
                        ),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            relations_path.write_text(
                json.dumps(
                    {
                        "relation_id": "rel_jsonl",
                        "relation_type": "causes",
                        "source_event_id": "evt_chat_jsonl",
                        "target_event_id": None,
                        "description": "聊天中出现火锅计划",
                        "evidence_event_ids": ["evt_chat_jsonl"],
                        "confidence": 0.72,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            build_stdout = io.StringIO()
            with contextlib.redirect_stdout(build_stdout):
                build_code = main(
                    ["build", "--db", str(db_path), "--events", str(events_path), "--relations", str(relations_path)]
                )

            search_stdout = io.StringIO()
            with contextlib.redirect_stdout(search_stdout):
                search_code = main(["search", "--db", str(db_path), "--query", "火锅"])

            search_payload = json.loads(search_stdout.getvalue())

        self.assertEqual(build_code, 0)
        self.assertEqual(search_code, 0)
        self.assertEqual(json.loads(build_stdout.getvalue())["status"], "built")
        self.assertIn("evt_chat_jsonl", [hit["item_id"] for hit in search_payload["hits"]])
        self.assertIn("explanation_trace", search_payload["hits"][0])
        self.assertTrue(search_payload["hits"][0]["explanation_trace"])

    def test_cli_build_with_profiles_and_todos_writes_searchable_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "memory.db"
            events_path = tmp_path / "events.jsonl"
            profiles_path = tmp_path / "profiles.jsonl"
            todos_path = tmp_path / "todos.jsonl"
            events_path.write_text(json.dumps(_sample_event().to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")
            profiles_path.write_text(
                json.dumps(
                    ProfileItem(
                        profile_id="profile_shop",
                        category="购物偏好",
                        claim="用户近期浏览建材商品。",
                        evidence_event_ids=["evt_shop_001"],
                        confidence=0.82,
                        time_range="2026-05-20/2026-05-27",
                        service_eligible=True,
                    ).to_dict(),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            todos_path.write_text(
                json.dumps(
                    TodoItem(
                        todo_id="todo_shop",
                        title="复查建材购物需求",
                        reason="浏览足迹显示用户可能仍需比较建材价格。",
                        source_event_ids=["evt_shop_001"],
                        priority="high",
                        due_time=None,
                        status="candidate",
                    ).to_dict(),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "build",
                    "--db",
                    str(db_path),
                    "--events",
                    str(events_path),
                    "--profiles",
                    str(profiles_path),
                    "--todos",
                    str(todos_path),
                ])

            store = PersonalMemoryStore(db_path)
            hits = store.search(
                AgentMemoryQuery(
                    intent="cards",
                    text="建材",
                    include_events=False,
                    include_cards=True,
                    limit=10,
                )
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["cards"], 3)
        self.assertIn("card_todo_todo_shop", [hit.item_id for hit in hits])
        self.assertTrue(any(hit.metadata["card_type"] == "weekly_summary" for hit in hits))

    def test_cli_search_limit_preserves_planner_default_unless_explicit(self) -> None:
        parser = build_parser()

        default_args = parser.parse_args(["search", "--db", "memory.db", "--query", "过去一周画像"])
        explicit_args = parser.parse_args(
            ["search", "--db", "memory.db", "--query", "过去一周画像", "--limit", "7"]
        )

        self.assertIsNone(default_args.limit)
        self.assertEqual(_apply_limit(plan_memory_query(default_args.query), default_args.limit).limit, 30)
        self.assertEqual(_apply_limit(plan_memory_query(explicit_args.query), explicit_args.limit).limit, 7)


if __name__ == "__main__":
    unittest.main()

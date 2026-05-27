from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()

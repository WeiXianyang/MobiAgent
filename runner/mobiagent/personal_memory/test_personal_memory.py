from __future__ import annotations

import unittest

from runner.mobiagent.personal_memory.schemas import (
    AgentMemoryQuery,
    MemoryCard,
    MemoryHit,
    NormalizedEvent,
    RawArtifact,
    RelationEdge,
)


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


if __name__ == "__main__":
    unittest.main()

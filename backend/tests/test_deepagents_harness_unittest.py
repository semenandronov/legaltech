import asyncio
import unittest
from typing import Any, Dict

from deepagents.middleware.permissions import FilesystemPermission

from unittest.mock import patch

from app.services.workflows.deepagents_harness import (
    WHITELIST_TOOLS,
    WorkflowDeepAgentsContext,
    WorkflowDeepAgentsHarness,
)
from app.config import config
from app.services.workflows.deepagents_stream_bridge import stream_parts_to_events


class _DummyToolResult:
    def __init__(self, *, success: bool, data: Dict[str, Any], output_summary: str):
        self.success = success
        self.data = data
        self.error = None
        self.output_summary = output_summary
        self.artifacts = []
        self.llm_calls = 0
        self.tokens_used = 0


class _FakeToolRegistry:
    def __init__(self):
        self.calls = []

    async def execute_tool(self, *, tool_name: str, params: Dict[str, Any], context: Dict[str, Any]):
        self.calls.append({"tool_name": tool_name, "params": params, "context": context})
        return _DummyToolResult(success=True, data={"ok": True}, output_summary=f"{tool_name} ok")


class DeepAgentsHarnessTests(unittest.TestCase):
    def test_whitelist_is_exact(self):
        self.assertEqual(
            WHITELIST_TOOLS,
            [
                "rag",
                "summarize",
                "extract_entities",
                "tabular_review",
                "playbook_check",
                "legal_db",
                "document_draft",
            ],
        )

    def test_build_tools_returns_7_tools(self):
        harness = WorkflowDeepAgentsHarness(
            tool_registry=_FakeToolRegistry(),
            ctx=WorkflowDeepAgentsContext(user_id="u1", case_id=None, execution_id="e1", previous_results={}),
        )
        tools = harness.build_tools()
        self.assertEqual(len(tools), 7)
        self.assertEqual({t.name for t in tools}, set(WHITELIST_TOOLS))

    def test_tool_proxy_calls_registry(self):
        fake = _FakeToolRegistry()
        harness = WorkflowDeepAgentsHarness(
            tool_registry=fake,
            ctx=WorkflowDeepAgentsContext(user_id="u1", case_id="c1", execution_id="e1", previous_results={}),
        )
        rag_tool = next(t for t in harness.build_tools() if t.name == "rag")

        async def _run():
            result = await rag_tool.ainvoke({"query": "q", "file_ids": ["f1"], "top_k": 3})
            return result

        out = asyncio.run(_run())
        self.assertTrue(out["success"])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["tool_name"], "rag")
        self.assertEqual(fake.calls[0]["params"]["query"], "q")

    def test_build_subagents_has_expected_roles_and_scopes(self):
        harness = WorkflowDeepAgentsHarness(
            tool_registry=_FakeToolRegistry(),
            ctx=WorkflowDeepAgentsContext(user_id="u1", case_id=None, execution_id="e1", previous_results={}),
        )
        subagents = harness.build_subagents()
        self.assertEqual([s["name"] for s in subagents], ["research", "analysis", "draft", "review"])
        # tool scopes should stay role-focused
        research_tools = {t.name for t in subagents[0]["tools"]}
        draft_tools = {t.name for t in subagents[2]["tools"]}
        self.assertIn("legal_db", research_tools)
        self.assertIn("document_draft", draft_tools)
        self.assertNotIn("document_draft", research_tools)

    def test_configured_skills_and_memory_from_env_like_config(self):
        harness = WorkflowDeepAgentsHarness(
            tool_registry=_FakeToolRegistry(),
            ctx=WorkflowDeepAgentsContext(user_id="u1", case_id=None, execution_id="e1", previous_results={}),
        )
        old_skills = config.WORKFLOW_DEEPAGENTS_SKILLS_PATHS
        old_memory = config.WORKFLOW_DEEPAGENTS_MEMORY_PATHS
        try:
            config.WORKFLOW_DEEPAGENTS_SKILLS_PATHS = "/skills/legal,/skills/review"
            config.WORKFLOW_DEEPAGENTS_MEMORY_PATHS = "/memories/AGENTS.md"
            self.assertEqual(
                harness._configured_skills(),
                ["/skills/legal", "/skills/review"],
            )
            self.assertEqual(
                harness._configured_memory(),
                ["/memories/AGENTS.md"],
            )
        finally:
            config.WORKFLOW_DEEPAGENTS_SKILLS_PATHS = old_skills
            config.WORKFLOW_DEEPAGENTS_MEMORY_PATHS = old_memory

    def test_configured_interrupt_on_filters_unknown_tools(self):
        harness = WorkflowDeepAgentsHarness(
            tool_registry=_FakeToolRegistry(),
            ctx=WorkflowDeepAgentsContext(user_id="u1", case_id=None, execution_id="e1", previous_results={}),
        )
        old_interrupt = config.WORKFLOW_DEEPAGENTS_INTERRUPT_ON_TOOLS
        try:
            config.WORKFLOW_DEEPAGENTS_INTERRUPT_ON_TOOLS = "document_draft,unknown_tool,rag"
            self.assertEqual(
                harness._configured_interrupt_on(),
                {"document_draft": True, "rag": True},
            )
        finally:
            config.WORKFLOW_DEEPAGENTS_INTERRUPT_ON_TOOLS = old_interrupt

    def test_permissions_policy_uses_deny_by_default(self):
        harness = WorkflowDeepAgentsHarness(
            tool_registry=_FakeToolRegistry(),
            ctx=WorkflowDeepAgentsContext(user_id="u1", case_id=None, execution_id="e1", previous_results={}),
        )
        old_enabled = config.WORKFLOW_DEEPAGENTS_PERMISSIONS_ENABLED
        old_read = config.WORKFLOW_DEEPAGENTS_ALLOWED_READ_PATHS
        old_write = config.WORKFLOW_DEEPAGENTS_ALLOWED_WRITE_PATHS
        try:
            config.WORKFLOW_DEEPAGENTS_PERMISSIONS_ENABLED = True
            config.WORKFLOW_DEEPAGENTS_ALLOWED_READ_PATHS = "/memories,/tmp"
            config.WORKFLOW_DEEPAGENTS_ALLOWED_WRITE_PATHS = "/memories"
            policy = harness._build_permissions()
            self.assertIsNotNone(policy)
            self.assertIsInstance(policy, list)
            self.assertTrue(all(isinstance(r, FilesystemPermission) for r in policy))
            self.assertEqual(policy[-1].mode, "deny")
            read_rule = policy[0]
            self.assertEqual(read_rule.operations, ["read"])
            self.assertEqual(read_rule.paths, ["/memories/**", "/tmp/**"])
            write_rule = policy[1]
            self.assertEqual(write_rule.operations, ["write"])
            self.assertEqual(write_rule.paths, ["/memories/**"])
        finally:
            config.WORKFLOW_DEEPAGENTS_PERMISSIONS_ENABLED = old_enabled
            config.WORKFLOW_DEEPAGENTS_ALLOWED_READ_PATHS = old_read
            config.WORKFLOW_DEEPAGENTS_ALLOWED_WRITE_PATHS = old_write

    def test_create_agent_passes_middleware_instances(self):
        harness = WorkflowDeepAgentsHarness(
            tool_registry=_FakeToolRegistry(),
            ctx=WorkflowDeepAgentsContext(user_id="u1", case_id=None, execution_id="e1", previous_results={}),
        )
        captured: dict = {}

        def _fake_create_deep_agent(**kwargs):
            captured.update(kwargs)
            return object()

        old_mw = config.WORKFLOW_DEEPAGENTS_MIDDLEWARE
        try:
            # TodoListMiddleware is built into deepagents; extra layers use presets (e.g. tool_retry).
            config.WORKFLOW_DEEPAGENTS_MIDDLEWARE = "tool_retry"
            with patch("deepagents.create_deep_agent", side_effect=_fake_create_deep_agent):
                harness.create_agent(system_prompt="test", model=None, checkpointer=None)
        finally:
            config.WORKFLOW_DEEPAGENTS_MIDDLEWARE = old_mw

        mw = captured.get("middleware")
        self.assertIsNotNone(mw)
        self.assertIsInstance(mw, list)
        self.assertTrue(all(not isinstance(x, str) for x in mw))


class DeepAgentsBridgeTests(unittest.TestCase):
    def test_bridge_emits_agent_todos_from_updates(self):
        async def _parts():
            yield {
                "type": "updates",
                "ns": (),
                "data": {
                    "agent": {
                        "todos": [
                            {"content": "Собрать нормы", "status": "in_progress"},
                            {"content": "Синтез", "status": "pending"},
                        ]
                    }
                },
            }

        async def _types():
            out = []
            async for ev in stream_parts_to_events(execution_id="e1", parts=_parts()):
                out.append(ev.event_type)
            return out

        event_types = asyncio.run(_types())
        self.assertIn("agent_todos_updated", event_types)

    def test_bridge_emits_step_events_from_custom(self):
        async def _parts():
            yield {"type": "custom", "ns": (), "data": {"type": "tool_started", "tool": "rag", "params_preview": {}}}
            yield {
                "type": "custom",
                "ns": (),
                "data": {
                    "type": "tool_completed",
                    "tool": "rag",
                    "success": True,
                    "output_summary": "ok",
                    "result": {"success": True, "data": {"x": 1}},
                },
            }

        async def _collect():
            evs = []
            async for ev in stream_parts_to_events(execution_id="e1", parts=_parts()):
                evs.append(ev.event_type)
            return evs

        event_types = asyncio.run(_collect())
        # planning_started always first
        self.assertIn("planning_started", event_types[0])
        self.assertIn("tool_reasoned", event_types)
        self.assertIn("step_started", event_types)
        self.assertIn("step_completed", event_types)


if __name__ == "__main__":
    unittest.main()


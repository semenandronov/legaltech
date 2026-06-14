"""Draft document creation lives in draft_agent, not chat_graph draft_node."""
from __future__ import annotations

import ast
from pathlib import Path


def test_chat_graph_has_no_draft_node():
    path = Path(__file__).resolve().parents[1] / "app/services/langchain_agents/graphs/chat_graph.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert "draft_node" not in names
    assert "generate_draft_plan_node" not in names


def test_draft_agent_writer_module_exists():
    path = Path(__file__).resolve().parents[1] / "app/services/draft_agent/writer.py"
    assert path.is_file()

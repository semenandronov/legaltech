"""Offline eval runner smoke tests."""

import json
import asyncio
from types import SimpleNamespace

import pytest

from app.services.evals.langfuse_eval_runner import run_offline_eval


def test_run_offline_eval_requires_array(tmp_path):
    file_path = tmp_path / "dataset.json"
    file_path.write_text(json.dumps({"bad": "shape"}), encoding="utf-8")

    with pytest.raises(ValueError):
        asyncio.run(run_offline_eval(str(file_path)))


def test_run_offline_eval_entity_metrics(monkeypatch, tmp_path):
    dataset = [
        {
            "id": "case-1",
            "question": "Какие судьи вели дело?",
            "reference": "Иванов И.И.",
            "eval_type": "entity",
            "token_cost": 1.25,
            "expected_clause_ids": ["c1", "c2"],
            "retrieved_clause_ids": ["c1"],
        }
    ]
    file_path = tmp_path / "dataset.json"
    file_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")

    class DummyLLM:
        async def ainvoke(self, _question: str):
            return SimpleNamespace(content="В документах отсутствуют сведения о судье.")

    monkeypatch.setattr(
        "app.services.evals.langfuse_eval_runner.create_legal_llm",
        lambda **_kwargs: DummyLLM(),
    )
    monkeypatch.setattr(
        "app.services.evals.langfuse_eval_runner.create_trace_context",
        lambda **_kwargs: SimpleNamespace(trace_id="trace-1"),
    )
    monkeypatch.setattr(
        "app.services.evals.langfuse_eval_runner.end_trace",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.evals.langfuse_eval_runner.record_score",
        lambda **_kwargs: None,
    )

    report = asyncio.run(run_offline_eval(str(file_path)))
    assert report["entity_cases"] == 1
    assert report["entity_false_negative"] == 1
    assert report["false_negative_rate_entity"] == 1.0
    assert report["avg_token_cost"] == 1.25
    assert report["clause_precision"] == 1.0
    assert report["clause_recall"] == 0.5
    assert report["clause_f1"] == pytest.approx(0.6667, abs=1e-4)

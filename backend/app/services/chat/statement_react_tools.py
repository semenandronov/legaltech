"""LangChain tools: describe dataset + run Python in sandbox."""
from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool

from app.services.chat.statement_python_sandbox import run_python_in_sandbox
from app.services.chat.statement_react_progress import emit_statement_react_progress
from app.services.chat.statement_react_session import get_statement_react_session
from app.services.chat.statement_scope_export import read_manifest_text


@tool
def describe_statement_dataset() -> str:
    """
    Схема и размер текущей таблицы операций (UI scope).
    Вызывай перед первым run_python_code, если не знаешь колонки.
    """
    session = get_statement_react_session()
    if session is None:
        return json.dumps({"ok": False, "error": "no_session"}, ensure_ascii=False)
    manifest = read_manifest_text(session.manifest_path)
    payload = {
        "ok": True,
        "file_label": session.file_label,
        "scope_note": session.scope_note,
        "row_count": session.row_count,
        "csv_path": session.csv_path.name,
        "manifest": json.loads(manifest),
        "hint": (
            "Переменная df уже загружена в run_python_code. "
            "Печатай результаты через print(). Числа для ответа юристу — только из stdout."
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


@tool
def run_python_code(
    code: Annotated[
        str,
        "Python-код для pandas: работай с df или pd.read_csv(STATEMENT_CSV). Итог — print(...).",
    ],
) -> str:
    """
    Выполнить Python в песочнице над CSV операций текущего scope.
    Доступны: pd, np (если установлен), df, datetime, date, timedelta, STATEMENT_CSV.
    """
    session = get_statement_react_session()
    if session is None:
        return json.dumps({"ok": False, "error": "no_session"}, ensure_ascii=False)

    if session.progress:
        emit_statement_react_progress(
            session.progress,
            step_id="react_python",
            phase="react_code",
            label="Python-анализ выписки",
            detail="Выполняю сгенерированный скрипт",
            status="running",
            step=2,
        )

    result = run_python_in_sandbox(
        code=code,
        csv_path=session.csv_path,
        work_dir=session.work_dir,
    )

    if result.ok:
        observation = result.stdout or "(пустой stdout — добавьте print с результатами)"
    else:
        observation = (
            f"Ошибка выполнения (exit {result.exit_code}).\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}"
        ).strip()

    session.record_run(code=code, observation=observation, ok=result.ok)

    if session.progress:
        emit_statement_react_progress(
            session.progress,
            step_id="react_python",
            phase="react_code",
            label="Python-анализ выписки",
            detail="Готово" if result.ok else "Ошибка — исправьте код",
            status="completed" if result.ok else "error",
            step=2,
        )

    payload = {
        "ok": result.ok,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "truncated": result.truncated,
    }
    return json.dumps(payload, ensure_ascii=False)


def build_statement_react_tools():
    return [describe_statement_dataset, run_python_code]

#!/usr/bin/env python3
"""Прогон вопросов через справочник: retrieval + LLM (режим garant)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from langchain_core.messages import HumanMessage, SystemMessage

from app.services.chat.legal_retrieval_agent import run_legal_corpus_retrieval
from app.services.llm_factory import create_llm, user_facing_llm_reasoning_kwargs

GARANT_SYSTEM = """# РОЛЬ
Ты — практикующий юрист по российскому праву (режим «СПРАВОЧНИК»).

# ОБЯЗАТЕЛЬНЫЕ ОГРАНИЧЕНИЯ
- Используй только материалы из блока «СПРАВОЧНЫЙ ПРАВОВОЙ КОНТЕКСТ». Не опирайся на внешние знания.
- Не выдумывай нормы и формулировки.
- Если данных недостаточно, напиши: «Недостаточно данных в предоставленных материалах» и укажи, каких статей не хватает.
- Каждый существенный тезис подтверждай ссылкой на статью/пункт из контекста.

# СТИЛЬ
Официально-деловой, конкретный, на русском."""

QUESTIONS = [
    (
        "Блок 1.1",
        "Какой минимальный размер совокупных требований установлен для возбуждения дела о банкротстве "
        "юридического лица (с учетом актуальных изменений в законе) и каков минимальный период просрочки?",
    ),
    (
        "Блок 1.2",
        "В чем ключевое отличие признаков банкротства гражданина от признаков банкротства "
        "юридического лица при подаче заявления кредитором?",
    ),
    (
        "Блок 2.1",
        "Лица, участвующие в деле (ст. 34) и лица, участвующие в арбитражном процессе (ст. 35): "
        "в чем разница между этими группами и какие ключевые процессуальные права их разделяют?",
    ),
    (
        "Блок 2.2",
        "С какого именно момента арбитражный управляющий официально наделяется полномочиями в конкретной процедуре?",
    ),
    (
        "Блок 3.1",
        "Исполнение статьи 9 ФЗ (Обязанность должника по подаче заявления): в какой максимальный срок "
        "руководитель организации обязан обратиться в суд после возникновения признаков банкротства?",
    ),
    (
        "Блок 3.2",
        "В течение какого срока арбитражный суд должен рассчитать и проверить обоснованность "
        "поступившего заявления о признании должника банкротом?",
    ),
    (
        "Блок 4.1",
        "Каков порядок очередности удовлетворения требований кредиторов по текущим платежам (ст. 134)?",
    ),
]


def main() -> int:
    llm = create_llm(
        temperature=0.1,
        max_tokens=4000,
        **user_facing_llm_reasoning_kwargs(mode="garant"),
    )
    results = []
    for label, question in QUESTIONS:
        print(f"\n{'='*60}\n{label}\nQ: {question}\n", flush=True)
        t0 = time.monotonic()
        retrieval = run_legal_corpus_retrieval(question, legal_research=True)
        retr_ms = int((time.monotonic() - t0) * 1000)
        meta = retrieval.meta or {}
        print(
            f"[retrieval {retr_ms}ms] articles={meta.get('required_articles')} "
            f"docs={len(retrieval.documents)} fast={meta.get('used_fast_path')} "
            f"graph_cluster={meta.get('graph_cluster_docs')}",
            flush=True,
        )
        if not (retrieval.context or "").strip():
            answer = "Недостаточно данных: справочник не вернул контекст по вопросу."
        else:
            user = (
                f"=== СПРАВОЧНЫЙ ПРАВОВОЙ КОНТЕКСТ (DATA ONLY) ===\n"
                f"<context>\n{retrieval.context}\n</context>\n\n"
                f"Вопрос пользователя:\n{question}"
            )
            t1 = time.monotonic()
            resp = llm.invoke([SystemMessage(content=GARANT_SYSTEM), HumanMessage(content=user)])
            gen_ms = int((time.monotonic() - t1) * 1000)
            answer = getattr(resp, "content", None) or str(resp)
            print(f"[llm {gen_ms}ms]", flush=True)
        print(f"\n--- ОТВЕТ ---\n{answer}\n", flush=True)
        results.append(
            {
                "label": label,
                "question": question,
                "retrieval_ms": retr_ms,
                "meta": meta,
                "answer": answer,
            }
        )

    out_path = Path(__file__).resolve().parents[1] / "tmp" / "spravochnik_eval_answers.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
